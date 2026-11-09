#!/usr/bin/env python3
"""Read-only repeat fast path (owner decision 08.11.2026), actual console.

A repeat of the last converged request answers "unchanged" with ONE native
read, no journal operation, no scratch and no write. Every condition that
could change the full-path answer makes it decline, and the full coordinator
then decides exactly as before: foreign native edit, decision edit, a new or
unknown journal operation, updater barrier, installed code change, tunnel
health change, damaged receipt, and an off whose choice is not VPN (answered
by the full path without any backend read). Fixtures only; never a router.
"""
import shutil
from live_fixture import LiveFixture


def calls(f):
    return f.calls.read_text().splitlines() if f.calls.exists() else []


def state(f):
    j = f.live/'journal'
    return sorted(p.name for p in j.iterdir()), (f.live/'decision').joinpath('choices.tsv').read_bytes(), f.native.read_bytes()


def converge(f):
    f.install_console()
    r = f.console('service', 'off', 'svc'); assert r.returncode == 0, (r.stdout, r.stderr)
    shutil.rmtree(f.live)
    for target in ('Wireguard1', 'Wireguard0'):
        r = f.console('service', 'on', 'svc', target)
        assert r.returncode == 0 and 'result=changed' in r.stdout, (target, r.stdout, r.stderr)
    assert (f.live/'.converged').exists(), 'verified commit left no convergence receipt'


def fast(f):
    """Repeat; return (result line, native calls made, journal/scratch changed?)."""
    before = state(f); n = len(calls(f))
    r = f.console('service', 'on', 'svc', 'Wireguard0')
    made = [c.split('\t', 1)[1] for c in calls(f)[n:]]
    return r, made, state(f) != before


def declines(f, setup, expect_rc=0, label=''):
    setup()
    cv = f.live/'.converged'
    ino = cv.stat().st_ino if cv.exists() else None
    r = f.console('service', 'on', 'svc', 'Wireguard0')
    if expect_rc == 0:
        assert r.returncode == 0, (label, r.stdout, r.stderr)
        # Only the full coordinator rewrites (new inode) or withdraws the
        # receipt; the read-only fast path never touches it.
        assert not (cv.exists() and cv.stat().st_ino == ino), (label, 'fast path answered')
    else:
        assert r.returncode != 0, (label, 'fast path answered over a refusal', r.stdout)
    return r


# 1. Converged repeat: one read, nothing written.
with LiveFixture() as f:
    converge(f)
    r, made, changed = fast(f)
    assert r.returncode == 0 and 'result=unchanged' in r.stdout, (r.stdout, r.stderr)
    assert made.count('show running-config') == 1, made
    assert not any(not c.startswith('show ') for c in made), ('fast path wrote', made)
    assert not changed, 'fast path changed journal (incl. scratch)/decision/native state'

    # 2. Every declining condition hands the request to the full path.
    # Damaged receipt.
    cv = f.live/'.converged'
    declines(f, lambda: cv.write_text(cv.read_text().replace('generation\tg-', 'generation\tg-0', 1)), label='receipt')
    r, made, _ = fast(f)  # the full path re-recorded it
    assert 'result=unchanged' in r.stdout and made.count('show running-config') == 1, (r.stdout, made)

    # Tunnel health change (Wireguard0 unknown -> context differs).
    marker = f.p/'interface-unknown-Wireguard1'
    def health():
        marker.write_text('x')
    r = declines(f, health, label='health')
    marker.unlink()

with LiveFixture() as f:
    converge(f)
    # Foreign native edit inside the own group.
    def foreign():
        t = f.native.read_text().replace('object-group fqdn domain-list1\n', 'object-group fqdn domain-list1\n    include owner-edit.example\n', 1)
        assert t != f.native.read_text(); f.native.write_text(t)
    declines(f, foreign, expect_rc=1, label='foreign-native')
    assert 'include owner-edit.example' in f.native.read_text(), 'foreign include lost'

with LiveFixture() as f:
    converge(f)
    # Updater barrier: the full path refuses; the fast path must not answer.
    (f.prefix/'tmp/vward-update-requested').write_text('x\n')
    declines(f, lambda: None, expect_rc=1, label='updater')
    (f.prefix/'tmp/vward-update-requested').unlink()

with LiveFixture() as f:
    converge(f)
    # A new unknown journal operation (crashed request): full path refuses.
    def unknown_op():
        src = sorted(p for p in (f.live/'journal').iterdir() if p.name.startswith('r-'))[-1]
        dst = f.live/'journal'/'r-crashed'
        shutil.copytree(src, dst)
        (dst/'state').write_text('unknown\n')
        (dst/'quiet').unlink(missing_ok=True)
    declines(f, unknown_op, expect_rc=1, label='journal')

with LiveFixture() as f:
    converge(f)
    # Installed code change.
    lib = f.prefix/'opt/lib/vward/vward-routing-plan.sh'
    declines(f, lambda: lib.write_text(lib.read_text() + '\n# changed\n'), label='code')

with LiveFixture() as f:
    converge(f)
    # Decision edit (another service's choice) declines before any read.
    ch = f.live/'decision/choices.tsv'
    declines(f, lambda: ch.write_text(ch.read_text() + 'service\tother\t1\tauto\t-\t-\t1\n'), label='decision')

with LiveFixture() as f:
    converge(f)
    r = f.console('service', 'off', 'svc'); assert r.returncode == 0 and 'result=changed' in r.stdout
    n = len(calls(f))
    r = f.console('service', 'off', 'svc')
    made = calls(f)[n:]
    assert r.returncode == 0 and 'result=unchanged' in r.stdout, (r.stdout, r.stderr)
    assert made == [], ('off of a non-VPN choice probed the backend', made)
print('LIVE_REPEAT_FAST_PATH=PASS converged repeat: one read, no write/journal/scratch; receipt/health/foreign native/updater/unknown journal/code/decision changes take the full path; off of non-VPN choice reads nothing')
