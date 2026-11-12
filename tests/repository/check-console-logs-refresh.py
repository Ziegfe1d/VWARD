#!/usr/bin/env python3
"""fix.35.3: a failed journal refresh is not an empty journal.

02.11.2026 21:45: «Все» showed entries until 21:41:47, then «Журналы пусты», «Обновлено в 21:45:01»
and every source «не читается», while the exported file had the entries. loadLog('all') turned each
failed request into «Журнал недоступен…», mergeLogs found no dated entry and the empty result replaced
the last good timeline with a renewed time. Now: the last good text of each source and its time stay,
with a warning; «Журналы пусты» only when the sources answered so; one load at a time (the 15 s refresh
does not pile up requests, an older answer never overwrites a newer one); HTTP errors, a JSON error
instead of the text and a body that stops coming are failures. The functions run unchanged in node.
"""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_LOGS_REFRESH=FAIL: {message}")


def block(start, end_marker):
    a = JS.index(start)
    return JS[a:JS.index(end_marker, a)]


merge = JS[JS.index("function logTime"):JS.index("\n}\n", JS.index("function mergeLogs")) + 3]
loader = block("const LOGRUN = {}", "function logStamp(")
api_text = block("async function apiBody(", "async function apiGet(") + block("async function apiText(", "async function apiPost(")
script = r"""
const S = { logs: {}, loadedAt: {} }, LOGINFO = [], LOG_HOURS = 24, LOG_MAX = 1000, LOGMORE = {};
let logNewest = true, current = 'other', logTab = 'all', calls = 0, mode = {}, logShown = {}, logN = 50, editing = false;
const LOG_TABS = [{ id: 'wan', label: 'Интернет' }, { id: 'tunnel', label: 'VPN' }, { id: 'cron', label: 'Расписание' }];
const render = () => {}, $ = () => null, esc = x => String(x), ico = () => '', fmtTime = x => x, errText = x => x.error;
const sleep = ms => new Promise(r => setTimeout(r, ms));
// «Все» is one request (owner 12.11.2026): every source after its «@@VWARD-LOG name» line; a
// source the answer lacks is that source's failure, a request that fails is every source's.
async function apiText(action, p) {
  calls++; await sleep(20);
  if (p.name === 'all') {
    const names = LOG_TABS.filter(t => t.id !== 'cron').map(t => t.id);
    if (names.every(n => mode[n] === 'fail')) throw new Error('роутер не ответил за 20 секунд');
    return names.filter(n => mode[n] !== 'fail').map(n => '@@VWARD-LOG ' + n + '\n' + (mode[n] || '')).join('\n');
  }
  const m = mode[p.name];
  if (m === 'fail') throw new Error('роутер не ответил за 20 секунд');
  return m || '';
}
""" + merge + loader + r"""
(async () => {
  const out = {};
  mode = { wan: '2026-11-02 21:40:00+0300 class=HEALTHY', tunnel: '2026-11-02 21:41:47|OK' };
  await loadLog('all', true);
  out.first = S.logs.all; const at1 = S.loadedAt['log:all']; out.warn1 = LOGWARN.all;
  // Both requests fail: the timeline and its time stay, a warning says so, sources say «не обновился».
  mode = { wan: 'fail', tunnel: 'fail' };
  await sleep(5);
  await loadLog('all', true);
  out.afterFailure = S.logs.all; out.timeKept = S.loadedAt['log:all'] === at1; out.warn2 = LOGWARN.all;
  // After a failed refresh the automatic one waits (no request); the owner's own goes at once.
  calls = 0; await loadLog('all', true, true); out.backoffCalls = calls;
  out.states2 = LOGINFO.map(i => i.state);
  // One source fails: the other's new entries and the failed one's previous entries, with a warning.
  mode = { wan: '2026-11-02 21:50:00+0300 class=DOWN', tunnel: 'fail' };
  await loadLog('all', true);
  out.partial = S.logs.all; out.warn3 = LOGWARN.all; out.states3 = LOGINFO.map(i => i.state);
  // Every source answers «empty»: an empty window is said as such.
  mode = { wan: 'Журнал пуст: записей пока нет.', tunnel: 'За последние 24 ч записей нет.' };
  await loadLog('all', true);
  out.empty = S.logs.all; out.warn4 = LOGWARN.all;
  // No overlap: an automatic refresh while one runs starts nothing; the owner's request runs once more.
  mode = { wan: '2026-11-02 22:00:00+0300 a', tunnel: '2026-11-02 22:00:01|b' };
  calls = 0; LOGBACK.all = 0;
  const p1 = loadLog('all', true, true), p2 = loadLog('all', true, true), p3 = loadLog('all', true, true);
  out.samePromise = p1 === p2 && p2 === p3;
  await p1; out.autoCalls = calls;
  calls = 0;
  const q1 = loadLog('all', true); mode.wan = '2026-11-02 22:05:00+0300 newest'; const q2 = loadLog('all', true);
  await q1; out.ownerCalls = calls; out.latest = S.logs.all.includes('newest'); out.q = q1 === q2;
  // A fresh Panel whose first load fails: «не прочитаны», never «пусты».
  for (const k of Object.keys(LOGGOOD)) delete LOGGOOD[k];
  mode = { wan: 'fail', tunnel: 'fail' };
  await loadLog('all', true);
  out.fresh = S.logs.all;
  // One journal tab: a failure keeps its last good text with a warning.
  mode = { wan: '2026-11-02 22:10:00+0300 x' }; await loadLog('wan', true);
  mode = { wan: 'fail' }; await loadLog('wan', true);
  out.tab = S.logs.wan; out.tabWarn = LOGWARN.wan;
  console.log(JSON.stringify(out));
})();
"""
r = subprocess.run(["node", "-e", script], text=True, capture_output=True, env=os.environ | {"TZ": "Europe/Moscow"}, timeout=60)
if r.returncode:
    fail(r.stderr[-600:])
