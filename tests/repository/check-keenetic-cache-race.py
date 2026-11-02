#!/usr/bin/env python3
"""The shared Keenetic configuration copy can vanish between «fresh?» and reading it: any ndmc
that may change the configuration drops it (vward_keenetic_dirty). The reader must then read
Keenetic again, never answer empty with success (CI #792 api-load: awg-data «cat: can't open
'/tmp/vward-keenetic/running-config'»). Two windows: a fresh copy found and the reader's own
new copy just published."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / 'components/runtime/lib/vward-device-profile.sh').read_text()
code = ''.join(re.search(r'^' + n + r'\(\)\n\{\n.*?^\}\n', SRC, re.M | re.S).group(0)
               for n in ('_vward_kc_fresh', 'vward_keenetic_config'))


def fail(m):
    raise SystemExit(f"KEENETIC_CACHE_RACE=FAIL: {m}")


shells = [["sh"]] + ([["busybox", "sh"]] if subprocess.run(["sh", "-c", "command -v busybox"], capture_output=True).returncode == 0 else [])
for shell in shells:
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / 'kc').mkdir()
        (t / 'ndmc').write_text('#!/bin/sh\necho read >> "$T/reads"\necho "interface Fresh"\necho "!"\n')
        (t / 'ndmc').chmod(0o755)
        # cat that loses the race once per marker: the copy is dropped just before it is opened.
        harness = f'''VWARD_KCACHE='{t}/kc'; _VWARD_KCACHE_OWN=1; VWARD_NDMC='{t}/ndmc'
vward_uptime_cs() {{ _VCS=0; }}
vward_keenetic_timed() {{ :; }}
cat() {{
    if [ -e "$T/drop" ] && [ "$1" = "$VWARD_KCACHE/running-config" ]; then rm -f "$T/drop" "$1"; fi
    command cat "$@"
}}
{code}
vward_keenetic_config
'''
        env = dict(os.environ, T=td)
        def run():
            return subprocess.run([*shell, '-c', harness], capture_output=True, text=True, env=env, timeout=20)
        # 1. A fresh copy is there, but dropped before it is read.
        (t / 'kc/running-config').write_text('interface Old\n!\n')
        (t / 'drop').write_text('')
        r = run()
        if r.returncode != 0 or 'interface Fresh' not in r.stdout or "can't open" in r.stderr or 'No such file' in r.stderr:
            fail(f"{shell[0]} RED: a copy dropped before reading gave rc={r.returncode} out={r.stdout!r} err={r.stderr!r}")
        # 2. No copy: this reader reads Keenetic; its own new copy is dropped right after publishing.
        (t / 'kc/running-config').unlink(missing_ok=True)
        (t / 'drop').write_text('')
        r = run()
        if r.returncode != 0 or r.stdout != 'interface Fresh\n!\n' or r.stderr:
            fail(f"{shell[0]} RED: the reader's own copy dropped after publishing gave rc={r.returncode} out={r.stdout!r} err={r.stderr!r}")
        if (t / 'kc/lock').exists():
            fail(f"{shell[0]} the lock is left behind")
print("KEENETIC_CACHE_RACE=PASS")
