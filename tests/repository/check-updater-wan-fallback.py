#!/usr/bin/env python3
"""Updater downloads: when a request fails (a dead VPN tunnel the router sends
the feed host through), it is repeated once bound to the device of the main
default route; a request that works is made once; the switch turns it off."""

import json
import os
import shutil
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

# An openssl that crashes on the Ed25519 check (Entware 3.5.5 on MIPS): the engine keeps a
# copy of the openssl that last verified and checks with it; a bad signature still fails.
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    manifest = ROOT / "updates/dev/v2/manifest.json"
    if manifest.exists():
        pub = ROOT / "config/updater/update-public.pem"
        upd = tmp / "updater"; upd.mkdir()
        bad = tmp / "bad"; bad.mkdir()
        real = shutil.which("openssl")
        # Stage 1: a working openssl verifies and is kept.
        base = (f'. "{ENGINE}/vward-update-common-base.sh"\nVU_LOG_DIR="{tmp}/log"\nVU_STAGING_DIR="{tmp}/st"\n'
                f'public_key_file="{pub}"\nVU_STATE_DIR="{upd}"\n')
        env = dict(os.environ, VWARD_NO_PERSIST_LOG="1", VWARD_UPDATER_ROOT=str(upd))
        r = subprocess.run(["sh", "-c", base + f'vu_manifest_verify_signature "{manifest}"; echo "rc=$?"'], env=env, capture_output=True, text=True)
        if "rc=0" not in r.stdout or not (upd / "openssl/openssl").exists():
            fail(f"a working openssl verifies and is kept: {r.stdout}{r.stderr}")
        # Stage 2: the system openssl crashes on pkeyutl; the kept copy verifies.
        (bad / "openssl").write_text(f'#!/bin/sh\n[ "$1" = pkeyutl ] && kill -SEGV $$\nexec {real} "$@"\n')
        (bad / "openssl").chmod(0o755)
        env2 = env | {"PATH": f"{bad}:{os.environ['PATH']}"}
        r = subprocess.run(["sh", "-c", base + f'vu_manifest_verify_signature "{manifest}"; echo "rc=$?"'], env=env2, capture_output=True, text=True)
        if "rc=0" not in r.stdout or "kept copy verified" not in r.stderr:
            fail(f"the kept openssl checks when the system one crashes: {r.stdout}{r.stderr}")
        forged = tmp / "forged.json"
        forged.write_text(json.dumps(json.loads(manifest.read_text()) | {"signature": "AAAA" + json.loads(manifest.read_text())["signature"][4:]}))
        r = subprocess.run(["sh", "-c", base + f'vu_manifest_verify_signature "{forged}"; echo "rc=$?"'], env=env2, capture_output=True, text=True)
        if "rc=1" not in r.stdout:
            fail("a wrong signature is refused by the kept copy too")

helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
if 'pkeyutl -verify -inkey "$eh_t/k" -rawin' not in helper or "&& echo openssl" not in helper:
    fail("an Entware upgrade that breaks openssl's Ed25519 check is rolled back")
print("PASS: a crashing openssl does not stop signed updates")
