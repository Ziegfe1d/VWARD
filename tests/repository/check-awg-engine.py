#!/usr/bin/env python3
"""Tunnel engine («Контур AmneziaWG»): the program is refused when its checksum
differs; a tunnel is kept only after a handshake, as a Keenetic «OpkgTun»
connection the program attaches to; a stopped program is started again; keys
are never printed or passed in a command's arguments."""

import gzip
import json
import os
import shutil
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
Address = 10.66.0.25/32, fd00::25/128
DNS = 10.66.0.1
Jc = 7
S3 = 800
S4 = 12
HeaderProtectionKey = {HPK}
[Peer]
PublicKey = {"P" * 42}A=
Endpoint = 203.0.113.10:3954
PersistentKeepalive = 25-35
"""

# vward-awg stand-in: -v, -n (file check) and a run that writes its state file
# with a handshake only while the "server" answers.
FAKE_AWG = """#!/bin/sh
ST=@ST@
case "$1" in -v) echo "vward-awg 1.2.1"; exit 0 ;; esac
for a in "$@"; do [ "$a" = -n ] && { grep -q BADCONF "$3" && exit 1; exit 0; }; done
while getopts i:c:s:t: o; do case $o in i) I=$OPTARG ;; c) C=$OPTARG ;; s) S=$OPTARG ;; esac; done
echo "$I" > "$ST/adapter"
echo "$GOMAXPROCS" > "$ST/threads"
while :; do
    h=0; [ -f "$ST/handshake" ] && h=$(date +%s)
    printf 'handshake=%s\\nrx=1\\ntx=1\\n' "$h" > "$S.tmp" && mv -f "$S.tmp" "$S"
    sleep 1
done
"""

# Keenetic stand-in: running-config from a JSON state; "reject" refuses the address.
FAKE_NDMC = r"""#!/usr/bin/env python3
import json, sys
from pathlib import Path
st = Path("@ST@")
f = st / "ifaces.json"
ifs = json.loads(f.read_text()) if f.exists() else {"OpkgTun0": "other program"}
cmd = sys.argv[2]
with open(st / "ndmc.log", "a") as log: log.write(cmd + "\n")
def save(): f.write_text(json.dumps(ifs))
if cmd == "show running-config":
    for name, d in ifs.items(): print("interface " + name); print("    description " + d); print("!")
    sys.exit(0)
if cmd == "system configuration save":
    (st / "saved").write_text("1"); print("Core::ConfigurationSaver: saving configuration..."); sys.exit(0)
w = cmd.split()
if w[0] == "no" and w[1] == "interface":
    ifs.pop(w[2], None); save(); print("Network::Interface::Repository: removed"); sys.exit(0)
if w[0] == "interface":
    if len(w) == 2:
        ifs[w[1]] = ""; save(); print("Network::Interface::Repository: created"); sys.exit(0)
    if w[1] not in ifs:
        print('Network::Interface::Base error[6553609]: unable to find ' + w[1]); sys.exit(0)
    if w[2] == "ip" and w[3] == "address" and (st / "reject").exists():
        print('Network::Interface::Ip error[1]: invalid address'); sys.exit(0)
    if w[2] == "description": ifs[w[1]] = " ".join(w[3:]).strip('"'); save()
    print("ok"); sys.exit(0)
print("Command::Base error[7405600]: no such command"); sys.exit(0)
"""

FAKE_CURL = r"""#!/usr/bin/env python3
import sys
from pathlib import Path
a = sys.argv[1:]
url = [x for x in a if x.startswith("http")][-1]
if "/vward-awg-linux-" in url:
    Path(a[a.index("-o") + 1]).write_bytes(Path("@ST@/download.gz").read_bytes()); sys.exit(0)
