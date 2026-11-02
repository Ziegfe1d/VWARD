#!/usr/bin/env python3
"""Xray install commits binary+version together; no live tunnel is started."""
import re
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / 'components/tunnel-guard/scripts/vward-vless-engine.sh').read_text()
install = re.search(r'^op_install\(\) \{\n.*?^\}\n', SRC, re.M | re.S).group(0)
cleanup = re.search(r'^cleanup\(\) \{\n.*?^\}\n', SRC, re.M | re.S).group(0)
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    base = f'''ENGINE_SHARE='{t}'; BIN="$ENGINE_SHARE/xray"; XRAY_VERSION=1; XRAY_URL=https://example.invalid
die() {{ echo "error=$1"; exit 1; }}
engine_arch() {{ echo mipsle; }}
xray_zip() {{ echo 'test.zip abc xray'; }}
get() {{ :; }}
sha256_of() {{ echo abc; }}
unzip_one() {{ printf '#!/bin/sh\\nexit 0\\n' > "$3"; }}
log() {{ :; }}
TMPD=''
{cleanup}
trap cleanup EXIT
{install}
op_install
'''
    # A bad version target must refuse BEFORE exposing the new executable.
    (t / 'version').mkdir()
    r = subprocess.run(['sh', '-c', base], capture_output=True, text=True)
    assert r.returncode != 0 and not (t / 'xray').exists(), f'XRAY_INSTALL=FAIL: binary exposed after metadata failure: {r.stdout}'
    (t / 'version').rmdir()
    changed_target = base.replace('unzip_one() {', 'unzip_one() { mkdir "$ENGINE_SHARE/version";')
    r = subprocess.run(['sh', '-c', changed_target], capture_output=True, text=True)
    assert r.returncode != 0 and not (t / 'xray').exists(), 'XRAY_INSTALL=FAIL: mv accepted a version directory created during download'
    import shutil
    shutil.rmtree(t / 'version')
    r = subprocess.run(['sh', '-c', base], capture_output=True, text=True)
    assert r.returncode == 0 and 'result=changed' in r.stdout
    assert (t / 'version').read_text() == '1\n' and (t / 'xray').exists()
    (t / 'version').unlink(); (t / 'xray').unlink()
    concurrent = base.replace('get() { :; }', '''get() {
touch "$ENGINE_SHARE/download.$$"
while [ ! -e "$ENGINE_SHARE/release" ]; do sleep 0.01; done
}''')
    procs = []
    try:
        procs.append(subprocess.Popen(['sh', '-c', concurrent], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True))
        deadline = time.monotonic() + 3
        while not list(t.glob('download.*')) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert list(t.glob('download.*')), 'first download did not start'
        procs.append(subprocess.Popen(['sh', '-c', concurrent], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True))
        deadline = time.monotonic() + 3
        while procs[1].poll() is None and len(list(t.glob('download.*'))) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(list(t.glob('download.*'))) == 1, 'XRAY_INSTALL=FAIL: parallel install entered a second download before pending'
        out, err = procs[1].communicate(timeout=2)
        assert 'error=install_busy' in out.decode(), (out, err)
        (t / 'release').touch()
        out, err = procs[0].communicate(timeout=5)
        assert procs[0].returncode == 0 and b'result=changed' in out, (out, err)
        assert not (t / 'install.pending').exists()
    finally:
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
print('XRAY_INSTALL=PASS')
