#!/usr/bin/env python3
"""Every Panel switch with a «Песочница» position has the «Вкл» position too (owner 16.11.2026).

«Выкл · Песочница · Вкл» for a part that can be switched off: «Вкл» is always shown; while the part
cannot act yet it is shown inactive, never left out (CLAUDE.md, docs/TASK_SANDBOX_ON_2026-11-16.md).
"""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
js = (root / "web/assets/vward-console.js").read_text(encoding="utf-8")
failures, seen = [], 0
for m in re.finditer(r"choiceSlider\('([a-z0-9-]+)',\s*\[((?:\[[^\]]*\],?\s*)+)\]", js):
    key, body = m.group(1), m.group(2)
    if "'sandbox'" not in body:
        continue
    seen += 1
    labels = re.findall(r"\['([a-z]+)',\s*'([^']*)'", body)
    if ("on", "Вкл") not in labels:
        failures.append(key + ": «Песочница» without «Вкл»")
    order = [v for v, _ in labels]
    if order[:3] != ["off", "sandbox", "on"]:
        failures.append(key + ": positions are not «Выкл · Песочница · Вкл»: " + ",".join(order))
if seen < 2:
    failures.append("sandbox switches not found (%d)" % seen)
if failures:
    raise SystemExit("SANDBOX_SWITCHES=FAIL: " + "; ".join(failures))
print("SANDBOX_SWITCHES=PASS switches=%d" % seen)
