#!/usr/bin/env python3
"""Run production failure branches: unknown config is not absence; retain DNS ownership."""
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REC = ROOT / 'components/route-reconciler/scripts/vward-route-reconciler.sh'
DNS = ROOT / 'components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh'


def function(path, name):
    m = re.search(r'^' + name + r'\(\)\s*\n?\{\n.*?^\}', path.read_text(), re.M | re.S)
    assert m, name
    return m.group(0) + '\n'


errors = []
with tempfile.TemporaryDirectory() as d:
    t = Path(d)
    for mode in ('unknown', 'absent', 'present'):
        persist = t / 'persist'
        persist.write_text('example.org\nother.example\n')
        targets = t / 'targets'
        targets.write_text('example.org\n')
        resolver = t / 'resolve'
        resolver.write_text('#!/bin/sh\nprintf "Address 1: 203.0.113.4\\n"\n')
        resolver.chmod(0o755)
        cfg = {'unknown': 'return 1', 'absent': 'printf "dns-proxy\\n!\\n"',
               'present': 'printf "object-group fqdn AdaptiveAuto\\n    include example.org\\n!\\n"'}[mode]
        setup = f'''STATE="{t}"
LOG="{t}/events"
HYST_DIR="{t}"
CHANGE="{t}/change"
TARGETS="{targets}"
PERSIST="{persist}"
GROUP=AdaptiveAuto
CONFIG_DIRTY="{t}/dirty"
DIRECT_OK_THRESHOLD=1
DIRECT_OK_MIN_INTERVAL=0
force_vpn_match() {{ return 1; }}
classify_isp_vs_vpn() {{ echo 'ISP_OK|0|200|0|200'; }}
ndmc() {{ return 1; }}
vward_running_config() {{ {cfg}; }}
'''
        script = setup + function(REC, 'adaptive_names') + function(REC, 'save_state')
        script += function(REC, 'remove_adaptive').replace('/opt/bin/vward-route-resolve4.sh', str(resolver)).replace('/opt/var/backups/vward/route-reconciler', str(t / 'backups'))
        script += 'remove_adaptive example.org\n'
        r = subprocess.run(['sh', '-c', script], capture_output=True, text=True)
        want = 'other.example\n' if mode == 'absent' else 'example.org\nother.example\n'
        if persist.read_text() != want: errors.append(mode + ': lost persist')
        state = t / 'example.org.state'
        if mode != 'absent' and state.exists() and 'STATUS=DIRECT_OK\n' in state.read_text():
            errors.append(mode + ': false DIRECT_OK')
        state.unlink(missing_ok=True)
        (t / 'example.org.state.tmp').unlink(missing_ok=True)
    for operation in ('agh_unbind', 'ns_release'):
        ledger = t / 'bindings'
        original = 'ok.example 127.0.0.1:65053\nbad.example 127.0.0.1:65053\nmanual.example ext\nretry.example failed 42\n'
        ledger.write_text(original)
        script = f'''AGH_BIND="{ledger}"
CHAIN_DIR="{t}"
ndm() {{ case "$*" in *bad.example*) return 1 ;; *) return 0 ;; esac; }}
ads_log() {{ :; }}
ads_epoch() {{ echo 123; }}
chain_line() {{ return 1; }}
'''
        script += function(DNS, operation)
        if operation == 'agh_unbind': script += 'agh_unbind\n'
        else:
            script += "ns_release '127.0.0.1:65053' 'ip name-server 127.0.0.1:65053 ok.example\nip name-server 127.0.0.1:65053 bad.example' outage\n"
        subprocess.run(['sh', '-c', script], capture_output=True, text=True, check=True)
        got = ledger.read_text() if ledger.exists() else ''
        if got != original.split('\n', 1)[1]: errors.append(operation + ': unconfirmed/foreign ownership discarded')
if errors: raise SystemExit('ROUTING_STATE_ERRORS=FAIL: ' + '; '.join(errors))
print('ROUTING_STATE_ERRORS=PASS')
