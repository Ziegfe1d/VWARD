#!/usr/bin/env python3
"""«Система → Стабильность»: the API gives what the real-time watcher saw (its state, an
hourly line for 7 days, the CPU of each component, the latest events of its actions and of
the cron supervisor) and what the watcher does not see (the tunnels passed traffic, the update
feed answered, curl did not crash on HTTPS, Keenetic answered in time); the Panel computes the
index: DNS 28, programs 14, repairs 14, memory 14, tunnel 10, updates 10, HTTPS 5, Keenetic 5.
What is not checked is left out, never counted as 100%."""

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
           "VWARD_SENTINEL_PIDFILE": str(tmp / "none.pid"), "VWARD_SENTINEL_BIN": str(tmp / "none"),
           "VWARD_TUNNEL_QUALITY_DIR": str(tmp / "q"), "VWARD_UPDATE_STATE_DIR": str(tmp / "upd"),
           "VWARD_TLS_BROKEN_FLAG": str(tmp / "tls"), "VWARD_RCI_FAIL_LOG": str(tmp / "rci.log")}
    import time
    now = int(time.time())
    (tmp / "q").mkdir(); (tmp / "upd").mkdir()
    (tmp / "q/samples.tsv").write_text(f"{now - 7200}\tWireguard0\tnwg0\t100\t-\n{now - 60}\tWireguard0\tnwg0\t0\t40\n"
                                       f"{now - 120}\tWireguard0\tnwg0\t100\t-\n{now - 60}\tOpkgTun0\topkgtun0\t33\t90\nbad\tline\n")
    (tmp / "upd/feed.state").write_text(f"ok_at={now - 3600}\nfail_at=\nfail_rc=\n")
    (tmp / "rci.log").write_text(f"{now - 90000}\t28\n{now - 500}\t28\n{now - 100}\t7\n")
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
    ck = d["checks"]
    if sorted((t["name"], t["n"], t["ok"]) for t in ck["tunnels"]) != [("OpkgTun0", 1, 1), ("Wireguard0", 2, 1)]:
        fail(f"tunnel checks of the last hour: {ck}")
    if ck["feed_ok_at"] != now - 3600 or ck["feed_fail_at"] is not None or ck["https_crash_at"] is not None \
            or ck["rci_fails_day"] != 2 or ck["rci_fail_at"] != now - 100:
        fail(f"checks: {ck}")
    if [e["what"] for e in d["events"]] != ["ACT|down|panel", "MEM_RESTART|panel|rss_kb=30000|limit_kb=24576"]:
        fail(f"events: the watcher's actions and the supervisor's restarts, newest first: {d['events']}")

# The index, computed by the Panel's own functions.
js = (ROOT / "web/assets/vward-console.js").read_text()
start, end = js.index("const STAB_W ="), js.index("const stabCls")
script = js[start:end] + """
const fmtKB = kb => kb + ' КБ', fmtStamp = x => 'T' + x, pct = x => Math.round(x * 100) + '%', tunLabel = n => n, plural = (n, a, b, c) => c;
let TUN = { name: 'Wireguard0', state: 'up' };
const prof = () => ({ tunnel_interface: 'Wireguard0' }), st = () => ({ wg: { interfaces: [TUN] } }), tunOff = t => t.state === 'down';
const D = { checks: { now: 100000, tunnels: [{ name: 'Wireguard0', n: 4, ok: 3 }], feed_ok_at: 99000, feed_fail_at: null, https_crash_at: null, rci_fails_day: 2, rci_calls_day: 200, rci_fail_at: 99900 } };
const noCount = stabChecks({ checks: { now: 100000, rci_fails_day: 20 } });
const k = stabChecks(D);
const noDns = stabScore([[1, 0, 0, 0, 0, 0, -1, 0, 0, 0]]);
const withChecks = stabScore([[1, 100, 0, 0, 0, 0, 60000, 50, 0, 0]], k);
const feedFailed = stabChecks({ checks: { now: 100000, feed_ok_at: 90000, feed_fail_at: 99000 } });
const oldFeed = stabChecks({ checks: { now: 900000, feed_ok_at: 90000 } });
const rowsText = stabCheckRows(stabChecks({ checks: {} })).map(r => r[1]);
TUN = { name: 'Wireguard0', state: 'down' };
const off = stabChecks(D);
const rows = [[1790630000, 120, 0, 3, 2, 0, 50000, 80, 0, 0], [1790633600, 118, 2, 5, 3, 1, 14000, 420, 1, 1]];
const a = stabScore(rows);
const b = stabScore([[1, 100, 0, 0, 0, 0, 60000, 50, 0, 0]]);
const c = stabRows({state: {now: 2000, started: 1000, samples: 5, dns_ok: 9, dns_fail: 1, actions_ok: 0, actions_fail: 0, mem_min_kb: 50000}, hours: []}, 86400);
console.log(JSON.stringify({a, b, c, none: stabScore([]), ev: stabEvent('ACT|leak|awg-t0|rss_kb=70010|restart'), mr: stabEvent('MEM_RESTART|panel|rss_kb=1')}));
"""
script_end = """
console.log(JSON.stringify({k: [k.tunnel, k.feed, k.https, k.rci], noDns, withChecks, feedFailed: [feedFailed.feed, feedFailed.https], oldFeed: [oldFeed.feed, oldFeed.https],
  off: [off.tunnel, off.off], rowsText, noCount: noCount.rci}));
"""
lines = subprocess.run(["node", "-e", script + script_end], text=True, capture_output=True, check=True).stdout.splitlines()
out, more = json.loads(lines[0]), json.loads(lines[1])
# Tunnel 3 of 4, feed answered, HTTPS fine (the feed came over it), Keenetic refused 2 of 200
# requests of the day (fix.30: a share, not «more than 10 - 0%»); without the counter a curve.
if more["k"] != [0.75, 1, 1, 0.99]:
    fail(f"checks: {more['k']}")
