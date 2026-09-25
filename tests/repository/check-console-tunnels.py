#!/usr/bin/env python3
"""Tunnels from the Console: replace a configuration in place, create, delete, subnets.

A small Keenetic stand-in keeps interfaces, DNS routes and static routes in a
JSON state, prints them as running-config (the private key hidden, as on the
router) and answers RCI with a handshake only for keys the "server" knows.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

OLD_KEY = "O" * 42 + "A="
NEW_KEY = "N" * 42 + "A="
BAD_KEY = "B" * 42 + "A="
PEER_OLD = "P" * 42 + "A="
PEER_NEW = "Q" * 42 + "A="
PSK = "S" * 42 + "A="

FAKE_NDMC = r'''#!/usr/bin/env python3
import json, os, shlex, sys
from pathlib import Path
st = Path("@STATE@")
s = json.loads(st.read_text())
cmd = sys.argv[2]
# Commands sent in an RCI body are logged apart from those in ndmc's arguments.
with open(str(st) + ".log", "a") as f:
    f.write(("RCI: " if os.environ.get("FAKE_VIA_RCI") else "") + cmd + "\n")
def out(t): print(t); st.write_text(json.dumps(s)); sys.exit(0)
if cmd == "show running-config":
    lines = []
    for name, i in s["ifs"].items():
        lines.append("interface " + name)
        if i.get("description"): lines.append('    description ' + i["description"])
        if i.get("address"): lines.append("    ip address " + i["address"])
        if i.get("mtu"): lines.append("    ip mtu " + i["mtu"])
        if i.get("asc"): lines.append("    wireguard asc " + i["asc"])
        for p, v in i["peers"].items():
            lines.append("    wireguard peer " + p)
            for k in ("endpoint", "keepalive-interval", "preshared-key"):
                if v.get(k): lines.append("        %s %s" % (k, v[k]))
            for a in v.get("allow", []): lines.append("        allow-ips " + a)
            if v.get("connect"): lines.append("        connect")
            lines.append("    !")
        if i.get("up"): lines.append("    up")
        lines.append("!")
    lines.append("dns-proxy")
    for g, t in s["dns"].items(): lines.append("    route object-group %s %s auto" % (g, t))
    lines.append("!")
    for n, t in s["routes"]: lines.append("ip route %s %s auto" % (n, t))
    for g in s["dns"]: lines += ["object-group fqdn " + g, "    include example.org", "!"]
    out("\n".join(lines))
if cmd == "system configuration save":
    s["saved"] = s.get("saved", 0) + 1; out("saved")
w = cmd.split(" ", 1)
neg = w[0] == "no"
rest = w[1] if neg else cmd
t = rest.split()
if t[0] == "interface":
    name = t[1]
    if len(t) == 2:
        if neg: s["ifs"].pop(name, None)
        else: s["ifs"].setdefault(name, {"peers": {}})
        out("ok")
    i = s["ifs"].get(name)
    if i is None: out("Command::Base error: no such entry")
    a = t[2:]
    if a[0] == "description": i["description"] = rest.split(" description ", 1)[1]
    elif a[:2] == ["security-level", "public"] or a[:2] == ["ip", "tcp"]: pass
    elif a[:2] == ["ip", "address"]: i["address"] = " ".join(a[2:])
    elif a[:2] == ["ip", "mtu"]: i["mtu"] = a[2]
    elif a[0] == "up": i["up"] = True
    elif a[:2] == ["wireguard", "private-key"]: i["key"] = a[2]
    elif a[:2] == ["wireguard", "asc"]:
        if neg: i.pop("asc", None)
        elif Path(str(st) + ".reject-asc").exists(): out("Wireguard::Interface error: invalid asc")
        else: i["asc"] = rest.split(" wireguard asc ", 1)[1]
    elif a[:2] == ["wireguard", "peer"]:
        p = a[2]
        if neg: i["peers"].pop(p, None); out("ok")
        v = i["peers"].setdefault(p, {})
        sub = a[3:]
        if not sub: pass
        elif sub[0] == "allow-ips": v.setdefault("allow", []).append(" ".join(sub[1:]))
        elif sub[0] == "connect": v["connect"] = True
        else: v[sub[0]] = sub[1]
    else: out("Command::Base error: syntax")
    out("ok")
if t[0] == "dns-proxy":
    r = t[1:] if not neg else t[1:]
    if cmd.startswith("dns-proxy no route"):
        g, tg = t[4], t[5]
        if s["dns"].get(g) == tg: s["dns"].pop(g)
    elif cmd.startswith("dns-proxy route"):
        s["dns"][t[3]] = t[4]
    out("ok")
if t[:2] == ["ip", "route"]:
    net, dev = t[2] + " " + t[3], t[4]
    if neg: s["routes"] = [r for r in s["routes"] if not (r[0] == net and r[1] == dev)]
    elif [net, dev] not in s["routes"]: s["routes"].append([net, dev])
    out("ok")
out("Command::Base error: syntax")
'''

FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
st = json.loads(Path("@STATE@").read_text())
url = [a for a in sys.argv if a.startswith("http")][-1]
if "--data-binary" in sys.argv:
    # RCI "parse": the command comes from the request body file, as on Keenetic.
    body = json.loads(Path(sys.argv[sys.argv.index("--data-binary") + 1][1:]).read_text())
    r = subprocess.run(["@NDMC@", "-c", body[0]["parse"]], env=os.environ | {"FAKE_VIA_RCI": "1"}, capture_output=True, text=True)
    bad = "error" in r.stdout.lower()
    print(json.dumps([{"parse": {"status": [{"status": "error" if bad else "message", "message": r.stdout.strip()}]}}]))
    sys.exit(0)
if "show/interface?name=" in url:
    name = url.split("name=", 1)[1]
    i = st["ifs"].get(name)
    good = i and i.get("key") in st["server_keys"] and i.get("up")
    print(json.dumps({"wireguard": {"peer": [{"online": bool(good), "last-handshake": 3 if good else 999999}]}} if i else {}))
    sys.exit(0)
sys.exit(22)
'''


def conf(key, peer, endpoint="de.example.net:44486", awg=True):
    c = f"""[Interface]
