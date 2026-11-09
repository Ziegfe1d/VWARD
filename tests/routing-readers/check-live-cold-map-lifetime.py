#!/usr/bin/env python3
"""Discovery surviving coordinator-only death cannot overwrite a newer shared map."""
import os
import shutil
import signal
import subprocess
import time
from fixture import SHELL,function_source
from live_fixture import LiveFixture

def until(path):
    end=time.monotonic()+8
    while not path.exists() and time.monotonic()<end:time.sleep(.02)
    assert path.exists(),path.name

with LiveFixture() as f:
    f.install_console()
    r=f.console('service','off','svc');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    shutil.rmtree(f.live)
    shared=f.prefix/'tmp/vward-device-map.tsv';shared.unlink()
    f.install_rci();(f.p/'rci-pause').touch()
    profile=f.prefix/'opt/lib/vward/vward-device-profile.sh'
    source=function_source(profile,'vward_device_map')
    point='    printf \'%s\\n\' "$_vp_map"\n'
    assert source.count(point)==1,'actual discovery completion boundary moved'
    actual=profile.read_text();assert actual.count(source)==1
    profile.write_text(actual.replace(source,source.replace(point,'    printf done > "$DISCOVERY_DONE"\n'+point)))
    done=f.p/'discovery-done'
    env=f.env|{'DISCOVERY_DONE':str(done),'VWARD_DEVICE_CONFIG_OWNER_UID':str(os.getuid()),
               'VWARD_CONSOLE_EDIT_LOCK':str(f.prefix/'tmp/vward-console-edit.lock'),
               'VWARD_ROUTE_CHANGE_LOCK':str(f.prefix/'tmp/vward-route-change.lock'),
               'VWARD_CONSOLE_AUDIT_LOG':str(f.p/'console-audit')}
    p=subprocess.Popen(SHELL+[str(f.console_path),'service','on','svc','Wireguard1'],env=env,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:
        until(f.p/'rci-paused')
        coordinator=int((f.prefix/'tmp/vward-console-edit.lock/pid').read_text())
        os.kill(coordinator,signal.SIGKILL)
        shared.write_text('I\tNewOwner\tWireguard\tnew0\tprivate\n');shared.chmod(0o600)
        inode=shared.stat().st_ino;replacement=shared.read_bytes()
        before=f.native.read_bytes();saved=f.startup.read_bytes()
        (f.p/'rci-resume').touch();until(done)
        out,err=p.communicate(timeout=8)
        assert p.returncode!=0 and not f.live.exists(),(p.returncode,out,err)
        assert shared.stat().st_ino==inode and shared.read_bytes()==replacement,'late discovery overwrote replacement map'
        assert f.native.read_bytes()==before and f.startup.read_bytes()==saved
    finally:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.communicate(timeout=5)
print('LIVE_COLD_MAP_LIFETIME=PASS parent-only kill/replacement map/late actual discovery preserves shared map and native state')