if more["noCount"] != 0.5:
    fail(f"20 refusals without the counter: {more['noCount']}")
if more["noDns"]["index"] is not None:
    fail(f"without DNS checks and memory less than half is known: no index, not 100%: {more['noDns']}")
want2 = round(100 * (28 + 14 + 14 + 14 + 10 * 0.75 + 10 + 5 + 5 * 0.99) / 100)
if more["withChecks"]["index"] != want2:
    fail(f"index with the checks: {more['withChecks']} want {want2}")
if more["feedFailed"] != [0, 1] or more["oldFeed"] != [None, None]:
    fail(f"feed: the last attempt failed - 0; nothing for two days - not checked: {more}")
if more["off"] != [None, True]:
    fail(f"a tunnel switched off by the owner is not counted: {more['off']}")
if more["rowsText"] != ["не проверено"] * 4:
    fail(f"nothing known - «не проверено»: {more['rowsText']}")
a = out["a"]
# dns 238/240; programs: 1 of 2 hours without a program gone or a leak (fix.30: hours, not minus
# 10% each); repairs by cases: no hour where nothing helped; memory 1 of 2 hours short.
want = round(100 * (0.4 * 238 / 240 + 0.2 * 0.5 + 0.2 * 1 + 0.2 * 0.5))
if a["index"] != want or a["downs"] != 1 or a["leaks"] != 1 or a["low"] != 1 or a["hours"] != 2:
    fail(f"index of two hours: {a} want {want}")
if out["b"]["index"] != 100 or out["none"] is not None:
    fail(f"a clean hour is 100, no hours is no index: {out['b']} {out['none']}")
if out["c"] != [[1000, 9, 1, None, 0, 0, 50000, None, 0, 0]]:
    fail(f"the running hour from the watcher's totals: {out['c']}")
if out["ev"] != "AmneziaWG, туннель 0: утечка памяти (70010 КБ), перезапущен" or out["mr"] != "Панель VWARD: утечка памяти, перезапущен":
    fail(f"events in words: {out['ev']} / {out['mr']}")
for need in ("'d-stability': { title: 'Стабильность', parent: 'system', data: ['stab'] }", "stab: () => apiGet('stability')",
             "['Стабильность', sc && sc.index != null ? sc.index + '% за сутки' : S.stab ? 'не проверено'", "'d-stability'() {"):
    if need not in js:
        fail(f"the Panel lacks {need!r}")
if not re.search(r"\|stability(\|[a-z-]+)*\) ;;", (ROOT / "web/cgi-bin/api.cgi").read_text()):
    fail("the API accepts action=stability")
print("STABILITY_PAGE=PASS")
