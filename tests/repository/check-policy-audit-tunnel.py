#!/usr/bin/env python3
"""IP categories (fix.32): sites are judged only through a tunnel that answers; a run with the
tunnel down is skipped or cut short and asked again once it is back."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = (ROOT / "components/policy-sync/scripts/vward-policy-audit.sh").read_text()
CHAIN = (ROOT / "components/policy-sync/scripts/vward-policy-chain.sh").read_text()
HOUSE = (ROOT / "components/runtime/scripts/vward-housekeeping.sh").read_text()


def fail(m):
    print(f"POLICY_AUDIT_TUNNEL=FAIL: {m}")
    sys.exit(1)


# The gate itself, run against health states.
gate = AUDIT[AUDIT.index('RECHECK="$STATE_DIR/recheck"'):AUDIT.index("VPN_FAILS=0")]
for status, rc in (("UP", 0), ("DEGRADED", 0), ("DOWN", 75), ("", 75)):
    with tempfile.TemporaryDirectory() as t:
        Path(t, "state").write_text(f"STATUS={status}\n" if status else "")
        sh = f'STATE_DIR="{t}"; SUMMARY_LOG="{t}/sum"; START_TEXT=now; VWARD_TUNNEL_HEALTH_STATE="{t}/state"\n' + gate + "exit 0\n"
        r = subprocess.run(["sh", "-c", sh], capture_output=True, text=True)
        if r.returncode != rc or (rc == 75) != Path(t, "recheck").exists():
            fail(f"health {status!r}: rc={r.returncode}, expected {rc} and the recheck mark")
if 'VPN_FAILS" -ge "${VWARD_AUDIT_TUNNEL_FAILS:-10}"' not in AUDIT:
    fail("a run is cut short when the tunnel stops answering")
if 'if [ "$AUDIT_RC" -eq 75 ]; then' not in CHAIN or '[ "$AUDIT_SKIPPED" = 0 ] || { COMPLETE=1;' not in CHAIN:
    fail("the chain still updates the categories when the check is skipped")
if "policy=recheck_after_tunnel" not in HOUSE:
    fail("housekeeping asks the check again once the tunnel answers")
print("POLICY_AUDIT_TUNNEL=PASS")
