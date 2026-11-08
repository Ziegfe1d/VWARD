#!/usr/bin/env python3
"""The route reconciler holds the shared HTTPS turn across the checks of a run (CI #814).

take/done around each of its 5 checks cost 82 processes (budget 64). Now the turn is taken
once in the reconciler's own shell and kept, within a bounded hold (VWARD_RECONCILER_TURN_HOLD,
10 s: a check starts only while held + 3 s fits), with a 1 s yield after a give-back for the
limit (a waiter tries once a second). Real functions of the reconciler and the device profile
(vward_tls_take/done), a fake curl that records whether a live turn exists, sh + BusyBox ash:
  1. three checks, one take; the turn stays this shell's until rc_turn_give, then it is gone;
  2. a removal's two checks in $(...) children borrow the held turn: no take, no give-back;
  3. without a held turn each child takes and gives back its own (no turn left behind);
  4. past the hold limit: given back, a yield (sleep 1), taken again;
  5. turn not given (another live owner): «could not check» (2), no curl;
  6. curl's own crash under the held turn: given back, broken noted, next check 2 without curl;
  7. static: the loop saves no state on a check that did not run, gives the turn back before
     vward_isp_control and after the loop, cleanup gives it back.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECON = (ROOT / "components/route-reconciler/scripts/vward-route-reconciler.sh").read_text()
PROFILE = ROOT / "components/runtime/lib/vward-device-profile.sh"
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(f"{label}: {detail}")


def fn(name):
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", RECON, re.S | re.M)
    check(f"function {name}", m is not None)
    return m.group(0) if m else ""


hold = re.search(r"^RC_TURN=0 .*?\nRC_TURN_HOLD=.*?\ncase \"\$RC_TURN_HOLD\".*?esac\n", RECON, re.S | re.M)
check("hold settings", hold is not None)
FUNCS = (hold.group(0) if hold else "") + "".join(
    fn(n) for n in ("rc_now", "rc_broken", "rc_turn_fits", "rc_turn_name", "rc_turn_give", "rc_turn_check", "probe_run",
                    "probe_result", "probe", "isp_check_ran", "classify_isp_vs_vpn"))

for shell in SHELLS:
    n = shell[-1]
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "bin").mkdir()
        # The fake curl: «owned» when a turn with a live owner exists while it runs.
        (t / "bin/curl").write_text(
            "#!/bin/sh\n"
            f'o=; read -r o _ < "{t}/tls.probe/owner" 2>/dev/null\n'
            f'if [ -n "$o" ] && kill -0 "$o" 2>/dev/null; then echo owned >> "{t}/curl.log"; else echo unowned >> "{t}/curl.log"; fi\n'
            f'rc=0; [ ! -f "{t}/curl.rc" ] || read -r rc < "{t}/curl.rc"\n'
            "printf '200|0.1'\nexit \"$rc\"\n")
        (t / "bin/curl").chmod(0o755)

        def run(body, extra=""):
            for f in ("curl.log", "takes", "sleeps", "curl.rc", "tls.broken"):
                (t / f).unlink(missing_ok=True)
            (t / "uptime").write_text("100.00 0\n")
            script = (f'PATH="{t}/bin:$PATH"\n. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                      f'VWARD_UPTIME_FILE="{t}/uptime"\nVWARD_TLS_TURN_WAIT_OK=1\n: > "{t}/tls.ok"\n'
                      f'{extra}\n{FUNCS}\n'
                      # Count the takes and the yields (the real take runs inside).
                      f'eval "$(echo "_real_take()"; type vward_tls_take >/dev/null 2>&1 && '
                      f'sed -n "/^vward_tls_take()/,/^}}/p" "{PROFILE}" | sed 1d)"\n'
                      f'vward_tls_take() {{ echo t >> "{t}/takes"; _real_take "$@"; }}\n'
                      f'sleep() {{ echo s >> "{t}/sleeps"; }}\n'
                      f'WAN=eth3 WG=nwg0\n{body}\n')
            return subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60)

        def lines(f):
            p = t / f
            return p.read_text().split() if p.exists() else []

        # 1. Three checks, one take, held until given back.
        r = run('probe h eth3 192.0.2.1; probe h eth3 192.0.2.1; probe h nwg0 192.0.2.1; echo "rc=$? turn=$RC_TURN"\n'
                f'read -r o _ < "{t}/tls.probe/owner"; [ "$o" = "$$" ] && echo own=self\n'
                f'rc_turn_give; [ -d "{t}/tls.probe" ] || echo gone')
        check(f"{n} one take for three checks", lines("takes") == ["t"], r.stdout + r.stderr + str(lines("takes")))
        check(f"{n} every curl owned", lines("curl.log") == ["owned"] * 3, lines("curl.log"))
        check(f"{n} held then given back", "rc=0 turn=1" in r.stdout and "own=self" in r.stdout and "gone" in r.stdout,
              r.stdout + r.stderr)

        # 2. Children of the holder borrow the turn (classify after a direct check).
        r = run('probe h eth3 192.0.2.1; rc_turn_check 2; CR=$(classify_isp_vs_vpn h 192.0.2.1); echo "cr=$CR turn=$RC_TURN"\n'
                f'[ -d "{t}/tls.probe" ] && echo held; rc_turn_give; [ -d "{t}/tls.probe" ] || echo gone')
        check(f"{n} classify borrows", lines("takes") == ["t"] and lines("curl.log") == ["owned"] * 3,
              r.stdout + r.stderr + str(lines("takes")) + str(lines("curl.log")))
        check(f"{n} borrowed turn kept by owner", "cr=ISP_OK|0|200|0|200 turn=1" in r.stdout and "held" in r.stdout
              and "gone" in r.stdout, r.stdout + r.stderr)

        # 3. No held turn: each child takes and gives back its own.
        r = run(f'CR=$(classify_isp_vs_vpn h 192.0.2.1); echo "cr=$CR"; [ -d "{t}/tls.probe" ] || echo free')
        check(f"{n} children take and give their own", lines("takes") == ["t", "t"] and "free" in r.stdout
              and lines("curl.log") == ["owned"] * 2, r.stdout + r.stderr + str(lines("takes")))

        # 4. Past the hold limit: given back, yield, taken again.
        r = run(f'probe h eth3 192.0.2.1; echo "107.01 0" > "{t}/uptime"; probe h eth3 192.0.2.1; echo "turn=$RC_TURN"\n'
                f'echo "117.00 0" > "{t}/uptime"; rc_turn_name; [ -d "{t}/tls.probe" ] || echo name-free')
        check(f"{n} hold limit", lines("takes") == ["t", "t"] and lines("sleeps") == ["s", "s"] and "turn=1" in r.stdout,
              r.stdout + r.stderr + str(lines("takes")) + str(lines("sleeps")))
        check(f"{n} given back at a new name", "name-free" in r.stdout, r.stdout + r.stderr)
        r = run(f'probe h eth3 192.0.2.1; rc_turn_name; [ -d "{t}/tls.probe" ] || echo free; echo "turn=$RC_TURN"')
        check(f"{n} new name within the limit: given back, no wait", "free" in r.stdout and "turn=0" in r.stdout
              and lines("sleeps") == [], r.stdout + r.stderr + str(lines("sleeps")))
        # An old crash note (over an hour) does not stop the hold.
        r = run(f': > "{t}/tls.broken"; touch -d "2 hours ago" "{t}/tls.broken"; probe h eth3 192.0.2.1; probe h eth3 192.0.2.1; rc_turn_give')
        check(f"{n} old crash note: still one take", lines("takes") == ["t"] and lines("curl.log") == ["owned"] * 2,
              r.stdout + r.stderr + str(lines("takes")))
        # A borrowing child that crashes: its sibling runs no curl, the owner gives back without «works».
        r = run(f'probe h eth3 192.0.2.1; rm -f "{t}/tls.ok"; echo 139 > "{t}/curl.rc"; CR=$(classify_isp_vs_vpn h 192.0.2.1); echo "cr=$CR"\n'
                f'rc_turn_give; [ -d "{t}/tls.probe" ] || echo free; [ -e "{t}/tls.ok" ] || echo no-ok')
        check(f"{n} borrowed crash: no second curl", lines("curl.log") == ["owned", "owned"] and "cr=UNKNOWN|139|200|2|000" in r.stdout
              and "free" in r.stdout and "no-ok" in r.stdout, r.stdout + r.stderr + str(lines("curl.log")))
        r = run(f'probe h eth3 192.0.2.1; echo "106.99 0" > "{t}/uptime"; probe h eth3 192.0.2.1; rc_turn_give')
        check(f"{n} within the limit kept", lines("takes") == ["t"] and lines("sleeps") == [], str(lines("takes")))

        # 5. Another live owner: not given, could not check, no curl.
        holder = subprocess.Popen(shell + ["-c", f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                                                 f'vward_tls_take 0 || exit 9\n: > "{t}/held"\n'
                                                 f'while [ ! -e "{t}/release" ]; do sleep 0.05; done\nvward_tls_done 0\n'])
        for _ in range(100):
            if (t / "held").exists():
                break
            subprocess.run(["sleep", "0.05"])
        r = run('probe h eth3 192.0.2.1; echo "rc=$? p=$PROBE_RC prc=$PRC turn=$RC_TURN"')
        (t / "release").touch()
        holder.wait(timeout=30)
        check(f"{n} not given", "rc=2 p=2 prc=2 turn=0" in r.stdout and lines("curl.log") == [], r.stdout + r.stderr)

        # 6. A crash under the held turn: given back, broken for the hour, next check without curl.
        r = run(f'probe h eth3 192.0.2.1; echo 139 > "{t}/curl.rc"; probe h eth3 192.0.2.1; echo "a=$? turn=$RC_TURN"\n'
                f'[ -d "{t}/tls.probe" ] || echo free; [ -e "{t}/tls.broken" ] && echo broken\n'
                f'vward_https_broken() {{ [ -e "{t}/tls.broken" ]; }}\n'
                'probe h eth3 192.0.2.1; echo "b=$?"')
        check(f"{n} crash gives back", "a=2 turn=0" in r.stdout and "free" in r.stdout and "broken" in r.stdout
              and "b=2" in r.stdout and lines("curl.log") == ["owned", "owned"], r.stdout + r.stderr + str(lines("curl.log")))

# 7. Static: the loop and cleanup.
loop = RECON[RECON.find('while [ "$DONE" -lt "$MAX_PER_RUN" ]'):]
body, after = loop.split("\ndone\n", 1) if "\ndone\n" in loop else (loop, "")
wan = body.find('if probe "$H" "$WAN" "$IP"; then')
unk = body.find('if [ "$PROBE_RC" = 2 ]; then')
ctrl = body.find("vward_isp_control; ISPC")
check("unknown direct check stops before any state", 0 < wan < unk < ctrl and "continue" in body[unk:ctrl], body[unk:ctrl])
vpn = body.find('elif probe "$H" "$WG" "$IP"; then')
broken = body.find('save_state "$H" "BROKEN"')
check("unknown VPN check is no BROKEN", 0 < vpn < body.find('elif [ "$PROBE_RC" = 2 ]; then') < broken)
check("turn given back before the ISP control", "rc_turn_give; vward_isp_control" in body)
check("turn given back after the loop", after.lstrip().startswith("rc_turn_give"))
check("cleanup gives the turn back", "rc_turn_give" in fn("cleanup"))
check("no subshell takes for a removal", "rc_turn_check 2\n        CR=$(classify_isp_vs_vpn" in RECON)
check("removal gives back before router changes", 'CR=$(classify_isp_vs_vpn "$H" "$MIP")\n        # Router changes follow: the turn is not held during them.\n        rc_turn_give' in RECON)
check("given back before a name's lookups", "rc_turn_name\n\n    AGH=$(nslookup" in body)

if fails:
    raise SystemExit("RECONCILER_TLS_HOLD=FAIL\n" + "\n".join(fails))
print("RECONCILER_TLS_HOLD=PASS " + "+".join(s[-1] for s in SHELLS) +
      ": one take per run, children borrow, own turns given back, 10 s hold with yield, not given/crash = could not check, loop saves nothing on unknown")
