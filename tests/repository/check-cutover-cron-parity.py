#!/usr/bin/env python3
"""scripts/beta-to-dev-cutover.sh embeds dev's crontab so it works as a
single file copied to the router. This checks that embedded copy against
config/cron/root.crontab byte for byte, and checks the list of beta cron
markers against the real beta crontab (from origin/beta, when reachable)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


script = (ROOT / "scripts/beta-to-dev-cutover.sh").read_text()
live_crontab = (ROOT / "config/cron/root.crontab").read_text().rstrip("\n")

m = re.search(r"DEV_CRONTAB='(.*?)'\n\n# Init scripts", script, re.DOTALL)
if not m:
    fail("could not find the embedded DEV_CRONTAB block")
embedded = m.group(1)
if embedded != live_crontab:
    fail("embedded DEV_CRONTAB no longer matches config/cron/root.crontab; "
         "regenerate the block in scripts/beta-to-dev-cutover.sh")

# Every dev cron line's script/init marker must be found by the script's own
# marker extraction, and none may collide with a beta marker (or the
# add-step would treat a dev line as already present).
m = re.search(r"BETA_CRON_MARKERS='(.*?)'\n", script, re.DOTALL)
beta_markers = set(m.group(1).strip().splitlines()) if m else set()
dev_markers = set(re.findall(r"/opt/(?:bin|etc/init\.d)/[A-Za-z0-9_.-]+", live_crontab))
overlap = beta_markers & dev_markers
if overlap:
    fail(f"a dev cron marker collides with a beta one: {overlap}")

beta_src = subprocess.run(["git", "-C", str(ROOT), "show", "origin/beta:config/cron/root.crontab"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
if beta_src.returncode == 0:
    beta_lines = [l for l in beta_src.stdout.splitlines() if l.strip()]
    # grep -vF drops a whole line on any one marker match, so each beta
    # cron line needs exactly one marker, not one per script it invokes.
    uncovered = [l for l in beta_lines if not any(marker in l for marker in beta_markers)]
    if uncovered:
        fail(f"origin/beta cron line(s) not matched by any BETA_CRON_MARKERS entry: {uncovered}")
    if len(beta_lines) != len(beta_markers):
        fail(f"BETA_CRON_MARKERS has {len(beta_markers)} entries for {len(beta_lines)} beta cron lines; "
             "expected one marker per line")
else:
    print("NOTE: origin/beta is not reachable here; skipped the beta-marker cross-check")

print("CUTOVER_CRON_PARITY=PASS")
