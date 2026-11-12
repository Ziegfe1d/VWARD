#!/usr/bin/env python3
"""r-lists (owner 2026-11-01): «Доменные списки» - a way for all and for each list VWARD manages,
0 lists as a normal state; Keenetic's own, service and unknown lists are never offered for mass actions.
Owner 2026-11-02: ONE list of all lists, every row opens its list (a managed list was a row without a
link - Supercell could not be opened), «Авто | VPN | DNS | Провайдер», «Разные» when the ways differ,
«под управлением VWARD» as a small mark, no check boxes or «Удалить выбранные» on this page."""

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
# fix.38 (owner 12.11.2026, mock-up v3): the way in words under each list, one search over the
# domains of every list, the path switch on a list's own page; «Все списки VWARD» stays.
for need in ("Доменных списков пока нет", "VWARD сам чужих списков не переносит", "ctrlRow('Все списки VWARD'",
             "' · маршрут: ' + listRoute(l)", "' · список VWARD'", "' · не под управлением VWARD'",
             "data-list-filter placeholder=\"Найти домен\"", "data-find=", "ordered.map(row)"):
    if need not in page:
        fail(f"lists page: {need} missing")
for gone in ("'Удалить выбранные'", "data-list-pick", "'Другие списки'", "panel('Списки VWARD'"):
    if gone in page:
        fail(f"RED: lists page still has {gone} (owner 02.11)")
if "const LIST_MODES = [['auto', 'Авто'], ['vpn', 'VPN'], ['dns', 'DNS'], ['bypass', 'Провайдер']];" not in JS:
    fail("the ways are «Авто | VPN | DNS | Провайдер» everywhere")
# fix.38.1 (owner 12.11.2026): one slider on every list's page; a list made outside VWARD is taken under
# management first (the owner confirms), then gets the way; VWARD's own list opens its own page.
for need in ("let rows = ctrlRow('Маршрут', choiceSlider('list-mode:' + l.name, listModes(l), mode,",
             "if (l && !l.managed && !l.dns_mode) { confirm = { id: 'list-adopt', name: g, then: v }; render(); } else listModeSet(g, v); }",
             "if (x && x.ok && c.then) return listModeSet(c.name, c.then);",
             "if (listOwn(l)) return ownListPage(l);", "data-go=\"l-' + esc(l.name) + '\""):
    if need not in JS:
        fail(f"list page: {need!r} is missing")
# fix.38.1 (owner 12.11.2026): technical words, no «Куда идёт», «сюда VWARD…», «выбирает сам».
for gone in ("data-list-watch=", "data-list-bypass=", "go('d-mydomains')", "'Взять под управление'", "ctrlRow('Куда идёт'",
             "сюда VWARD добавляет", "VWARD этот список не меняет", "'VWARD выбирает сам"):
    if gone in JS:
        fail(f"list page: {gone!r} is back")
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


code = stmt("function listDnsWhy(l) {", "\n}\n") + stmt("function listModes(l) {", "\n") + stmt("const LIST_MODES = ") + stmt("const listMode = ") + stmt("function listDelText(ls) {", "\n}\n")
harness = """
const S={lists:{}},num=x=>Number(x),LISTBULK={busy:''};
const viaIs = (l, v) => l.via === v; const fmtInt = n => String(n);
const plural = (n, a, b, c) => { n = Math.abs(n) % 100; const m = n % 10; return n > 10 && n < 20 ? c : m > 1 && m < 5 ? b : m === 1 ? a : c; };
""" + code + """
const L = (name, via, watch, count, description) => ({ name, via, watch, count, description });
const blocked=listModes({domains:['example.com'],count:1}).find(x=>x[0]==='dns')[2];
S.lists={smartdns_state:'ready',doh_used:2,doh_limit:8};
const available=!listModes({domains:['example.com'],count:1}).find(x=>x[0]==='dns')[2];
S.lists.doh_used=8;
const full=listModes({domains:['example.com'],count:1}).find(x=>x[0]==='dns')[2];
console.log(JSON.stringify({
  dns: [blocked,available,full,listMode({dns_mode:true,via:'bypass'})],
  modes: [listMode(L('a', 'vpn', true)), listMode(L('b', 'vpn', false)), listMode(L('c', 'bypass', false)), listMode(L('d', 'none', false))],
  one: listDelText([L('domain-list5', 'vpn', false, 3, 'Игры')]),
  two: listDelText([L('x', 'bypass', false, 1, ''), L('y', 'vpn', true, 21, 'Видео')])
}));
"""
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr.strip()[-500:])
got = json.loads(r.stdout)
if got["dns"] != [True, True, True, "dns"]:
    fail(f"DNS readiness/slot guard: {got['dns']}")
if got["modes"] != ["auto", "vpn", "bypass", ""]:
    fail(f"modes: {got['modes']}")
if got["one"] != ("Удалить 1 список (Игры)? 3 домена перестанут подбираться; 1 список сейчас идёт через VPN и пойдёт напрямую. "
                  "Перед удалением каждого списка сохраняется копия настроек VWARD; вернуть список одной кнопкой нельзя."):
    fail(f"preview of one: {got['one']}")
if not got["two"].startswith("Удалить 2 списка (x, Видео)? 22 домена"):
    fail(f"preview of two: {got['two']}")
print("CONSOLE_LISTS_CENTER=PASS")
