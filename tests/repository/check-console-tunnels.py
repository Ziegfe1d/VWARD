#!/usr/bin/env python3
"""VPN: the list says which tunnel is the default one («по умолчанию») and each tunnel's
kind, not its handshake (that is on the tunnel's page); a tunnel of VWARD's engines shows the
engine's server, handshake, traffic and memory; any tunnel but the default one can be switched
off from the Panel (the engine's program stops too) and on again."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
HELPER = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_TUNNELS=FAIL: {message}")


def piece(start, end):
    a = JS.index(start)
    return JS[a:JS.index(end, a)]


script = "\n".join([piece("const TUN_TYPE =", "// Switched off in Keenetic"), piece("const tunOff =", "// Restart (off and on"),
                    piece("const vlessOf =", "\n")]) + r"""
const isTrue = v => v === true || v === 1 || v === '1' || v === 'true';
let S = { awg: { tunnels: [{ name: 'OpkgTun0', running: true, handshake: 12 }, { name: 'OpkgTun2', running: false }], vless: { tunnels: [{ name: 'OpkgTun1', running: true }] } } };
const st = () => ({ wg: { failopen_active: false } }), prof = () => ({ tunnel_interface: 'Wireguard0' });
console.log(JSON.stringify([
  tunSub({ name: 'Wireguard0', type: 'wireguard', handshake: 6, state: 'up' }),
  tunSub({ name: 'OpkgTun0', type: 'opkgtun', state: 'up' }),
  tunSub({ name: 'OpkgTun2', type: 'opkgtun', state: 'up' }),
  tunSub({ name: 'OpkgTun2', type: 'opkgtun', state: 'down' }),
  tunSub({ name: 'OpkgTun1', type: 'opkgtun', state: 'up' }),
  tunSub({ name: 'Proxy0', type: 'proxy', state: 'up' })]));
"""
r = subprocess.run(["node", "-e", script], text=True, capture_output=True)
if r.returncode:
    fail(r.stderr[-500:])
got = json.loads(r.stdout)
want = ["WireGuard", "контур AmneziaWG", "контур AmneziaWG · программа остановлена", "контур AmneziaWG", "VLESS", "Proxy"]
if got != want:
    fail(f"list lines: {got} want {want}")
if "рукопожатие" in piece("const tunSub = t => {", "\n};\n"):
    fail("the list shows no handshake")
for need in ("'<span class=\"st ok\">по умолчанию</span>'", "'Сделать туннелем по умолчанию'", "['Туннель по умолчанию', managed ? 'Да' : 'Нет'",
             "' · контур AmneziaWG (VWARD)'", "t.endpoint || (e && e.endpoint) || (v && v.server)", "['Память программы'",
             "const rx = t.rx != null ? t.rx : e && e.rx", "btn('ask', 'close', 'Выключить', 'danger', ' data-confirm=\"tunnel-down\"'",
             "'tunnel-down': () => tunnelState('down', current.slice(2))", "canOff = name !== prof().tunnel_interface && !tunOff(t)", "mp[0] + tunnelProbePanel(name) + tunnelTrafficPanel(name) + mp.slice(1).join('')"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
if "для маршрутов" in JS:
    fail("the default tunnel is called «по умолчанию» everywhere")
if "    restart|up|down)" not in API or "rx: ($t[6] // \"\" | tonumber? // null)" not in API or "off: ($t[5] == \"1\")" not in API:
    fail("the API passes down and the engines' traffic and off flag")
body = HELPER[HELPER.index("op_tunnel_state() {"):HELPER.index("op_tunnel_delete() {")]
down = body[body.index('if [ "$1" = down ]; then'):body.index('done_ok "tunnel-state down $2" changed')]
for need in ('[ "$2" != "$VWARD_TUNNEL_INTERFACE" ] || die main_tunnel 64', '"$ENG" disable "$2"', 'ndm "interface $2 down"', "save_router"):
    if need not in down:
        fail(f"switching off lacks {need}")
if '"$ENG" enable "$2"' not in body:
    fail("switching on starts the engine's program again")
# Switched off in Keenetic's own settings while still the default: the Panel must not say the traffic
# goes through the VPN, and must say the lists go direct (card, notification, tunnel page).
for need in ("tunnels.some(t => t.name === prof().tunnel_interface && tunOff(t)) ? 'туннель по умолчанию выключен, списки идут напрямую'",
             "'Туннель по умолчанию выключен в Keenetic'", "down = tunnels.filter(t => !isTrue(t.connected) && !tunOff(t))",
             "он назначен по умолчанию, списки VPN идут напрямую"):
    if need not in JS:
        fail(f"a default tunnel switched off outside the Panel: lacks {need}")
if 'INTERFACE_DISABLED_EXTERNAL' not in (ROOT / "components/tunnel-guard/scripts/vward-tunnel-guard.sh").read_text():
    fail("the guard must leave a tunnel the owner switched off alone")
# A rejected router command: the router's own reply reaches the Panel next to the error,
# one line, without quotes, backslashes or control characters.
import tempfile
fn = lambda name: HELPER[HELPER.index(name + "() {"):HELPER.index("\n}\n", HELPER.index(name + "() {")) + 3]
with tempfile.TemporaryDirectory() as d:
    nd = Path(d) / "ndmc"
    nd.write_text('#!/bin/sh\nprintf \'Command::Interface: \\"x\\" in use\\r\\n(error) static route "1.2.3.4" uses Wireguard0\\n\'\nexit 0\n')
    nd.chmod(0o755)
    sh = fn("die") + fn("ndm") + 'NDMC=%s\nndm "no interface Wireguard0" || die router_rejected\n' % nd
    r = subprocess.run(["sh", "-c", sh], text=True, capture_output=True)
    if r.stdout != "reason=(error) static route 1.2.3.4 uses Wireguard0\nerror=router_rejected\n":
        fail(f"the router's reply to a rejected command: {r.stdout!r}")
for need in ("TWHY=\"$(printf '%s\\n' \"$TALL\" | sed -n 's/^reason=//p' | tail -n 1)\"", "{reason:$w}"):
    if need not in API:
        fail(f"the API passes the router's reply: lacks {need}")
if "(x && x.reason ? ' (ответ роутера: ' + x.reason + ')' : '')" not in JS:
    fail("the Panel shows the router's reply")
print("CONSOLE_TUNNELS=PASS")
