#!/usr/bin/env python3
"""Updater downloads: when a request fails (a dead VPN tunnel the router sends
the feed host through), it is repeated once bound to the device of the main
default route; a request that works is made once; the switch turns it off."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "components/update-engine"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def run(tmp: Path, mode: str, script: str, extra_env=None) -> subprocess.CompletedProcess:
    bin_ = tmp / "bin"
    bin_.mkdir(exist_ok=True)
    (tmp / "calls").write_text("")
    # Fake curl: logs its arguments; plain requests fail like a dead tunnel
    # unless mode is "ok"; requests bound to a device succeed.
    write_exec(bin_ / "curl", f"""#!/bin/sh
printf '%s\\n' "$*" >> "{tmp}/calls"
out=
prev=
for a in "$@"; do [ "$prev" = --output ] && out=$a; prev=$a; done
case " $* " in
    *" --interface "*) ;;
    *) [ "{mode}" = ok ] || {{ printf '000'; exit 28; }} ;;
esac
[ -z "$out" ] || printf 'feed' > "$out"
case " $* " in *write-out*) printf '200' ;; esac
""")
    write_exec(bin_ / "ip", "#!/bin/sh\necho 'default via 100.84.0.1 dev eth3 proto static'\n")
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", VWARD_NO_PERSIST_LOG="1",
               VU_ROOT_PREFIX=str(tmp / "root"))
    env.update(extra_env or {})
    full = f'. "{ENGINE}/vward-update-common-base.sh"\nVU_LOG_DIR="{tmp}/log"\n{script}'
    return subprocess.run(["sh", "-c", full], env=env, capture_output=True, text=True, timeout=30)


with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    url = "https://example.invalid/update-manifest.json"

    r = run(tmp, "dead", f'vu_fetch_feed "{url}" "{tmp}/out" 100000; echo "rc=$?"')
    calls = (tmp / "calls").read_text().splitlines()
    if "rc=0" not in r.stdout or (tmp / "out").read_text() != "feed":
        fail(f"a feed behind a dead tunnel is fetched through the provider: {r.stdout}{r.stderr}")
    if len(calls) != 2 or "--interface eth3" not in calls[1]:
        fail(f"the second request is bound to the default-route device: {calls}")
    if "retrying directly through eth3" not in r.stderr:
        fail("the retry is logged")

    (tmp / "out").unlink()
    r = run(tmp, "ok", f'vu_fetch_feed "{url}" "{tmp}/out" 100000; echo "rc=$?"')
    calls = (tmp / "calls").read_text().splitlines()
    if "rc=0" not in r.stdout or len(calls) != 1 or "--interface" in calls[0]:
        fail(f"a working request is made once, unbound: {calls}")

    r = run(tmp, "dead", f'vu_fetch_bounded "{url}" "{tmp}/b" 100000; echo "rc=$?"')
    if "rc=0" not in r.stdout or "--interface eth3" not in (tmp / "calls").read_text():
        fail("package downloads use the same fallback")

    r = run(tmp, "dead", f'vu_fetch_feed "{url}" "{tmp}/c" 100000; echo "rc=$?"', {"VU_DIRECT_FALLBACK": "0"})
    if "rc=1" not in r.stdout or len((tmp / "calls").read_text().splitlines()) != 1:
        fail("VU_DIRECT_FALLBACK=0 turns the retry off")

watch = (ENGINE / "vward-update-watch.sh").read_text()
delta = (ENGINE / "vward-update-delta.sh").read_text()
if "status=$(curl " in watch or watch.count("status=$(vu_curl ") != 3:
    fail("the watcher fetches the feed through vu_curl")
if "tail -c 3" not in watch:
    fail("the watcher keeps only the last HTTP code of a retried request")
if "vu_curl --fail" not in delta:
    fail("per-file (v2) downloads go through vu_curl")

print("PASS: updater downloads fall back to the provider when the tunnel is dead")

# The update engine has no package files of its own: the status API gives it a
# healthy row when the active slot holds a readable engine (not «Нет данных»).
import re as _re
api = (ROOT / "web/cgi-bin/api.cgi").read_text()
m = _re.search(r"# The update engine updates itself into a slot.*?\nesac\n", api, _re.S)
if not m:
    fail("the status API builds the update engine row")
with tempfile.TemporaryDirectory() as d:
    slot = Path(d)
    (slot / "vward-update-common-base.sh").write_text("VU_ENGINE_VERSION=2.0.3\n")
    script = 'COMPONENTS=\'{"route-engine":{"health":"PASS"}}\'\n' + m.group(0) + 'printf "%s" "$COMPONENTS"'
    env = dict(os.environ, JQ="jq", VWARD_VERSION="0.2.0-rc.2.fix.2", ACTIVE_SLOT=str(slot))
    out = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True).stdout
    import json as _json
    row = _json.loads(out).get("update-engine", {})
    if row.get("health") != "PASS" or row.get("engine_version") != "2.0.3":
        fail(f"update engine row: {out}")
print("PASS: the update engine has its own healthy row")
