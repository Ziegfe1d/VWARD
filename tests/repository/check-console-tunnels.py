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


script = "\n".join([piece("const TUN_TYPE =", "// Switched off in Keenetic"), piece("const tunOff =", "async function tunnelOp("),
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
want = ["WireGuard", "модуль AmneziaWG", "модуль AmneziaWG · программа остановлена", "модуль AmneziaWG", "VLESS", "Proxy"]
if got != want:
    fail(f"list lines: {got} want {want}")
if "рукопожатие" in piece("const tunSub = t => {", "\n};\n"):
    fail("the list shows no handshake")
for need in ("'<span class=\"st ok\">по умолчанию</span>'", "'Сделать туннелем по умолчанию'", "['Туннель по умолчанию', managed ? 'Да' : 'Нет'",
             "' · модуль AmneziaWG (VWARD)'", "t.endpoint || (e && e.endpoint) || (v && (v.server_name ? v.server_name + ' · ' + v.server : v.server))", "['Память программы'",
             "const rx = t.rx != null ? t.rx : e && e.rx", "btn('ask', 'close', 'Выключить', 'danger', ' data-confirm=\"tunnel-down\"'",
             "'tunnel-down': () => tunnelState('down', current.slice(2))", "canOff = name !== prof().tunnel_interface && !tunOff(t)", "mp[0] + tunnelProbePanel(name) + tunnelTrafficPanel(name) + mp.slice(1).join('')"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
if "для маршрутов" in JS:
    fail("the default tunnel is called «по умолчанию» everywhere")
if "    restart|up|down|delete|subnet-add|subnet-remove)" not in API or 'set -- tunnel-state "$TOP" "$TNAME"' not in API or "rx: ($t[6] // \"\" | tonumber? // null)" not in API or "off: ($t[5] == \"1\")" not in API:
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
# Switched off by the owner (owner 2026-10-12): the Overview and the tunnel page say the lists
# go direct, the bell stays quiet (check-console-tunnel-status.py runs it).
for need in ("!on.some(t => t.name === prof().tunnel_interface) ? 'списки идут напрямую'",
             "down = tunnels.filter(t => !isTrue(t.connected) && !tunOff(t) && !tunGuardOff(t))",
             "он назначен по умолчанию, списки VPN идут напрямую"):
    if need not in JS:
        fail(f"a default tunnel switched off outside the Panel: lacks {need}")
if "'Туннель по умолчанию выключен в Keenetic'" in JS:
    fail("a tunnel the owner switched off is no notification")
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
    if r.stdout != "reason=no interface Wireguard0: (error) static route 1.2.3.4 uses Wireguard0\nerror=router_rejected\n":
        fail(f"the router's reply to a rejected command: {r.stdout!r}")
# A tunnel Keenetic has switched off is «down» for the Panel even while its program keeps the
# adapter up (an OpkgTun of Xray: `state: up`, conf layer disabled; a Viva 2026-10-12).
_wgi = API[API.index('WG_INTERFACES="$('):]
_wgi = _wgi[_wgi.index('--arg wan'):]
_prog = _wgi[_wgi.index("'") + 1:_wgi.index("' 2>/dev/null")]
_ifs = {"OpkgTun2": {"type": "OpkgTun", "state": "up", "link": "down", "summary": {"layer": {"conf": "disabled"}}},
        "Wireguard0": {"type": "Wireguard", "state": "up", "link": "up", "summary": {"layer": {"conf": "running"}}}}
_r = subprocess.run(["jq", "-c", "--arg", "types", "wireguard opkgtun", "--arg", "wan", "", "--arg", "awgn", " Wireguard0 ", _prog], input=json.dumps(_ifs), text=True, capture_output=True)
_st = {t["name"]: (t["state"], t["awg"]) for t in json.loads(_r.stdout or "[]")}
# And a WireGuard connection with obfuscation (`wireguard asc`) is AmneziaWG, not «WireGuard».
if _st != {"OpkgTun2": ("down", False), "Wireguard0": ("up", True)}:
    fail(f"switched off in Keenetic must read as off: {_st} {_r.stderr}")
if "t.type === 'wireguard' && t.awg ? 'AmneziaWG'" not in JS:
    fail("an AmneziaWG connection of the firmware is named AmneziaWG")
for need in ("TWHY=\"$(printf '%s\\n' \"$TALL\" | sed -n 's/^reason=//p' | tail -n 1)\"", "{reason:$w}"):
    if need not in API:
        fail(f"the API passes the router's reply: lacks {need}")
if "' (ответ роутера: ' + x.reason + ')'" not in JS or "x.error === 'conf_unknown_setting'" not in JS:
    fail("the Panel shows the router's reply")
# Keenetic writes a route to one address without its mask («ip route 192.0.2.9 OpkgTun2 auto»):
# the delete moves it, and an added /32 subnet is found (it was «199 of 200», Viva 2026-10-12).
import os, tempfile
route_awk = HELPER[HELPER.index("ROUTE_AWK='"):HELPER.index("'\n", HELPER.index("ROUTE_AWK='") + 11) + 2]
present = HELPER[HELPER.index("subnet_present() {"):HELPER.index("\n}\n", HELPER.index("subnet_present() {")) + 3]
with tempfile.TemporaryDirectory() as tmp:
    rc = os.path.join(tmp, "rc")
    with open(rc, "w") as f:
        f.write("ip route 198.51.100.0 255.255.255.0 OpkgTun2 auto\nip route 192.0.2.9 OpkgTun2 auto\nip route 203.0.113.0 255.255.255.0 ISP auto\n")
    sh = route_awk + present + f"""RUNCFG={rc}
subnet_present 192.0.2.9 255.255.255.255 OpkgTun2 && echo one
subnet_present 198.51.100.0 255.255.255.0 OpkgTun2 && echo net
subnet_present 192.0.2.9 255.255.255.255 Wireguard0 || echo other
awk -v i=OpkgTun2 "$ROUTE_AWK"' $1 == "ip" && $2 == "route" && rdev() == i {{print $3 " " rmask()}}' "$RUNCFG"
"""
    r = subprocess.run(["sh", "-c", sh], text=True, capture_output=True)
    if r.stdout.split("\n") != ["one", "net", "other", "198.51.100.0 255.255.255.0", "192.0.2.9 255.255.255.255", ""]:
        fail(f"a route to one address: {r.stdout!r} {r.stderr}")
for need in ('"$ROUTE_AWK"\' $1 == "ip" && $2 == "route" && rdev() == i {print $3 " " rmask()}\'',
             '"$ROUTE_AWK"\' $1 == "ip" && $2 == "route" && rdev() == i {f = 1}'):
    if need not in HELPER:
        fail(f"tunnel delete lacks {need}")
# «Резерв и выбор туннеля»: settings only, the tunnels are in «Туннели» (owner 2026-10-12); a
# VLESS tunnel's quality is a page's answer, not ping; the speed carries its date and is not
# shown while measuring is off.
if "panel('Несколько туннелей'" in JS or "panel('Резерв и выбор туннеля'" not in JS or "раз в минуту пинг через каждый туннель" in JS:
    fail("the reserve panel lists no tunnels and says nothing of ping")
q = piece("const tqSpeed =", "const TQ_CRITERIA") + r"""
const fmtTime = x => 'T' + x;
let S = { tq: { auto: { speed: 'night' } }, awg: { vless: { tunnels: [{ name: 'OpkgTun1' }] } } };
const vlessOf = n => S.awg.vless.tunnels.find(x => x.name === n);
const a = tqText({ name: 'OpkgTun1', avg_ms: 120, loss_pct: 0, speed_mbps: 7.9, speed_at: 5 });
const b = tqText({ name: 'Wireguard0', avg_ms: 40, loss_pct: 0 });
S.tq.auto.speed = 'off';
const c = tqText({ name: 'OpkgTun1', avg_ms: 120, loss_pct: 0, speed_mbps: 7.9, speed_at: 5 });
console.log(JSON.stringify([a, b, c]));
"""
r = subprocess.run(["node", "-e", q], text=True, capture_output=True)
if r.returncode:
    fail(r.stderr[-400:])
got = json.loads(r.stdout)
if got != ["ответ страницы 120 мс · потери 0% · скорость 7,9 Мбит/с (T5000)", "пинг 40 мс · потери 0%", "ответ страницы 120 мс · потери 0%"]:
    fail(f"quality lines: {got}")
# The API switches a tunnel in the request (no background job): the helper's answer, and the
# router's own words on a refusal.
import shutil as _sh, tempfile as _tf
with _tf.TemporaryDirectory() as tmp:
    helper = os.path.join(tmp, "helper")
    with open(helper, "w") as f:
        f.write('#!/bin/sh\necho "$*" >> "$(dirname "$0")/calls"\n'
                'case "$3" in Wireguard9) echo "reason=Command::Base error: not found"; echo "error=router_rejected" ;; *) echo "result=changed" ;; esac\n')
    os.chmod(helper, 0o755)
    os.makedirs(os.path.join(tmp, "tmp"))
    def post(body):
        e = {"PATH": os.environ["PATH"], "REQUEST_METHOD": "POST", "QUERY_STRING": "action=tunnel-conf", "JQ": _sh.which("jq"),
             "VWARD_PROFILE_LIB": "/nonexistent", "VWARD_CONSOLE_CONFIG_BIN": helper, "CONTENT_TYPE": "application/x-www-form-urlencoded",
             "CONTENT_LENGTH": str(len(body)), "HTTP_X_VWARD_REQUEST": "console", "VWARD_ROOT_PREFIX": tmp,
             "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh")}
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e, input=body, text=True, capture_output=True, timeout=30)
        return json.loads(r.stdout.split("\n\n", 1)[1])
    if post("op=up&name=Wireguard2") != {"ok": True, "result": "changed"} or post("op=down&name=Wireguard2") != {"ok": True, "result": "changed"}:
        fail("the API switches a tunnel in the request")
    if post("op=up&name=Wireguard9") != {"ok": False, "error": "router_rejected", "reason": "Command::Base error: not found"}:
        fail("a refusal carries the router's reply")
    if open(os.path.join(tmp, "calls")).read().splitlines() != ["tunnel-state up Wireguard2", "tunnel-state down Wireguard2", "tunnel-state up Wireguard9"]:
        fail("the API asks the helper for tunnel-state")
print("CONSOLE_TUNNELS=PASS")
