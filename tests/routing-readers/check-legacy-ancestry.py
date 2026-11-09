#!/usr/bin/env python3
"""A private leaf is insufficient when an intermediate DATA parent is a link."""
import os,signal,subprocess,time
from fixture import PipelineFixture,SHELL

def legacy_file(root):
    p=root/'domain-lists';p.mkdir(parents=True,mode=0o700)
    leaf=p/'domain-list0';leaf.write_text('route=ISP\tauto\ndoh=https upstream https://dns.example.test/dns-query domain x.example\n');leaf.chmod(0o600)
    return leaf

with PipelineFixture() as f:
    f.configure_dns('keenetic')
    external=f.p/'external-legacy';external.mkdir(mode=0o700);leaf=legacy_file(external);before=leaf.read_bytes()
    (f.e/'route-engine').symlink_to(external)
    work=f.p/'work';work.mkdir(mode=0o700);(work/'stage').mkdir(mode=0o700);(work/'lower').mkdir(mode=0o700)
    script='''vrb_envelope "$1" ancestry || exit $?
    cp "$vrb_e/running.cfg" "$vrb_e/running-config"
    vward_routing_consistent_read2 "$2/stage" "$vrb_e/decision" >/dev/null || exit $?
    cp "$2/stage/inputs.fp" "$2/lower/inputs.fp"
    printf 'routing-plan\\t2\\t%s\\tdenied\\n' "$(cat "$2/stage/generation")" > "$2/lower/plan"
    vrb_compile_legacy_prune "$2/stage" "$2/lower" delete url1 -
    '''
    r=f.run(f.script(script),*f.libs,f.j,work,timeout=12)
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr,'compiler escaped DATA root through an ancestor symlink')
    assert leaf.read_bytes()==before and not (f.e/'calls').exists()

with PipelineFixture() as f:
    f.configure_dns('keenetic')
    original=f.e/'route-engine';original.mkdir(mode=0o700);leaf=legacy_file(original);before=leaf.read_bytes()
    external=f.p/'external-legacy';external.mkdir(mode=0o700);other=legacy_file(external)
    (f.e/'publish-pause').touch()
    p=subprocess.Popen(SHELL+['-c',f.script('vward_routing_server2 "$@"'),'swap',*map(str,f.libs),str(f.j),'swap','policy1','delete','-','1'],
        env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        end=time.monotonic()+12
        while not (f.e/'publish-waiting').exists() and p.poll() is None and time.monotonic()<end:time.sleep(.02)
        assert (f.e/'publish-waiting').exists(),'RAW publisher did not reach the fault point'
        original.rename(f.e/'route-engine-before');original.symlink_to(external)
        (f.e/'publish-pause').unlink()
        out,err=p.communicate(timeout=8)
        assert p.returncode==3,(p.returncode,out,err)
        assert other.read_bytes()==before and (f.e/'route-engine-before/domain-lists/domain-list0').read_bytes()==before,'publisher wrote through a replaced ancestor'
        assert (f.j/'swap/state').read_text()=='unknown\n'
    finally:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.wait(timeout=5)
print('B_LEGACY_ANCESTRY=PASS compiler and final publication refuse symlink ancestors, external DATA bytes preserved')
