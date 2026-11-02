#!/usr/bin/env python3
"""Start phases account for measured uptime, including a failed restore."""
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / 'components/route-engine/scripts/vward-route-engine.sh').read_text()
m = re.search(r'^startup_phase\(\)\n\{\n.*?^\}\n', SRC, re.M | re.S)
phase = m.group(0) if m else ''
main = SRC[SRC.index('# MAIN LIVE LOOP'):]
# The timing function is loaded above; execute only the actual startup calls.
main = main[main.index('\n}\n') + 3:]
main = main[main.index('echo '):main.index('while :; do')]
for status in (0, 1):
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / 'uptime').write_text('100.2 0\n')
        script = f'''EVENT_LOG='{t}/events'; VWARD_UPTIME_FILE='{t}/uptime'
STOP_T0=100
restore_adaptive_from_persist() {{ echo '114.9 0' > "$VWARD_UPTIME_FILE"; return {status}; }}
agh_bind_prune() {{ echo '115.4 0' > "$VWARD_UPTIME_FILE"; }}
refresh_sets() {{ echo '120.1 0' > "$VWARD_UPTIME_FILE"; }}
{phase}
{main}
'''
        subprocess.run(['sh', '-c', script], check=True, capture_output=True)
        events = (t / 'events').read_text()
        for want in (f'|START_PHASE|phase=restore|elapsed=14s|total=14s|rc={status}',
                     '|START_PHASE|phase=agh-prune|elapsed=1s|total=15s|rc=0',
                     '|START_PHASE|phase=refresh|elapsed=5s|total=20s|rc=0'):
            assert want in events, f'START_PHASES=FAIL: missing {want}: {events}'
print('START_PHASES=PASS')
