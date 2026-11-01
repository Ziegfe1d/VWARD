#!/usr/bin/env python3
"""Engine start reads Keenetic's configuration ONCE (diagnostics 31.10.2026, P0).

Viva 19:13-19:51: 41 START_FAILED / 42 TERM, one per watchdog minute. Each start ran
PERSIST_RESTORE_OK with added=0 removed=0 left=0 (no Keenetic call at all) and still needed
8-13 s: the time was the configuration read. restore read it directly, then set REFRESH_TS=0 so
refresh_sets read it directly AGAIN, all before the capture program starts; S91 waits 12 s for
that program. Now: the restore and the refresh use the shared copy (a read already made is
reused); the refresh is forced only when the restore actually changed the group (the ndmc
write drops the shared copy, so the next read is fresh). No timeout was raised.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(msg):
    print(f"ROUTE_ENGINE_START_READS=FAIL: {msg}")
    sys.exit(1)


def func(name):
    i = ENGINE.index(f"\n{name}()\n") + 1
    j = ENGINE.index("\n}\n", i) + 3
    return ENGINE[i:j]


restore = ENGINE[ENGINE.index("valid_fqdn()\n"):ENGINE.index("# ADD TO VPN")]
code = func("shared_config") + func("refresh_sets") + restore
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])
CFG = "dns-proxy\n    route object-group AdaptiveAuto OpkgTun4 auto\n!\nobject-group fqdn AdaptiveAuto\n{inc}!\n"

for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "bin").mkdir()
        # ndmc write: drops the shared copy, as the real wrapper does.
        (t / "bin/ndmc").write_text('#!/bin/sh\necho "$2" >> "$T/ndmc.log"\nrm -f "$T/cache"\nexit 0\n')
        (t / "bin/ndmc").chmod(0o755)
        script = t / "run.sh"
        script.write_text(f"""T="{t}"; PERSIST="$T/persist"; EVENT_LOG="$T/events"; GROUP=AdaptiveAuto; REFRESH_TS="$T/ts"
ADAPTIVE_FULL="$T/full"; LOCK="$T/lock"; MANUAL="$T/manual"; ADAPTIVE="$T/adaptive"; SMARTDNS="$T/smartdns"
LISTS_CONF="$T/lists.conf"; VOLATILE_DIR="$T/vol"; GROUP_REFRESH=300; VWARD_ENGINE_SHARED_CONFIG=1
change_lock() {{ :; }}; change_unlock() {{ :; }}; list_watch_map() {{ :; }}; vward_agh_smartdns_domains() {{ :; }}
fetch() {{ echo x >> "$T/reads"; cat "$T/rc"; }}
vward_running_config() {{ fetch; }}
vward_keenetic_config() {{ if [ -s "$T/cache" ]; then cat "$T/cache"; else fetch | tee "$T/cache"; fi; }}
{code}
restore_adaptive_from_persist
refresh_sets
""")
        env = {"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t)}

        def run(cur, want, ts=None):
            (t / "rc").write_text(CFG.format(inc="".join(f"    include {h}\n" for h in cur)))
            (t / "persist").write_text("".join(f"{h}\n" for h in want))
            for f in ("reads", "cache", "ndmc.log", "events", "ts", "manual", "adaptive", "smartdns"):
                (t / f).unlink(missing_ok=True)
            if ts is not None:
                (t / "ts").write_text(f"{ts}\n")
            r = subprocess.run([*shell, str(script)], env=env, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                fail(f"{shell} run failed: {r.stderr[-300:]}")
            reads = (t / "reads").read_text().count("x") if (t / "reads").exists() else 0
            return reads

        # A. nothing to restore (the Viva case: added=0 removed=0): ONE configuration read in all.
        n = run(["a.example", "b.example"], ["a.example", "b.example"])
        if n != 1:
            fail(f"RED: start with nothing to restore read Keenetic's configuration {n} times (want 1)")
        if "PERSIST_RESTORE_OK|added=0|removed=0" not in (t / "events").read_text():
            fail("restore did not report OK for an unchanged group")
        if sorted((t / "adaptive").read_text().split()) != ["a.example", "b.example"]:
            fail("the refresh did not produce the AdaptiveAuto list")
        # B. the restore changes the group: the write drops the shared copy and the refresh is forced,
        # so the sets are built from a fresh read (2 reads) - correctness kept.
        n = run(["a.example"], ["a.example", "new.example"], ts=10**10)
        if n != 2 or "object-group fqdn AdaptiveAuto include new.example" not in (t / "ndmc.log").read_text():
            fail(f"a changed group must be re-read once after the write (reads={n})")
        if (t / "ts").read_text().strip() == "0":
            fail("refresh left the forced marker behind")
        # C. a recent refresh and no change: the refresh itself is skipped (no second read, files kept).
        (t / "manual").write_text("keep\n"); (t / "adaptive").write_text("keep\n"); (t / "smartdns").write_text("")
        import time
        now = int(time.time())
        (t / "rc").write_text(CFG.format(inc="    include a.example\n"))
        (t / "persist").write_text("a.example\n")
        for f in ("reads", "cache", "ndmc.log", "events"):
            (t / f).unlink(missing_ok=True)
        (t / "ts").write_text(f"{now}\n")
        r = subprocess.run([*shell, str(script)], env=env, capture_output=True, text=True, timeout=60)
        reads = (t / "reads").read_text().count("x") if (t / "reads").exists() else 0
        if r.returncode != 0 or reads != 1 or (t / "adaptive").read_text() != "keep\n":
            fail(f"recent refresh with an unchanged group must cost one read and keep the lists (reads={reads})")
print("ROUTE_ENGINE_START_READS=PASS: one configuration read at start; forced re-read only after a real change")
