#!/usr/bin/env python3
"""Closed native commands compile the same sealed prefixes for DATA and live transport."""
from fixture import PipelineFixture

with PipelineFixture() as f:
    work=f.p/'native-compile';work.mkdir(mode=0o700)
    expected=f.p/'expected';expected.write_text('-\n');expected.chmod(0o600)
    original=(f.e/'running.cfg').read_bytes()
    def compile(command):
        return f.run(f.script('vrb_native_compile "$@"'),*f.libs,command,f.e/'running.cfg',expected,work)
    r=compile('object-group fqdn domain-list0')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (work/'native.next').read_text()=='group=domain-list0\n'
    (f.e/'running.cfg').write_bytes((work/'config.next').read_bytes());expected.write_bytes((work/'native.next').read_bytes())
    for cmd in ('object-group fqdn domain-list0 include x.example','dns-proxy route object-group domain-list0 Wireguard0 auto'):
        r=compile(cmd);assert r.returncode==0,(cmd,r.returncode,r.stderr)
        (f.e/'running.cfg').write_bytes((work/'config.next').read_bytes());expected.write_bytes((work/'native.next').read_bytes())
    assert 'include x.example\n' in expected.read_text() and 'route=Wireguard0\tauto\n' in expected.read_text()
    before=(f.e/'running.cfg').read_bytes()
    expected.write_text('-\n')
    r=compile('no object-group fqdn domain-list0')
    assert r.returncode==75 and (f.e/'running.cfg').read_bytes()==before, 'compiler ignored current scope precondition'
    for cmd in ('object-group fqdn Owner','object-group fqdn domain-list0; touch /tmp/NO',
                'dns-proxy route object-group domain-list0 Wireguard0','system configuration save'):
        assert compile(cmd).returncode!=0,cmd
    assert not f.trace.exists(),'pure compiler called a transport'
print('NATIVE_COMPILER=PASS closed literal commands, exact prefix CAS, unrelated native bytes retained; no transport')
