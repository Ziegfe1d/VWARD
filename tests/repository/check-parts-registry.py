#!/usr/bin/env python3
"""One registry of VWARD's parts (owner 12.11.2026: «по порядочку, без дублей»).

config/components/component-registry.json «parts»: every part the owner sees - the package's
components, the VPN and DNS programs, the routing core, the optional parts of the agents - once,
with its one name, its group, what switches it and which agent runs it. The Panel and the router
read their names from here; this test keeps it whole:
  * ids unique; every package component and every optional part (vward_extra) is here;
  * the switch is one the router knows (component / module / extra / none), the group and the
    agent are the registry's own;
  * a component's name_ru is its part's title (one name, not two);
  * no «сторож»/«страж» in what the owner reads (owner 12.11.2026).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(m):
    raise SystemExit(f"PARTS_REGISTRY=FAIL: {m}")


reg = json.loads((ROOT / "config/components/component-registry.json").read_text(encoding="utf-8"))
parts = reg.get("parts") or fail("no parts")
if reg.get("parts_schema") != 1:
    fail("parts_schema must be 1")
ids = [p["id"] for p in parts]
if len(ids) != len(set(ids)):
    fail(f"duplicate parts: {sorted(i for i in ids if ids.count(i) > 1)}")
groups, agents = reg["parts_groups"], reg["parts_agents"]
for p in parts:
    if set(p) != {"id", "kind", "title", "group", "desc", "switch", "agent"}:
        fail(f"{p['id']}: fields {sorted(p)}")
    if p["kind"] not in ("component", "module", "service", "extra"):
        fail(f"{p['id']}: kind {p['kind']}")
    if p["switch"] not in (None, "component", "module", "extra"):
        fail(f"{p['id']}: switch {p['switch']}")
    if p["group"] not in groups or (p["agent"] is not None and p["agent"] not in agents):
        fail(f"{p['id']}: group {p['group']} / agent {p['agent']}")
    if p["switch"] == "extra" and p["kind"] != "extra" or p["kind"] == "extra" and p["switch"] != "extra":
        fail(f"{p['id']}: an optional part is switched as one")
    for t in (p["title"], p["desc"]):
        if re.search(r"[Сс]торож|[Сс]траж", t):
            fail(f"{p['id']}: «{t}»")
comps = {c["id"]: c for c in reg["components"]}
by = {p["id"]: p for p in parts}
for cid, c in comps.items():
    if cid not in by or by[cid]["kind"] != "component":
        fail(f"component {cid} is not a part")
    if c.get("name_ru") != by[cid]["title"]:
        fail(f"{cid}: two names: {c.get('name_ru')!r} / {by[cid]['title']!r}")
    if c.get("core") and by[cid]["switch"] is not None:
        fail(f"{cid}: a core component has no switch")
code = "".join((ROOT / f).read_text() for f in ("components/runtime/scripts/vward-housekeeping.sh", "components/runtime/scripts/vward-cron-supervisor.sh"))
extras = {p["id"] for p in parts if p["kind"] == "extra"}
used = set(re.findall(r"vward_extra ([a-z-]+)", code))
if used != extras:
    fail(f"optional parts: code {sorted(used)} / registry {sorted(extras)}")
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
if set(re.search(r'VWARD_EXTRA_NAMES="([^"]+)"', helper).group(1).split()) != extras:
    fail("the helper switches the registry's optional parts only")
print(f"PARTS_REGISTRY=PASS: {len(parts)} parts in {len(groups)} groups, one name each")
