#!/usr/bin/env python3
"""Keenetic 5.1 / BusyBox: canonical body, portable sets, legacy creation evidence.

Synthetic addresses only. No network, router, admission bypass or external utility installation.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path
import service_fixture as fixture

source = fixture.HELPER.read_text()


def function(name):
    start = source.index(name + '() {')
    return source[start:source.index('\n}\n', start) + 3]


with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    left, right = p / 'left', p / 'right'
    for a, b, want in [('', '', ''), ('a\nb\n', '', 'a\nb\n'),
                       ('', 'a\n', ''), ('a\nb\n', 'a\nc\n', 'b\n')]:
        left.write_text(a); right.write_text(b)
        r = subprocess.run(['sh', '-c', function('service_difference') +
                            '\nservice_difference "$1" "$2"', 'test', str(left), str(right)],
                           text=True, capture_output=True)
        assert r.returncode == 0 and r.stdout == want, (a, b, r.stdout, r.stderr)
    right.unlink()
    r = subprocess.run(['sh', '-c', function('service_difference') +
                        '\nservice_difference "$1" "$2"', 'test', str(left), str(right)],
                       capture_output=True)
    assert r.returncode != 0, 'missing input must never become an empty difference'
    # Keep significant embedded quotes/escapes; strip only complete syntactic quotes.
    body = 'description "ChatGPT"\ndescription "A\\\\B"\ndescription A"B\nexclude owner.example\n'
    r = subprocess.run(['sh', '-c', function('service_canonical')+'\nservice_canonical'], input=body, text=True, capture_output=True)
    assert r.returncode == 0 and sorted(r.stdout.splitlines()) == sorted([
        'description ChatGPT', 'description "A\\\\B"', 'description A"B', 'exclude owner.example'])
    # Birth identity prevents PID reuse from being mistaken for the old writer.
    txn = p/'old'; txn.mkdir(); (txn/'pid').write_text(str(os.getpid()))
    proc = Path('/proc')/str(os.getpid())/'stat'
    birth = proc.read_text().split(') ',1)[1].split()[19]
    code = 'ai_writers_live(){ return 1; }\n' + function('svr_live') + '''
vward_pid_start_var(){ VA_PS="''' + birth + '''"; va_rest='S '; }
svr_live "$1"
'''
    for saved, expected in ((birth, 0), ('1', 1)):
        (txn/'pid_start').write_text(saved)
        r = subprocess.run(['sh', '-c', code, 'test', str(txn)], capture_output=True)
        assert r.returncode == expected, (saved, r.stderr)
    # Legacy format and a disappearing /proc entry: no leaked redirection error.
    (txn/'pid').unlink(); (txn/'pid_start').unlink(); (p/'123').mkdir()
    code = 'ai_writers_live(){ return 1; }\n'+function('svr_live').replace('/proc/[0-9]*', str(p)+'/[0-9]*')+'\nsvr_live "$1"'
    r = subprocess.run(['sh', '-c', code, 'test', str(txn)], capture_output=True)
    assert r.returncode == 1 and not r.stderr, r.stderr

with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td))
    # The normal path has no Smart DNS. Explicit tunnel must load its validator first.
    r = s.run('ai', 'claude.ai', 'vpn:Wireguard0', 'keep')
    assert r.returncode == 0, r.stdout + r.stderr
    claim = s.etc / 'services/owned/domain-list0'
    before = claim.read_text()
    # Real Keenetic readback removes only syntactic surrounding quotes.
    s.cfg.write_text(s.cfg.read_text().replace('description "Claude"', 'description Claude'))
    r = s.run('ai', 'claude.ai', 'vpn', 'keep')
    assert r.returncode == 0, r.stdout + r.stderr
    assert s.cfg.read_text().count('object-group fqdn domain-list0\n') == 1
    for edit in [('description Claude', 'description Owner'),
                 ('include claude.ai', 'exclude claude.ai'),
                 ('include claude.ai', 'include owner.example')]:
        original = s.cfg.read_text()
        s.cfg.write_text(original.replace(*edit))
        r = s.run('service', 'tunnel', 'claude.ai', 'Wireguard0')
        assert 'error=service_reference_only' in r.stdout, r.stdout
        assert claim.read_text() == before or claim.read_text().replace('description Claude', 'description "Claude"') == before
        s.cfg.write_text(original)

# Lost registration: an accepted private creation journal proves origin; similarity does not.
with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td))
    s.foreign()
    original = s.cfg.read_text()
    assert 'error=service_reference_only' in s.run('service', 'on', 'claude.ai', 'auto').stdout
    assert s.cfg.read_text() == original and not s.state.exists()
    # Exact authoritative creation image and postimage registration, as on the owner's router.
    body = 'description "Claude"\ninclude claude.ai\ninclude user.example\n'
    txn = s.tmp / 'backup/service-transactions.resolved/txn.Ab12Cd'
    txn.mkdir(parents=True, mode=0o700); txn.parent.chmod(0o700)
    for name, value in {'new.domain-list7': body, 'group.domain-list7': '',
                        'route.domain-list7': '', 'groups': 'domain-list7\n',
                        'after.enabled': 'claude.ai\tdomain-list7\tauto\n',
                        'enabled.absent': '', 'resolved': 'state=accepted:partial\n'}.items():
        (txn / name).write_text(value); (txn / name).chmod(0o600)
    s.cfg.write_text(original.replace('description "Claude"', 'description Claude')
                    .replace('domain-list7 ISP auto', 'domain-list7 Wireguard0 auto'))
    saved = s.etc / 'route-engine/domain-lists/domain-list7'
    saved.parent.mkdir(parents=True)
    saved.write_text('route=-\n' + 'doh=https upstream https://deleted.example/dns-query domain claude.ai\n')
    saved.chmod(0o600)
    before = s.cfg.read_bytes()
    assert 'error=service_reference_only' in s.run('service', 'on', 'claude.ai', 'auto').stdout
    assert s.cfg.read_bytes() == before and not s.state.exists()
    saved.write_text('route=-\n')
    r = s.run('ai', 'claude.ai', 'vpn', 'keep')
    assert r.returncode == 0, r.stdout + r.stderr
    assert s.state.read_text() == 'claude.ai\tdomain-list7\tauto\n'
    assert (s.etc / 'services/owned/domain-list7').exists()
    assert s.cfg.read_text().count('object-group fqdn ') == 1
    assert s.run('ai', 'claude.ai', 'vpn', 'keep').returncode == 0

# Owner's observed 03.11 case. domain-list3 is a selected slice only; it remains manual.
with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td))
    s.cat.write_text((fixture.ROOT / 'components/console/data/services-catalog.json').read_text())
    dev = Path(s.env['VWARD_DEVICE_CONFIG'])
    dev.write_text(dev.read_text().replace('Wireguard0', 'OpkgTun4'))
    domains = ['cdn.auth0.com', 'chatgpt.com', 'd.docs.live.net', 'files.oaiusercontent.com',
               'gpt3-openai.com', 'mobile.events.data.microsoft.com', 'oaistatic.com',
               'openai.com', 'openai.fund', 'openai.org']
    manual = ('object-group fqdn domain-list3\n    description Manual\n'
              '    include openai.com\n    include oaiusercontent.com\n'
              '    include openai.com.cdn.cloudflare.net\n'
              '    include openaicom-api-bdcpf8c6d2e9atf6.z01.azurefd.net\n!\n')
    s.cfg.write_text('interface OpkgTun4\n!\ndns-proxy\n'
                     '    route object-group domain-list3 OpkgTun4 auto\n'
                     '    route object-group domain-list24 OpkgTun4 auto\n!\n' + manual +
                     'object-group fqdn domain-list24\n    description ChatGPT\n' +
                     ''.join('    include ' + d + '\n' for d in domains) + '!\n')
    registrations = ('telegram.org\tdomain-list27\tauto\nyoutube.com\tdomain-list25\tauto\n'
                     'aistudio.google.com\tdomain-list0\tauto\ncanva.com\tdomain-list1\tauto\n'
                     'stitch.withgoogle.com\tdomain-list10\tauto\n')
    s.state.write_text(registrations)
    txn = s.tmp / 'backup/service-transactions/txn.Xs72Ii'
    txn.mkdir(parents=True, mode=0o700)
    for n, v in {'groups': 'domain-list24\n', 'group.domain-list24': '', 'route.domain-list24': '',
                 'new.domain-list24': 'description "ChatGPT"\n' + ''.join('include '+d+'\n' for d in domains),
                 'after.enabled': registrations + 'chatgpt.com\tdomain-list24\tauto\n',
                 'enabled': registrations, 'categories.absent': '', 'catalog.absent': '', 'undo': '',
                 'foreign.domain-list24': '', 'dns-risk.domain-list24': '', 'pending': ''}.items():
        (txn/n).write_text(v); (txn/n).chmod(0o600)
    before = s.cfg.read_bytes()
    st = s.run('service-recover', 'status')
    assert st.returncode == 0 and st.stderr == '', st.stdout + st.stderr
    assert 'domain-list24|10|0|absent|OpkgTun4|ChatGPT' in st.stdout, st.stdout
    (txn/'group.domain-list24').unlink()
    unknown = s.run('service-recover', 'status')
    assert unknown.returncode != 0 and 'result=checked' not in unknown.stdout, unknown.stdout
    (txn/'group.domain-list24').write_text('')
    assert s.run('service-recover', txn.name, 'accept').returncode == 0
    saved = s.etc / 'route-engine/domain-lists/domain-list24'; saved.parent.mkdir(parents=True)
    saved.write_text('route=-\n'); saved.chmod(0o600)
    r = s.run('ai', 'chatgpt.com', 'vpn', 'keep')
    assert r.returncode == 0, r.stdout + r.stderr
    assert s.cfg.read_bytes() == before
    assert s.state.read_text() == registrations + 'chatgpt.com\tdomain-list24\tauto\n'
    assert (s.etc / 'services/owned/domain-list24').is_file()
    assert not (s.etc / 'services/owned/domain-list3').exists()
    assert s.run('ai', 'chatgpt.com', 'vpn:OpkgTun4', 'keep').returncode == 0

assert 'comm -' not in source, 'all comm calls must be replaced, including refresh and restore'
print('SERVICE_PORTABLE=PASS')
