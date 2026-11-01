#!/usr/bin/env python3
"""A matching catalog is no permission to mutate a user's FQDN group."""
import json
import tempfile
from pathlib import Path
from service_fixture import Services

failures = []
for case in ('adopt', 'off', 'retarget', 'category', 'refresh', 'auto-writer', 'edited-owned', 'route-edited-owned', 'claim-mode', 'off-race', 'extra-route'):
    with tempfile.TemporaryDirectory() as d:
        s = Services(Path(d))
        if case in ('edited-owned', 'route-edited-owned', 'claim-mode', 'off-race', 'extra-route'):
            r = s.run('service', 'on', 'claude.ai', 'auto')
            assert r.returncode == 0, r.stdout
            if case == 'edited-owned':
                s.cfg.write_text(s.cfg.read_text().replace('    include claude.ai\n',
                                '    include claude.ai\n    include user.example\n'))
            elif case == 'route-edited-owned':
                s.cfg.write_text(s.cfg.read_text().replace('domain-list0 Wireguard0', 'domain-list0 ISP'))
            elif case == 'claim-mode':
                (s.etc / 'services/owned/domain-list0').chmod(0o666)
            elif case == 'off-race':
                Path(str(s.cfg) + '.edit-on-save').touch()
            else:
                s.cfg.write_text(s.cfg.read_text().replace('    route object-group domain-list0 Wireguard0 auto\n', '    route object-group domain-list0 Wireguard0 auto\n    route object-group domain-list0 ISP auto\n'))
        else:
            s.foreign()
            if case != 'adopt': s.enabled()
        before = s.cfg.read_text()
        if case == 'adopt': r = s.run('service', 'on', 'claude.ai', 'auto')
        elif case in ('off', 'edited-owned', 'route-edited-owned', 'claim-mode', 'off-race', 'extra-route'): r = s.run('service', 'off', 'claude.ai')
        elif case == 'retarget': r = s.run('service', 'tunnel', 'claude.ai', 'Wireguard0')
        elif case == 'category': r = s.run('service-category', 'ai', 'Wireguard0')
        elif case == 'refresh':
            s.served.write_text(json.dumps(s.catalog))
            r = s.run('services-refresh', 'run')
        else:
            r = s.run('domain-list', 'domain-list7', 'Wireguard0', VWARD_SERVICE_ID='claude.ai')
        if case == 'off-race':
            if 'owner.example' not in s.cfg.read_text() or r.returncode == 0:
                failures.append('off deleted a group edited during bypass')
            continue
        if s.cfg.read_text() != before:
            failures.append(case + ': user group/route changed')
        if case in ('adopt', 'retarget', 'category', 'auto-writer'):
            if r.returncode == 0 or 'error=service_reference_only' not in r.stdout:
                failures.append(case + ': mutation permission not refused: ' + r.stdout.strip())
        elif r.returncode:
            failures.append(case + ': safe detach/skip failed: ' + r.stdout.strip())
if failures:
    raise SystemExit('SERVICE_OWNERSHIP=FAIL: ' + '; '.join(failures))
print('SERVICE_OWNERSHIP=PASS')
