#!/usr/bin/env python3
"""DNS of the whole home network goes through AdGuard Home.

A stand-in for iptables keeps the tables in a JSON file (chains, rules, packet
counters) and answers -N/-F/-X/-A/-I/-D/-C/-L like the real one; Keenetic's
firewall rebuild is a wipe of that file.  Stand-ins for netstat (AdGuard Home's
DNS port), curl (Keenetic's host list, AdGuard Home's API) and the Ads control
script (the DoH list) complete the router.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh"

FAKE_IPTABLES = r'''#!/usr/bin/env python3
import json, sys, os
from pathlib import Path
p = Path(os.environ["FAKE_FW"])
fw = json.loads(p.read_text()) if p.exists() else {}
with open(str(p) + ".log", "a") as f: f.write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
table = "filter"
if a[:1] == ["-t"]: table, a = a[1], a[2:]
t = fw.setdefault(table, {"PREROUTING": [], "FORWARD": []} if True else {})
t.setdefault("PREROUTING", []); t.setdefault("FORWARD", [])
op, chain, rest = a[0], a[1], a[2:]
def save(): p.write_text(json.dumps(fw)); sys.exit(0)
def spec(r): return " ".join(r)
if "REJECT" in rest and os.environ.get("FAKE_NO_REJECT") == "1": sys.exit(1)
if op == "-N":
    if chain in t: sys.exit(1)
    t[chain] = []; save()
if chain not in t: sys.exit(1)
if op == "-F": t[chain] = []; save()
if op == "-X":
    if t[chain] or any("-j " + chain in r["spec"] for c in t.values() for r in c): sys.exit(1)
    del t[chain]; save()
if op == "-A": t[chain].append({"spec": spec(rest), "pkts": 0}); save()
if op == "-I":
    pos = 1
    if rest and rest[0].isdigit(): pos, rest = int(rest[0]), rest[1:]
    t[chain].insert(pos - 1, {"spec": spec(rest), "pkts": 0}); save()
if op in ("-D", "-C"):
    for i, r in enumerate(t[chain]):
        if r["spec"] == spec(rest):
            if op == "-D": del t[chain][i]; save()
            sys.exit(0)
    sys.exit(1)
if op == "-L":
    print("Chain %s (1 references)" % chain)
    print("    pkts      bytes target     prot opt in     out     source               destination")
    for r in t[chain]:
        w = r["spec"].split(); tgt = w[w.index("-j") + 1]
        print("%8d %10d %-10s all  --  *      *       0.0.0.0/0            0.0.0.0/0" % (r["pkts"], r["pkts"] * 60, tgt))
    sys.exit(0)
sys.exit(2)
'''

FAKE_CURL = r'''#!/usr/bin/env python3
import json, sys, os
from pathlib import Path
st = json.loads(Path(os.environ["FAKE_ROUTER"]).read_text())
args = sys.argv[1:]
if "-K" in args: sys.stdin.read()
url = [a for a in args if a.startswith("http")][-1]
out = args[args.index("-o") + 1] if "-o" in args else None
def reply(obj):
    if out: Path(out).write_text(json.dumps(obj))
    else: print(json.dumps(obj))
    sys.exit(0)
if "/rci/show/ip/hotspot" in url:
    if st.get("rci_down"): sys.exit(7)
    reply({"host": st["hosts"]})
if url.endswith("/control/filtering/status"):
    reply({"enabled": True, "filters": st["filters"]})
sys.exit(22)
'''

FAKE_NETSTAT = r'''#!/bin/sh
[ "$(cat "$FAKE_AGH_UP")" = 1 ] || exit 0
echo "udp        0      0 192.168.1.1:65053       0.0.0.0:*                           1234/AdGuardHome"
'''

FAKE_CONTROL = r'''#!/bin/sh
echo "$*" >> "$FAKE_CONTROL_LOG"
echo "CONTROL=PASS"
'''

FAKE_PROFILE = r'''
vward_profile_load() {
    VWARD_LAN_ADDRESS=192.168.1.1
    VWARD_LAN_SUBNET=192.168.1.0/24
    VWARD_ADGUARD_CONFIG=$FAKE_AGH_YAML
}
'''

YAML = """dns:
  bind_hosts:
    - 192.168.1.1
  port: 65053
  upstream_dns:
    - '[/chatgpt.com/]https://smart.example/dns-query/k'
    - {up}
  upstream_mode: parallel