o = json.loads(r.stdout)
if "21:41:47" not in o["first"] or o["warn1"]:
    fail("first load: " + json.dumps(o))
if o["afterFailure"] != o["first"] or not o["timeKept"]:
    fail("RED: a failed refresh replaced the last good timeline or renewed its time: " + json.dumps(o))
if "не обновились" not in o["warn2"] or o["states2"] != ["stale", "stale"]:
    fail("the failure must be said, the sources «не обновился»: " + json.dumps(o))
if "21:50:00" not in o["partial"] or "21:41:47" not in o["partial"] or "1 из 2" not in o["warn3"] or o["states3"] != ["ok", "stale"]:
    fail("a partial failure: new entries plus the failed source's previous ones, with a warning: " + json.dumps(o))
if o["backoffCalls"] != 0:
    fail("the automatic refresh right after a failed one must wait: " + json.dumps(o))
if o["empty"] != "Журналы пусты" or o["warn4"]:
    fail("an empty window answered by the sources: " + json.dumps(o))
if not o["samePromise"] or o["autoCalls"] != 1:
    fail("RED: «Все» is one request, and refreshes must not pile up: " + json.dumps(o))
if o["ownerCalls"] != 2 or not o["latest"] or not o["q"]:
    fail("the owner's request during a run must run once more and end with the newest answer: " + json.dumps(o))
if not o["fresh"].startswith("Журналы не прочитаны") :
    fail("RED: a failed first load must not read «Журналы пусты»: " + json.dumps(o))
if "22:10:00" not in o["tab"] or "не обновился" not in o["tabWarn"]:
    fail("one journal: the last good text stays with a warning: " + json.dumps(o))

# apiText: HTTP errors, a JSON error instead of the text and a stalled body are failures.
script2 = r"""
const API = '/cgi-bin/api.cgi', errText = x => 'код ' + x.error;
let next;
async function apiFetch() { return next; }
const realSetTimeout = setTimeout;
global.setTimeout = (f, ms) => realSetTimeout(f, Math.min(ms, 30));
""" + api_text + r"""
(async () => {
  const res = [];
  for (const [ok, status, body] of [[false, 502, Promise.resolve('x')], [true, 200, Promise.resolve('{"ok":false,"error":"auth_required"}')],
                                    [true, 200, new Promise(() => {})], [true, 200, Promise.resolve('2026-11-02 21:00:00 ok')]]) {
    next = { ok, status, text: () => body };
    try { res.push('ok:' + await apiText('log', { name: 'wan' })); } catch (e) { res.push('err:' + e.message); }
  }
  // fix.35.4: a JSON answer whose body is aborted by apiFetch's 20 s ends the wait with an error.
  const aborted = Object.assign(new Error('aborted'), { name: 'AbortError' });
  let done = 0;
  try { await apiJson({ text: () => Promise.reject(aborted), vwardDone: () => { done++; } }); res.push('json:ok'); } catch (e) { res.push('json:' + e.message); }
  res.push('timer:' + done);
  console.log(JSON.stringify(res));
})();
"""
r = subprocess.run(["node", "-e", script2], text=True, capture_output=True, timeout=60)
if r.returncode:
    fail(r.stderr[-600:])
got = json.loads(r.stdout)
if not (got[0].startswith("err:") and "502" in got[0] and got[1] == "err:код auth_required" and got[2].startswith("err:")
        and "20 секунд" in got[2] and got[3] == "ok:2026-11-02 21:00:00 ok"
        and got[4] == "json:роутер не передал ответ за 20 секунд" and got[5] == "timer:1"):
    fail("apiText must fail on HTTP errors, JSON errors and a stalled body: " + json.dumps(got))
# owner 12.11.2026: nothing loads by itself; «Показать журнал» asks for N entries, «Показать ещё» for N more.
for need in ("apiText('log', { name: 'all', count: want, hours: LOG_HOURS })", "else if (a === 'log-show') { logShown[logTab] = logN;",
             "Math.min(LOG_MAX, (logShown[logTab] || logN) + logN)", 'id="logSrc"', 'id="logWarn"', "Показать журнал", "Обновить журнал"):
    if need not in JS:
        fail("the Panel lacks " + need)
if "loadLog(logTab, true, true)" in JS or "обновляется само" in JS:
    fail("RED: «Журналы» must not refresh by themselves")
print("CONSOLE_LOGS_REFRESH=PASS")
