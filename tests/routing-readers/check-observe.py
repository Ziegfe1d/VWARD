#!/usr/bin/env python3
"""RS-6 stage 3: read-only observers of route-engine, reconciler, Services,
tunnel-guard and policy-sync on ONE verified snapshot. Parity with the real
decision functions; no executor, network or write call; changes -> unknown."""
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

RE = 'components/route-engine/scripts/vward-route-engine.sh'
RC = 'components/route-reconciler/scripts/vward-route-reconciler.sh'
SV = 'components/console/scripts/vward-console-config.sh'
TG = 'components/tunnel-guard/scripts/vward-tunnel-guard.sh'
TQ = 'components/tunnel-guard/scripts/vward-tunnel-quality.sh'
PS = 'components/policy-sync/scripts/vward-policy-sync.sh'
q = shlex.quote
LOAD = '. "$1"; . "$2"; . "$4"; vward_routing_consistent_read "$3"'

def snap(f, name='snap', env=None):
    out = f.p/name; out.mkdir(mode=0o700, exist_ok=True)
    r = f.run(LOAD, READ, SNAP, out, OBSERVE, env=env)
    return r, out

def rows(out):
    lines = (out/'legacy.tsv').read_text().splitlines()
    assert lines[0].startswith('generation\tg-')
    return [l.split('\t') for l in lines[1:]]

def pick(rs, mech, dom=None):
    return [r for r in rs if r[0] == mech and (dom is None or r[1] == dom)]

def shadow(f, out, gen=None):
    gen = gen or (out/'generation').read_text().strip()
    audit = f.audit((out/'intents.tsv').read_text(), (out/'snapshot.tsv').read_text())
    with tempfile.TemporaryDirectory() as td:
        a = Path(td)/'a'; a.write_text(audit)
        r = f.run('. "$1"; vward_routing_shadow "$2" "$3" "$4" "$5"', SHADOW, gen, a, out/'identity.tsv', out/'legacy.tsv')
    assert r.returncode == 0, r.stderr
    return [l.split('\t') for l in r.stdout.splitlines()]

now = int(time.time())
def samples(f, spec):
    """spec: {tunnel: [loss per minute oldest..newest]}"""
    lines = []
    for name, losses in spec.items():
        for i, loss in enumerate(losses):
            ts = now - (len(losses) - 1 - i) * 30
            lines.append(f'{ts}\t{name}\tnwg\t{loss}\t{10 if loss < 100 else "-"}')
    p = f.p/'quality'; p.mkdir(exist_ok=True)
    (p/'samples.tsv').write_text('\n'.join(lines) + '\n')
    f.env['VWARD_TUNNEL_QUALITY_DIR'] = str(p)

