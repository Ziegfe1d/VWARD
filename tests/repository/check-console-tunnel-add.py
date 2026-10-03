#!/usr/bin/env python3
"""Adding a tunnel from a .conf, and switching a tunnel off: the Panel's writer on a fake router."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

PRIV = "A" * 42 + "A="
PUB = "B" * 42 + "A="
CONF = f"""[Interface]
PrivateKey = {PRIV}
Address = 10.8.16.6/32
MTU = 1280

[Peer]
PublicKey = {PUB}
AllowedIPs = 0.0.0.0/0
Endpoint = vpn.example.net:51820
PersistentKeepalive = 25
"""

# A stateful fake Keenetic CLI: «interface X» opens a block, its settings land in it, «no interface X»
# removes it.  Flags: .noaddr - the address command is refused; .down-refused - «interface X down» fails.
FAKE_NDMC = r"""#!/bin/sh
CFG="@CFG@"
[ "$1" = -c ] || exit 2
cmd=$2
echo "$cmd" >> "$CFG.log"
case "$cmd" in
  "show running-config") cat "$CFG"; exit 0 ;;
  "system configuration save") echo saved; exit 0 ;;
esac
set -- $cmd
if [ "$1" = no ] && [ "$2" = interface ] && [ $# -eq 3 ]; then
  awk -v n="interface $3" '$0 == n {skip = 1; next} skip && /^!/ {skip = 0; next} !skip' "$CFG" > "$CFG.new"; mv "$CFG.new" "$CFG"; echo ok; exit 0
fi
[ "$1" = interface ] || { echo ok; exit 0; }
if [ $# -eq 2 ]; then printf 'interface %s\n!\n' "$2" >> "$CFG"; echo ok; exit 0; fi
if [ "$3" = ip ] && [ "$4" = address ] && [ -e "$CFG.noaddr" ]; then echo "Network::Interface::Base: error[1]: address conflicts"; exit 0; fi
if [ "$3" = down ] && [ -e "$CFG.down-refused" ]; then echo "Network::Interface::Base: error[1]: refused"; exit 0; fi
i=$2; shift 2
awk -v n="interface $i" -v l="    $*" '{print} $0 == n {print l}' "$CFG" > "$CFG.new"; mv "$CFG.new" "$CFG"
echo ok
"""

RUNNING = """interface Wireguard0
    ip address 10.8.16.6 255.255.255.255
!
interface Wireguard1
    ip address 10.9.0.2 255.255.255.255
!
"""


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    (tools / "ndmc").write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); (tools / "ndmc").chmod(0o755)
    (tmp / "interface.json").write_text('{"Wireguard0":{"type":"Wireguard","security-level":"public"},"Wireguard1":{"type":"Wireguard","security-level":"public"}}')
    curl = tools / "curl"
    curl.write_text(f"""#!/bin/sh
for URL do :; done
case "$URL" in
  */show/interface) cat "{tmp}/interface.json" ;;
  */show/interface?name=*) echo '{{"id":"x","state":"up","link":"up","wireguard":{{"peer":[{{"online":true,"last-handshake":3}}]}}}}' ;;
  */show/interface/system-name?name=*) echo '"nwg0"' ;;
  */rci/) cat >/dev/null; echo '[{{"parse":{{"status":[{{"status":"message"}}]}}}}]' ;;
  *) exit 22 ;;
