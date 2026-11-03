#!/usr/bin/env python3
"""A later group step must not turn an owner edit into composite success."""
import json
import tempfile
from pathlib import Path
import service_fixture as fixture

with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td))
    s.catalog['services'].append({'id': 'second.example', 'title': 'Second',
                                  'category': 'ai', 'domains': ['second.example']})
    s.cat.write_text(json.dumps(s.catalog))
    ndmc = Path(s.env['VWARD_NDMC'])
    ndmc.write_text(ndmc.read_text().replace('text = cfg.read_text()', '''
if cmd == 'dns-proxy route object-group domain-list1 Wireguard0 auto':
    cfg.write_text(cfg.read_text().replace('domain-list0 Wireguard0 auto', 'domain-list0 ISP auto'))
text = cfg.read_text()'''))
    r = s.run('ai', 'all', 'vpn')
    assert r.returncode != 0 and 'error=ai_verification_failed' in r.stdout, (r.stdout, r.stderr)
    config = s.cfg.read_text()
    assert 'domain-list0 ISP auto' in config, config
    assert 'domain-list1 Wireguard0 auto' in config, config
    assert len(s.state.read_text().splitlines()) == 2
    assert 'composite_verified' not in '\n'.join(p.read_text() for p in (s.tmp/'backup').rglob('resolution') if p.is_file())
print('AI_FINAL_VERIFICATION=PASS')
