#!/usr/bin/env python3
"""«Система → Стабильность»: the API gives what the real-time watcher saw (its state, an
hourly line for 7 days, the CPU of each component, the latest events of its actions and of
the cron supervisor), and the Panel computes the index: 40% DNS answered, 20% VWARD's
programs kept running, 20% repairs that helped, 20% hours with enough memory."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"STABILITY_PAGE=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "st").mkdir(); (tmp / "cpu").mkdir()
    (tmp / "st/state").write_text("version=1\nnow=1790640000\nsamples=100\ndns_ok=50\ndns_fail=1\nmem_kb=55000\nbad=x1\n"
                                  "watch=route-engine|123|6000|5900|7000|16384|35|0|0\nwatch=bad\"name|1|1|1|1|1|1|0|0\n")
    (tmp / "hours.tsv").write_text("1790630000\t120\t0\t3\t2\t0\t50000\t80\t0\t0\nnot a line\n1790633600\t118\t2\t5\t3\t1\t14000\t420\t1\t1\n")
    (tmp / "cpu/tunnel-health").write_text("12 345\n")
    (tmp / "cpu/.times.x").write_text("junk\n")
    (tmp / "s.log").write_text('2026-09-29 01:00:00|ACT|down|panel\nnoise\n')
    (tmp / "sup.log").write_text("2026-09-29 00:59:00|MEM_RESTART|panel|rss_kb=30000|limit_kb=24576\n2026-09-29 00:58:00|SUPERVISOR_START|pid=1\n")
    env = {"PATH": os.environ["PATH"], "REQUEST_METHOD": "GET", "QUERY_STRING": "action=stability", "JQ": shutil.which("jq"),
           "VWARD_PROFILE_LIB": "/nonexistent", "VWARD_SENTINEL_STATE": str(tmp / "st"), "VWARD_SENTINEL_HOURS": str(tmp / "hours.tsv"),
           "VWARD_CPU_DIR": str(tmp / "cpu"), "VWARD_SENTINEL_LOG": str(tmp / "s.log"), "VWARD_SUPERVISOR_LOG": str(tmp / "sup.log"),
           "VWARD_SENTINEL_PIDFILE": str(tmp / "none.pid"), "VWARD_SENTINEL_BIN": str(tmp / "none")}
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env, text=True, capture_output=True, timeout=30)
    d = json.loads(r.stdout.split("\n\n", 1)[1])
    if d.get("sentinel") != {"running": False, "installed": False}:
        fail(f"sentinel: {d.get('sentinel')}")
    st = d["state"]
    if st.get("dns_ok") != 50 or "bad" in st or [w["name"] for w in st["watch"]] != ["route-engine"] or st["watch"][0]["cpu_x100"] != 35:
        fail(f"state: numbers only, odd watch names dropped: {st}")
    if d["hours"] != [[1790630000, 120, 0, 3, 2, 0, 50000, 80, 0, 0], [1790633600, 118, 2, 5, 3, 1, 14000, 420, 1, 1]]:
        fail(f"hours: {d['hours']}")
    if d["cpu"] != [{"component": "tunnel-health", "runs": 12, "cs": 345}]:
        fail(f"cpu: {d['cpu']}")
    if [e["what"] for e in d["events"]] != ["ACT|down|panel", "MEM_RESTART|panel|rss_kb=30000|limit_kb=24576"]:
        fail(f"events: the watcher's actions and the supervisor's restarts, newest first: {d['events']}")

# The index, computed by the Panel's own functions.
js = (ROOT / "web/assets/vward-console.js").read_text()
start, end = js.index("function stabScore("), js.index("const stabCls")
script = js[start:end] + """
const fmtKB = kb => kb + ' КБ';
const rows = [[1790630000, 120, 0, 3, 2, 0, 50000, 80, 0, 0], [1790633600, 118, 2, 5, 3, 1, 14000, 420, 1, 1]];
const a = stabScore(rows);
const b = stabScore([[1, 100, 0, 0, 0, 0, 60000, 50, 0, 0]]);
const c = stabRows({state: {now: 2000, started: 1000, samples: 5, dns_ok: 9, dns_fail: 1, actions_ok: 0, actions_fail: 0, mem_min_kb: 50000}, hours: []}, 86400);
console.log(JSON.stringify({a, b, c, none: stabScore([]), ev: stabEvent('ACT|leak|awg-t0|rss_kb=70010|restart'), mr: stabEvent('MEM_RESTART|panel|rss_kb=1')}));
"""
out = json.loads(subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True).stdout)
a = out["a"]
# dns 238/240, programs 1-0.1-0.2, repairs 5/6, memory 1 of 2 hours short.
want = round(100 * (0.4 * 238 / 240 + 0.2 * 0.7 + 0.2 * 5 / 6 + 0.2 * 0.5))
if a["index"] != want or a["downs"] != 1 or a["leaks"] != 1 or a["low"] != 1 or a["hours"] != 2:
    fail(f"index of two hours: {a} want {want}")
if out["b"]["index"] != 100 or out["none"] is not None:
    fail(f"a clean hour is 100, no hours is no index: {out['b']} {out['none']}")
if out["c"] != [[1000, 9, 1, None, 0, 0, 50000, None, 0, 0]]:
    fail(f"the running hour from the watcher's totals: {out['c']}")
if out["ev"] != "AmneziaWG, туннель 0: утечка памяти (70010 КБ), перезапущен" or out["mr"] != "Панель VWARD: утечка памяти, перезапущен":
    fail(f"events in words: {out['ev']} / {out['mr']}")
for need in ("'d-stability': { title: 'Стабильность', parent: 'system', data: ['stab'] }", "stab: () => apiGet('stability')",
             "['Стабильность', sc ? sc.index + '% за сутки'", "'d-stability'() {"):
    if need not in js:
        fail(f"the Panel lacks {need!r}")
if not re.search(r"\|stability(\|[a-z-]+)*\) ;;", (ROOT / "web/cgi-bin/api.cgi").read_text()):
    fail("the API accepts action=stability")
print("STABILITY_PAGE=PASS")
