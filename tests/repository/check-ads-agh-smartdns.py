#!/usr/bin/env python3
"""AdGuard Home Smart DNS rows for lists sent into a tunnel.

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
elif path == "dns_info": res = {"upstream_dns": st["up"], "upstream_dns_file": st.get("file", ""), "bootstrap_dns": ["9.9.9.9"]}
elif path == "dns_config" and method == "POST":
    if set(body) - {"upstream_dns"}: sys.exit(22)
    st["posts"] = st.get("posts", 0) + 1
    if st.get("ignore_posts"): res = {}
    else: st["up"] = body["upstream_dns"]; res = {}
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

    # A list holding anthropic.com (and api.anthropic.com below it) and a domain without Smart DNS.
    inc.write_text("anthropic.com\ntelegram.org\n")
    out = ctl("smartdns-take", str(inc), str(pairs))
    if "TAKEN=1" not in out or pairs.read_text() != f"anthropic.com\t{D}\n":
        fail(f"take: {out} {pairs.read_text()!r}")
    if S()["up"] != [f"[/claude.ai/]{D}", f"[/chatgpt.com/]{D}", "[/lan/]192.168.1.1", "https://dns.nextdns.io/abc", "77.88.8.8"]:
        fail(f"a shared row keeps its other domains, the rest stays: {S()['up']}")

    # A list with google.com has nothing in AdGuard Home: no write at all.
    posts = S().get("posts", 0)
    inc.write_text("google.com\n")
    if "TAKEN=0" not in ctl("smartdns-take", str(inc), str(tmp / "none.txt")) or S().get("posts", 0) != posts:
        fail("nothing to take must not write AdGuard Home")

    # Back: the pair returns as its own row; a second put changes nothing.
    ctl("smartdns-put", str(pairs))
    if S()["up"][-1] != f"[/anthropic.com/]{D}" or len(S()["up"]) != 6:
        fail(f"put: {S()['up']}")
    posts = S().get("posts", 0)
    ctl("smartdns-put", str(pairs))
    if S().get("posts", 0) != posts:
        fail("a pair already present is not written again")

    # A parent in the list takes subdomains; the whole row goes when all its domains go.
    inc.write_text("claude.ai\nchatgpt.com\n")
    ctl("smartdns-take", str(inc), str(pairs))
    if any("claude.ai" in u or "chatgpt.com" in u for u in S()["up"]) or sorted(pairs.read_text().split("\n")[:-1]) != [f"chatgpt.com\t{D}", f"claude.ai\t{D}"]:
        fail(f"take two: {S()['up']} {pairs.read_text()!r}")
    ctl("smartdns-put", str(pairs))
    if f"[/chatgpt.com/claude.ai/]{D}" not in S()["up"] and f"[/claude.ai/chatgpt.com/]{D}" not in S()["up"]:
        fail(f"pairs of one upstream come back in one row: {S()['up']}")

    # AdGuard Home that does not keep the change: the check fails, nothing is taken.
    st = S(); st["ignore_posts"] = True; state.write_text(json.dumps(st))
    before = S()["up"]
    inc.write_text("anthropic.com\n")
    ctl("smartdns-take", str(inc), str(pairs), ok=False)
    if S()["up"] != before or pairs.read_text() != "":
        fail("a change AdGuard Home did not keep must leave nothing taken")

    # Upstreams from a file are not edited.
    st = S(); st["ignore_posts"] = False; st["file"] = "/opt/etc/up.txt"; state.write_text(json.dumps(st))
    if "upstream_file_unsupported" not in ctl("smartdns-take", str(inc), str(pairs), ok=False):
        fail("an upstream file must be refused")

print("ADS_AGH_SMARTDNS=PASS")
