#!/usr/bin/env python3
"""Real updater request must not cross routing unknown; EDIT freezes new coordinators."""
import os
import shlex
import shutil
import signal
import subprocess
import time
from fixture import PipelineFixture, LIBDIR, ROOT, SHELL, function_source

UPDATER = ROOT / 'components/update-engine'

def installed(f):
    prefix = f.p / 'updater-root'
    (prefix / 'tmp').mkdir(parents=True)
    libs = prefix / 'opt/lib/vward'; libs.mkdir(parents=True)
    for lib in LIBDIR.glob('*.sh'): shutil.copy2(lib, libs / lib.name)
    state = prefix / 'opt/var/lib/vward/routing'; state.mkdir(parents=True, mode=0o700)
    shutil.copytree(f.decision, state / 'decision')
    shutil.copytree(f.j, state / 'journal')
    return prefix, state

def request(f, prefix, spy=False, busy=False, fail_publish=False):
    script = 'SELF_DIR='+shlex.quote(str(UPDATER))+'\n. "$SELF_DIR/vward-update-common.sh"\n'
    if spy:
        script += r'''
printf() {
    # This is the actual marker redirection/printf boundary, not a successful
    # stand-in request. Delegate every print to the real shell builtin.
    if [ "$#" = 2 ] && [ "$1" = '%s\n' ] && [ "$2" = "$VU_LOCK_TOKEN" ] && [ -f "$VU_REQUEST_MARKER" ]; then
        [ -d "$VU_ROOT_PREFIX/tmp/vward-console-edit.lock" ] || return 1
        IFS=' ' read -r publisher_pid _ < /proc/self/stat || return 1
        [ "$(cat "$VU_ROOT_PREFIX/tmp/vward-console-edit.lock/pid")" = "$publisher_pid" ] || return 1
        command printf 'observed\n' > "$VU_ROOT_PREFIX/tmp/request-under-edit"
    fi
    command printf "$@"
}
'''
    if fail_publish:
        script += r'''
printf() {
    if [ "$#" = 2 ] && [ "$1" = '%s\n' ] && [ "$2" = "$VU_LOCK_TOKEN" ] && [ -f "$VU_REQUEST_MARKER" ]; then
        [ -d "$VU_ROOT_PREFIX/tmp/vward-console-edit.lock" ] || exit 90
        return 1
    fi
    command printf "$@"
}
'''
    if busy:
        script += '. "$VU_ROOT_PREFIX/opt/lib/vward/vward-runtime-admission.sh"\n'
        script += 'vward_lock_take "$VU_ROOT_PREFIX/tmp/vward-console-edit.lock" || exit 91\n'
    script += '''
vu_lock_acquire || exit 9
trap 'vu_barrier_leave; vu_lock_release' EXIT
vu_barrier_recover_stale || exit 8
previous_mask=$(umask)
case $- in *C*) previous_noclobber=1 ;; *) previous_noclobber=0 ;; esac
result=0
vu_barrier_request || result=$?
[ "$(umask)" = "$previous_mask" ] || exit 94
case $- in *C*) current_noclobber=1 ;; *) current_noclobber=0 ;; esac
[ "$previous_noclobber" = "$current_noclobber" ] || exit 95
printf 'request_rc=%s why=%s\n' "$result" "${VU_QUIESCE_WHY:-}"
[ "$result" != 0 ] || [ -f "$VU_REQUEST_MARKER" ] || exit 7
'''
    if busy:
        script += '[ -d "$VU_ROOT_PREFIX/tmp/vward-console-edit.lock" ] || exit 92\n'
        script += 'vward_lock_release "$VU_ROOT_PREFIX/tmp/vward-console-edit.lock" || exit 93\n'
    script += 'exit "$result"\n'
    return f.run(script, env=f.env | {'VWARD_ROOT_PREFIX': str(prefix)}, timeout=30)

with PipelineFixture() as f:
    (f.e / 'save-fails').touch()
    r=f.invoke('vward_routing_pipeline2', f.j, 'pending', 'svc', 'vpn', 'VPN:Wireguard0', 'default', 0)
    assert r.returncode==3, (r.stdout,r.stderr)
    prefix,state=installed(f)
    before={p:p.read_bytes() for p in state.rglob('*') if p.is_file()}
    r=request(f,prefix)
    assert r.returncode!=0 and 'routing' in r.stdout, ('unknown crossed updater request',r.returncode,r.stdout,r.stderr)
    assert all(p.read_bytes()==b for p,b in before.items()), 'updater changed unknown routing evidence'
    assert not (prefix/'tmp/vward-update-requested').exists()

with PipelineFixture() as f:
    prefix,state=installed(f)
    r=request(f,prefix,spy=True)
    assert r.returncode==0, ('healthy request did not freeze EDIT first',r.returncode,r.stdout,r.stderr)
    assert (prefix/'tmp/request-under-edit').read_text()=='observed\n', 'request spy did not reach real publication'
    assert not (prefix/'tmp/vward-console-edit.lock').exists(), 'EDIT stayed held after request'
    assert not (prefix/'tmp/vward-update-requested').exists(), 'request cleanup failed'

