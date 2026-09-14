#!/usr/bin/env python3
"""Keep update-manifest enums aligned with the canonical component registry."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
registry = json.loads((root / "config/components/component-registry.json").read_text(encoding="utf-8"))
schema = json.loads((root / "config/updater/update-manifest.schema.json").read_text(encoding="utf-8"))

components = registry["components"]
registry_ids = {item["id"] for item in components}
registry_profiles = {item["health_profile"] for item in components}
signed_props = schema["properties"]["signed"]["properties"]
schema_ids = set(signed_props["affected_components"]["items"]["enum"])
schema_profiles = set(signed_props["health_profile"]["enum"])

missing_ids = sorted(registry_ids - schema_ids)
unknown_ids = sorted(schema_ids - registry_ids)
missing_profiles = sorted(registry_profiles - schema_profiles)

errors = []
if missing_ids:
    errors.append("schema missing component ids: " + ", ".join(missing_ids))
if unknown_ids:
    errors.append("schema contains unknown component ids: " + ", ".join(unknown_ids))
if missing_profiles:
    errors.append("schema missing health profiles: " + ", ".join(missing_profiles))

if errors:
    raise SystemExit("FAIL: " + "; ".join(errors))
print("UPDATE_SCHEMA_REGISTRY=PASS")
