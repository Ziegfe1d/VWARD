#!/usr/bin/env python3
"""Fewer ndmc sessions in Keenetic's journal (fix.39, owner's diagnostics 13.11.2026: 2 566 of
~4 000 lines were «Core::Session started/disconnected», about 85 ndmc an hour, and nothing said
whose).

1. The shared copy of Keenetic's configuration (vward_keenetic_config: the Panel and every agent
   that only looks) is read through RCI first - no session line, and 5.5 s instead of 12.7 s on a
   Viva (08.11); ndmc only when RCI gives no whole answer. VWARD_KEENETIC_CONFIG_RCI=0 keeps ndmc.
   Before, every renewal of the copy (about once a minute) was one ndmc session.
2. Every ndmc of a program that loads the library is counted for that program by the hour
   (VWARD_NDMC_CALLS/PROGRAM, shell built-ins only); vward_ndmc_calls_report prints the counts of
   this hour, of the hour before and of the last 24 hours for the Panel's «Диагностика».
3. The router's diagnostics answer carries them (keenetic.ndmc, keenetic.calls_day) and the Panel
   shows «Обращения к Keenetic»: one line a part of VWARD, the largest first. The hourly files are
   read one by one (vward_hour_sum), in «Стабильность» too."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"


def fail(m):
    raise SystemExit(f"KEENETIC_NDMC_SESSIONS=FAIL: {m}")


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    bin_ = tmp / "bin"
    bin_.mkdir()
    # Keenetic's ndmc as a program on PATH (the library wraps only that), and curl for RCI.
    (bin_ / "ndmc").write_text(f"""#!/bin/sh
echo "$2" >> "{tmp}/ndmc.calls"
[ ! -e "{tmp}/ndmc-down" ] || exit 1
case "$2" in 'show running-config') printf 'interface OpkgTun0\\r\\n    description from-ndmc\\r\\n!\\r\\n' ;; *) echo ok ;; esac
""")
    (bin_ / "curl").write_text(f"""#!/bin/sh
for a in "$@"; do url=$a; done
echo "$url" >> "{tmp}/rci.calls"
[ ! -e "{tmp}/rci-down" ] || exit 7
case "$url" in
    */show/running-config) if [ -e "{tmp}/rci-empty" ]; then echo '{{"message": []}}'; else echo '{{"message": ["interface OpkgTun0", "    description from-rci", "!"]}}'; fi ;;
    *) echo '{{}}' ;;
