#!/usr/bin/env python3
"""Closed HTTPS commands compile the same exact native scope with zero transport."""
from fixture import PipelineFixture,CFG

with PipelineFixture() as f:
    (f.e/'running.cfg').write_text(CFG)
    work=f.p/'compile';work.mkdir(mode=0o700)
    expected=f.p/'expected';expected.write_text('https upstream https://dns.example/secret-token domain smart.example\n')
    before=(f.e/'running.cfg').read_bytes()
    def compile(cmd):
        return f.invoke('vrb_native_dns_compile',cmd,f.e/'running.cfg',expected,work)
    r=compile('dns-proxy https upstream https://neutral.example.test/dns-query domain new.example')
    assert r.returncode==0,(r.returncode,r.stderr)
    after=(work/'config.next').read_text()
    assert 'https upstream https://neutral.example.test/dns-query domain new.example' in after
    assert 'route object-group Mine Wireguard0 auto' in after and 'object-group fqdn Mine' in after
    for middle in ('dnsm','dnsm on ISP','on ISP','on ISP dnsm'):
        r=compile('dns-proxy https upstream https://neutral.example.test/dns-query '+middle+' domain new.example')
        assert r.returncode==0,('supported native dnsm/on form rejected',middle,r.returncode,r.stderr)
    r=compile('dns-proxy no https upstream https://dns.example/secret-token')
    assert r.returncode==0 and 'domain smart.example' not in (work/'config.next').read_text(),(r.returncode,r.stderr)
    for command in ('dns-proxy https upstream http://neutral.example.test/x domain new.example',
                    'dns-proxy no https upstream https://dns.example/secret-token domain smart.example',
                    'dns-proxy https upstream https://neutral.example.test/x domain evil;command.example',
                    'dns-proxy https upstream https://neutral.example.test/x domain a.example\nshow running-config',
                    'dns-proxy https upstream https://neutral.example.test/x',
                    'object-group fqdn domain-list0'):
        r=compile(command);assert r.returncode!=0,('nonclosed DNS command accepted',command)
    expected.write_text('')
    r=compile('dns-proxy no https upstream https://dns.example/secret-token')
    assert r.returncode==75,'changed HTTPS scope passed CAS'
    assert (f.e/'running.cfg').read_bytes()==before and not f.trace.exists(),'compiler invoked a transport'
print('NATIVE_DNS_COMPILER=PASS closed URL-wide withdrawal/add grammar, exact HTTPS precondition, unrelated native bytes preserved/no transport')
