#!/usr/bin/env python3
"""r-lists (owner 2026-11-01): «Доменные списки» - «Авто / Через VPN / Напрямую» for all and for
each list VWARD manages, «Удалить выбранные» with an exact preview, 0 lists as a normal state.
Keenetic's own, service and unknown lists are never offered for mass actions."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_LISTS_CENTER=FAIL: {message}")


page = JS[JS.index("  lists() {"):JS.index("  'd-wanrec'()")]
for need in ("Доменных списков пока нет", "VWARD сам списков не создаёт и чужие не переносит", "'Списки VWARD'",
             "'Все списки VWARD'", "'Удалить выбранные'", "data-confirm=\"lists-del\"", "'Другие списки'"):
    if need not in page:
        fail(f"lists page: {need} missing")
if "l.managed && l.name !== (cfgRoute().group || prof().policy_group)" not in page:
    fail("only managed lists (not «Мои домены») get the switches")
# The mass switch skips service lists and lists already on the chosen way.
if "l.managed && !svcOf(l.name)" not in JS or "listMode(l) !== v" not in JS:
    fail("«Все списки» must only touch managed non-service lists that differ")
# Taking a list under management is explicit and confirmed; the API asks for the token.
if "'list-adopt': c => cfgSet({ op: 'list-adopt', target: c.name, value: '1', confirm: 'LIST_ADOPT' }" not in JS:
    fail("list-adopt confirmation")
if 'list-adopt) set -- "$OP" "$TARGET" "$VALUE"; [ "$VALUE" != 1 ] || REQUIRED=LIST_ADOPT ;;' not in API:
    fail("API: list-adopt needs LIST_ADOPT")
if "managed: (($managed | index([$n]) != null) and ($unmanaged | index([$n]) == null))" not in API:
    fail("API: managed flag")
if not shutil.which("node"):
    print("CONSOLE_LISTS_CENTER=PASS (node not found: texts not run)")
    sys.exit(0)


def stmt(start, end=";\n"):
    i = JS.index(start)
    return JS[i:JS.index(end, i) + len(end)]


code = stmt("const LIST_MODES = ") + stmt("const listMode = ") + stmt("function listDelText(ls) {", "\n}\n")
harness = """
const viaIs = (l, v) => l.via === v; const fmtInt = n => String(n);
const plural = (n, a, b, c) => { n = Math.abs(n) % 100; const m = n % 10; return n > 10 && n < 20 ? c : m > 1 && m < 5 ? b : m === 1 ? a : c; };
""" + code + """
const L = (name, via, watch, count, description) => ({ name, via, watch, count, description });
console.log(JSON.stringify({
  modes: [listMode(L('a', 'vpn', true)), listMode(L('b', 'vpn', false)), listMode(L('c', 'bypass', false)), listMode(L('d', 'none', false))],
  one: listDelText([L('domain-list5', 'vpn', false, 3, 'Игры')]),
  two: listDelText([L('x', 'bypass', false, 1, ''), L('y', 'vpn', true, 21, 'Видео')])
}));
"""
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr.strip()[-500:])
got = json.loads(r.stdout)
if got["modes"] != ["auto", "vpn", "bypass", ""]:
    fail(f"modes: {got['modes']}")
if got["one"] != ("Удалить 1 список (Игры)? 3 домена перестанут подбираться; 1 список сейчас идёт через VPN и пойдёт напрямую. "
                  "Перед удалением каждого списка сохраняется копия настроек VWARD; вернуть список одной кнопкой нельзя."):
    fail(f"preview of one: {got['one']}")
if not got["two"].startswith("Удалить 2 списка (x, Видео)? 22 домена"):
    fail(f"preview of two: {got['two']}")
print("CONSOLE_LISTS_CENTER=PASS")
