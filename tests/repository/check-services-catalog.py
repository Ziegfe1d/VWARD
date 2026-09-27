#!/usr/bin/env python3
"""Services catalog: the shape routers accept, and the build folds as promised.

With a path argument only that catalog is checked (the daily workflow uses it).
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "components/console/data/services-catalog.json"
LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9.@_-]{0,62}$")
TITLE = re.compile(r'^[^"\\\x00-\x1f]{1,64}$')


def fail(msg: str) -> None:
    raise SystemExit(f"FAIL: {msg}")


def check(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > 524288:
        fail(f"{path}: catalog over 512 KB")
    c = json.loads(raw)
    if c.get("schema") != 1 or not isinstance(c.get("services"), list) or not c["services"]:
        fail(f"{path}: wrong schema")
    cats = {x["id"] for x in c["categories"]}
    seen = set()
    for s in c["services"]:
        sid = s.get("id", "")
        if not SERVICE_ID.match(sid) or sid in seen:
            fail(f"bad or repeated service id {sid!r}")
        seen.add(sid)
        if s.get("category") not in cats or not TITLE.match(s.get("title", "")):
            fail(f"{sid}: category or title")
        ds = s.get("domains")
        if not isinstance(ds, list) or not ds or len(ds) > c["limit"] and not s.get("too_big"):
            fail(f"{sid}: domains")
        for d in ds:
            parts = d.split(".")
            if not (4 <= len(d) <= 253 and len(parts) >= 2 and all(LABEL.match(p) for p in parts) and re.match(r"^[a-z]", parts[-1])):
                fail(f"{sid}: bad domain {d!r}")
        if len(set(ds)) != len(ds) or ds != sorted(ds):
            fail(f"{sid}: domains not sorted or repeated")
        have = set(ds)
        for d in ds:
            p = d.split(".")
            if any(".".join(p[i:]) in have for i in range(1, len(p) - 1)):
                fail(f"{sid}: {d} is covered by its parent")
    return c


if len(sys.argv) > 1:
    c = check(Path(sys.argv[1]))
    print(f"SERVICES_CATALOG=PASS services={len(c['services'])}")
    sys.exit(0)

c = check(BUNDLED)
if not any(s["id"] == "youtube.com" for s in c["services"]):
    fail("bundled catalog lacks YouTube")

# The build: subdomains under a listed parent go, three names under one domain
# become the domain, shared CDN domains never do, junk is dropped.
with tempfile.TemporaryDirectory() as t:
    src = Path(t) / "iplist"
    (src / "config/video").mkdir(parents=True)
    (src / "config/porn").mkdir(parents=True)
    (src / "config/unknown").mkdir(parents=True)
    (src / "config/video/example.tv.json").write_text(json.dumps({"domains": [
        "a.example.tv", "b.example.tv", "c.example.tv", "www.example.tv.",
        "x.cloudfront.net", "y.cloudfront.net", "z.cloudfront.net",
        "cdn.other.com", "img.cdn.other.com", "bad_domain.com", "nodot", "r3---sn.googlevideo", "*.wild.com"]}))
    (src / "config/porn/empty.json").write_text(json.dumps({"domains": []}))
    (src / "config/unknown/skip.json").write_text(json.dumps({"domains": ["skip.com"]}))
    out = Path(t) / "c.json"
    r = subprocess.run([sys.executable, str(ROOT / "tools/build-services-catalog.py"), str(src), str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        fail("build: " + r.stderr)
    b = check(out)
    svc = {s["id"]: s for s in b["services"]}
    if list(svc) != ["example.tv"]:
        fail(f"build kept {list(svc)}")
    want = ["cdn.other.com", "example.tv", "x.cloudfront.net", "y.cloudfront.net", "z.cloudfront.net"]
    if svc["example.tv"]["domains"] != want:
        fail(f"folding: {svc['example.tv']['domains']}")
    if [x["id"] for x in b["categories"]] != ["video"]:
        fail("categories without services must not be listed")

print(f"SERVICES_CATALOG=PASS services={len(c['services'])}")
