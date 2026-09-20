#!/usr/bin/env python3
"""Reject stale component and roadmap versions in the active dev line."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
required = (
    root / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh",
    root / "components/route-engine/lib/vward-domain-classifier-lib.sh",
    root / "docs/ROADMAP.md",
)

for path in required:
    if version not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"FAIL: stale platform version in {path.relative_to(root)}")

print(f"VERSION_SYNCHRONIZATION=PASS version={version}")
