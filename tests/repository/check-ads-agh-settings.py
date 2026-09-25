#!/usr/bin/env python3
"""Ads page: AdGuard Home's own ad settings are read and changed through its API.

A stand-in for curl answers the AdGuard Home control API from a JSON state:
protection, filtering and its lists, blocked services (the current API),
safe browsing, parental control and safe search.  The login travels on
curl's stdin (-K -), never in argv.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-view.sh"
CONTROL = ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
st_path = Path("@STATE@")
st = json.loads(st_path.read_text())
args = sys.argv[1:]
with open(str(st_path) + ".argv", "a") as f: f.write(" ".join(args) + "\n")
conf = sys.stdin.read() if "-K" in args else ""
want = 'user = "%s"' % st["login"].replace("\\", "\\\\").replace('"', '\\"') if st.get("login") else ""
if want and conf.strip() != want:
    sys.exit(22)
method = args[args.index("-X") + 1] if "-X" in args else "GET"
out = args[args.index("-o") + 1]
body = {}
if "--data-binary" in args:
    raw = Path(args[args.index("--data-binary") + 1][1:]).read_text()
    body = json.loads(raw) if raw else {}
url = [a for a in args if a.startswith("http")][-1]
path = url.split("/control/", 1)[1]
res = None
if path == "status": res = {"version": "v0.107.52", "protection_enabled": st["protection"]}
elif path == "protection" and method == "POST": st["protection"] = body["enabled"]; res = {}
elif path == "filtering/status": res = {"enabled": st["filtering"], "interval": st["interval"], "filters": st["filters"], "whitelist_filters": [], "user_rules": ["||x^"]}
elif path == "filtering/config": st["filtering"] = body["enabled"]; st["interval"] = body["interval"]; res = {}
elif path == "filtering/set_url":
    for f in st["filters"]:
        if f["url"] == body["url"]: f["enabled"] = body["data"]["enabled"]
    res = {}
elif path == "filtering/add_url": st["filters"].append({"id": 9, "name": body["name"], "url": body["url"], "enabled": True, "rules_count": 10}); res = {}
elif path == "filtering/remove_url": st["filters"] = [f for f in st["filters"] if f["url"] != body["url"]]; res = {}
elif path == "filtering/refresh": res = {"updated": 1}
elif path == "blocked_services/all": res = {"blocked_services": [{"id": "youtube", "name": "YouTube", "icon_svg": "x", "rules": ["||youtube.com^"]}, {"id": "tiktok", "name": "TikTok"}]}
elif path == "blocked_services/get": res = {"ids": st["services"], "schedule": {"time_zone": "Local"}}
elif path == "blocked_services/update" and method == "PUT": st["services"] = body["ids"]; res = {}
elif path in ("safebrowsing/status", "parental/status"): res = {"enabled": st[path.split("/")[0]]}
elif path in ("safebrowsing/enable", "safebrowsing/disable", "parental/enable", "parental/disable"):
    st[path.split("/")[0]] = path.endswith("enable"); res = {}
elif path == "safesearch/status": res = {"enabled": st["safesearch"], "bing": True, "google": True}
elif path == "safesearch/settings" and method == "PUT": st["safesearch"] = body["enabled"]; res = {}
if res is None: sys.exit(22)
st_path.write_text(json.dumps(st))
Path(out).write_text(json.dumps(res))
'''


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = tmp / "agh.json"
    state.write_text(json.dumps({
        "login": 'admin:p"w', "protection": True, "filtering": True, "interval": 24,
        "filters": [{"id": 1, "name": "AdGuard DNS filter", "url": "https://adguardteam.github.io/f1.txt", "enabled": True, "rules_count": 50000}],
        "services": [], "safebrowsing": False, "parental": False, "safesearch": False}))
    curl = tmp / "curl"; curl.write_text(FAKE_CURL.replace("@STATE@", str(state))); curl.chmod(0o755)
    etc = tmp / "etc"; etc.mkdir()
    auth = etc / "agh-api.auth"; auth.write_text('admin:p"w\n'); auth.chmod(0o600)
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_ADS_LIB": str(ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"),
        "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(tmp / "state"), "VWARD_ADS_LOG_DIR": str(tmp / "log"),
        "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(curl), "VWARD_ADS_AGH_AUTH_FILE": str(auth),
        "AGH_API_BASE": "http://192.0.2.1:3001/control", "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"), "TMPDIR": str(tmp),
    }
    # The auth file must belong to root: the stand-in owner check reads the test user's uid.
    lib = (ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh").read_text()
    patched = tmp / "lib.sh"
    patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    env["VWARD_ADS_LIB"] = str(patched)

    def S():
        return json.loads(state.read_text())

    def view():
        r = subprocess.run(["sh", str(VIEW), "agh"], env=env, text=True, capture_output=True)
        return json.loads(r.stdout)

    def ctl(*args, ok=True):
        r = subprocess.run(["sh", str(CONTROL), "agh", *args], env=env, text=True, capture_output=True)
        if ok and (r.returncode != 0 or "CONTROL=PASS" not in r.stdout):
            fail(f"agh {args}: rc={r.returncode} {r.stdout} {r.stderr[-300:]}")
        if not ok and r.returncode == 0:
            fail(f"agh {args} must fail")
        return r.stdout

    v = view()
    if not v["ok"] or v["protection"] is not True or v["filtering"]["filters"][0]["rules"] != 50000 or v["services"]["available"][0] != {"id": "tiktok", "name": "TikTok"} or v["safesearch"] is not False:
        fail(f"view: {v}")
    if "icon_svg" in json.dumps(v):
        fail("service icons and rules must not be passed to the page")

    ctl("protection", "0"); ctl("filtering", "0"); ctl("interval", "72")
    ctl("safebrowsing", "1"); ctl("parental", "1"); ctl("safesearch", "1")
    ctl("service", "youtube", "1"); ctl("service", "tiktok", "1"); ctl("service", "youtube", "0")
    ctl("filter-enable", "https://adguardteam.github.io/f1.txt", "0")
    ctl("filter-add", "https://example.org/list.txt", "My list")
    ctl("filter-remove", "https://example.org/list.txt")
    ctl("filters-refresh")
    s = S()
    if (s["protection"], s["filtering"], s["interval"], s["safebrowsing"], s["parental"], s["safesearch"], s["services"]) != (False, False, 72, True, True, True, ["tiktok"]):
        fail(f"settings not applied: {s}")
    if s["filters"][0]["enabled"] is not False or len(s["filters"]) != 1:
        fail(f"filters: {s['filters']}")

    ctl("interval", "5", ok=False); ctl("service", "a;b", "1", ok=False); ctl("filter-add", "http://x/y", "n", ok=False)
    ctl("filter-enable", "https://nowhere.example/z.txt", "1", ok=False)
    if 'p"w' in (Path(str(state) + ".argv")).read_text():
        fail("the AdGuard Home password reached curl's argv")

    auth.write_text("admin:wrong\n")
    if view().get("error") != "adguard_auth_required" and view().get("error") != "adguard_unavailable":
        fail(f"a wrong login must be reported: {view()}")

print("ADS_AGH_SETTINGS=PASS")
