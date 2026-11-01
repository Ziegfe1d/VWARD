#!/usr/bin/env python3
"""Real service writer: preserve ownership and state across disk/transport faults."""
import json
import os
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path
import service_fixture as fixture

errors = []
for case in ('new-owner-edit', 'new-state-write', 'off-save', 'off-dns', 'unknown-rollback', 'owner-local', 'postimage-owner'):
    with tempfile.TemporaryDirectory() as d:
        s = fixture.Services(Path(d))
        original_helper = fixture.HELPER
        if case == 'new-owner-edit':
            Path(str(s.cfg) + '.edit-on-save').touch()
        elif case in ('new-state-write', 'unknown-rollback'):
            marker = s.tmp / 'fail-mv'
            marker.touch()
            prefix = ('mv() { case "$*" in *"' + str(s.state) + '"*) '
                      'if [ -e "' + str(marker) + '" ]; then rm -f "' + str(marker) + '"; return 1; fi;; esac; command mv "$@"; }\n')
            if case == 'unknown-rollback':
                prefix = prefix.replace('return 1;', 'touch "' + str(s.tmp / 'config-error') + '"; return 1;')
                ndmc = Path(s.env['VWARD_NDMC'])
                ndmc.write_text(ndmc.read_text().replace('text = cfg.read_text()',
                    f'if cmd == "show running-config" and Path({str(s.tmp / "config-error")!r}).exists():\n'
                    f'    Path({str(s.tmp / "config-error")!r}).unlink(); print("error: snapshot unavailable"); sys.exit(0)\n'
                    'text = cfg.read_text()'))
            helper = s.tmp / 'helper.sh'
            helper.write_text(original_helper.read_text().replace('ETC=', prefix + 'ETC=', 1))
            fixture.HELPER = helper
        elif case == 'owner-local':
            once = s.tmp / 'owner-once'
            once.touch()
            ndmc = Path(s.env['VWARD_NDMC'])
            ndmc.write_text(ndmc.read_text().replace('if cmd == "system configuration save":',
                f'if cmd == "system configuration save" and Path({str(once)!r}).exists():\n'
                f'    Path({str(once)!r}).unlink()\n'
                f'    Path({str(s.etc / "services/categories.tsv")!r}).write_text("ai\\tWireguard1\\n"); print("error: refused"); sys.exit(0)\n'
                'if cmd == "system configuration save":'))
        elif case == 'postimage-owner':
            marker = s.tmp / 'commit-once'
            marker.touch()
            prefix = ('rm() { case "$*" in */pending) if [ -e "' + str(marker) + '" ]; then command rm -f "' + str(marker) + '"; '
                      'echo "manual.example\tdomain-list9\tauto" >> "' + str(s.state) + '"; return 1; fi;; esac; command rm "$@"; }\n')
            helper = s.tmp / 'helper.sh'
            helper.write_text(original_helper.read_text().replace('ETC=', prefix + 'ETC=', 1))
            fixture.HELPER = helper
        else:
            assert s.run('service', 'on', 'claude.ai', 'auto').returncode == 0
            before = s.cfg.read_text()
            state = s.state.read_text()
            if case == 'off-dns':
                saved = s.etc / 'route-engine/domain-lists/domain-list0'
                with saved.open('a') as f: f.write('agh=claude.ai\thttps://dns.example/dns-query\n')
                ads = s.tmp / 'ads'
                ads.write_text('#!/bin/sh\n[ "$2" != smartdns-put ] || cp "$3" "' + str(s.tmp / 'agh-state') + '"\necho CONTROL=PASS\n')
                ads.chmod(0o755)
                s.env['VWARD_ADS_CONTROL_BIN'] = str(ads)
            # The bypass save succeeds; reject the save after group deletion.
            ndmc = Path(s.env['VWARD_NDMC'])
            ndmc.write_text(ndmc.read_text().replace('if cmd == "system configuration save":',
                'if cmd == "system configuration save" and "object-group fqdn domain-list0" not in cfg.read_text():\n'
                '    print("error: save refused"); sys.exit(0)\nif cmd == "system configuration save":'))
        try:
            is_off = case in ('off-save', 'off-dns')
            r = s.run('service', 'off' if is_off else 'on', 'claude.ai', *(() if is_off else ('auto',)))
        finally:
            fixture.HELPER = original_helper
        if r.returncode == 0:
            errors.append(case + ': fault reported success')
        if case == 'new-owner-edit':
            if 'owner.example' not in s.cfg.read_text():
                errors.append(case + ': cleanup deleted owner edit')
        elif case == 'new-state-write':
            if 'object-group fqdn domain-list0' in s.cfg.read_text():
                errors.append(case + ': orphan group after failed state commit')
        elif case == 'owner-local':
            path = s.etc / 'services/categories.tsv'
            if not path.exists() or path.read_text() != 'ai\tWireguard1\n':
                errors.append(case + ': rollback erased untouched owner setting')
        elif case == 'postimage-owner':
            if not s.state.exists() or 'manual.example\tdomain-list9\tauto\n' not in s.state.read_text():
                errors.append(case + ': rollback overwrote unexpected local postimage')
            if not list((s.tmp / 'backup/service-transactions').glob('*/pending')):
                errors.append(case + ': overwritten local state recovery lost')
        elif case in ('off-dns', 'unknown-rollback'):
            pending = list((s.tmp / 'backup/service-transactions').glob('*/pending'))
            if 'error=rollback_incomplete' not in r.stdout or not pending:
                errors.append(case + ': unknown/DNS rollback falsely completed')
            if case == 'unknown-rollback' and 'object-group fqdn domain-list0' not in s.cfg.read_text():
                errors.append(case + ': unknown snapshot authorized deletion')
            if case == 'off-dns':
                assert (s.tmp / 'agh-state').read_text() == 'claude.ai\thttps://dns.example/dns-query\n'
                assert s.cfg.read_text() == before and s.state.read_text() == state
        elif s.cfg.read_text() != before or s.state.read_text() != state:
            errors.append(case + ': lost group/route/state')

