#!/usr/bin/env python3
"""One connected B fixture: stage -> real choice/policy -> plan -> journal/workers/readback.

Uses the existing native-router fixture. No router, arbitrary executor, or network.
"""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture import Fixture, READ, SNAP, OBSERVE, AUDIT, PLAN, JOURNAL, DRYRUN, digest

EXTRA=('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs')
with Fixture() as f:
    inp=f.p/'decision';inp.mkdir(mode=0o700)
    for name in EXTRA:(inp/(name+'.tsv')).write_text('')
    (inp/'version.tsv').write_text('routing-state\t2\n')
    (inp/'choices.tsv').write_text('schema\t1\n')
    (inp/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\n')
    (inp/'context.tsv').write_text('source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\n')
    out=f.p/'out';out.mkdir(mode=0o700)
    shim=f.p/'poison';shim.mkdir();trace=f.p/'transport'
    for name in ('ndmc','curl','comm','cksum'):
        p=shim/name;p.write_text('#!/bin/sh\necho '+name+' >> "'+str(trace)+'"\nexit 99\n');p.chmod(0o755)
    if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH']}
    def stage():
        return f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',
                     READ,OBSERVE,SNAP,out,inp,env=env)
    before=digest(f.p);r=stage()
    assert r.returncode==0,(r.stdout,r.stderr)
    gen=(out/'generation').read_text();assert gen.startswith('g-')
    assert sorted(x.name for x in (out/'decision').iterdir())==[x+'.tsv' for x in sorted(EXTRA)]
    for name in EXTRA:assert (out/'decision'/(name+'.tsv')).read_bytes()==(inp/(name+'.tsv')).read_bytes()
    assert stage().stdout==r.stdout,'repeat changed generation'
    (inp/'choices.tsv').write_text('schema\t1\nservice\tsvc\t1\tisp\tISP\tdefault\t0\n')
    r=stage();assert r.returncode==0 and (out/'generation').read_text()!=gen,'choice missing from generation'
    for name in ('bindings','evidence','tombstones'):
        p=inp/(name+'.tsv');old=p.read_text();oldgen=(out/'generation').read_text()
        p.write_text(old+'new\n');r=stage()
        assert r.returncode==0 and (out/'generation').read_text()!=oldgen,(name,r.stdout,r.stderr)
        p.write_text(old)
    # Missing/symlink/FIFO is unknown, never stale generation or a partly valid stage.
    p=inp/'queue.tsv';p.unlink()
    r=stage();assert r.returncode==3 and not (out/'generation').exists(),(r.stdout,r.stderr)
    os.mkfifo(p);r=stage();assert r.returncode==3 and not (out/'generation').exists()
    p.unlink();p.symlink_to(inp/'choices.tsv');r=stage();assert r.returncode==3 and not (out/'generation').exists()
    p.unlink();p.write_text('')
    assert stage().returncode==0
    # Permission changes are authority changes even when file bytes/inode/mtime
    # are unchanged. Mixed identities cannot share a known generation.
    real=f.p/'read-real.sh';real.write_text(READ.read_text().replace('vward_routing_read() (','vward_routing_read_real() (',1))
    script='''
    . "$1"; . "$2"; . "$3"; test_proof=$6
    vward_routing_read() {
        [ "$1" != identity ] || chmod 0644 "$test_proof"
        vward_routing_read_real "$@"
    }
    vward_routing_consistent_read2 "$4" "$5"
    '''
    r=f.run(script,real,OBSERVE,SNAP,out,inp,f.proof,env=env)
    assert r.returncode==3 and not (out/'generation').exists(),'authority changed between projections but stage stayed known'
    f.proof.chmod(0o600)
    assert not trace.exists(),'stage called transport/comm/cksum'
print('B_PIPELINE_STAGE=PASS native+choice/bindings/evidence/versions, consistent copies, no transports/cksum')
