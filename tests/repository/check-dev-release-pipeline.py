#!/usr/bin/env python3
"""Guard the dev release pipeline against non-publishable candidates."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
workflow = (root / ".github/workflows/build-dev-release.yml").read_text(encoding="utf-8")
publisher = root / "scripts/prepare-dev-release.sh"
production_config = (root / "config/updater/update.conf.production").read_text(encoding="utf-8")

if "busybox" not in workflow:
    raise SystemExit("FAIL: dev build workflow does not install BusyBox")
if "scripts/prepare-dev-release.sh" not in workflow:
    raise SystemExit("FAIL: dev build workflow does not use canonical release preparer")
if not publisher.is_file():
    raise SystemExit("FAIL: canonical dev release preparer is missing")
if "https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/update-manifest.json" not in production_config:
    raise SystemExit("FAIL: dev production profile does not use the dev signed feed")

body = publisher.read_text(encoding="utf-8")
for marker in (
    "vward-$VERSION.tar.gz",
    "update-manifest.json",
    "openssl pkeyutl -sign",
    "openssl pkeyutl -verify",
    "SIGNING_REQUIRED",
    "PUBLISH_READY",
):
    if marker not in body:
        raise SystemExit(f"FAIL: dev release preparer misses {marker}")

print("DEV_RELEASE_PIPELINE=PASS")
