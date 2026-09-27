#!/usr/bin/env python3
"""Routing sources: the small hint lists and the official subnets.

The functions are taken from the scripts themselves and run with a stand-in
download: a good list is kept and reported, a missing or too short one leaves
the last good copy in place and is reported as failed.
"""

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HINTS = (ROOT / "components/route-tools/scripts/vward-route-hints-update.sh").read_text()
POLICY = (ROOT / "components/policy-sync/scripts/vward-policy-sync.sh").read_text()


def fail(msg):
    raise SystemExit(f"ROUTE_SOURCES=FAIL: {msg}")


def func(src, name):
    m = re.search(r"^" + re.escape(name) + r"\(\)\n\{\n.*?^\}\n", src, re.S | re.M)
    if not m:
        fail(f"function {name} not found")
    return m.group(0)


for url in ("https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/community.lst",
            "https://community.antifilter.download/list/domains.lst"):
    if url not in HINTS:
        fail(f"hint source missing: {url}")
if '"$CACHE/refilter.tsv" "$CACHE/antifilter.tsv"' not in HINTS:
    fail("the hint lists must join the catalog")
if "https://core.telegram.org/resources/cidr.txt" not in POLICY or '"$OFFICIAL_SRC"/*.cidr' not in POLICY:
    fail("official subnets must join the IP catalog")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    served = tmp / "served"; served.mkdir()
    status = tmp / "sources.status"

    hints = "\n".join([
        f'WORK="{tmp}/work"; CACHE="{tmp}/cache"; SOURCES_STATUS="{status}"; mkdir -p "$WORK" "$CACHE"',
        # fetch URL OUT: the file named after the URL's last part, if served.
        'fetch() { f="' + str(served) + '/$(basename "$1")"; [ -s "$f" ] && cp "$f" "$2"; }',
        func(HINTS, "normalize_domains"), func(HINTS, "update_text_list"), func(HINTS, "source_status"),
        'if update_text_list refilter "https://x/community.lst" refilter-community 3; then source_status refilter ok; else source_status refilter fail; fi',
        'if update_text_list antifilter "https://x/domains.lst" antifilter-community 3; then source_status antifilter ok; else source_status antifilter fail; fi',
    ])
    (served / "community.lst").write_text("4pda.ru\n# comment\nautodesk.com\n*.adguard.com\nwww.chatgpt.com.\nBAD DOMAIN\n")
    (served / "domains.lst").write_text("a.example\nb.example\n")
    r = subprocess.run(["sh", "-c", hints], text=True, capture_output=True)
    rows = dict(l.split("|", 1)[0:1] + [l] for l in status.read_text().splitlines())
    if rows["refilter"].split("|")[2:] != ["ok", "4"] or rows["antifilter"].split("|")[2:] != ["fail", "0"]:
        fail(f"first run: {status.read_text()} {r.stdout} {r.stderr}")
    if (tmp / "cache/refilter.tsv").read_text().splitlines() != [
            "4pda.ru|refilter|refilter-community", "adguard.com|refilter|refilter-community",
            "autodesk.com|refilter|refilter-community", "www.chatgpt.com|refilter|refilter-community"]:
        fail(f"catalog rows: {(tmp / 'cache/refilter.tsv').read_text()}")
    # Next night the source is down: the last good copy stays, the failure shows.
    (served / "community.lst").unlink()
    subprocess.run(["sh", "-c", hints], text=True, capture_output=True)
    rows = dict((l.split("|")[0], l.split("|")) for l in status.read_text().splitlines())
    if rows["refilter"][2:] != ["fail", "4"] or len((tmp / "cache/refilter.tsv").read_text().splitlines()) != 4:
        fail(f"source down: {status.read_text()}")

    policy = "\n".join([
        f'WORK="{tmp}/pwork"; OFFICIAL_SRC="{tmp}/official"; SOURCES_STATUS="{status}"; mkdir -p "$WORK"',
        'download() { f="' + str(served) + '/$(basename "$1")"; [ -s "$f" ] && cp "$f" "$2"; }',
        'replace_source_dir() { rm -rf "$2"; mv "$1" "$2"; }',
        func(POLICY, "normalize_ipv4"), func(POLICY, "update_official_catalog"), func(POLICY, "source_status"),
        'if update_official_catalog; then source_status official ok "$OFFICIAL_SRC"; else source_status official fail "$OFFICIAL_SRC"; fi',
    ])
    (served / "cidr.txt").write_text("91.108.56.0/22\n91.108.4.0/22\n149.154.160.0/20\n2001:b28:f23d::/48\n")
    r = subprocess.run(["sh", "-c", policy], text=True, capture_output=True)
    rows = dict((l.split("|")[0], l.split("|")) for l in status.read_text().splitlines())
    tg = (tmp / "official/telegram.cidr").read_text().split()
    if rows["official"][2:] != ["ok", "3"] or "149.154.160.0/20" not in tg or any(":" in x for x in tg):
        fail(f"official subnets: {status.read_text()} {tg} {r.stdout} {r.stderr}")
    if rows["refilter"][2:] != ["fail", "4"]:
        fail("one script must not wipe the other's status")
    # A short answer (not the list) keeps the last good subnets.
    (served / "cidr.txt").write_text("<html>maintenance</html>\n")
    subprocess.run(["sh", "-c", policy], text=True, capture_output=True)
    rows = dict((l.split("|")[0], l.split("|")) for l in status.read_text().splitlines())
    if rows["official"][2:] != ["fail", "3"]:
        fail(f"bad answer: {status.read_text()}")

print("ROUTE_SOURCES=PASS")
