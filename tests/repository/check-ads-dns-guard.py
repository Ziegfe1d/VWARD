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
import time
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
# iptables 1.4 (Keenetic's Entware): a port in DNAT only with -p tcp/udp.
if "DNAT" in rest and ":" in rest[-1] and "-p" not in rest:
    print("iptables v1.4.21: Need TCP, UDP, SCTP or DCCP with port specification", file=sys.stderr); sys.exit(2)
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
if op == "-S":
    for r in t[chain]: print("-A %s %s" % (chain, r["spec"]))
    sys.exit(0)
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

FAKE_NSLOOKUP = r'''#!/bin/sh
case "$2" in *:65053) A=$FAKE_AGH_ANSWER ;; *) A=$FAKE_ISP_ANSWER ;; esac
if [ -f "$A" ] && [ "$(cat "$A")" != 1 ]; then echo ";; connection timed out; no servers could be reached"; exit 1; fi
printf 'Server:\t\t%s\nAddress:\t%s\n\nName:\t%s\nAddress: 93.184.216.34\n' "${2%%:*}" "$2" "$1"
'''

FAKE_NDMC = r'''#!/bin/sh
echo "$2" >> "$FAKE_NDMC_LOG"
case "$2" in
    "show running-config") cat "$FAKE_RC" ;;
    "show ip name-server") printf '  address: 192.168.1.1\n     port: 65053\n  address: 89.207.216.1\n' ;;
    "no ip name-server "*) grep -vx "ip name-server ${2#no ip name-server }" "$FAKE_RC" > "$FAKE_RC.n"; mv "$FAKE_RC.n" "$FAKE_RC" ;;
    "ip name-server "*) echo "$2" >> "$FAKE_RC" ;;
esac
exit 0
'''