sys.exit(22)
"""


def fail(msg: str) -> None:
    raise SystemExit(f"FAIL: {msg}")



def _safe_read(f):
    try:
        return f.read_text().strip()
    except OSError:
        return ""


def _safe_cmd(d):
    try:
        return (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""

def tool(path: Path, text: str) -> Path:
    path.write_text(text); path.chmod(0o755); return path


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    st = t / "state"; st.mkdir()
    tools = t / "tools"; tools.mkdir()
    curl = tool(tools / "curl", FAKE_CURL.replace("@ST@", str(st)))
    ndmc = tool(tools / "ndmc", FAKE_NDMC.replace("@ST@", str(st)))
    (st / "download.gz").write_bytes(gzip.compress(b"not the pinned program"))
    share = t / "share"
    env = os.environ | {
        "VWARD_AWG_ETC": str(t / "etc"), "VWARD_AWG_SHARE": str(share), "VWARD_AWG_RUN": str(t / "run"),
        "VWARD_AWG_LOG": str(t / "engine.log"), "VWARD_CURL_BIN": str(curl), "VWARD_NDMC": str(ndmc),
        "VWARD_AWG_ARCH": "mipsle", "VWARD_AWG_HANDSHAKE_WAIT": "4", "VWARD_ENGINE_COOLDOWN": "0",
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

    def ifaces():
        f = st / "ifaces.json"
        return json.loads(f.read_text()) if f.exists() else {"OpkgTun0": "other program"}

    # The download is refused when it is not the pinned program.
    run("install", expect="error=checksum_mismatch")
    if (share / "vward-awg").exists():
        fail("a refused download was installed")
    run("add", "Finland", str(conf), expect="error=engine_install_failed")

    # With the program in place (as if installed).
    share.mkdir(exist_ok=True)
    tool(share / "vward-awg", FAKE_AWG.replace("@ST@", str(st)))
    (share / "version").write_text("1.2.1\n")
    run("install", expect="result=unchanged")
    run("add", 'Bad"name', str(conf), expect="error=invalid_description")
    noaddr = t / "noaddr.conf"; noaddr.write_text(CONF.replace("Address = 10.66.0.25/32, fd00::25/128\n", ""))
    run("add", "Finland", str(noaddr), expect="error=conf_no_address")
    bad = t / "bad.conf"; bad.write_text(CONF + "# BADCONF\n")
    run("add", "Finland", str(bad), expect="error=conf_rejected")

    # No handshake: nothing stays - no program, no files, no Keenetic connection.
    run("add", "Finland", str(conf), expect="error=tunnel_no_handshake")
    if list((t / "etc").glob("t[0-9]*")) or list((t / "run").glob("*.pid")) or set(ifaces()) != {"OpkgTun0"}:
        fail(f"a tunnel without a handshake left something: {ifaces()}")

    # «keep»: the owner chose to keep it though the server is silent - the tunnel stays, said so.
    out = run("add", "Finland", str(conf), "keep", expect="result=changed")
    if "info.handshake=none" not in out or "info.name=OpkgTun1" not in out or ifaces().get("OpkgTun1") != "Finland" or not (t / "etc/t0.conf").exists():
        fail(f"a kept tunnel: {out} {ifaces()}")
    run("remove", "OpkgTun1", expect="result=changed")
    if list((t / "etc").glob("t[0-9]*")) or set(ifaces()) != {"OpkgTun0"}:
        fail("removing the kept tunnel left something")

    # Keenetic refuses the address: the connection goes, its words reach the log.
    (st / "handshake").write_text("1")
    (st / "reject").write_text("1")
    run("add", "Finland", str(conf), expect="error=router_rejected")
    if list((t / "etc").glob("t[0-9]*")) or set(ifaces()) != {"OpkgTun0"}:
        fail("a refused tunnel left files or a connection")
    if "invalid address" not in (t / "engine.log").read_text():
        fail("the log must keep Keenetic's reason")
    (st / "reject").unlink()

    # A good tunnel: the first free OpkgTun (OpkgTun0 belongs to another program),
    # made before the program starts, the address from the file, saved.
    (st / "ndmc.log").write_text("")
    # With fd 3 open (as the Panel's job opens it) the add reports its steps there.
    r = subprocess.run(["sh", "-c", 'sh "$0" add Finland "$1" 3>&1', str(ENGINE), str(conf)], env=env, text=True, capture_output=True, timeout=60)
    out = r.stdout
    outs.append(r.stdout + r.stderr)
    if out.strip().splitlines()[-1:] != ["result=changed"]:
        fail(f"add: {out} {r.stderr[-300:]}")
    steps = [l[5:] for l in out.splitlines() if l.startswith("step=")]
    if steps != ["router", "program", "handshake", "save"]:
        fail(f"add steps: {steps}")
    if "info.name=OpkgTun1" not in out or ifaces().get("OpkgTun1") != "Finland":
        fail(f"add: {out} {ifaces()}")
    cmds = (st / "ndmc.log").read_text().splitlines()
    want = ["interface OpkgTun1", 'interface OpkgTun1 description "Finland"', "interface OpkgTun1 ip address 10.66.0.25 255.255.255.255",
            "interface OpkgTun1 security-level public", "interface OpkgTun1 ip tcp adjust-mss pmtu", "interface OpkgTun1 up"]
    if [c for c in cmds if c.startswith("interface OpkgTun1")] != want or cmds[-1] != "system configuration save":
        fail(f"Keenetic commands: {cmds}")
    if (st / "adapter").read_text().strip() != "opkgtun1":
        fail("the program must attach to Keenetic's adapter opkgtun1")
    if (st / "threads").read_text().strip() != "2":
        fail("the program must run on two threads")
    tconf = (t / "etc/t0.conf").read_text()
    if KEY not in tconf or "\r" in tconf:
        fail("the tunnel file lost its key")
    if (t / "etc/t0.conf").stat().st_mode & 0o077 or (t / "etc").stat().st_mode & 0o077:
        fail("tunnel files are readable by others")

    # Status: facts only.
    st_out = run("status", expect="result=status")
    if "tunnel=OpkgTun1\t1\t" not in st_out or "Finland" not in st_out or "203.0.113.10:3954" not in st_out:
        fail(f"status: {st_out}")

    # replace: the file is swapped and the program restarts on it; anything wrong puts the old one back.
    new = t / "new.conf"
    new.write_text(CONF.replace("10.66.0.25", "10.66.0.77").replace("203.0.113.10:3954", "198.51.100.7:4000")); new.chmod(0o600)
    old_text = (t / "etc/t0.conf").read_text()
    (st / "ndmc.log").write_text("")
    run("replace", "OpkgTun1", str(new), expect="result=changed")
    if "198.51.100.7:4000" not in (t / "etc/t0.conf").read_text() or "interface OpkgTun1 ip address 10.66.0.77 255.255.255.255" not in (st / "ndmc.log").read_text():
        fail("replace: the new file and the new address are not in place")
    if (t / "etc/t0.conf").stat().st_mode & 0o077 or list((t / "etc").glob("t0.conf.*")):
        fail("replace left a file behind or loosened a mode")
    run("replace", "OpkgTun1", str(bad), expect="error=conf_rejected")
    if "198.51.100.7:4000" not in (t / "etc/t0.conf").read_text():
        fail("a rejected file must not replace the working one")
    (st / "handshake").unlink()
    (st / "ndmc.log").write_text("")
    run("replace", "OpkgTun1", str(conf), expect="error=tunnel_no_handshake")
    if "198.51.100.7:4000" not in (t / "etc/t0.conf").read_text() or "interface OpkgTun1 ip address 10.66.0.77 255.255.255.255" not in (st / "ndmc.log").read_text() or list((t / "etc").glob("t0.conf.*")):
        fail("a silent server must put the old file and the old address back")
    out = run("replace", "OpkgTun1", str(conf), "keep", expect="result=changed")
    if "info.handshake=none" not in out or "203.0.113.10:3954" not in (t / "etc/t0.conf").read_text():
        fail(f"replace with keep: {out}")
    (st / "handshake").write_text("1")
    run("replace", "OpkgTun1", str(conf), expect="result=changed")
    if (t / "etc/t0.conf").read_text().replace("\r", "") != old_text:
        fail("the original file is back after the last replace")
    run("replace", "OpkgTun7", str(conf), expect="error=unknown_tunnel")

    # The Panel's API reads the same facts (Entware jq: no regex functions).
    api = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True,
                         env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=awg-data", "JQ": shutil.which("jq"),
                                    "VWARD_AWG_ENGINE_BIN": str(ENGINE)})
    j = json.loads(api.stdout[api.stdout.index("{"):])
    t0 = j["tunnels"][0] if j.get("tunnels") else {}
    if not j.get("installed") or t0.get("name") != "OpkgTun1" or not t0.get("running") or t0.get("description") != "Finland" or t0.get("endpoint") != "203.0.113.10:3954":
        fail(f"awg-data: {j}")
    outs.append(api.stdout)
    # Keenetic's own tunnels from AmneziaWG 3.x files (H1-H4 = 1 2 3 4, S3/S4 kept, header
    # protection dropped) are found; an AmneziaWG 2.0 tunnel with its own H values is not.
    rc = tool(tools / "ndmc-rc", "#!/bin/sh\ncat <<'EOF'\n"
              "interface Wireguard0\n    description de\n    wireguard asc 5 10 50 40 30 100000000-200000000 300000000-400000000 500000000-600000000 700000000-800000000 47 15 \"<b 0x52>\"\n    wireguard peer PDeA=\n        endpoint de.example:1\n    !\n    up\n!\n"
              "interface Wireguard2\n    description fi\n    wireguard asc 7 10 80 600 150 1 2 3 4 800 12 \"<b 0x52><rd 9>\"\n    wireguard peer PFiA=\n        endpoint 203.0.113.10:3954\n    !\n    down\n!\n"
              "interface Wireguard4\n    description \"us-east.conf (1)\"\n    wireguard asc 6 10 80 300 800 1 2 3 4 200 12 \"<b 0x52>\"\n    wireguard peer PUsA=\n    !\n!\nEOF\n")
    api2 = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True,
                          env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=awg-data", "JQ": shutil.which("jq"),
                                     "VWARD_AWG_ENGINE_BIN": str(ENGINE), "VWARD_NDMC": str(rc)})
    lost = json.loads(api2.stdout[api2.stdout.index("{"):])["lost"]
    if lost != [{"name": "Wireguard2", "description": "fi", "peer": "PFiA="}, {"name": "Wireguard4", "description": "us-east.conf (1)", "peer": "PUsA="}]:
        fail(f"lost tunnels: {lost}")

    # A stopped program is started again by supervise, on the same adapter.
    pid = int((t / "run/t0.pid").read_text())
    os.kill(pid, 9); time.sleep(0.3)
    (st / "adapter").unlink()
    run("supervise", expect="result=changed")
    if int((t / "run/t0.pid").read_text()) == pid:
        fail("supervise did not start the tunnel again")
    time.sleep(0.5)
    if (st / "adapter").read_text().strip() != "opkgtun1":
        fail("the restarted program is on another adapter")
    run("supervise", expect="result=unchanged")

    # Keenetic switched the interface off and on (the guard does): the program starts afresh.
    sysfs = t / "sys"; (sysfs / "opkgtun1").mkdir(parents=True)
    env["VWARD_SYSFS_NET"] = str(sysfs)
    pid = (t / "run/t0.pid").read_text()
    (sysfs / "opkgtun1/flags").write_text("0x1090\n")
    run("supervise", expect="result=unchanged")
    if not (t / "run/t0.down").exists() or (t / "run/t0.pid").read_text() != pid:
        fail("an adapter switched off: a mark, the program stays")
    (sysfs / "opkgtun1/flags").write_text("0x1091\n")
    run("supervise", expect="result=changed")
    if (t / "run/t0.down").exists() or (t / "run/t0.pid").read_text() == pid:
        fail("the adapter on again: the program must start afresh")
    time.sleep(0.5)
    run("supervise", expect="result=unchanged")
    del env["VWARD_SYSFS_NET"]

    # The program of a tunnel that is gone (removed, but not stopped; Viva 2026-10-04) is stopped.
    orphan = subprocess.Popen([str(share / "vward-awg"), "-i", "opkgtun7", "-c", str(t / "etc/t7.conf"), "-s", str(t / "run/t7.state")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    run("supervise", expect="result=unchanged")
    time.sleep(0.5)
    if orphan.poll() is None:
        orphan.kill(); fail("the program of a removed tunnel must be stopped")
    if "stopped the program of a removed tunnel (slot 7)" not in (t / "engine.log").read_text():
        fail("the stopped orphan is logged")
    # A stale pid file: restart leaves exactly one program on the slot's configuration.
    (t / "run/t0.pid").write_text("999999\n")
    (st / "handshake").write_text("1")
    run("restart", "OpkgTun1", expect="result=changed")
    time.sleep(0.5)
    live = [d.name for d in Path("/proc").iterdir() if d.name.isdigit() and (d / "comm").exists()
            and _safe_read(d / "comm") == "vward-awg" and str(t / "etc/t0.conf") in _safe_cmd(d)]
    if len(live) != 1:
        fail(f"after a restart with a stale pid file exactly one program runs: {live}")

    # Traffic comes from the program's own state; «Выключить» in the Panel: the program stops,
    # supervise leaves it alone (the flag outlives a reboot), status says so; «Включить» back.
    (t / "run/t0.state").write_text(f"handshake={int(time.time()) - 5}\nrx=123456\ntx=7890\npid=1\nupdated=1\n")
    line = [l for l in run("status", expect="result=status").splitlines() if l.startswith("tunnel=")][0].split("\t")
    if line[6:] != ["123456", "7890", "0"]:
        fail(f"status traffic and off flag: {line}")
    api3 = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True,
                          env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=awg-data", "JQ": shutil.which("jq"), "VWARD_AWG_ENGINE_BIN": str(ENGINE)})
    t3 = json.loads(api3.stdout[api3.stdout.index("{"):])["tunnels"][0]
    if t3.get("rx") != 123456 or t3.get("tx") != 7890 or t3.get("off") is not False:
        fail(f"awg-data traffic: {t3}")
    run("disable", "OpkgTun7", expect="error=unknown_tunnel")
    pid = int((t / "run/t0.pid").read_text())
    run("disable", "OpkgTun1", expect="result=changed")
    time.sleep(0.3)
    if not (t / "etc/t0.off").exists() or os.path.exists(f"/proc/{pid}") and "zombie" not in open(f"/proc/{pid}/status").read().lower() and (t / "run/t0.pid").exists() and int((t / "run/t0.pid").read_text()) == pid:
        fail("disable must stop the program and keep the flag")
    run("supervise", expect="result=unchanged")
    if not run("status", expect="result=status").rstrip().split("\n")[-2].endswith("\t1"):
        fail("status must say the tunnel is off")
    run("enable", "OpkgTun1", expect="result=changed")
    run("enable", "OpkgTun1", expect="result=unchanged")
    run("supervise", expect="result=changed")
    time.sleep(0.3)

    # Remove: program stopped, Keenetic connection gone and saved, files deleted.
    run("remove", "OpkgTun7", expect="error=unknown_tunnel")
    (st / "saved").unlink()
    run("remove", "OpkgTun1", expect="result=changed")
    if list((t / "etc").glob("t[0-9]*")) or (t / "etc/tunnels.tsv").read_text().strip():
        fail("remove left files")
    if "OpkgTun1" in ifaces() or "OpkgTun0" not in ifaces() or not (st / "saved").exists():
        fail(f"remove must delete only its own connection and save: {ifaces()}")
    run("stop", expect="result=changed")
    if list((t / "run").glob("*.pid")):
        fail("a program kept running after remove")

    everything = "".join(outs) + (t / "engine.log").read_text() + (st / "ndmc.log").read_text()
    if KEY in everything or HPK in everything:
        fail("a key reached the output, the log or a Keenetic command")

    # The pinned sums are the reproducible build's.
    sums = {name: s for s, name in (l.split() for l in (ROOT / "tools/vward-awg/SHA256SUMS").read_text().splitlines())}
    engine = ENGINE.read_text()
    for arch in ("mipsle", "mips", "arm64", "arm"):
        if f"{arch}) echo {sums['vward-awg-linux-' + arch]} ;;" not in engine:
            fail(f"the engine pins another {arch} build than tools/vward-awg/SHA256SUMS")

print("AWG_ENGINE=PASS")
