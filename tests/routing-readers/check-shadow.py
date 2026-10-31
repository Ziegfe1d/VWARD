#!/usr/bin/env python3
"""RS-6 shadow comparison on ONE consistent snapshot; executors are never called.

Legacy observations are produced by running the REAL extracted decision
functions (route-engine, reconciler, Services, tunnel-guard, policy-sync) on the
same fixture, then normalized and compared with the RS5/RS6 audit.
"""
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

def legacy_fn(path, name, prefix, call):
    src = (ROOT/path).read_text()
    m = re.search(r"^" + name + r"\(\)\s*\{\n.*?^\}\n", src, re.M | re.S)
    assert m, name
    r = subprocess.run(["sh", "-c", prefix + "\n" + m.group(0) + "\n" + call], capture_output=True, text=True, timeout=5)
    return r

def cfg_routes(cfg_text):
    """group -> {tunnel/ISP targets}, group -> domains (read-only parse of the fixture)."""
    routes, doms, g = {}, {}, None
    for line in cfg_text.splitlines():
        m = re.match(r'\s+route object-group (\S+) (\S+)', line)
        if m: routes.setdefault(m[1], set()).add('ISP' if m[2] == 'GigabitEthernet1' else 'VPN:' + m[2])
        m = re.match(r'object-group fqdn (\S+)$', line)
        if m: g = m[1]; doms.setdefault(g, [])
        m = re.match(r'\s+include (\S+)', line)
        if m and g: doms[g].append(m[1])
        if line.startswith('!'): g = None
    return routes, doms

def observe(f, gen, cfg_text=None, tunnel='Wireguard0', best_from='Wireguard1'):
    """Normalized observation file text for the current fixture state."""
    cfg_text = cfg_text if cfg_text is not None else f.cfg.read_text()
    routes, doms = cfg_routes(cfg_text)
    rows = [f'generation\t{gen}']
    q = shlex.quote
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        cfgfile = w/'cfg'; cfgfile.write_text(cfg_text)   # what the legacy side saw
        manual = w/'manual'; manual.write_text('x.example\nsmart.example\n')
        for d in ('x.example', 'smart.example', 'other.example'):
            r = legacy_fn('components/route-engine/scripts/vward-route-engine.sh', 'is_manual_known', 'MANUAL=' + q(str(manual)), 'is_manual_known ' + d)
            if r.returncode == 0:
                rows.append(f'route-engine\t{d}\t-\tnone\t-\tmanual\tskip\tmanual-list')
        r = legacy_fn('components/route-reconciler/scripts/vward-route-reconciler.sh', 'adaptive_names',
                      'vward_keenetic_config() { cat ' + q(str(cfgfile)) + '; }; vward_running_config() { cat ' + q(str(cfgfile)) + '; }', 'adaptive_names')
        assert r.returncode == 0
        running = set(r.stdout.split())
        for d in f.persist.read_text().split():
            conf = 'VPN:' + tunnel if d in running else 'none'
            rows.append(f'route-reconciler\t{d}\t{conf}\tVPN:{tunnel}\t-\tvward\t{"none" if d in running else "add"}\tpersist')
        r = legacy_fn('components/console/scripts/vward-console-config.sh', 'service_target',
                      'JQ=jq; SV_CAT=' + q(str(f.catalog)) + '; SERVICES_CATS=' + q(str(f.cats)) +
                      '; is_tunnel() { [ "$1" = Wireguard0 ] || [ "$1" = Wireguard1 ]; }', 'service_target auto svc')
        assert r.returncode == 0
        stgt = 'VPN:' + r.stdout.strip()
        for d in doms.get('domain-list0', []):
            cf = '|'.join(sorted(routes.get('domain-list0', {'none'})))
            rows.append(f'services\t{d}\t{cf}\t{stgt}\t-\tvward\tnone\tcatalog-pin')
        r = legacy_fn('components/policy-sync/scripts/vward-policy-sync.sh', 'collect_vpn_domains',
                      'WORK=' + q(td) + '; WG=nwg0; VWARD_TUNNEL_INTERFACE=' + tunnel, 'collect_vpn_domains ' + q(str(cfgfile)))
        assert r.returncode == 0
        for d in sorted(set(r.stdout.split())):
            rows.append(f'policy-sync\t{d}\tVPN:{tunnel}\t-\t-\t-\tobserve\tcidr-plan')
        (w/'q').write_text(f'{tunnel}\t0\t10\t0\t2\t0\t10\t5\n{best_from}\t0\t20\t0\t2\t0\t20\t6\n')
        r = legacy_fn('components/tunnel-guard/scripts/vward-tunnel-guard.sh', 'lists_best', 'LW=' + q(td), 'lists_best ' + tunnel)
        assert r.returncode == 0
        best = r.stdout.strip()
        if best:
            rows.append(f'tunnel-guard\t-\tVPN:{tunnel}\tVPN:{best}\t-\t-\tswitch\tguard-fallback')
    return '\n'.join(rows) + '\n'

