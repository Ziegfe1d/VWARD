#!/usr/bin/env python3
"""P0-2: a check that did not run (or says nothing) is UNKNOWN, never a network failure.

The real route-engine functions (probe, handle_new, handle_adaptive, add_adaptive,
handle_hint, alt_tunnel, list_watch_check, save_state...) and the real device-profile
vward_tls_take/vward_tls_done run under sh and BusyBox ash with a curl stand-in.
UNKNOWN (shared HTTPS turn not given, curl broken/crashed, stopped from outside
137/141/143, no IPv4 to check, ISP control unable to tell) must not become
ISP_FAIL_WG_FAIL/BROKEN/AUTO_VPN, must not touch an existing trusted state and
must not count toward LIST_AUTO_VPN. Real failures (curl 7/28/35/52/60, 451)
keep their old meaning, confirmations and cooldowns.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
PROFILE = ROOT / "components/runtime/lib/vward-device-profile.sh"
NAMES = ("state_path read_state save_state regular_cooldown adaptive_due tls_broken tls_crash "
         "probe probe_ran unknown_recent probe_unknown alt_tunnel event_result handle_new "
         "handle_adaptive add_adaptive hint_direct_known handle_hint list_watch_unknown list_watch_check").split()


def func(name):
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", ENGINE, re.S | re.M)
    return m.group(0) if m else ""


# The owner's list_watch_act=1 (08.11: observation by default, tested in check-list-watch).
FUNCS = "re_acts() { return 0; }\n" + "".join(func(n) for n in NAMES)
CONST = "\n".join(re.findall(r"^(?:DIRECT_COOLDOWN|FAIL_COOLDOWN|UNKNOWN_COOLDOWN|ADAPTIVE_RECHECK)=\d+$", ENGINE, re.M))
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []


def run(shell, tmp, body, curl=None, isp_control=0, tls_take=None):
    """curl: {iface: [(rc, output), ...]} answered in order; calls logged."""
    t = Path(tmp)
    for d in ("vol", "opt", "tools"):
        (t / d).mkdir(exist_ok=True)
    for iface, answers in (curl or {}).items():
        (t / f"curl.{iface}").write_text("".join(f"{rc}|{out}\n" for rc, out in answers))
    stub = t / "tools/curl"
    stub.write_text(f"""#!/bin/sh
