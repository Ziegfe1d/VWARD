#!/usr/bin/env python3
"""Every bundled AI service, real writer over a stateful transport, no network."""
import json
import os
import tempfile
from pathlib import Path
import service_fixture as fixture
from doh_fixture import responder
from agh_fixture import install as agh_install

catalog = json.loads((fixture.ROOT / 'components/console/data/services-catalog.json').read_text())
services = [s for s in catalog['services'] if s['category'] == 'ai']
DNS = '''
if cmd.startswith('dns-proxy https upstream ') or cmd.startswith('dns-proxy no https upstream '):
    start = lines.index('dns-proxy'); end = lines.index('!', start)
    neg = cmd.startswith('dns-proxy no ')
    line = '    ' + cmd[len('dns-proxy no ' if neg else 'dns-proxy '):]
    if neg:
        if line not in lines[start:end]: print('error: not found'); sys.exit(0)
        lines.remove(line)
    elif line not in lines[start:end]:
        if sum('https upstream ' in l and ' domain ' in l for l in lines[start:end]) >= 8:
            print('error: limit'); sys.exit(0)
        lines.insert(end, line)
    save()
'''

for store in ('keenetic', 'agh'):
    for service in services:
        with tempfile.TemporaryDirectory() as td:
            s = fixture.Services(Path(td))
            s.cat.write_text(json.dumps(catalog))
            responder(Path(td), s.env)
            ndmc = Path(s.env['VWARD_NDMC'])
            ndmc.write_text(ndmc.read_text().replace('if w[:1] == ["dns-proxy"]:', DNS + '\nif w[:1] == ["dns-proxy"]:'))
            (s.etc / 'smartdns.conf').write_text('SMARTDNS_STORE=' + store + '\nSMARTDNS_URL=https://dns.example.test/dns-query/synthetic\n')
            yaml = agh_install(Path(td), s.env) if store == 'agh' else None
            for mode in ('vpn', 'vpn:Wireguard0', 'dns', 'dns', 'isp', 'isp', 'vpn'):
                r = s.run('ai', service['id'], mode)
                assert r.returncode == 0, (service['id'], mode, r.stdout, r.stderr)
                config = s.cfg.read_text()
                enabled = s.state.read_text() if s.state.exists() else ''
                if mode.startswith('vpn'):
                    assert service['id'] + '\t' in enabled
                    assert ' Wireguard0 auto' in config and 'https upstream' not in config
                    assert config.count('object-group fqdn ') == 1
                else:
                    assert not enabled and 'object-group fqdn ' not in config
                    assert (('https upstream' in config) if yaml is None else ('[/' in yaml.read_text())) == (mode == 'dns')


# Existing group operation covers precisely the same set, not a hardcoded ChatGPT path.
with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td)); s.cat.write_text(json.dumps(catalog))
    responder(Path(td), s.env)
    yaml = agh_install(Path(td), s.env)
    (s.etc/'smartdns.conf').write_text('SMARTDNS_STORE=agh\nSMARTDNS_URL=https://dns.example.test/dns-query/synthetic\n')
    r = s.run('ai', 'all', 'vpn')
    assert r.returncode == 0, r.stdout + r.stderr
    assert {l.split('\t')[0] for l in s.state.read_text().splitlines()} == {s['id'] for s in services}
    r = s.run('ai', 'all', 'dns')
    assert r.returncode == 0 and not s.state.read_text() and '[/' in yaml.read_text(), r.stdout + r.stderr
    assert 'object-group fqdn ' not in s.cfg.read_text()
    r = s.run('ai', 'all', 'isp')
    assert r.returncode == 0 and not s.state.read_text(), r.stdout + r.stderr
    assert '[/' not in yaml.read_text()
print(f'AI_CATALOG_CYCLE=PASS services={len(services)} x 2 stores + group VPN/DNS/ISP')
