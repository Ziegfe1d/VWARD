#!/usr/bin/env python3
"""Narrow reads of Keenetic's configuration (owner 08.11: a whole read took 5.5-12.7 s on the Viva,
the subtrees 0.04-0.13 s). vward_keenetic_part prints a part as running-config lines from its RCI
subtree, proven against the whole configuration at its first use in a boot; a difference (twice)
or a failed RCI read: the whole configuration, as before. sh and BusyBox."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"
SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

FULL = """system
    hostname Viva
!
object-group fqdn domain-list0
    description Telegram
    include t.me
    include telegram.org
!
object-group fqdn domain-list4
    description "Claude AI"
    include claude.ai
!
dns-proxy
    filter profile DnsProfile0
    route object-group domain-list0 OpkgTun4 auto
    route object-group domain-list4 OpkgTun4 auto
    https upstream https://doh.example/q dnsm on ISP domain ai.example
!
ip name-server 192.168.1.1:65053 "" on Bridge0
ip name-server 8.8.8.8 youtube.com on OpkgTun4
ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto
"""
RCI = {
    "object-group/fqdn": {"domain-list0": {"description": "Telegram", "include": [{"address": "t.me"}, {"address": "telegram.org"}]},
                          "domain-list4": {"description": "Claude AI", "include": [{"address": "claude.ai"}]}},
    "dns-proxy": {"filter": {"profile": [{"name": "DnsProfile0"}]},
                  "route": [{"object-group": "domain-list0", "interface": "OpkgTun4", "auto": True},
                            {"object-group": "domain-list4", "interface": "OpkgTun4", "auto": True}],
                  "https": {"upstream": [{"url": "https://doh.example/q", "format": "dnsm", "on": "ISP", "domain": "ai.example"}]}},
    "ip/name-server": [{"address": "192.168.1.1", "port": 65053, "interface": "Bridge0"},
                       {"address": "8.8.8.8", "domain": "youtube.com", "interface": "OpkgTun4"}],
    "ip/route": [{"network": "8.8.8.0", "mask": "255.255.255.0", "interface": "OpkgTun4", "auto": True}],
}


def fail(message: str) -> None:
    raise SystemExit(f"KEENETIC_PARTS=FAIL: {message}")


for sh in SHELLS:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "rci").mkdir()
        for k, v in RCI.items():
            (t / "rci" / k.replace("/", "_")).write_text(json.dumps(v))
        (t / "full").write_text(FULL)
        (t / "curl").write_text(f'''#!/bin/sh
for a; do u=$a; done
p=${{u#*/rci/}}; p=$(echo "$p" | tr / _)
echo "$p" >> "{t}/rci.log"
[ -e "{t}/rci-down" ] && exit 7
cat "{t}/rci/$p"
''')
        (t / "ndmc").write_text(f'#!/bin/sh\necho x >> "{t}/full.log"\ncat "{t}/full"\n')
        for f in ("curl", "ndmc"):
            (t / f).chmod(0o755)
        env = {"PATH": "/usr/bin:/bin", "VWARD_CURL_BIN": str(t / "curl"), "VWARD_NDMC": str(t / "ndmc"),
               "VWARD_JQ_BIN": shutil.which("jq"), "VWARD_KPART": str(t / "kpart"), "VWARD_KCACHE": str(t / "kc"),
               "VWARD_KEENETIC_SLOW_LOG": str(t / "slow.log"), "VWARD_KEENETIC_CALLS": str(t / "calls"),
               "VWARD_KEENETIC_SLOWN": str(t / "slown"), "VWARD_KEENETIC_LAST": str(t / "last"), "VWARD_RCI_CALLS": str(t / "rcic")}

        def run(script):
            r = subprocess.run(sh + ["-c", f'. "{LIB}"; {script}'], env=env, text=True, capture_output=True, timeout=60)
            return r.returncode, r.stdout

        def count(f):
            p = t / f
            return len(p.read_text().splitlines()) if p.exists() else 0

        # First use: proven against the whole configuration, then the narrow answer.
        rc, out = run("vward_keenetic_parts groups dnsproxy nameservers iproutes")
        for want in ("object-group fqdn domain-list4", "    include claude.ai", "    route object-group domain-list0 OpkgTun4 auto",
                     "    https upstream https://doh.example/q dnsm on ISP domain ai.example",
                     "ip name-server 192.168.1.1:65053 on Bridge0", "ip name-server 8.8.8.8 youtube.com on OpkgTun4",
                     "ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto"):
            if want not in out.splitlines():
                fail(f"{sh} narrow parts: {want!r} missing in {out!r}")
        if "hostname" in out or not all((t / "kpart" / f"{p}.ok").exists() for p in ("groups", "dnsproxy", "nameservers", "iproutes")):
            fail(f"{sh} only the parts, each proven: {out!r}")
        whole_reads = count("full.log")
        # Proven: no whole read any more.
        rc, out = run("vward_keenetic_part groups; vward_keenetic_part nameservers")
        if count("full.log") != whole_reads or "include t.me" not in out:
            fail(f"{sh} a proven part reads only its subtree")
        # The consumers' parsers see the same lines as in the whole configuration.
        rc, a = run("vward_keenetic_part dnsproxy | awk '/^[^ \\t!]/ {c = ($1 == \"dns-proxy\")} c && $1 == \"route\" {print $3, $4}'")
        if a.split("\n")[:2] != ["domain-list0 OpkgTun4", "domain-list4 OpkgTun4"]:
            fail(f"{sh} dns-proxy routes as the agents parse them: {a!r}")
        # RCI down: the whole configuration, once, nothing lost.
        (t / "rci-down").touch()
        rc, out = run("vward_keenetic_parts groups nameservers")
        if out.count("object-group fqdn domain-list0") != 1 or "hostname Viva" not in out:
            fail(f"{sh} RCI down: the whole configuration once: {out!r}")
        (t / "rci-down").unlink()
        # A part that differs from the whole configuration (twice): whole until the next boot.
        shutil.rmtree(t / "kpart")
        bad = dict(RCI["ip/name-server"][1]); bad["domain"] = "other.example"
        (t / "rci/ip_name-server").write_text(json.dumps([RCI["ip/name-server"][0], bad]))
        rc, out = run("vward_keenetic_parts nameservers")
        if "hostname Viva" not in out or not (t / "kpart/nameservers.bad").exists():
            fail(f"{sh} a differing part is not trusted: {out!r}")
        before = count("rci.log")
        rc, out = run("vward_keenetic_parts nameservers")
        if count("rci.log") != before or "hostname Viva" not in out:
            fail(f"{sh} a part found different is read whole until the next boot")
        rc, out = run("VWARD_KEENETIC_NARROW=0 vward_keenetic_parts groups")
        if "hostname Viva" not in out:
            fail(f"{sh} VWARD_KEENETIC_NARROW=0: always whole")
print("KEENETIC_PARTS=PASS")
