#!/usr/bin/env python3
"""The Panel counts autopick's domains where the Go core keeps them (owner 12.11.2026: «Автоподбор
доменов: 0 доменов» while AdaptiveAuto held 60 - the Panel read the shell engine's file only).
config-data reads the AdaptiveAuto group in Keenetic; route-data reads the core's owned.json; the
shell engine's adaptive-persist.txt only when those are not at hand."""
import sys
from pathlib import Path
API = (Path(__file__).resolve().parents[2] / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
need = [
    "[ -z \"${RUNNING:-}\" ] || ADAPT=\"$(printf '%s\\n' \"$RUNNING\" | awk -v g=\"${ADAPTIVE_GROUP:-AdaptiveAuto}\"",
    "CORE_OWNED=${VWARD_CORE_OWNED:-/opt/var/lib/vward/core-adaptive/owned.json}",
    "ADAPTIVE_COUNT=\"$(\"$JQ\" -r '.names // {} | length' \"$CORE_OWNED\" 2>/dev/null)\"",
]
miss = [n for n in need if n not in API]
a = API.index("ADAPTIVE_COUNT= ADAPTIVE_RECENT="); b = API.index('wc -l 2>/dev/null < "$ADAPTIVE_PERSIST"')
if a > b:
    miss.append("the core's list is read after the shell engine's file")
if miss:
    print("ADAPTIVE_COUNT=FAIL:", miss); sys.exit(1)
print("ADAPTIVE_COUNT=PASS")