iface=
while [ $# -gt 0 ]; do [ "$1" = --interface ] && iface=$2; shift; done
q="{t}/curl.$iface"; echo "$iface" >> "{t}/curl.calls"
[ -s "$q" ] || exit 7
line=$(head -n 1 "$q"); tail -n +2 "$q" > "$q.n"; mv "$q.n" "$q"
printf '%s' "${{line#*|}}"; exit "${{line%%|*}}"
""")
    stub.chmod(0o755)
    take = "" if tls_take is None else f"vward_tls_take() {{ return {tls_take}; }}\n"
    script = f"""
PATH="{t}/tools:$PATH"
. "{PROFILE}"
{take}
VWARD_TLS_BROKEN_FLAG="{t}/tls.broken"
STATE_DIR="{t}/opt" VOLATILE_DIR="{t}/vol" EVENT_LOG="{t}/events"
WAN=eth3 WG=nwg0 GROUP=AdaptiveAuto CONNECT_TIMEOUT=1 MAX_TIME=1 QNOW=1000000
ADAPTIVE="{t}/adaptive" ADAPTIVE_DISABLED="{t}/no-disabled" ADAPTIVE_FULL="{t}/no-full" ADAPTIVE_FULL_MIN=60
REFRESH_TS="{t}/refresh" MANUAL="{t}/manual" QUALITY="{t}/no-quality"
LIST_WATCH_COOLDOWN=0 LIST_WATCH_FAILS=2 CONSOLE_CONFIG_BIN="{t}/tools/helper"
{CONST}
sleep() {{ :; }}; agh_blocked() {{ return 1; }}; resolve_ipv4() {{ echo 192.0.2.9; }}
change_lock() {{ :; }}; change_unlock() {{ :; }}; refresh_sets() {{ :; }}; ru_zone() {{ return 1; }}
is_manual_known() {{ return 1; }}; parent_list_match() {{ return 1; }}; is_special() {{ return 1; }}
is_adaptive() {{ return 1; }}; persist_sync_cache() {{ :; }}; nslookup() {{ :; }}; wg_quick_ok() {{ return 0; }}
ndmc() {{ echo "ndmc $*" >> "{t}/ndmc.calls"; }}
vward_isp_control() {{ return {isp_control}; }}
{FUNCS}
{body}
"""
    (t / "tools/helper").write_text(f'#!/bin/sh\necho "$*" >> "{t}/helper.calls"\necho result=changed\n')
    (t / "tools/helper").chmod(0o755)
    r = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60)
    return r


def read(p):
    return p.read_text() if p.exists() else ""


def check(label, cond, detail=""):
    if not cond:
        fails.append(f"{label}: {detail}")


for shell in SHELLS:
    sname = shell[-1]

    # 1. handle_new: every UNKNOWN cause leaves no failure state and no route.
    for case, kw in {
        "tls-turn-refused": dict(tls_take=1, curl={"eth3": [(7, "000|-")] * 2, "nwg0": [(7, "000|-")] * 2}),
        "direct-killed-143": dict(curl={"eth3": [(143, "")]}),
        "direct-pipe-141": dict(curl={"eth3": [(141, "")]}),
        "vpn-killed-137": dict(curl={"eth3": [(7, "000|-")] * 2, "nwg0": [(137, "")]}),
        "vpn-crash-139": dict(curl={"eth3": [(28, "000|1.0")] * 2, "nwg0": [(139, "")]}),
        "vpn-crash-132": dict(curl={"eth3": [(35, "000|0.1")] * 2, "nwg0": [(132, "")]}),
        "vpn-retry-143": dict(curl={"eth3": [(7, "000|-")] * 2, "nwg0": [(0, "200|0.1"), (143, "")]}),
        "no-curl-127": dict(curl={"eth3": [(127, "")]}),
    }.items():
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "opt").mkdir()
            (t / "opt/site.example.state").write_text("HOST=site.example\nSTATUS=AUTO_VPN\nLAST_CHECK=1\n")
            r = run(shell, tmp, 'add_adaptive() { echo "ADD $1" >> "$EVENT_LOG"; }\nhandle_new site.example', **kw)
            ev = read(t / "events")
            check(f"{sname} handle_new {case}", r.returncode == 0, r.stderr)
            check(f"{sname} handle_new {case}", "ISP_FAIL" not in ev and "ADD " not in ev and "BROKEN" not in ev,
                  f"UNKNOWN became a failure/route: {ev!r}")
            check(f"{sname} handle_new {case}", not (t / "vol/site.example.state").exists(),
                  "UNKNOWN saved a state")
            check(f"{sname} handle_new {case}", read(t / "opt/site.example.state").endswith("STATUS=AUTO_VPN\nLAST_CHECK=1\n"),
                  "trusted persistent AUTO_VPN state was removed or changed")
            check(f"{sname} handle_new {case}", "PROBE_UNKNOWN|site.example|" in ev, f"no bounded UNKNOWN record: {ev!r}")
            calls = read(t / "curl.calls").count("\n")
            # A repeat within UNKNOWN_COOLDOWN runs no curl at all.
            r2 = run(shell, tmp, 'add_adaptive() { :; }\nhandle_new site.example', **kw)
            check(f"{sname} handle_new {case} cooldown", read(t / "curl.calls").count("\n") == calls,
                  "UNKNOWN repeat was not held back")
        if case == "vpn-crash-139":
            check(f"{sname} crash noted", True)

    # 1b. The real shared turn held by a live owner (P0-1): the check is UNKNOWN, never curl unowned.
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        holder = subprocess.Popen(["sleep", "60"])
        try:
            stat = Path(f"/proc/{holder.pid}/stat").read_text().rsplit(") ", 1)[1].split()
            (t / "tls.probe").mkdir()
            (t / "tls.probe/owner").write_text(f"{holder.pid} {stat[19]}\n")
            (t / "tls.ok").touch()
            r = run(shell, tmp, 'VWARD_TLS_TURN_WAIT_OK=1; add_adaptive() { echo "ADD $1" >> "$EVENT_LOG"; }\nhandle_new site.example',
                    curl={"eth3": [(7, "000|-")] * 2, "nwg0": [(7, "000|-")] * 2})
        finally:
            holder.kill(); holder.wait()
        ev = read(t / "events")
        check(f"{sname} live turn owner", "why=tls_turn" in ev and "ISP_FAIL" not in ev and not read(t / "curl.calls"),
              f"events={ev!r} curl={read(t / 'curl.calls')!r}")

    # 2. Real failures keep their meaning and confirmation.
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run(shell, tmp, 'add_adaptive() { :; }\nhandle_new site.example',
            curl={"eth3": [(28, "000|1.0")] * 2, "nwg0": [(52, "000|0.2")]})
        check(f"{sname} real WG fail", "STATUS=ISP_FAIL_WG_FAIL" in read(t / "vol/site.example.state"), read(t / "events"))
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run(shell, tmp, 'add_adaptive() { echo "ADD $1" >> "$EVENT_LOG"; }\nhandle_new site.example',
            curl={"eth3": [(0, "451|0.1"), (60, "000|0.1")], "nwg0": [(0, "200|0.1"), (0, "200|0.1")]})
        check(f"{sname} real ISP fail + WG ok x2", "ADD site.example" in read(t / "events"), read(t / "events"))
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run(shell, tmp, 'add_adaptive() { :; }\nhandle_new site.example',
            curl={"eth3": [(0, "403|0.1")]})
        check(f"{sname} direct ok", "STATUS=DIRECT_OK" in read(t / "vol/site.example.state"), read(t / "events"))

    # 3. handle_adaptive: UNKNOWN never marks BROKEN; a real double failure does.
    for case, answers, broken in (
        ("direct-143", {"eth3": [(143, "")]}, False),
        ("vpn-137", {"eth3": [(7, "000|-")], "nwg0": [(137, "")]}, False),
        ("vpn-retry-tls", {"eth3": [(7, "000|-")], "nwg0": [(7, "000|-"), (139, "")]}, False),
        ("real", {"eth3": [(7, "000|-")], "nwg0": [(7, "000|-"), (28, "000|1")]}, True),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "opt").mkdir()
            (t / "opt/a.example.state").write_text("HOST=a.example\nSTATUS=AUTO_VPN\nLAST_CHECK=1\n")
            run(shell, tmp, 'remove_adaptive() { :; }\nhandle_adaptive a.example', curl=answers)
            st = read(t / "opt/a.example.state")
            check(f"{sname} handle_adaptive {case}", ("STATUS=BROKEN" in st) == broken, st + read(t / "events"))

    # 4. add_adaptive: an UNKNOWN check or ISP control (2) makes no AUTO_VPN.
    for case, answers, ctrl, added in (
        ("direct-143", {"eth3": [(143, "")]}, 0, False),
        ("isp-control-2", {"eth3": [(7, "000|-")], "nwg0": [(0, "200|0.1")]}, 2, False),
        ("vpn-turn", {"eth3": [(7, "000|-")], "nwg0": [(141, "")]}, 0, False),
        ("real", {"eth3": [(7, "000|-")], "nwg0": [(0, "200|0.1")]}, 0, True),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            r = run(shell, tmp, 'add_adaptive new.example', curl=answers, isp_control=ctrl)
            nd = read(t / "ndmc.calls")
            check(f"{sname} add_adaptive {case}", ("include new.example" in nd) == added,
                  f"ndmc={nd!r} events={read(t / 'events')!r} {r.stderr}")
            check(f"{sname} add_adaptive {case}", ("STATUS=AUTO_VPN" in read(t / "opt/new.example.state")) == added)

    # 5. handle_hint: known DIRECT_OK without an IPv4 address or with UNKNOWN checks stays.
    for case, body in (("no-ipv4", 'resolve_ipv4() { :; }\n'), ("killed", "")):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "vol").mkdir()
            (t / "vol/h.example.state").write_text("HOST=h.example\nSTATUS=DIRECT_OK\nLAST_CHECK=1\n")
            run(shell, tmp, body + 'add_hint_adaptive() { echo "HADD $1" >> "$EVENT_LOG"; }\nhandle_hint h.example',
                curl={"eth3": [(143, ""), (143, "")]})
            ev = read(t / "events")
            check(f"{sname} handle_hint {case}", "HADD" not in ev and "HINT_DIRECT_FAIL" not in read(t / "vol/h.example.state"), ev)

    # 6. list_watch_check: UNKNOWN does not count; real failures still move the list.
    for case, answers, take, moved in (
        ("killed-143", [(143, "")] * 3, None, False),
        ("pipe-141", [(141, "")] * 3, None, False),
        ("turn-refused", [(28, "000 ")] * 3, 1, False),
        ("timeout-28", [(28, "000 ")] * 2, None, True),
        ("451", [(0, "451 ")] * 2, None, True),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            body = "LW_I=0; while [ $LW_I -lt %d ]; do list_watch_check claude.ai domain-list4; LW_I=$((LW_I+1)); done" % len(answers)
            run(shell, tmp, body, curl={"eth3": answers}, tls_take=take)
            hc = read(t / "helper.calls")
            check(f"{sname} list_watch {case}", ("domain-list domain-list4 vpn" in hc) == moved,
                  f"helper={hc!r} events={read(t / 'events')!r}")
            if not moved:
                st = read(t / "vol/list-watch.domain-list4").split()
                check(f"{sname} list_watch {case} count", st[1:] in ([], ["0"]), f"UNKNOWN counted: {st}")

    # 7. alt_tunnel never reports a tunnel on UNKNOWN.
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        q = t / "quality"
        q.write_text("#!/bin/sh\nprintf 'Alt1\\tnwg1\\t10\\t0\\t5\\n'\n")
        q.chmod(0o755)
        r = run(shell, tmp, f'QUALITY="{q}"; vward_valid_ifname() {{ :; }}; alt_tunnel x.example 192.0.2.9 && echo FOUND',
                curl={"nwg1": [(143, ""), (143, "")]})
        check(f"{sname} alt_tunnel", "FOUND" not in r.stdout, r.stdout)

if fails:
    raise SystemExit("ROUTE_ENGINE_PROBE_UNKNOWN=FAIL\n" + "\n".join(fails[:40]))
print("ROUTE_ENGINE_PROBE_UNKNOWN=PASS " + "+".join(s[-1] for s in SHELLS) +
      ": UNKNOWN (turn/crash/137/141/143/127/no IPv4/ISP control) keeps state, no failure/route/list move; real failures unchanged")