PrivateKey = {key}
Address = 10.8.25.7/32, fd00::7/128
DNS = 1.1.1.1
MTU = 1324
"""
    if awg:
        c += """Jc = 5
Jmin = 10
Jmax = 50
S1 = 43
S2 = 30
S3 = 47
S4 = 15
H1 = 179064566-1646449610
H2 = 1687083366-1702146341
H3 = 1888033499-1927208669
H4 = 2059508124-2092293846
I1 = <b 0x5245474953544552>
I2 = <b 0x1603030078>
"""
    c += f"""
[Peer]
PublicKey = {peer}
PresharedKey = {PSK}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint}
PersistentKeepalive = 25
"""
    return c


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = tmp / "state.json"
    base = {
        "server_keys": [OLD_KEY, NEW_KEY],
        "ifs": {"Wireguard0": {"description": "Main", "address": "10.8.25.2 255.255.255.255", "mtu": "1324",
                               "asc": "4 40 70 0 0 1 2 3 4", "key": OLD_KEY, "up": True,
                               "peers": {PEER_OLD: {"endpoint": "old.example.net:51820", "keepalive-interval": "25",
                                                    "preshared-key": PSK, "allow": ["0.0.0.0 0.0.0.0"], "connect": True}}}},
        "dns": {"domain-list0": "Wireguard0", "domain-list4": "ISP"},
        "routes": [["91.108.56.0 255.255.252.0", "Wireguard0"]],
    }
    state.write_text(json.dumps(base))
    tools = tmp / "tools"; tools.mkdir()
    (tools / "ndmc").write_text(FAKE_NDMC.replace("@STATE@", str(state)))
    (tools / "curl").write_text(FAKE_CURL.replace("@STATE@", str(state)).replace("@NDMC@", str(tools / "ndmc")))
    for f in ("ndmc", "curl"):
        (tools / f).chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n")
    devconf.chmod(0o600)
    (tmp / "root/tmp").mkdir(parents=True)
    etc = tmp / "etc"
    # The device map lists the tunnels, as vward-device-profile.sh builds it from RCI.
    (tmp / "map.tsv").write_text("")
    env = os.environ | {
        "VWARD_NDMC": str(tools / "ndmc"), "VWARD_CURL_BIN": str(tools / "curl"), "VWARD_DEVICE_CONFIG": str(devconf),
        "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()), "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"),
        "VWARD_SYSFS_NET": str(tmp / "sys"), "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(etc),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_TUNNEL_HANDSHAKE_WAIT": "2", "VWARD_TUNNEL_HEALTH_STATE": str(tmp / "health"),
    }

    def S():
        return json.loads(state.read_text())

    def run(*args, expect=None):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True)
        last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if expect is not None and last != expect:
            fail(f"{args[:2]}: {last!r} != {expect!r} {r.stderr[-400:]}")
        if (tmp / "change.lock").exists():
            fail(f"{args[:2]}: change lock left behind")
        return r.stdout

    def upload(text):
        f = tmp / "upload.conf"
        f.write_text(text); f.chmod(0o600)
        return str(f)

    def only_main():
        s = S()
        return sorted(s["ifs"]) == ["Wireguard0"]

    # Check: a summary without keys, the file removed.
    out = run("tunnel-conf", "check", upload(conf(NEW_KEY, PEER_NEW)), expect="result=checked")
    if "info.endpoint=de.example.net:44486" not in out or "info.awg=1" not in out or NEW_KEY in out:
        fail(f"check summary: {out}")
    if (tmp / "upload.conf").exists():
        fail("the uploaded .conf with the private key must be removed")
    for bad, err in ((conf("short=", PEER_NEW), "error=conf_key_private"),
                     (conf(NEW_KEY, PEER_NEW, endpoint="x;reboot:1"), "error=conf_endpoint"),
                     ("[Interface]\nPrivateKey = " + NEW_KEY + "\n", "error=conf_peer_count"),
                     (conf(NEW_KEY, PEER_NEW).replace("I1 = <b 0x5245474953544552>", 'I1 = <b "x">'), "error=conf_awg")):
        run("tunnel-conf", "check", upload(bad), expect=err)

    # Replace: proven on a temporary interface, then written into Wireguard0 in place.
    before = S()
    run("tunnel-conf", "replace", upload(conf(NEW_KEY, PEER_NEW)), "Wireguard0", expect="result=changed")
    s = S()
    w = s["ifs"]["Wireguard0"]
    if not only_main():
        fail(f"the temporary interface was left: {sorted(s['ifs'])}")
    if w["key"] != NEW_KEY or list(w["peers"]) != [PEER_NEW] or w["address"] != "10.8.25.7 255.255.255.255":
        fail(f"Wireguard0 not replaced: {w}")
    if w["asc"] != '5 10 50 43 30 179064566-1646449610 1687083366-1702146341 1888033499-1927208669 2059508124-2092293846 47 15 "<b 0x5245474953544552>" "<b 0x1603030078>"':
        fail(f"AmneziaWG line: {w['asc']}")
    p = w["peers"][PEER_NEW]
    if p.get("endpoint") != "de.example.net:44486" or p.get("allow") != ["0.0.0.0 0.0.0.0", ":: 0"] or not p.get("connect") or p.get("preshared-key") != PSK:
        fail(f"peer: {p}")
    if s["dns"] != before["dns"] or s["routes"] != before["routes"] or s.get("saved", 0) < 1:
        fail("lists and routes must stay, the config must be saved")
    log = (Path(str(state) + ".log")).read_text()
    if "interface Wireguard1 ip address 192.0.2.254 255.255.255.255" not in log:
        fail("the test interface must use the test address")
    # Keys reach the router only in an RCI body, never in a process's arguments.
    for line in log.splitlines():
        if not line.startswith("RCI: ") and any(k in line for k in (NEW_KEY, OLD_KEY, PSK)):
            fail(f"a key went through ndmc arguments: {line[:60]}")
    if f"RCI: interface Wireguard0 wireguard private-key {NEW_KEY}" not in log:
        fail("the private key must be set through RCI")
    stored = etc / "tunnels/Wireguard0/current.conf"
    if not stored.exists() or oct(stored.stat().st_mode & 0o777) != "0o600":
        fail("the applied .conf must be kept root-only")

    # A server that does not know the key: Wireguard0 untouched, nothing left behind.
    before = S()
    run("tunnel-conf", "replace", upload(conf(BAD_KEY, PEER_OLD)), "Wireguard0", expect="error=tunnel_no_handshake")
    if S()["ifs"] != before["ifs"]:
        fail("a configuration that fails its test must not touch the tunnel")

    # The router rejects AmneziaWG settings: same.
    Path(str(state) + ".reject-asc").touch()
    run("tunnel-conf", "replace", upload(conf(NEW_KEY, PEER_NEW)), "Wireguard0", expect="error=conf_rejected_awg")
    if S()["ifs"] != before["ifs"]:
        fail("a rejected command must leave the tunnel as it was")
    Path(str(state) + ".reject-asc").unlink()

    # Replace back to the previous configuration: the private key comes from VWARD's store.
    s = S(); s["server_keys"] = [NEW_KEY, OLD_KEY]; s["ifs"]["Wireguard0"]["key"] = NEW_KEY; state.write_text(json.dumps(s))
    run("tunnel-conf", "replace", upload(conf(OLD_KEY, PEER_OLD, awg=False)), "Wireguard0", expect="result=changed")
    w = S()["ifs"]["Wireguard0"]
    if w["key"] != OLD_KEY or "asc" in w or list(w["peers"]) != [PEER_OLD]:
        fail(f"second replace: {w}")
    if not (etc / "tunnels/Wireguard0/prev1.conf").exists():
        fail("the previous configuration must be kept")
    run("tunnel-conf", "replace", upload(conf(NEW_KEY, PEER_NEW)), "Wireguard9", expect="error=unknown_tunnel")

    # Create a second tunnel.
    out = run("tunnel-conf", "create", upload(conf(NEW_KEY, PEER_NEW)), "Germany 2", expect="result=changed")
    s = S()
    if "info.name=Wireguard1" not in out or sorted(s["ifs"]) != ["Wireguard0", "Wireguard1"]:
        fail(f"create: {out} {sorted(s['ifs'])}")
    if s["ifs"]["Wireguard1"].get("description") != '"Germany 2"' or s["ifs"]["Wireguard1"]["key"] != NEW_KEY:
        fail(f"new tunnel: {s['ifs']['Wireguard1']}")
    run("tunnel-conf", "create", upload(conf(BAD_KEY, PEER_NEW)), "Broken", expect="error=tunnel_no_handshake")
    if sorted(S()["ifs"]) != ["Wireguard0", "Wireguard1"]:
        fail("a tunnel that does not answer must be removed again")
    run("tunnel-conf", "create", upload(conf(NEW_KEY, PEER_NEW)), 'a"b', expect="error=invalid_description")

    # The device map now knows Wireguard1: lists and subnets can go through it.
    (tmp / "map.tsv").unlink(missing_ok=True)
    env["VWARD_DEVICE_MAP_CACHE"] = str(tmp / "map2.tsv")
    (tmp / "map2.tsv").write_text("I\tWireguard0\twireguard\tnwg0\t1\nI\tWireguard1\twireguard\tnwg1\t1\n")
    run("tunnel-subnet", "Wireguard1", "add", "149.154.160.0/20", expect="result=changed")
    run("tunnel-subnet", "Wireguard1", "add", "149.154.160.0/20", expect="result=unchanged")
    run("tunnel-subnet", "Wireguard1", "add", "10.0.0.0/4", expect="error=invalid_subnet")
    if ["149.154.160.0 255.255.240.0", "Wireguard1"] not in S()["routes"]:
        fail(f"subnet not routed: {S()['routes']}")
    s = S(); s["dns"]["domain-list7"] = "Wireguard1"; state.write_text(json.dumps(s))

    # Delete: the VWARD tunnel stays; another tunnel hands its lists and subnets over first.
    run("tunnel-delete", "Wireguard0", "bypass", expect="error=main_tunnel")
    run("tunnel-delete", "Wireguard1", "vpn", expect="result=changed")
    s = S()
    if sorted(s["ifs"]) != ["Wireguard0"] or s["dns"].get("domain-list7") != "Wireguard0" or ["149.154.160.0 255.255.240.0", "Wireguard0"] not in s["routes"]:
        fail(f"delete did not hand over: {s['dns']} {s['routes']} {sorted(s['ifs'])}")
    if (etc / "tunnels/Wireguard1").exists():
        fail("the deleted tunnel's stored configuration must go")

    # The API: a .conf from the browser, decoded with its line breaks; keys never come back.
    import shutil, urllib.parse
    up = tmp / "uploads"
    body = urllib.parse.urlencode({"op": "check", "conf": conf(NEW_KEY, PEER_NEW)})
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, text=True, capture_output=True,
                       env=env | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=tunnel-conf", "CONTENT_LENGTH": str(len(body)),
                                  "CONTENT_TYPE": "application/x-www-form-urlencoded", "HTTP_X_VWARD_REQUEST": "console",
                                  "JQ": shutil.which("jq"), "VWARD_CONSOLE_CONFIG_BIN": str(HELPER), "VWARD_CONSOLE_TUNNEL_TMP": str(up)})
    got = json.loads(r.stdout.split("\n\n", 1)[1])
    if not got.get("ok") or got.get("endpoint") != "de.example.net:44486" or got.get("awg") != "1" or NEW_KEY in r.stdout:
        fail(f"api check: {got} {r.stderr[-300:]}")
    if any(up.iterdir()):
        fail("the uploaded .conf must not stay on the router")
    body = urllib.parse.urlencode({"op": "replace", "name": "Wireguard0", "conf": conf(NEW_KEY, PEER_NEW)})
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, text=True, capture_output=True,
                       env=env | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=tunnel-conf", "CONTENT_LENGTH": str(len(body)),
                                  "CONTENT_TYPE": "application/x-www-form-urlencoded", "HTTP_X_VWARD_REQUEST": "console",
                                  "JQ": shutil.which("jq"), "VWARD_CONSOLE_CONFIG_BIN": str(HELPER), "VWARD_CONSOLE_TUNNEL_TMP": str(up)})
    if json.loads(r.stdout.split("\n\n", 1)[1]).get("error") != "confirmation_required" or any(up.iterdir()):
        fail("replace needs its confirmation and leaves no file behind")

    # Across every run, rollbacks included, no key went through ndmc's arguments.
    for line in Path(str(state) + ".log").read_text().splitlines():
        if not line.startswith("RCI: ") and any(k in line for k in (NEW_KEY, OLD_KEY, BAD_KEY, PSK)):
            fail(f"a key went through ndmc arguments: {line[:60]}")
    if not any(l.startswith("RCI: ") and OLD_KEY in l for l in Path(str(state) + ".log").read_text().splitlines()):
        fail("the rollback must put the old key back through RCI")

print("CONSOLE_TUNNELS=PASS")
