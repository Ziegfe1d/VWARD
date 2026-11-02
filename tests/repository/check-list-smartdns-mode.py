#!/usr/bin/env python3
"""Managed-list DNS transaction: explicit healthy server, foreign rows, rollback."""
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fixture = ROOT / 'tests/repository/check-console-domain-lists.py'
ns = {'__file__': str(fixture)}
exec(fixture.read_text().split('with tempfile.TemporaryDirectory() as tmp:')[0], ns)
HELPER = ROOT / 'components/console/scripts/vward-console-config.sh'
with tempfile.TemporaryDirectory() as td:
    t = Path(td); etc = t / 'etc'; (etc / 'route-engine').mkdir(parents=True)
    (t / 'root/tmp').mkdir(parents=True)
    cfg = t / 'running.cfg'
    baseline = '''interface Wireguard0
!
dns-proxy
    route object-group domain-list3 Wireguard0 auto
    https upstream https://dns.example.invalid/other dnsm on ISP domain guard.example
    https upstream https://dns.example.invalid/other dnsm on ISP domain guard2.example
!
object-group fqdn domain-list3
    include example.com
    include example.net
!
object-group fqdn domain-list0
    include owner.example
!
ip route 192.0.2.0 255.255.255.0 Wireguard0 auto
ip name-server 192.0.2.53 owner.example on Wireguard0
'''
    baseline += ''.join(f'ip route 203.0.113.{16*n} 255.255.255.240 Wireguard0 auto\n' for n in range(8))
    baseline += ''.join(f'ip name-server 192.0.2.54 manual{n}.example on Wireguard0\n' for n in range(16))
    cfg.write_text(baseline)
    fake = ns['FAKE_NDMC'].replace('@CFG@', str(cfg))
    fake = fake.replace('    doh = [l for l in block', '''    if not neg and words[-1] == "example.net" and mode("reject-dns"):
        print("Dns::Proxy: error[5]: rejected"); sys.exit(0)
    doh = [l for l in block''')
    fake = fake.replace('print("ok")', '''if words[:2] == ["route", "object-group"] and not neg and mode("owner-group-race"):
    cfg.write_text(cfg.read_text().replace("    include owner.example", "    include example.com"))
    Path(str(cfg)+".mode-owner-group-race").unlink()
if words[:2] == ["https", "upstream"] and not neg and mode("lost-reply"):
    sys.exit(1)
if words[:2] == ["https", "upstream"] and not neg and mode("owner-edit"):
    cfg.write_text(cfg.read_text().replace("    include example.net", "    include owner-change.example"))
    sys.exit(1)
if words[:2] == ["https", "upstream"] and not neg and mode("pause"):
    import time
    Path(str(cfg)+".paused").touch(); time.sleep(30)
print("ok")''')
    ndmc = t / 'ndmc'; ndmc.write_text(fake); ndmc.chmod(0o755)
    device = t / 'device.conf'; device.write_text(ns['DEVICE_CONF']); device.chmod(0o600)
    lconf = etc / 'route-engine/domain-lists.conf'; lconf.write_text('managed.domain-list3=1\nwatch.domain-list3=1\n')
    env = dict(os.environ, VWARD_NDMC=str(ndmc), VWARD_DEVICE_CONFIG=str(device),
               VWARD_DEVICE_CONFIG_OWNER_UID=str(os.getuid()), VWARD_ROOT_PREFIX=str(t / 'root'),
               VWARD_DEVICE_MAP_CACHE=str(t / 'map'), VWARD_SYSFS_NET=str(t / 'sys'),
               VWARD_CONSOLE_ETC=str(etc), VWARD_ROUTE_STATE=str(t / 'route'),
               VWARD_CONSOLE_BACKUP_DIR=str(t / 'backup'), VWARD_CONSOLE_AUDIT_LOG=str(t / 'audit'),
               VWARD_ROUTE_CHANGE_LOCK=str(t / 'change.lock'),
               VWARD_PROFILE_LIB=str(ROOT / 'components/runtime/lib/vward-device-profile.sh'),
               VWARD_ADMISSION_LIB=str(ROOT / 'components/runtime/lib/vward-runtime-admission.sh'),
               VWARD_LIST_DNS_LIB=str(ROOT / 'components/console/lib/vward-list-dns.sh'),
               VWARD_ADS_CONTROL_BIN=str(t / 'no-ads'), VWARD_DOH_ALIVE='0', VWARD_JOURNAL_SYNC='0')
    def run(mode, expect='result=changed', group='domain-list3'):
        r = subprocess.run(['sh', str(HELPER), 'list-mode', group, mode], env=env, capture_output=True, text=True, timeout=30)
        assert r.stdout.strip().splitlines()[-1] == expect, f'LIST_DNS=FAIL {mode}: {r.stdout} {r.stderr}'
        return r
    run('dns', 'error=smartdns_not_configured')
    assert cfg.read_text() == baseline
    (etc / 'smartdns.conf').write_text('SMARTDNS_URL=https://dns.example.invalid/private-test\n')
    # Unknown is a refusal too. Only an actual successful probe enables DNS.
    run('dns', 'error=smartdns_unknown')
    curl = t / 'curl'; curl.write_text('#!/bin/sh\n[ ! -e "$T/dead" ] || { printf 000; exit 28; }\nprintf 200\n'); curl.chmod(0o755)
    env.update(VWARD_DOH_ALIVE='1', VWARD_CURL_BIN=str(curl), VWARD_DOH_ALIVE_DIR=str(t / 'alive'), T=td)
    (t / 'dead').touch()
    run('dns', 'error=smartdns_dead')
    assert cfg.read_text() == baseline
    (t / 'dead').unlink()
    run('dns', 'error=list_not_managed', 'domain-list0')
    # Capacity and overlapping ownership are refused BEFORE any mutation.
    cfg.write_text(baseline.replace('    include example.net', '\n'.join('    include x%d.example' % n for n in range(8))))
    before = cfg.read_text(); run('dns', 'error=smartdns_keenetic_full'); assert cfg.read_text() == before
    cfg.write_text(baseline.replace('    include owner.example', '    include sub.example.com'))
    before = cfg.read_text(); run('dns', 'error=list_dns_shared_domain'); assert cfg.read_text() == before
    cfg.write_text(baseline)
    run('dns')
    active = cfg.read_text()
    assert 'route object-group domain-list3 GigabitEthernet1 auto' in active and 'domain example.com' in active and 'domain example.net' in active
    assert 'watch.domain-list3=0' in lconf.read_text()
    assert 'guard.example' in active and 'ip name-server 192.0.2.53 owner.example on Wireguard0' in active
    run('dns', 'result=unchanged')
    # Every older UI writer must respect active list DNS ownership.
    for args in (('list-domain', 'add', 'domain-list3', 'new.example'),
                 ('list-domain', 'remove', 'domain-list3', 'example.com'),
                 ('list', 'clear', 'domain-list3'), ('list', 'delete', 'domain-list3'),
                 ('list', 'merge', 'domain-list3', 'domain-list0'),
                 ('list', 'merge', 'domain-list0', 'domain-list3'),
                 ('list-adopt', 'domain-list3', '0')):
        before_active = cfg.read_text()
        r = subprocess.run(['sh', str(HELPER), *args], env=env, capture_output=True, text=True, timeout=30)
        assert r.stdout.strip().endswith('error=list_dns_active'), f'LIST_DNS=FAIL: legacy writer bypass: {args}: {r.stdout}'
        assert cfg.read_text() == before_active
    r = subprocess.run(['sh', str(HELPER), 'domain-list-watch', 'domain-list3', '1'], env=env, capture_output=True, text=True, timeout=30)
    assert 'result=changed' in r.stdout and 'watch.domain-list3=1' in lconf.read_text(), r.stdout
    assert 'private-test' not in cfg.read_text(), 'watch enabled without leaving owned DNS'
    run('dns')
    # Exit through the same owned transaction, without restoring old deleted DNS.
    run('vpn')
    assert sorted(cfg.read_text().splitlines()) == sorted(baseline.splitlines())
    assert 'private-test' not in (t / 'audit').read_text(), 'private server leaked to audit'
    # A rejected router step leaves exact preimage and no success, permits a safe retry.
    Path(str(cfg) + '.mode-reject-route').touch()
    before = cfg.read_text(); before_conf = lconf.read_bytes()
    run('dns', 'error=list_dns_write_failed')
    assert cfg.read_text() == before and lconf.read_bytes() == before_conf
    Path(str(cfg) + '.mode-reject-route').unlink()
    # A partially applied batch and a lost successful reply both restore exactly.
    for mode in ('reject-dns', 'lost-reply'):
        marker = Path(str(cfg) + '.mode-' + mode); marker.touch()
        before = cfg.read_text(); before_conf = lconf.read_bytes()
        run('dns', 'error=list_dns_write_failed')
        assert sorted(cfg.read_text().splitlines()) == sorted(before.splitlines()), mode
        assert lconf.read_bytes() == before_conf, mode
        assert not list((t / 'backup-recovery').glob('smartdns.*')), mode
        marker.unlink()
    # TERM rolls back; SIGKILL keeps durable evidence and blocks the next mutation.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        marker = Path(str(cfg) + '.mode-pause'); marker.touch()
        paused = Path(str(cfg) + '.paused'); paused.unlink(missing_ok=True)
        p = subprocess.Popen(['sh', str(HELPER), 'list-mode', 'domain-list3', 'dns'], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        deadline = time.monotonic() + 10
        while not paused.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert paused.exists(), 'write was not reached'
        os.killpg(p.pid, sig); p.communicate(timeout=10)
        marker.unlink()
        if sig == signal.SIGTERM:
            assert sorted(cfg.read_text().splitlines()) == sorted(before.splitlines()), 'TERM rollback'
        else:
            assert list((t / 'backup-recovery').glob('smartdns.*')), 'SIGKILL lost recovery'
            run('dns', 'error=routing_recovery_required')
            # Fixture reset models an owner-directed recovery, never product auto replay.
            import shutil
            shutil.rmtree(t / 'backup-recovery')
            cfg.write_text(before)
    # An owner edit revokes compensation; it remains present with a closed gate.
    Path(str(cfg) + '.mode-owner-edit').touch()
    run('dns', 'error=rollback_incomplete')
    assert 'owner-change.example' in cfg.read_text(), 'owner edit overwritten'
    assert list((t / 'backup-recovery').glob('smartdns.*')), 'unknown state not retained'
    run('vpn', 'error=routing_recovery_required')
    # New ownership in another group during the write must revoke admission too.
    Path(str(cfg) + '.mode-owner-edit').unlink()
    shutil.rmtree(t / 'backup-recovery'); cfg.write_text(before)
    Path(str(cfg) + '.mode-owner-group-race').touch()
    run('dns', 'error=rollback_incomplete')
    assert 'object-group fqdn domain-list0\n    include example.com' in cfg.read_text()
    assert 'private-test' not in cfg.read_text(), 'DNS created after foreign group acquired the domain'
print('LIST_DNS=PASS')