FAKE_PIDOF = r'''#!/bin/sh
[ -s "$FAKE_AGH_PID" ] && cat "$FAKE_AGH_PID" || exit 1
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
    for name, body in (("iptables", FAKE_IPTABLES), ("curl", FAKE_CURL), ("netstat", FAKE_NETSTAT), ("control", FAKE_CONTROL), ("nslookup", FAKE_NSLOOKUP), ("ndmc", FAKE_NDMC), ("pidof", FAKE_PIDOF)):
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
        "VWARD_NSLOOKUP": str(bindir / "nslookup"), "VWARD_DNS_GUARD_PARK": str(tmp / "parked"),
        "VWARD_DNS_GUARD_PROBE_FAILS": str(tmp / "probe-fails"), "FAKE_AGH_ANSWER": str(tmp / "agh-answer"),
        "FAKE_FW": str(fw), "FAKE_ROUTER": str(router), "FAKE_AGH_YAML": str(yaml), "FAKE_AGH_UP": str(up),
        "FAKE_CONTROL_LOG": str(tmp / "control.log"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "TMPDIR": str(tmp),
        "VWARD_NDMC": str(bindir / "ndmc"), "VWARD_PIDOF": str(bindir / "pidof"), "VWARD_DNS_CHAIN_STATE": str(tmp / "chain"),
        "VWARD_DNS_CHAIN_PAUSE": "0", "VWARD_AGH_BINDINGS": str(tmp / "agh-bindings.txt"), "FAKE_RC": str(tmp / "rc"), "FAKE_ISP_ANSWER": str(tmp / "isp-answer"), "FAKE_NDMC_LOG": str(tmp / "ndmc.log"), "FAKE_AGH_PID": str(tmp / "agh.pid"),
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
        if chain("nat", "VWARD_DNS") != ["-d 192.168.1.1 -j RETURN", "-p udp -j DNAT --to-destination 192.168.1.1:65053", "-p tcp -j DNAT --to-destination 192.168.1.1:65053"]:
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

        # Counters for the Panel.
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
        if chain("nat", "VWARD_DNS") != ["-s 192.168.1.50 -j RETURN", "-d 192.168.1.1 -j RETURN", "-p udp -j DNAT --to-destination 192.168.1.1:65053", "-p tcp -j DNAT --to-destination 192.168.1.1:65053"] or chain("filter", "VWARD_DNS_FWD") != want:
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

        # Fail-open for the owner's own redirect (a netfilter.d hook outside VWARD): into a port nothing
        # answers on, the DNS of the whole home is gone. The redirect comes off, and goes back when
        # AdGuard Home answers again; a port that is open but silent counts as dead on the second tick.
        OWN = ["-s 192.168.1.0/24 -d 192.168.1.1/32 -i br0 -p tcp -m tcp --dport 53 -j REDIRECT --to-ports 65053",
               "-s 192.168.1.0/24 -d 192.168.1.1/32 -i br0 -p udp -m udp --dport 53 -j REDIRECT --to-ports 65053"]
        park, answer = tmp / "parked", tmp / "agh-answer"

        def own_rules():
            for spec in OWN:
                subprocess.run([str(bindir / "iptables"), "-t", "nat", "-I", "PREROUTING", "1", *spec.split()], env=env, check=True)

        def guardlog():
            return "".join(f.read_text() for f in sorted((tmp / "log").glob("*")))

        def parked():
            return park.read_text().splitlines() if park.exists() else []

        for f in (park, tmp / "probe-fails"):
            f.unlink(missing_ok=True)
        fw.write_text(json.dumps({})); up.write_text("1"); answer.write_text("1")
        own_rules()
        run("tick", shell=shell)
        if sorted(chain("nat", "PREROUTING")) != sorted(OWN) or parked():
            fail(f"{shell[0]} AdGuard Home answers: its redirect must stay: {chain('nat', 'PREROUTING')}")
        up.write_text("0")
        run("tick", shell=shell)
        if chain("nat", "PREROUTING") or len(parked()) != 2 or "DNS_FAILOPEN" not in guardlog():
            fail(f"{shell[0]} AdGuard Home dead: the redirect must come off: {chain('nat', 'PREROUTING')} {parked()}")
        up.write_text("1")
        run("tick", shell=shell)
        if sorted(chain("nat", "PREROUTING")) != sorted(OWN) or parked() or "DNS_RESTORED" not in guardlog():
            fail(f"{shell[0]} AdGuard Home back: the redirect must return: {chain('nat', 'PREROUTING')} {parked()}")
        answer.write_text("0")
        run("tick", shell=shell)
        if sorted(chain("nat", "PREROUTING")) != sorted(OWN):
            fail(f"{shell[0]} one silent minute is not a death")
        run("tick", shell=shell)
        if chain("nat", "PREROUTING") or len(parked()) != 2:
            fail(f"{shell[0]} open but silent twice: the redirect must come off: {chain('nat', 'PREROUTING')}")
        answer.write_text("1")
        run("tick", shell=shell)
        if sorted(chain("nat", "PREROUTING")) != sorted(OWN) or parked():
            fail(f"{shell[0]} answering again: the redirect must return")
        # Keenetic rebuilds its firewall while AdGuard Home is down: the owner's hook puts the redirect
        # back unasked; VWARD's hook, right after it, takes it off at once.
        up.write_text("0"); fw.write_text(json.dumps({})); own_rules()
        run("hook", "nat", shell=shell)
        if chain("nat", "PREROUTING") or len(parked()) != 2:
            fail(f"{shell[0]} firewall rebuild with AdGuard Home down: {chain('nat', 'PREROUTING')} {parked()}")
        up.write_text("1")
        run("tick", shell=shell)
        if sorted(chain("nat", "PREROUTING")) != sorted(OWN) or parked():
            fail(f"{shell[0]} back after the hook: the redirect must return")
        # Switched off in the settings: the redirect is left alone.
        (etc / "dns-guard.conf").write_text("ENFORCE=0\nBYPASS=0\nEXCLUDE=\nFAILOPEN=0\n")
        up.write_text("0")
        run("tick", shell=shell)
        if sorted(chain("nat", "PREROUTING")) != sorted(OWN) or parked():
            fail(f"{shell[0]} FAILOPEN=0 must leave the redirect")
        (etc / "dns-guard.conf").unlink(); up.write_text("1")
        fw.write_text(json.dumps({})); answer.unlink()

        # Off, and nothing left behind: the minute tick changes no rule (it only reads the table).
        (tmp / "guard.state").unlink(missing_ok=True)
        before = len((tmp / "fw.json.log").read_text().splitlines())
        run("tick", shell=shell)
        if [l for l in (tmp / "fw.json.log").read_text().splitlines()[before:] if l != "-t nat -S PREROUTING"]:
            fail(f"{shell[0]} an idle tick must only read iptables")

        # The chain: Keenetic hands the queries to AdGuard Home («ip name-server 192.168.1.1:65053»)
        # while it answers; silent twice or restarting in a loop - out (the home keeps the
        # provider's DNS), back after 3 answers in a row; never into a loop back to the router.
        rc, chaindir, ndlog, pid = tmp / "rc", tmp / "chain", tmp / "ndmc.log", tmp / "agh.pid"
        shutil.rmtree(chaindir, ignore_errors=True)
        # The quick take-out of before fix.34 (CHAIN_OBSERVE=0); the observation mode is below.
        conf = etc / "dns-guard.conf"
        conf.write_text((conf.read_text() if conf.exists() else "") + "CHAIN_OBSERVE=0\n")
        rc.write_text("ip name-server 1.1.1.1\n"); ndlog.write_text(""); pid.write_text("1234\n")
        up.write_text("1"); answer.write_text("1")
        NS = "ip name-server 192.168.1.1:65053"
        inchain = lambda: NS in rc.read_text().splitlines()
        for i in range(2):
            run("tick", shell=shell)
            if inchain():
                fail(f"{shell[0]} back only after 3 answers in a row (tick {i + 1})")
        run("tick", shell=shell)
        if not inchain() or "system configuration save" not in ndlog.read_text() or "DNS_CHAIN_IN" not in guardlog():
            fail(f"{shell[0]} AdGuard Home answers: it goes back into the chain: {rc.read_text()!r}")
        if status().get("chain_state") != "in":
            fail(f"{shell[0]} status: {status()}")
        answer.write_text("0")
        for i in range(2):
            run("tick", shell=shell)
            if not inchain():
                fail(f"{shell[0]} {i + 1} silent minute(s) is not a death (a filter reload, a quick restart)")
        run("tick", shell=shell)
        if inchain() or "ip name-server 1.1.1.1" not in rc.read_text() or "DNS_CHAIN_OUT" not in guardlog():
            fail(f"{shell[0]} silent 3 minutes: out of the chain, the provider's DNS stays: {rc.read_text()!r}")
        st = status()
        if st.get("chain_state") != "out" or st.get("chain_reason") != "silent":
            fail(f"{shell[0]} status out: {st}")
        answer.write_text("1")
        for _ in range(3):
            run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} answering again: back into the chain")
        # The real-time watcher saw it silent for 15 s: out at once - when the provider's DNS answers.
        answer.write_text("0"); (tmp / "isp-answer").write_text("0")
        run("chain-out", shell=shell)
        if not inchain() or "DNS_CHAIN_KEEP" not in guardlog():
            fail(f"{shell[0]} the provider silent too: AdGuard Home stays (the internet is down, not it)")
        (tmp / "isp-answer").write_text("1")
        # List domains the route engine bound to AdGuard Home go out with it; one bound by hand stays.
        binds = tmp / "agh-bindings.txt"
        binds.write_text("googlevideo.com 192.168.1.1:65053\nyoutube.com 192.168.1.1:65053\nsmart.example ext\nbad.example failed\n")
        rc.write_text(rc.read_text() + "ip name-server 192.168.1.1:65053 googlevideo.com\nip name-server 192.168.1.1:65053 youtube.com\n"
                      "ip name-server 192.168.1.1:65053 smart.example\n")
        out = run("chain-out", shell=shell).stdout
        if inchain() or "chain_state=out" not in out or status().get("chain_reason") != "fast":
            fail(f"{shell[0]} chain-out: out at once: {out!r} {status()}")
        left = rc.read_text()
        if "googlevideo.com" in left or "youtube.com" in left or "smart.example" not in left or not binds.exists() or binds.read_text() != "smart.example ext\nbad.example failed\n" \
                or "AGH_UNBIND|count=2" not in guardlog():
            fail(f"{shell[0]} out of the chain: VWARD's list bindings go, one made by hand stays: {left!r}")
        # Already out: the watcher's next minute does not read Keenetic's configuration again.
        nd = tmp / "ndmc.log"
        n0 = len(nd.read_text().splitlines()) if nd.exists() else 0
        run("chain-out", shell=shell)
        if (len(nd.read_text().splitlines()) if nd.exists() else 0) != n0:
            fail(f"{shell[0]} chain-out while out: Keenetic is not asked again")
        # The second take-out within the hour: back after 9 answers in a row, not 3 (out and in
        # every few minutes, each with a save).
        answer.write_text("1")
        for _ in range(3):
            run("tick", shell=shell)
        if inchain():
            fail(f"{shell[0]} the second take-out within the hour: not back after 3 minutes")
        for _ in range(6):
            run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} back after a fast take-out (9 answers)")
        answer.write_text("1")
        run("chain-out", shell=shell)
        if not inchain():
            fail(f"{shell[0]} chain-out while it answers changes nothing")
        # A restart loop (a new process every minute) takes it out though it answers.
        # One restart (a settings change, an update) is no loop.
        pid.write_text("1235\n"); run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} one restart is not a loop")
        # A second crash within 10 minutes: a loop, out at once (not after five).
        pid.write_text("1236\n"); run("tick", shell=shell)
        if inchain() or status().get("chain_reason") != "loop":
            fail(f"{shell[0]} two crashes: a loop, out of the chain: {status()}")
        # AdGuard Home that would hand the queries back to the router never goes into the chain.
        shutil.rmtree(chaindir, ignore_errors=True); pid.write_text("1300\n")
        good_yaml = yaml.read_text()
        yaml.write_text(good_yaml.replace("upstream_dns:", "upstream_dns:\n    - 192.168.1.1", 1))
        for _ in range(4):
            run("tick", shell=shell)
        if inchain() or status().get("chain_reason") != "loop_upstream":
            fail(f"{shell[0]} an upstream back to the router: never into the chain: {status()}")
        yaml.write_text(good_yaml)
        # CHAIN=0: the owner keeps the line as it is.
        if "DNS_GUARD=PASS" not in run("set", "chain", "0", shell=shell).stdout:
            fail(f"{shell[0]} set chain 0")
        before = ndlog.read_text()
        for _ in range(4):
            run("tick", shell=shell)
        if inchain() or ndlog.read_text() != before:
            fail(f"{shell[0]} CHAIN=0: VWARD leaves the chain alone")
        run("set", "chain", "1", shell=shell)
        (etc / "dns-guard.conf").unlink(missing_ok=True)
        # An update VWARD makes: out before it, its restarts are no crash, back at once after.
        shutil.rmtree(chaindir, ignore_errors=True); answer.write_text("1")
        for _ in range(3):
            run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} back in before the update test")
        (tmp / "isp-answer").write_text("1")
        out = run("planned", "300", shell=shell).stdout
        if inchain() or status().get("chain_reason") != "update":
            fail(f"{shell[0]} planned: out before the update: {out!r} {status()}")
        for n in (1400, 1401, 1402):
            pid.write_text(f"{n}\n"); run("tick", shell=shell)
        if inchain() or status().get("chain_reason") != "update":
            fail(f"{shell[0]} restarts during an update are no loop: {status()}")
        answer.write_text("1")
        run("planned-done", shell=shell)
        if not inchain():
            fail(f"{shell[0]} planned-done: back at once when it answers: {status()}")
        run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} after the update: stays in")

        # fix.34, observation (the default, dns-guard.conf without CHAIN_OBSERVE): the short signs
        # only write WOULD_TAKE_OUT; AdGuard Home goes out after 10 silent minutes in a row, Keenetic
        # not busy, the provider answering, once an hour; back after 3 answers as before.
        (etc / "dns-guard.conf").unlink(missing_ok=True)
        shutil.rmtree(chaindir, ignore_errors=True); answer.write_text("1"); (tmp / "isp-answer").write_text("1")
        pid.write_text("2000\n")
        for _ in range(3):
            run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} observation: in the chain while it answers")
        log0 = len(guardlog())
        newlog = lambda: guardlog()[log0:]
        answer.write_text("0")
        for _ in range(4):
            run("tick", shell=shell)
        run("chain-out", shell=shell)
        pid.write_text("2001\n"); run("tick", shell=shell)
        pid.write_text("2002\n"); run("tick", shell=shell)
        log = newlog()
        if not inchain() or "DNS_CHAIN_OUT" in log:
            fail(f"{shell[0]} observation: 6 silent minutes, the watcher and restarts change nothing: {rc.read_text()!r}")
        for why in ("silent", "fast", "loop"):
            if log.count(f"WOULD_TAKE_OUT|{why}|") != 1:
                fail(f"{shell[0]} observation: «WOULD_TAKE_OUT|{why}» once a silence: {log.count(f'WOULD_TAKE_OUT|{why}|')}")
        (chaindir / "pids").unlink()  # the restarts are over (else a loop keeps it out 3 minutes)
        # 11 minutes of silence in a row (the first silent check 11 minutes ago): out.
        (chaindir / "silent.since").write_text(f"{int(time.time()) - 660}\n")
        run("tick", shell=shell)
        if inchain() or status().get("chain_reason") != "silent_10min" or "reason=silent_10min" not in newlog():
            fail(f"{shell[0]} observation: 11 silent minutes take it out: {status()} {rc.read_text()!r}")
        answer.write_text("1")
        for _ in range(3):
            run("tick", shell=shell)
        if not inchain():
            fail(f"{shell[0]} observation: back after 3 answers in a row: {status()}")
        # Silent 11 minutes again within the hour: stays, the journal says why.
        answer.write_text("0"); run("tick", shell=shell)
        (chaindir / "silent.since").write_text(f"{int(time.time()) - 660}\n")
        run("tick", shell=shell)
        if not inchain() or "WOULD_TAKE_OUT|hourly_limit|" not in newlog():
            fail(f"{shell[0]} observation: not more than once an hour")
        # Keenetic busy (an answer of 4.5 s a minute ago): such a minute does not decide.
        (chaindir / "outs").unlink()
        upt = int(float(Path("/proc/uptime").read_text().split()[0]))
        (tmp / "root/tmp/vward-keenetic-last").write_text(f"{upt} 450\n")
        run("tick", shell=shell)
        if not inchain() or "WOULD_TAKE_OUT|keenetic_busy|" not in newlog():
            fail(f"{shell[0]} observation: Keenetic busy does not decide")
        (tmp / "root/tmp/vward-keenetic-last").unlink()
        # The provider's DNS silent too: the internet is down, not AdGuard Home.
        (tmp / "isp-answer").write_text("0"); run("tick", shell=shell)
        if not inchain() or "WOULD_TAKE_OUT|provider_silent|" not in newlog():
            fail(f"{shell[0]} observation: the provider silent too keeps it")
        (tmp / "isp-answer").write_text("1"); run("tick", shell=shell)
        if inchain():
            fail(f"{shell[0]} observation: all conditions met, out")
        answer.write_text("1")

# Keenetic hands all queries to AdGuard Home only by the line without a domain («""» before an
# interface); a domain bound to it (Smart DNS, a list) is not the chain (Viva 2026-10-13: with 24
# such bindings AdGuard Home was taken for in after a fast take-out and never put back).
src = GUARD.read_text()
fn = src[src.index("chain_line()\n"):]
fn = fn[:fn.index("\n}\n") + 3]
for text, want in (("ip name-server 192.168.1.1:65053\n", 0), ('ip name-server 192.168.1.1:65053 "" on Bridge0\n', 0),
                   ("ip name-server 192.168.1.1:65053 on Bridge0\n", 0),
                   ("ip name-server 192.168.1.1:65053 youtube.com\nip name-server 192.168.1.1:65053 claude.ai on ISP\n", 1),
                   ("ip name-server 192.168.1.1:650531\n", 1)):
    r = subprocess.run(["sh", "-c", fn + 'chain_line 192.168.1.1:65053'], input=text, text=True)
    if r.returncode != want:
        fail(f"chain line {text!r}: rc={r.returncode}")

# fix.32: AdGuard Home gone with the USB stick, its 25 lines left in Keenetic - every listed domain
# asked a dead server. Nothing listening on the port twice in a row: the lines go, ad blocking
# not set up at all; a listening port (a restart) keeps them.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bindir = tmp / "bin"; bindir.mkdir()
    for name, body in (("ndmc", FAKE_NDMC), ("pidof", FAKE_PIDOF), ("nslookup", FAKE_NSLOOKUP)):
        f = bindir / name; f.write_text(body); f.chmod(0o755)
    (tmp / "profile.sh").write_text(FAKE_PROFILE + "vward_note() { echo \"$*\" >> \"$FAKE_NOTES\"; }\n")
    net = tmp / "net"; net.mkdir()
    head = "  sl  local_address rem_address   st\n"
    (net / "udp").write_text(head + "   0: 00000000:0035 00000000:0000 07\n"); (net / "udp6").write_text(head)
    rc = tmp / "rc"
    rc.write_text("ip name-server 192.168.1.1:65053\nip name-server 192.168.1.1:65053 chatgpt.com\n"
                  "ip name-server 192.168.1.1:65053 claude.ai\nip name-server 8.8.8.8\nip name-server 192.168.1.1:5353 local.example\n")
    (tmp / "agh-bindings.txt").write_text("chatgpt.com 192.168.1.1:65053\nclaude.ai 192.168.1.1:65053\nkeep.example ext\n")
    etc = tmp / "etc"; etc.mkdir()
    env = os.environ | {"VWARD_ADS_LIB": str(ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"),
        "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(tmp / "state"), "VWARD_ADS_LOG_DIR": str(tmp / "log"),
        "VWARD_ADS_DEVICE_PROFILE_LIB": str(tmp / "profile.sh"), "FAKE_AGH_YAML": str(tmp / "absent.yaml"),
        "VWARD_NDMC": str(bindir / "ndmc"), "VWARD_PIDOF": str(bindir / "pidof"), "FAKE_RC": str(rc), "FAKE_NDMC_LOG": str(tmp / "ndmc.log"),
        "FAKE_AGH_PID": str(tmp / "agh.pid"), "FAKE_NOTES": str(tmp / "notes"), "VWARD_PROC_NET": str(net), "VWARD_NSLOOKUP": str(bindir / "nslookup"),
        "VWARD_DNS_CHAIN_STATE": str(tmp / "chain"), "VWARD_AGH_BINDINGS": str(tmp / "agh-bindings.txt"),
        "VWARD_DNS_GUARD_LOCK": str(tmp / "lock"), "VWARD_DNS_GUARD_STATE": str(tmp / "guard.state"),
        "VWARD_DNS_ORPHAN_EVERY_MIN": "0", "VWARD_ROOT_PREFIX": str(tmp), "TMPDIR": str(tmp),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"), "VWARD_PROC": str(tmp / "proc")}
    orphan = lambda: subprocess.run(["sh", str(GUARD), "orphan"], env=env, text=True, capture_output=True, timeout=60)
    # The take-out of before fix.34 (two looks); the observation mode below.
    (etc / "dns-guard.conf").write_text("CHAIN_OBSERVE=0\n")
    # fix.33.2 (WP-B п.5): no look counts in the first 5 minutes after boot, nor while AdGuard Home
    # is younger than 2 minutes (its port opens after the start).
    proc = tmp / "proc"; (proc / "4242").mkdir(parents=True)
    (proc / "4242/stat").write_text("4242 (AdGuardHome) S " + " ".join(["1"] * 18) + " 95000 0 0\n")
    for up, pid, why in (("100.00 1", "", "the first minutes after boot"), ("1000.00 1", "4242", "AdGuard Home starting")):
        (proc / "uptime").write_text(up + "\n"); (tmp / "agh.pid").write_text(pid)
        orphan(); orphan()
        if "192.168.1.1:65053 chatgpt.com" not in rc.read_text():
            fail(f"orphan: {why} is no death")
    (proc / "uptime").write_text("1000.00 1\n"); (tmp / "agh.pid").write_text("")
    orphan()
    if "192.168.1.1:65053 chatgpt.com" not in rc.read_text():
        fail("orphan: one look is not a death (a restart)")
    # The other local server answers: its line stays.
    (net / "udp").write_text(head + "   0: 0101A8C0:14E9 00000000:0000 07\n")
    orphan()
    lines = rc.read_text().splitlines()
    if any(":65053" in l for l in lines) or "ip name-server 8.8.8.8" not in lines or "ip name-server 192.168.1.1:5353 local.example" not in lines:
        fail(f"orphan: the lines into the dead server go, the others stay: {lines}")
    if (tmp / "agh-bindings.txt").read_text().split("\n")[0] != "keep.example ext" or (tmp / "chain/state").read_text().strip() != "out":
        fail("orphan: bindings of the dead server forgotten, the chain marked out")
    if "system configuration save" not in (tmp / "ndmc.log").read_text() or "AdGuard Home" not in (tmp / "notes").read_text():
        fail("orphan: saved and told in the bell")
    # Observation (fix.34): a port nothing listens on is a sign; 10 minutes of it decide.
    (etc / "dns-guard.conf").unlink()
    shutil.rmtree(tmp / "chain")
    rc.write_text("ip name-server 192.168.1.1:65053\nip name-server 192.168.1.1:65053 chatgpt.com\nip name-server 8.8.8.8\n")
    (net / "udp").write_text(head)
    orphan(); orphan(); orphan()
    logs = lambda: " ".join(f.read_text() for f in (tmp / "log").rglob("*") if f.is_file())
    if "192.168.1.1:65053 chatgpt.com" not in rc.read_text() or logs().count("WOULD_TAKE_OUT|absent|") != 1:
        fail(f"orphan, observation: a few minutes change nothing, the journal says it once: {rc.read_text()!r}")
    (tmp / "chain/orphan.65053.since").write_text(f"{int(time.time()) - 660}\n")
    orphan()
    if ":65053" in rc.read_text() or "ip name-server 8.8.8.8" not in rc.read_text():
        fail(f"orphan, observation: 11 minutes of nothing listening: the lines go: {rc.read_text()!r} {logs()[-300:]}")
    sched = (ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-scheduler.sh").read_text()
    if sched.index('"$SCH_G" orphan') > sched.index("vward_component_gate ads-privacy-guard"):
        fail("the scheduler looks for dead DNS lines before the ads gate (ads off or never set up)")

# Ad blocking never set up (no ads-privacy-guard.conf; the owner's router, 2026-10-18..19: 12
# «config not readable»): opening the Panel's page is an answer, not a failure in the journal.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    env = os.environ | {"VWARD_ADS_LIB": str(ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"),
        "VWARD_ADS_ETC": str(tmp / "etc"), "VWARD_ADS_STATE": str(tmp / "state"), "VWARD_ADS_LOG_DIR": str(tmp / "log"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"), "VWARD_ROOT_PREFIX": str(tmp), "TMPDIR": str(tmp)}
    for script, args in (("vward-ads-privacy-settings.sh", ["show"]), ("vward-ads-privacy-scheduler.sh", [])):
        r = subprocess.run(["sh", str(ROOT / "components/ads-privacy-guard/scripts" / script), *args], env=env, text=True, capture_output=True, timeout=60)
        logs = " ".join(f.read_text() for f in (tmp / "log").rglob("*") if f.is_file()) if (tmp / "log").exists() else ""
        if "not readable" in logs or "FAIL|" in logs:
            fail(f"{script} without a config must not write a failure into the journal: {logs!r}")

print("ADS_DNS_GUARD=PASS")
