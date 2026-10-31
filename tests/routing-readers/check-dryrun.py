#!/usr/bin/env python3
"""RS-7 stage 3: dry-run executor on a Keenetic stand-in (no real router, switch off by default).

PLAN -> PENDING -> simulated write -> DONE/FAILED/UNKNOWN -> RECOVERY for one service group,
with refusals, lost replies, foreign edits, SIGKILL at each step, repeats, locks and an AGH
step through the real control script against a fake AdGuard Home API.
"""
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

GEN = 'g-0123456789abcdef'
ROW = f'new.example\tadd\tVPN:Wireguard0\tdefault\tyes\tdenied:writers-disabled\trecheck-generation,owner-proof,change-lock,journal-before-write\tnew-coverage-needed\t{GEN}\n'
CFG = ('interface Wireguard0\n!\ndns-proxy\n    route object-group domain-list0 Wireguard0 auto\n!\n'
       'object-group fqdn domain-list0\n    include s.example\n    include x.example\n!\n'
       'object-group fqdn Mine\n    include m.example\n!\n')
STANDIN = r'''#!/usr/bin/env python3
# VWARD-DRYRUN-STANDIN: Keenetic emulator for tests, never a router.
import sys, time
from pathlib import Path
d = Path("@D@")
cmd = sys.argv[2]
with open(d / "calls", "a") as f: f.write(cmd + "\n")
cfg = d / "running.cfg"
if cmd == "show running-config":
    if (d / "show-fails").exists(): sys.exit(1)
    print(cfg.read_text(), end=""); sys.exit(0)
if (d / "slow-before").exists(): time.sleep(30)
if (d / "refuse").exists():
    print("Network::ObjectGroup: error: synthetic refusal"); sys.exit(0)
g, _, dom = cmd.split()[2:5]
lines = cfg.read_text().splitlines(); i = lines.index("object-group fqdn " + g); j = lines.index("!", i)
lines.insert(j, "    include " + dom)
if (d / "foreign").exists(): lines.insert(j, "    include user-added.example")
cfg.write_text("\n".join(lines) + "\n")
if (d / "show-fails-after").exists(): (d / "show-fails").touch()
if (d / "slow-after").exists(): time.sleep(30)
if (d / "lost").exists(): sys.exit(28)
sys.exit(0)
'''

