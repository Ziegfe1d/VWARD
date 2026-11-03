#!/usr/bin/env python3
"""Explicit read-only association is not adoption, and grants no mutation right."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
import service_fixture as fixture

with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td)); s.foreign()
    s.cfg.write_text(s.cfg.read_text().replace('domain-list7 ISP auto', 'domain-list7 Wireguard0 auto')
                     .replace('    include user.example\n', '    include user.example\n    include anthropic.com\n    include claude.com\n'))
    before = s.cfg.read_bytes()
    token = hashlib.sha256((s.cfg.read_text().rstrip('\n')+'\n').encode()).hexdigest()
    api = subprocess.run(['sh', str(fixture.ROOT/'web/cgi-bin/api.cgi')], env=s.env | {
        'REQUEST_METHOD': 'GET', 'QUERY_STRING': 'action=ai-data', 'JQ': 'jq',
        'VWARD_CONSOLE_CACHE_TTL': '0', 'VWARD_SERVICES_FETCHED': str(s.cat)}, capture_output=True, text=True, timeout=30)
    assert api.returncode == 0 and api.stdout.split('\n\n', 1)[-1].strip(), api.stdout + api.stderr
    data = json.loads(api.stdout.split('\n\n', 1)[-1])
    assert data['reference_token'] == token
    ref = data['services'][0]['paths'][0]
    assert ref['reference'] and ref['group'] == 'domain-list7' and len(ref['members']) == 4, data
    r = s.run('service', 'reference', 'claude.ai', 'domain-list7', token)
    assert r.returncode == 0, r.stdout + r.stderr
    assert s.cfg.read_bytes() == before
    assert s.state.read_text() == 'claude.ai\tdomain-list7\tauto\n'
    assert not (s.etc/'services/owned/domain-list7').exists()
    r = s.run('ai', 'claude.ai', 'vpn')
    assert r.returncode == 0 and s.cfg.read_bytes() == before, r.stdout + r.stderr
    assert s.run('service', 'off', 'claude.ai').returncode == 0
    assert s.cfg.read_bytes() == before and not s.state.read_text()
    # A changed preview, exclusion, incomplete coverage or borrowed claim never grants rights.
    for replacement in ('description Owner', 'exclude claude.ai', 'include owner.example'):
        s.cfg.write_bytes(before)
        s.cfg.write_text(s.cfg.read_text().replace('include claude.ai', replacement))
        r = s.run('service', 'reference', 'claude.ai', 'domain-list7', token)
        assert r.returncode != 0 and not s.state.read_text(), r.stdout
    s.cfg.write_bytes(before)
    claim = s.etc/'services/owned/domain-list7'; claim.parent.mkdir(parents=True)
    claim.write_text('unattributed old claim\n'); claim.chmod(0o600)
    assert s.run('service', 'reference', 'claude.ai', 'domain-list7', token).returncode != 0
    assert not s.state.read_text() and s.cfg.read_bytes() == before
print('SERVICE_REFERENCE_CHOICE=PASS')
