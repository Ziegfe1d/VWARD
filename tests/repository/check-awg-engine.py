#!/usr/bin/env python3
"""Tunnel engine («Контур AmneziaWG»): the pinned program is refused when its
checksum differs; a tunnel is kept only after a handshake and a Keenetic proxy
connection; a stopped program is started again; keys are never printed."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "components/tunnel-guard/scripts/vward-awg-engine.sh"
KEY = "K" * 42 + "A="
HPK = "H" * 42 + "A="
CONF = f"""[Interface]
PrivateKey = {KEY}
Address = 100.101.72.25/32
Jc = 7
S1 = 649
S2 = 170
S3 = 815
S4 = 12
HeaderProtectionKey = {HPK}
[Peer]
PublicKey = {"P" * 42}A=
Endpoint = 66.234.150.186:3954
PersistentKeepalive = 25-35

[Socks5]
BindAddress = 0.0.0.0:1080
"""

# wireproxy stand-in: -v, -n (config check) and a long run.
FAKE_WP = """#!/bin/sh
case "$1" in -v) echo "wireproxy, version 1.0.18"; exit 0 ;; esac
for a in "$@"; do [ "$a" = -n ] && exit 0; done
exec sleep 3600
"""

# curl stand-in: the release download, the health page and Keenetic's RCI.
FAKE_CURL = r"""#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
st = Path("@ST@")
a = sys.argv[1:]
url = [x for x in a if x.startswith("http")][-1]
if "/metrics" in url:
    if (st / "handshake").exists():
        print("private_key=" + "ab" * 32)
        print("last_handshake_time_sec=%d" % (int(time.time()) - 5))
        sys.exit(0)
    print("last_handshake_time_sec=0"); sys.exit(0)
if "releases/download" in url:
    out = a[a.index("-o") + 1]
    Path(out).write_bytes(b"not the pinned release"); sys.exit(0)
if "-d" in a:
    body = a[a.index("-d") + 1]
    with open(st / "rci.log", "a") as f: f.write(body + "\n")
    if (st / "rci-reject").exists() and '"proxy"' in body:
        print(json.dumps([{"interface": {"status": [{"status": "error", "message": "rejected"}]}}])); sys.exit(0)
    print("[]"); sys.exit(0)
