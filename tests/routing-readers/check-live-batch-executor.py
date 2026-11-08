#!/usr/bin/env python3
"""Batch executor on the actual installed NDMC seam (owner decision 08.11.2026).

1. A 40-domain service is ONE native batch: native reads per request do not
   grow with the number of commands, every command is sent once, committed.
2. Every step of the operation is pending in the journal BEFORE the first
   native command, and the journal lock is held by the live coordinator.
3. A command refused in the middle stops the batch: nothing after it is sent,
   the batch request stays pending, the operation is unknown, nothing saved,
   explicit compensation refuses the unresolved request (no blind inverse).
4. A lost reply whose command applied is unknown, never success.
Fixtures only; never a router.
"""
import json
import shlex
import shutil
from live_fixture import LiveFixture

DOMAINS = [f'd{i:02d}.example' for i in range(40)]


def many(f):
    cat = f.prefix/'opt/var/lib/vward/services/catalog.json'
    cat.write_text(json.dumps({'schema': 1, 'services': [
        {'id': 'svc', 'title': 'Service', 'category': 'ai', 'domains': DOMAINS},
        {'id': 'off', 'title': 'Off', 'category': 'ai', 'domains': ['off.example']}]}))


def wrap(f, body):
    """NDMC wrapper: BODY runs before the actual fixture with $2 = command."""
    real = shlex.quote(str(f.ndmc))
    w = f.p/'ndmc-wrapper'
    w.write_text('#!/bin/sh\n' + body + '\nexec ' + real + ' "$@"\n')
    w.chmod(0o755)
    f.env['VWARD_NDMC'] = str(w)


def calls(f):
    return f.calls.read_text().splitlines() if f.calls.exists() else []


def cold(f):
    # Same start as the process budget gate: a fresh first import.
    r = f.console('service', 'off', 'svc')
    assert r.returncode == 0, (r.stdout, r.stderr)
    shutil.rmtree(f.live)


def op(f):
    ops = [p for p in (f.live/'journal').iterdir() if p.name.startswith('r-')]
    return max(ops, key=lambda p: p.stat().st_mtime)


# 1. One batch for 40 domains (actual console: fresh catalog inputs).
with LiveFixture() as f:
    f.install_console()
    cold(f)
    many(f)
    base = len(calls(f))
    r = f.console('service', 'on', 'svc', 'Wireguard0')
    assert r.returncode == 0 and 'result=changed' in r.stdout, (r.returncode, r.stdout, r.stderr)
    big = op(f)
    assert (big/'state').read_text() == 'committed\n'
    c = [x.split('\t', 1)[1] for x in calls(f)[base:]]
    reads = c.count('show running-config')
    includes = [x for x in c if x.startswith('object-group fqdn domain-list') and ' include ' in x]
    assert sorted(x.rsplit(' ', 1)[1] for x in includes) == sorted(DOMAINS), includes
    assert len(set(includes)) == len(includes), 'a command was sent twice'
    # A cold first request (import + inputs state-set + the service batch).
    # Per-command reads would be >= 2 x 42; the batch keeps them constant.
    assert reads <= 12, ('native reads grow with the batch', reads)
    assert f.startup.read_bytes() == f.native.read_bytes()
    dto = json.loads((big/'prepared/outcome.json').read_text())
    assert dto['configured']['state'] == 'verified', dto['configured']

# 2. Pending before the first dispatch; journal lock held by the coordinator.
with LiveFixture() as f:
    probe = f.p/'probe'
    wrap(f, '''case $2 in 'object-group fqdn '*)
  [ -e ''' + shlex.quote(str(probe)) + ''' ] || {
    j=''' + shlex.quote(str(f.live/'journal/pend')) + '''
    for s in "$j"/step.*; do printf '%s %s\\n' "${s##*/}" "$(cat "$s/state")"; done > ''' + shlex.quote(str(probe)) + '''
    printf 'lock %s\\n' "$(cut -f1 ''' + shlex.quote(str(f.live/'journal/.lock/owner')) + ''' 2>/dev/null)" >> ''' + shlex.quote(str(probe)) + '''
  } ;;
esac''')
    r = f.invoke('vward_routing_live_service', 'pend', 'svc', 'vpn', 'VPN:Wireguard0', 'default', 0)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    seen = probe.read_text().splitlines()
    steps = sum(x.startswith('step\t') for x in (f.live/'journal/pend/plan').read_text().splitlines())
    states = [x for x in seen if x.startswith('step.')]
    assert len(states) == steps and all(x.endswith(' pending') for x in states), seen
    lock = [x for x in seen if x.startswith('lock ')]
    assert lock and lock[0] != 'lock ', ('journal lock not held during the batch', seen)

# 3. A refused command in the middle of the batch.
with LiveFixture() as f:
    f.install_console()
    cold(f)
    many(f)
    refused = 'object-group fqdn domain-list0 include ' + DOMAINS[5]
    wrap(f, 'case $2 in ' + shlex.quote(refused) + ') echo "Command::refused" ; exit 1 ;; esac')
    r = f.console('service', 'on', 'svc', 'Wireguard0')
    assert r.returncode != 0, (r.returncode, r.stdout, r.stderr)
    ref = op(f)
    assert (ref/'state').read_text() == 'unknown\n'
    sent = [x.split('\t', 1)[1] for x in calls(f)]
    assert refused not in sent  # the wrapper refused it before the fixture
    after = DOMAINS[6:]
    assert not any(x.endswith(' include ' + d) for x in sent for d in after), 'commands after the refusal were sent'
    pend = list(ref.glob('native.*/request.pending'))
    assert pend, 'refused batch request was resolved without proof'
    assert f.startup.read_bytes() != f.native.read_bytes() or 'domain-list0' not in f.startup.read_text()
    assert 'system configuration save' not in sent
    r = f.invoke('vward_routing_live_recover', ref.name, 'compensate')
    assert r.returncode != 0, ('compensation ran over an unresolved request', r.stdout)

# 4. Lost reply after the command applied: unknown, not success.
with LiveFixture() as f:
    lost = 'object-group fqdn domain-list0 include x.example'
    (f.p/'native-lost-reply').write_text(lost + '\n')
    r = f.invoke('vward_routing_live_service', 'lost', 'svc', 'vpn', 'VPN:Wireguard0', 'default', 0)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert (f.live/'journal/lost/state').read_text() == 'unknown\n'
    assert 'include x.example' in f.native.read_text()
    assert f.startup.read_bytes() != f.native.read_bytes()
print('LIVE_BATCH_EXECUTOR=PASS 40 commands one batch with constant native reads; all steps pending before dispatch under the held journal lock; mid-batch refusal stops unsent tail, pending kept, no compensation; lost reply unknown')
