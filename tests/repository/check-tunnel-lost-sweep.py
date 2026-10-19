#!/usr/bin/env python3
"""A tunnel without settings: its lists and subnets go to the default tunnel (fix.32)."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = (ROOT / "components/tunnel-guard/scripts/vward-tunnel-guard.sh").read_text()
HELPER = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
JS = (ROOT / "web/assets/vward-console.js").read_text()


def fail(message: str) -> None:
    print(f"TUNNEL_LOST_SWEEP=FAIL: {message}")
    sys.exit(1)


fn = re.search(r"^lost_sweep\(\)\n\{\n.*?^\}\n", GUARD, re.S | re.M)
if not fn:
    fail("the guard has no lost_sweep")
CONFIG = """interface OpkgTun2
!
interface OpkgTun4
!
interface OpkgTun5
!
dns-proxy
    route object-group Youtube OpkgTun2 auto
    route object-group Games OpkgTun5 auto
    route object-group Mine OpkgTun4 auto
!
ip route 10.20.0.0 255.255.0.0 OpkgTun2 auto
"""


def run(mode: str, action: str = "KEEP_UP", link5: str = "down") -> tuple[str, str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "cfg").write_text(CONFIG)
        (t / "helper").write_text(f'#!/bin/sh\necho "$*" >> "{t}/helper.log"\necho result=changed\n')
        (t / "helper").chmod(0o755)
        sh = f"""
ACTION={action} MODE={mode} DIR="{t}" LOG="{t}/guard.log" NOW_TEXT=now HELPER="{t}/helper"
VWARD_TUNNEL_INTERFACE=OpkgTun4
vward_keenetic_config() {{ cat "{t}/cfg"; }}
engine_of() {{ [ "$1" = OpkgTun5 ] && echo /bin/engine; [ "$1" = OpkgTun5 ]; }}
vward_interface_state() {{ case "$1" in OpkgTun5) printf 'up\\n{link5}\\n' ;; *) printf 'up\\ndown\\n' ;; esac; }}
vward_agent_acts() {{ echo "$2|$3" >> "{t}/proposed"; return 1; }}
vward_note() {{ echo "$1|$2|$4" >> "{t}/notes"; }}
{fn.group(0)}
lost_sweep
lost_sweep
"""
        r = subprocess.run(["sh", "-c", sh], text=True, capture_output=True, timeout=30)
        if r.returncode != 0:
            fail(f"rc={r.returncode} {r.stderr[-300:]}")
        read = lambda n: (t / n).read_text() if (t / n).exists() else ""
        return read("helper.log"), read("notes") + read("guard.log"), read("proposed")


h, notes, prop = run("AUTO")
if h != "tunnel-delete OpkgTun2 vpn move\n":
    fail(f"only the tunnel without settings moves, once in 30 minutes: {h!r}")
if "LOST_MOVED|from=OpkgTun2|to=OpkgTun4" not in notes or "t-OpkgTun2" not in notes:
    fail(f"the move is journaled and told: {notes!r}")
h, notes, prop = run("WATCH")
if h or "lost-move:OpkgTun2" not in prop:
    fail(f"watching proposes and changes nothing: {h!r} {prop!r}")
h, _, _ = run("AUTO", action="FALLBACK_SWITCH")
if h:
    fail("nothing moves while the default tunnel does not answer")
# The helper: move only, the tunnel stays; the API passes it down; the Panel offers it.
if 'if [ "${3:-}" = move ]; then' not in HELPER or 'done_ok "tunnel-move $1 lists=$td_lists subnets=$td_nets to=$2" changed' not in HELPER:
    fail("the helper has no move-only mode")
if 'set -- tunnel-delete "$TNAME" vpn move' not in API:
    fail("the API does not pass the move down")
if "'tunnel-move': () =>" not in JS or 'data-confirm="tunnel-move"' not in JS:
    fail("the Panel does not offer the move")
print("TUNNEL_LOST_SWEEP=PASS")
