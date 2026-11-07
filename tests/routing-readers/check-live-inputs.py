#!/usr/bin/env python3
"""Actual CLI refreshes captured membership/defaults and configuration health."""
from live_fixture import LiveFixture

with LiveFixture(vpns=3) as f:
    f.install_console()
    decision=f.live/'decision'
    # No fabricated service membership or cached positive health on first use.
    (decision/'bindings.tsv').write_text('')
    (decision/'context.tsv').write_text('source:M\t1\nsource:S\t1\nsource:A\t1\n')
    (f.etc/'services/categories.tsv').write_text('ai\tWireguard2\n')
    before=f.startup.read_bytes()
    r=f.console('service','on','svc','auto')
    assert r.returncode==0 and 'result=changed' in r.stdout,('fresh actual action',r.returncode,r.stdout,r.stderr)
    assert '\tvpn\tVPN:auto\tdefault\t' in (decision/'choices.tsv').read_text()
    assert ' Wireguard2 auto' in f.native.read_text(),'captured category did not choose its VPN'
    assert (f.etc/'services/enabled.tsv').read_text().rstrip().endswith('\tauto')
    bindings=(decision/'bindings.tsv').read_text()
    assert 'svc\tx.example\texact\tconfirmed\tipv4\tknown\n' in bindings
    assert 'svc\ts.example\texact\tconfirmed\tipv4\tknown\n' in bindings
    assert 'off.example' not in bindings,'unrequested inactive catalog was imported wholesale'
    assert before!=f.startup.read_bytes() and f.startup.read_bytes()==f.native.read_bytes()
    calls=f.calls.read_text()
    assert '\tshow interface Wireguard2\n' in calls and 'show interface GigabitEthernet1' not in calls
    committed={p.name for p in (f.live/'journal').iterdir() if (p/'state').is_file()}
    before=f.native.read_bytes()
    r=f.console('service','on','svc','auto')
    assert r.returncode==0 and 'result=unchanged' in r.stdout and f.native.read_bytes()==before,('repeat without new input',r.returncode,r.stdout,r.stderr)
    assert committed=={p.name for p in (f.live/'journal').iterdir() if (p/'state').is_file()},'unchanged input created another physical state transaction'
    # A captured explicit category target disappearing does not fall back to
    # the profile default, and an unknown health result never uses cached UP.
    (f.etc/'services/categories.tsv').write_text('ai\tWireguard77\n')
    before=f.native.read_bytes();choices=(decision/'choices.tsv').read_bytes()
    r=f.console('service','on','svc','auto')
    assert r.returncode!=0 and f.native.read_bytes()==before and (decision/'choices.tsv').read_bytes()==choices,('missing category silently fell back',r.returncode,r.stdout,r.stderr)
    assert committed=={p.name for p in (f.live/'journal').iterdir() if (p/'state').is_file()},'denied dependency request published a durable observation transaction'
    (f.etc/'services/categories.tsv').write_text('ai\tWireguard2\n')
    (f.p/'interface-unknown-Wireguard2').write_text('1')
    r=f.console('service','on','svc','auto')
    assert r.returncode!=0 and f.native.read_bytes()==before and (decision/'choices.tsv').read_bytes()==choices,('unknown interface reused cached UP',r.returncode,r.stdout,r.stderr)
    (f.p/'interface-unknown-Wireguard2').unlink()
    (f.etc/'services/categories.tsv').unlink()
    r=f.console('service','on','svc','auto')
    assert r.returncode==0 and ' Wireguard0 auto' in f.native.read_text(),('normal absent category did not use profile default',r.returncode,r.stdout,r.stderr)
print('LIVE_INPUTS=PASS actual CLI fresh catalog/category/configuration health, logical auto retained, no WAN probe or missing-target fallback')