def shadow(f, gen, audit, ident, legacy, env=None):
    with tempfile.TemporaryDirectory() as td:
        ps = [Path(td)/n for n in ('audit', 'ident', 'legacy')]
        for p, t in zip(ps, (audit, ident, legacy)): p.write_text(t)
        return f.run('. "$1"; vward_routing_shadow "$2" "$3" "$4" "$5"', SHADOW, gen, *ps, env=env)

def coordinated(f):
    out = f.p/'snap'; out.mkdir(mode=0o700, exist_ok=True)
    r = f.run('. "$1"; . "$2"; . "$4"; vward_routing_consistent_read "$3"', READ, SNAP, out, OBSERVE)
    assert r.returncode == 0, r.stdout + r.stderr
    gen = (out/'generation').read_text().strip()
    audit = f.audit((out/'intents.tsv').read_text(), (out/'snapshot.tsv').read_text())
    return gen, audit, (out/'identity.tsv').read_text()

def table(text):
    return [l.split('\t') for l in text.splitlines()]

def find(rows, mech, dom):
    got = [r for r in rows if r[1] == mech and r[0] == dom]
    assert len(got) == 1, (mech, dom, got)
    return got[0]

with Fixture() as f:
    # Poisoned transports: any call by the comparator itself would leave a trace.
    shim = f.p/'shim'; shim.mkdir(); trace = f.p/'trace'
    for name in ('ndmc', 'curl', 'nslookup', 'ip', 'iptables', 'ipset', 'wg', 'vward-route-engine.sh', 'vward-route-reconciler.sh'):
        (shim/name).write_text(f'#!/bin/sh\necho {name} >> {trace}\nexit 99\n'); (shim/name).chmod(0o755)
    env = dict(f.env, PATH=str(shim) + ':' + os.environ['PATH'])
    before = digest(f.p)
    gen, audit, ident = coordinated(f)
    legacy = observe(f, gen)
    r = shadow(f, gen, audit, ident, legacy, env=env)
    assert r.returncode == 0, r.stderr
    rows = table(r.stdout)
    assert all(len(x) == 14 for x in rows)
    # Same fixture twice -> byte-identical; permuted observation rows too.
    assert shadow(f, gen, audit, ident, legacy).stdout == r.stdout
    lines = legacy.splitlines()
    assert shadow(f, gen, audit, ident, '\n'.join([lines[0]] + lines[:0:-1]) + '\n').stdout == r.stdout, 'order dependent'
    assert not trace.exists(), 'comparator invoked an executor'
    # Expected semantics on the baseline.
    x = find(rows, 'route-engine', 'x.example')
    assert x[2] == 'match' and x[3] == 'observe-agrees' or x[2] == 'match', x
    assert 'rs=observe-only' in x[12] and 'secret' not in r.stdout
    a = find(rows, 'route-reconciler', 'a.example')      # persisted intent, no runtime route yet
    assert a[2] == 'match' and 'M' not in a[6].split(',') and 'A' in a[6], a
    s = find(rows, 'services', 's.example')
    assert s[2] == 'match' and 'identity=verified' in s[11], s   # proof matches, yet right stays rs=observe-only
    assert find(rows, 'policy-sync', 'smart.example')[2] == 'match'
    g = find(rows, 'tunnel-guard', '-')
    assert g[2] == 'diverge' and g[3] == 'guard-owned-switch' and g[4] == 'info' and g[5] == 'low', g
    assert not any(row[4] == 'review' for row in rows), [row for row in rows if row[4] == 'review']
    # Identity is an input of ownership, never of permission.
    assert all(row[12].startswith('rs=observe-only') for row in rows)

    # Same domains, different VPN: reconciler persists for Wireguard1 while RS wants Wireguard0.
    other = legacy.replace('route-reconciler\ta.example\tnone\tVPN:Wireguard0', 'route-reconciler\ta.example\tnone\tVPN:Wireguard1')
    rr = table(shadow(f, gen, audit, ident, other).stdout)
    t = find(rr, 'route-reconciler', 'a.example')
    assert t[2] == 'diverge' and t[3] == 'target-mismatch' and t[4] == 'review', t
    # ... but a guard fallback to ISP under VPN issues is an expected, protective difference.
    guard = legacy.replace('route-reconciler\ta.example\tnone\tVPN:Wireguard0\t-\tvward\tadd\tpersist', 'route-reconciler\ta.example\tnone\tISP\t-\tvward\tadd\tguard-fallback')
    t = find(table(shadow(f, gen, audit, ident, guard).stdout), 'route-reconciler', 'a.example')
    assert t[3] == 'expected-guard' and t[4] == 'info', t
    # DNS policy differs (legacy says default for a Smart DNS domain).
    dns = legacy.replace('route-engine\tsmart.example\t-\tnone\t-', 'route-engine\tsmart.example\t-\tVPN:Wireguard0\tdefault')
    t = find(table(shadow(f, gen, audit, ident, dns).stdout), 'route-engine', 'smart.example')
    assert t[3] == 'dns-mismatch' and t[4] == 'review', t
    # Configured route differs: legacy believes the service group is not routed.
    miss = legacy.replace('services\ts.example\tVPN:Wireguard0', 'services\ts.example\tnone')
    t = find(table(shadow(f, gen, audit, ident, miss).stdout), 'services', 's.example')
    assert t[3] == 'configured-mismatch', t
    # Unclaimed-by-RS domain (wildcard/legacy semantics) is reported, not silently dropped.
    extra = legacy + 'policy-sync\tghost.example\tVPN:Wireguard0\t-\t-\t-\tobserve\tcidr-plan\n'
    t = find(table(shadow(f, gen, audit, ident, extra).stdout), 'policy-sync', 'ghost.example')
    assert t[3] == 'legacy-only-domain' and t[4] == 'review'

    # VPN/ISP conflict stays explicit; legacy picks silently.
    f.cfg.write_text(CFG.replace('Mine Wireguard0 auto', 'Mine GigabitEthernet1 auto'))
    gen2, audit2, ident2 = coordinated(f)
    c = find(table(shadow(f, gen2, audit2, ident2, observe(f, gen2)).stdout), 'route-engine', 'x.example')
    assert c[3] == 'rs-conflict-legacy-picks' and c[4] == 'review', c
    # Unknown source (corrupt cache) -> rs-unknown, low confidence, never a false mismatch.
    f.cfg.write_text('error: refused\n')
    gen3, audit3, ident3 = coordinated(f)
    leg3 = observe(f, gen3, cfg_text=CFG)
    rr = table(shadow(f, gen3, audit3, ident3, leg3).stdout)
    assert rr and all(row[2] in ('unknown', 'match') or row[3] in ('legacy-only-domain', 'guard-owned-switch') for row in rr), rr
    assert any(row[3] == 'rs-unknown' and row[5] == 'low' for row in rr)
    assert not any(row[3] == 'configured-mismatch' for row in rr), 'unknown config produced a false mismatch'
    f.cfg.write_text(CFG)
    # Inactive source (adaptive disabled): RS ignores A, legacy still acts -> not-comparable.
    (f.etc/'route-engine/adaptive.disabled').write_text('')
    gen4, audit4, ident4 = coordinated(f)
    t = find(table(shadow(f, gen4, audit4, ident4, observe(f, gen4)).stdout), 'route-reconciler', 'a.example')
    assert t[2] == 'not-comparable' and t[3] == 'source-inactive', t
    (f.etc/'route-engine/adaptive.disabled').unlink()

    # Input-set discipline: a different generation, bad tokens, secrets and limits -> no stdout.
    r = shadow(f, gen, audit, ident, legacy.replace(gen, 'g-0000000000000000'))
    assert r.returncode == 3 and r.stdout == 'unknown\tgeneration-mismatch\n'
    r = shadow(f, 'g-0000000000000000', audit, ident, legacy)
    assert r.returncode == 3 and r.stdout.startswith('unknown')
    r = shadow(f, gen, audit, ident, legacy + 'services\tx.example\tVPN:Wireguard0\tVPN:Wireguard0\thttps://dns.example/secret-token\tvward\tnone\tnone\n')
    assert r.returncode == 2 and r.stdout == '' and 'secret' not in r.stderr
    r = shadow(f, gen, audit, ident, legacy + 'services\tx.example\tROUTE\tnone\t-\tvward\tnone\tnone\n'); assert r.returncode == 2 and r.stdout == ''
    r = shadow(f, gen, audit, ident, legacy.replace('generation\t' + gen + '\n', '')); assert r.returncode == 2 and r.stdout == ''
    r = shadow(f, 'bad', audit, ident, legacy); assert r.returncode == 2 and r.stdout == ''
    big = legacy + ''.join(f'policy-sync\tx.example\tVPN:Wireguard0\t-\t-\t-\tobserve\tcidr-plan\n' for _ in range(5000))
    r = shadow(f, gen, audit, ident, big); assert r.returncode == 2 and r.stdout == ''
    # Output cap: 1024 domains x 5 mechanisms would exceed 4096 rows -> refused, not truncated.
    many_a = ''.join(f'd{i}.example\t-\t-\t-\t-\t-\t0\tinactive\tno-active-intent\t-\t{gen}\tunknown\n' for i in range(1024))
    many_l = f'generation\t{gen}\n' + ''.join(f'{m}\td{i}.example\t-\t-\t-\t-\tobserve\tnone\n' for i in range(1024)
                                              for m in ('route-engine', 'route-reconciler', 'services', 'policy-sync', 'route-engine'))
    r = shadow(f, gen, many_a, ident, many_l); assert r.returncode == 2 and r.stdout == '', r.returncode
    # Inputs unchanged; no executor trace; loading is inert.
    assert not trace.exists()
    assert {k: v for k, v in digest(f.p).items() if not k.startswith(('snap/', 'shim/'))} == {k: v for k, v in before.items() if not k.startswith(('snap/', 'shim/'))}
    assert f.run('sentinel=1; . "$1"; [ "$sentinel" = 1 ]', SHADOW).returncode == 0
print('RS6_SHADOW=PASS: match/diverge classes, guard fallback, VPN/ISP/DNS, unknown, limits, no executor calls')
