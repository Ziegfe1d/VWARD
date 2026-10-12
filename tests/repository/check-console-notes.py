#!/usr/bin/env python3
"""The bell's notification center (fix.26, owner 2026-10-12).

API (action=notes): the history is kept on the router, newest first, the last 200; one key
(a warning several open Panels see) is written once in 6 hours; «Прочитать все» stamps
read_at; a note is one line whatever it holds; bad values and unknown fields are refused.
Panel: pop-ups top right under the bell (none at the bottom), the bell has «Требует внимания» and
«История» with «Прочитать все», input errors are said under the field, not in a pop-up."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_NOTES=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)

    def api(method, fields=None):
        body = urllib.parse.urlencode(fields or {})
        e = {"PATH": os.environ["PATH"], "REQUEST_METHOD": method, "QUERY_STRING": "action=notes", "JQ": shutil.which("jq"),
             "VWARD_PROFILE_LIB": "/nonexistent", "VWARD_CONSOLE_NOTES": str(t / "notes"), "VWARD_CONSOLE_AUTH_CONF": str(t / "auth.conf"),
             "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body.encode())), "HTTP_X_VWARD_REQUEST": "console"}
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e, input=body, text=True, capture_output=True, timeout=30)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    d = api("GET")
    if d != {"ok": True, "read_at": 0, "items": []}:
        fail(f"an empty history: {d}")
    d = api("POST", {"op": "add", "sev": "ok", "title": "Сохранено\tс\nпереносом", "text": "строка \"в кавычках\" \\ и <b>", "to": "u-vward", "key": ""})
    it = d["items"][0]
    if it["title"] != "Сохранено с переносом" or it["text"] != "строка \"в кавычках\" \\ и <b>" or it["to"] != "u-vward" or it["sev"] != "ok":
        fail(f"a note is not kept as one line as it was: {it}")
    if (t / "notes/notes.tsv").stat().st_mode & 0o077:
        fail("the history is readable by others")
    for bad in ({"sev": "boom"}, {"to": "../x"}, {"key": "a b"}, {"title": ""}, {"op": "drop"}, {"extra": "1"}):
        f = {"op": "add", "sev": "warn", "title": "x", "text": "", "to": "", "key": ""}
        f.update(bad)
        if api("POST", f).get("ok") is not False:
            fail(f"a bad note is taken: {bad}")
    # One warning seen by two Panels: written once.
    w = {"op": "add", "sev": "warn", "title": "VPN не в сети", "text": "DE", "to": "vpn", "key": "n1abc"}
    api("POST", w)
    if api("POST", w).get("result") != "unchanged" or len(api("GET")["items"]) != 2:
        fail("the same warning is written twice")
    # The newest first, never more than 200.
    for i in range(230):
        api("POST", {"op": "add", "sev": "info", "title": f"n{i}", "text": "", "to": "", "key": ""})
    items = api("GET")["items"]
    if len(items) > 200 or items[0]["title"] != "n229" or len((t / "notes/notes.tsv").read_text().splitlines()) > 220:
        fail(f"the history is not the last 200, newest first: {len(items)}, {items[0]['title']}")
    d = api("POST", {"op": "read"})
    if not d.get("ok") or d["read_at"] < 1_700_000_000:
        fail(f"«Прочитать все» is not kept: {d.get('read_at')}")
    # The router's own agents write to the same history (the Panel may be closed).
    lib = ROOT / "components/runtime/lib/vward-device-profile.sh"
    r = subprocess.run(["sh", "-c", '. "$1"; vward_note warn "«{t}» выключен агентом VPN" "строка\tс табом" t-Wireguard0', "sh", str(lib)],
                       env=dict(os.environ, VWARD_CONSOLE_NOTES=str(t / "notes")), capture_output=True, text=True, timeout=30)
    top = api("GET")["items"][0]
    if r.returncode or top["title"] != "«{t}» выключен агентом VPN" or top["text"] != "строка с табом" or top["to"] != "t-Wireguard0" or top["sev"] != "warn":
        fail(f"an agent's note is not in the history: {top} {r.stderr[:200]}")
    # Behind the Panel's login like every action.
    (t / "auth.conf").write_text("AUTH_ENABLED=1\n")
    if api("GET").get("error") != "auth_required":
        fail("the history is open without the login")

guard = (ROOT / "components/tunnel-guard/scripts/vward-tunnel-guard.sh").read_text()
if 'vward_note warn "«{t}» выключен агентом VPN"' not in guard or 'vward_note ok "«{t}» снова включён агентом VPN"' not in guard:
    fail("the VPN agent does not write its switch-off and switch-on to the history")
if 'vu_note ok "Установлено обновление' not in (ROOT / "components/update-engine/vward-update.sh").read_text():
    fail("the updater does not write an installed update to the history")
JS = (ROOT / "web/assets/vward-console.js").read_text()
CSS = (ROOT / "web/assets/vward-console.css").read_text()
for need in ("function popup(n)", "function noteKeep(n, quiet)", "notes: () => apiGet('notes')", "data-act=\"notes-read\">Прочитать все",
             "'<div class=\"result-group\">Требует внимания</div>'", "'<div class=\"result-group\">История</div>'", "notesWatch(active)",
             "function fieldErr(form, msg)", "if (!n.own) noteKeep(", "const noteTun = ", "Роутер отвечает медленно…", "'Обновление…'", "card skel"):
    if need not in JS:
        fail(f"the Panel lacks {need!r}")
sub = JS[JS.index("async function onSubmit(e, f) {"):JS.index("/* ---------- Тема и обновление данных")]
if re.search(r"toast\([^;]*\); return;", sub):
    fail("an input error goes to a pop-up instead of under its field")
toasts = re.search(r"#toasts\{[^}]*\}", CSS)
if not toasts or "top:" not in toasts.group(0) or "bottom:" in toasts.group(0) or re.search(r"\.toast\{[^}]*bottom:", CSS):
    fail("pop-ups are not top right under the bell")
print("CONSOLE_NOTES=PASS")
