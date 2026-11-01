#!/usr/bin/env python3
"""External Entware package lifecycle (dnsmasq-full, sing-box-go) on an EMULATED root.

Nothing touches a real router: opkg is an emulator inside a temporary root. Checks
integrity, architecture, dependencies, scripts, payload paths, room, install-disabled,
reboot keeps it off, upgrade keeps the user's conffile edits, failure -> restore of the
previous verified version, unknown -> gate, SIGKILL -> evidence-only recovery, and that no
other package is touched.
"""
import hashlib
import io
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'components/runtime/lib/vward-entware-pkg.sh'
SHELL = [os.environ['ENTWARE_BUSYBOX'], 'ash'] if os.environ.get('ENTWARE_BUSYBOX') else ['sh']
ARCH = 'mipselsf-k3.4'

FAKE_OPKG = r'''#!/usr/bin/env python3
import io, os, sys, tarfile, time, subprocess
from pathlib import Path
R = Path(os.environ["VWARD_ROOT_PREFIX"]); db = R / "opt/lib/opkg"; fake = R / "fake"
with open(fake / "calls", "a") as f: f.write(" ".join(sys.argv[1:]) + "\n")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
def stanzas():
    t = (db / "status").read_text() if (db / "status").exists() else ""
    return [s for s in t.split("\n\n") if s.strip()]
def save(st): (db / "status").write_text("\n\n".join(st) + "\n\n")
if args[0] == "remove":
    p = args[1]; st = [s for s in stanzas() if not s.startswith("Package: " + p + "\n")]
    for l in (db / "info" / (p + ".list")).read_text().split() if (db / "info" / (p + ".list")).exists() else []:
        (R / l.lstrip("/")).unlink(missing_ok=True)
    (db / "info" / (p + ".list")).unlink(missing_ok=True); save(st); sys.exit(0)
if args[0] != "install": sys.exit(2)
if (fake / "sleep-before").exists(): time.sleep(30)
ipk = tarfile.open(args[1], "r:gz")
ctl = tarfile.open(fileobj=io.BytesIO(ipk.extractfile("./control.tar.gz").read()), mode="r:gz")
control = ctl.extractfile("./control").read().decode()
fields = dict(l.split(": ", 1) for l in control.splitlines() if ": " in l)
pkg, ver = fields["Package"], fields["Version"]
if (fake / ("fail-" + ver)).exists(): sys.exit(255)
data = tarfile.open(fileobj=io.BytesIO(ipk.extractfile("./data.tar.gz").read()), mode="r:gz")
files = []
for m in data.getmembers():
    if m.isfile():
        dst = R / m.name.lstrip("./"); dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data.extractfile(m).read()); dst.chmod(m.mode); files.append("/" + m.name.lstrip("./"))
db.joinpath("info").mkdir(parents=True, exist_ok=True)
(db / "info" / (pkg + ".list")).write_text("\n".join(files) + "\n")
conf = fields.get("Conffiles-Emu", "")
st = [s for s in stanzas() if not s.startswith("Package: " + pkg + "\n")]
stanza = "Package: %s\nVersion: %s\nArchitecture: %s\nStatus: install user installed" % (pkg, ver, fields["Architecture"])
if conf: stanza += "\nConffiles:\n " + conf + " 0"
st.append(stanza); save(st)
if (fake / ("partial-" + ver)).exists(): sys.exit(1)
if (fake / "sleep-after").exists(): time.sleep(30)
names = [m.name for m in ctl.getmembers()]
if "./postinst" in names:
    p = R / "fake" / "postinst"; p.write_bytes(ctl.extractfile("./postinst").read())
    subprocess.run(["sh", str(p)], env=dict(os.environ, IPKG_INSTROOT=str(R)))
sys.exit(0)
'''

def ipk(path, pkg, ver, arch=ARCH, files=None, postinst=None, depends='libc', installed_size=100, conffile=None, name_ctl=None):
    def tgz(entries):
        b = io.BytesIO()
        with tarfile.open(fileobj=b, mode='w:gz') as t:
            for name, data, mode in entries:
                ti = tarfile.TarInfo(name); ti.size = len(data); ti.mode = mode; t.addfile(ti, io.BytesIO(data))
        return b.getvalue()
    control = f'Package: {name_ctl or pkg}\nVersion: {ver}\nArchitecture: {arch}\nDepends: {depends}\nInstalled-Size: {installed_size}\n'
    if conffile: control += f'Conffiles-Emu: {conffile}\n'
    ctl = [('./control', control.encode(), 0o644)]
    if postinst: ctl.append(('./postinst', postinst.encode(), 0o755))
    data = tgz([('./' + n.lstrip('/'), c.encode(), m) for n, c, m in (files or [])])
    outer = tgz([('./debian-binary', b'2.0\n', 0o644), ('./control.tar.gz', tgz(ctl), 0o644), ('./data.tar.gz', data, 0o644)])
    Path(path).write_bytes(outer)
    return Path(path)