with PipelineFixture() as f:
    prefix,state=installed(f)
    r=request(f,prefix,busy=True)
    assert r.returncode==1 and 'routing' in r.stdout, ('busy EDIT crossed',r.returncode,r.stdout,r.stderr)
    assert not (prefix/'tmp/vward-update-requested').exists()
    assert not (prefix/'tmp/vward-console-edit.lock').exists()
    # Even the first bootstrap must serialize against the request marker;
    # absence of common state is not absence of a concurrent new coordinator.
    shutil.rmtree(state)
    r=request(f,prefix,spy=True)
    assert r.returncode==0, ('no-state request bypassed EDIT',r.returncode,r.stdout,r.stderr)
    assert not state.exists(), 'updater implicitly bootstrapped routing state'
    r=request(f,prefix,fail_publish=True)
    assert r.returncode==1, ('marker failure hidden',r.returncode,r.stdout,r.stderr)
    assert not (prefix/'tmp/vward-console-edit.lock').exists(), 'failed marker leaked EDIT'
    assert (prefix/'tmp/vward-update-requested').exists(), 'unconfirmed partial marker silently discarded'
print('LIVE_UPDATER_ADMISSION=PASS persistent unknown held, healthy request freezes EDIT then releases; evidence preserved')

def until(path):
    end=time.monotonic()+8
    while not path.exists() and time.monotonic()<end: time.sleep(.02)
    assert path.exists(), path.name

def stop(proc):
    if proc is None: return
    try: os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    proc.communicate(timeout=5)

# Pause the ACTUAL publisher before redirection. A historical child publisher
# really survives parent-only death and crosses a replacement EDIT holder.
# The corrected publisher is that owner itself and cannot resume after death.
for old_child in (True,False):
    with PipelineFixture() as f:
        prefix,state=installed(f)
        pause=f.p/'marker-paused';resume=f.p/'marker-resume';held=f.p/'new-edit-held'
        fault='''IFS=' ' read -r fixture_pid _ < /proc/self/stat || exit 96
printf '%s\\n' "$fixture_pid" > "$PAUSED"
while [ ! -f "$RESUME" ]; do sleep .02; done
'''
        publish=function_source(UPDATER/'vward-update-common-base.sh','vu_barrier_request_publish')
        point='    printf \'%s\\n\' "$VU_LOCK_TOKEN" > "$VU_REQUEST_MARKER" 2>/dev/null || vu_rr_publish_rc=$?\n'
        assert publish.count(point)==1, 'request publisher fault boundary changed'
        publish=publish.replace(point,fault+point)
        if old_child:
            # Keep the actual guards; restore ONLY the former unleased final
            # publication shape, to prove this regression detects its lifetime.
            publish=publish.replace('    vu_rr_umask=$(umask)', '    (\n    vu_rr_umask=$(umask)',1)
            publish=publish.replace('    return "$vu_rr_publish_rc"','    exit "$vu_rr_publish_rc"\n    ) || return 1\n    VU_REQUEST_OWNED=1',1)
        script='SELF_DIR='+shlex.quote(str(UPDATER))+'\n. "$SELF_DIR/vward-update-common.sh"\n'+publish
        script+='\nvu_lock_acquire && vu_barrier_request\n'
        env=f.env | {'VWARD_ROOT_PREFIX':str(prefix),'PAUSED':str(pause),'RESUME':str(resume)}
        p=subprocess.Popen(SHELL+['-c',script],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        q=None
        try:
            until(pause)
            publisher=int(pause.read_text())
            assert (publisher!=p.pid)==old_child, ('wrong actual publisher',publisher,p.pid)
            os.kill(p.pid,signal.SIGKILL);p.wait(timeout=5)
            assert not (prefix/'tmp/vward-update-requested').exists()
            lock=prefix/'tmp/vward-console-edit.lock'
            holder='. '+shlex.quote(str(LIBDIR/'vward-runtime-admission.sh'))+'\n'
            holder+='vward_lock_take "$1" || exit 75\nprintf held > "$2"\nsleep 30\n'
            q=subprocess.Popen(SHELL+['-c',holder,'holder',str(lock),str(held)],env=env,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            until(held)
            new_owner=(lock/'pid').read_text()
            resume.touch()
            marker=prefix/'tmp/vward-update-requested'
            if old_child: until(marker)
            else: assert not marker.exists(), 'dead elected owner published a late request'
            assert (lock/'pid').read_text()==new_owner, 'old request changed replacement EDIT'
        finally:
            stop(q);stop(p)
print('LIVE_UPDATER_LIFETIME=PASS old unleased child RED, elected owner GREEN after parent-only kill/replacement EDIT')
