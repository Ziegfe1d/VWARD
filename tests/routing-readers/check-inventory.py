#!/usr/bin/env python3
"""Native inventory keeps stable resource, mutable content, native name and rights separate."""
from fixture import Fixture
with Fixture() as f:
    first=[x.split('\t') for x in f.read('inventory').splitlines()]
    assert first and all(len(r)==13 and r[0]=='resource' and r[10]=='reference' for r in first)
    own=[r for r in first if r[2]=='domain-list0']
    assert own and all(r[7]=='vward' and r[9]=='verified' for r in own)
    manual=[r for r in first if r[2]=='Mine']
    assert manual and all(r[9]=='reference-only' for r in manual)
    before={r[3]:r for r in own}
    f.cfg.write_text(f.cfg.read_text().replace('domain-list0 Wireguard0','domain-list0 Wireguard1'))
    after={r[3]:r for r in [x.split('\t') for x in f.read('inventory').splitlines()] if r[2]=='domain-list0'}
    for domain,row in after.items():
        assert row[12]==before[domain][12] and row[11]==before[domain][11],'stable identity depends on target'
        assert row[1]!=before[domain][1] and row[8]!=before[domain][8],'content revision did not change'
        assert row[9]=='unknown' and row[7]=='unknown','stale exact proof granted ownership'
print('B_NATIVE_INVENTORY=PASS stable identity/content/native name/exact proof, reference-only rights')
