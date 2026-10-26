#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "components/policy-sync/scripts/vward-policy-audit.sh"
RECONCILE = ROOT / "components/policy-sync/scripts/vward-policy-reconcile.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def extract_function(source: str, name: str) -> str:
    pattern = rf"(?ms)^{re.escape(name)}\(\)\n\{{\n.*?^\}}\n"
    match = re.search(pattern, source)
    if not match:
        fail(f"missing shell function: {name}")
    return match.group(0)


def run_shell(script: str, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write("#!/bin/sh\nset -u\n")
        handle.write(script)
        path = handle.name
    try:
        return subprocess.run(
            ["/bin/sh", path, *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
    finally:
        os.unlink(path)


audit_source = AUDIT.read_text(encoding="utf-8")
reconcile_source = RECONCILE.read_text(encoding="utf-8")

for name, source in (("audit", audit_source), ("reconcile", reconcile_source)):
    if 'sed -n "/^object-group fqdn $' in source:
        fail(f"{name} still contains prefix-based FQDN group parsing")

    group_members = extract_function(source, "group_members")

    fixture = """\
dns-proxy
    route object-group domain-list1 nwg1
    route object-group domain-list10 nwg1
    route object-group domain-list11 nwg1
!
object-group fqdn domain-list1
    description Youtube
    include youtube.com
!
object-group fqdn domain-list10
    description GGSEL
    include ggsel.net
!
object-group fqdn domain-list11
    description Supercell
    include clashmini.com
    include supercellstore.com
!
"""

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as cfg:
        cfg.write(fixture)
        cfg_path = cfg.name

    try:
        result = run_shell(
            group_members
            + '\ngroup_members domain-list1 "$1"\n'
            + 'printf "%s\\n" "---"\n'
            + 'group_members domain-list11 "$1"\n',
            [cfg_path],
        )
    finally:
        os.unlink(cfg_path)

    if result.returncode != 0:
        fail(f"{name} group parser execution failed: {result.stderr.strip()}")

    expected = "youtube.com\n---\nclashmini.com\nsupercellstore.com\n"
    if result.stdout != expected:
        fail(f"{name} group isolation mismatch: {result.stdout!r}")

ndm_cmd = extract_function(reconcile_source, "ndm_cmd")
group_members = extract_function(reconcile_source, "group_members")
membership_state = extract_function(reconcile_source, "membership_state")

if "no such entry" not in ndm_cmd:
    fail("ndm_cmd does not reject Keenetic 'no such entry' semantic errors")
if '"$ROLLBACK" \\\n        "$POSTSAVE"' not in reconcile_source:
    fail("cleanup does not include POSTSAVE in the rm command")

with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    fake_ndmc = td_path / "ndmc"

    fake_ndmc.write_text(
        "#!/bin/sh\n"
        "echo 'Network::ObjectGroup: domain-list1: no such entry: clashmini.com'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ndmc.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{td}:{env.get('PATH', '')}"

    result = run_shell(ndm_cmd + '\nndm_cmd "test command"\n', [], env)
    if result.returncode == 0:
        fail("ndm_cmd accepted semantic error with process rc=0")

    fake_ndmc.write_text("#!/bin/sh\necho 'ok'\nexit 0\n", encoding="utf-8")
    fake_ndmc.chmod(0o755)

    result = run_shell(ndm_cmd + '\nndm_cmd "test command"\n', [], env)
    if result.returncode != 0:
        fail("ndm_cmd rejected a successful command")

    fixture = td_path / "running-config"
    fixture.write_text(
        "object-group fqdn domain-list1\n"
        "    include youtube.com\n"
        "!\n"
        "object-group fqdn domain-list11\n"
        "    include clashmini.com\n"
        "!\n",
        encoding="utf-8",
    )

    fake_ndmc.write_text(
        "#!/bin/sh\n"
        f"cat '{fixture}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ndmc.chmod(0o755)

    # Running configuration comes through the shared profile helper (RCI, then ndmc).
    profile_source = (ROOT / "components/runtime/lib/vward-device-profile.sh").read_text(encoding="utf-8")
    env["VWARD_CURL_BIN"] = "/nonexistent/curl"
    # The timing of every request to Keenetic (fix.33.2) is not what this test looks at.
    functions = "\n".join(("vward_uptime_cs() { _VCS=0; }\nvward_keenetic_timed() { :; }",
                           extract_function(profile_source, "vward_tool"),
                           extract_function(profile_source, "vward_running_config"),
                           group_members, membership_state))

    result = run_shell(functions + '\nmembership_state domain-list1 clashmini.com\n', [], env)
    if result.returncode != 1:
        fail(f"membership_state falsely found clashmini.com in domain-list1: rc={result.returncode}")

    result = run_shell(functions + '\nmembership_state domain-list11 clashmini.com\n', [], env)
    if result.returncode != 0:
        fail(f"membership_state missed clashmini.com in domain-list11: rc={result.returncode}")

# Only public subnets reach the tunnel: a home, provider or reserved range there would take the
# router's own answers too (an SSH session from the internet). The filter of build_catalog, run.
sync_source = (ROOT / "components/policy-sync/scripts/vward-policy-sync.sh").read_text(encoding="utf-8")
m = re.search(r"awk -F'\[\./\]' '(.*?)' \"\$FILE\"", sync_source, re.S)
if not m:
    fail("build_catalog has no filter of reserved ranges")
sample = "8.8.8.0/24\n10.0.0.0/8\n192.168.1.0/24\n100.64.0.0/10\n1.2.3.4/32\n0.0.0.0/0\n172.0.0.0/8\n172.20.0.0/16\nfoo\n224.0.0.0/4\n91.108.4.0/22\n1.0.0.0/7\n300.1.1.0/24\n"
kept = subprocess.run(["awk", "-F[./]", m.group(1)], input=sample, text=True, capture_output=True).stdout.split()
if kept != ["8.8.8.0/24", "1.2.3.4/32", "91.108.4.0/22"]:
    fail(f"reserved, private or too wide subnets pass the filter: {kept}")

# A route to one address Keenetic already has (shown without its mask) is not added and saved
# again every hour.
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    (t / "catalog").mkdir(); (t / "work").mkdir()
    (t / "catalog/google.cidr").write_text("74.125.247.128/32\n8.8.8.0/24\n")
    (t / "cats").write_text("google\n")
    (t / "running").write_text("ip route 74.125.247.128 OpkgTun2 auto\nip route 8.8.8.0 255.255.255.0 OpkgTun2 auto\n")
    (t / "owned").write_text("74.125.247.128/32\n8.8.8.0/24\n")
    script = "\n".join((extract_function(sync_source, "prefix_mask"), extract_function(sync_source, "route_line"),
                        extract_function(sync_source, "reconcile_routes"))) + f"""
log() {{ :; }}
ndm() {{ echo "$*" >> "{t}/ndm.log"; }}
WORK="{t}/work"; CATALOG="{t}/catalog"; OWNED="{t}/owned"; OWNED_DEVICE="{t}/owned-device"; ACTIVE="{t}/active"
SHRINK_PENDING="{t}/shrink.pending"; LAST_GOOD="{t}/last-good"; LISTS_CONF="{t}/lists.conf"
RT=OpkgTun2; WG=OpkgTun2
reconcile_routes "{t}/running" "{t}/cats"
"""
    r = run_shell(script, [])
    if r.returncode != 0 or (t / "ndm.log").exists() or "ADDED=0" not in r.stdout or "CONFIG_SAVE=NOT_NEEDED" not in r.stdout:
        fail(f"a /32 route Keenetic shows without its mask is added and saved again: {r.stdout} {r.stderr}")

print("POLICY_SYNC_SAFETY=PASS")
