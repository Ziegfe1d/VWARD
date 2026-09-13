#!/usr/bin/env python3
"""Candidate integration gate for the VWARD Dev.7 unified settings registry."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
frag = json.loads((ROOT / 'config/settings/settings-registry.fragment.json').read_text(encoding='utf-8'))
items = frag['settings']
assert items and len({x['id'] for x in items}) == len(items)
allowed_keys = {
 'ENABLED','RUN_MODE','SCHEDULE_INTERVAL_MIN','DYNAMIC_MIN_INTERVAL_SEC',
 'DYNAMIC_MAX_LOAD_PER_CPU_X100','DYNAMIC_MIN_MEM_AVAILABLE_KB','DYNAMIC_MIN_OPT_FREE_KB',
 'DYNAMIC_MAX_CANDIDATES_PER_RUN','AUTO_SOURCE_UPDATE','SOURCE_UPDATE_INTERVAL_HOURS',
 'QUERY_SOURCE','AUTO_RULE_SCOPE','PUBLISH_MODE','AUTO_PUBLISH'
}
for x in items:
    assert x['component'] == 'ads-privacy-guard'
    assert x['source'] == 'ads-privacy-guard.conf'
    assert x['key'] in allowed_keys
    assert x['secret'] is False
    assert x['editable'] is True
    assert x['restart_requirement'] == 'none'
assert {x['key'] for x in items} == allowed_keys
print('ADS_PRIVACY_SETTINGS_REGISTRY=PASS')
