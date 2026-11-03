#!/usr/bin/env python3
"""SIGKILL/TERM at composite boundaries; no router/network or weakened admission."""
import ast
import os
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path
import service_fixture as fixture
from doh_fixture import responder

tree = ast.parse((Path(__file__).with_name('check-ai-catalog-cycle.py')).read_text())
DNS = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'DNS')


def setup(p):
    s = fixture.Services(p); responder(p, s.env)
    ndmc = Path(s.env['VWARD_NDMC'])
    ndmc.write_text(ndmc.read_text().replace('if w[:1] == ["dns-proxy"]:', DNS + '\nif w[:1] == ["dns-proxy"]:'))
    (s.etc/'smartdns.conf').write_text('SMARTDNS_STORE=keenetic\nSMARTDNS_URL=https://dns.example.test/dns-query/synthetic\n')
    return s


def reboot(s):
    for p in (s.tmp/'change.lock', s.tmp/'edit.lock', s.tmp/'root/tmp'):
        shutil.rmtree(p, ignore_errors=True)
    (s.tmp/'root/tmp').mkdir(parents=True)


with tempfile.TemporaryDirectory() as td:
    s = setup(Path(td))
    (s.etc/'smartdns-wait').write_text('claude.ai\nother.example\n')
    helper = s.tmp/'fault-helper.sh'
    original = fixture.HELPER
    body = original.read_text()
    old = '                  [ "${3:-}" = keep ] || ai_wait del "$ai_id" ;;'
    assert body.count(old) == 1
    helper.write_text(body.replace(old, '                  [ "${3:-}" = keep ] || ai_wait del "$ai_id"\n                  kill -KILL $$ ;;'))
    try:
        fixture.HELPER = helper
        r = s.run('ai', 'claude.ai', 'vpn')
        assert r.returncode != 0
    finally:
        fixture.HELPER = original
    assert s.state.read_text() and (s.etc/'smartdns-wait').read_text() == 'other.example\n'
    reboot(s)
    r = s.run('ai', 'claude.ai', 'vpn')
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list((s.tmp/'backup/service-transactions').glob('*/pending'))
    assert s.cfg.read_text().count('object-group fqdn ') == 1

for sig, kill_child in ((signal.SIGKILL, False), (signal.SIGTERM, False), (signal.SIGKILL, True)):
    with tempfile.TemporaryDirectory() as td:
        s = setup(Path(td)); helper = s.tmp/'fault-helper.sh'
        pid, entered, resume = (s.tmp/n for n in ('pid', 'entered', 'resume'))
        original = fixture.HELPER
        helper.write_text(original.read_text().replace('    ai_journal_begin "$1" "$2" "${3:-}"',
                          f'    echo $$ > "{pid}"\n    ai_journal_begin "$1" "$2" "${{3:-}}"'))
        ndmc = Path(s.env['VWARD_NDMC']); b = ndmc.read_text()
        b = b.replace('def save():', f'''def fault_pause():
    if not cmd.startswith('dns-proxy https upstream '): return
    import time
    Path({str(entered)!r}).touch()
    while not Path({str(resume)!r}).exists(): time.sleep(0.01)
def save():''')
        b = b.replace('cfg.write_text("\\n".join(lines) + "\\n");', 'fault_pause(); cfg.write_text("\\n".join(lines) + "\\n");')
        ndmc.write_text(b)
        result = []
        try:
            fixture.HELPER = helper
            t = threading.Thread(target=lambda: result.append(s.run('ai', 'claude.ai', 'dns')))
            t.start(); deadline = time.monotonic()+20
            while not entered.exists() and t.is_alive() and time.monotonic()<deadline: time.sleep(0.01)
            assert entered.exists(), result
            os.kill(int(pid.read_text()), sig)
            if kill_child:
                for slot in (s.tmp/'backup/service-transactions').glob('*/children/*'):
                    os.kill(int(slot.name), signal.SIGKILL)
            fixture.HELPER = original
            # A live descendant still owns the write even if its AI parent died.
            r = s.run('ai', 'claude.ai', 'isp')
            assert r.returncode != 0 and 'service_recovery_required' in r.stdout, r.stdout
        finally:
            resume.touch(); fixture.HELPER = original
            if 't' in locals(): t.join(30)
        assert not t.is_alive() and result[0].returncode != 0
        deadline = time.monotonic()+10
        def active_children():
            return [p for p in (s.tmp/'backup/service-transactions').glob('*/children/*')
                    if fixture.process_state(p.name) not in (None, 'Z', 'X')]
        while active_children() and time.monotonic()<deadline:
            time.sleep(0.01)
        assert not active_children(), 'child did not leave'
        # The orphan external transport may outlive the killed registered shell.
        while 'https upstream' not in s.cfg.read_text() and time.monotonic()<deadline:
            time.sleep(0.01)
        assert 'https upstream' in s.cfg.read_text(), 'paused transport did not apply'
        reboot(s)
        before = s.cfg.read_bytes()
        r = s.run('ai', 'claude.ai', 'isp')
        assert r.returncode != 0 and s.cfg.read_bytes() == before, (sig, r.stdout, r.stderr, before, s.cfg.read_bytes())
        pending = list((s.tmp/'backup/service-transactions').glob('*/pending'))
        assert pending, 'an uncheckpointed DNS write must remain detectable'
        st = s.run('service-recover', 'status')
        assert 'info.dns=' in st.stdout and '|add|' in st.stdout, st.stdout + st.stderr
        # One explicit keep decision changes no router settings and retains private evidence.
        r = s.run('service-recover', pending[0].parent.name, 'accept')
        assert r.returncode == 0 and s.cfg.read_bytes() == before, r.stdout
        assert s.run('ai', 'claude.ai', 'isp').returncode == 0
        assert 'https upstream' not in s.cfg.read_text()
print('AI_INTERRUPTIONS=PASS checkpoint, live descendant, TERM, SIGKILL, reboot, retry')
