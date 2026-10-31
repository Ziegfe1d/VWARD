#!/usr/bin/env python3
"""RS-6 persistent identity: REF/container/content/route IDs and identity states.

Identity (what a record IS) is kept apart from content (what it holds), link
(where the reference came from) and right (permission to change: always
`reference` here). Name, list position or equal domains never prove ownership.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

def rows(text):
    return [line.split('\t') for line in text.splitlines()]

def by_ref(f):
    return {r[0]: r for r in rows(f.read('identity'))}

with Fixture() as f:
    before = digest(f.p)
    base = {m: f.read(m) for m in ('intents', 'snapshot', 'identity')}
    assert all(f.read(m) == base[m] for m in base), 'repeat reads differ'
    assert digest(f.p) == before, 'inputs changed by reading'
    ids = rows(base['identity'])
    assert ids and all(len(r) == 9 and r[8] == 'reference' for r in ids), 'rights must stay reference'
    assert 'managed' not in base['identity'] and 'secret' not in base['identity']
    for r in ids:  # contract identifier charset / length (RS5 REF)
        assert len(r[0]) <= 64 and r[0][0].isalnum()
    # Every identity REF is exactly an intent REF or a snapshot route REF.
    refs = {l.split('\t')[1] for l in base['intents'].splitlines()}
    refs |= {l.split('\t')[1] for l in base['snapshot'].splitlines() if l.startswith('route\t')}
    assert {r[0] for r in ids} == refs, 'identity table and RS5 projections disagree'
    state = {r[0]: r[7] for r in ids}
    # The owned service group (private exact proof) is verified; manual/runtime/persist are reference-only.
    kinds = {(r[1], r[2]): r[7] for r in ids}
    assert kinds[('intent', 'S')] == 'verified' and kinds[('intent', 'M')] == 'reference-only'
    assert kinds[('intent', 'A')] == 'reference-only'

    # 1. Permuting rows, groups, routes, enabled/persist order changes nothing.
    f.cfg.write_text(
        'interface Wireguard1\n!\ninterface Wireguard0\n!\ndns-proxy\n'
        '    https upstream https://dns.example/secret-token domain smart.example\n'
        '    route object-group AdaptiveAuto Wireguard0 auto\n'
        '    route object-group domain-list0 Wireguard0 auto\n'
        '    route object-group Mine Wireguard0 auto\n!\n'
        'object-group fqdn AdaptiveAuto\n    include x.example\n!\n'
        'object-group fqdn domain-list0\n    include s.example\n    include x.example\n!\n'
        'object-group fqdn Mine\n    include smart.example\n    include x.example\n!\n')
    f.persist.write_text('a.example\nx.example\n')
    permuted = {m: f.read(m) for m in base}
    assert permuted == base, 'row/group permutation renamed or reordered identities'
    # Inserting an unrelated group before the others keeps every existing ID.
    f.cfg.write_text(f.cfg.read_text().replace('object-group fqdn AdaptiveAuto',
        'object-group fqdn Another\n    include other.example\n!\nobject-group fqdn AdaptiveAuto', 1))
    assert {r[0] for r in rows(f.read('identity'))} >= {r[0] for r in ids}, 'existing IDs moved after insertion'
    f.cfg.write_text(CFG)

    # 2. Different VPN / ISP routes never share route ID or REF.
    wg1 = CFG.replace('route object-group Mine Wireguard0 auto', 'route object-group Mine Wireguard1 auto')
    f.cfg.write_text(wg1); moved = rows(f.read('identity')); f.cfg.write_text(CFG)
    isp = CFG.replace('route object-group Mine Wireguard0 auto', 'route object-group Mine GigabitEthernet1 auto')
    f.cfg.write_text(isp); direct = rows(f.read('identity')); f.cfg.write_text(CFG)
    route_ids = lambda rs: {r[5] for r in rs if r[1] == 'route'}
    assert route_ids(moved) != route_ids(ids) and route_ids(direct) != route_ids(ids) and route_ids(moved) != route_ids(direct)
    assert {r[0] for r in moved} & {r[0] for r in direct} - {r[0] for r in ids} == set(), 'VPN and ISP records share a REF'

    # 3. Reused group name: same name, different content -> proof no longer matches.
    f.cfg.write_text(CFG.replace('include s.example', 'include foreign.example'))
    reuse = by_ref(f)
    assert all(r[7] == 'unknown' for r in reuse.values() if r[3].startswith('g-') and r[6] == 'native-group'
               and r[3] == next(x[3] for x in ids if x[1] == 'route' and x[7] == 'verified')), reuse
    assert not any(r[7] == 'verified' for r in reuse.values()), 'changed group still verified'
    # 4. User adds a domain: private proof no longer exact -> unknown, never verified.
    f.cfg.write_text(CFG.replace('    include s.example\n', '    include s.example\n    include extra.example\n'))
    assert not any(r[7] == 'verified' for r in rows(f.read('identity')))
    # 5. Foreign group with identical domains and routes but a different name: same content ID, other container, never verified.
    f.cfg.write_text(CFG.replace('domain-list0', 'domain-list7'))
    foreign = rows(f.read('identity'))
    assert not any(r[7] == 'verified' for r in foreign), 'name change inherited the proof'
    assert {r[4] for r in foreign if r[1] == 'route' and r[6] == 'native-group'} >= {r[4] for r in ids if r[7] == 'verified'}
    f.cfg.write_text(CFG)
    # 6. Proof missing -> reference-only; unsafe proof mode or symlink -> unknown. Name alone is nothing.
    f.proof.unlink()
    assert not any(r[7] == 'verified' for r in rows(f.read('identity')))
    assert all(r[7] == 'reference-only' for r in rows(f.read('identity')) if r[3] == next(x[3] for x in ids if x[7] == 'verified'))
    f.proof.write_text('include s.example\ninclude x.example\nroute=Wireguard0\tauto\n'); f.proof.chmod(0o666)
    assert not any(r[7] == 'verified' for r in rows(f.read('identity')))
    assert any(r[7] == 'unknown' for r in rows(f.read('identity')))
    f.proof.chmod(0o600)
    assert any(r[7] == 'verified' for r in rows(f.read('identity'))), 'restored proof must verify again'
    # 7. Duplicate declaration of one group name is ambiguous -> unknown + M unknown (never merged silently).
    f.cfg.write_text(CFG + 'object-group fqdn Mine\n    include dup.example\n!\n')
    dup = rows(f.read('identity'))
    assert all(r[7] == 'unknown' for r in dup if r[6] == 'native-group' and r[3] == next(x[3] for x in ids if x[1] == 'intent' and x[2] == 'M'))
    assert 'source\tM\t1\tunknown' in f.read('snapshot')
    f.cfg.write_text(CFG)
    # 8. Unknown / unreadable configuration yields no invented identities.
    f.cfg.write_text('error: refused\n')
    assert not [r for r in rows(f.read('identity')) if r[1] == 'route' or r[2] in ('M',)]
    f.cfg.unlink()
    assert not [r for r in rows(f.read('identity')) if r[1] == 'route']
    # 9. Service whose group cfg is gone: unknown, not an invented link.
    f.cfg.write_text(CFG.replace('domain-list0', 'other-list'))
    assert all(r[7] == 'unknown' for r in rows(f.read('identity')) if r[2] == 'S')
    # 10. Same RS5 audit result for permuted input (decision-level determinism).
    f.cfg.write_text(CFG)
    a = f.audit(base['intents'], base['snapshot'])
    assert a == f.audit(f.read('intents'), f.read('snapshot'))
print('RS6_IDENTITY=PASS: stable IDs, permutation/insert/reuse/foreign/duplicate/unsafe proof, VPN-vs-ISP')
