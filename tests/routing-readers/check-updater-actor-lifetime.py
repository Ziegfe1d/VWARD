#!/usr/bin/env python3
"""Updater quiescence distinguishes a real zombie, a live actor and unknown identity."""
import os
import subprocess
from fixture import Fixture,ROOT

with Fixture() as f:
    prefix=f.p/'update-root'
    active=prefix/'tmp/vward-runtime-active';active.mkdir(parents=True,mode=0o700)
    updater=ROOT/'components/update-engine'
    def slot(pid):
        start=open(f'/proc/{pid}/stat').read().rsplit(') ',1)[1].split()[19]
        s=active/f'routing-publisher.{pid}.{start}';s.mkdir(mode=0o700)
        (s/'pid').write_text(str(pid)+'\n');(s/'pid_start').write_text(start+'\n');(s/'component').write_text('routing-publisher\n')
        return s
    def inspect(extra=''):
        return f.run('SELF_DIR="$1";. "$SELF_DIR/vward-update-common.sh"\n'+extra+
                     '\nrc=0;vu_activity_clear || rc=$?;printf "activity=%s why=%s\\n" "$rc" "${VU_ACTIVITY_WHY:-}";exit "$rc"',
                     updater,env=f.env|{'VWARD_ROOT_PREFIX':str(prefix)})
    p=subprocess.Popen(['sh','-c',':'])
    try:
        os.waitid(os.P_PID,p.pid,os.WEXITED|os.WNOWAIT)
        assert open(f'/proc/{p.pid}/stat').read().rsplit(') ',1)[1].split()[0]=='Z'
        s=slot(p.pid);r=inspect()
        assert r.returncode==0 and not s.exists(),('zombie retained execution authority',r.returncode,r.stdout,r.stderr)
    finally:p.wait(timeout=5)
    p=subprocess.Popen(['sleep','30'])
    try:
        s=slot(p.pid);before={x.name:x.read_bytes() for x in s.iterdir()}
        r=inspect();assert r.returncode==1 and s.is_dir() and 'active:' in r.stdout,(r.returncode,r.stdout,r.stderr)
        # Identity parsing is independent of a caller's TSV parser settings;
        # its local split must not overwrite the caller's IFS either.
        start=(s/'pid_start').read_text().strip()
        r=f.run('SELF_DIR="$1";. "$SELF_DIR/vward-update-common.sh";IFS="|";'
                'vu_actor_status "$2" "$3" && [ "$IFS" = "|" ]',
                updater,p.pid,start,env=f.env|{'VWARD_ROOT_PREFIX':str(prefix)})
        assert r.returncode==0,('caller IFS leaked into actor identity',r.returncode,r.stderr)
        # An unavailable kernel identity is NOT evidence of process death.
        r=inspect('vu_process_stat() { return 2; }')
        assert r.returncode==1 and {x.name:x.read_bytes() for x in s.iterdir()}==before,('unknown actor reaped',r.returncode,r.stdout,r.stderr)
        os.kill(p.pid,0)
    finally:p.terminate();p.wait(timeout=5)
print('UPDATER_ACTOR_LIFETIME=PASS kernel zombie non-authority, real live and unknown actor remain fenced; no process killed/replayed')
