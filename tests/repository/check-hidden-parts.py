#!/usr/bin/env python3
"""Frozen parts (owner 13.11.2026, fix.39): hidden in the Panel and off for good, code kept.

sentinel («Контроль состояния»), «Наблюдение за памятью», «Ремонт пакетов Entware», «Контроль
Wi-Fi клиентов» and sing-box are frozen (ROADMAP §8): not shown, not run, whatever the owner
switched on before (NAME.on, all.on), not developed. Nothing is removed: their code stays and their
files ship as they are, so a part can come back. This test keeps the freeze whole:
  * settings-registry.json «parts_hidden» names them; they are still parts (their files are there);
  * the admission library keeps the switchable ones off: vward_extra / vward_component_enabled
    say «off» even with NAME.on and all.on, other parts behave as before;
  * the Panel helper does not switch them on (retired_part);
  * the router's answers leave them out (parts list, components graph, versions);
  * the Panel has no section, card, job, journal tab or search entry for them.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(m):
    raise SystemExit(f"HIDDEN_PARTS=FAIL: {m}")


REG_PATH = ROOT / "config/settings/settings-registry.json"
REG = json.loads(REG_PATH.read_text(encoding="utf-8"))
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
HELPER = (ROOT / "components/console/scripts/vward-console-config.sh").read_text(encoding="utf-8")
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")

EXPECTED = ["sentinel", "memory-watch", "repair", "wifi-client-guard", "singbox"]
hidden = REG.get("parts_hidden")
if hidden != EXPECTED:
    fail(f"parts_hidden must name the five frozen parts: {hidden}")
parts = {p["id"]: p for p in REG["parts"]}
for h in hidden:
    if h not in parts:
        fail(f"{h}: a hidden part stays a part: its code and files are kept")
switchable = [h for h in hidden if parts[h]["switch"] in ("extra", "component")]
m = re.search(r'^VWARD_RETIRED_PARTS=\$\{VWARD_RETIRED_PARTS-"([^"]*)"\}$', LIB.read_text(encoding="utf-8"), re.M)
if not m or m.group(1).split() != switchable:
    fail(f"the admission library keeps off {m and m.group(1)!r}, the registry {switchable}")

# The router: off for good, whatever was switched on; other parts as before.
with tempfile.TemporaryDirectory() as t:
    st = Path(t)
    for n in ("sentinel", "memory-watch", "repair", "flash-watch", "all"):
        (st / f"{n}.on").write_text("")
    probe = " ".join(f'vward_extra {n} && echo {n}=on || echo {n}=off;' for n in ("sentinel", "memory-watch", "repair", "flash-watch", "backup"))
    probe += (' vward_component_enabled wifi-client-guard && echo wifi=on || echo wifi=off;'
              ' vward_component_enabled wan-guard && echo wan=on || echo wan=off;'
              ' (vward_component_gate wifi-client-guard; echo gate=passed)')
    out = subprocess.run(["sh", "-c", f'VWARD_COMPONENT_STATE="{st}"; . "{LIB}"; {probe}'],
                         capture_output=True, text=True).stdout.split()
    want = ["sentinel=off", "memory-watch=off", "repair=off", "flash-watch=on", "backup=on",
            "wifi=off", "wan=on", "COMPONENT_DISABLED=wifi-client-guard"]
    if out != want:
        fail(f"RED: frozen parts must stay off with NAME.on and all.on: {out}")

# The Panel helper: a frozen part is not switched on (switched off: as before).
cut = lambda name: HELPER[HELPER.index(name + "() {"):HELPER.index("\n}\n", HELPER.index(name + "() {")) + 3]
fn = cut("reg_has") + cut("op_extra")
with tempfile.TemporaryDirectory() as t:
    pre = (f'COMPONENT_STATE={t}; JQ=jq; SETTINGS_REG={REG_PATH}; die() {{ echo "error=$1"; exit 1; }}; '
           'done_ok() { echo "result=$2"; exit 0; }\n')
    op = lambda *a: subprocess.run(["sh", "-c", pre + fn + 'op_extra "$@"', "x", *a], capture_output=True, text=True).stdout.strip()
    got = [op("sentinel", "1"), op("repair", "1"), op("sentinel", "0"), op("flash-watch", "1")]
    if got != ["error=retired_part", "error=retired_part", "result=unchanged", "result=changed"]:
        fail(f"RED: the helper switches a frozen part on: {got}")
comp = cut("op_component")
if "[ \"$2\" = 0 ] || ! reg_has '.parts_hidden[]?' \"$1\" || die retired_part 64" not in comp:
    fail("op_component must refuse to switch a frozen component on")
if "retired_part: '" not in JS:
    fail("the Panel has no words for retired_part")

# The router's answers: the parts list (run as the API runs it), the components graph, versions.
a = API.index("PARTS_JSON=$(printf"); b = API.index('[ -n "$PARTS_JSON" ]', a)
res = subprocess.run(["sh", "-c", f'JQ=jq; PARTS_REG="{REG_PATH}"; EXTRAS_ALL=0; PARTS_FACTS=""\n' + API[a:b] + 'printf "%s" "$PARTS_JSON"'],
                     capture_output=True, text=True)
try:
    pj = json.loads(res.stdout)
except ValueError:
    fail(f"the parts answer is not JSON: {res.stdout[:200]!r} {res.stderr[:200]!r}")
shown = [p["id"] for p in pj["list"]]
if set(shown) & set(hidden) or len(shown) != len(parts) - len(hidden) or pj.get("hidden") != hidden:
    fail(f"RED: the router shows frozen parts: {sorted(set(shown) & set(hidden))}, hidden={pj.get('hidden')}")
for need in ("--argjson hidden \"${HIDDEN_PARTS:-[]}\" '[.components[] | select(.id | IN($hidden[]) | not) |",
             "'.components // {} | with_entries(select(.key | IN($hidden[]) | not))'"):
    if need not in API:
        fail(f"the router's answer keeps frozen components: {need!r}")

# The Panel: no section, card, job, journal tab or search entry.
def block(start):
    i = JS.index(start); return JS[i:JS.index("];", i)]
if "'wifi-client-guard'" in block("const COMPONENTS = ["):
    fail("COMPONENTS keeps «Контроль Wi-Fi клиентов»")
if "'wifi'" in block("const CARD_IDS = ["):
    fail("the overview keeps the Wi-Fi card")
tabs = re.findall(r"\{ id: '([a-z]+)', label: '", block("const LOG_TABS = ["))
if {"wifi", "sentinel"} & set(tabs):
    fail(f"«Журналы» keep tabs of frozen parts: {tabs}")
if re.search(r"\['(wifi|wan)', 'Wi-Fi", block("const SEARCH_INDEX = [")):
    fail("the search still finds the Wi-Fi page")
for gone in ("panel('Агент реального времени'", "panel('Под наблюдением агента'", "panel('Домашняя сеть', kv([['Wi-Fi клиенты'",
             "title: 'Wi-Fi: ' + wc"):
    if gone in JS:
        fail(f"the Panel still shows {gone!r}")
for need in ("const partHidden = id => ((st().parts && st().parts.hidden) || []).includes(id);",
             ".filter(x => !partHidden(JOB_COMPONENT[x.name] || x.component));"):
    if need not in JS:
        fail(f"the Panel lacks {need!r}")
for page in ("overview", "wan"):
    line = next(l for l in JS.splitlines() if l.startswith(f"  {{ id: '{page}', title: "))
    if "'wifi'" in line:
        fail(f"{page} still loads Wi-Fi data")
print(f"HIDDEN_PARTS=PASS: {len(hidden)} parts hidden, {len(switchable)} kept off on the router")
