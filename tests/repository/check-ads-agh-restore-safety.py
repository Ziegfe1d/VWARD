#!/usr/bin/env python3
"""AdGuard Home Smart DNS: an unconfirmed write must never roll back over newer user changes.

smartdns-take removes the [/domain/]https://... rows of the list's domains and
below (other domains of a shared row stay, plain upstreams stay) and writes the
taken pairs; smartdns-put brings them back.  Every change is read back; a
mismatch puts the previous upstream list back.  An upstream file is refused.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
st_path = Path("@STATE@")
st = json.loads(st_path.read_text())
args = sys.argv[1:]
conf = sys.stdin.read() if "-K" in args else ""
method = args[args.index("-X") + 1] if "-X" in args else "GET"
out = args[args.index("-o") + 1]
body = {}
if "--data-binary" in args:
    raw = Path(args[args.index("--data-binary") + 1][1:]).read_text()
    body = json.loads(raw) if raw else {}
url = [a for a in args if a.startswith("http")][-1]
path = url.split("/control/", 1)[1]
res = None
if path == "status": res = {"version": "v0.107.52", "protection_enabled": True}
elif path == "dns_info":
    st["gets"] = st.get("gets", 0) + 1
    if st.get("edit_on_get") and st["gets"] == st["edit_on_get"]["n"]: st["up"] = st["up"] + st["edit_on_get"]["add"]
    res = {"upstream_dns": st["up"], "upstream_dns_file": st.get("file", ""), "bootstrap_dns": ["9.9.9.9"]}
elif path == "dns_config" and method == "POST":
    if set(body) - {"upstream_dns"}: sys.exit(22)
    st["posts"] = st.get("posts", 0) + 1
    st.setdefault("log", []).append(body["upstream_dns"])
    if st.get("ignore_posts"): res = {}
    else:
        st["up"] = body["upstream_dns"]; res = {}
        if st.get("user_edit_after_post") and st["posts"] == 1: st["up"] = st["up"] + st["user_edit_after_post"]
if res is None: sys.exit(22)
st_path.write_text(json.dumps(st))
Path(out).write_text(json.dumps(res))
'''


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


D = "https://tr.example:8443/dns-query/x"
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = tmp / "agh.json"
    UP = [f"[/anthropic.com/claude.ai/]{D}", f"[/chatgpt.com/]{D}", "[/lan/]192.168.1.1", "https://dns.nextdns.io/abc", "77.88.8.8"]
    state.write_text(json.dumps({"up": UP}))
    curl = tmp / "curl"; curl.write_text(FAKE_CURL.replace("@STATE@", str(state))); curl.chmod(0o755)
    etc = tmp / "etc"; etc.mkdir()
    auth = etc / "agh-api.auth"; auth.write_text("admin:pw\n"); auth.chmod(0o600)
    (tmp / "root/tmp").mkdir(parents=True)
    lib = (ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh").read_text()
    patched = tmp / "lib.sh"
    patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    env = os.environ | {
        "VWARD_ADS_LIB": str(patched), "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(tmp / "state"), "VWARD_ADS_LOG_DIR": str(tmp / "log"),
        "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(curl), "VWARD_ADS_AGH_AUTH_FILE": str(auth),
        "AGH_API_BASE": "http://192.0.2.1:3001/control", "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"), "TMPDIR": str(tmp),
    }

    def ctl(*args, ok=True):
        r = subprocess.run(["sh", str(CONTROL), "agh", *args], env=env, text=True, capture_output=True)
        if ok and (r.returncode != 0 or "CONTROL=PASS" not in r.stdout):
            fail(f"agh {args}: rc={r.returncode} {r.stdout} {r.stderr[-300:]}")
        if not ok and r.returncode == 0:
            fail(f"agh {args} must fail: {r.stdout}")
        return r.stdout

    S = lambda: json.loads(state.read_text())
    inc = tmp / "inc.txt"; pairs = tmp / "pairs.txt"
    USER = "[/user-added.example/]https://user.example/dns-query"

    # 1. take: the first write is overlaid by a user edit before read-back. The
    # reader sees a mismatch; the old list must NOT be written over the user row.
    state.write_text(json.dumps({"up": UP, "user_edit_after_post": [USER]}))
    inc.write_text("anthropic.com\n")
    out = ctl("smartdns-take", str(inc), str(pairs), ok=False)
    if USER not in S()["up"]:
        fail("RED: rollback after a mismatch erased the user's newer AdGuard Home row")
    if S().get("posts", 0) != 1:
        fail(f"RED: stale rollback POST issued ({S().get('posts')} posts)")
    # The pairs stay as private recovery evidence for the owner; not discarded.
    if pairs.read_text() != f"anthropic.com\t{D}\n":
        fail(f"recovery pairs were dropped on an unconfirmed change: {pairs.read_text()!r}")

    # 2. put: same race, with a recovery directory (the caller's evidence).
    rec = tmp / "rec"; rec.mkdir(mode=0o700)
    env2 = dict(env, VWARD_AGH_RECOVERY_DIR=str(rec))
    state.write_text(json.dumps({"up": UP[1:], "user_edit_after_post": [USER]}))
    pairs.write_text(f"anthropic.com\t{D}\n")
    r = subprocess.run(["sh", str(CONTROL), "agh", "smartdns-put", str(pairs)], env=env2, text=True, capture_output=True)
    if r.returncode == 0:
        fail("put with an unconfirmed read-back must fail")
    if USER not in S()["up"]:
        fail("RED: put rollback erased the user's newer AdGuard Home row")
    if not (rec / "dns.before.json").is_file() or not (rec / "dns.planned.json").is_file():
        fail("recovery evidence missing before the write")

    # 4. A user edit between our read and our write: the plan was built from a stale
    # list, so writing it would silently drop the edit. Nothing may be written.
    for op, setup in (("smartdns-take", lambda: inc.write_text("anthropic.com\n")),
                      ("smartdns-put", lambda: pairs.write_text(f"anthropic.com\t{D}\n"))):
        state.write_text(json.dumps({"up": UP if op == "smartdns-take" else UP[1:], "edit_on_get": {"n": 2, "add": [USER]}}))
        setup()
        r = subprocess.run(["sh", str(CONTROL), "agh", op, str(inc if op == "smartdns-take" else pairs)] + ([str(tmp / "taken.txt")] if op == "smartdns-take" else []),
                           env=env, text=True, capture_output=True)
        if r.returncode == 0:
            fail(f"RED: {op} wrote a plan built from a stale AdGuard Home list")
        if S().get("posts", 0) != 0 or USER not in S()["up"]:
            fail(f"RED: {op} overwrote a user edit made after the read (posts={S().get('posts')})")

    # 3. no race: a clean mismatch (AGH ignores the write) still restores nothing
    # destructive and leaves the original list intact.
    state.write_text(json.dumps({"up": UP, "ignore_posts": True}))
    inc.write_text("anthropic.com\n")
    ctl("smartdns-take", str(inc), str(pairs), ok=False)
    if S()["up"] != UP:
        fail("a refused change altered the list")

print("ADS_AGH_RESTORE_SAFETY=PASS")
