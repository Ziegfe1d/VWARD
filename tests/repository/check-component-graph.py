#!/usr/bin/env python3
"""Component graph: declared dependencies match what the scripts actually use."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
registry = json.loads((ROOT / "config/components/component-registry.json").read_text(encoding="utf-8"))
comps = {c["id"]: c for c in registry["components"]}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


CORE = {"platform-core", "runtime", "console", "update-engine"}
if {i for i, c in comps.items() if c.get("core")} != CORE:
    fail("core components must be exactly: " + ", ".join(sorted(CORE)))

for cid, c in comps.items():
    for key in ("depends_on", "requires_running", "uses"):
        if not isinstance(c.get(key), list) or any(d not in comps or d == cid for d in c[key]):
            fail(f"{cid}.{key} must list other registry components")
    if not c["core"] and "runtime" not in c["depends_on"]:
        fail(f"{cid} runs on the shared runtime and must depend on it")
    if not set(c["requires_running"]) <= set(c["depends_on"]):
        fail(f"{cid}: a component required running must also be an install dependency")
    if c["core"] and any(not comps[d]["core"] for d in c["depends_on"] + c["requires_running"]):
        fail(f"core component {cid} must not depend on an optional component")


def cycle(key):
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            fail(f"{key} cycle: " + " -> ".join(path + [n]))
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in comps[n][key]:
            visit(d, path + [n])
        state[n] = 2

    for n in comps:
        visit(n, [])


cycle("depends_on")
cycle("requires_running")

# Every reference an optional component's scripts make to another component's
# installed file or state directory must be declared.
STATE_OWNER = {
    "/opt/var/lib/vward/route-engine": "route-engine",
    "/opt/etc/vward/route-engine/hints-catalog.tsv": "route-tools",
    "/opt/var/lib/vward/policy-sync": "policy-sync",
    "/tmp/vward-tunnel-health": "tunnel-guard",
    "/tmp/vward-route-engine-state": "route-engine",
    "/opt/var/lib/vward/tunnel-guard": "tunnel-guard",
    "/opt/var/lib/vward/wifi-client-guard": "wifi-client-guard",
}
owner = {t: c["id"] for c in registry["components"] for t in c["runtime_targets"]}
rows = [l.split("\t") for l in (ROOT / "config/components/package-map.tsv").read_text().splitlines() if l and not l.startswith("#")]
for comp, source, _target, _mode in rows:
    if comps[comp]["core"] or not source.endswith(".sh"):
        continue
    text = (ROOT / source).read_text(errors="ignore")
    declared = set(comps[comp]["depends_on"]) | set(comps[comp]["uses"])
    for path, other in list(owner.items()) + list(STATE_OWNER.items()):
        if other != comp and path in text and other not in declared:
            fail(f"{source} uses {path} of {other}, but {comp} does not declare it")

# The Console takes the graph from the API; a second hardcoded copy would drift.
js = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
if re.search(r"\{ id: '[a-z-]+', name: '[^']+', desc: '[^']*', deps:", js):
    fail("Console must not keep its own copy of component dependencies")

print("COMPONENT_GRAPH=PASS")
