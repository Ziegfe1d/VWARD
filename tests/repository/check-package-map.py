#!/usr/bin/env python3
"""Validate the signed-package source-to-runtime map against the component registry."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
registry = json.loads((root / "config/components/component-registry.json").read_text(encoding="utf-8"))
map_path = root / "config/components/package-map.tsv"

rows = []
for number, raw in enumerate(map_path.read_text(encoding="utf-8").splitlines(), 1):
    if not raw or raw.startswith("#"):
        continue
    parts = raw.split("\t")
    if len(parts) != 4:
        raise SystemExit(f"FAIL: package map line {number} must contain four tab-separated fields")
    component, source, target, mode = parts
    if mode not in {"0644", "0755"}:
        raise SystemExit(f"FAIL: invalid mode at line {number}: {mode}")
    if not target.startswith("/opt/"):
        raise SystemExit(f"FAIL: target outside /opt at line {number}: {target}")
    if not (root / source).is_file():
        raise SystemExit(f"FAIL: missing package source at line {number}: {source}")
    rows.append((component, source, target, mode))

targets = [row[2] for row in rows]
sources = [row[1] for row in rows]
if len(targets) != len(set(targets)):
    raise SystemExit("FAIL: duplicate package target")
if len(sources) != len(set(sources)):
    raise SystemExit("FAIL: duplicate package source")

mapped = {(row[0], row[2]) for row in rows}
expected = {
    (component["id"], target)
    for component in registry["components"]
    if component["update_method"] == "signed-package"
    for target in component["runtime_targets"]
}
missing = sorted(expected - mapped)
unexpected = sorted(mapped - expected)
if missing:
    raise SystemExit("FAIL: package map missing registry targets: " + repr(missing))
if unexpected:
    raise SystemExit("FAIL: package map contains unexpected targets: " + repr(unexpected))

slot_components = {
    component["id"] for component in registry["components"]
    if component["update_method"] == "slot-installer"
}
if slot_components & {row[0] for row in rows}:
    raise SystemExit("FAIL: slot-installer component included in signed package map")

common = (root / "components/update-engine/vward-update-common-base.sh").read_text(encoding="utf-8")
safe_body = common.split("vu_safe_target() {", 1)[1].split("vu_local_target() {", 1)[0]
allowed_targets = set(re.findall(r"/opt/[A-Za-z0-9._/-]+", safe_body))
not_allowed = sorted(set(targets) - allowed_targets)
if not_allowed:
    raise SystemExit("FAIL: package targets rejected by updater allowlist: " + repr(not_allowed))

print(f"PACKAGE_MAP=PASS targets={len(rows)}")
