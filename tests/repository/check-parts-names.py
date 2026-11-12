#!/usr/bin/env python3
"""One list of VWARD's parts and their names (fix.38, owner 12.11.2026: «по порядочку, без дублей»).

The parts' registry (config/settings/settings-registry.json) is the only place a part's or an
agent's name and the list of optional parts live. The Panel takes names from the registry the
router sends; the helper and the API check and list part ids from the registry file. A second
list of names anywhere lets one page show a new name and another the old one.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REG = json.loads((ROOT / "config/settings/settings-registry.json").read_text(encoding="utf-8"))
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
HELPER = (ROOT / "components/console/scripts/vward-console-config.sh").read_text(encoding="utf-8")
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
CREG = json.loads((ROOT / "config/components/component-registry.json").read_text(encoding="utf-8"))
errors = []
fail = errors.append

parts = {p["id"]: p for p in REG["parts"]}
titles = [p["title"] for p in REG["parts"]]
if len(set(titles)) != len(titles):
    fail(f"two parts share a name: {sorted(t for t in titles if titles.count(t) > 1)}")
for p in REG["parts"]:
    if p.get("agent") and p["agent"] not in REG["parts_agents"]:
        fail(f"{p['id']}: unknown agent {p['agent']}")

# The Panel: no list of names of its own.
for name in ("const COMP_NAME", "const AGENTS ", "const AGENT_NAME", "const EXTRAS "):
    if name in JS:
        fail(f"the Panel keeps its own list of names: {name}")
a = JS.index("const COMPONENTS = ["); b = JS.index("];", a)
comps = JS[a:b]
if re.search(r"\bname:|\bdesc:", comps):
    fail("COMPONENTS keeps names or descriptions: they are the registry's")
ids = re.findall(r"\{ id: '([a-z-]+)'", comps)
for i in ids:
    if i not in parts or parts[i]["kind"] != "component":
        fail(f"COMPONENTS: {i} is not a component of the registry")
reg_comps = [p["id"] for p in REG["parts"] if p["kind"] == "component"]
if sorted(ids) != sorted(reg_comps):
    fail(f"COMPONENTS {sorted(ids)} and the registry's components {sorted(reg_comps)} differ")
m = re.search(r"const PART_PAGE = \{([^}]*)\}", JS)
for k in re.findall(r"'?([a-z-]+)'?:", m.group(1) if m else ""):
    if k not in parts:
        fail(f"PART_PAGE: {k} is not a part of the registry")
for need in ("const compName = id => (((st().parts || {}).list || []).find(p => p.id === id) || {}).title",
             "const agentList = () => Object.entries((st().parts && st().parts.agents) || {});",
             "DETAILS['c-' + c.id] = { get title() { return compName(c.id); }"):
    if need not in JS:
        fail(f"the Panel lacks {need!r}")

# The router: the helper checks names against the registry, the API lists the extras from it.
if "VWARD_EXTRA_NAMES" in HELPER or re.search(r"network:act\|", HELPER):
    fail("the helper keeps its own list of parts or agents")
for need in ("reg_has '.parts[] | select(.switch == \"extra\") | .id' \"$1\"", "reg_has '.parts_agents | keys[]' \"$1\""):
    if need not in HELPER:
        fail(f"the helper lacks {need!r}")
if re.search(r"for x in memory-watch", API) or 'select(.switch == "extra" and .id != "sentinel")' not in API:
    fail("the API lists the optional parts from the registry")

# The engine's component registry carries the same names.
for c in CREG.get("components", []):
    if c.get("id") in parts and c.get("name_ru") and c["name_ru"] != parts[c["id"]]["title"]:
        fail(f"component-registry {c['id']}: {c['name_ru']!r} != {parts[c['id']]['title']!r}")

if errors:
    for e in errors:
        print("FAIL:", e)
    sys.exit(1)
print("PARTS_NAMES=PASS")
