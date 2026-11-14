#!/usr/bin/env python3
"""One style across the Panel (owner 13.11.2026).

A choice of up to four fixed values is the Panel's slider (as in Smart DNS), not a drop-down list:
  * segSel draws the slider over a hidden select that keeps the attribute, the value and its «change»
    handler (the checks and the router's answer stay the select's);
  * no sel(...) with a literal list of four values or fewer is left; longer lists of fixed values were
    cut to four (the WAN recovery, the update interval); a list of tunnels stays a list;
  * one switch for the whole Panel (one .switch rule, no size of its own anywhere);
  * the words of a part that can be switched off are «Выкл · Песочница · Вкл» (CLAUDE.md).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
CSS = (ROOT / "web/assets/vward-console.css").read_text(encoding="utf-8")


def fail(m):
    raise SystemExit(f"CONSOLE_UI_STYLE=FAIL: {m}")


if "const segSel = (attr, label, opts, value) =>" not in JS or "sel(attr + ' hidden', label, opts, value)" not in JS:
    fail("RED: no slider over a select")
if "sl.dispatchEvent(new Event('change', { bubbles: true }))" not in JS or "t.dataset.seg.startsWith('sel:')" not in JS:
    fail("a tap on the slider must fire the select's own «change»")
# No drop-down of four fixed values or fewer.
for m in re.finditer(r"\bsel\(([^;]*?)\)", JS):
    arg = m.group(1)
    lit = re.search(r"\[\s*(\[[^\[\]]*\](?:\s*,\s*\[[^\[\]]*\])*)\s*\]", arg)
    if lit and arg.lstrip().startswith(("'data-", '"data-')) and "withCur(" not in arg and ".concat(" not in arg:
        n = len(re.findall(r"\[[^\[\]]*\]", lit.group(1)))
        if 1 < n <= 4:
            fail(f"RED: a drop-down of {n} fixed values, the slider is for it: {arg[:120]}")
for gone in ("counts(10)", "counts(6)", "counts(24)", "[2, 'раз в 2 минуты']", "[10800, '3 часа']"):
    if gone in JS:
        fail(f"a long list of fixed values was cut to four: {gone!r} is back")
if len(re.findall(r"(?m)^\.switch\{", CSS)) != 1 or re.search(r"\.switch\{[^}]*width:(?!42px)", CSS.replace(".switch{position:relative;display:inline-block;width:42px;height:24px;flex:none}", "")):
    fail("one switch size for the whole Panel")
if "[['off', 'Выкл'], ['check', 'Песочница'], ['active', 'Вкл']]" not in JS:
    fail("an ads source's modes are «Выкл · Песочница · Вкл»")
# The slider's select is never seen: no dropdown button of its own, hidden by the style too.
if "querySelectorAll('select.input:not([data-dd]):not([hidden])')" not in JS or ".seg-sel>select{display:none!important}" not in CSS:
    fail("RED: the select under a slider showed beside it")
# Neighbouring sections with one sign (the audit of 13.11.2026 over all the pages): their own signs.
for need in ("[/^Туннели$/, 'link']", "[/^Домены через VPN/, 'list']", "[/^Подсети через VPN/, 'route']", "[/^Агенты$/, 'auto']",
             "[/^Обслуживание$/, 'tools']", "[/^Состояние$/, 'pulse']", "[/^Устройство$/, 'cpu']", "[/^Оформление$/, 'sun']", "[/^Восстановление интернета/, 'undo']"):
    if need not in JS:
        fail(f"a section's own sign is gone: {need}")
print("CONSOLE_UI_STYLE=PASS")
