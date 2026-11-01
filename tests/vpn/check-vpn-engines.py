#!/usr/bin/env python3
"""VPN engines: Xray main, AmneziaWG kept, sing-box alternative and OFF. One tunnel = one
engine; only proven protocol support; links never printed; plans never executed."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'components/runtime/lib/vward-vpn-engines.sh'
SHELL = [os.environ['VPN_BUSYBOX'], 'ash'] if os.environ.get('VPN_BUSYBOX') else ['sh']
def fail(m): raise SystemExit('VPN_ENGINES=FAIL: ' + m)
SECRET = '0f5e2c4a-1111-2222-3333-444455556666'

with tempfile.TemporaryDirectory() as td:
    td = Path(td); R = td/'root'
    for d in ('opt/etc/vward/vless-engine', 'opt/etc/vward/awg-engine', 'opt/etc/vward/singbox-engine', 'opt/bin'):
        (R/d).mkdir(parents=True)
    shim = td/'shim'; shim.mkdir(); trace = td/'trace'
    for n in ('ndmc', 'xray', 'awg', 'curl'):
        (shim/n).write_text(f'#!/bin/sh\necho {n} "$@" >> {trace}\nexit 99\n'); (shim/n).chmod(0o755)
    env = dict(os.environ, VWARD_ROOT_PREFIX=str(R), PATH=f'{shim}:{os.environ["PATH"]}', JQ=shutil.which('jq'))
    for k in ('VWARD_VLESS_ETC', 'VWARD_AWG_ETC', 'VWARD_SINGBOX_ETC'): env.pop(k, None)
    def L(s, *a): return subprocess.run([*SHELL, '-c', f'. "{LIB}"\n' + s, 'x', *map(str, a)], env=env, text=True, capture_output=True, timeout=30)
    def w(n, t): p = td/n; p.write_text(t); p.chmod(0o600); return p
    (R/'opt/etc/vward/vless-engine/tunnels.tsv').write_text('srv1\tOpkgTun1\n')
    (R/'opt/etc/vward/awg-engine/tunnels.tsv').write_text('home\tOpkgTun2\n')

    # ---- ownership: one tunnel, one engine ------------------------------------------------------
    for name, want in (('OpkgTun1', 'xray'), ('OpkgTun2', 'awg'), ('OpkgTun3', 'none')):
        if L('vward_vpn_engine_owner "$1"', name).stdout.strip() != want: fail('owner of ' + name)
    (R/'opt/etc/vward/singbox-engine/tunnels.tsv').write_text('dup\tOpkgTun1\n')
    r = L('vward_vpn_engine_owner OpkgTun1')
    if r.returncode != 75 or r.stdout.strip() != 'conflict,xray,singbox': fail('two engines on one tunnel not detected: ' + r.stdout)
    (R/'opt/etc/vward/singbox-engine/tunnels.tsv').write_text('')
    if L('vward_vpn_engine_owner "$1"', 'OpkgTun1; reboot').returncode != 2: fail('bad tunnel name accepted')

    # ---- link classification, secrets never printed ----------------------------------------------------
    links = {
        'reality': f'vless://{SECRET}@a.example:443?type=tcp&security=reality&sni=b.example&fp=chrome&pbk=PUB&sid=ab#n',
        'xhttp': f'vless://{SECRET}@a.example:443?type=xhttp&security=tls&sni=a.example#n',
        'ws': f'vless://{SECRET}@a.example:443?type=ws&security=tls&path=%2Fx&host=a.example',
        'trojan': f'trojan://{SECRET}@a.example:443?sni=a.example',
        'wg': '[Interface]\nPrivateKey = KEY\n[Peer]\nPublicKey = P\n',
        'awg': '[Interface]\nPrivateKey = KEY\nJc = 4\nJmin = 40\n[Peer]\nPublicKey = P\n',
    }
    want = {'reality': 'vless\ttcp\treality', 'xhttp': 'vless\txhttp\ttls', 'ws': 'vless\tws\ttls', 'trojan': 'trojan\ttcp\ttls',
            'wg': 'wireguard\tudp\tnone', 'awg': 'amneziawg\tudp\tnone'}
    files = {k: w(k + '.link', v + '\n') for k, v in links.items()}
    for k, p in files.items():
        r = L('vward_vpn_link_class "$1"', p)
        if r.stdout.strip() != want[k] or SECRET in r.stdout + r.stderr or 'KEY' in r.stdout: fail(f'class {k}: {r.stdout}')
    if L('vward_vpn_link_class "$1"', w('junk', 'hello\n')).stdout.strip() != 'unknown\t-\t-': fail('junk classified')

    # ---- capabilities: absent binary -> unknown -> sing-box supports nothing ------------------------------
    if L('vward_singbox_caps').stdout.strip() != 'unknown': fail('caps without binary')
    def compat(e, k, caps):
        p, n, s = want[k].split('\t'); return L('vward_vpn_engine_compat "$1" "$2" "$3" "$4" "$5"', e, p, n, s, caps).stdout.strip()
    for k in want:
        if not compat('singbox', k, 'unknown').startswith('no\t'): fail('unknown capabilities must support nothing: ' + k)
    sb = R/'opt/bin/sing-box'
    sb.write_text(f'#!/bin/sh\necho "$@" >> {trace}.sb\ncase "$1" in version) printf "sing-box version 1.11.4\\n\\nEnvironment: go1.23\\nTags: with_gvisor,with_quic,with_utls,with_wireguard\\n" ;; check) grep -q \'"type": "tun"\' "$3" ;; *) exit 9 ;; esac\n')
    sb.chmod(0o755)
    caps = L('vward_singbox_caps').stdout.strip()
    if caps != 'version=1.11.4\ttags=with_gvisor,with_quic,with_utls,with_wireguard': fail('caps: ' + caps)
    matrix = {('singbox', 'reality'): 'yes', ('singbox', 'xhttp'): 'no\txhttp-not-supported-by-singbox', ('singbox', 'ws'): 'yes',
              ('singbox', 'trojan'): 'yes', ('singbox', 'wg'): 'yes', ('singbox', 'awg'): 'no\tamneziawg-not-supported-by-singbox',
              ('xray', 'xhttp'): 'yes', ('xray', 'reality'): 'yes', ('xray', 'awg'): 'no', ('awg', 'awg'): 'yes', ('awg', 'reality'): 'no'}
    for (e, k), v in matrix.items():
        if not compat(e, k, caps).startswith(v): fail(f'compat {e}/{k}: {compat(e, k, caps)}')
    nou = 'version=1.11.4\ttags=with_quic'
    if compat('singbox', 'reality', nou) != 'no\treality-needs-with_utls' or compat('singbox', 'wg', nou) != 'no\twireguard-tag-missing':
        fail('missing build tags must mean unsupported')

    # ---- render: private, secret stays in the file, xhttp/awg refused, check is parse-only ----------------
    out = td/'sb.json'
    r = L('vward_singbox_render "$1" "$2" opkgtun3', files['reality'], out)
    if r.returncode or SECRET in r.stdout + r.stderr: fail('render reality: ' + r.stderr)
    cfg = json.loads(out.read_text()); ob = cfg['outbounds'][0]
    if oct(out.stat().st_mode & 0o777) != '0o600' or ob['uuid'] != SECRET or ob['tls']['reality']['public_key'] != 'PUB' \
            or cfg['inbounds'][0]['interface_name'] != 'opkgtun3' or cfg['inbounds'][0]['auto_route'] is not False: fail('render content')
    r = L('vward_singbox_render "$1" "$2" opkgtun3', files['ws'], out)
    if r.returncode or json.loads(out.read_text())['outbounds'][0]['transport'] != {'type': 'ws', 'path': '/x', 'headers': {'Host': 'a.example'}}: fail('render ws')
    for k in ('xhttp', 'awg', 'wg'):
        if L('vward_singbox_render "$1" "$2" opkgtun3', files[k], td/'no.json').returncode != 75 or (td/'no.json').exists(): fail('render must refuse ' + k)
    if L('vward_singbox_render "$1" "$2" "$3"', files['reality'], out, 'eth0').returncode != 2: fail('render on a non-OpkgTun device')
    if L('vward_singbox_check "$1"', out).stdout.strip() != 'valid': fail('check')
    if L('vward_singbox_check "$1"', w('bad.json', '{}')).stdout.strip() != 'invalid': fail('check invalid')

    # ---- plans: never two engines, proven before switching, keys kept, writer off ------------------------------
    base = {'compat': 'yes', 'config': 'valid', 'probe': 'ok', 'target_installed': 'yes', 'writer': 'disabled'}
    def plan(name, target, **over):
        p = w('facts', ''.join(f'{k}\t{v}\n' for k, v in dict(base, **over).items() if v is not None))
        return L('vward_vpn_engine_plan "$1" "$2" "$3"', name, target, p)
    r = plan('OpkgTun1', 'singbox')
    lines = r.stdout.splitlines()
    if r.returncode or [l.split('\t')[0] for l in lines] != ['1', '2', '3', '4', '5', 'writer'] or 'nothing executed' not in lines[-1]: fail('plan: ' + r.stdout)
    if 'kept' not in lines[0] or 'start xray again' not in lines[4]: fail('plan must keep the old engine as the return path')
    for over, why in ((dict(compat='no'), 'protocol-not-supported-by-target'), (dict(config='unknown'), 'target-config-not-validated'),
                      (dict(probe='none'), 'target-not-proven-working'), (dict(target_installed='no'), 'target-engine-not-installed'),
                      (dict(probe=None), 'target-not-proven-working')):
        r = plan('OpkgTun1', 'singbox', **over)
        if r.returncode != 75 or r.stdout.strip() != f'refuse\t{why}': fail(f'plan must refuse {why}: {r.stdout}')
    if plan('OpkgTun1', 'xray').stdout.strip() != 'none\talready-xray': fail('same engine')
    if plan('OpkgTun3', 'singbox').stdout.strip() != 'refuse\ttunnel-has-no-engine': fail('unowned tunnel')
    (R/'opt/etc/vward/singbox-engine/tunnels.tsv').write_text('dup\tOpkgTun1\n')
    if plan('OpkgTun1', 'awg').stdout.strip() != 'refuse\ttwo-engines-claim-the-tunnel': fail('conflict must refuse')
    if 'requires owner approval' not in plan('OpkgTun2', 'singbox', writer='enabled').stdout: fail('enabled writer still needs approval')

    # ---- no engine, tunnel or router was touched; sing-box only asked for version/check -------------------------
    if trace.exists(): fail('an engine or Keenetic was called: ' + trace.read_text())
    calls = {l.split()[0] for l in Path(f'{trace}.sb').read_text().splitlines()}
    if not calls <= {'version', 'check'}: fail('sing-box was asked to do more than version/check: ' + str(calls))
    if subprocess.run([*SHELL, '-c', f'sentinel=1; . "{LIB}"; [ "$sentinel" = 1 ]']).returncode: fail('load not inert')
print('VPN_ENGINES=PASS: one engine per tunnel, link classes without secrets, proven-only sing-box support (no XHTTP/AmneziaWG), private render, parse-only check, ordered plans')
