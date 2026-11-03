#!/usr/bin/env python3
"""Release numbers (owner 2026-11-01): fix.N is the next full cumulative release, fix.N.1, fix.N.2 ... are
quick corrections of a released base. The updater's own comparator must order them so every router moves
forward: fix.34.1 < fix.35 < fix.35.1 < fix.35.2 < fix.36; the release metadata names one version; the
Panel's System card and «Что нового» understand it."""

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"VERSION_NUMBERING=FAIL: {message}")


version = (ROOT / "VERSION").read_text().strip()
if not re.fullmatch(r"\d+\.\d+\.\d+-rc\.\d+\.fix\.\d+(\.\d+)*", version):
    fail(f"VERSION {version!r} is not a fix.N[.M] release")
registry = json.loads((ROOT / "config/components/component-registry.json").read_text())
if registry.get("platform_version") != version:
    fail(f"registry platform_version {registry.get('platform_version')!r} != {version}")
for path, var in (("components/route-engine/lib/vward-domain-classifier-lib.sh", "VWARD_CLASSIFIER_VERSION"),
                  ("components/ads-privacy-guard/lib/vward-ads-privacy-common.sh", "VWARD_ADS_VERSION")):
    if f'{var}="{version}"' not in (ROOT / path).read_text():
        fail(f"{path}: {var} is not {version}")
if f"## {version}:" not in (ROOT / "CHANGELOG.md").read_text():
    fail("CHANGELOG has no section for this version («Что нового» reads it)")

pairs = [("0.2.0-rc.2.fix.32", "0.2.0-rc.2.fix.34.1"), ("0.2.0-rc.2.fix.34.1", "0.2.0-rc.2.fix.35"),
         ("0.2.0-rc.2.fix.35", "0.2.0-rc.2.fix.35.1"), ("0.2.0-rc.2.fix.35.1", "0.2.0-rc.2.fix.35.2"), ("0.2.0-rc.2.fix.35.2", "0.2.0-rc.2.fix.35.3"), ("0.2.0-rc.2.fix.35.3", "0.2.0-rc.2.fix.35.4"),
         ("0.2.0-rc.2.fix.35.9", "0.2.0-rc.2.fix.35.10"), ("0.2.0-rc.2.fix.35.10", "0.2.0-rc.2.fix.36"),
         ("0.2.0-rc.2.fix.36", "0.2.0-rc.2.fix.37"), ("0.1.9-beta", "0.2.0-rc.2.fix.35")]
script = ". components/update-engine/vward-update-common-base.sh >/dev/null 2>&1\n" + "".join(
    f'vu_version_lt "{a}" "{b}" && ! vu_version_lt "{b}" "{a}" || echo "BAD {a} {b}"\n' for a, b in pairs)
r = subprocess.run(["sh", "-c", script], cwd=ROOT, capture_output=True, text=True)
if r.returncode or r.stdout.strip():
    fail(f"comparator: {r.stdout.strip() or r.stderr.strip()}")
# The installed version must be the newest of the published ones the router may hold.
if not all(subprocess.run(["sh", "-c", ". components/update-engine/vward-update-common-base.sh >/dev/null 2>&1; vu_version_lt " + a + " " + version],
                          cwd=ROOT).returncode == 0 for a in ("0.2.0-rc.2.fix.32", "0.2.0-rc.2.fix.34.1")):
    fail(f"{version} must be newer than fix.32 and fix.34.1")

if shutil.which("node"):
    js = (ROOT / "web/assets/vward-console.js").read_text()
    rx = "/^(.*?)\\.fix\\.(\\d+(?:\\.\\d+)*)$/"
    if rx not in js:
        fail("the System card's version pattern changed")
    out = subprocess.run(["node", "-e", f"const m = {rx}.exec({json.dumps(version)}); console.log(JSON.stringify(m && [m[1], m[2]]))"],
                         capture_output=True, text=True).stdout.strip()
    want = json.dumps([version.split(".fix.")[0], version.split(".fix.")[1]], separators=(",", ":"))
    if out != want:
        fail(f"System card: {out} != {want}")
print(f"VERSION_NUMBERING=PASS version={version}")