esac
""")
    curl.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br2\nVWARD_LAN_INTERFACE=Bridge2\n"
                       "VWARD_WAN_DEVICE=eth2.4\nVWARD_WAN_INTERFACE=ISP\nVWARD_TUNNEL_INTERFACE=Wireguard1\nVWARD_POLICY_GROUP=streaming\n")
    devconf.chmod(0o600)
    engine = tools / "engine"
    engine.write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/engine.log"\necho result=changed\n'); engine.chmod(0o755)
    (tmp / "etc/awg").mkdir(parents=True)
    env = os.environ | {
        "VWARD_NDMC": str(tools / "ndmc"), "VWARD_CURL_BIN": str(curl), "VWARD_DEVICE_CONFIG": str(devconf),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"), "VWARD_ROUTE_STATE": str(tmp / "route"),
        "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"),
        "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"), "VWARD_CONSOLE_CACHE_DIR": str(tmp / "cache"),
        "VWARD_TUNNEL_HANDSHAKE_WAIT": "0", "VWARD_AWG_ETC": str(tmp / "etc/awg"),
        "VWARD_AWG_ENGINE_BIN": str(engine), "VWARD_VLESS_ENGINE_BIN": str(engine), "VWARD_VLESS_ETC": str(tmp / "etc/awg"),
    }

    def run(*args):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        return out, r

    conf = tmp / "t.conf"
    def put(text):
        conf.write_text(text); conf.chmod(0o600)

    # The address is already on Wireguard0: refused before anything is written to the router.
    put(CONF)
    before = cfg.read_text()
    out, r = run("tunnel-conf", "create", str(conf), "Finland")
    if out != "error=tunnel_address_taken" or r.returncode != 64:
        fail(f"a taken address must be refused: {out!r} rc={r.returncode} {r.stderr.strip()}")
    if cfg.read_text() != before or "interface Wireguard2" in (tmp / "running.cfg.log").read_text() if (tmp / "running.cfg.log").exists() else False:
        fail("a refused create must not touch the router")
    # The same check on the in-place replace of another tunnel.
    put(CONF)
    out, r = run("tunnel-conf", "replace", str(conf), "Wireguard1")
    if out != "error=tunnel_address_taken":
        fail(f"replace into a taken address: {out!r}")
    # Replacing the tunnel that owns the address is not a conflict with itself.
    out, r = run("tunnel-conf", "replace", str(conf), "Wireguard0")
    if out == "error=tunnel_address_taken":
        fail("a tunnel's own address must not conflict with itself")

    # A free address: the tunnel appears, answers, is saved; the key stays out of arguments.
    put(CONF.replace("10.8.16.6", "10.8.16.7"))
    out, r = run("tunnel-conf", "create", str(conf), "Finland")
    if out != "result=changed":
        fail(f"create: {out!r} {r.stdout!r} {r.stderr.strip()}")
    text = cfg.read_text(); log = (tmp / "running.cfg.log").read_text()
    if "interface Wireguard2" not in text or "ip address 10.8.16.7 255.255.255.255" not in text:
        fail(f"the new tunnel is missing: {text!r}")
    if "system configuration save" not in log.splitlines()[-1]:
        fail("the configuration must be saved last")
    if PRIV in log or PRIV in (tmp / "audit.log").read_text():
        fail("the private key must not reach argv or the audit log")
    if not (tmp / "etc/tunnels/Wireguard2/current.conf").exists():
        fail("the applied .conf must be kept")

    # The router refuses the address after all: the new interface is removed again.
    put(CONF.replace("10.8.16.6", "10.8.16.8"))
    (tmp / "running.cfg.noaddr").touch()
    before = cfg.read_text()
    out, r = run("tunnel-conf", "create", str(conf), "Sweden")
    (tmp / "running.cfg.noaddr").unlink()
    if out != "error=conf_rejected_address" or cfg.read_text() != before:
        fail(f"a refused address must roll the new interface back: {out!r}")

    # Keenetic now lists the new tunnel.
    (tmp / "interface.json").write_text('{"Wireguard0":{"type":"Wireguard","security-level":"public"},"Wireguard1":{"type":"Wireguard","security-level":"public"},"Wireguard2":{"type":"Wireguard","security-level":"public"}}')
    (tmp / "map.tsv").unlink(missing_ok=True)
    # Switching off: the default tunnel stays; an ordinary one goes down and is saved.
    out, _ = run("tunnel-state", "down", "Wireguard1")
    if out != "error=main_tunnel":
        fail(f"the default tunnel must not be switched off: {out!r}")
    before_log = (tmp / "running.cfg.log").read_text()
    out, _ = run("tunnel-state", "down", "Wireguard2")
    if out != "result=changed":
        fail(f"down: {out!r}")
    new_log = (tmp / "running.cfg.log").read_text()[len(before_log):].splitlines()
    if new_log[-2:] != ["interface Wireguard2 down", "system configuration save"]:
        fail(f"down must switch the interface off, then save: {new_log}")
    # Refused by the router: nothing is saved, the engine is given back.
    (tmp / "running.cfg.down-refused").touch()
    out, _ = run("tunnel-state", "down", "Wireguard2")
    (tmp / "running.cfg.down-refused").unlink()
    if out != "error=router_rejected":
        fail(f"a refused down: {out!r}")
    if (tmp / "change.lock").exists():
        fail("lock left behind")

print("CONSOLE_TUNNEL_ADD=PASS")
