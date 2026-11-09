#!/usr/bin/env python3
"""P0-3: save_state never loses the previous record and never reports a save it did not make.

Real route-engine save_state/state_path/read_state/state_recover (+ handle_new and
add_adaptive callers) under sh and BusyBox ash. Failure injection by shell function
wrappers of mv/rm on the exact target, equal-second mtimes (USB resolution), a save
killed between its renames, concurrent writers, restart/persist.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
NAMES = ("state_path read_state save_state state_save_fail state_recover regular_cooldown "
         "probe probe_ran unknown_recent probe_unknown tls_broken tls_crash event_result handle_new add_adaptive").split()


def func(name):
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", ENGINE, re.S | re.M)
    return m.group(0) if m else ""


FUNCS = "".join(func(n) for n in NAMES)
CONST = "\n".join(re.findall(r"^(?:DIRECT_COOLDOWN|FAIL_COOLDOWN|UNKNOWN_COOLDOWN)=\d+$", ENGINE, re.M))
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(f"{label}: {detail}")


def run(shell, t, body, timeout=60):
    script = f"""
STATE_DIR="{t}/opt" VOLATILE_DIR="{t}/vol" EVENT_LOG="{t}/events" QNOW=2000000
WAN=eth3 WG=nwg0 GROUP=AdaptiveAuto CONNECT_TIMEOUT=1 MAX_TIME=1
ADAPTIVE="{t}/adaptive" ADAPTIVE_DISABLED="{t}/none" ADAPTIVE_FULL="{t}/none" ADAPTIVE_FULL_MIN=60 REFRESH_TS="{t}/refresh"
VWARD_TLS_BROKEN_FLAG="{t}/tls.broken"
{CONST}
sleep() {{ :; }}; agh_blocked() {{ return 1; }}; resolve_ipv4() {{ echo 192.0.2.9; }}
change_lock() {{ :; }}; change_unlock() {{ :; }}; refresh_sets() {{ :; }}; ru_zone() {{ return 1; }}
is_manual_known() {{ return 1; }}; parent_list_match() {{ return 1; }}; is_special() {{ return 1; }}
is_adaptive() {{ return 1; }}; persist_sync_cache() {{ :; }}; nslookup() {{ :; }}
ndmc() {{ echo "ndmc $*" >> "{t}/ndmc.calls"; }}
curl() {{ printf '%s' "$(cat "{t}/curl.$CURL_IFACE" 2>/dev/null || echo '000|-')"; return "$(cat "{t}/curl.rc.$CURL_IFACE" 2>/dev/null || echo 7)"; }}
{FUNCS}
{body}
"""
    return subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=timeout)


def rec(path, status, last=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"HOST=d.example\nSTATUS={status}\nLAST_CHECK={last}\n")


def same_second(*paths):
    t = int(time.time())
    for p in paths:
        os.utime(p, (t, t))


def read(shell, t):
    return run(shell, t, 'read_state d.example && echo "$ST_STATUS"').stdout.strip()


def leftovers(t):
    return sorted(str(p.relative_to(t)) for d in ("opt", "vol") if (t / d).exists()
                  for p in (t / d).iterdir() if ".tmp." in p.name or ".prev." in p.name)


for shell in SHELLS:
    n = shell[-1]

    # 1. Normal commits both directions, equal-second mtimes: the reader sees exactly the new record.
    for new, old_where, old in (("AUTO_VPN", "vol", "DIRECT_OK"), ("DIRECT_OK", "opt", "AUTO_VPN"), ("BROKEN", "vol", "ISP_FAIL_WG_FAIL")):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); (t / "opt").mkdir(); (t / "vol").mkdir()
            rec(t / old_where / "d.example.state", old)
            other = t / ("vol" if old_where == "opt" else "opt") / "d.example.state"
            rec(other, old); same_second(other, t / old_where / "d.example.state")
            r = run(shell, t, f'save_state d.example {new}; echo "rc=$?"')
            check(f"{n} commit {new}", r.stdout.strip() == "rc=0" and read(shell, t) == new, r.stdout + r.stderr)
            where = "opt" if new in ("AUTO_VPN", "BROKEN") else "vol"
            check(f"{n} commit {new} one copy", (t / where / "d.example.state").exists() and
                  not (t / ({"opt": "vol", "vol": "opt"}[where]) / "d.example.state").exists() and not leftovers(t), leftovers(t))

    # 2. Injected failures: nothing changes for the reader, failure is returned and logged.
    cases = {
        # The new record cannot be written (its directory is gone).
        "write": ('rm -rf "$VOLATILE_DIR"', ""),
        # Publishing the new record fails.
        "publish": ("", 'mv() { for a; do l=$a; done; case "$l" in "$VOLATILE_DIR"/*.state) return 1 ;; esac; command mv "$@"; }'),
        # Moving/removing the other copy fails (the old rm and the new rename alike).
        "other": ("", 'mv() { for a; do case "$a" in "$STATE_DIR"/*.state) return 1 ;; esac; done; command mv "$@"; }\n'
                      'rm() { for a; do case "$a" in "$STATE_DIR"/*.state) return 1 ;; esac; done; command rm "$@"; }'),
    }
    for case, (pre, wrap) in cases.items():
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); (t / "vol").mkdir()
            rec(t / "opt/d.example.state", "AUTO_VPN")
            same_second(t / "opt/d.example.state")
            r = run(shell, t, f'{pre}\n{wrap}\nsave_state d.example DIRECT_OK; echo "rc=$?"')
            got = read(shell, t)
            check(f"{n} {case} rc", r.stdout.strip().endswith("rc=1"), r.stdout + r.stderr)
            check(f"{n} {case} previous kept", (t / "opt/d.example.state").exists() and got == "AUTO_VPN",
                  f"reader={got!r} opt={(t / 'opt/d.example.state').exists()}")
            check(f"{n} {case} logged", "STATE_SAVE_FAIL|d.example|status=DIRECT_OK" in
                  ((t / "events").read_text() if (t / "events").exists() else ""))
            check(f"{n} {case} no leftovers", not leftovers(t), leftovers(t))

    # 3. A save killed between its two renames: the record set aside comes back at start.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td); (t / "vol").mkdir()
        rec(t / "opt/d.example.state.prev.4242", "AUTO_VPN")
        rec(t / "opt/k.example.state", "BROKEN"); rec(t / "opt/k.example.state.prev.77", "AUTO_VPN")
        (t / "opt/unrelated.state.tmp.9").write_text("partial")
        r = run(shell, t, "state_recover")
        check(f"{n} recover", read(shell, t) == "AUTO_VPN" and not (t / "opt/d.example.state.prev.4242").exists(), r.stderr)
        check(f"{n} recover obsolete", not (t / "opt/k.example.state.prev.77").exists() and
              "STATUS=BROKEN" in (t / "opt/k.example.state").read_text())
        check(f"{n} recover touches nothing else", (t / "opt/unrelated.state.tmp.9").read_text() == "partial")

    # 4. Callers: an unsaved result is never logged as a success.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td); (t / "opt").mkdir()
        (t / "curl.eth3").write_text("200|0.1"); (t / "curl.rc.eth3").write_text("0")
        r = run(shell, t, 'CURL_IFACE=eth3; handle_new d.example; echo "rc=$?"')
        ev = (t / "events").read_text() if (t / "events").exists() else ""
        check(f"{n} handle_new unsaved", "|DIRECT_OK|" not in ev and "STATE_SAVE_FAIL|d.example" in ev and r.stdout.strip() == "rc=1", ev + r.stdout)
    with tempfile.TemporaryDirectory() as td:
        t = Path(td); (t / "vol").mkdir()
        r = run(shell, t, 'probe() { case "$2" in eth3) P_RC=7 P_CODE=000 P_TIME=-; return 1 ;; *) P_RC=0 P_CODE=200 P_TIME=0.1; return 0 ;; esac; }\n'
                          'vward_isp_control() { return 0; }\nadd_adaptive d.example; echo "rc=$?"')
        check(f"{n} add_adaptive unsaved", "AUTO_VPN: d.example" not in r.stdout and r.stdout.strip().endswith("rc=1") and
              "STATE_SAVE_FAIL|d.example|status=AUTO_VPN" in (t / "events").read_text(), r.stdout + r.stderr)

    # 5. Concurrent writers of one domain: the reader always gets a whole record, no leftovers.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td); (t / "opt").mkdir(); (t / "vol").mkdir()
        loop = 'i=0; while [ $i -lt 25 ]; do save_state d.example {s} >/dev/null 2>&1; i=$((i+1)); done'
        bodies = [loop.format(s=s) for s in ("AUTO_VPN", "DIRECT_OK", "BROKEN", "ISP_FAIL_WG_FAIL")]
        # Run the writers as parallel processes of the real functions.
        import threading
        res = []
        th = [threading.Thread(target=lambda b=b: res.append(run(shell, t, b, timeout=120))) for b in bodies]
        for x in th: x.start()
        for x in th: x.join()
        got = read(shell, t)
        check(f"{n} concurrent whole record", got in ("AUTO_VPN", "DIRECT_OK", "BROKEN", "ISP_FAIL_WG_FAIL"), got)
        check(f"{n} concurrent no leftovers", not leftovers(t), leftovers(t))

    # 6. Restart/persist: AUTO_VPN survives the loss of RAM, a RAM result does not shadow it later.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td); (t / "opt").mkdir(); (t / "vol").mkdir()
        run(shell, t, "save_state d.example AUTO_VPN")
        shutil.rmtree(t / "vol"); (t / "vol").mkdir()
        check(f"{n} persist", read(shell, t) == "AUTO_VPN")

if fails:
    raise SystemExit("ROUTE_STATE_COMMIT=FAIL\n" + "\n".join(fails))
print("ROUTE_STATE_COMMIT=PASS " + "+".join(s[-1] for s in SHELLS) +
      ": equal-second commit, write/publish/other failures keep the previous record and return 1, killed-save recovery, unsaved never logged as success, concurrent, persist")
