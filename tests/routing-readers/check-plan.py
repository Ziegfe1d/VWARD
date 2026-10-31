#!/usr/bin/env python3
"""RS-7 stage 1: the planner is a pure function of one verified snapshot.

It proposes (never executes, never grants), blocks on every doubt, keeps ownership separate
from the name, honours the three mutually exclusive DNS modes and AGH recovery evidence,
and records a reason for every decision and refusal.
"""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

GEN = 'g-0123456789abcdef'
D1, D2 = 'new.example', 'other.example'

def audit_rows(snapshot_known='known', health='available', routes=(), intents=None, toggles=(1, 1, 1), src_known=('known',) * 3):
    """RS5 audit of a synthetic snapshot (real vward_routing_audit)."""
    intents = intents if intents is not None else [('M', 'm-aaaaaaaaaaaaaaaa', D1, 'exact', 'VPN:Wireguard0', 'default', 1)]
    i = ''.join('\t'.join(map(str, r)) + '\n' for r in intents)
    s = f'snapshot\t{GEN}\t{snapshot_known}\n'
    for c, t, k in zip('MSA', toggles, src_known):
        s += f'source\t{c}\t{t}\t{k}\n'
    s += f'health\tDNS\t{health}\nhealth\tAGH\t{health}\nhealth\tVPN:Wireguard0\t{health}\nhealth\tVPN:Wireguard1\t{health}\n'
    for r in routes:
        s += '\t'.join(r) + '\n'
    return i, s

def ctx(**kw):
    base = dict(dns_mode='agh', agh_recovery='none', writers='disabled', age='5', max_age='60')
    base.update(kw)
    return ''.join(f'{k}\t{v}\n' for k, v in base.items() if v is not None)

IDENT_V = 'm-aaaaaaaaaaaaaaaa\tintent\tM\tg-1\tc-1.1\tt-1\tnative-group\tverified\treference\n'
IDENT_R = IDENT_V.replace('verified', 'reference-only')
IDENT_U = IDENT_V.replace('verified', 'unknown')