"""


def fail(msg):
    raise SystemExit(f"ADS_DNS_GUARD=FAIL: {msg}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bindir = tmp / "bin"; bindir.mkdir()
    for name, body in (("iptables", FAKE_IPTABLES), ("curl", FAKE_CURL), ("netstat", FAKE_NETSTAT), ("control", FAKE_CONTROL)):
        f = bindir / name; f.write_text(body); f.chmod(0o755)
    (tmp / "profile.sh").write_text(FAKE_PROFILE)
    etc = tmp / "etc"; etc.mkdir()
    auth = etc / "agh-api.auth"; auth.write_text("admin:pw\n"); auth.chmod(0o600)
    lib = (ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh").read_text()
    patched = tmp / "lib.sh"
    patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    (tmp / "root/tmp").mkdir(parents=True)
    fw, router, yaml, up = tmp / "fw.json", tmp / "router.json", tmp / "agh.yaml", tmp / "agh-up"
    hooks = tmp / "netfilter.d"
    ROUTER = {"hosts": [
        {"name": "Work laptop", "mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.50", "active": True},
        {"name": "TV", "mac": "aa:bb:cc:dd:ee:02", "ip": "192.168.1.60", "active": True}], "filters": []}
    env = os.environ | {
        "VWARD_ADS_LIB": str(patched), "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(tmp / "state"),
        "VWARD_ADS_LOG_DIR": str(tmp / "log"), "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(bindir / "curl"),
        "VWARD_ADS_AGH_AUTH_FILE": str(auth), "AGH_API_BASE": "http://192.0.2.1:3001/control",
        "VWARD_ADS_DEVICE_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_RCI_BASE": "http://rci/rci",
        "VWARD_IPTABLES": str(bindir / "iptables"), "VWARD_NETSTAT": str(bindir / "netstat"),
        "VWARD_ADS_CONTROL_BIN": str(bindir / "control"), "VWARD_NETFILTER_DIR": str(hooks),
        "VWARD_DNS_GUARD_STATE": str(tmp / "guard.state"), "VWARD_DNS_GUARD_LOCK": str(tmp / "guard.lock"),
        "VWARD_DNS_GUARD_BIN": "/opt/bin/vward-ads-privacy-dns-guard.sh",
        "VWARD_DOH_IPS": "1.1.1.1 8.8.8.8",
        "FAKE_FW": str(fw), "FAKE_ROUTER": str(router), "FAKE_AGH_YAML": str(yaml), "FAKE_AGH_UP": str(up),
        "FAKE_CONTROL_LOG": str(tmp / "control.log"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "TMPDIR": str(tmp),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

    def run(*args, shell=("sh",), extra=None):
        return subprocess.run([*shell, str(GUARD), *args], env=env | (extra or {}), text=True, capture_output=True, timeout=60)

    def tables():
        return json.loads(fw.read_text()) if fw.exists() else {}

    def chain(table, name):
        return [r["spec"] for r in tables().get(table, {}).get(name, [])]

    def status():
        return dict(l.split("=", 1) for l in run("status").stdout.splitlines() if "=" in l)

    for shell in shells:
        for f in (fw, tmp / "guard.state", etc / "dns-guard.conf", tmp / "control.log", tmp / "fw.json.log"):
            f.unlink(missing_ok=True)
        shutil.rmtree(hooks, ignore_errors=True)
        router.write_text(json.dumps(ROUTER)); up.write_text("1")

        # A plain way out of AdGuard Home: nothing can be switched on.
        yaml.write_text(YAML.format(up="9.9.9.10"))
        r = run("set", "enforce", "1", shell=shell)
        if r.returncode == 0 or "upstream_not_encrypted" not in r.stdout or (etc / "dns-guard.conf").exists():
            fail(f"{shell[0]} plain upstream must refuse: {r.stdout}")
        if status()["upstream"] != "plain":
            fail("status must say the way out is plain")

        # Encrypted: every LAN DNS query goes to AdGuard Home, the router's own ones stay.
        yaml.write_text(YAML.format(up="https://dns.quad9.net/dns-query"))
        r = run("set", "enforce", "1", shell=shell)
        if r.returncode != 0 or "DNS_GUARD=PASS" not in r.stdout:
            fail(f"{shell[0]} enforce: {r.stdout} {r.stderr[-300:]}")
        pre = chain("nat", "PREROUTING")
        if pre[:2] != ["-s 192.168.1.0/24 -p tcp --dport 53 -j VWARD_DNS", "-s 192.168.1.0/24 -p udp --dport 53 -j VWARD_DNS"]:
            fail(f"{shell[0]} PREROUTING jumps: {pre}")
        if chain("nat", "VWARD_DNS") != ["-d 192.168.1.1 -j RETURN", "-j DNAT --to-destination 192.168.1.1:65053"]:
            fail(f"{shell[0]} redirect chain: {chain('nat', 'VWARD_DNS')}")
        hook = (hooks / "060-vward-dns-guard.sh").read_text()
        if '"/opt/bin/vward-ads-privacy-dns-guard.sh" hook "$table"' not in hook or not os.access(hooks / "060-vward-dns-guard.sh", os.X_OK):
            fail(f"{shell[0]} netfilter hook: {hook}")
        if chain("filter", "FORWARD"):
            fail("bypass is off: nothing in FORWARD")

        # The same settings again: no firewall call at all.
        before = len((tmp / "fw.json.log").read_text().splitlines())
        run("tick", shell=shell)
        after = (tmp / "fw.json.log").read_text().splitlines()
        if any(l.split()[:1] in (["-A"], ["-I"], ["-F"], ["-D"]) or l.startswith("-t nat -A") or l.startswith("-t nat -I") for l in after[before:]):
            fail(f"{shell[0]} an unchanged tick rewrote rules: {after[before:]}")

        # An excluded device (by MAC, whatever the case) keeps its own DNS.
        r = run("set", "exclude", "AA:BB:CC:DD:EE:01", shell=shell)
        if chain("nat", "VWARD_DNS")[0] != "-s 192.168.1.50 -j RETURN" or "aa:bb:cc:dd:ee:01" not in (etc / "dns-guard.conf").read_text():
            fail(f"{shell[0]} exclusion: {chain('nat', 'VWARD_DNS')} {r.stdout}")
        if run("set", "exclude", "not-a-mac", shell=shell).returncode == 0:
            fail("a bad MAC must be refused")

        # No way around: DoT/DoQ and DoH addresses refused, the DoH list in AdGuard Home.
        r = run("set", "bypass", "1", shell=shell)
        fwd = chain("filter", "VWARD_DNS_FWD")
        want = ["-s 192.168.1.50 -j RETURN",
                "-p tcp --dport 853 -j REJECT --reject-with tcp-reset", "-p udp --dport 853 -j REJECT",
                "-d 1.1.1.1 -p tcp --dport 443 -j REJECT --reject-with tcp-reset", "-d 1.1.1.1 -p udp --dport 443 -j REJECT",
                "-d 8.8.8.8 -p tcp --dport 443 -j REJECT --reject-with tcp-reset", "-d 8.8.8.8 -p udp --dport 443 -j REJECT"]
        if r.returncode != 0 or fwd != want or chain("filter", "FORWARD") != ["-s 192.168.1.0/24 -j VWARD_DNS_FWD"]:
            fail(f"{shell[0]} bypass rules: {fwd} {r.stdout}")
        if "agh filter-add https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/doh.txt HaGeZi Encrypted DNS Bypass" not in (tmp / "control.log").read_text():
            fail(f"{shell[0]} the DoH list must be added to AdGuard Home")

        # Counters for the Console.
        t = tables(); t["nat"]["VWARD_DNS"][-1]["pkts"] = 42; t["filter"]["VWARD_DNS_FWD"][1]["pkts"] = 7; fw.write_text(json.dumps(t))
        st = status()
        if (st.get("redirected"), st.get("refused"), st["redirect_active"], st["bypass_active"], st["upstream"]) != ("42", "7", "1", "1", "encrypted"):
            fail(f"{shell[0]} status: {st}")

        # AdGuard Home's DNS port closed: the redirect comes off, the rest stays.
        up.write_text("0")
        run("tick", shell=shell)
        if chain("nat", "PREROUTING") or "VWARD_DNS" in tables().get("nat", {}) or not chain("filter", "FORWARD"):
            fail(f"{shell[0]} AdGuard Home down: {tables()}")
        if "reason=agh_down" not in (tmp / "guard.state").read_text():
            fail("the state must say AdGuard Home is down")
        up.write_text("1")
        run("tick", shell=shell)
        if len(chain("nat", "PREROUTING")) != 2:
            fail(f"{shell[0]} AdGuard Home back: redirect must return")

        # Keenetic rebuilds its firewall: the hook puts everything back.
        fw.write_text(json.dumps({}))
        run("hook", "nat", shell=shell); run("hook", "filter", shell=shell)
        if chain("nat", "VWARD_DNS") != ["-s 192.168.1.50 -j RETURN", "-d 192.168.1.1 -j RETURN", "-j DNAT --to-destination 192.168.1.1:65053"] or chain("filter", "VWARD_DNS_FWD") != want:
            fail(f"{shell[0]} hook after rebuild: {tables()}")

        # Keenetic does not answer: an excluded device is never redirected by accident.
        rj = json.loads(router.read_text()); rj["rci_down"] = True; router.write_text(json.dumps(rj))
        before = chain("nat", "VWARD_DNS")
        r = run("apply", shell=shell)
        if r.returncode == 0 or chain("nat", "VWARD_DNS") != before or "router_unavailable" not in r.stdout:
            fail(f"{shell[0]} router down: {r.stdout} {chain('nat', 'VWARD_DNS')}")
        rj["rci_down"] = False; router.write_text(json.dumps(rj))

        # A kernel without REJECT: DROP instead.
        r = run("apply", shell=shell, extra={"FAKE_NO_REJECT": "1"})
        if r.returncode != 0 or chain("filter", "VWARD_DNS_FWD")[1] != "-p tcp --dport 853 -j DROP":
            fail(f"{shell[0]} DROP fallback: {chain('filter', 'VWARD_DNS_FWD')}")

        # Everything off: rules, chains and hook go; the DoH list is switched off, not removed.
        rj["filters"] = [{"url": "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/doh.txt", "enabled": True}]
        router.write_text(json.dumps(rj))
        run("set", "bypass", "0", shell=shell); run("set", "enforce", "0", shell=shell)
        t = tables()
        if t["nat"]["PREROUTING"] or t["filter"]["FORWARD"] or "VWARD_DNS" in t["nat"] or "VWARD_DNS_FWD" in t["filter"]:
            fail(f"{shell[0]} off: {t}")
        if (hooks / "060-vward-dns-guard.sh").exists():
            fail("off: the hook must go")
        if "agh filter-enable https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/doh.txt 0" not in (tmp / "control.log").read_text():
            fail(f"{shell[0]} the DoH list must be switched off")

        # Off, and nothing left behind: the minute tick starts no firewall process.
        (tmp / "guard.state").unlink()
        before = len((tmp / "fw.json.log").read_text().splitlines())
        run("tick", shell=shell)
        if len((tmp / "fw.json.log").read_text().splitlines()) != before:
            fail(f"{shell[0]} an idle tick must not call iptables")

print("ADS_DNS_GUARD=PASS")
