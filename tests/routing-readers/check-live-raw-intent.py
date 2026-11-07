#!/usr/bin/env python3
"""First import keeps the raw legacy selection; it never adopts the observed route.

enabled.tsv stores ID<TAB>GROUP<TAB>auto|TUNNEL. "auto" is the logical default
selector (canonical VPN:auto), a tunnel is an explicit pin. The currently
observed native route is evidence only: it must not replace auto by a physical
interface, must not move a pin, and an observed provider route never becomes
an ISP choice.
"""
import json
import shutil
from live_fixture import LiveFixture

SERVICES = {  # id: (group, raw selection, observed native route)
    'sa': ('domain-list0', 'auto', 'Wireguard0'),
    'sp': ('domain-list1', 'Wireguard1', 'Wireguard0'),
    'so': ('domain-list2', 'OpkgTun4', 'OpkgTun4'),
    'sv': ('domain-list3', 'auto', 'OpkgTun4'),
    'sm': ('domain-list4', 'Wireguard9', 'Wireguard0'),
}
EXPECTED = {'sa': 'VPN:auto', 'sp': 'VPN:Wireguard1', 'so': 'VPN:OpkgTun4',
            'sv': 'VPN:auto', 'sm': 'VPN:Wireguard9'}


def prepare(f, services):
    catalog = {'schema': 1, 'services': [
        {'id': sid, 'title': 'T' + sid, 'category': 'other', 'domains': [sid + '.example']}
        for sid in services] + [{'id': 'idle', 'title': 'Idle', 'category': 'other', 'domains': ['idle.example']}]}
    (f.prefix / 'opt/var/lib/vward/services/catalog.json').write_text(json.dumps(catalog))
    (f.etc / 'services/categories.tsv').write_text('')
    f.install_console()
    r = f.console('service', 'off', 'idle')
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    shutil.rmtree(f.live)
    cache = f.prefix / 'tmp/vward-device-map.tsv'
    cache.write_text(cache.read_text() + 'I\tOpkgTun4\tOpkgTun\topkgtun4\tprivate\n')
    routes = ''.join(f'    route object-group {g} {t} auto\n' for g, _raw, t in services.values())
    groups = ''.join(f'object-group fqdn {g}\n    include {sid}.example\n!\n' for sid, (g, _raw, _t) in services.items())
    f.native.write_text('interface OpkgTun4\n!\n' + f.native.read_text().replace('dns-proxy\n', 'dns-proxy\n' + routes) + groups)
    f.startup.write_bytes(f.native.read_bytes())
    (f.etc / 'services/enabled.tsv').write_text(''.join(f'{sid}\t{g}\t{raw}\n' for sid, (g, raw, _t) in services.items()))
    for sid, (g, _raw, t) in services.items():
        proof = f.etc / 'services/owned' / g
        proof.write_text(f'include {sid}.example\nroute={t}\tauto\n')
        proof.chmod(0o400)


def choices(f):
    path = f.live / 'decision/choices.tsv'
    if not path.exists():
        return None
    return {row.split('\t')[1]: row.split('\t')[3:6] for row in path.read_text().splitlines() if row.startswith('service\t')}


fail = []
with LiveFixture(vpns=2) as f:
    prepare(f, SERVICES)
    before, saved = f.native.read_bytes(), f.startup.read_bytes()
    r = f.console('service', 'off', 'idle', preserve_profile=True)
    got = choices(f)
    if r.returncode != 0 or got is None:
        fail.append(('import refused', r.returncode, r.stdout, r.stderr))
    else:
        for sid, target in EXPECTED.items():
            if got.get(sid) != ['vpn', target, 'default']:
                fail.append((sid, 'raw', SERVICES[sid][1], 'observed', SERVICES[sid][2], 'choice', got.get(sid)))
    if f.native.read_bytes() != before or f.startup.read_bytes() != saved:
        fail.append(('import changed native configuration',))

# An observed provider route is never adopted as an ISP choice, and a missing
# raw selection is never filled in from the observation.
for case, services in (('observed-isp', {'sa': ('domain-list0', 'auto', 'GigabitEthernet1')}),
                       ('missing-raw', {'sa': ('domain-list0', '', 'Wireguard0')})):
    with LiveFixture(vpns=2) as f:
        prepare(f, services)
        before, saved = f.native.read_bytes(), f.startup.read_bytes()
        r = f.console('service', 'off', 'idle', preserve_profile=True)
        got = choices(f)
        if f.native.read_bytes() != before or f.startup.read_bytes() != saved:
            fail.append((case, 'import changed native configuration'))
        if case == 'missing-raw':
            if r.returncode == 0 or got is not None:
                fail.append((case, 'missing raw selection imported', r.returncode, got, r.stdout, r.stderr))
        elif got is not None and got.get('sa') not in (None, ['vpn', 'VPN:auto', 'default']):
            fail.append((case, 'observed route became the choice', got.get('sa')))

assert not fail, fail
print('LIVE_RAW_INTENT=PASS raw auto/pin/OpkgTun4/missing pin kept; observed route and provider route never become the choice')
