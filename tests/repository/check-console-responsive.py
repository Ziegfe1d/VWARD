#!/usr/bin/env python3
"""Console CSS contract: one layer of rules, both themes, phone layout."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
css = (ROOT / "web/assets/vward-console.css").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def blocks(text):
    """Yield (context, selector) for every rule; context is the enclosing @media or ''."""
    depth, i, context, start = 0, 0, [], 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            head = text[start:i].strip()
            if head.startswith("@"):
                context.append(head)
            else:
                yield (" ".join(context), head)
                end = text.index("}", i)
                i, start = end + 1, end + 1
                continue
            start = i + 1
        elif ch == "}":
            if context:
                context.pop()
            start = i + 1
        i += 1


body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
seen = {}
for context, selector in blocks(body):
    for single in (s.strip() for s in selector.split(",")):
        key = (context, single)
        seen[key] = seen.get(key, 0) + 1
duplicates = sorted(f"{c or 'base'}: {s}" for (c, s), n in seen.items() if n > 1 and not c.startswith("@keyframes"))
# The dark palette is declared twice on purpose: for the OS preference and for the explicit toggle.
duplicates = [d for d in duplicates if ":root" not in d]
if duplicates:
    fail("селектор задан повторно в одном контексте (правьте существующее правило): " + "; ".join(duplicates[:8]))

for marker in (
    ":root{", '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])', ':root[data-theme="dark"]',
    "color-scheme:dark", "body{height:100%;margin:0;background:var(--bg)",
    "@media (min-width:900px)", "@media (max-width:379px)",
    ".tabbar{position:fixed", "border-radius:28px", "env(safe-area-inset-bottom,0px)",
    "user-select:none", ".kv-row.stack", ".cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))",
    "@media (hover:hover)", "@media (prefers-reduced-motion:reduce)", ":focus-visible",
):
    if marker not in css:
        fail(f"нет обязательного правила: {marker}")

colors = re.findall(r"#[0-9a-fA-F]{3,8}\b", body.split("*{box-sizing", 1)[1])
if len(colors) > 6:
    fail("цвета заданы вне токенов: " + ", ".join(colors[:6]))

print("CONSOLE_RESPONSIVE=PASS")
