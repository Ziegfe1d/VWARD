#!/usr/bin/env python3
"""Retired parts (fix.39): config/components/retired.json, the list every release signs into its
manifests and the update engine 2.1 removes from the routers.

The list is permanent and must never fight the release: a retired file is never shipped again
(package map), never owned by a component (registry), its crontab programs are never scheduled
by the installer again, and every path is one the engine accepts (else the whole update would be
refused on the routers)."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
fails = []


def fail(msg):
    fails.append(msg)


data = json.loads((root / "config/components/retired.json").read_text(encoding="utf-8"))
if data.get("schema") != 1 or not isinstance(data.get("parts"), list):
    raise SystemExit("FAIL: retired.json: schema 1 with a parts list")
parts = data["parts"]
if len(parts) > 64:
    fail("retired.json: at most 64 parts")

SAFE = re.compile(r"^/[A-Za-z0-9/._-]+$")
FILE_PLACE = re.compile(r"^(/opt/bin/vward-.+|/opt/lib/vward/.+|/opt/share/vward/.+|/opt/etc/init\.d/S[0-9][0-9]vward-.+)$")
LOCAL = re.compile(r"^(/opt/etc/vward/|/opt/var/|/tmp/|/opt/share/vward/updater/)|/hints\.conf$|/skip-domains\.conf$|\.bak$|\.before-|\.failed-")
SERVICE = re.compile(r"^/opt/etc/init\.d/S[0-9][0-9]vward-.+$")
CRON = re.compile(r"^(/opt/bin/vward-.+|/opt/etc/init\.d/S[0-9][0-9]vward-.+)$")
DIR = re.compile(r"^(/opt/share/vward/.+|/opt/lib/vward/.+)$")


def path_ok(p):
    return (isinstance(p, str) and 1 < len(p) <= 200 and SAFE.match(p) and not p.endswith("/")
            and "//" not in p and "/./" not in p and "/../" not in p and not p.endswith("/.."))


names = set()
retired_files, retired_cron = set(), set()
for part in parts:
    name = part.get("part", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name or ""):
        fail(f"retired.json: bad part name {name!r}")
    if name in names:
        fail(f"retired.json: part {name} twice")
    names.add(name)
    for key in ("title", "retired_in"):
        if not isinstance(part.get(key), str) or not part[key]:
            fail(f"retired.json: {name}: {key} (for people reading the list)")
    files = part.get("files") or []
    if not files:
        fail(f"retired.json: {name}: no files")
    for key, rule in (("files", FILE_PLACE), ("dirs", DIR), ("cron", CRON), ("services", SERVICE)):
        values = part.get(key, [])
        if not isinstance(values, list) or len(values) > 256 or len(set(values)) != len(values):
            fail(f"retired.json: {name}: {key} must be a list of distinct paths")
            continue
        for p in values:
            if not path_ok(p) or not rule.match(p) or (key == "files" and LOCAL.search(p)):
                fail(f"retired.json: {name}: {key} {p!r} is not a place the update engine removes")
            if key == "dirs" and (p == "/opt/share/vward/updater" or p.startswith("/opt/share/vward/updater/")):
                fail(f"retired.json: {name}: the update engine folder")
    for s in part.get("services", []):
        if s not in files:
            fail(f"retired.json: {name}: service {s} is not among its files")
    retired_files.update(files)
    retired_cron.update(part.get("cron", []))

package_map = set()
for line in (root / "config/components/package-map.tsv").read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#"):
        package_map.add(line.split("\t")[2])
for f in sorted(retired_files & package_map):
    fail(f"retired file still shipped by package-map.tsv: {f}")

registry = json.loads((root / "config/components/component-registry.json").read_text(encoding="utf-8"))
owned = {t for c in registry["components"] for t in c["runtime_targets"]}
for f in sorted(retired_files & owned):
    fail(f"retired file still owned by the component registry: {f}")

crontab = (root / "config/cron/root.crontab").read_text(encoding="utf-8")
for line in crontab.splitlines():
    if line.lstrip().startswith("#"):
        continue
    tokens = set(re.split(r"[ \t;&|<>()\"]+", line))
    for prog in sorted(tokens & retired_cron):
        fail(f"root.crontab still schedules retired {prog}")

engine = (root / "components/update-engine/vward-update-delta.sh").read_text(encoding="utf-8")
for marker in ("vu_retire_validate", "vu_retire_plan", "vu_retire_apply", "vu_retire_state_prune"):
    if marker not in engine:
        fail(f"update engine misses {marker}")
release = (root / "scripts/prepare-dev-release.sh").read_text(encoding="utf-8")
if release.count("{retire:$retire}") != 2 or "config/components/retired.json" not in release:
    fail("prepare-dev-release.sh signs the retire list into both manifests")

if fails:
    raise SystemExit("FAIL: " + "\nFAIL: ".join(fails))
print(f"RETIRED_PARTS=PASS parts={len(parts)} files={len(retired_files)}")
