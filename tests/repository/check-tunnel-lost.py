#!/usr/bin/env python3
"""A tunnel whose settings went with the USB drive (owner 12.11.2026, Viva): it cannot be switched
on, so its page offers no «Включить» and no switch, says once «Нет настроек» and leads to
«Добавить туннель» first; its row in the list does not repeat the status."""
import sys
from pathlib import Path

JS = (Path(__file__).resolve().parents[2] / "web/assets/vward-console.js").read_text(encoding="utf-8")
need = [
    "if (tunLost(t)) return '';",
    "const lost = tunLost(t), off = tunOff(t) && !lost,",
    "const use = managed || tunLost(t) ? '' :",
    "return (lost ? mp[0] : '') + (gOff ? panel('Выключен агентом'",
    "(managed || lost ? '' : sw('data-tun-onoff=",
    "(lost ? '' : mp[0])",
    "panel('Нет настроек', '<p class=\"panel-desc\">Настройки туннеля хранились на флешке",
]
miss = [n for n in need if n not in JS]
a = JS.find("panel('Нет настроек'"); b = JS.find("];", a)
if a < 0 or "btn('tunnel-create', 'plus', 'Добавить туннель'" not in JS[a:b]:
    miss.append("«Добавить туннель» in the panel")
if "'настройки не найдены'" in JS:
    miss.append("the row still repeats «настройки не найдены»")
if miss:
    print("TUNNEL_LOST=FAIL:", "; ".join(miss)); sys.exit(1)
print("TUNNEL_LOST=PASS")
