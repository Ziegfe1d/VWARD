#!/usr/bin/env python3
"""VLESS servers by country (fix.28.2): the country of a server from the flag at the start of its
name; countries switched off are never tried by a failover; without «cross» a failover stays in
the server's own country; the Panel shows the servers on the tunnel's page at once, grouped by
country or as one list, sorted by answer time, name or country. Synthetic servers only.
fix.33.1: a change answers «result=changed» (it was «changedcross», which the Panel took for a
failure); an answer the Panel does not know leaves its last line with the error in the journal."""

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "components/tunnel-guard/scripts/vward-vless-engine.sh"
SRC = ENGINE.read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"VLESS_COUNTRIES=FAIL: {message}")


def func(name):
    return re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SRC, re.S | re.M).group(0)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "etc").mkdir()
    (tmp / "etc/tunnels.tsv").write_text("2\tOpkgTun2\t192.0.2.10:443\n")
    lib = (f'ENGINE_ETC="{tmp}/etc"; TUNNELS="$ENGINE_ETC/tunnels.tsv"\n'
           'die() { printf "error=%s\\n" "$1"; exit "${2:-1}"; }\nlog() { :; }\n'
           'row_of() { awk -F"\\t" -v p="$1" \'$2 == p {print; exit}\' "$TUNNELS"; }\n'
           + func("cc") + "countries_get() { sed -n \"s/^$2=//p\" \"$ENGINE_ETC/v$1.countries\" 2>/dev/null | tail -n 1; }\n" + func("op_countries"))

    def sh(script):
        return subprocess.run(["sh", "-c", lib + script], text=True, capture_output=True, timeout=30).stdout

    names = {"\U0001F1E9\U0001F1EA Germany 1": "DE", "\U0001F1F3\U0001F1F1 Netherlands": "NL", "Plain server": "--", "\U0001F1FA\U0001F1F8": "US"}
    for n, want in names.items():
        got = sh(f"cc '{n}'").strip()
        if got != want:
            fail(f"country of {n!r}: {got!r}, want {want}")
    out = sh("op_countries OpkgTun2")
    if out != "info.countries.off=\ninfo.countries.cross=1\nresult=checked\n":
        fail(f"defaults: {out!r}")
    sh("op_countries OpkgTun2 DE 0 >/dev/null; op_countries OpkgTun2 NL 0 >/dev/null; op_countries OpkgTun2 DE 1 >/dev/null; op_countries OpkgTun2 cross 0 >/dev/null")
    if (tmp / "etc/v2.countries").read_text() != "off=NL\ncross=0\n":
        fail(f"settings: {(tmp / 'etc/v2.countries').read_text()!r}")
    # The answer line of a change and of a plain read.
    for args, want in (("DE 0", "result=changed\n"), ("cross 1", "result=changed\n"), ("", "result=checked\n")):
        out = sh(f"op_countries OpkgTun2 {args}")
        if not out.endswith(want) or "changedcross" in out or "checkedcross" in out:
            fail(f"the answer to «{args}» ends with {want!r}: {out!r}")
    for bad in (("de", "0"), ("DE", "2"), ("cross", "x"), ("DE;rm", "0")):
        if "error=invalid_value" not in sh(f"op_countries OpkgTun2 '{bad[0]}' '{bad[1]}'"):
            fail(f"a wrong value must be refused: {bad}")

# The failover: switched-off countries skipped, other countries only with cross.
fo = func("op_failover")
for need in ('fo_off=" $(countries_get "$n" off) "', '*" $(cc "$(nm "$l")") "*) continue', 'elif [ "${fo_cross:-1}" != 0 ]; then echo "$i" >> "$TMPD/other"'):
    if need not in fo:
        fail(f"failover lacks {need}")
if "info.countries.off=" not in func("op_list") or '"$ENGINE_ETC/v$n.countries"' not in func("op_remove"):
    fail("the list carries the settings; a removed tunnel takes them along")

# Helper, API, Panel.
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text(encoding="utf-8")
api = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
js = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
if 'vs_out=$("$VLESS_ENGINE" countries "$2" "$3" "$4"' not in helper:
    fail("the helper must pass a country change to the engine")
if 'RELAY_REASON=$(printf \'%s\\n\' "$vs_out" | tail -n 1' not in helper:
    fail("an unknown answer of the engine leaves its last line in the journal")
for need in ('vless-server countries "$TNAME" "$TCC" "$TCV"', "countries: {off:"):
    if need not in api:
        fail(f"the API lacks {need}")
for need in ("if (!VSRV[name]) vlessServers(name)", "'Группировать по странам'", "['ping', 'Отклик'], ['name', 'Название'], ['country', 'Страна']",
             "'Переходить между странами'", "data-vcountry=", "localStorage.setItem('vward.vless.view'"):
    if need not in js:
        fail(f"the Panel lacks {need}")
if "'Показать серверы'" in js:
    fail("the servers are shown at once, without a button first")
print("VLESS_COUNTRIES=PASS")
