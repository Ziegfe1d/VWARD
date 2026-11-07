#!/usr/bin/env python3
"""First ordinary request must not strand an unusable control root."""
import shutil
from live_fixture import LiveFixture

fail=[]
for scenario in ('valid','bad-catalog','missing-map','writable-profile'):
    with LiveFixture() as f:
        f.install_console()
        # Initialize the same valid existing device profile without a route.
        r=f.console('service','off','svc');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        shutil.rmtree(f.live)
        if scenario=='bad-catalog':
            (f.prefix/'opt/var/lib/vward/services/catalog.json').write_text('{invalid-json\n')
        elif scenario=='missing-map':
            (f.prefix/'tmp/vward-device-map.tsv').unlink()
        elif scenario=='writable-profile':
            (f.etc/'device.conf').chmod(0o666)
        before=f.native.read_bytes();saved=f.startup.read_bytes()
        r=f.console('service','on','svc','Wireguard1',preserve_profile=True)
        if scenario=='valid':
            assert r.returncode==0 and 'result=changed' in r.stdout,(scenario,r.returncode,r.stdout,r.stderr)
            assert (f.live/'decision/version.tsv').read_text()=='routing-state\t2\n'
            assert '\tvpn\tVPN:Wireguard1\tdefault\t' in (f.live/'decision/choices.tsv').read_text()
            assert ' Wireguard1 auto' in f.native.read_text() and f.startup.read_bytes()==f.native.read_bytes()
            assert (f.live/'.bootstrap/completion').read_text()=='acknowledged-root-transfer\n'
        elif not (r.returncode!=0 and not f.live.exists() and f.native.read_bytes()==before and f.startup.read_bytes()==saved):
            fail.append((scenario,'unready request stranded root',r.returncode,
                         (f.live/'decision/version.tsv').read_text() if f.live.exists() else 'absent',r.stdout,r.stderr))
assert not fail,fail
print('LIVE_FIRST_REQUEST=PASS actual cold console boot/import/write; invalid inputs refuse before root publication')
