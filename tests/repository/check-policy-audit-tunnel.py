#!/usr/bin/env python3
"""IP categories (fix.32): sites are judged only through a tunnel that answers; a run with the
tunnel down is skipped or cut short and asked again once it is back.

fix.33.1, both branches: ten dead sites in a row cut the run short only when the tunnel fails
the VPN agent's own probes too; with the tunnel answering the run goes on (before: every hour
the same place, the tunnel up)."""
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
# The abort itself, run with a tunnel that answers the probes and one that does not.
fn = AUDIT[AUDIT.index("tunnel_answers() {"):]
fn = fn[:fn.index("\n}\n") + 3]
block = AUDIT[AUDIT.index("            # Ten sites in a row silent"):AUDIT.index('            [ -n "$VPN_CODE" ] || VPN_CODE="000"')]
for answers, fails, rc_exp in ((False, 9, 75), (True, 9, 0), (False, 3, 0)):
    with tempfile.TemporaryDirectory() as t:
        Path(t, "curl").write_text("#!/bin/sh\n" + ("exit 0\n" if answers else "exit 28\n"))
        Path(t, "curl").chmod(0o755)
        script = (f'PATH="{t}:$PATH"; WG=nwg0; SUMMARY_LOG="{t}/sum"; RECHECK="{t}/recheck"; CHECKED=7\n'
                  f"VPN_RC=28; VPN_FAILS={fails}\n" + fn + block + "echo CONTINUE\n")
        r = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
        label = f"tunnel {'answers' if answers else 'silent'}, {fails} dead sites before this one"
        if r.returncode != rc_exp:
            fail(f"{label}: rc={r.returncode}, expected {rc_exp}: {r.stdout} {r.stderr[-200:]}")
        aborted = Path(t, "sum").exists() and "ABORTED_TUNNEL_DOWN" in Path(t, "sum").read_text()
        if aborted != (rc_exp == 75) or Path(t, "recheck").exists() != (rc_exp == 75):
            fail(f"{label}: the abort is journaled and marked for a recheck only when it aborts")
        if (rc_exp == 0) != ("CONTINUE" in r.stdout):
            fail(f"{label}: the run goes on exactly when it does not abort")
if 'if [ "$AUDIT_RC" -eq 75 ]; then' not in CHAIN or '[ "$AUDIT_SKIPPED" = 0 ] || { COMPLETE=1;' not in CHAIN:
    fail("the chain still updates the categories when the check is skipped")
if "policy=recheck_after_tunnel" not in HOUSE:
    fail("housekeeping asks the check again once the tunnel answers")
print("POLICY_AUDIT_TUNNEL=PASS")
