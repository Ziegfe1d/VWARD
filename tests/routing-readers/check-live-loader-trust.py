#!/usr/bin/env python3
"""The full live closure is checked before any candidate source is evaluated."""
import shutil
from fixture import Fixture,LIBDIR,ROOT
from live_fixture import LiveFixture

with Fixture() as f:
    prefix=f.p/'installed';lib=prefix/'opt/lib/vward';lib.mkdir(parents=True)
    for p in LIBDIR.glob('*.sh'):
        shutil.copy2(p,lib/p.name);(lib/p.name).chmod(0o644)
    cap=lib/'routing-capabilities.tsv';shutil.copy2(ROOT/'config/runtime/routing-capabilities.tsv',cap);cap.chmod(0o644)
    marker=f.p/'untrusted-sourced'
    command=lib/'vward-routing-command.sh';original=command.read_text()
    command.write_text(original+'\nprintf sourced > "$SOURCE_MARKER"\n')
    env=f.env|{'VWARD_ROOT_PREFIX':str(prefix),'SOURCE_MARKER':str(marker)}
    def load():return f.run('. "$1";vward_routing_live_modules_load "$2"',LIBDIR/'vward-routing-loader.sh',lib,env=env,timeout=5)
    command.chmod(0o666)
    r=load();assert r.returncode==75 and not marker.exists(),('writable code was sourced',r.returncode,r.stdout,r.stderr)
    command.chmod(0o644);lib.parent.chmod(0o777)
    r=load();assert r.returncode==75 and not marker.exists(),('replaceable ancestor was sourced',r.returncode,r.stdout,r.stderr)
    lib.parent.chmod(0o755);command.write_text(original)
    cap.write_bytes(b'routing-runtime\t2\n\n')
    r=load();assert r.returncode==75,'noncanonical capsule bytes were accepted'
    cap.write_bytes(b'routing-runtime\t2\n')
    r=load();assert r.returncode==0,(r.returncode,r.stdout,r.stderr)

with LiveFixture() as f:
    f.install_console()
    loader=f.prefix/'opt/lib/vward/vward-routing-loader.sh'
    marker=f.p/'loader-evaluated'
    loader.write_text(loader.read_text()+'\nprintf sourced > "$SOURCE_MARKER"\nreturn 75\n')
    loader.chmod(0o666);f.env['SOURCE_MARKER']=str(marker)
    before=f.native.read_bytes()
    r=f.console('service','on','svc','Wireguard0')
    assert r.returncode==75 and not marker.exists() and not f.calls.exists() and f.native.read_bytes()==before,('first console source bypassed trust gate',r.returncode,r.stdout,r.stderr)
print('LIVE_LOADER_TRUST=PASS nonwritable fixed closure/ancestors and exact capsule required before sourcing')