with Fixture() as f:
    shim = f.p/'shim'; shim.mkdir(); trace = f.p/'trace'
    for name in ('ndmc', 'curl', 'nslookup', 'ip', 'iptables', 'ipset', 'wg', 'vward-console-config.sh', 'vward-route-engine.sh'):
        (shim/name).write_text(f'#!/bin/sh\necho {name} >> {trace}\nexit 99\n'); (shim/name).chmod(0o755)
    env = dict(f.env, PATH=str(shim) + ':' + os.environ['PATH'])

    def plan(audit, ident, shadow='', context=None, gen=GEN, env_=env):
        with tempfile.TemporaryDirectory() as td:
            ps = [Path(td)/n for n in ('a', 'i', 's', 'c')]
            for p, t in zip(ps, (audit, ident, shadow, context if context is not None else ctx())): p.write_text(t)
            return f.run('. "$1"; vward_routing_plan "$2" "$3" "$4" "$5" "$6"', PLAN, gen, *ps, env=env_)

    def one(r, dom=D1):
        assert r.returncode == 0, (r.stdout, r.stderr)
        rows = [l.split('\t') for l in r.stdout.splitlines()]
        got = [x for x in rows if x[0] == dom]
        assert len(got) == 1 and len(got[0]) == 9, (rows, dom)
        return got[0]

    def audited(**kw):
        i, s = audit_rows(**kw)
        return f.audit(i, s)

    review = audited()
    assert review.split('\t')[7] == 'review'
    # ---- the sound proposal, and what it still needs --------------------------------------
    x = one(plan(review, IDENT_V))
    assert x == [D1, 'add', 'VPN:Wireguard0', 'default', 'yes', 'denied:writers-disabled',
                 'recheck-generation,owner-proof,change-lock,journal-before-write', 'new-coverage-needed', GEN], x
    x = one(plan(review, IDENT_V, context=ctx(writers='enabled')))
    assert x[4] == 'yes' and x[5] == 'requires-approval' and 'granted' not in '\t'.join(x)   # never a grant

    # ---- every doubt blocks (reason is explicit) -------------------------------------------
    def blocked(reason, audit=review, ident=IDENT_V, shadow='', **kw):
        x = one(plan(audit, ident, shadow, ctx(**kw)))
        assert x[4] == 'no' and x[5] == 'denied:not-eligible' and x[6] == '-' and x[7] == reason, (reason, x)
        return x
    blocked('ownership-unproven', ident=IDENT_R)        # same name/domain, no proof
    blocked('ownership-unknown', ident=IDENT_U)
    blocked('ownership-unknown', ident='')              # ref missing from the identity table
    blocked('snapshot-stale', age='61')
    blocked('snapshot-age-unknown', age='unknown')
    blocked('snapshot-age-unknown', age=None)
    blocked('snapshot-age-unknown', max_age=None)
    blocked('dns-mode-unknown', dns_mode='unknown')
    blocked('dns-mode-unknown', dns_mode=None)
    blocked('dns-modes-conflict', dns_mode='both')      # AGH and dnsmasq must never be active together
    blocked('agh-recovery-pending', agh_recovery='pending')
    blocked('agh-recovery-unknown', agh_recovery='unknown')
    blocked('agh-recovery-pending', agh_recovery='pending', dns_mode='dnsmasq')   # evidence is never ignored
    # AGH recovery unknown does not block a mode that does not use AGH.
    assert one(plan(review, IDENT_V, context=ctx(dns_mode='native', agh_recovery='unknown')))[4] == 'yes'
    for mode in ('agh', 'dnsmasq', 'native'):
        assert one(plan(review, IDENT_V, context=ctx(dns_mode=mode)))[4] == 'yes', mode
    # Shadow findings: Services replaced an unknown target by "vpn"; a real mismatch; unknown RS state.
    sh = lambda cls, sev, v='diverge': f'{D1}\tservices\t{v}\t{cls}\t{sev}\tlow\tS\tS:s-1\trs=-|legacy=-\trs=-|legacy=-\t-\t-\t-\tr\n'
    blocked('service-target-defaulted', shadow=sh('service-target-defaulted', 'info'))
    blocked('shadow-target-mismatch', shadow=sh('target-mismatch', 'review'))
    blocked('shadow-unknown', shadow=sh('rs-unknown', 'info', 'unknown'))
    assert one(plan(review, IDENT_V, sh('expected-guard', 'info')))[4] == 'yes'   # an explained, protective difference
    # A wildcard-expanded domain that the snapshot does not know is reported, never planned.
    wild = f'ghost.sub.test\troute-engine\tdiverge\tlegacy-only-domain\treview\tmedium\t-\t-\trs=-|legacy=-\trs=-|legacy=-\t-\t-\t-\tdomain-missing-in-rs\n'
    g = one(plan(review, IDENT_V, wild), 'ghost.sub.test')
    assert g[1] == 'none' and g[4] == 'no' and g[7] == 'domain-not-in-snapshot'

    # ---- audit decisions that are never proposals ----------------------------------------------
    for audit, reason in (
        (audited(snapshot_known='unknown'), 'snapshot-or-source-unknown'),
        (audited(src_known=('unknown', 'known', 'known')), 'snapshot-or-source-unknown'),
        (audited(health='unknown'), 'dependency-unknown'),
        (audited(health='unavailable'), 'dependency-unavailable'),
        (audited(toggles=(0, 0, 0)), 'no-active-intent'),
        (audited(routes=[('route', 'r-1', D1, 'exact', 'VPN:Wireguard0', 'default', 'unknown', 'reference')]), 'already-covered'),
        (audited(intents=[('M', 'm-aaaaaaaaaaaaaaaa', D1, 'exact', 'VPN:Wireguard0', 'default', 1),
                          ('S', 's-bbbbbbbbbbbbbbbb', D1, 'exact', 'ISP', 'default', 1)]), 'conflicting-target-or-dns'),
    ):
        x = one(plan(audit, IDENT_V))
        assert x[1] == 'none' and x[4] == 'no' and x[7] == reason, (reason, x)
    # ISP vs another VPN, and Smart DNS vs default, are conflicts too (no hidden priority).
    x = one(plan(audited(intents=[('M', 'm-aaaaaaaaaaaaaaaa', D1, 'exact', 'VPN:Wireguard0', 'default', 1),
                                  ('A', 'a-cccccccccccccccc', D1, 'exact', 'VPN:Wireguard1', 'default', 1)]), IDENT_V))
    assert x[7] == 'conflicting-target-or-dns' and x[1] == 'none'
    x = one(plan(audited(intents=[('M', 'm-aaaaaaaaaaaaaaaa', D1, 'exact', 'VPN:Wireguard0', 'default', 1),
                                  ('A', 'a-cccccccccccccccc', D1, 'exact', 'VPN:Wireguard0', 'smartdns', 1)]), IDENT_V))
    assert x[7] == 'conflicting-target-or-dns'

    # ---- an unselected catalog row or two ACTIVE refs: the worst ownership wins ---------------------
    two = audited(intents=[('M', 'm-aaaaaaaaaaaaaaaa', D1, 'exact', 'VPN:Wireguard0', 'default', 1),
                           ('S', 's-bbbbbbbbbbbbbbbb', D1, 'exact', 'VPN:Wireguard0', 'default', 1)])
    S_V = IDENT_V.replace('m-aaaaaaaaaaaaaaaa', 's-bbbbbbbbbbbbbbbb').replace('\tM\t', '\tS\t')
    both_v = IDENT_V + S_V
    assert one(plan(two, both_v))[4] == 'yes'
    mixed = IDENT_V + S_V.replace('verified', 'reference-only')
    assert one(plan(two, mixed))[7] == 'ownership-unproven'

    # ---- 8 source combinations / 24 transitions: a toggled-off or unknown source never plans -------
    res = {}
    for bits in range(8):
        tg = tuple((bits >> n) & 1 for n in range(3))
        intents = [('M', 'm-aaaaaaaaaaaaaaaa', D1, 'exact', 'VPN:Wireguard0', 'default', 1)]
        res[bits] = plan(audited(intents=intents, toggles=tg), IDENT_V).stdout
        assert (one(plan(audited(intents=intents, toggles=tg), IDENT_V))[4] == 'yes') == bool(tg[0])
    assert sum(1 for b in range(8) for n in range(3) if res[b ^ (1 << n)] == res[b ^ (1 << n)]) == 24
    assert len(set(res.values())) == 2                                        # M on -> proposal, M off -> none

    # ---- generation / input discipline -----------------------------------------------------------------
    r = plan(review, IDENT_V, gen='g-ffffffffffffffff')
    assert r.returncode == 3 and r.stdout == 'unknown\tgeneration-mismatch\n'
    for bad in ('bad', 'g-12'):
        r = plan(review, IDENT_V, gen=bad); assert r.returncode == 2 and r.stdout == ''
    for badctx in (ctx() + 'dns_mode\tnative\n', 'dns_mode\tsmartdns\n', 'writers\tgranted\n', 'age\t-1\n', 'bogus\t1\n', 'age\t5\textra\n'):
        r = plan(review, IDENT_V, context=badctx); assert r.returncode == 2 and r.stdout == '', badctx
    r = plan(review + review, IDENT_V); assert r.returncode == 2 and r.stdout == ''           # duplicate domain
    r = plan(review.replace('review', 'approved'), IDENT_V); assert r.returncode == 2
    r = plan('x' * 10, IDENT_V); assert r.returncode == 2
    big = ''.join(f'd{i}.example\t-\t-\t-\t-\t-\t0\tinactive\tno-active-intent\t-\t{GEN}\tunknown\n' for i in range(1025))
    r = plan(big, ''); assert r.returncode == 2 and r.stdout == ''                             # 1024-domain bound
    r = f.run('. "$1"; vward_routing_plan "$2" /a /b /c', PLAN, GEN); assert r.returncode == 2
    r = f.run('. "$1"; vward_routing_plan "$2"', PLAN, GEN); assert r.returncode == 2

    # ---- determinism, permutation, purity ------------------------------------------------------------------
    r1 = plan(two, both_v, sh('expected-guard', 'info'))
    r2 = plan('\n'.join(reversed(two.splitlines())) + '\n', '\n'.join(reversed(both_v.splitlines())) + '\n', sh('expected-guard', 'info'),
              ctx().replace('age\t5\n', '') + 'age\t5\n')
    assert r1.returncode == 0 and r1.stdout == r2.stdout
    assert not trace.exists()
    assert f.run('sentinel=1; . "$1"; [ "$sentinel" = 1 ]', PLAN).returncode == 0

    # ---- the decision log: bounded, secret-free, nothing written -----------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        pf = Path(td)/'plan'; pf.write_text(r1.stdout)
        lg = f.run('. "$1"; vward_routing_plan_log "$2"', PLAN, pf)
        assert lg.returncode == 0 and lg.stdout.splitlines() == [f'PLAN|{D1}|add|yes|denied:writers-disabled|new-coverage-needed|{GEN}'], lg.stdout
        pf.write_text(r1.stdout.replace('add', 'move')); assert f.run('. "$1"; vward_routing_plan_log "$2"', PLAN, pf).returncode == 2
        pf.write_text(r1.stdout.replace('new-coverage-needed', 'https://dns.example/secret-token')); lg = f.run('. "$1"; vward_routing_plan_log "$2"', PLAN, pf)
        assert lg.returncode == 2 and lg.stdout == ''

    # ---- on the real coordinated snapshot: health is unknown today, so nothing is eligible ------------------
    out = f.p/'snap'; out.mkdir(mode=0o700)
    r = f.run('. "$1"; . "$2"; . "$4"; vward_routing_consistent_read "$3"', READ, SNAP, out, OBSERVE, env=env); assert r.returncode == 0, r.stdout
    gen = (out/'generation').read_text().strip()
    audit = f.audit((out/'intents.tsv').read_text(), (out/'snapshot.tsv').read_text())
    with tempfile.TemporaryDirectory() as td:
        a = Path(td)/'a'; a.write_text(audit)
        sh_ = f.run('. "$1"; vward_routing_shadow "$2" "$3" "$4" "$5"', SHADOW, gen, a, out/'identity.tsv', out/'legacy.tsv'); assert sh_.returncode == 0
        s = Path(td)/'s'; s.write_text(sh_.stdout); c = Path(td)/'c'; c.write_text(ctx())
        pl = f.run('. "$1"; vward_routing_plan "$2" "$3" "$4" "$5" "$6"', PLAN, gen, a, out/'identity.tsv', s, c, env=env)
    assert pl.returncode == 0, pl.stderr
    rows = [l.split('\t') for l in pl.stdout.splitlines()]
    assert rows and all(x[4] == 'no' and x[1] in ('none', 'add') for x in rows)
    assert not any(x[4] == 'yes' for x in rows), 'a plan was eligible although every dependency is unknown'
    assert not trace.exists()
print('RS7_PLAN=PASS: pure proposals, ownership/DNS-mode/AGH-recovery/freshness/shadow blocks, 8 states/24 transitions, log')
