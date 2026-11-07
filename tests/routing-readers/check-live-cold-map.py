#!/usr/bin/env python3
"""Cold bootstrap uses the existing profile's show-only device-map discovery."""
import shutil
from live_fixture import LiveFixture

for scenario in ('discover','unavailable'):
    with LiveFixture() as f:
        f.install_console()
        r=f.console('service','off','svc')
        assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        shutil.rmtree(f.live)
        device_map=f.prefix/'tmp/vward-device-map.tsv';device_map.unlink()
        f.install_rci()
        if scenario=='unavailable':(f.p/'rci-unavailable').touch()
        before=f.native.read_bytes();saved=f.startup.read_bytes()
        r=f.console('service','on','svc','Wireguard1',preserve_profile=True)
        if scenario=='discover':
            assert r.returncode==0 and 'result=changed' in r.stdout,('cold discovery did not reach actual owner action',r.returncode,r.stdout,r.stderr)
            assert '\tvpn\tVPN:Wireguard1\tdefault\t' in (f.live/'decision/choices.tsv').read_text()
            assert ' Wireguard1 auto' in f.native.read_text() and f.startup.read_bytes()==f.native.read_bytes()
            assert not device_map.exists(),'cold SDK published a shared discovery cache'
            archived=list((f.live/'journal/.migrations').glob('*/legacy/map'))
            assert len(archived)==1 and 'I\tWireguard1\tWireguard\tnwg1\tprivate' in archived[0].read_text()
        else:
            assert r.returncode!=0 and not f.live.exists() and not device_map.exists()
            assert f.native.read_bytes()==before and f.startup.read_bytes()==saved
        calls=(f.p/'rci.calls').read_text().splitlines()
        assert calls and all(c=='/rci/show/interface?' or c.startswith('/rci/show/interface/system-name?name=') for c in calls),calls
print('LIVE_COLD_MAP=PASS actual profile discovery/RCI show-only calls; absent map can bootstrap, unavailable discovery refuses before ROOT')
