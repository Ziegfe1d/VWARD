#!/usr/bin/env python3
"""Ads & Privacy Guard Console functions: views, custom sources, categories."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "components/ads-privacy-guard/scripts"
VIEW = SCRIPTS / "vward-ads-privacy-view.sh"
SRC = SCRIPTS / "vward-ads-privacy-source-control.sh"
JQ = shutil.which("jq")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


QUERYLOG = {"data": [
    {"time": "2026-09-23T10:00:00Z", "client": "10.0.0.5", "question": {"name": "ads.example.com."}, "reason": "FilteredBlackList"},
    {"time": "2026-09-23T10:00:01Z", "client": "10.0.0.6", "question": {"name": "news.example.org"}, "reason": "NotFilteredNotFound"},
    {"time": "2026-09-23T10:00:02Z", "client": "10.0.0.6", "question": {"name": "maybe.example.net"}, "reason": "NotFilteredNotFound"},
]}
STATS = {"num_dns_queries": 1200, "num_blocked_filtering": 300, "avg_processing_time": 0.0123,
         "top_blocked_domains": [{"ads.example.com": 120}, {"t.example.com": 30}]}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    etc, state, share = tmp / "etc", tmp / "state", tmp / "share"
    for d in (etc, state / "work", state / "generated", share, tmp / "root/tmp"):
        d.mkdir(parents=True)
    shutil.copy(ROOT / "components/ads-privacy-guard/data/source-registry.json", share / "source-registry.json")
    (tmp / "querylog.json").write_text(json.dumps(QUERYLOG))
    (tmp / "stats.json").write_text(json.dumps(STATS))
    curl = tmp / "curl"
    curl.write_text(f"""#!/bin/sh
out=""; url=""
while [ "$#" -gt 0 ]; do case "$1" in -o) out="$2"; shift 2 ;; -u|--connect-timeout|--max-time|-H|--data-binary) shift 2 ;; -*) shift ;; *) url="$1"; shift ;; esac; done
echo "$url" >> "{tmp}/urls"
case "$url" in
  */querylog*) cp "{tmp}/querylog.json" "$out" ;;
  */stats) cp "{tmp}/stats.json" "$out" ;;
  *) exit 22 ;;