with Fixture() as f:
    shim = f.p/'shim'; shim.mkdir(); trace = f.p/'trace'
    for name in ('ndmc', 'curl', 'nslookup', 'dig', 'ip', 'iptables', 'ipset', 'wg', 'vward-route-engine.sh',
                 'vward-route-reconciler.sh', 'vward-tunnel-guard.sh', 'vward-policy-sync.sh', 'vward-console-config.sh'):
        (shim/name).write_text(f'#!/bin/sh\necho {name} >> {trace}\nexit 99\n'); (shim/name).chmod(0o755)
    f.env = dict(f.env, PATH=str(shim) + ':' + os.environ['PATH'], VWARD_TUNNEL_GUARD_DIR=str(f.p/'guard'))
    (f.p/'guard').mkdir()
    # Fixture content for the observers.
    (f.state/'manual-domains.txt').write_text('smart.example\n*.sub.test\n')
    (f.state/'adaptive-domains.txt').write_text('x.example\n')
    (f.etc/'route-engine/force-vpn.conf').write_text('# owner list\nx.example\n*.sub.test  # wildcard\n')
    samples(f, {'Wireguard0': [0, 0, 0, 0], 'Wireguard1': [0, 0, 0, 0]})
    inputs_before = digest(f.p)

    # ---- baseline + parity with the REAL functions --------------------------------------
    r, out = snap(f)
    assert r.returncode == 0, (r.stdout, r.stderr)
    gen = (out/'generation').read_text().strip()
    L = rows(out)
    legacy_text = (out/'legacy.tsv').read_text()
    assert 'secret' not in legacy_text and 'http' not in legacy_text
    universe = {x[1] for x in pick(L, 'policy-sync')} | {'a.example', 'other.example'}
    # route-engine.is_manual_known
    for d in sorted(universe):
        real = legacy_fn(RE, 'is_manual_known', 'MANUAL=' + q(str(f.state/'manual-domains.txt')), 'is_manual_known ' + d).returncode == 0
        got = [x for x in pick(L, 'route-engine', d) if x[6] == 'skip']
        assert real == bool(got), (d, real, got)
    # reconciler.adaptive_names == observed AdaptiveAuto members
    cfgf = q(str(f.cfg))
    real = legacy_fn(RC, 'adaptive_names', f'vward_keenetic_config() {{ cat {cfgf}; }}; vward_running_config() {{ cat {cfgf}; }}', 'adaptive_names')
    assert real.returncode == 0 and {x[1] for x in pick(L, 'route-reconciler')} == set(real.stdout.split())
    # reconciler.force_vpn_match (hard-coded path substituted, nothing else changed)
    for d in ('x.example', 'a.example', 'sub.test', 'a.sub.test', 'b.other.test'):
        rr = legacy_fn(RC, 'force_vpn_match', '', 'force_vpn_match ' + d,
                       [('F="/opt/etc/vward/route-engine/force-vpn.conf"', f'F={q(str(f.etc/"route-engine/force-vpn.conf"))}')])
        assert rr.returncode in (0, 1)
    x = pick(L, 'route-reconciler', 'x.example')[0]
    assert x[3] == 'VPN:Wireguard0' and x[7] == 'force-vpn', x      # forced by force-vpn.conf
    # services.service_target (real) vs observed desired target
    for pin, svc in (('auto', 'svc'),):
        rs_ = legacy_fn(SV, 'service_target', 'JQ=jq; SV_CAT=' + q(str(f.catalog)) + '; SERVICES_CATS=' + q(str(f.cats)) +
                        '; is_tunnel() { [ "$1" = Wireguard0 ] || [ "$1" = Wireguard1 ]; }', f'service_target {pin} {svc}')
        assert rs_.returncode == 0 and rs_.stdout.strip() == 'Wireguard0'
        assert all(r[3] == 'VPN:Wireguard0' and r[7] == 'catalog-pin' for r in pick(L, 'services'))
    # policy-sync.collect_vpn_domains
    with tempfile.TemporaryDirectory() as td:
        ps = legacy_fn(PS, 'collect_vpn_domains', 'WORK=' + q(td) + '; WG=nwg0; VWARD_TUNNEL_INTERFACE=Wireguard0', 'collect_vpn_domains ' + cfgf)
    assert ps.returncode == 0 and {x[1] for x in pick(L, 'policy-sync')} == set(ps.stdout.split())
    assert all(x[7] == 'cidr-plan' and x[3] == '-' for x in pick(L, 'policy-sync'))   # no IP/CIDR claim
    # tunnel-guard lists_best on the real quality summary of the same samples
    with tempfile.TemporaryDirectory() as td:
        sm = legacy_fn(TQ, 'summary', f'SAMPLES={q(str(f.p/"quality/samples.tsv"))}; SPEED_FILE=/nonexistent; WINDOW=1800', 'summary > ' + q(td + '/q'))
        assert sm.returncode == 0
        best = legacy_fn(TG, 'lists_best', 'LW=' + q(td), 'lists_best Wireguard0').stdout.strip()
    g = pick(L, 'tunnel-guard', '-')
    assert len(g) == 1 and g[0][3] == g[0][2] == 'VPN:Wireguard0' and best == 'Wireguard1', (g, best)  # healthy: no switch proposed

    # ---- shadow on the coordinated LEGACY ---------------------------------------------
    sh = shadow(f, out)
    cls = {(r[1], r[0]): r[3] for r in sh}
    assert cls[('route-engine', 'smart.example')] == 'observe-agrees' or cls[('route-engine', 'smart.example')] == 'match'
    assert not [r for r in sh if r[4] == 'review'], [r for r in sh if r[4] == 'review']
    assert cls[('route-reconciler', 'x.example')] in ('match',)    # forced VPN agrees with M/A/S wanted VPN
    assert not trace.exists(), 'executor was invoked'

    # ---- wildcard semantics (both exact) -------------------------------------------------
    f.cfg.write_text('interface Wireguard0\n!\ndns-proxy\n    route object-group Mine Wireguard0 auto\n    route object-group AdaptiveAuto Wireguard0 auto\n!\n'
                     'object-group fqdn Mine\n    include sub.test\n    include a.sub.test\n    include b.other.test\n!\n'
                     'object-group fqdn AdaptiveAuto\n    include sub.test\n    include a.sub.test\n!\n')
    f.enabled.write_text(''); f.persist.write_text('')
    (f.etc/'services/owned/domain-list0').unlink()
    r, out = snap(f); assert r.returncode == 0, r.stdout
    L = rows(out)
    skip = {x[1] for x in pick(L, 'route-engine') if x[6] == 'skip'}
    assert skip == {'a.sub.test'}, skip                                  # strict subdomain only, apex not
    forced = {x[1] for x in pick(L, 'route-reconciler') if x[7] == 'force-vpn'}
    assert forced == {'sub.test', 'a.sub.test'}, forced                  # reconciler matches the apex too
    for d in ('sub.test', 'a.sub.test', 'b.other.test'):
        real = legacy_fn(RE, 'is_manual_known', 'MANUAL=' + q(str(f.state/'manual-domains.txt')), 'is_manual_known ' + d).returncode == 0
        assert real == (d in skip)

    # ---- Services: target replaced by "vpn" (profile tunnel) vs RS-6 ------------------------
    f.cfg.write_text(CFG)
    f.enabled.write_text('svc\tdomain-list0\tauto\n'); f.persist.write_text('x.example\na.example\n')
    f.proof.write_text('include s.example\ninclude x.example\nroute=Wireguard0\tauto\n'); f.proof.chmod(0o600)
    # (a) category row missing: Services use "vpn" = the profile tunnel; RS-6 also takes the profile
    # tunnel, so the decisions AGREE (basis is still recorded as defaulted).
    f.cats.write_text('other\tWireguard1\n')
    r, out = snap(f); assert r.returncode == 0
    L = rows(out)
    assert all(x[3] == 'VPN:Wireguard0' and x[7] == 'service-target-defaulted' for x in pick(L, 'services')), pick(L, 'services')
    assert not [r for r in shadow(f, out) if r[1] == 'services' and r[3] == 'service-target-defaulted']
    # (b) the category names an interface that is not a known tunnel: Services still fall back to
    # "vpn" (is_tunnel false), RS-6 keeps the target unknown -> recorded divergence class.
    f.cats.write_text('ai\tWireguard9\n')
    r, out = snap(f); assert r.returncode == 0
    L = rows(out)
    assert all(x[3] == 'VPN:Wireguard0' and x[7] == 'service-target-defaulted' for x in pick(L, 'services')), pick(L, 'services')
    real = legacy_fn(SV, 'service_target', 'JQ=jq; SV_CAT=' + q(str(f.catalog)) + '; SERVICES_CATS=' + q(str(f.cats)) +
                     '; is_tunnel() { [ "$1" = Wireguard0 ] || [ "$1" = Wireguard1 ]; }', 'service_target auto svc')
    assert real.stdout.strip() == 'vpn'                                  # the production substitution
    sh = shadow(f, out)
    d = [r for r in sh if r[1] == 'services']
    assert d and all(r[3] == 'service-target-defaulted' and r[2] == 'diverge' and r[4] == 'info' and r[5] == 'low' for r in d), d
    assert 'source\tS\t1\tunknown' in (out/'snapshot.tsv').read_text()   # RS-6 keeps unknown
    # (c) no categories.tsv at all: Services default, RS-6 source S unknown.
    f.cats.unlink()
    r, out = snap(f); assert r.returncode == 0
    assert all(x[7] == 'service-target-defaulted' for x in pick(rows(out), 'services'))
    assert all(r[3] == 'service-target-defaulted' for r in shadow(f, out) if r[1] == 'services')
    f.cats.write_text('ai\tWireguard0\n')

    # ---- tunnel-guard: saved moves, return, quality switch -----------------------------
    mine_moved = CFG.replace('route object-group Mine Wireguard0 auto', 'route object-group Mine Wireguard1 auto')
    f.cfg.write_text(mine_moved)
    (f.p/'guard/lists-fallback').write_text('Mine\tWireguard0\tWireguard1\t1\nGone\tWireguard0\tWireguard1\t1\n')
    r, out = snap(f); assert r.returncode == 0
    L = rows(out)
    tg = {x[1]: x for x in pick(L, 'tunnel-guard') if x[1] != '-'}
    assert set(tg) == {'x.example', 'smart.example'} and all(v[2] == 'VPN:Wireguard1' and v[3] == 'VPN:Wireguard0' and v[7] == 'guard-fallback' and v[6] == 'restore' for v in tg.values()), tg
    sh = shadow(f, out)
    tgs = {r[0]: r for r in sh if r[1] == 'tunnel-guard' and r[0] != '-'}
    assert tgs['smart.example'][3] == 'expected-guard' and tgs['smart.example'][4] == 'info', tgs
    # x.example is also in two other groups still routed to Wireguard0: RS-6 keeps that conflict explicit.
    assert tgs['x.example'][3] == 'rs-conflict-legacy-picks', tgs
    # A move the guard would forget (list no longer routed to "to") claims nothing.
    f.cfg.write_text(CFG)
    r, out = snap(f); assert not [x for x in pick(rows(out), 'tunnel-guard') if x[1] != '-']
    (f.p/'guard/lists-fallback').unlink()
    # Quality: the profile tunnel failed twice, Wireguard1 answers -> real lists_best agrees.
    samples(f, {'Wireguard0': [0, 0, 100, 100], 'Wireguard1': [0, 0, 0, 0]})
    r, out = snap(f); assert r.returncode == 0
    g = pick(rows(out), 'tunnel-guard', '-')
    with tempfile.TemporaryDirectory() as td:
        legacy_fn(TQ, 'summary', f'SAMPLES={q(str(f.p/"quality/samples.tsv"))}; SPEED_FILE=/nonexistent; WINDOW=1800', 'summary > ' + q(td + '/q'))
        best = legacy_fn(TG, 'lists_best', 'LW=' + q(td), 'lists_best Wireguard0').stdout.strip()
    assert best == 'Wireguard1' and g == [['tunnel-guard', '-', 'VPN:Wireguard0', 'VPN:Wireguard1', '-', '-', 'switch', 'guard-fallback']], (g, best)
    sh = shadow(f, out)
    assert [r for r in sh if r[0] == '-' and r[1] == 'tunnel-guard'][0][3] == 'guard-owned-switch'
    # Stale quality data: unknown, never a guessed switch or match.
    old = f.p/'quality/samples.tsv'; os.utime(old, (now - 900, now - 900))
    txt = old.read_text().splitlines()
    old.write_text('\n'.join(l.replace(l.split('\t')[0], str(int(l.split('\t')[0]) - 900)) for l in txt) + '\n')
    r, out = snap(f); assert r.returncode == 0
    assert pick(rows(out), 'tunnel-guard', '-') == [['tunnel-guard', '-', 'unknown', 'unknown', '-', '-', 'none', 'none']]
    samples(f, {'Wireguard0': [0, 0, 0, 0], 'Wireguard1': [0, 0, 0, 0]})

    # ---- determinism, permutation, immutability, idempotence -----------------------------
    r, out = snap(f); base = (out/'legacy.tsv').read_text().splitlines()[1:]
    assert snap(f)[0].stdout == r.stdout and (out/'legacy.tsv').read_text().splitlines()[1:] == base
    (f.state/'manual-domains.txt').write_text('*.sub.test\nsmart.example\n')
    (f.etc/'route-engine/force-vpn.conf').write_text('*.sub.test  # wildcard\nx.example\n# owner list\n')
    f.persist.write_text('a.example\nx.example\n'); f.enabled.write_text('svc\tdomain-list0\tauto\n\n')
    r, out = snap(f); assert r.returncode == 0
    assert (out/'legacy.tsv').read_text().splitlines()[1:] == base, 'row order changed an observation'
    assert not trace.exists()

    # ---- a file replaced between fingerprint and copy -> unknown, not a stale copy -------
    # Hooks are shell FUNCTIONS (BusyBox runs cp as a built-in applet, a PATH shim would not fire).
    def hooked(hook, name):
        out = f.p/name; out.mkdir(mode=0o700)
        script = f'''. "{READ}"; . "{SNAP}"; . "{OBSERVE}"
        {hook}
        vward_routing_consistent_read "$1"'''
        return f.run(script, out), out
    mfile = str(f.state/'manual-domains.txt')
    # (1) replaced for good just before the copy: both the copy check and the final fingerprint see it.
    r, out = hooked(f'''cp() {{ case "$1" in */manual-domains.txt) printf 'changed.example\\n' > "$1" ;; esac; command cp "$@"; }}''', 'race')
    assert r.returncode == 3 and r.stdout == 'unknown\tchanged-during-read\n' and os.listdir(out) == [], (r.stdout, os.listdir(out))
    # (2) ABA: changed before the copy and put back (same size, content AND mtime, same inode) right after.
    # The final fingerprint is identical again; ONLY the check of the copy against the pre-copy fingerprint can notice.
    aba = f'''cp() {{ case "$1" in */manual-domains.txt)
            command cp -p "$1" "$1.keep"; printf 'XXXXXXXXXXXXXXXXXXXXXXX\\n' | head -c "$(wc -c < "$1")" > "$1"
            command cp "$@"; rc=$?; cat "$1.keep" > "$1"; touch -r "$1.keep" "$1"; rm -f "$1.keep"; return $rc ;; esac
          command cp "$@"; }}'''
    r, out = hooked(aba, 'race-aba')
    assert r.returncode == 3 and r.stdout == 'unknown\tchanged-during-read\n' and os.listdir(out) == [], (r.stdout, os.listdir(out))
    # ... and an observer input changing while the projections are read.
    real = f.p/'real-read.sh'; real.write_text(READ.read_text().replace('vward_routing_read() (', 'vward_routing_read_real() (', 1))
    wrapper = f'''. "{real}"; . "{SNAP}"; . "{OBSERVE}"
    n=0
    vward_routing_read() {{ n=$((n+1)); if [ "$n" = 2 ]; then printf 'late.example\\n' >> "$VRO_FILE"; fi; vward_routing_read_real "$@"; }}
    vward_routing_consistent_read "$1"'''
    out = f.p/'race2'; out.mkdir(mode=0o700)
    r = f.run(wrapper, out, env=dict(f.env, VRO_FILE=str(f.state/'manual-domains.txt')))
    assert r.returncode == 3 and r.stdout == 'unknown\tchanged-during-read\n' and os.listdir(out) == [], (r.stdout, r.stderr)
    (f.state/'manual-domains.txt').write_text('*.sub.test\nsmart.example\n')

    # ---- unreadable / invalid inputs: one mechanism-level unknown row ----------------------
    mf = f.state/'manual-domains.txt'; mf.unlink(); os.mkfifo(mf)
    r, out = snap(f); assert r.returncode == 0                           # soft input: snapshot survives
    assert pick(rows(out), 'route-engine') == [['route-engine', '-', 'unknown', 'unknown', '-', '-', 'none', 'none']]
    assert pick(rows(out), 'route-reconciler') and pick(rows(out), 'policy-sync')
    sh = shadow(f, out); assert [r for r in sh if r[1] == 'route-engine'][0][3] == 'legacy-unknown'
    mf.unlink(); mf.write_text('not a domain!\n')
    r, out = snap(f); assert pick(rows(out), 'route-engine') == [['route-engine', '-', 'unknown', 'unknown', '-', '-', 'none', 'none']]
    mf.write_text('*.sub.test\nsmart.example\n')
    ff = f.etc/'route-engine/force-vpn.conf'; ff.unlink(); os.symlink(f.dev, ff)
    r, out = snap(f); assert pick(rows(out), 'route-reconciler') == [['route-reconciler', '-', 'unknown', 'unknown', '-', '-', 'none', 'none']]
    ff.unlink(); ff.write_text('x.example\n')
    (f.p/'quality/samples.tsv').write_text('x' * (1024*1024 + 1))
    r, out = snap(f); assert r.returncode == 0
    assert pick(rows(out), 'tunnel-guard', '-') == [['tunnel-guard', '-', 'unknown', 'unknown', '-', '-', 'none', 'none']]
    samples(f, {'Wireguard0': [0, 0, 0, 0], 'Wireguard1': [0, 0, 0, 0]})
    # Corrupt running-config: every config-based mechanism is unknown, nothing is invented.
    f.cfg.write_text('error: refused\n')
    r, out = snap(f); assert r.returncode == 0
    for m in ('route-reconciler', 'policy-sync', 'services', 'tunnel-guard'):
        assert any(x[1] == '-' and x[2] == 'unknown' for x in pick(rows(out), m)), m
    assert not [x for x in pick(rows(out), 'policy-sync') if x[1] != '-']
    f.cfg.write_text(CFG)
    # Duplicate group declaration is ambiguous for the observers too.
    f.cfg.write_text(CFG + 'object-group fqdn Mine\n    include dup.example\n!\n')
    r, out = snap(f); assert any(x[1] == '-' and x[2] == 'unknown' for x in pick(rows(out), 'policy-sync'))
    f.cfg.write_text(CFG)
    # Lost / stale cache: no observation files at all.
    f.cfg.unlink(); r, out = snap(f, 'lost'); assert r.returncode == 3 and os.listdir(out) == []
    f.cfg.write_text(CFG)

    # ---- eight source combinations and 24 transitions on the observed snapshot ------------
    r, out = snap(f); assert r.returncode == 0
    inten, snp = (out/'intents.tsv').read_text(), (out/'snapshot.tsv').read_text()
    def combo(bits):
        t = snp
        for n, c in enumerate('MSA'):
            t = t.replace(f'source\t{c}\t1\tknown', f'source\t{c}\t{(bits >> n) & 1}\tknown')
        return f.audit(inten, t)
    res = {b: combo(b) for b in range(8)}
    assert sum(1 for b in range(8) for n in range(3) if combo(b ^ (1 << n)) == res[b ^ (1 << n)]) == 24
    legacy_once = (out/'legacy.tsv').read_text()
    assert snap(f)[0].returncode == 0 and (out/'legacy.tsv').read_text() == legacy_once   # legacy never depends on toggles

    # ---- resource limits (unchanged): 5000 manual lines -> unknown, no files --------------
    mf.write_text('d%d.example\n' % 0 + ''.join('d%d.example\n' % n for n in range(5000)))
    r, out = snap(f, 'limit'); assert r.returncode == 3 and r.stdout == 'unknown\tobserver-failed\n' and os.listdir(out) == [], r.stdout
    mf.write_text('*.sub.test\nsmart.example\n')
    # ---- nothing was written, no executor ran ----------------------------------------------
    assert not trace.exists()
    after = digest(f.p)
    watched = {k: v for k, v in after.items() if k.split('/')[0] in ('etc', 'state', 'cache', 'guard', 'quality', 'backup')}
    assert all(k in watched for k in watched)
    assert f.run('sentinel=1; . "$1"; . "$2"; . "$3"; . "$4"; [ "$sentinel" = 1 ]', READ, SNAP, OBSERVE, SHADOW).returncode == 0
print('RS6_OBSERVE=PASS: five observers, parity with real functions, wildcard, vpn substitution, fallback, race/copy, unknown, limits')
