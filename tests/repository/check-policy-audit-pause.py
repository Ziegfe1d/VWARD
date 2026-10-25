#!/usr/bin/env python3
"""IP categories' night check: portions and pauses while Keenetic is busy, reasons in the summary
(fix.34; Viva 25.10: 26-36 min over ~500 sites at 00:10, 273 of 491 not passed, 60 -> 19 passed,
the same minutes as the night's false «Интернет»).

  * every 20 sites the run waits while vward_busy says so, 15 s at a time, 600 s at most in all;
    VWARD_AUDIT_PAUSE=0 turns it off; which sites and how they are judged does not change;
  * the summary line counts why the sites did not pass (curl's error or the HTTP class, the
    tunnel failing too, no address) and the seconds paused - diagnostics only.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = (ROOT / "components/policy-sync/scripts/vward-policy-audit.sh").read_text()


def fail(m):
    print(f"POLICY_AUDIT_PAUSE=FAIL: {m}")
    sys.exit(1)


fns = AUDIT[AUDIT.index("AUDIT_PORTION="):AUDIT.index("RUNCFG=")]
summary = AUDIT[AUDIT.index("REASON_SUM=$("):AUDIT.index('echo "Reasons:')]
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])
for shell in shells:
    with tempfile.TemporaryDirectory() as t:
        def run(body, **env):
            r = subprocess.run([*shell, "-c", f'sleep() {{ :; }}\n{fns}\n{body}'], capture_output=True, text=True,
                               env={"PATH": "/usr/bin:/bin", **env}, timeout=30)
            if r.returncode:
                fail(f"{shell[0]}: rc={r.returncode} {r.stderr}")
            return r.stdout.strip()

        # Busy three checks, then free: three steps of 15 s, one pause.
        busy3 = 'n=0; vward_busy() { n=$((n + 1)); [ "$n" -le 3 ]; }\n'
        if run(busy3 + 'audit_pause; echo "$PAUSED $PAUSES"') != "45 1":
            fail(f"{shell[0]}: a busy Keenetic: {run(busy3 + 'audit_pause; echo $PAUSED $PAUSES')}")
        # Busy without end: no more than 600 s in all, over several portions.
        always = 'vward_busy() { return 0; }\n'
        if run(always + 'audit_pause; audit_pause; echo "$PAUSED"') != "600":
            fail(f"{shell[0]}: the pauses are not capped")
        # Off, or no vward_busy (an old library): no wait.
        if run(always + 'audit_pause; echo "$PAUSED"', VWARD_AUDIT_PAUSE="0") != "0" or run('audit_pause; echo "$PAUSED"') != "0":
            fail(f"{shell[0]}: the pause cannot be turned off")

        # The reasons: the judging's own variables, as the loop leaves them.
        cases = [
            ("ISP_OK", 0, "200", 0, 0),          # passed: no reason
            ("ISP_BAD", 28, "000", 1, 0),        # the provider times out, the tunnel answers
            ("ISP_BAD", 28, "000", 1, 0),
            ("ISP_BAD", 56, "000", 1, 0),        # reset
            ("UNKNOWN", 28, "000", 1, 7),        # the tunnel fails too
            ("UNKNOWN", 0, "503", 0, 0),         # 5xx straight
            ("ISP_BAD", 0, "451", 1, 0),
        ]
        body = "".join(f'CLASS={c}; ISP_RC={rc}; CODE={code}; NEED_VPN={nv}; VPN_RC={vr}; audit_reason\n' for c, rc, code, nv, vr in cases)
        body += 'REASONS="$REASONS nodns"\n' + summary + 'echo "$REASON_SUM"'
        got = run(body)
        want = {"isp_timeout:2", "vpn_down:1", "nodns:1", "isp_reset:1", "http_5xx:1", "http_451:1"}
        if set(got.split(",")) != want or not got.startswith("isp_timeout:2,"):
            fail(f"{shell[0]}: the reasons, the most frequent first: {got}")

if "[ $((CHECKED % AUDIT_PORTION)) -ne 0 ] || audit_pause" not in AUDIT:
    fail("the run is not cut into portions")
if "|paused=${PAUSED}s|reasons=${REASON_SUM:-none}\"" not in AUDIT:
    fail("the summary line carries the pauses and the reasons")
print("POLICY_AUDIT_PAUSE=PASS")
