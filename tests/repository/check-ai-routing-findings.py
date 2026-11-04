#!/usr/bin/env python3
"""Configuration evidence is distinct from DNS answers and the LAN client path."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import service_fixture as fixture

catalog = json.loads((fixture.ROOT/'components/console/data/services-catalog.json').read_text())
claude = next(s for s in catalog['services'] if s['id'] == 'claude.ai')

with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td)); s.cat.write_text(json.dumps(catalog))
    env = s.env | {'REQUEST_METHOD':'GET', 'QUERY_STRING':'action=ai-data',
                   'JQ':shutil.which('jq'), 'VWARD_DOH_ALIVE':'0'}
    def data(config):
        s.cfg.write_text(config)
        r = subprocess.run(['sh', str(fixture.ROOT/'web/cgi-bin/api.cgi')], env=env,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout.split('\n\n',1)[-1]); assert d['ok'], d
        assert d.get('evidence') == 'configuration' and d.get('client_path_verified') is False, d
        assert s.cfg.read_text() == config and not s.state.exists(), 'reader changed routing/registry'
        return {v['id']:v for v in d['services']}
    def config(domains, excluded=''):
        return ('object-group fqdn AdaptiveAuto\n' + ''.join('    include '+d+'\n' for d in domains)
                + ('    exclude '+excluded+'\n' if excluded else '') + '!\n'
                'object-group fqdn domain-list4\n    include claudemcpclient.com\n'
                '    include claudemcpcontent.com\n!\ndns-proxy\n'
                '    route object-group AdaptiveAuto Wireguard0 auto\n'
                '    route object-group domain-list4 Wireguard0 auto\n!\n')
    full = data(config(claude['domains']))['claude.ai']
    assert full['effective'] == 'vpn' and full['selected'] is None, full
    assert {p['group'] for p in full['paths']} == {'AdaptiveAuto','domain-list4'}, full
    assert not any(p['reference'] for p in full['paths'] if p['group']=='AdaptiveAuto'), 'AdaptiveAuto is not a manual reference target'
    partial = data(config(['claude.ai']))['claude.ai']
    assert partial['effective'] == 'mixed' and partial['coverage']['routed'] == 3, partial
    mcp = data(config([]))['claude.ai']
    assert mcp['coverage']['routed'] == 2 and mcp['effective'] == 'mixed', mcp
    excluded = data(config(claude['domains'], 'claude.ai'))['claude.ai']
    assert excluded['effective'] == 'mixed' and excluded['coverage']['routed'] == len(claude['domains'])-1, excluded
    unknown = data('')['cursor.com']
    assert unknown['effective'] == 'unknown' and unknown['selected'] is None, unknown

js = (fixture.ROOT/'web/assets/vward-console.js').read_text()
at = js.index('  const status = s => {', js.index('function aiPage()'))
status = js[at:js.index('\n  };',at)+5]
render = ('const AICHK={},esc=String,tunLabel=String;\n'+status+'''
const text=status({id:'claude.ai',selected:null,effective:'mixed',coverage:{routed:2,catalog:21},paths:[{group:'domain-list4',route:'Wireguard0'}]});
if(!text.toLowerCase().includes('неполное') || text.includes('Пересекаются DNS и маршруты')) throw Error(text);
''')
r = subprocess.run(['node','-e',render],capture_output=True,text=True)
assert r.returncode == 0, r.stderr

# Cursor uses the ordinary service writer without Smart DNS and preserves
# unrelated manual sources, including a failed save followed by compensation.
for save_refusal in (False, True):
    with tempfile.TemporaryDirectory() as td:
        s = fixture.Services(Path(td)); s.cat.write_text(json.dumps(catalog))
        manual = ('object-group fqdn domain-list4\n    description Manual\n'
                  '    include claudemcpclient.com\n    include claudemcpcontent.com\n!\n')
        before = manual+s.cfg.read_text().replace('dns-proxy\n','dns-proxy\n    route object-group domain-list4 Wireguard0 auto\n')
        s.cfg.write_text(before)
        curl = Path(s.env['VWARD_CURL_BIN']); called = Path(td)/'probe-called'
        curl.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                        +'Path('+repr(str(called))+').open("a").write(repr(sys.argv)+sys.stdin.read())\nsys.exit(22)\n')
        (s.etc/'smartdns.conf').write_text('SMARTDNS_URL=https://expired.example.test/dns-query/synthetic\n')
        if save_refusal: s.reject('system configuration save')
        r = s.run('ai','cursor.com','vpn:Wireguard0')
        calls = called.read_text() if called.exists() else ''
        assert 'expired.example.test' not in calls and 'application/dns-message' not in calls, 'Cursor VPN asked Smart DNS'
        assert manual in s.cfg.read_text(), 'manual source changed'
        if save_refusal:
            assert r.returncode != 0 and s.cfg.read_text() == before, (r.stdout,r.stderr)
            assert not s.state.exists() or not s.state.read_text(), r.stdout
            continue
        assert r.returncode == 0, (r.stdout,r.stderr)
        stable = (s.cfg.read_text(), s.state.read_bytes())
        r = s.run('ai','cursor.com','vpn:Wireguard0')
        assert r.returncode == 0 and stable == (s.cfg.read_text(),s.state.read_bytes()), r.stdout
        r = s.run('ai','cursor.com','isp')
        assert r.returncode == 0 and s.cfg.read_text() == before, (r.stdout,r.stderr)
print('AI_ROUTING_FINDINGS=PASS other source, partial/excluded coverage, unknown, Cursor no-DNS repeat/rollback')
