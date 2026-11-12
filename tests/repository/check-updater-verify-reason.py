#!/usr/bin/env python3
"""The updater says why a manifest failed its check (11.11.2026: «Manifest structure/signature
verification failed» every 15 minutes, and it could not be told whether jq or openssl was at
fault). The published dev manifest and the production key, the router's flow (watch -> --check):
jq crashing -> «Manifest structure check failed ... jq rc=132»; openssl crashing (no kept copy) ->
«Manifest signature check failed: openssl rc=132 kept_copy=none key=readable jq runs»; both
working -> accepted, no such line."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "updates/dev/v2/manifest.json"


def fail(m):
    raise SystemExit(f"UPDATER_VERIFY_REASON=FAIL: {m}")


def flow(tmp: Path, crash: str) -> str:
    bin_ = tmp / "bin"
    bin_.mkdir(exist_ok=True)
    for tool in ("jq", "openssl"):
        p = bin_ / tool
        if tool == crash:
            p.write_text("#!/bin/sh\nkill -ILL $$\n")
            p.chmod(0o755)
        elif p.exists():
            p.unlink()
    sh = f"""set -u
REPO={ROOT}
. "$REPO/tests/updater/seed-runtime.sh"
R={tmp}/root; rm -rf "$R"
mkdir -p "$R/opt/etc/vward/console" "$R/opt/share/vward/console/www/cgi-bin" "$R/opt/bin" "$R/opt/var/lib/vward/updater" "$R/tmp"
cp "$REPO/config/updater/update-public.pem" "$R/opt/etc/vward/update-public.pem"
V=0.2.0-rc.2.fix.36
printf '%s\\n' "$V" > "$R/opt/share/vward/VERSION"
C=$R/opt/etc/vward/update.conf
printf '%s\\n' update_enabled=1 auto_apply=0 channel=dev manifest_url=https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/update-manifest.json \\
  "public_key_file=$R/opt/etc/vward/update-public.pem" "current_version_file=$R/opt/share/vward/VERSION" barrier_integration_ready=1 check_interval_seconds=1 > "$C"
printf 'installed_version=%s\\ninstalled_update_id=vward-%s\\nlast_sequence=2026110801\\nmanifest_hash=x\\nlast_health_check=x\\n' "$V" "$V" > "$R/opt/var/lib/vward/updater/committed.state"
seed_runtime "$R" >/dev/null 2>&1
PATH="{bin_}:$PATH" VWARD_ROOT_PREFIX="$R" VWARD_UPDATE_CONFIG="$C" VWARD_TEST_HTTP_STATUS=200 VWARD_TEST_WATCH_MANIFEST="{MANIFEST}" \\
  sh "$REPO/components/update-engine/vward-update-watch.sh" --once >/dev/null 2>&1
echo "rc=$?"
cat "$R"/opt/var/log/vward/updater.log 2>/dev/null
"""
    return subprocess.run(["sh", "-c", sh], capture_output=True, text=True, timeout=120).stdout


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    out = flow(tmp, "")
    if "rc=0" not in out or "check failed" in out:
        fail(f"working tools: the manifest is accepted\n{out}")
    out = flow(tmp, "jq")
    if "Manifest structure check failed" not in out or "jq rc=132" not in out:
        fail(f"jq crashing:\n{out}")
    out = flow(tmp, "openssl")
    if "Manifest signature check failed: openssl rc=132 kept_copy=none key=readable jq runs" not in out:
        fail(f"openssl crashing:\n{out}")
print("UPDATER_VERIFY_REASON=PASS")
