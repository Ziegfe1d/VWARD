#!/usr/bin/env python3
"""An installed profile's real ndmc entry must fence managed/unknown writes before transport."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
from fixture import PipelineFixture, LIBDIR, ROOT, SHELL

with PipelineFixture() as f:
    r = f.invoke('vward_routing_pipeline2', f.j, 'pin', 'svc', 'isp', 'ISP', 'default', 0)
    assert r.returncode == 0, (r.stdout, r.stderr)
    with (f.e / 'running.cfg').open('a') as out:
        out.write('object-group fqdn Shared\n    include x.example\n    include outside.example\n!\n')
    prefix = f.p / 'installed'
    tmp = prefix / 'tmp'; tmp.mkdir(parents=True)
    libs = prefix / 'opt/lib/vward'; libs.mkdir(parents=True)
    for lib in LIBDIR.glob('*.sh'):
        shutil.copy2(lib, libs / lib.name)
    root = prefix / 'opt/var/lib/vward/routing'; root.mkdir(parents=True, mode=0o700)
    shutil.copytree(f.decision, root / 'decision')
    shutil.copytree(f.j, root / 'journal')
    bin_ = f.p / 'native-bin'; bin_.mkdir()
    ndmc = bin_ / 'ndmc'
    calls = f.p / 'native-calls'
    native = f.e / 'running.cfg'
    ndmc.write_text('#!/bin/sh\nif [ "$1" = -c ] && [ "$2" = "show running-config" ]; then\n'
                    'printf "read\\n" >> ' + shlex.quote(str(calls)) + '\ncat ' + shlex.quote(str(native)) + '\nexit 0\nfi\n'
                    'printf "write\\n" >> ' + shlex.quote(str(calls)) + '\nprintf "! native mutation\\n" >> '
                    + shlex.quote(str(native)) + '\nexit 0\n')
    ndmc.chmod(0o755)
    env = f.env | {'PATH': str(bin_) + ':' + os.environ['PATH'], 'VWARD_ROOT_PREFIX': str(prefix),
                   'VWARD_PROFILE_LIB': str(libs / 'vward-device-profile.sh'), 'VWARD_NDMC': str(ndmc),
                   'VWARD_CONSOLE_ETC': str(f.e), 'VWARD_ROUTE_STATE': str(f.e / 'route'),
                   'VWARD_DEVICE_CONFIG': str(f.e / 'device.conf'), 'VWARD_DEVICE_MAP_CACHE': str(f.e / 'device-map.tsv'),
                   'VWARD_SERVICES_FETCHED': str(f.e / 'catalog.json'), 'VWARD_SERVICES_BUNDLED': str(f.e / 'missing'),
                   'VWARD_ROUTING_AGH_DOMAINS': str(f.e / 'agh-domains'), 'VWARD_KEENETIC_TIMING': '0'}

    def run(command):
        return f.run('. "$VWARD_PROFILE_LIB"; ndmc -c "$1"', command, env=env)

    before = native.read_bytes()
    r = run('object-group fqdn Other include x.example')
    assert r.returncode == 75 and native.read_bytes() == before, (r.returncode, r.stdout, r.stderr)
    assert 'write' not in calls.read_text(), 'protected mutation reached actual ndmc boundary'
    r = run('dns-proxy route object-group Shared Wireguard1 auto')
    assert r.returncode == 75 and native.read_bytes() == before, (r.returncode, r.stderr)
    r = run('show running-config')
    assert r.returncode == 0 and 'include x.example' in r.stdout and native.read_bytes() == before
    # The actual console action must refuse its DOMAIN before its first group
    # creation. A native-command fence alone is too late for a compound action.
    dev = f.e / 'device.conf'
    dev.write_text('VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\n'
                   'VWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n'
                   'VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\n'
                   'VWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n'
                   'VWARD_POLICY_GROUP=Mine\n')
    dev.chmod(0o600)
    cli_env = env | {'VWARD_DEVICE_CONFIG_OWNER_UID': str(os.getuid()),
                     'VWARD_ADMISSION_LIB': str(libs / 'vward-runtime-admission.sh'),
                     'VWARD_CONSOLE_EDIT_LOCK': str(tmp / 'edit.lock'),
                     'VWARD_ROUTE_CHANGE_LOCK': str(tmp / 'change.lock'),
                     'VWARD_CONSOLE_AUDIT_LOG': str(f.p / 'console-audit.log')}
    calls.write_text('')
    r = subprocess.run(SHELL + [str(ROOT / 'components/console/scripts/vward-console-config.sh'),
                               'route-domain', 'add', 'x.example'], env=cli_env,
                       text=True, capture_output=True, timeout=30)
    assert r.returncode == 75 and 'error=routing_policy_handoff' in r.stdout, (r.returncode, r.stdout, r.stderr, 'native_changed', native.read_bytes() != before)
    assert native.read_bytes() == before and 'write' not in calls.read_text(), 'console wrote before semantic scope admission'
    # This is scoped admission, not a blanket refusal of every legacy command.
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 0 and native.read_bytes() != before, (r.returncode, r.stderr)
    native.write_bytes(before)
    # A truncated/error native answer cannot prove the group is unprotected.
    for broken in (b'', b'Command:: error\n'):
        native.write_bytes(broken)
        r = run('dns-proxy route object-group Shared Wireguard1 auto')
        assert r.returncode == 75 and native.read_bytes() == broken, (r.returncode, r.stderr)
    native.write_bytes(before)
    # Missing installed dependencies fail closed; no old-writer fallback.
    required = libs / 'vward-routing-project.sh'
    required.rename(required.with_suffix('.kept'))
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 75 and native.read_bytes() == before, (r.returncode, r.stderr)
    required.with_suffix('.kept').rename(required)
    # Pre-B recovery evidence is also a barrier; a clean new J2 is not enough.
    recovery = Path(env['VWARD_CONSOLE_BACKUP_DIR'] + '-recovery') / 'smartdns.reserved'
    recovery.mkdir(parents=True)
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 75 and native.read_bytes() == before, ('legacy recovery crossed', r.returncode, r.stderr)
    recovery.rmdir()
    txn = Path(env['VWARD_CONSOLE_BACKUP_DIR']) / 'service-transactions/txn.closed'
    txn.mkdir(parents=True)
    (txn / 'pending').write_text('')
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 75 and native.read_bytes() == before
    (txn / 'pending').unlink()
    (txn / 'retained').write_bytes(b'completed legacy evidence\n')
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 0 and (txn / 'retained').read_bytes() == b'completed legacy evidence\n', (r.returncode, r.stderr)
    native.write_bytes(before)
    # Corruption or incomplete bootstrap refuses before native IO; diagnostics still works.
    version = root / 'decision/version.tsv'; saved_version = version.read_bytes(); version.unlink()
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 75 and native.read_bytes() == before, (r.returncode, r.stderr)
    assert run('show running-config').returncode == 0
    version.write_bytes(saved_version); version.chmod(0o600)
    # No state means the existing legacy path, without implicitly activating/creating B state.
    absent = root.with_name('routing-kept'); root.rename(absent)
    r = run('object-group fqdn Other include outside.example')
    assert r.returncode == 0 and native.read_bytes() != before, (r.returncode, r.stderr)
    assert not root.exists(), 'ordinary old writer bootstrapped a new routing intention'
    native.write_bytes(before); absent.rename(root)
    assert not f.trace.exists(), 'installed boundary used the old poisoned DATA fixture transport'
print('LIVE_NATIVE_BOUNDARY=PASS installed profile blocks native protected writes, unknown and incomplete state; no-state legacy retained')
