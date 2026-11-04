#!/usr/bin/env python3
"""Healthy saved URL is not permission to restore a removed/replaced server."""
import ast
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
import service_fixture as fixture
from doh_fixture import responder

tree = ast.parse(Path(__file__).with_name('check-ai-catalog-cycle.py').read_text())
DNS = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'DNS')
OLD = 'https://old.example.test/dns-query/synthetic'
NEW = 'https://new.example.test/dns-query/synthetic'
for selected in (OLD, NEW, ''):
    with tempfile.TemporaryDirectory() as td:
        s = fixture.Services(Path(td)); responder(Path(td), s.env)
        ndmc = Path(s.env['VWARD_NDMC'])
        ndmc.write_text(ndmc.read_text().replace('if w[:1] == ["dns-proxy"]:', DNS+'\nif w[:1] == ["dns-proxy"]:'))
        s.cfg.write_text(s.cfg.read_text().replace('dns-proxy\n',
            'dns-proxy\n    https upstream '+OLD+' dnsm on ISP domain claude.ai\n'
            '    https upstream https://resolver.example/dns-query/a\n'
            '    https upstream https://resolver.example/dns-query/b\n'))
        conf = s.etc/'smartdns.conf'; conf.write_text('SMARTDNS_URL='+OLD+'\n')
        assert s.run('service', 'on', 'claude.ai', 'auto').returncode == 0
        assert OLD not in s.cfg.read_text()
        conf.write_text('SMARTDNS_URL='+selected+'\n' if selected else '')
        curl = Path(s.env['VWARD_CURL_BIN']); calls = s.tmp/'probes'
        curl.write_text(curl.read_text().replace('sys.stdin.read()', f'Path({str(calls)!r}).open("a").write(sys.stdin.read())'))
        r = s.run('service', 'off', 'claude.ai')
        assert r.returncode == 0, r.stdout + r.stderr
        text = s.cfg.read_text()
        assert (OLD in text) == (selected == OLD), 'removed/replaced server resurrected'
        assert text.count('https upstream https://resolver.example/dns-query/') == 2
        if selected != OLD:
            assert not calls.exists() or 'old.example.test' not in calls.read_text(), 'unconfigured old server probed'
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    conf = td/'config'; conf.write_text('')
    saved = td/'saved'
    source = fixture.HELPER.read_text()
    functions = '\n'.join(re.findall(r'^(?:doh_restore_allowed|smartdns_config_signature|smartdns_selected_url|smartdns_saved_marker)\(\) \{\n.*?^\}', source, re.M|re.S))
    def allowed(prefix=''):
        script = ('SMARTDNS_CONF="$1"; saved="$2"\n'+functions+'\n'+prefix+'\ndoh_restore_allowed "$3"')
        return subprocess.run(['sh','-c',script,'guard',str(conf),str(saved),OLD],capture_output=True).returncode
    for marker in ('smartdns_config=\n', 'smartdns_config=bad\n',
                   'smartdns_config='+'a'*64+'\nsmartdns_config='+'a'*64+'\n'):
        saved.write_text(marker)
        assert allowed() == 2, 'invalid marker downgraded to legacy permission'
    saved.write_text('smartdns_config='+hashlib.sha256(b'').hexdigest()+'\n')
    assert allowed() == 0
    assert allowed('awk() { return 2; }') == 2, 'read failure authorized a saved server'
    saved.write_text('route=ISP\tauto\n')
    assert allowed() == 0, 'legacy unconfigured return lost its liveness path'
print('SMARTDNS_SAVED_AUTHORIZATION=PASS current, removed, replaced; invalid/read-error proof refuses; legacy preserved')
