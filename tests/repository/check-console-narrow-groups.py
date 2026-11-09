#!/usr/bin/env python3
"""Panel domain edits read only Keenetic's domain lists (owner 08.11: «домен в список» 9 s on the
Viva = two whole configurations): route_group_change and op_list_domain take the object-group RCI
subtree when it is proven (vward_keenetic_part groups) and never «show running-config"; when the
part is not available, the whole configuration as before. Runs the helper's own functions (sh and
BusyBox) with stand-ins for ndmc and the device profile."""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HELPER = os.path.join(ROOT, "components/console/scripts/vward-console-config.sh")
text = open(HELPER).read()


def fn(name):
    m = re.search(r"\n(%s\(\) \{\n.*?\n\})\n" % re.escape(name), text, re.S)
    if not m:
        sys.exit(f"CONSOLE_NARROW_GROUPS=FAIL: no function {name}")
    return m.group(1)


body = "\n".join(fn(n) for n in ("snapshot", "snapshot_groups", "in_group", "group_set", "route_group_change"))
if "snapshot_groups" not in fn("op_list_domain") or re.search(r"\n\s+snapshot\n", fn("op_list_domain")):
    sys.exit("CONSOLE_NARROW_GROUPS=FAIL: op_list_domain reads the whole configuration")

shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])
with tempfile.TemporaryDirectory() as t:
    state = os.path.join(t, "groups")
    ndmc = os.path.join(t, "ndmc")
    with open(ndmc, "w") as f:
        f.write(f"""#!/bin/sh
echo "$2" >> {t}/ndmc.log
case "$2" in
  'show running-config') printf 'object-group fqdn Mine\\n' ; cat {state}; printf '!\\n' ;;
  'object-group fqdn Mine include '*) echo "    include ${{2##* }}" >> {state} ;;
  'no object-group fqdn Mine include '*) grep -vx "    include ${{2##* }}" {state} > {state}.n; mv {state}.n {state} ;;
esac
""")
    os.chmod(ndmc, 0o755)
    for sh in shells:
        for narrow in (True, False):
            open(state, "w").close()
            if os.path.exists(f"{t}/ndmc.log"):
                os.remove(f"{t}/ndmc.log")
            part = (f'vward_keenetic_part() {{ [ "$1" = groups ] || return 2; echo RCI >> {t}/rci.log; '
                    f'printf "object-group fqdn Mine\\n"; cat {state}; printf "!\\n"; }}') if narrow else \
                "vward_keenetic_part() { return 3; }"
            script = f"""RUNCFG= NDMC={ndmc}
die() {{ echo "DIE $1"; exit 9; }}
ndm() {{ "$NDMC" -c "$1" >/dev/null; }}
config_snapshot_valid() {{ grep -q '^object-group' "$1"; }}
{part}
{body}
route_group_change Mine example.com add; echo "rc=$?"
route_group_change Mine example.com add; echo "rc=$?"
route_group_change Mine example.com remove; echo "rc=$?"
"""
            r = subprocess.run(sh + ["-c", script], capture_output=True, text=True)
            log = open(f"{t}/ndmc.log").read().splitlines() if os.path.exists(f"{t}/ndmc.log") else []
            full = log.count("show running-config")
            if r.stdout.split() != ["rc=0", "rc=3", "rc=0"]:
                sys.exit(f"CONSOLE_NARROW_GROUPS=FAIL: {sh[0]} narrow={narrow}: {r.stdout!r} {r.stderr!r}")
            if narrow and full:
                sys.exit(f"CONSOLE_NARROW_GROUPS=FAIL: {sh[0]}: {full} whole reads with the part proven")
            if not narrow and full != 5:
                sys.exit(f"CONSOLE_NARROW_GROUPS=FAIL: {sh[0]}: fallback must read the whole config ({full})")
# The VPN guard's list fallback and lost sweep, and the r6 check, take parts too (owner 08.11).
for path, want in (("components/tunnel-guard/scripts/vward-tunnel-guard.sh", ("vward_keenetic_parts dnsproxy;", "vward_keenetic_parts dnsproxy iproutes;")),
                   ("components/tunnel-guard/scripts/vward-tunnel-health.sh", ("vward_keenetic_part nameservers",))):
    src = open(os.path.join(ROOT, path)).read()
    for w in want:
        if w not in src:
            sys.exit(f"CONSOLE_NARROW_GROUPS=FAIL: {path}: no narrow read {w!r}")
print("CONSOLE_NARROW_GROUPS=PASS")