# Kill/TERM and contention use a barrier at the transport boundary, after one
# real mutation. The product helper, locks and persistent journal stay real.
for case in ('term', 'kill-reboot', 'concurrent', 'stage-write', 'catalog-write', 'journal-write', 'restore-write'):
    with tempfile.TemporaryDirectory() as d:
        s = fixture.Services(Path(d))
        assert s.run('service', 'on', 'claude.ai', 'auto').returncode == 0
        before, state = s.cfg.read_text(), s.state.read_bytes()
        if case == 'restore-write':
            Path(s.env['VWARD_SERVICES_FETCHED']).write_text(json.dumps(s.catalog))
        newer = json.loads(json.dumps(s.catalog))
        newer['services'][0]['domains'].append('new.example')
        s.served.write_text(json.dumps(newer))
        original_helper = fixture.HELPER
        helper = s.tmp / 'fault-helper.sh'
        pidfile, entered, resume = (s.tmp / n for n in ('pid', 'entered', 'resume'))
        prefix = '[ -e "' + str(pidfile) + '" ] || echo $$ > "' + str(pidfile) + '"\n'
        if case in ('stage-write', 'catalog-write', 'restore-write'):
            dest = '*/catalog.new' if case == 'stage-write' else str(s.tmp / 'fetched.json')
            marker = s.tmp / 'mv-once'
            marker.touch()
            prefix += ('mv() { case "$2" in ' + dest + ') if [ -e "' + str(marker) +
                       '" ]; then rm -f "' + str(marker) + '"; return 1; fi;; esac; command mv "$@"; }\n')
            if case == 'restore-write':
                # A rename can apply before its reply fails; restoring the old
                # catalog then encounters a real local copy refusal.
                prefix = prefix.replace('return 1;', 'command mv "$@"; return 1;')
                prefix += 'cp() { case "$*" in *fetched.json.restore*) return 1;; esac; command cp "$@"; }\n'
        elif case == 'journal-write':
            prefix += r'''printf() { case "$1" in 'no object-group fqdn %s include %s\n') return 1;; esac; command printf "$@"; }
'''
        helper.write_text(original_helper.read_text().replace('ETC=', prefix + 'ETC=', 1))
        fixture.HELPER = helper
        result = []
        try:
            if case in ('term', 'kill-reboot', 'concurrent'):
                ndmc = Path(s.env['VWARD_NDMC'])
                body = ndmc.read_text()
                pause = ('\ndef fault_pause():\n'
                         '    if cmd != "object-group fqdn domain-list0 include new.example": return\n'
                         f'    Path({str(entered)!r}).touch()\n'
                         f'    while not Path({str(resume)!r}).exists():\n'
                         '        import time; time.sleep(0.01)\n')
                body = body.replace('def save():', pause + '\ndef save():')
                body = body.replace('cfg.write_text("\\n".join(lines) + "\\n");',
                                    'cfg.write_text("\\n".join(lines) + "\\n"); fault_pause();')
                ndmc.write_text(body)
                worker = threading.Thread(target=lambda: result.append(s.run('services-refresh', 'run')))
                worker.start()
                deadline = time.monotonic() + 25
                while not entered.exists() and worker.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert entered.exists(), 'transport barrier not reached'
                if case == 'concurrent':
                    second = s.run('service', 'off', 'claude.ai')
                    assert second.returncode != 0 and 'error=route_change_busy' in second.stdout, second.stdout
                else:
                    os.kill(int(pidfile.read_text()), signal.SIGTERM if case == 'term' else signal.SIGKILL)
                resume.touch()
                worker.join(30)
                assert not worker.is_alive() and result, 'writer did not finish'
                r = result[0]
            else:
                r = s.run('services-refresh', 'run')
            pending = list((s.tmp / 'backup/service-transactions').glob('*/pending'))
            if case == 'concurrent':
                assert r.returncode == 0 and 'include new.example' in s.cfg.read_text(), r.stdout
            elif case in ('kill-reboot', 'restore-write'):
                assert r.returncode != 0 and pending, 'durable recovery lost: ' + r.stdout
                recovery = pending[0].parent
                evidence = {p.name: p.read_bytes() for p in recovery.iterdir() if p.is_file()}
                assert (recovery.stat().st_mode & 0o077) == 0
                # Model reboot by dropping volatile admission/edit/change locks only.
                for p in (s.tmp / 'change.lock', s.tmp / 'edit.lock', s.tmp / 'root/tmp'):
                    shutil.rmtree(p, ignore_errors=True)
                (s.tmp / 'root/tmp').mkdir(parents=True, exist_ok=True)
                current = s.cfg.read_bytes()
                for _ in range(2):
                    retry = s.run('service', 'off', 'claude.ai')
                    assert retry.returncode != 0 and 'error=service_recovery_required' in retry.stdout, retry.stdout
                    assert s.cfg.read_bytes() == current
                    assert {p.name: p.read_bytes() for p in recovery.iterdir() if p.is_file()} == evidence
            else:
                assert r.returncode != 0 and not pending, case + ': rollback/recovery mismatch: ' + r.stdout + '\nCFG=' + s.cfg.read_text() + '\nFILES=' + repr({p.name:p.read_text() for p in pending[0].parent.iterdir() if p.is_file()} if pending else {})
                assert s.cfg.read_text() == before and s.state.read_bytes() == state, case + ': partial commit'
                assert not (s.tmp / 'fetched.json').exists()
        finally:
            resume.touch()
            fixture.HELPER = original_helper
if errors:
    raise SystemExit('SERVICE_FAULTS=FAIL: ' + '; '.join(errors))
print('SERVICE_FAULTS=PASS')