esac
""")
    curl.chmod(0o755)
    (state / "verdicts.tsv").write_text(
        "ads.example.com|BLOCK|BLOCK|HIGH|1|1700000300|0|source_consensus|x\n"
        "maybe.example.net|SUSPECT|NONE|MEDIUM|1|1700000200|0|single_source|x\n"
        "old.example.net|SUSPECT|BLOCK|MEDIUM|1|1700000100|0|block_revalidation_pending|x\n"
        "fine.example.org|ALLOW|NONE|MEDIUM|1|1700000000|0|no_block_evidence|x\n")
    env = os.environ | {
        "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(state), "VWARD_ADS_SHARE": str(share),
        "VWARD_ADS_LOG_DIR": str(tmp), "VWARD_ADS_BACKUP_ROOT": str(tmp / "backups"),
        "VWARD_ADS_JQ": JQ, "VWARD_ADS_CURL": str(curl), "AGH_API_BASE": "http://agh.test/control",
        "ADS_REQUIRE_SECURE_CONFIG": "0", "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }

    def view(*args):
        r = subprocess.run(["sh", str(VIEW), *args], env=env, text=True, capture_output=True)
        try:
            return json.loads(r.stdout)
        except ValueError:
            fail(f"view {args}: {r.stdout!r} {r.stderr!r}")

    def src(*args, ok=True):
        r = subprocess.run(["sh", str(SRC), *args], env=env, text=True, capture_output=True)
        if ok and (r.returncode != 0 or "SOURCE_CONTROL=PASS" not in r.stdout) and args[0] != "list":
            fail(f"source-control {args}: rc={r.returncode} {r.stdout!r} {r.stderr!r}")
        if not ok and r.returncode == 0:
            fail(f"source-control {args} must be refused")
        return r.stdout

    # Query log: AdGuard reasons become blocked/allowed, VWARD verdicts are joined.
    q = view("querylog", "all")
    if [e["domain"] for e in q["entries"]] != ["ads.example.com", "news.example.org", "maybe.example.net"]:
        fail(f"querylog domains: {q}")
    if q["entries"][0] != {"time": "2026-09-23T10:00:00Z", "client": "10.0.0.5", "domain": "ads.example.com", "blocked": True,
                           "reason": "FilteredBlackList", "verdict": "BLOCK", "vward_block": True}:
        fail(f"querylog entry: {q['entries'][0]}")
    if [e["domain"] for e in view("querylog", "review")["entries"]] != ["maybe.example.net"]:
        fail("review filter must keep only domains under review")
    # A router's verdicts pass 128 KB: they must reach jq as a file, not as one argument.
    saved = (state / "verdicts.tsv").read_text()
    with (state / "verdicts.tsv").open("a") as f:
        for i in range(5000):
            f.write(f"filler{i:05d}.example.org|ALLOW|NONE|HIGH|0|0|0|reason|evidence\n")
    big = view("querylog", "review")
    if big.get("ok") is not True or [e["domain"] for e in big["entries"]] != ["maybe.example.net"]:
        fail(f"querylog with thousands of verdicts: {big}")
    (state / "verdicts.tsv").write_text(saved)
    view("querylog", "blocked", "ads.example")
    urls = (tmp / "urls").read_text()
    if "response_status=blocked&search=ads.example" not in urls or "response_status=all" not in urls:
        fail(f"querylog must pass the filter and search to AdGuard Home: {urls}")
    for bad in (("querylog", "all", "a&b=1"), ("querylog", "everything"), ("list", "review", "x y")):
        if view(*bad).get("ok") is not False:
            fail(f"view {bad} must be refused")

    s = view("stats")
    if s != {"ok": True, "queries": 1200, "blocked": 300, "avg_ms": 12,
             "top_blocked": [{"domain": "ads.example.com", "count": 120}, {"domain": "t.example.com", "count": 30}]}:
        fail(f"stats: {s}")

    review = view("list", "review")
    if [e["domain"] for e in review["entries"]] != ["maybe.example.net", "old.example.net"] or review["total"] != 2:
        fail(f"review list: {review}")
    blocked = view("list", "blocked", "old")
    if [e["domain"] for e in blocked["entries"]] != ["old.example.net"]:
        fail(f"blocked search: {blocked}")

    # Unpublished changes against what was last published.
    (state / "generated/vward-ads-privacy-guard.rules").write_text("! header\n||a.example^\n||b.example^\n")
    if view("publish-status")["published"] is not False or view("publish-status")["added"] != 2:
        fail("nothing published yet: every rule is pending")
    (state / "published.rules").write_text("||a.example^\n||c.example^\n")
    ps = view("publish-status")
    if (ps["added"], ps["removed"]) != (1, 1):
        fail(f"publish-status diff: {ps}")

    # Custom sources: strict address and format, start in "check", can be removed.
    out = src("add", "https://lists.example.org/block/ads.txt", "adblock")
    sid = next(l.split("=", 1)[1] for l in out.splitlines() if l.startswith("SOURCE_ID="))
    listing = [l.split("|") for l in src("list").splitlines()]
    mine = [row for row in listing if row[0] == sid]
    if not mine or mine[0][1] != "check" or mine[0][5] != "1" or "lists.example.org" not in mine[0][2]:
        fail(f"custom source must be listed in check mode: {mine}")
    src("add", "https://lists.example.org/block/ads.txt", "adblock", ok=False)
    for bad in (("http://plain.example/list.txt", "adblock"), ("https://x.example/a b", "hosts"),
                ("https://user@x.example/l.txt", "hosts"), ("https://x.example/l.txt", "json"),
                ("https://x.example/$(reboot)", "hosts")):
        src("add", *bad, ok=False)
    src("set", sid, "active")
    src("delete", sid)
    if any(row[0] == sid for row in (l.split("|") for l in src("list").splitlines())):
        fail("deleted custom source still listed")
    src("delete", "hagezi-pro", ok=False)

    # A hand-edited custom file cannot smuggle options or non-https URLs in.
    (etc / "custom-sources.json").write_text(json.dumps({"schema": 1, "sources": [
        {"id": "custom-0123456789", "url": "https://ok.example/list.txt", "format": "hosts", "weight": 999, "single_source_block": True},
        {"id": "custom-aaaaaaaaaa", "url": "http://evil.example/list.txt", "format": "hosts"},
        {"id": "hagezi-pro", "url": "https://evil.example/list.txt", "format": "hosts"}]}))
    merged = subprocess.run(["sh", "-c", f'. "{ROOT}/components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"; cat "$ADS_SOURCE_REGISTRY"'],
                            env=env, text=True, capture_output=True).stdout
    sources = {s["id"]: s for s in json.loads(merged)["sources"]}
    if "custom-aaaaaaaaaa" in sources or sources["custom-0123456789"]["weight"] != 40 or sources["custom-0123456789"]["single_source_block"]:
        fail("custom source entries must be rebuilt from the validated subset")
    if sources["hagezi-pro"]["urls"][0].startswith("https://evil"):
        fail("a custom entry must never replace a built-in source")

    # Categories switch every source of a purpose off, and back to its default.
    src("category", "popup-ads", "off")
    modes = {row[0]: row[1] for row in (l.split("|") for l in src("list").splitlines())}
    if modes["hagezi-popup"] != "off" or modes["adguard-popup"] != "off" or modes["hagezi-pro"] != "active":
        fail(f"category off: {modes}")
    src("category", "popup-ads", "on")
    modes = {row[0]: row[1] for row in (l.split("|") for l in src("list").splitlines())}
    if modes["hagezi-popup"] != "active" or modes["adguard-popup"] != "active":
        fail(f"category on must restore default modes: {modes}")
    src("category", "no-such-thing", "off", ok=False)

print("ADS_CONSOLE=PASS")
