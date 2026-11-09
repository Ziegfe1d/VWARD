#!/usr/bin/env python3
"""A full native group proof does not attribute every member to its service."""
import shutil
from live_fixture import LiveFixture

with LiveFixture() as f:
    f.install_console()
    r=f.console('service','off','svc')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    shutil.rmtree(f.live)
    f.native.write_text(f.native.read_text().replace('dns-proxy\n',
        'dns-proxy\n    route object-group domain-list0 Wireguard0 auto\n')+
        'object-group fqdn domain-list0\n    include s.example\n    include x.example\n    include manual-extra.example\n!\n')
    f.startup.write_bytes(f.native.read_bytes())
    enabled=f.etc/'services/enabled.tsv'
    enabled.write_text('svc\tdomain-list0\tWireguard0\n')
    proof=f.etc/'services/owned/domain-list0'
    proof.write_text('include manual-extra.example\ninclude s.example\ninclude x.example\nroute=Wireguard0\tauto\n')
    proof.chmod(0o400)
    before=f.native.read_bytes();saved=f.startup.read_bytes()
    registration=enabled.read_bytes();proof_bytes=proof.read_bytes()
    r=f.console('service','off','svc',preserve_profile=True)
    assert r.returncode!=0 and f.native.read_bytes()==before and f.startup.read_bytes()==saved,(
        'unknown member acquired S withdrawal authority',r.returncode,r.stdout,r.stderr,f.native.read_text())
    assert enabled.read_bytes()==registration and proof.read_bytes()==proof_bytes
    resources=f.live/'decision/resources.tsv'
    if resources.exists():
        assert not any('\tmanual-extra.example\t' in row and 'S:svc' in row for row in resources.read_text().splitlines()),'unmatched member imported as S'
print('LIVE_IMPORT_ATTRIBUTION=PASS private full-group proof cannot turn an unmatched member into S withdrawal authority')
