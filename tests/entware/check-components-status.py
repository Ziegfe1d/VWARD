#!/usr/bin/env python3
"""Panel report: new components show "Не установлен" / "Установлен, выключен" from the real
package state; never "Работает"; DNS mode and the owner's update permissions (off by default)."""
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
LIBS = [ROOT/'components/runtime/lib/vward-entware-pkg.sh', ROOT/'components/runtime/lib/vward-dns-mode.sh',
        ROOT/'components/runtime/lib/vward-components-status.sh']
SHELL = [os.environ['ENTWARE_BUSYBOX'], 'ash'] if os.environ.get('ENTWARE_BUSYBOX') else ['sh']
def fail(m): raise SystemExit('COMPONENTS_STATUS=FAIL: ' + m)
with tempfile.TemporaryDirectory() as td:
    R = Path(td)/'root'
    for d in ('opt/lib/opkg/info', 'opt/etc/init.d', 'opt/etc/vward', 'opt/share/vward/vless-engine', 'opt/sbin', 'opt/bin'): (R/d).mkdir(parents=True)
    env = dict(os.environ, VWARD_ROOT_PREFIX=str(R))
    src = ''.join(f'. "{l}"\n' for l in LIBS)
    def rep():
        r = subprocess.run([*SHELL, '-c', src + 'vward_components_status'], env=env, text=True, capture_output=True, timeout=30)
        if r.returncode: fail(r.stderr)
        return {l.split('\t')[0]: l.split('\t')[1:] for l in r.stdout.splitlines()}
    st = rep()
    if st['dnsmasq-full'] != ['entware', 'not-installed', '-', 'Не установлен'] or st['sing-box-go'][1] != 'not-installed': fail(str(st))
    if st['dns-mode'][1:] != ['agh', '-', 'AdGuard Home'] or any(st[f'entware-auto-{a}'][1] != 'off' for a in ('check', 'download', 'apply')): fail('defaults ' + str(st))
    (R/'opt/lib/opkg/status').write_text('Package: dnsmasq-full\nVersion: 2.90-1\nArchitecture: mipselsf-k3.4\nStatus: install user installed\n\n')
    (R/'opt/lib/opkg/info/dnsmasq-full.list').write_text('/opt/etc/init.d/S56dnsmasq\n/opt/sbin/dnsmasq\n')
    (R/'opt/etc/init.d/S56dnsmasq').write_text('#!/bin/sh\nENABLED=no\n')
    if rep()['dnsmasq-full'] != ['entware', 'installed-off', '2.90-1', 'Установлен, выключен']: fail('installed-off: ' + str(rep()['dnsmasq-full']))
    (R/'opt/etc/init.d/S56dnsmasq').write_text('#!/bin/sh\nENABLED=yes\n')
    if rep()['dnsmasq-full'][1:] != ['enabled-not-running', '2.90-1', 'Включён, не запущен']: fail('enabled')
    import shutil; shutil.copy(shutil.which('sleep'), R/'opt/sbin/dnsmasq')
    p = subprocess.Popen([str(R/'opt/sbin/dnsmasq'), '30'])
    try:
        got = rep()['dnsmasq-full']
        if got[1:] != ['running-unverified', '2.90-1', 'Запущен, не проверен']: fail('running: ' + str(got))
    finally:
        p.kill(); p.wait()
    out = subprocess.run([*SHELL, '-c', src + 'vward_components_status'], env=env, text=True, capture_output=True).stdout
    if 'Работает' in out: fail('"Работает" must never come from this report')
    (R/'opt/etc/vward/dns-mode.conf').write_text('mode=bogus\n'); (R/'opt/etc/vward/entware.conf').write_text('auto_check=1\n')
    st = rep()
    if st['dns-mode'][1] != 'unknown' or st['entware-auto-check'][1] != 'on' or st['entware-auto-apply'][1] != 'off': fail('mode/permissions ' + str(st))
print('COMPONENTS_STATUS=PASS: not installed / installed-off / enabled / running-unverified, never "Работает", DNS mode, permissions off by default')
