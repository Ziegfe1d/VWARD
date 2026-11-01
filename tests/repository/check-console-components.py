#!/usr/bin/env python3
"""«Компоненты» (owner 2026-11-01): equal components in three groups, one state model.

Installed / selected / enabled / running / works / known are separate facts; the user sees
Работает, Установлен, Выключен, Не используется, Не установлен, Не работает, Нет связи or
Нет данных. Green only when the work is confirmed; never green from a process alone, from
unknown data, from the browser's copy or after the router stopped answering. New Entware
components (dnsmasq, sing-box) are never selected by themselves."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_COMPONENTS=FAIL: {message}")


page = JS[JS.index("  utils() {"):JS.index("  'd-dnsmasq'()")]
for group in ("'DNS и фильтрация'", "'VPN-движки'", "'Системные службы'"):
    if "panel(" + group not in page:
        fail(f"group {group} missing")
for name, desc in (("AdGuard Home", "DNS и фильтрация"), ("dnsmasq", "DNS и кэширование"), ("Xray", "VLESS, Trojan"),
                   ("AmneziaWG", "VPN-туннели"), ("sing-box", "Сетевые протоколы"),
                   ("Контроль состояния", "Мониторинг VWARD"), ("Захват DNS-запросов", "Автоподбор доменов")):
    if f"'{name}'" not in page or f"'{desc}'" not in page:
        fail(f"{name} - «{desc}» missing")
for word in ("Основной", "Альтернативный", "Отключён"):
    if word in page:
        fail(f"no «{word}» on «Компоненты»")
# Every component opens its card.
for slug in ("'d-agh'", "'d-dnsmasq'", "'d-doh'", "'d-vless'", "'d-awg'", "'d-singbox'", "'d-stability'", "'d-dnscap'"):
    if slug not in page:
        fail(f"no card link {slug}")
# sing-box serves no tunnel until the owner moves one: never selected here.
if "pkgFacts('sing-box-go'), { selected: false }" not in page:
    fail("sing-box must not be selected by itself")
if not shutil.which("node"):
    print("CONSOLE_COMPONENTS=PASS (node not found: model not run)")
    sys.exit(0)


def grab(start, end="\n}\n"):
    i = JS.index(start)
    return JS[i:JS.index(end, i) + len(end)]


def stmt(start):
    i = JS.index(start)
    return JS[i:JS.index(";\n", i) + 2]


code = "".join([grab("const CS = {", ";\n"), grab("function compStatus(f) {"), stmt("const sentinelFacts = "),
                stmt("const dnscapFacts = "), stmt("const dohFacts = "), stmt("const dnsMode = "), grab("const pkgFacts = ", "\n};\n")])
harness = """
let STATUS = {}; const S = { status: {}, cached: {} }; const st = () => STATUS;
""" + code + """
const out = {}, cs = f => compStatus(f).join('|');
// The model on its own: every state, unknown first.
out.model = {
  unknown: cs({ known: false, installed: true, selected: true, running: true, works: true }),
  missing: cs(null),
  none: cs({ known: true, installed: false }),
  off: cs({ known: true, installed: true, enabled: false, selected: true, running: true, works: true }),
  installed: cs({ known: true, installed: true, selected: false, running: false }),
  unused: cs({ known: true, installed: true, selected: false, running: true }),
  works: cs({ known: true, installed: true, selected: true, running: true, works: true }),
  bad: cs({ known: true, installed: true, selected: true, running: false, works: false }),
  nolink: cs({ known: true, installed: true, selected: true, running: true, works: false, vpn: true }),
  nodata: cs({ known: true, installed: true, selected: true, running: true, works: null })
};
// Контроль состояния: a process without a fresh check is not green; a stale one is red.
const k = true;
out.sentinel = [cs(sentinelFacts({ installed: true, running: true, fresh: true }, k)), cs(sentinelFacts({ installed: true, running: true, fresh: false }, k)),
  cs(sentinelFacts({ installed: true, running: true }, k)), cs(sentinelFacts({ installed: true, running: false, fresh: true }, k)),
  cs(sentinelFacts({}, k)), cs(sentinelFacts({ installed: true, running: true, fresh: true }, false))];
