#!/usr/bin/env python3
"""AdaptiveAuto at Keenetic's limit and Russian services (Viva self-test 15.10).

Keenetic takes at most 300 names in a group and answers «too many elements», and the engine tried
again on every query (a Keenetic session every 10-30 s). 110 of the 300 were Russian services
(*.ru, yandex.net, vk.com) whose direct check had failed by chance. Now:
  * a Russian zone or service is never checked for AdaptiveAuto (VWARD_ADAPTIVE_RU=1 lets them in);
  * «too many elements» (even without an error code): the name is not taken for added, no new
    name is tried for an hour, one notification in the bell;
  * the hour is up: the next name is tried again.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(msg):
    print(f"ADAPTIVE_FULL=FAIL: {msg}")
    sys.exit(1)


start = ENGINE.index("# Keenetic takes at most 300 names in a group")
end = ENGINE.index("\n}\n", ENGINE.index("add_adaptive()\n")) + 3
fn = ENGINE[start:end]
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "bin").mkdir()
        (t / "bin/ndmc").write_text('#!/bin/sh\necho "$2" >> "$T/ndmc.log"\n'
                                    '[ -e "$T/full" ] && echo \'Network::ObjectGroup: "AdaptiveAuto": too many elements\'\nexit 0\n')
        (t / "bin/ndmc").chmod(0o755)
        script = t / "run.sh"
        script.write_text(f"""STATE_DIR="{t}"; EVENT_LOG="{t}/events"; ADAPTIVE="{t}/adaptive"; GROUP=AdaptiveAuto
ADAPTIVE_DISABLED="{t}/off"; REFRESH_TS="{t}/ts"; WAN=eth3; WG=nwg1; VWARD_DNS_SERVER=192.0.2.1
change_lock() {{ :; }}; change_unlock() {{ :; }}; refresh_sets() {{ :; }}; is_manual_known() {{ return 1; }}
parent_list_match() {{ return 1; }}; is_special() {{ return 1; }}; is_adaptive() {{ return 1; }}; agh_blocked() {{ return 1; }}
resolve_ipv4() {{ echo 198.51.100.7; }}; save_state() {{ :; }}; persist_sync_cache() {{ :; }}; nslookup() {{ :; }}
probe() {{ echo "$1 $2" >> "{t}/probes"; P_RC=0 P_CODE=200 P_TIME=1; [ "$2" = nwg1 ]; }}
vward_note() {{ echo "$2" >> "{t}/notes"; }}
{fn}
add_adaptive "$1"
""")
        env = {"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t)}

        def run(name, **extra):
            r = subprocess.run([*shell, str(script), name], env=env | extra, capture_output=True, text=True, timeout=30)
            if r.returncode:
                fail(f"{shell[0]} {name}: rc={r.returncode} {r.stderr}")

        def text(name):
            p = t / name
            return p.read_text() if p.exists() else ""

        for ru in ("napi.wildberries.ru", "static-basket-01.wbbasket.ru", "startup.mobile.yandex.net", "sun1.userapi.com",
                   "vk.com", "xn--80ak6aa92e.xn--p1ai"):
            run(ru)
        if text("probes") or text("ndmc.log") or text("events").count("ADD_SKIP_RU_ZONE") != 6:
            fail(f"{shell[0]} Russian services checked for AdaptiveAuto: {text('probes')!r} {text('ndmc.log')!r}")
        run("napi.wildberries.ru", VWARD_ADAPTIVE_RU="1")
        if "napi.wildberries.ru" not in text("ndmc.log"):
            fail(f"{shell[0]} VWARD_ADAPTIVE_RU=1 does not let them in")

        # Full: refused without an error code - not taken for added, an hour of quiet, one note.
        (t / "full").write_text("")
        run("blocked-one.example")
        if "blocked-one.example" in text("adaptive") or "|AUTO_VPN|blocked-one" in text("events") or not (t / "adaptive.full").exists():
            fail(f"{shell[0]} a refused name is taken for added: {text('events')}")
        if text("notes").count("AdaptiveAuto полон") != 1:
            fail(f"{shell[0]} no notification of a full AdaptiveAuto: {text('notes')!r}")
        n = len(text("probes").splitlines())
        run("blocked-two.example")
        run("blocked-three.example")
        if len(text("probes").splitlines()) != n or "blocked-two" in text("ndmc.log"):
            fail(f"{shell[0]} full: names still tried within the hour: {text('ndmc.log')!r}")
        # The hour is up: tried again; still full - the bell is not rung twice in two hours.
        old = time.time() - 3700
        os.utime(t / "adaptive.full", (old, old))
        run("blocked-four.example")
        if "blocked-four.example" not in text("ndmc.log") or text("notes").count("AdaptiveAuto полон") != 1:
            fail(f"{shell[0]} after the hour: {text('ndmc.log')!r} {text('notes')!r}")
        # Room again: added as before.
        (t / "full").unlink()
        os.utime(t / "adaptive.full", (old, old))
        run("blocked-five.example")
        if "blocked-five.example" not in text("adaptive") or "|AUTO_VPN|blocked-five.example|" not in text("events"):
            fail(f"{shell[0]} room again: not added: {text('events')}")

print("ADAPTIVE_FULL=PASS")
