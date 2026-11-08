#!/usr/bin/env python3
"""Owner 08.11: no VWARD script and not the Go routing core ever writes into Keenetic's DNS
filter or its profiles («dns-proxy filter ...», «filter profile ...») or removes the whole
dns-proxy that holds them.

1. Dynamic: the generic write wrappers (Panel ndm, policy-sync ndm, policy-reconcile ndm_cmd)
   refuse such a command without starting ndmc; an ordinary command still goes through.
2. Static: the guard is in every generic wrapper (also ndm_secret and the B executor's
   vrl_native_exec), and no source sends such a command literally.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD = "*' dns-proxy filter'*|*' dns-proxy no filter'*|*' filter profile '*|' no dns-proxy ')"
WRAPPERS = [
    ("components/console/scripts/vward-console-config.sh", "ndm() {", "}"),
    ("components/console/scripts/vward-console-config.sh", "ndm_secret() {", "}"),
    ("components/policy-sync/scripts/vward-policy-sync.sh", "ndm()\n{", "}"),
    ("components/policy-sync/scripts/vward-policy-reconcile.sh", "ndm_cmd()\n{", "}"),
    ("components/runtime/lib/vward-routing-live.sh", "vrl_native_exec() (", ")"),
]
BAD = [
    "dns-proxy filter profile DnsProfile0 tls upstream 1.1.1.1",
    "dns-proxy no filter engine",
    "dns-proxy filter engine public",
    "no dns-proxy filter profile DnsProfile0",
    "no dns-proxy",
    "ip hotspot host 00:11:22:33:44:55 filter profile DnsProfile0",
]
GOOD = "dns-proxy no https upstream https://smart.example/x dnsm on ISP domain chatgpt.com"
fails = []


def body(path, start, end):
    text = open(os.path.join(ROOT, path)).read()
    i = text.find("\n" + start)
    if i < 0:
        return None
    j = text.find("\n" + end + "\n", i + 1)
    return text[i + 1:j + len(end) + 2] if j > 0 else None


for path, start, end in WRAPPERS:
    b = body(path, start, end)
    if b is None or GUARD not in b:
        fails.append(f"{path}: {start.split()[0]} has no DNS filter guard")

with tempfile.TemporaryDirectory() as tmp:
    log = os.path.join(tmp, "calls")
    fake = os.path.join(tmp, "ndmc")
    with open(fake, "w") as f:
        f.write('#!/bin/sh\nprintf "%s\\n" "$2" >> "' + log + '"\nexit 0\n')
    os.chmod(fake, 0o755)
    for path, start, end in WRAPPERS[:1] + WRAPPERS[2:4]:
        name = start.split("(")[0]
        b = body(path, start, end)
        if b is None:
            continue
        script = "log() { :; }\nNDMC=%s\nVWARD_ROOT_PREFIX=%s\n%s\n" % (fake, tmp, b)
        for cmd in BAD + [GOOD]:
            if os.path.exists(log):
                os.remove(log)
            r = subprocess.run(["sh", "-c", script + '%s "$1"' % name, "sh", cmd],
                               env={"PATH": tmp + ":/usr/bin:/bin"}, capture_output=True, text=True)
            sent = os.path.exists(log)
            if cmd == GOOD and (r.returncode != 0 or not sent):
                fails.append(f"{path} {name}: ordinary command not sent (rc={r.returncode})")
            if cmd != GOOD and (r.returncode == 0 or sent):
                fails.append(f"{path} {name}: {cmd!r} not refused (rc={r.returncode}, sent={sent})")

# Literal sends anywhere in the sources (shell, Panel, Go core), the guards themselves excepted.
lit = re.compile(r"(ndmc\b|\bndm\b|ndm_cmd|ndm_secret|\"parse\"|Cmd:).*(dns-proxy (no )?filter|filter profile)")
for top in ("components", "web", "tools/vward-core"):
    for dp, _, files in os.walk(os.path.join(ROOT, top)):
        for fn in files:
            if not fn.endswith((".sh", ".cgi", ".js", ".go")) or fn.endswith("_test.go"):
                continue
            p = os.path.join(dp, fn)
            for n, line in enumerate(open(p, errors="replace"), 1):
                if GUARD in line or line.lstrip().startswith(("#", "//")):
                    continue
                if lit.search(line):
                    fails.append(f"{os.path.relpath(p, ROOT)}:{n}: sends into the DNS filter")

if fails:
    print("FAIL check-dns-filter-no-write:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("PASS check-dns-filter-no-write (%d wrappers, %d forms)" % (len(WRAPPERS), len(BAD)))
