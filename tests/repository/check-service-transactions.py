#!/usr/bin/env python3
"""Service pins and catalog refresh must commit together with verified router changes."""
import json
import re
import tempfile
from pathlib import Path
from service_fixture import Services

errors = []
for case in ('retarget', 'refresh-failure', 'save-failure', 'capacity', 'rollback-failure', 'owner-between', 'retarget-lost-reply'):
    with tempfile.TemporaryDirectory() as d:
        s = Services(Path(d))
        s.cfg.write_text(s.cfg.read_text() + 'interface OpkgTun1\n!\n')
        s.env['VWARD_KCACHE'] = str(s.tmp / 'kcache')
        if case == 'capacity':
            s.catalog['services'][0]['domains'] = [f'd{i:03}.example' for i in range(300)]
            s.cat.write_text(json.dumps(s.catalog))
        r = s.run('service', 'on', 'claude.ai', 'auto')
        assert r.returncode == 0, r.stdout
        before = s.cfg.read_text()
        state = s.state.read_text()
        if case in ('retarget', 'owner-between', 'retarget-lost-reply'):
            if case == 'owner-between':
                Path(str(s.cfg) + '.snapshot-edit').write_text('3')
            elif case == 'retarget-lost-reply':
                Path(str(s.cfg) + '.applied-error').write_text('dns-proxy route object-group domain-list0 OpkgTun1')
            else:
                s.reject('dns-proxy route object-group domain-list0 OpkgTun1')
            r = s.run('service', 'tunnel', 'claude.ai', 'OpkgTun1')
            want = before.replace('domain-list0 Wireguard0', 'domain-list0 ISP') if case == 'owner-between' else before
            if r.returncode == 0 or s.state.read_text() != state or s.cfg.read_text() != want:
                errors.append(case + ': refused retarget changed pin/config')
        else:
            newer = json.loads(json.dumps(s.catalog))
            if case == 'capacity':
                newer['services'][0]['domains'][-1] = 'replacement.example'
                Path(str(s.cfg) + '.mode-limit').write_text('300')
            else:
                newer['services'][0]['domains'] += ['new.example', 'z.example']
                if case == 'save-failure': s.reject('system configuration save')
                else: s.reject('include z.example')
                if case == 'rollback-failure':
                    s.reject('no object-group fqdn domain-list0 include new.example', always=True)
            s.served.write_text(json.dumps(newer))
            r = s.run('services-refresh', 'run')
            if case == 'capacity':
                if r.returncode or 'replacement.example' not in s.cfg.read_text() or 'd299.example' in s.cfg.read_text():
                    errors.append('300-to-300 replacement failed')
                repeat = s.run('services-refresh', 'run')
                if repeat.returncode or 'result=unchanged' not in repeat.stdout:
                    errors.append('refresh not idempotent')
            elif case == 'rollback-failure':
                recovery = re.findall(r'^recovery=(.+)$', r.stdout, re.M)
                if 'error=rollback_incomplete' not in r.stdout or len(recovery) != 1 or not Path(recovery[0]).is_dir():
                    errors.append('incomplete rollback lost recovery')
            elif r.returncode == 0 or s.cfg.read_text() != before or Path(s.env['VWARD_SERVICES_FETCHED']).exists():
                errors.append(case + ': partial router/catalog commit')
if errors: raise SystemExit('SERVICE_TRANSACTIONS=FAIL: ' + '; '.join(errors))
print('SERVICE_TRANSACTIONS=PASS')