// Захват DNS-запросов: running but nothing captured for 15 minutes is «Нет данных», not green.
out.dnscap = [cs(dnscapFacts({ installed: true, running: true, fresh: true }, k)), cs(dnscapFacts({ installed: true, running: true, fresh: null }, k)),
  cs(dnscapFacts({ installed: true, running: false }, k)), cs(dnscapFacts({ installed: false }, k))];
out.doh = [cs(dohFacts({ installed: true, running: true }, k)), cs(dohFacts({ installed: true, running: false }, k))];
// Entware packages from the router's component report (TSV through the API).
const comp = (id, state) => ({ id, source: 'entware', state, version: state === 'not-installed' ? '-' : '1.0', label: '' });
const pkg = (states, mode, who, sel) => {
  STATUS = { services: { components: states.concat(mode ? [{ id: 'dns-mode', state: mode }] : []) } };
  const f = Object.assign(pkgFacts(who), { selected: sel(dnsMode()) });
  if (f.selected) f.works = f.running ? null : false;
  return cs(f);
};
const dm = m => m === 'dnsmasq';
out.dnsmasq = {
  absent: pkg([comp('dnsmasq-full', 'not-installed')], 'agh', 'dnsmasq-full', dm),
  fresh: pkg([comp('dnsmasq-full', 'installed-off')], 'agh', 'dnsmasq-full', dm),
  noMode: pkg([comp('dnsmasq-full', 'installed-off')], '', 'dnsmasq-full', dm),
  runningAside: pkg([comp('dnsmasq-full', 'running-unverified')], 'agh', 'dnsmasq-full', dm),
  selectedDown: pkg([comp('dnsmasq-full', 'installed-off')], 'dnsmasq', 'dnsmasq-full', dm),
  selectedUp: pkg([comp('dnsmasq-full', 'running-unverified')], 'dnsmasq', 'dnsmasq-full', dm),
  unknown: pkg([comp('dnsmasq-full', 'unknown')], 'agh', 'dnsmasq-full', dm),
  noReport: pkg([], 'agh', 'dnsmasq-full', dm)
};
out.singbox = [pkg([comp('sing-box-go', 'installed-off')], 'agh', 'sing-box-go', () => false),
  pkg([comp('sing-box-go', 'running-unverified')], 'agh', 'sing-box-go', () => false)];
// The browser's copy, the router not answering yet / any more: no verdict.
S.cached = { status: Date.now() };
out.cached = pkg([comp('dnsmasq-full', 'running-unverified')], 'dnsmasq', 'dnsmasq-full', dm);
S.cached = {}; S.status = null;
out.lost = pkg([comp('dnsmasq-full', 'running-unverified')], 'dnsmasq', 'dnsmasq-full', dm);
out.defaultMode = (STATUS = {}, dnsMode());
console.log(JSON.stringify(out));
"""
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr.strip()[-600:])
got = json.loads(r.stdout)
want = {
    "model": {"unknown": "|Нет данных", "missing": "|Нет данных", "none": "off|Не установлен", "off": "off|Выключен",
              "installed": "off|Установлен", "unused": "off|Не используется", "works": "ok|Работает", "bad": "crit|Не работает",
              "nolink": "crit|Нет связи", "nodata": "|Нет данных"},
    "sentinel": ["ok|Работает", "crit|Не работает", "|Нет данных", "crit|Не работает", "off|Не установлен", "|Нет данных"],
    "dnscap": ["ok|Работает", "|Нет данных", "crit|Не работает", "off|Не установлен"],
    "doh": ["|Нет данных", "off|Установлен"],
    "dnsmasq": {"absent": "off|Не установлен", "fresh": "off|Установлен", "noMode": "off|Установлен",
                "runningAside": "off|Не используется", "selectedDown": "crit|Не работает", "selectedUp": "|Нет данных",
                "unknown": "|Нет данных", "noReport": "|Нет данных"},
    "singbox": ["off|Установлен", "off|Не используется"],
    "cached": "|Нет данных", "lost": "|Нет данных", "defaultMode": "agh",
}
for key, value in want.items():
    if got.get(key) != value:
        fail(f"{key}: {json.dumps(got.get(key), ensure_ascii=False)} != {json.dumps(value, ensure_ascii=False)}")
# Nothing on the page is green unless compStatus said so: no literal 'ok' pill for the rows.
if "'Работает', 'ok'" in page:
    fail("a literal «Работает» on «Компоненты»")
print("CONSOLE_COMPONENTS=PASS")
