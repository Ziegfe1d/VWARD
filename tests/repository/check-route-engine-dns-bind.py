#!/usr/bin/env python3
"""P-7: a rejected DNS binding is retried without duplicate rows or a hot retry loop."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / 'components/route-engine/scripts/vward-route-engine.sh').read_text()
def fn(name):
    m = re.search(r'^'+name+r'\(\)\n\{\n.*?^\}\n', SRC, re.M | re.S)
    return m.group(0) if m else ''
functions = ''.join(fn(n) for n in ['agh_bound', 'agh_bind_record', 'agh_bind_one'])
shells = [['sh']] + ([['busybox','sh']] if shutil.which('busybox') else [])
for shell in shells:
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)
        setup = '''AGH_BIND="$T/bind"; AGH_BIND_RUN="$T/run"; EVENT_LOG="$T/events"; CONFIG_DIRTY="$T/dirty"
mkdir "$AGH_BIND_RUN"
AGH_BIND_MAX=1
QNOW=1000
agh_ns() { echo 192.0.2.1:5353; }
agh_ns_room() { echo 10; }
shared_config() { printf 'dns-proxy\\n!\\n'; }
ndmc() { echo "$*" >> "$T/calls"; if [ -e "$T/refuse" ]; then echo 'Command::Base error: busy'; return "$(cat "$T/refuse")"; fi; return 0; }
'''
        # A failed row must expire, an old no-timestamp failed row must be retried.
        cases = [
            ('legacy failure', 'echo "example.com failed" > "$AGH_BIND"; ! agh_bound api.example.com'),
            ('recent failure', 'echo "example.com failed 990" > "$AGH_BIND"; agh_bound api.example.com'),
            ('expired failure', 'echo "example.com failed 800" > "$AGH_BIND"; ! agh_bound api.example.com'),
            ('successful parent', 'echo "example.com 192.0.2.1:5353" > "$AGH_BIND"; agh_bound api.example.com; ! agh_bound notexample.com'),
            ('legacy opt-out', 'VWARD_AGH_BIND_RETRY=0; echo "example.com failed 800" > "$AGH_BIND"; agh_bound api.example.com'),
        ]
        for title, body in cases:
            r=subprocess.run(shell+['-c', setup+functions+body], env={'PATH':'/usr/bin:/bin','T':td}, capture_output=True,text=True)
            if r.returncode: raise SystemExit('DNS_BIND=FAIL '+title+': '+r.stderr)
        original = 'example.org 192.0.2.1:5353\n'
        (p/'bind').write_text(original)
        r=subprocess.run(shell+['-c',setup+functions+'awk() { return 9; }; ! agh_bind_record example.com ext'],env={'PATH':'/usr/bin:/bin','T':td},capture_output=True,text=True)
        assert r.returncode == 0 and (p/'bind').read_text() == original, 'state read failure lost existing ownership'
        # If durable ownership cannot be written, undo the new router binding.
        (p/'bind').unlink(missing_ok=True);(p/'calls').unlink(missing_ok=True)
        r=subprocess.run(shell+['-c',setup+functions+'agh_bind_record() { return 9; }; ! agh_bind_one example.com'],env={'PATH':'/usr/bin:/bin','T':td},capture_output=True,text=True)
        calls=(p/'calls').read_text().splitlines()
        assert r.returncode == 0 and len(calls)==2 and '-c no ip name-server 192.0.2.1:5353 example.com' == calls[-1], calls
        # Rejected commands, including ndmc returning rc=0 with an error, are not ready.
        for code in ['0','1']:
            script=setup+functions+f'''echo {code} > "$T/refuse"
rm -f "$AGH_BIND" "$T/calls"
agh_bind_one example.com
[ "$(awk '$2=="failed" {{print $1}}' "$AGH_BIND")" = example.com ] || exit 11
agh_bind_one example.com
[ "$(wc -l < "$T/calls")" -eq 1 ] || exit 12
QNOW=1100; rm "$T/refuse"
agh_bind_one example.com
[ "$(wc -l < "$T/calls")" -eq 2 ] || exit 13
[ "$(wc -l < "$AGH_BIND")" -eq 1 ] || exit 14
grep -q '^example.com 192.0.2.1:5353$' "$AGH_BIND" || exit 15
agh_bound api.example.com || exit 16
'''
            r=subprocess.run(shell+['-c',script],env={'PATH':'/usr/bin:/bin','T':td},capture_output=True,text=True)
            if r.returncode:raise SystemExit(f'DNS_BIND=FAIL retry rc={code} case={r.returncode}: {r.stderr}')
print('DNS_BIND=PASS')
