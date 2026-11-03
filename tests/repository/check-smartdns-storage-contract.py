#!/usr/bin/env python3
"""Preference is for new bindings; neither store changes on preference/repeat."""
import ast
import tempfile
from pathlib import Path
import service_fixture as fixture
from agh_fixture import install
from doh_fixture import responder

tree = ast.parse(Path(__file__).with_name('check-ai-catalog-cycle.py').read_text())
DNS = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'DNS')

for first, second in (('agh','keenetic'),('keenetic','agh')):
    with tempfile.TemporaryDirectory() as td:
        s = fixture.Services(Path(td)); responder(Path(td),s.env); yaml = install(Path(td),s.env)
        ndmc = Path(s.env['VWARD_NDMC'])
        ndmc.write_text(ndmc.read_text().replace('if w[:1] == ["dns-proxy"]:',DNS+'\nif w[:1] == ["dns-proxy"]:'))
        conf = s.etc/'smartdns.conf'
        conf.write_text('SMARTDNS_URL=https://dns.example.test/dns-query/synthetic\nSMARTDNS_STORE='+first+'\n')
        assert s.run('smartdns-domain','add','claude.ai').returncode == 0
        before_cfg, before_agh = s.cfg.read_bytes(),yaml.read_bytes()
        assert s.run('smartdns-store',second).returncode == 0
        assert s.cfg.read_bytes() == before_cfg and yaml.read_bytes() == before_agh
        r = s.run('smartdns-domain','add','claude.ai')
        assert r.returncode == 0 and 'result=unchanged' in r.stdout, r.stdout+r.stderr
        assert s.cfg.read_bytes() == before_cfg and yaml.read_bytes() == before_agh

with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td)); before = s.cfg.read_bytes()
    assert s.run('smartdns-store','agh').returncode == 0
    conf = s.etc/'smartdns.conf'; previous = conf.read_bytes()
    assert 'error=smartdns_not_configured' in s.run('smartdns-domain','add','claude.ai').stdout
    assert s.cfg.read_bytes() == before and conf.read_bytes() == previous
    original=fixture.HELPER; fault=s.tmp/'fault-helper.sh'
    fault.write_text(original.read_text().replace('ETC=', 'mv(){ case "$*" in *smartdns.conf*) return 1;; esac; command mv "$@"; }\nETC=',1))
    try:
        fixture.HELPER=fault
        r=s.run('smartdns-store','keenetic')
        assert r.returncode != 0 and 'error=write_failed' in r.stdout, r.stdout
    finally:
        fixture.HELPER=original
    assert s.cfg.read_bytes() == before and conf.read_bytes() == previous
print('SMARTDNS_STORAGE_CONTRACT=PASS both stores, no migration, unavailable preference, write failure')
