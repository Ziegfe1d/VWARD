#!/usr/bin/env python3
"""The first ROOT publisher must revalidate its actual parent namespace."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from fixture import LIBDIR,SHELL,function_source,digest
from live_fixture import LiveFixture

for phase in ('prepare','publish'):
    with LiveFixture() as f:
        shutil.rmtree(f.live)
        if os.environ.get('RS6_BUSYBOX'):(f.p/'poison/mv').symlink_to(os.environ['RS6_BUSYBOX'])
        name='vrl_init_prepare' if phase=='prepare' else 'vrl_init_publish'
        source=function_source(LIBDIR/'vward-routing-bootstrap.sh',name)
        point=('    vrl_init_parent && vrj2_file "$vrl_etc/device.conf" || return 75\n' if phase=='prepare' else
               '    vrl_init_parent && vrl_init_seal_valid "$1" || return 75\n    # BusyBox/GNU')
        assert source.count(point)==1,(phase,'actual preparation/final publisher boundary moved')
        source=source.replace(point,'''    printf paused > "$PAUSED"
    while [ ! -e "$RESUME" ];do sleep .02;done
'''+point)
        paused=f.p/'ancestry-paused';resume=f.p/'ancestry-resume'
        env=f.env|{'PAUSED':str(paused),'RESUME':str(resume)}
        p=subprocess.Popen(SHELL+['-c',f.script(source+'vward_routing_live_bootstrap first'),
                           'bootstrap',*map(str,f.libs)],env=env,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            end=time.monotonic()+8
            while not paused.exists() and time.monotonic()<end:time.sleep(.02)
            assert paused.exists(),(phase,'boundary was not reached')
            parent=f.live.parent;kept=parent.with_name('vward-kept')
            parent.rename(kept);parent.symlink_to(kept,target_is_directory=True)
            retained=digest(kept);native=f.native.read_bytes();saved=f.startup.read_bytes()
            resume.touch();out,err=p.communicate(timeout=8)
            assert p.returncode==75 and not (kept/'routing').exists(),(
                phase,'ROOT published through a replaced ancestor',p.returncode,out,err)
            assert digest(kept)==retained and f.native.read_bytes()==native and f.startup.read_bytes()==saved,(
                phase,'aliased subtree or native configuration changed after refusal')
        finally:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            p.communicate(timeout=5)
print('LIVE_BOOTSTRAP_ANCESTRY=PASS actual prepare/final publisher refuse replaced parent; no ROOT transfer or aliased/native writes')
