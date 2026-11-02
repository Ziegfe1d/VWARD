#!/usr/bin/env python3
"""Panel install: trusted HTTPS feed, absent-only, SHA/deps, disabled, rollback."""
import gzip
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Reuse the existing real archive builder/opkg emulator without executing its cases.
source = ROOT / 'tests/entware/check-entware-lifecycle.py'
ns = {'__file__': str(source)}
exec(source.read_text().split('with tempfile.TemporaryDirectory() as td:')[0], ns)
LIB = ROOT / 'components/runtime/lib/vward-entware-pkg.sh'
with tempfile.TemporaryDirectory() as td:
    t = Path(td); r = t / 'root'
    for d in ('opt/bin', 'opt/sbin', 'opt/etc/init.d', 'opt/lib/opkg/info', 'opt/etc/vward', 'tmp', 'fake'):
        (r / d).mkdir(parents=True)
    (r / 'opt/etc/opkg.conf').write_text('src/gz entware http://bin.entware.net/mipselsf-k3.4\narch mipselsf-k3.4 200\n')
    (r / 'opt/lib/opkg/status').write_text('Package: libc\nVersion: 1\nArchitecture: mipselsf-k3.4\nStatus: install user installed\n\n')
    opkg = r / 'opt/bin/opkg'; opkg.write_text(ns['FAKE_OPKG']); opkg.chmod(0o755)
    ipk = ns['ipk'](t / 'dns.ipk', 'dnsmasq-full', '1', files=[('/opt/etc/init.d/S56dnsmasq', ns['INIT'], 0o755), ('/opt/etc/dnsmasq.conf', '# default\n', 0o600)])
    index = ns['index_entry'](ipk, 'dnsmasq-full', '1').rstrip() + '\nFilename: dns.ipk\n\n'
    (t / 'Packages.gz').write_bytes(gzip.compress(index.encode()))
    curl = t / 'curl'
    curl.write_text('''#!/usr/bin/env python3
import os,sys,shutil
from pathlib import Path
a=sys.argv[1:]; t=Path(os.environ['T']); u=a[-1]
with (t/'downloads').open('a') as f:f.write(u+'\\n')
if not u.startswith('https://bin.entware.net/'): sys.exit(7)
shutil.copyfile(t/('Packages.gz' if u.endswith('Packages.gz') else 'dns.ipk'),a[a.index('-o')+1])
'''); curl.chmod(0o755)
    env = dict(os.environ, VWARD_ROOT_PREFIX=str(r), VWARD_CURL_BIN=str(curl), VWARD_JOURNAL_SYNC='0', T=td)
    def run(pkg='dnsmasq-full'):
        return subprocess.run(['sh', '-c', f'. "{LIB}"\nvward_entware_install_manual "$1"', 'x', pkg], env=env, capture_output=True, text=True, timeout=20)
    bad = run('xray')
    assert bad.returncode == 75 and not (t / 'downloads').exists(), 'allow-list bypass'
    # Existing foreign configuration must survive even an absent package install.
    conf = r / 'opt/etc/dnsmasq.conf'; conf.write_text('# owner\n')
    out = run()
    assert out.returncode == 75 and 'path-conflict' in out.stdout, f'PANEL_PKG=FAIL: {out.stdout} {out.stderr}'
    assert conf.read_text() == '# owner\n' and not (r / 'fake/calls').exists()
    conf.unlink()
    # An unreviewed maintainer script cannot run merely because the owner clicked Install.
    original_ipk = ipk.read_bytes(); original_index = (t / 'Packages.gz').read_bytes()
    scripted = ns['ipk'](t / 'scripted.ipk', 'dnsmasq-full', '1', files=[('/opt/etc/dnsmasq.conf', '# default\n', 0o600)],
                         postinst='#!/bin/sh\necho unexpected > "$IPKG_INSTROOT/fake/script-ran"\n')
    ipk.write_bytes(scripted.read_bytes())
    scripted_index = ns['index_entry'](ipk, 'dnsmasq-full', '1').rstrip() + '\nFilename: dns.ipk\n\n'
    (t / 'Packages.gz').write_bytes(gzip.compress(scripted_index.encode()))
    out = run()
    assert out.returncode == 75 and not (r / 'fake/script-ran').exists(), f'unreviewed script executed: {out.stdout}'
    ipk.write_bytes(original_ipk); (t / 'Packages.gz').write_bytes(original_index)
    out = run()
    assert out.returncode == 0 and '\tdone\t1\toff' in out.stdout, (out.stdout, out.stderr)
    assert 'ENABLED=no' in (r / 'opt/etc/init.d/S56dnsmasq').read_text()
    calls = (r / 'fake/calls').read_text()
    out = run()
    assert out.returncode == 0 and '\tunchanged\t' in out.stdout
    assert (r / 'fake/calls').read_text() == calls, 'existing package was reinstalled/upgraded'
    assert all(u.startswith('https://bin.entware.net/') for u in (t / 'downloads').read_text().splitlines())
    helper_env = env | {'VWARD_ADMISSION_LIB': str(ROOT / 'components/runtime/lib/vward-runtime-admission.sh'),
                        'VWARD_ENTWARE_LIB': str(LIB), 'VWARD_CONSOLE_ETC': str(r / 'opt/etc/vward'),
                        'VWARD_CONSOLE_AUDIT_LOG': str(t / 'audit'), 'VWARD_CONSOLE_BACKUP_DIR': str(t / 'backup')}
    out = subprocess.run(['sh', str(ROOT / 'components/console/scripts/vward-console-config.sh'),
                          'package-install', 'dnsmasq-full', 'install'], env=helper_env, capture_output=True, text=True)
    assert out.returncode == 0 and 'result=unchanged' in out.stdout, f'PANEL_PKG route=FAIL: {out.stdout} {out.stderr}'
    assert (r / 'fake/calls').read_text() == calls
print('PANEL_PKG=PASS')