esac
""")
    for f in ("ndmc", "curl"):
        (bin_ / f).chmod(0o755)
    (tmp / "uptime").write_text("7300.50 100.00\n")  # the third hour of uptime
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "VWARD_KCACHE": str(tmp / "kc"), "VWARD_CURL_BIN": str(bin_ / "curl"),
           "VWARD_KEENETIC_SLOW_LOG": str(tmp / "slow.log"), "VWARD_NDMC_CALLS": str(tmp / "ndmc-by"),
           "VWARD_KEENETIC_CALLS": str(tmp / "calls"), "VWARD_KEENETIC_SLOWN": str(tmp / "slown"),
           "VWARD_KEENETIC_LAST": str(tmp / "last"), "VWARD_RCI_CALLS": str(tmp / "rci-by-hour"),
           "VWARD_UPTIME_FILE": str(tmp / "uptime"), "VWARD_RCI_FAIL_LOG": str(tmp / "rci-fail.log")}

    def run(name, script, extra=None):
        prog = tmp / name
        prog.write_text(f'#!/bin/sh\n. "{LIB}"\n{script}\n')
        prog.chmod(0o755)
        r = subprocess.run([os.environ.get("NDMC_TEST_SH", "sh"), str(prog)], env=env | (extra or {}), text=True, capture_output=True, timeout=60)
        return r.stdout

    def lines(name):
        p = tmp / name
        out = p.read_text().splitlines() if p.exists() else []
        p.unlink(missing_ok=True)
        return out

    # 1. The shared copy through RCI: the configuration as RCI gives it, no ndmc session.
    out = run("vward-agent.sh", "vward_keenetic_config")
    if out != "interface OpkgTun0\n    description from-rci\n!\n":
        fail(f"the shared copy must come through RCI: {out!r}")
    if lines("ndmc.calls") or not any(u.endswith("/show/running-config") for u in lines("rci.calls")):
        fail("the shared copy read through RCI must open no ndmc session")
    if (tmp / "ndmc-by").exists():
        fail("no ndmc session - nothing counted")
    # The young copy is shared as before: Keenetic is not asked again.
    run("vward-agent.sh", "vward_keenetic_config >/dev/null")
    if lines("rci.calls") or lines("ndmc.calls"):
        fail("a young copy must be used")
    # RCI silent, or an answer that is not a whole configuration: ndmc, counted for the program.
    for flag in ("rci-down", "rci-empty"):
        (tmp / flag).write_text("")
        out = run("vward-agent.sh", "vward_keenetic_dirty; vward_keenetic_config")
        (tmp / flag).unlink()
        if out != "interface OpkgTun0\n    description from-ndmc\n!\n" or lines("ndmc.calls") != ["show running-config"]:
            fail(f"{flag}: ndmc must answer instead: {out!r}")
        lines("rci.calls")
    # The switch back (device.conf).
    out = run("vward-agent.sh", "vward_keenetic_dirty; vward_keenetic_config", {"VWARD_KEENETIC_CONFIG_RCI": "0"})
    if "from-ndmc" not in out or lines("rci.calls"):
        fail("VWARD_KEENETIC_CONFIG_RCI=0 must keep ndmc")
    lines("ndmc.calls")
    # Neither answers: no answer, no copy left behind.
    (tmp / "rci-down").write_text(""); (tmp / "ndmc-down").write_text("")
    out = run("vward-agent.sh", "vward_keenetic_dirty; vward_keenetic_config; echo rc=$?")
    (tmp / "rci-down").unlink(); (tmp / "ndmc-down").unlink()
    if out != "rc=1\n" or (tmp / "kc/running-config").exists():
        fail(f"no answer from either must fail with nothing shared: {out!r}")
    lines("ndmc.calls"); lines("rci.calls")

    # 2. Sessions by program: every ndmc of a program that loads the library.
    run("vward-other.sh", 'ndmc -c "show version" >/dev/null; "${VWARD_NDMC:-ndmc}" -c "show interface" >/dev/null')
    rep = run("api.cgi", "vward_ndmc_calls_report")
    got = {l.split()[0]: l.split()[1:] for l in rep.splitlines()}
    # vward-agent.sh: rci-down, rci-empty, the switch, both down = 4; vward-other.sh = 2.
    if got != {"vward-agent.sh": ["4", "0", "4"], "vward-other.sh": ["2", "0", "2"]}:
        fail(f"sessions by program (this hour, the hour before, day): {rep!r}")
    # An hour later they are the hour before; three hours later only the day keeps them; a day
    # later nothing is left.
    (tmp / "uptime").write_text("11000.00 100.00\n")
    rep = run("api.cgi", "vward_ndmc_calls_report")
    if sorted(rep.splitlines()) != ["vward-agent.sh 0 4 4", "vward-other.sh 0 2 2"]:
        fail(f"an hour later: {rep!r}")
    (tmp / "uptime").write_text("18100.00 100.00\n")
    rep = run("api.cgi", "vward_ndmc_calls_report")
    if sorted(rep.splitlines()) != ["vward-agent.sh 0 0 4", "vward-other.sh 0 0 2"]:
        fail(f"three hours later: {rep!r}")
    (tmp / "uptime").write_text(f"{7300 + 26 * 3600}.00 100.00\n")
    if run("api.cgi", "vward_ndmc_calls_report").strip():
        fail("sessions older than a day are not shown")
    # Several hours of one program: each hour's file is read by itself (the files do not end with a
    # newline; read together they glued the next hour to the dots before it).
    (tmp / "uptime").write_text("7300.50 100.00\n")
    run("vward-other.sh", 'ndmc -c "show version" >/dev/null')
    for up, want in (("11000.00", "vward-other.sh 1 3 4"), ("14500.00", "vward-other.sh 0 1 4")):
        (tmp / "uptime").write_text(up + " 100.00\n")
        if up == "11000.00":
            run("vward-other.sh", 'ndmc -c "show version" >/dev/null')
        rep = run("api.cgi", "vward_ndmc_calls_report")
        if want not in rep.splitlines():
            fail(f"hours kept apart at uptime {up}: {rep!r}, want {want!r}")
    (tmp / "uptime").write_text("14500.00 100.00\n")
    out = run("api.cgi", f'vward_hour_sum "{tmp}/ndmc-by/vward-other.sh" 2 3; echo "$_VHS"; vward_hour_sum "{tmp}/ndmc-by/vward-other.sh" 3 3; echo "$_VHS"; vward_hour_sum "{tmp}/none" 0 9; echo "$_VHS"')
    if out.split() != ["4", "1", "0"]:
        fail(f"vward_hour_sum: {out!r}")
    # Timing switched off (device.conf): nothing is counted.
    (tmp / "uptime").write_text("7300.50 100.00\n")
    run("vward-quiet.sh", 'ndmc -c "show version" >/dev/null', {"VWARD_KEENETIC_TIMING": "0"})
    if (tmp / "ndmc-by/vward-quiet.sh").exists():
        fail("VWARD_KEENETIC_TIMING=0 must count nothing")

# 3. The answer and the Panel.
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
JS = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("vward_ndmc_calls_report", ".keenetic = {ndmc: $ndmc_by, calls_day: $kcalls_day}", 'vward_hour_sum "$RCI_CD"'):
    if need not in API:
        fail(f"api.cgi lacks {need!r}")
if 'cat "$RCI_CD"/*' in API:
    fail("the hourly files must not be read together")
if "keeneticCallsPanel(d && d.keenetic)" not in JS[JS.index("  'd-diag'() {"):JS.index("  'd-stability'() {")]:
    fail("«Диагностика» must show the requests to Keenetic")
if shutil.which("node"):
    a = JS.index("const NDMC_PROGS = "); b = JS.index("function cronText(")
    h = """const esc = s => String(s), fmtInt = n => String(n), JOB_NAMES = { 'vward-tunnel-health.sh': 'Агент VPN' };
