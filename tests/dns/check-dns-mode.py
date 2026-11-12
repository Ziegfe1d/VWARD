#!/usr/bin/env python3
"""DNS mode selector (agh | dnsmasq | native): mutually exclusive handlers, dnsmasq rendered
safe (no DHCP, no :53, no AGH port, no loop), switch plans that never put AGH and dnsmasq in
the chain together. Read/render/plan only: nothing is started, stopped or sent to Keenetic."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'components/runtime/lib/vward-dns-mode.sh'
SHELL = [os.environ['DNS_BUSYBOX'], 'ash'] if os.environ.get('DNS_BUSYBOX') else ['sh']
def fail(m): raise SystemExit('DNS_MODE=FAIL: ' + m)

with tempfile.TemporaryDirectory() as td:
    td = Path(td); R = td/'root'; (R/'opt/etc/vward').mkdir(parents=True)
    shim = td/'shim'; shim.mkdir(); trace = td/'trace'
    for n in ('ndmc', 'dnsmasq', 'AdGuardHome', 'curl'):
        (shim/n).write_text(f'#!/bin/sh\necho {n} "$@" >> {trace}\nexit 99\n'); (shim/n).chmod(0o755)
    LAN = '10.77.0.1'   # the device profile's LAN address (never a constant in the library)
    env = dict(os.environ, VWARD_ROOT_PREFIX=str(R), PATH=f'{shim}:{os.environ["PATH"]}', VWARD_LAN_ADDRESS=LAN)
    def L(s, *a): return subprocess.run([*SHELL, '-c', f'. "{LIB}"\n' + s, 'x', *map(str, a)], env=env, text=True, capture_output=True, timeout=30)
    def w(name, text): p = td/name; p.write_text(text); return p

    # ---- mode: default agh, explicit, unsafe/invalid -> unknown ------------------------------
    # Owner 12.11.2026: nothing recorded and no AdGuard Home is Keenetic's own DNS, never «:65053»;
    # with AdGuard Home installed the default stays AGH.
    if L('vward_dns_mode_get').stdout != 'native\tdefault-no-agh\n': fail('RED: without AdGuard Home the default must be native')
    (R/'opt/etc/AdGuardHome').mkdir(parents=True); (R/'opt/etc/AdGuardHome/AdGuardHome.yaml').write_text('dns:\n')
    if L('vward_dns_mode_get').stdout != 'agh\tdefault\n': fail('default must be AGH where it is installed')
    mc = R/'opt/etc/vward/dns-mode.conf'
    for text, want in (('mode=dnsmasq\n', 'dnsmasq\tconfigured\n'), ('mode=native\n', 'native\tconfigured\n'),
                       ('mode=both\n', 'unknown\tinvalid\n'), ('mode=agh\nmode=dnsmasq\n', 'unknown\tinvalid\n'), ('', 'unknown\tinvalid\n')):
        mc.write_text(text); r = L('vward_dns_mode_get')
        if r.stdout != want: fail(f'mode {text!r}: {r.stdout!r}')
    mc.unlink(); os.symlink(td/'x', mc)
    if L('vward_dns_mode_get').stdout != 'unknown\tunsafe-file\n': fail('symlinked mode file accepted')
    mc.unlink()

    # ---- render: safe defaults, Smart DNS to a local DoH client, Ads blocks --------------------------
    up = w('up', '9.9.9.9\n149.112.112.112#53\n')
    sd = w('sd', 'claude.ai\t127.0.0.1#5453\nchatgpt.com\t127.0.0.1#5453\n')
    ads = w('ads', 'ads.example\ntracker.example\n')
    out = td/'dnsmasq.conf'
    r = L('vward_dns_dnsmasq_render "$1" 65054 "$2" "$3" "$4"', out, up, sd, ads)
    if r.returncode: fail('render: ' + r.stdout + r.stderr)
    conf = out.read_text()
    for need in ('port=65054', 'listen-address=127.0.0.1', 'bind-interfaces', 'no-resolv', 'server=9.9.9.9',
                 'server=/claude.ai/127.0.0.1#5453', 'address=/ads.example/0.0.0.0'):
        if need + '\n' not in conf: fail('render lacks ' + need)
    if any(l.startswith(('dhcp-', 'interface=', 'enable-tftp')) for l in conf.splitlines()): fail('DHCP/interface in config')
    if oct(out.stat().st_mode & 0o777) != '0o600': fail('config not private')
    if L('vward_dns_dnsmasq_validate "$1"', out).stdout != 'valid\n': fail('rendered config not valid')
    first = conf
    L('vward_dns_dnsmasq_render "$1" 65054 "$2" "$3" "$4"', out, up, sd, ads)
    if out.read_text() != first: fail('render not deterministic')
    # refusals leave the previous config untouched
    for args, why in (((53,), 'port-reserved-53'), ((65053,), 'port-reserved-65053'),
                      ((65054, w('u2', 'https://dns.example/q\n')), 'bad-upstream'), ((65054, w('u3', '')), 'no-upstream'),
                      ((65054, up, w('s2', 'claude.ai\thttps://x.example/dns-query\n')), 'bad-smartdns-rule'),
                      ((65054, up, w('s3', 'bad domain\t127.0.0.1#5453\n')), 'bad-smartdns-rule'),
                      ((65054, up, sd, w('a2', 'x;rm -rf /\n')), 'bad-ads-domain')):
        a = list(args) + [up, sd, ads][len(args) - 1:]
        r = L('vward_dns_dnsmasq_render "$1" "$2" "$3" "$4" "$5"', out, *a[:4])
        if r.returncode != 75 or why not in r.stdout or out.read_text() != first: fail(f'render must refuse {why}: {r.stdout}')
    # ---- validate: hand-edited unsafe configurations ----------------------------------------------------
    for extra, why in (('dhcp-range=192.168.1.50,192.168.1.150\n', 'dhcp-or-interface-dhcp-range'),
                       ('interface=br0\n', 'dhcp-or-interface-interface'), ('enable-tftp\n', 'dhcp-or-interface-enable-tftp'),
                       ('server=127.0.0.1#53\n', 'loop-127.0.0.1#53'), ('server=10.77.0.1\n', 'loop-10.77.0.1'),
                       ('server=/x.example/127.0.0.1#65054\n', 'loop-127.0.0.1#65054'), ('conf-dir=/opt/etc\n', 'external-include-conf-dir')):
        p = w('v.conf', first + extra); r = L('vward_dns_dnsmasq_validate "$1"', p)
        if r.returncode != 75 or why not in r.stdout: fail(f'validate must refuse {why}: {r.stdout}')
    for text, why in ((first.replace('port=65054', 'port=53'), 'port-reserved'), (first.replace('listen-address=127.0.0.1', 'listen-address=0.0.0.0'), 'listen-not-loopback'),
                      (first + 'port=65055\n', 'port-count')):
        r = L('vward_dns_dnsmasq_validate "$1"', w('v2.conf', text))
        if r.returncode != 75 or why not in r.stdout: fail(f'validate must refuse {why}: {r.stdout}')

    # ---- plans: never both handlers, proven before the chain moves, unknown refuses -------------------
    base = {'agh_running': 'yes', 'dnsmasq_running': 'no', 'dnsmasq_installed': 'yes', 'dnsmasq_config': 'valid',
            'dnsmasq_port': '65054', 'port_free': 'yes', 'smartdns_rules': '8', 'smartdns_mapped': '8',
            'native_upstream': 'yes', 'probe_dnsmasq': 'ok', 'router_address': LAN, 'writer': 'disabled'}
    def plan(target, **over):
        facts = dict(base, **over); p = w('facts', ''.join(f'{k}\t{v}\n' for k, v in facts.items() if v is not None))
        return L('vward_dns_mode_plan "$1" "$2"', target, p)
    r = plan('dnsmasq')
    steps = r.stdout.splitlines()
    if r.returncode or not steps[0].startswith('1\tjournal-plan mode=agh->dnsmasq'): fail('agh->dnsmasq plan: ' + r.stdout)
    chain = [s for s in steps if s.startswith('4\t')][0]
    if chain != '4\treplace chain: no ip name-server 10.77.0.1:65053; ip name-server 10.77.0.1:65054': fail('chain step: ' + chain)
    order = [s.split('\t')[0] for s in steps]
    if order != ['1', '2', '3', '4', '5', '6', '7', 'writer'] or 'nothing executed' not in steps[-1]: fail('step order ' + str(order))
    if 'stop agh' not in r.stdout: fail('the old handler must stop after the new chain answers')
    for over, why in ((dict(agh_running='yes', dnsmasq_running='yes'), 'both-handlers-running'),
                      (dict(agh_running='unknown'), 'handler-state-unknown'), (dict(agh_running=None), 'handler-state-unknown'),
                      (dict(agh_running='no'), 'mode-disagrees-with-running'),
                      (dict(dnsmasq_installed='no'), 'dnsmasq-not-installed'), (dict(dnsmasq_config='invalid'), 'dnsmasq-config-not-valid'),
                      (dict(dnsmasq_port='53'), 'dnsmasq-port-reserved'), (dict(dnsmasq_port='65053'), 'dnsmasq-port-reserved'),
                      (dict(port_free='no'), 'dnsmasq-port-busy'), (dict(smartdns_mapped='7'), 'smartdns-not-fully-mapped'),
                      (dict(router_address=None), 'router-address-unknown'), (dict(router_address='999.1.1.1'), 'router-address-unknown')):
        r = plan('dnsmasq', **over)
        if r.returncode != 75 or r.stdout.strip() != f'refuse\t{why}': fail(f'plan must refuse {why}: {r.stdout}')
    if plan('agh').stdout.strip() != 'none\talready-agh': fail('same mode must be a no-op')
    if plan('native', native_upstream='no').stdout.strip() != 'refuse\tnative-upstream-missing': fail('native without upstream')
    r = plan('native')
    if r.returncode or '4\treplace chain: no ip name-server 10.77.0.1:65053; native' not in r.stdout: fail('agh->native: ' + r.stdout)
    mc.write_text('mode=dnsmasq\n')
    r = plan('agh', agh_running='no', dnsmasq_running='yes')
    if r.returncode or '4\treplace chain: no ip name-server 10.77.0.1:65054; ip name-server 10.77.0.1:65053' not in r.stdout: fail('dnsmasq->agh: ' + r.stdout)
    mc.write_text('mode=garbage\n')
    if plan('agh').stdout.strip() != 'refuse\tcurrent-mode-unknown': fail('unknown current mode must refuse')
    mc.unlink()
    if 'requires owner approval' not in plan('dnsmasq', writer='enabled').stdout: fail('enabled writer still needs approval')

    # ---- purity: no executor, no handler program, no Keenetic call -------------------------------------------
    if trace.exists(): fail('a DNS handler or Keenetic was called: ' + trace.read_text())
    if subprocess.run([*SHELL, '-c', f'sentinel=1; . "{LIB}"; [ "$sentinel" = 1 ]']).returncode: fail('load not inert')
print('DNS_MODE=PASS: exclusive agh/dnsmasq/native, safe dnsmasq render/validate (no DHCP, no :53/:65053, no loop), ordered plans, unknown refuses')
