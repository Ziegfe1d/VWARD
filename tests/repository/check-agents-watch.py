#!/usr/bin/env python3
"""Observation mode of the agents (the default, owner 2026-10-18) («Наблюдение | Действие», fix.28.6): an agent that only watches
writes down what it would do (a proposed action) and changes nothing; the mode is set for all
agents or one; what keeps the home online and the Panel reachable is never gated."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"


def fail(message: str) -> None:
    raise SystemExit(f"AGENTS_WATCH=FAIL: {message}")


read = lambda p: (ROOT / p).read_text(encoding="utf-8")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    conf, prop = tmp / "etc/agents.conf", tmp / "proposed.tsv"
    env = {"PATH": "/usr/bin:/bin", "VWARD_AGENTS_CONF": str(conf), "VWARD_PROPOSED": str(prop)}

    def sh(script):
        r = subprocess.run(["sh", "-c", f'. "{LIB}"; {script}'], env=env, text=True, capture_output=True, timeout=30)
        return r.stdout.strip()

    modes = "for a in network components updates maintenance; do printf '%s ' $(vward_agent_mode $a); done"
    # No settings: every agent watches (owner 2026-10-18: observation by default) and writes down.
    if sh(modes) != "watch watch watch watch" or sh('vward_agent_acts network x "y" || echo watched') != "watched" or not prop.exists():
        fail("without settings the agents watch and write down what they would do")
    prop.unlink()
    # All watch; one agent acts on its own choice.
    conf.parent.mkdir(parents=True)
    conf.write_text("all=watch\nupdates=act\n")
    if sh(modes) != "watch watch act watch":
        fail(f"modes: {sh(modes)}")
    # Watching: not done, written down once an hour per action.
    out = sh('vward_agent_acts network tunnel-down:T1 "Туннель T1 не отвечает" || echo watched; '
             'vward_agent_acts network tunnel-down:T1 "Туннель T1 не отвечает" || echo watched; '
             'vward_agent_acts network wan-bounce "Интернет" || echo watched; '
             'vward_agent_acts updates ext-upgrade:curl "curl" && echo acts')
    rows = [l.split("\t") for l in prop.read_text().splitlines()]
    if out.split() != ["watched", "watched", "watched", "acts"] or [r[1:3] for r in rows] != [["network", "tunnel-down:T1"], ["network", "wan-bounce"]]:
        fail(f"proposals: {out!r} {rows}")
    if rows[0][3] != "Туннель T1 не отвечает":
        fail("the proposal keeps its text")

    # The Panel's helper: all=… replaces every choice; one agent: its own line.
    root = tmp / "root"; (root / "tmp").mkdir(parents=True)
    henv = os.environ | {"VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_AGENTS_CONF": str(conf), "VWARD_ROOT_PREFIX": str(root),
                         "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"), "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"),
                         "VWARD_ADMISSION_LIB": str(LIB), "VWARD_COMPONENT_STATE": str(tmp / "components"), "VWARD_ROUTE_STATE": str(tmp / "route")}
    helper = lambda *a: subprocess.run(["sh", str(HELPER), *a], env=henv, text=True, capture_output=True, timeout=60).stdout.strip().splitlines()[-1:]
    if helper("agents-mode", "all", "act") != ["result=changed"] or conf.read_text() != "all=act\n":
        fail(f"all=act: {conf.read_text()!r}")
    if helper("agents-mode", "network", "watch") != ["result=changed"] or conf.read_text() != "all=act\nnetwork=watch\n":
        fail(f"network=watch: {conf.read_text()!r}")
    if helper("agents-mode", "network", "watch") != ["result=unchanged"]:
        fail("the same choice again changes nothing")
    for bad in (("all", "maybe"), ("sentinel", "watch"), ("network", "act;reboot")):
        if helper("agents-mode", *bad) != ["error=invalid_value"]:
            fail(f"a wrong value must be refused: {bad}")

# Where the agents ask before acting.
GATES = {
    "components/tunnel-guard/scripts/vward-tunnel-guard.sh": ['[ "$(vward_agent_mode network)" = act ] || MODE="WATCH"', 'vward_agent_acts network "list-move:$1"', 'vward_agent_acts network "tunnel-down:'],
    "components/wan-guard/scripts/vward-wan-guard.sh": ["vward_agent_acts network wan-bounce", "vward_agent_acts network dhcp-renew"],
    "components/runtime/scripts/vward-cron-supervisor.sh": ['vward_agent_acts components "mem-restart:$1"', 'vward_agent_acts components "hung:$WS"', 'vward_agent_acts components "restart:$AN"'],
    "components/console/scripts/vward-console-config.sh": ['vward_agent_acts updates "ext-upgrade:$dp_pkg"'],
    "components/runtime/scripts/vward-housekeeping.sh": ['vward_agent_acts maintenance "repair:$rp_name"', "vward_agent_acts maintenance repair:curl-https", "vward_agent_acts maintenance repair:doh"],
}
for path, needs in GATES.items():
    src = read(path)
    for need in needs:
        if need not in src:
            fail(f"{path} must ask before acting: {need}")
# Never gated: starting what stopped, the Panel, SSH, the DNS fail-open, VWARD's own updates.
sup = read("components/runtime/scripts/vward-cron-supervisor.sh")
body = lambda name: re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", sup, re.S | re.M).group(0)
for name in ("start_of",):
    if "vward_agent_acts" in body(name):
        fail(f"{name} must never wait for the owner")
if "vward_agent_acts" in read("components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh") or "vward_agent_acts" in read("components/update-engine/vward-update-watch.sh"):
    fail("the DNS fail-open and VWARD's own updates are never gated")

# The Panel: the slider, the always-on rows, the proposals.
api, js = read("web/cgi-bin/api.cgi"), read("web/assets/vward-console.js")
for need in ("journal|agents-mode) set --", "agents:{mode:$agents_mode,proposed:$proposed}"):
    if need not in api:
        fail(f"the API lacks {need}")
for need in ("'d-agents': { title: 'Агенты'", "data-agent-mode=", "op: 'agents-mode'", "'Наблюдение'", "'Действие'", "panel('Работают всегда'", "panel('Предполагаемые действия'"):
    if need not in js:
        fail(f"the Panel lacks {need}")
print("AGENTS_WATCH=PASS")