const kv = rows => rows.map(r => r[0] + '|' + r[1] + '|' + (r[2] || '') + '|' + (r[5] || '')).join('\\n'), panel = (t, body, o) => t + '\\n' + body + '\\n' + (o && o.desc || '');
""" + JS[a:b] + """
console.log(JSON.stringify({ none: keeneticCallsPanel(null), empty: keeneticCallsPanel({ ndmc: [], calls_day: 0 }),
  full: keeneticCallsPanel({ ndmc: [{ p: 'vward-policy-sync.sh', now: 0, last: 1, day: 2 }, { p: 'api.cgi', now: 3, last: 14, day: 300 }, { p: 'vward-policy-audit.sh', now: 1, last: 0, day: 1 },
    { p: 'vward-tunnel-health.sh', now: 0, last: 0, day: 5 }, { p: 'vward-new.sh', now: 0, last: 0, day: 4 }], calls_day: 2000 }) }));
"""
    r = subprocess.run(["node", "-e", h], capture_output=True, text=True, timeout=30)
    if r.returncode:
        fail(r.stderr[-500:])
    o = json.loads(r.stdout)
    if o["none"] != "" or "Через ndmc|за сутки не было||" not in o["empty"]:
        fail(f"no data / no sessions: {o['none']!r} {o['empty']!r}")
    rows = o["full"].split("\n")
    want = ["Обращения к Keenetic", "Через ndmc|312 за сутки|warn|за прошлый час 15, за этот 4", "Панель VWARD: страницы|300 за сутки||за прошлый час 14, за этот 3",
            "Агент VPN|5 за сутки||за прошлый час 0, за этот 0", "vward-new.sh|4 за сутки||за прошлый час 0, за этот 0",
            "IP-категории|3 за сутки||за прошлый час 1, за этот 1", "Все обращения|2000 за сутки||вместе с RCI: он не оставляет строк в журнале Keenetic"]
    if rows[:7] != want:
        fail(f"the Panel's block: {rows}")
print("KEENETIC_NDMC_SESSIONS=PASS")
