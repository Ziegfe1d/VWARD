#!/usr/bin/env python3
"""Tunnel statuses in the Panel (owner 2026-10-12).

- A tunnel the owner switched off is the owner's choice: no warning, no bell, a grey
  «Выключен»; the Overview counts only switched-on tunnels; all off - «VPN выключен».
- A tunnel the VPN agent switched off is a warning in the bell: when and why, the sites
  go direct, the agent turns it back on.
- A switched-on tunnel that is not connected is a warning, as before.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(msg):
    raise SystemExit(f"CONSOLE_TUNNEL_STATUS=FAIL: {msg}")


if not shutil.which("node"):
    print("CONSOLE_TUNNEL_STATUS=SKIPPED (node not found)")
    sys.exit(0)


def grab(start, end="\n}\n"):
    i = JS.index(start)
    return JS[i:JS.index(end, i) + len(end)]


def line(start):
    i = JS.index(start)
    return JS[i:JS.index("\n", i) + 1]


code = "".join([
    line("const isTrue = "), line("const FO_WHY = "), line("const foText = "), grab("const tunPill = ", "];\n"), line("const tunGuardOff = "),
    line("const tunOff = "), line("const viaIs = "), line("const vpnDirect = "),
    grab("function tunDupAddresses("), grab("function notifications() {"), grab("function cardData(id) {"),
])
harness = """
let STATUS = null; const S = { errors: {}, lists: null };
const st = () => STATUS || {}; const prof = () => ({ tunnel_interface: 'OpkgTun2' }); const plat = () => ({});
const tunLabel = n => n; const fmtTime = t => 'T' + t; const num = v => v == null ? null : Number(v); const fmtKB = v => v; const fmtInt = v => v;
const TUNBUSY = {}, TUNUP = {}; const TUN_BUSY = { up: 'Включение', down: 'Выключение', restart: 'Перезапуск' };
const phaseText = v => v; const plural = (n, a) => a; const comp = () => null; const awgLost = () => []; const durText = v => v; const fmtSpeed = v => v;
""" + code + """
const T = (name, connected, state) => ({ name, description: name, connected: connected ? 'yes' : 'no', state });
const run = wg => { STATUS = { wg }; S.status = STATUS; return { notes: notifications().map(n => n.title + ' | ' + n.text), card: cardData('vpn'), pills: (wg.interfaces || []).map(t => tunPill(t).join(':')) }; };
const out = {
  ownerOff: run({ interfaces: [T('OpkgTun0', false, 'down'), T('OpkgTun2', true, 'up'), T('Wireguard0', false, 'down')] }),
  allOff: run({ interfaces: [T('OpkgTun0', false, 'down'), T('OpkgTun2', false, 'down')] }),
  silent: run({ interfaces: [T('OpkgTun0', false, 'down'), T('OpkgTun2', false, 'up')] }),
  agentOff: run({ interfaces: [T('OpkgTun0', false, 'down'), T('OpkgTun2', false, 'down')], failopen_active: true, failopen_at: 1791770000, failopen_reason: ['silent', 'restart_servers', 'no_fallback'] }),
};
// Switched in place: what is going on, then «Подключение» until the server answers.
TUNBUSY.OpkgTun0 = 'down'; out.busy = run({ interfaces: [T('OpkgTun0', true, 'up')] }).pills; delete TUNBUSY.OpkgTun0;
TUNUP.OpkgTun0 = 1; out.connecting = run({ interfaces: [T('OpkgTun0', false, 'up')] }).pills; delete TUNUP.OpkgTun0;
console.log(JSON.stringify(out));
"""
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    fail(r.stderr[-1200:])
o = json.loads(r.stdout)

if o["busy"] != [":Выключение"] or o["connecting"] != [":Подключение"]:
    fail(f"the status while switching: {o['busy']} {o['connecting']}")
# Switched off by the owner: quiet; only switched-on tunnels counted.
if o["ownerOff"]["notes"] or o["ownerOff"]["card"]["pill"] != ["ok", "Работает"] or o["ownerOff"]["card"]["value"] != "1 из 1" or "выключены: 2" not in o["ownerOff"]["card"]["sub"]:
    fail(f"tunnels the owner switched off are no fault: {o['ownerOff']}")
if o["ownerOff"]["pills"] != [":Выключен", "ok:В сети", ":Выключен"]:
    fail(f"«Выключен» is grey: {o['ownerOff']['pills']}")
if o["allOff"]["notes"] or o["allOff"]["card"]["value"] != "Выключен" or o["allOff"]["card"]["pill"] != ["", "Выключен"]:
    fail(f"every tunnel off by the owner: «VPN выключен», no warning: {o['allOff']}")
# Switched on and silent: a warning, as before.
if not any(n.startswith("VPN не в сети") or n.startswith("Не все туннели в сети") for n in o["silent"]["notes"]) or o["silent"]["card"]["pill"] != ["warn", "Внимание"] or o["silent"]["card"]["value"] != "0 из 1":
    fail(f"a switched-on tunnel that is not connected warns: {o['silent']}")
# Switched off by the VPN agent: the bell says when and why, once.
ag = [n for n in o["agentOff"]["notes"] if "агентом VPN" in n]
if len(ag) != 1 or "T1791770000000" not in ag[0] or "другие серверы подписки не помогли" not in ag[0] or "включит его сам" not in ag[0]:
    fail(f"the agent's switch-off: when and why: {o['agentOff']['notes']}")
if any("не в сети" in n.lower() for n in o["agentOff"]["notes"]) or o["agentOff"]["pills"][1] != "warn:Выключен агентом":
    fail(f"the agent's switch-off is told once, as such: {o['agentOff']}")
print("CONSOLE_TUNNEL_STATUS=PASS")