def index_entry(p, pkg, ver, arch=ARCH, depends='libc', sha=None, size=None):
    b = Path(p).read_bytes()
    return (f'Package: {pkg}\nVersion: {ver}\nDepends: {depends}\nArchitecture: {arch}\n'
            f'Size: {size if size is not None else len(b)}\nSHA256sum: {sha or hashlib.sha256(b).hexdigest()}\n\n')

INIT = '''#!/bin/sh
ENABLED=yes
R=${VWARD_ROOT_PREFIX:-}
case "$1" in
  start) [ "$ENABLED" = yes ] || exit 0; "$R/opt/sbin/dnsmasq" 300 >/dev/null 2>&1 & echo $! > "$R/fake/dnsmasq.pid" ;;
  stop) [ -f "$R/fake/dnsmasq.pid" ] && kill "$(cat "$R/fake/dnsmasq.pid")" 2>/dev/null; rm -f "$R/fake/dnsmasq.pid" ;;
esac
'''

def fail(m): raise SystemExit('ENTWARE_LIFECYCLE=FAIL: ' + m)

with tempfile.TemporaryDirectory() as td:
    td = Path(td); R = td/'root'
    for d in ('opt/bin', 'opt/sbin', 'opt/etc/init.d', 'opt/lib/opkg/info', 'opt/etc/vward', 'fake'):
        (R/d).mkdir(parents=True)
    (R/'opt/etc/opkg.conf').write_text(f'src/gz entware https://bin.entware.net/{ARCH}\narch all 100\narch {ARCH} 200\n')
    (R/'opt/lib/opkg/status').write_text('Package: libc\nVersion: 1.2\nArchitecture: mipselsf-k3.4\nStatus: install user installed\n\n'
                                        'Package: xray\nVersion: 25.1\nArchitecture: mipselsf-k3.4\nStatus: install user installed\n\n')
    (R/'opt/sbin/AdGuardHome').write_text('agh'); (R/'opt/bin/xray').write_text('xray')
    opkg = R/'opt/bin/opkg'; opkg.write_text(FAKE_OPKG); opkg.chmod(0o755)
    env = dict(os.environ, VWARD_ROOT_PREFIX=str(R), TMPDIR=str(td), VWARD_JOURNAL_SYNC='0')
    sleep_bin = shutil.which('sleep')
    def L(script, *a, env_=None, timeout=60):
        return subprocess.run([*SHELL, '-c', f'. "{LIB}"\n' + script, 'x', *map(str, a)], env=env_ or env, text=True, capture_output=True, timeout=timeout)
    def files_dnsmasq(ver, conf='# default\n'):
        # The daemon is a copy of `sleep`, so a started copy is a real, visible process.
        return [('/opt/etc/init.d/S56dnsmasq', INIT, 0o755), ('/opt/etc/dnsmasq.conf', conf + f'# v{ver}\n', 0o644)]
    seq = [0]
    def build(ver, **kw):
        kw.setdefault('files', files_dnsmasq(ver)); kw.setdefault('conffile', '/opt/etc/dnsmasq.conf')
        seq[0] += 1
        p = ipk(td/f'dnsmasq-full_{ver}.{seq[0]}.ipk', 'dnsmasq-full', ver, **kw)
        return p
    def install_daemon_binary():
        shutil.copy(sleep_bin, R/'opt/sbin/dnsmasq'); (R/'opt/sbin/dnsmasq').chmod(0o755)
    install_daemon_binary()
    def status(): return L('vward_entware_status dnsmasq-full').stdout.strip().split('\t')
    def running(): return (R/'fake/dnsmasq.pid').exists() and subprocess.run(['kill', '-0', (R/'fake/dnsmasq.pid').read_text().strip()]).returncode == 0
    others = {p: p.read_bytes() for p in (R/'opt/sbin/AdGuardHome', R/'opt/bin/xray')}
    xray_stanza = 'Package: xray\nVersion: 25.1'

    # ---- status / allow-list --------------------------------------------------------------------
    if status()[:2] != ['dnsmasq-full', 'absent'] or status()[4] != 'off': fail('absent package status')
    for bad in ('xray', 'AdGuardHome', 'dnsmasq', '../x'):
        if L('vward_entware_status "$1"', bad).returncode != 75: fail('not allow-listed accepted: ' + bad)

    # ---- index checks: arch, deps, integrity fields -----------------------------------------------
    v1 = build('2.90-1'); idx = td/'Packages'
    idx.write_text(index_entry(v1, 'dnsmasq-full', '2.90-1'))
    r = L('vward_entware_check dnsmasq-full "$1"', idx)
    if r.returncode or r.stdout.split('\t')[1] != 'candidate': fail('valid candidate refused: ' + r.stdout)
    for text, why in ((index_entry(v1, 'dnsmasq-full', '2.90-1', arch='mipssf-k3.4'), 'arch-mipssf-k3.4'),
                      (index_entry(v1, 'dnsmasq-full', '2.90-1', depends='libc, libnettle'), 'missing-dependency-libnettle'),
                      (index_entry(v1, 'dnsmasq-full', '2.90-1', sha='zz'), 'no-sha256'),
                      ('Package: other\nVersion: 1\n\n', 'not-in-index')):
        idx.write_text(text); r = L('vward_entware_check dnsmasq-full "$1"', idx)
        if r.returncode != 75 or why not in r.stdout: fail(f'check must refuse {why}: {r.stdout}')
    idx.write_text(index_entry(v1, 'dnsmasq-full', '2.90-1'))

    # ---- inspect: integrity, control, scripts, payload --------------------------------------------
    if L('vward_entware_inspect dnsmasq-full "$1" "$2"', v1, idx).returncode: fail('valid package refused')
    cases = []
    tampered = td/'tampered.ipk'; tampered.write_bytes(v1.read_bytes()[:-3] + b'xyz'); cases.append((tampered, 'sha256-mismatch', None))
    short = td/'short.ipk'; short.write_bytes(v1.read_bytes()[:-10]); cases.append((short, 'size-mismatch', None))
    corrupt = td/'corrupt.ipk'; corrupt.write_bytes(b'not a package' * 10); cases.append((corrupt, 'corrupt-package', 'self'))
    cases.append((build('2.90-1', name_ctl='evil'), 'control-mismatch', 'self'))
    cases.append((build('2.90-1', postinst='#!/bin/sh\n/opt/etc/init.d/S56dnsmasq start\n'), 'script-starts-service-postinst', 'self'))
    cases.append((build('2.90-1', postinst='#!/bin/sh\nstart-stop-daemon -S -x /opt/sbin/dnsmasq\n'), 'script-starts-service-postinst', 'self'))
    cases.append((build('2.90-1', files=files_dnsmasq('2.90-1') + [('/opt/bin/vward-route-engine.sh', 'x', 0o755)]), 'unsafe-payload-path', 'self'))
    cases.append((build('2.90-1', files=[('/etc/passwd', 'x', 0o644)]), 'unsafe-payload-path', 'self'))
    for p, why, own in cases:
        if own: idx.write_text(index_entry(p, 'dnsmasq-full', '2.90-1'))
        r = L('vward_entware_inspect dnsmasq-full "$1" "$2"', p, idx)
        if r.returncode != 75 or why not in r.stdout: fail(f'inspect must refuse {why}: {r.returncode} {r.stdout}')
    v1 = build('2.90-1'); idx.write_text(index_entry(v1, 'dnsmasq-full', '2.90-1'))

    # ---- apply is off unless the owner switch says so; auto needs its own permission ---------------
    if L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v1, idx).returncode != 75: fail('apply without the switch')
    on = dict(env, VWARD_ENTWARE_APPLY='1')
    if L('vward_entware_apply dnsmasq-full "$1" "$2" auto', v1, idx, env_=on).returncode != 75: fail('auto apply without permission')
    if L('vward_entware_apply xray "$1" "$2" manual', v1, idx, env_=on).returncode != 75: fail('xray must never be managed here')
    if (R/'fake/calls').exists(): fail('opkg called while refused')

    # ---- fresh install: installed, DISABLED, not running, nothing else touched ----------------------
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v1, idx, env_=on)
    if r.returncode or 'done\t2.90-1\toff' not in r.stdout: fail('install: ' + r.stdout + r.stderr)
    if status() != ['dnsmasq-full', 'installed', '2.90-1', ARCH, 'off']: fail('installed state ' + str(status()))
    if 'ENABLED=no' not in (R/'opt/etc/init.d/S56dnsmasq').read_text() or running(): fail('service enabled or running after install')
    calls = (R/'fake/calls').read_text().splitlines()
    if calls != [f'install --nodeps {v1}'] or any('upgrade' in c for c in calls): fail('opkg calls: ' + str(calls))
    if xray_stanza not in (R/'opt/lib/opkg/status').read_text() or any(p.read_bytes() != b for p, b in others.items()): fail('another package touched')
    if not (R/'opt/var/cache/vward/entware/dnsmasq-full_2.90-1.ipk').exists(): fail('verified image not kept for rollback')
    if oct((R/'opt/var/lib/vward/entware').stat().st_mode & 0o777) != '0o700': fail('state not private')

    # ---- "reboot": every init script runs `start`; a disabled component stays off ----------------------
    for s in sorted((R/'opt/etc/init.d').glob('S*')):
        subprocess.run(['sh', str(s), 'start'], env=env, timeout=10)
    if running(): fail('disabled component started at boot')

    # ---- upgrade keeps the user's conffile edits ----------------------------------------------------
    (R/'opt/etc/dnsmasq.conf').write_text('# owner edit: server=/example/1.1.1.1\n')
    v2 = build('2.91-1'); idx.write_text(index_entry(v2, 'dnsmasq-full', '2.91-1'))
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v2, idx, env_=on)
    if r.returncode or status()[2] != '2.91-1' or status()[4] != 'off': fail('upgrade: ' + r.stdout + r.stderr)
    if (R/'opt/etc/dnsmasq.conf').read_text() != '# owner edit: server=/example/1.1.1.1\n': fail('user conffile edit lost on upgrade')
    if L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v2, idx, env_=on).stdout.split('\t')[1] != 'unchanged': fail('same version re-applied')

    # ---- a postinst that starts the daemon by means the scan cannot see: stopped and disabled anyway ----
    sneaky = '#!/bin/sh\nX=$IPKG_INSTROOT/opt/etc/init.d/S56dnsmasq; eval "sh $X st""art"\n'
    v2b = build('2.91-2', postinst=sneaky); idx.write_text(index_entry(v2b, 'dnsmasq-full', '2.91-2'))
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v2b, idx, env_=on)
    if r.returncode or running() or status()[4] != 'off': fail('a self-started daemon survived: ' + r.stdout + str(status()))

    # ---- failed upgrade -> previous verified version restored, still off ---------------------------
    v3 = build('2.92-1'); idx.write_text(index_entry(v3, 'dnsmasq-full', '2.92-1')); (R/'fake/fail-2.92-1').touch()
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v3, idx, env_=on)
    if r.returncode != 1 or 'failed-restored\t2.91-2' not in r.stdout: fail('failed upgrade: ' + r.stdout)
    if status()[2:] != ['2.91-2', ARCH, 'off'] or L('vward_entware_gate').returncode: fail('restore state ' + str(status()))
    # ---- partial install AND restore impossible -> UNKNOWN, gate closed, no further apply --------------
    (R/'fake/fail-2.92-1').unlink(); (R/'fake/partial-2.92-1').touch(); (R/'fake/fail-2.91-2').touch()
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v3, idx, env_=on)
    if r.returncode != 3 or L('vward_entware_gate').returncode != 75: fail('unverified rollback must be unknown: ' + r.stdout)
    n = len((R/'fake/calls').read_text().splitlines())
    if L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v3, idx, env_=on).returncode != 75: fail('apply despite unknown')
    if len((R/'fake/calls').read_text().splitlines()) != n: fail('opkg called while the gate is closed')
    (R/'opt/var/lib/vward/entware/dnsmasq-full.unknown').unlink(); (R/'fake/fail-2.91-2').unlink(); (R/'fake/partial-2.92-1').unlink()
    # The owner resolves the unknown state by hand (out of scope here): put the verified version back.
    subprocess.run([str(opkg), 'install', str(R/'opt/var/cache/vward/entware/dnsmasq-full_2.91-2.ipk')], env=env, check=True)
    L('vward_entware_status dnsmasq-full')
    (R/'opt/etc/init.d/S56dnsmasq').write_text((R/'opt/etc/init.d/S56dnsmasq').read_text().replace('ENABLED=yes', 'ENABLED=no'))
    subprocess.run(['sh', str(R/'opt/etc/init.d/S56dnsmasq'), 'stop'], env=env)     # that image's postinst starts it
    if status()[4] != 'off': fail('manual resolution left the daemon on')

    # ---- no rollback image, no room: refused before anything changes ------------------------------------
    cache = R/'opt/var/cache/vward/entware'
    cur = status()[2]; img = cache/f'dnsmasq-full_{cur}.ipk'; img.rename(td/'saved.ipk')
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', v3, idx, env_=on)
    if r.returncode != 75 or 'no-rollback-image' not in r.stdout: fail('upgrade without a way back: ' + r.stdout)
    (td/'saved.ipk').rename(img)
    huge = build('2.93-1', installed_size=10**12); idx.write_text(index_entry(huge, 'dnsmasq-full', '2.93-1'))
    r = L('vward_entware_apply dnsmasq-full "$1" "$2" manual', huge, idx, env_=on)
    if r.returncode != 75 or 'no-space' not in r.stdout or status()[2] != cur: fail('no-space: ' + r.stdout)

    # ---- SIGKILL / power loss in the middle -> recovery by evidence only ----------------------------------
    for flag, want in (('sleep-before', 'failed'), ('sleep-after', 'unknown')):
        v4 = build('2.94-1'); idx.write_text(index_entry(v4, 'dnsmasq-full', '2.94-1')); (R/'fake'/flag).touch()
        p = subprocess.Popen([*SHELL, '-c', f'. "{LIB}"\nvward_entware_apply dnsmasq-full "$1" "$2" manual', 'x', str(v4), str(idx)],
                             env=on, start_new_session=True)
        for _ in range(200):
            if (R/'opt/var/lib/vward/entware/dnsmasq-full.pending').exists(): break
            time.sleep(0.05)
        time.sleep(1.0); os.killpg(p.pid, signal.SIGKILL); p.wait(); (R/'fake'/flag).unlink()
        if L('vward_entware_gate').returncode != 75: fail('pending must close the gate')
        r = L('vward_entware_recover dnsmasq-full')
        # sleep-after: the new version landed but its init script is still ENABLED=yes -> not provably off -> unknown
        got = r.stdout.split('\t')[1] if r.stdout else ''
        if got != want: fail(f'recover after SIGKILL ({flag}): {r.stdout}')
        if want == 'unknown':
            if L('vward_entware_gate').returncode != 75: fail('unknown must keep the gate closed')
            (R/'opt/var/lib/vward/entware/dnsmasq-full.unknown').unlink()
        if (R/'fake/calls').read_text().count(str(v4)) != 1: fail('recovery retried the install')

    # ---- sing-box-go goes through the same path -----------------------------------------------------
    sb = ipk(td/'sing-box-go_1.11.0-1.ipk', 'sing-box-go', '1.11.0-1', files=[('/opt/bin/sing-box', 'bin', 0o755),
             ('/opt/etc/init.d/S99sing-box', '#!/bin/sh\nENABLED=yes\n', 0o755)])
    idx.write_text(index_entry(sb, 'sing-box-go', '1.11.0-1'))
    r = L('vward_entware_apply sing-box-go "$1" "$2" manual', sb, idx, env_=on)
    st = L('vward_entware_status sing-box-go').stdout.strip().split('\t')
    if r.returncode or st[1:] != ['installed', '1.11.0-1', ARCH, 'off'] or 'ENABLED=no' not in (R/'opt/etc/init.d/S99sing-box').read_text():
        fail('sing-box-go install: ' + r.stdout + str(st))
    if xray_stanza not in (R/'opt/lib/opkg/status').read_text() or any(p.read_bytes() != b for p, b in others.items()): fail('xray/AGH touched')
    if any('upgrade' in c for c in (R/'fake/calls').read_text().splitlines()): fail('opkg upgrade was called')
    if f'sentinel=1; . "{LIB}"; [ "$sentinel" = 1 ]' and subprocess.run([*SHELL, '-c', f'sentinel=1; . "{LIB}"; [ "$sentinel" = 1 ]']).returncode: fail('load not inert')
print('ENTWARE_LIFECYCLE=PASS: allow-list, index/arch/deps, integrity, scripts, payload, installed-off, reboot, conffiles, restore, unknown gate, SIGKILL, sing-box')
