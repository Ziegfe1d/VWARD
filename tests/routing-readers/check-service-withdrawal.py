#!/usr/bin/env python3
"""Retired service withdrawal requires exact private own scope; other unknown stays."""
import json
from live_fixture import LiveFixture

with LiveFixture() as f:
    (f.live/'decision/bindings.tsv').write_text('')
    f.install_console()
    r=f.console('service','on','svc','Wireguard0')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    catalog=f.prefix/'opt/var/lib/vward/services/catalog.json'
    c=json.loads(catalog.read_text());c['services']=[s for s in c['services'] if s['id']!='svc'];catalog.write_text(json.dumps(c))
    bindings=f.live/'decision/bindings.tsv'
    bindings.write_text(bindings.read_text().replace('\tconfirmed\tipv4\tknown','\tunknown\tunknown\tunknown'))
    before=f.native.read_bytes()
    enabled=f.etc/'services/enabled.tsv';registration=enabled.read_text();group=registration.split('\t')[1]
    proof=f.etc/'services/owned'/group;proof_bytes=proof.read_bytes();proof_mode=proof.stat().st_mode&0o777
    counter=0
    def query(project=False):
        global counter
        counter+=1
        work=f.p/f'withdraw-stage-{counter}';work.mkdir(mode=0o700)
        out=f.p/f'withdraw-project-{counter}';out.mkdir(mode=0o700)
        action='vward_routing_project2 "$2" svc "$3/next" "$3" && vward_routing_plan2 "$2" "$3" withdraw' if project else 'vr2_own_service_withdrawal "$2" svc "$3/next"'
        script='''vrl_bind
vrl_envelope "$1" inspect-withdraw || exit 75
vrl_refresh && vward_routing_consistent_read2 "$2" "$vrb_e/decision" >/dev/null || exit 75
vward_routing_choice "$2/decision/choices.tsv" svc off - - 1 > "$3/next" || exit 75
'''+action
        return f.run(f.script(script),*f.libs,f.live/'journal',work,out,timeout=20)
    r=query();assert r.returncode==0,('positive exact withdrawal boundary not reached',r.returncode,r.stdout,r.stderr)
    proof.unlink()
    r=query();assert r.returncode!=0,'missing native private proof was accepted'
    proof.write_bytes(proof_bytes);proof.chmod(proof_mode)
    f.native.write_text(f.native.read_text().replace('object-group fqdn '+group+'\n','object-group fqdn '+group+'\n    include foreign.example\n'))
    r=query();assert r.returncode!=0,'foreign group member was accepted as own scope'
    f.native.write_bytes(before)
    enabled.write_text(registration+'other\t'+group+'\tWireguard0\n')
    r=query();assert r.returncode!=0,'unbound legacy service was hidden behind canonical withdrawal'
    enabled.write_text(registration)
    # The exception covers the retired S registration only. An independent A
    # active record without a fresh native-boot probe remains unknown/HOLD.
    evidence=f.live/'decision/evidence.tsv'
    evidence.write_text('A\ta-unknown\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t1\tsvc\n')
    r=query(project=True)
    assert r.returncode==0 and '\nhold\t' in r.stdout and '\nstep\t' not in r.stdout,('unknown A acquired authority during withdrawal',r.returncode,r.stdout,r.stderr)
    assert f.native.read_bytes()==before and enabled.read_text()==registration,'read-only withdrawal checks wrote native/registry'
print('SERVICE_WITHDRAWAL=PASS exact own positive; missing private proof/foreign member/unbound legacy refuse; independent A unknown still HOLD')
