#!/usr/bin/env python3
"""Legacy pending must resolve through its real CLI before first common state exists."""
import shutil
import subprocess
import os
from live_fixture import LiveFixture

with LiveFixture() as f:
    if os.environ.get('RS6_BUSYBOX'):
        mv=f.p/'poison/mv';mv.symlink_to(os.environ['RS6_BUSYBOX'])
    shutil.rmtree(f.live)
    txn=f.prefix/'opt/var/backups/vward/console-config/service-transactions/txn.abcdef'
    txn.mkdir(parents=True,mode=0o700)
    for parent in (txn.parent,txn.parent.parent):parent.chmod(0o700)
    for name in ('pending','ai','groups'):(txn/name).write_text('')
    dead=subprocess.Popen(['true']);dead.wait();(txn/'pid').write_text(str(dead.pid)+'\n')
    before=f.native.read_bytes()
    r=f.invoke('vward_routing_live_bootstrap','init-pending')
    assert r.returncode==75 and not f.live.exists(),('bootstrap hid old recovery behind new schema gate',r.returncode,r.stdout,r.stderr)
    assert (txn/'pending').exists() and f.native.read_bytes()==before
    # Explicit fixture owner action uses the actual existing console recovery,
    # not an rm pending workaround. It keeps current configuration/evidence.
    r=f.console('service-recover','txn.abcdef','accept')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert not f.live.exists() and f.native.read_bytes()==before
    resolved=txn.parent.parent/'service-transactions.resolved/txn.abcdef'
    assert resolved.is_dir() and (resolved/'resolved').is_file() and not (resolved/'pending').exists()
    r=f.invoke('vward_routing_live_bootstrap','init-clean')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (f.live/'decision/version.tsv').read_text()=='routing-state\t2\n'
    assert f.native.read_bytes()==before,'observation-only import changed native routing'
    assert not [x for x in f.calls.read_text().splitlines() if not x.endswith('\tshow running-config')]

with LiveFixture() as f:
    shutil.rmtree(f.live)
    if os.environ.get('RS6_BUSYBOX'):(f.p/'poison/mv').symlink_to(os.environ['RS6_BUSYBOX'])
    bundled=f.prefix/'opt/share/vward/console/services-catalog.json';bundled.parent.mkdir(parents=True)
    (f.prefix/'opt/var/lib/vward/services/catalog.json').rename(bundled)
    enabled=f.etc/'services/enabled.tsv';enabled.write_text('svc\tdomain-list0\tauto\n');enabled.chmod(0o644)
    proof=f.etc/'services/owned/domain-list0'
    proof.write_text('include s.example\ninclude x.example\nroute=Wireguard0\tauto\n');proof.chmod(0o400)
    foreign='object-group fqdn Owner\n    include outside.example\n!\n'
    f.native.write_text(f.native.read_text().replace('dns-proxy\n','dns-proxy\n    route object-group domain-list0 Wireguard0 auto\n    route object-group Owner ISP auto\n')+
                       'object-group fqdn domain-list0\n    include x.example\n    include s.example\n!\n'+foreign)
    before=f.native.read_bytes();startup=f.startup.read_bytes()
    old={p:(p.read_bytes(),p.stat().st_mode&0o777) for p in f.etc.rglob('*') if p.is_file()}
    r=f.invoke('vward_routing_live_bootstrap','init-legacy')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert f.native.read_bytes()==before and f.startup.read_bytes()==startup,'migration wrote/saved native legacy configuration'
    assert all(p.read_bytes()==data and p.stat().st_mode&0o777==mode for p,(data,mode) in old.items())
    # Raw 'auto' is kept as VPN:auto, not the observed physical Wireguard0.
    assert '\tvpn\tVPN:auto\tdefault\t' in (f.live/'decision/choices.tsv').read_text()
    rows=(f.live/'decision/resources.tsv').read_text().splitlines()
    assert len(rows)==2 and all(r.split('\t')[8]=='vward' for r in rows),rows
    assert 'outside.example' not in (f.live/'decision/resources.tsv').read_text(),'manual group adopted by importer'
    assert (f.live/'journal/init-legacy/state').read_text()=='committed\n'
    assert (f.live/'.bootstrap/completion').read_text()=='acknowledged-root-transfer\n'
    assert all(x.endswith('\tshow running-config') for x in f.calls.read_text().splitlines())
print('LIVE_BOOTSTRAP=PASS pending refuses before ROOT, actual legacy owner recovery remains reachable; clean observation-only version-last import')
