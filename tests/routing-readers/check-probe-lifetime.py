#!/usr/bin/env python3
"""A persisted positive/active flag is not a fresh probe across boot/expiry."""
from fixture import Fixture,READ,OBSERVE,SNAP,AUDIT,LIBDIR,digest
BOOT1='11111111-1111-1111-1111-111111111111'
BOOT2='22222222-2222-2222-2222-222222222222'
with Fixture() as f:
    f.cfg.write_text('interface Wireguard0\n!\ndns-proxy\n!\n');f.enabled.write_text('');f.persist.write_text('')
    d=f.p/'decision';d.mkdir(mode=0o700)
    for key in ('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs','upstreams'):
        p=d/(key+'.tsv');p.write_text('');p.chmod(0o600)
    (d/'version.tsv').write_text('routing-state\t2\n');(d/'choices.tsv').write_text('schema\t1\nservice\tsvc\t5\tauto\t-\t-\t0\n')
    (d/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\n')
    (d/'evidence.tsv').write_text('A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tpositive\t5\tsvc\n')
    (d/'context.tsv').write_text(f'source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\nprobe:a1\tfresh\nprobe-boot:a1\t{BOOT1}\nprobe-until:a1\t155\n')
    stage=f.p/'stage';stage.mkdir(mode=0o700);project=f.p/'project';project.mkdir(mode=0o700)
    next_choice=f.p/'next';r=f.run('. "$1";vward_routing_choice "$2" svc auto - - 5',AUDIT,d/'choices.tsv');assert r.returncode==0
    next_choice.write_text(r.stdout)
    def view(boot,now):
        script='. "$1";. "$2";. "$3"; vr2_clock_read() { printf "%s %s\\n" "$TEST_BOOT" "$TEST_NOW"; };vward_routing_consistent_read2 "$4" "$5"'
        r=f.run(script,READ,OBSERVE,SNAP,stage,d,env=f.env|{'TEST_BOOT':boot,'TEST_NOW':str(now)})
        assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        r=f.run('. "$1";. "$2";vward_routing_project2 "$3" svc "$4" "$5"',AUDIT,LIBDIR/'vward-routing-project.sh',stage,next_choice,project)
        assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        active=any(x.split('\t')[1:4]==['contribution','A','a1'] and x.split('\t')[6]=='active' for x in (project/'policy.tsv').read_text().splitlines())
        return active,(stage/'generation').read_text()
    before=digest(d)
    active,g1=view(BOOT1,100);assert active,'fresh current-boot positive was rejected'
    active,g2=view(BOOT2,10);assert not active,'old-boot positive became fresh after reboot'
    assert g1!=g2,'reboot failed to invalidate the old operation generation'
    active,_=view(BOOT1,156);assert not active,'expired positive remained a fresh Auto contributor'
    (d/'context.tsv').write_text((d/'context.tsv').read_text().replace('155','100000'))
    active,_=view(BOOT1,100);assert not active,'unbounded future deadline granted a fresh probe'
    (d/'context.tsv').write_text((d/'context.tsv').read_text().replace('100000','155'))
    assert digest(d)==before,'read adapter rewrote persisted evidence'
print('B_PROBE_LIFETIME=PASS current boot/deadline required, old/expired/unbounded probes inactive, read-only')