sys.exit(22)
"""


def fail(msg: str) -> None:
    raise SystemExit(f"FAIL: {msg}")


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    st = t / "state"; st.mkdir()
    tools = t / "tools"; tools.mkdir()
    curl = tools / "curl"; curl.write_text(FAKE_CURL.replace("@ST@", str(st))); curl.chmod(0o755)
    share = t / "share"
    env = os.environ | {
        "VWARD_AWG_ETC": str(t / "etc"), "VWARD_AWG_SHARE": str(share), "VWARD_AWG_RUN": str(t / "run"),
        "VWARD_AWG_LOG": str(t / "engine.log"), "VWARD_CURL_BIN": str(curl), "VWARD_AWG_ARCH": "mipsle",
        "VWARD_AWG_HANDSHAKE_WAIT": "4", "VWARD_RCI_BASE": "http://127.0.0.1:79/rci",
    }
    conf = t / "upload.conf"; conf.write_text(CONF); conf.chmod(0o600)
    outs = []

    def run(*args, expect):
        r = subprocess.run(["sh", str(ENGINE), *args], env=env, text=True, capture_output=True, timeout=60)
        outs.append(r.stdout + r.stderr)
        last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if last != expect:
            fail(f"{args[:2]}: {last!r} != {expect!r} {r.stderr[-300:]}")
        return r.stdout

    # The download is refused when it is not the pinned release.
    run("install", expect="error=checksum_mismatch")
    if (share / "wireproxy").exists():
        fail("a refused download was installed")
    run("add", "Finland", str(conf), expect="error=engine_install_failed")

    # With the program in place (as if installed).
    share.mkdir(exist_ok=True)
    (share / "wireproxy").write_text(FAKE_WP); (share / "wireproxy").chmod(0o755)
    (share / "version").write_text("v1.0.18\n")
    run("install", expect="result=unchanged")
    run("add", 'Bad"name', str(conf), expect="error=invalid_description")

    # No handshake: nothing stays - no program, no files, no Keenetic connection.
    run("add", "Finland", str(conf), expect="error=tunnel_no_handshake")
    if list((t / "etc").glob("t[0-9]*")) or (st / "rci.log").exists():
        fail("a tunnel without a handshake left files or a Keenetic connection")

    # Keenetic refuses the proxy connection: the program stops, files go.
    (st / "handshake").write_text("1")
    (st / "rci-reject").write_text("1")
    run("add", "Finland", str(conf), expect="error=router_rejected")
    if "router_rejected Proxy40: rejected" not in (t / "engine.log").read_text():
        fail("the log must keep Keenetic's reason for a refused connection")
    if list((t / "etc").glob("t[0-9]*")) or list((t / "run").glob("*.pid")):
        fail("a refused tunnel left files behind")
    (st / "rci-reject").unlink()

    # A good tunnel: Proxy40 on 127.0.0.1:25400, UDP through, config saved.
    out = run("add", "Finland", str(conf), expect="result=changed")
    if "info.name=Proxy40" not in out:
        fail(f"add: {out}")
    rci = (st / "rci.log").read_text()
    body = [json.loads(l) for l in rci.splitlines() if '"proxy"' in l][-1][0]["interface"]
    if body["name"] != "Proxy40" or body["description"] != "Finland" or body["proxy"]["upstream"] != {"host": "127.0.0.1", "port": "25400"} or body["proxy"]["socks5-udp"] is not True:
        fail(f"Keenetic proxy connection: {body}")
    tconf = (t / "etc/t0.conf").read_text()
    if "[Socks5]" in tconf or "0.0.0.0:1080" in tconf or KEY not in tconf:
        fail("the tunnel file keeps a foreign proxy section or lost its key")
    if (t / "etc/t0.conf").stat().st_mode & 0o077 or (t / "etc").stat().st_mode & 0o077:
        fail("tunnel files are readable by others")
    if "BindAddress = 127.0.0.1:25400" not in (t / "etc/t0.wp").read_text():
        fail("the local proxy port")

    # Status: facts only.
    st_out = run("status", expect="result=status")
    if "tunnel=Proxy40\t1\t" not in st_out or "Finland" not in st_out:
        fail(f"status: {st_out}")

    # The Panel's API reads the same facts (Entware jq: no regex functions).
    import shutil
    api = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True,
                         env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=awg-data", "JQ": shutil.which("jq"),
                                    "VWARD_AWG_ENGINE_BIN": str(ENGINE)})
    j = json.loads(api.stdout[api.stdout.index("{"):])
    # Keenetic's own tunnels from AmneziaWG 3.x files (H1-H4 = 1 2 3 4, S3/S4 kept, header
    # protection dropped) are found; an AmneziaWG 2.0 tunnel with its own H values is not.
    ndmc = tools / "ndmc"
    ndmc.write_text("#!/bin/sh\ncat <<'EOF'\n"
                    "interface Wireguard0\n    description AWG2_DE\n    wireguard asc 5 10 50 43 30 179064566-1646449610 1687083366-1702146341 1888033499-1927208669 2059508124-2092293846 47 15 \"<b 0x52>\"\n    wireguard peer PeLt=\n        endpoint de.example:1\n    !\n    up\n!\n"
                    "interface Wireguard2\n    description fi\n    wireguard asc 7 10 80 649 170 1 2 3 4 815 12 \"<b 0x52><rd 9>\"\n    wireguard peer zOuN=\n        endpoint 66.234.150.186:3954\n    !\n    down\n!\n"
                    "interface Wireguard4\n    description \"us-east.conf (1)\"\n    wireguard asc 6 10 80 381 865 1 2 3 4 209 12 \"<b 0x52>\"\n    wireguard peer jcct=\n    !\n!\nEOF\n")
    ndmc.chmod(0o755)
    api2 = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True,
                          env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=awg-data", "JQ": shutil.which("jq"),
                                     "VWARD_AWG_ENGINE_BIN": str(ENGINE), "VWARD_NDMC": str(ndmc)})
    lost = json.loads(api2.stdout[api2.stdout.index("{"):])["lost"]
    if lost != [{"name": "Wireguard2", "description": "fi", "peer": "zOuN="}, {"name": "Wireguard4", "description": "us-east.conf (1)", "peer": "jcct="}]:
        fail(f"lost tunnels: {lost}")
    t0 = j["tunnels"][0] if j.get("tunnels") else {}
    if not j.get("installed") or t0.get("name") != "Proxy40" or not t0.get("running") or t0.get("description") != "Finland" or t0.get("endpoint") != "66.234.150.186:3954":
        fail(f"awg-data: {j}")
    outs.append(api.stdout)

    # A stopped program is started again by supervise.
    pid = int((t / "run/t0.pid").read_text())
    os.kill(pid, 9); time.sleep(0.3)
    run("supervise", expect="result=changed")
    if int((t / "run/t0.pid").read_text()) == pid:
        fail("supervise did not start the tunnel again")
    run("supervise", expect="result=unchanged")

    # Remove: Keenetic connection gone, program stopped, files deleted.
    run("remove", "Proxy99", expect="error=unknown_tunnel")
    run("remove", "Proxy40", expect="result=changed")
    if list((t / "etc").glob("t[0-9]*")) or (t / "etc/tunnels.tsv").read_text().strip():
        fail("remove left files")
    if '"no": true' not in (st / "rci.log").read_text().splitlines()[-1].replace('"no":true', '"no": true'):
        fail("remove did not delete the Keenetic connection")
    run("stop", expect="result=changed")

    everything = "".join(outs) + (t / "engine.log").read_text() + (st / "rci.log").read_text()
    if KEY in everything or HPK in everything or "ab" * 32 in everything:
        fail("a key reached the output, the log or Keenetic")

print("AWG_ENGINE=PASS")
