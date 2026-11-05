#!/usr/bin/env python3
"""Observe absent/partial legacy B state without inventing a usable v2 ledger."""
from fixture import Fixture,READ,OBSERVE,SNAP,AUDIT,LIBDIR
with Fixture() as f:
    d=f.p/'absent-state';d.mkdir(mode=0o700)
    out=f.p/'stage';out.mkdir(mode=0o700)
    libs=(READ,OBSERVE,SNAP,AUDIT,LIBDIR/'vward-routing-project.sh')
    def call(name):
        return f.run('for lib in "$1" "$2" "$3" "$4" "$5";do . "$lib";done;shift 5;"$@"',*libs,name,out,d)
    r=call('vward_routing_consistent_read2');assert r.returncode==3 and not (out/'generation').exists()
    r=call('vward_routing_bootstrap_read2');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (out/'decision/version.tsv').read_text()=='routing-state\t0\n'
    assert (out/'decision/choices.tsv').read_text()=='schema\t1\n'
    assert (out/'inventory.tsv').read_text() and 'v2-version absent' in (out/'inputs.fp').read_text()
    next_choice=f.p/'next';next_choice.write_text('schema\t1\n')
    project=f.p/'projection';project.mkdir(mode=0o700)
    r=f.run('. "$1";. "$2";vward_routing_project2 "$3" svc "$4" "$5"',AUDIT,libs[-1],out,next_choice,project)
    assert r.returncode==2 and not (project/'generation').exists(),'legacy observation granted v2 planning rights'
    # A partial interrupted bootstrap remains explicit observation0 even if a
    # foreign/version-last marker is already present. Strict v2 still refuses.
    p=d/'version.tsv';p.write_text('routing-state\t2\n');p.chmod(0o600)
    r=call('vward_routing_consistent_read2');assert r.returncode==3
    r=call('vward_routing_bootstrap_read2');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (out/'decision/version.tsv').read_text()=='routing-state\t0\n'
    assert 'v2-version absent' not in (out/'inputs.fp').read_text()
print('B_BOOTSTRAP_READ=PASS absent/partial fingerprints; observation0 never accepted as usable state2')