with Fixture() as f:
    base = f.p
    shim = base/'shim'; shim.mkdir(); trace = base/'trace'
    for name in ('ndmc', 'curl', 'ip', 'wg', 'vward-console-config.sh'):
        (shim/name).write_text(f'#!/bin/sh\necho {name} >> {trace}\nexit 99\n'); (shim/name).chmod(0o755)
    emu = base/'emu'; emu.mkdir()
    stand = emu/'keenetic-standin'; stand.write_text(STANDIN.replace('@D@', str(emu))); stand.chmod(0o755)
    env = dict(f.env, PATH=str(shim) + ':' + os.environ['PATH'], VWARD_RS7_DRYRUN='1', VWARD_DRYRUN_NDMC=str(stand))
    planf = base/'plan.tsv'; planf.write_text(ROW)
    LIBS = f'. "{JOURNAL}"; . "{DRYRUN}"'
    def sh(script, *a, env_=None, timeout=20):
        return subprocess.run([*SHELL, '-c', LIBS + '\n' + script, 'x', *map(str, a)], env=env_ or env, text=True, capture_output=True, timeout=timeout)
    def reset():
        (emu/'running.cfg').write_text(CFG)
        for n in ('calls', 'refuse', 'lost', 'foreign', 'show-fails', 'show-fails-after', 'slow-before', 'slow-after'):
            (emu/n).unlink(missing_ok=True)
    def writes():
        return [l for l in ((emu/'calls').read_text().splitlines() if (emu/'calls').exists() else []) if l.startswith('object-group')]
    n = [0]
    def jdir():
        n[0] += 1; d = base/f'j{n[0]}'; d.mkdir(mode=0o700); return d
    def plan(j, op='op-1', ident='verified', owner='vward'):
        r = sh('vward_journal_plan "$1" "$2" "$3" new.example S "$4" "$5"', j, op, planf, owner, ident); assert r.returncode == 0, r.stderr
    def add(j, op='op-1', gen=GEN, group='domain-list0', dom='new.example', env_=None):
        return sh('vward_routing_dryrun_add "$1" "$2" "$3" "$4" "$5"', j, op, gen, group, dom, env_=env_)
    def state(j, op='op-1'):
        r = sh('vward_journal_status "$1"', j); return {l.split('\t')[0]: l.split('\t')[1] for l in r.stdout.splitlines()}.get(op)
    def gate(j): return sh('vward_journal_gate "$1"', j).returncode
    def has(dom): return f'    include {dom}\n' in (emu/'running.cfg').read_text()

    # ---- the switch and the stand-in guard: nothing runs, nothing is called ------------------
    reset(); j = jdir(); plan(j)
    for e in (dict(env, VWARD_RS7_DRYRUN='0'), {k: v for k, v in env.items() if k != 'VWARD_RS7_DRYRUN'},
              dict(env, VWARD_DRYRUN_NDMC=''), dict(env, VWARD_DRYRUN_NDMC='/opt/bin/ndmc'), dict(env, VWARD_DRYRUN_NDMC='relative'),
              dict(env, VWARD_DRYRUN_NDMC=str(shim/'ndmc')), dict(env, VWARD_DRYRUN_NDMC=str(shim/'curl'))):
        r = add(j, env_=e); assert r.returncode == 75, (r.returncode, r.stdout, r.stderr)
    unmarked = emu/'unmarked'; unmarked.write_text(STANDIN.replace('VWARD-DRYRUN-STANDIN', 'x')); unmarked.chmod(0o755)
    assert add(j, env_=dict(env, VWARD_DRYRUN_NDMC=str(unmarked))).returncode == 75
    lnk = emu/'link'; os.symlink(stand, lnk)
    assert add(j, env_=dict(env, VWARD_DRYRUN_NDMC=str(lnk))).returncode == 75
    assert not (emu/'calls').exists() and state(j) == 'plan'

    # ---- full cycle: PLAN -> PENDING -> write -> DONE --------------------------------------------
    r = add(j); assert r.returncode == 0 and 'result=done' in r.stdout, (r.stdout, r.stderr)
    assert has('new.example') and state(j) == 'done' and gate(j) == 0 and len(writes()) == 1
    # repeat of the same operation id: refused, nothing written again
    assert add(j).returncode == 75 and len(writes()) == 1
    # a new id for an already present domain: nothing to do, no write, no PENDING
    plan(j, 'op-2'); r = add(j, 'op-2'); assert r.returncode == 0 and 'result=unchanged' in r.stdout and len(writes()) == 1
    assert state(j, 'op-2') == 'plan'

    # ---- refused by the router: proven not applied -> FAILED, gate open --------------------------
    reset(); j = jdir(); plan(j); (emu/'refuse').touch()
    r = add(j); assert r.returncode == 1 and 'result=failed' in r.stdout and not has('new.example')
    assert state(j) == 'failed' and gate(j) == 0

    # ---- lost reply, change applied -> DONE (read-back decides, no retry) -------------------------
    reset(); j = jdir(); plan(j); (emu/'lost').touch()
    r = add(j); assert r.returncode == 0 and 'write_rc=28' in r.stdout and 'result=done' in r.stdout and len(writes()) == 1

    # ---- lost reply AND read-back impossible -> UNKNOWN, gate closed, recovery later ---------------
    reset(); j = jdir(); plan(j); (emu/'lost').touch(); (emu/'show-fails-after').touch()
    r = add(j); assert r.returncode == 3 and 'result=unknown' in r.stdout
    assert state(j) == 'unknown' and gate(j) == 75
    plan(j, 'op-2')
    calls_before = (emu/'calls').read_text()
    r = sh('vward_routing_dryrun_add "$1" op-2 "$2" Mine other.example', j, GEN); assert r.returncode == 75   # gate closed
    assert (emu/'calls').read_text() == calls_before, 'a closed gate must stop the executor before it even reads the router'
    assert len(writes()) == 1                                                  # never a retry, never another write
    r = sh('vward_routing_dryrun_recover "$1"', j); assert state(j) == 'unknown'   # still unreadable
    (emu/'show-fails').unlink()
    r = sh('vward_routing_dryrun_recover "$1"', j); assert r.returncode == 0 and state(j) == 'done' and gate(j) == 0

    # ---- someone else changed the same group meanwhile -> UNKNOWN, stays blocked, no compensation ----
    reset(); j = jdir(); plan(j); (emu/'foreign').touch()
    r = add(j); assert r.returncode == 3 and state(j) == 'unknown' and gate(j) == 75
    assert has('user-added.example') and has('new.example')               # the user's edit is never undone
    sh('vward_routing_dryrun_recover "$1"', j); assert state(j) == 'unknown' and len(writes()) == 1

    # ---- SIGKILL before the write lands / after it lands -> recovery by evidence -------------------
    for flag, want in (('slow-before', 'failed'), ('slow-after', 'done')):
        reset(); j = jdir(); plan(j); (emu/flag).touch()
        p = subprocess.Popen([*SHELL, '-c', LIBS + '\nvward_routing_dryrun_add "$1" op-1 "$2" domain-list0 new.example', 'x', str(j), GEN], env=env)
        for _ in range(200):
            if (j/'op-1/pending').exists() and (emu/'calls').exists() and writes(): break
            time.sleep(0.05)
        time.sleep(0.3); os.kill(p.pid, signal.SIGKILL); p.wait()
        for c in subprocess.run(['pgrep', '-f', str(stand)], capture_output=True, text=True).stdout.split():
            os.kill(int(c), signal.SIGKILL)
        (emu/flag).unlink()
        assert state(j) == 'pending' and gate(j) == 75, state(j)
        r = sh('vward_routing_dryrun_recover "$1"', j); assert state(j) == want, (flag, state(j), r.stderr)
        assert gate(j) == 0

    # ---- two executors at once: exactly one writes -------------------------------------------------
    reset(); j = jdir(); plan(j, 'op-a'); plan(j, 'op-b'); (emu/'slow-after').touch()
    ps = [subprocess.Popen([*SHELL, '-c', LIBS + f'\nvward_routing_dryrun_add "$1" {op} "$2" domain-list0 {d}; echo "rc=$?" > "$1/{op}.rc"', 'x', str(j), GEN], env=env)
          for op, d in (('op-a', 'a1.example'), ('op-b', 'b1.example'))]
    time.sleep(3); (emu/'slow-after').unlink()
    for c in subprocess.run(['pgrep', '-f', str(stand)], capture_output=True, text=True).stdout.split():
        os.kill(int(c), signal.SIGTERM)
    for p in ps: p.wait(timeout=60)
    assert len(writes()) == 1, writes()
    rcs = sorted((j/f'{op}.rc').read_text().strip() for op in ('op-a', 'op-b'))
    assert 'rc=75' in rcs, rcs

    # ---- not eligible / foreign ownership / stale generation / no group: refused before any write ----
    for kw, extra in ((dict(ident='reference-only'), {}), (dict(owner='manual'), {}), ({}, dict(gen='g-ffffffffffffffff')),
                      ({}, dict(group='missing')), ({}, dict(group='Mine; reboot'))):
        reset(); j = jdir(); plan(j, **kw)
        r = add(j, **extra); assert r.returncode in (2, 75), (kw, extra, r.returncode)
        assert writes() == [] and state(j) == 'plan'
    reset(); (emu/'running.cfg').write_text(CFG + 'object-group fqdn domain-list0\n    include dup.example\n!\n')
    j = jdir(); plan(j); assert add(j).returncode == 75 and writes() == []      # duplicated group = no image

    # ---- AGH step: real control script, fake AdGuard Home API, journal around it -------------------------
    fx = ast.parse((ROOT / 'tests/repository/check-ads-agh-smartdns.py').read_text())
    fake_curl = next(ast.literal_eval(n.value) for n in fx.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'FAKE_CURL' for t in n.targets))
    fake_curl = fake_curl.replace('else: st["up"] = body["upstream_dns"]; res = {}',
        'else:\n        st["up"] = body["upstream_dns"]; res = {}\n        if st.get("user_edit_after_post") and st["posts"] == 1: st["up"] = st["up"] + st["user_edit_after_post"]')
    assert 'user_edit_after_post' in fake_curl
    agh = base/'agh'; agh.mkdir(); st = agh/'state.json'
    curl = agh/'curl'; curl.write_text(fake_curl.replace('@STATE@', str(st))); curl.chmod(0o755)
    etc = agh/'etc'; etc.mkdir(); auth = etc/'agh-api.auth'; auth.write_text('admin:pw\n'); auth.chmod(0o600)
    (agh/'root/tmp').mkdir(parents=True)
    lib = (ROOT/'components/ads-privacy-guard/lib/vward-ads-privacy-common.sh').read_text()
    patched = agh/'lib.sh'; patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    aenv = dict(env, VWARD_ADS_LIB=str(patched), VWARD_ADS_ETC=str(etc), VWARD_ADS_STATE=str(agh/'state'), VWARD_ADS_LOG_DIR=str(agh/'log'),
                VWARD_ADS_JQ=shutil.which('jq'), VWARD_ADS_CURL=str(curl), VWARD_ADS_AGH_AUTH_FILE=str(auth),
                AGH_API_BASE='http://192.0.2.1:3001/control', VWARD_ROOT_PREFIX=str(agh/'root'),
                VWARD_ADMISSION_LIB=str(ROOT/'components/runtime/lib/vward-runtime-admission.sh'), TMPDIR=str(agh))
    D = 'https://tr.example:8443/dns-query/x'
    UP = [f'[/new.example/]{D}', '9.9.9.9']
    CONTROL = ROOT/'components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh'
    def agh_image(path):
        Path(path).write_text('\n'.join(sorted(json.loads(st.read_text())['up'])) + '\n')
    for edit, want in ((None, 'done'), (['[/user.example/]https://u.example/q'], 'unknown')):
        st.write_text(json.dumps({'up': UP, **({'user_edit_after_post': edit} if edit else {})}))
        j = jdir(); plan(j)
        pre = base/'agh-pre'; agh_image(pre)
        post = base/'agh-post'; post.write_text('9.9.9.9\n')
        assert sh('vward_journal_begin "$1" op-1 "$2" "$3" "$4" agh:take,dryrun', j, GEN, pre, post).returncode == 0
        inc = base/'inc'; inc.write_text('new.example\n'); rec = base/f'rec{edit is None}'; rec.mkdir(mode=0o700)
        r = subprocess.run(['sh', str(CONTROL), 'agh', 'smartdns-take', str(inc), str(rec/'pairs.tsv')],
                           env=dict(aenv, VWARD_AGH_RECOVERY_DIR=str(rec)), text=True, capture_output=True)
        now = base/'agh-now'; agh_image(now)
        assert sh('vward_journal_finish "$1" op-1 "$2"', j, now).returncode == 0
        assert state(j) == want, (edit, state(j), r.stdout)
        if edit:   # the user's row survives, the evidence is kept, the gate stays closed
            assert '[/user.example/]https://u.example/q' in json.loads(st.read_text())['up'] and gate(j) == 75
            assert (rec/'dns.before.json').is_file() and (j/'op-1/pre').is_file()

    # ---- nothing real was ever called; no secret in any journal --------------------------------------------
    assert not trace.exists(), 'a real executor or transport was called'
    # Records are closed tokens; only the private pre-image (0600 in a 0700 directory, like the
    # existing AGH recovery evidence) may hold upstream URLs - it is never logged or published.
    for d in base.glob('j*'):
        for rec in d.rglob('*'):
            if not rec.is_file(): continue
            if rec.name == 'pre':
                assert rec.stat().st_mode & 0o077 == 0 and rec.parent.stat().st_mode & 0o077 == 0
            else:
                assert 'tr.example' not in rec.read_text(errors='ignore') and '//' not in rec.read_text(errors='ignore'), rec
    assert f.run('sentinel=1; . "$1"; . "$2"; [ "$sentinel" = 1 ]', JOURNAL, DRYRUN).returncode == 0
print('RS7_DRYRUN=PASS: stand-in only, switch off by default, done/failed/unknown/recovery, lost reply, foreign edit, SIGKILL, race, AGH')
