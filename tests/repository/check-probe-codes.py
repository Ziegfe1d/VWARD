#!/usr/bin/env python3
"""A real answer of the server is not a reason for the VPN (owner 02.11.2026).

ir-20.ozone.ru: HINT_DIRECT_OK 403 at 18:10, HINT_AUTO_VPN at 18:12 - the hint path sent a site
into the VPN on ONE failed direct check, without ru_zone. Now: a failed check is repeated, the
direct check itself must work (vward_isp_control), Russian zones never go (add_hint_adaptive).
400/401/403/404 directly is the server answering: ISP_OK in the reconciler and the night audit;
451 and silence keep their meaning.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
RECON = (ROOT / "components/route-reconciler/scripts/vward-route-reconciler.sh").read_text()
AUDIT = (ROOT / "components/policy-sync/scripts/vward-policy-audit.sh").read_text()


def fail(m):
    raise SystemExit(f"PROBE_CODES=FAIL: {m}")


def func(src, name):
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", src, re.S | re.M)
    if not m:
        fail(f"missing {name}")
    return m.group(0)


if 'if ru_zone "$H"; then' not in func(ENGINE, "add_hint_adaptive"):
    fail("the hint path must check ru_zone")

# The hint path: the direct check answers in sequence from SEQ (1 ok, 0 failed), the control from CTRL.
hint = func(ENGINE, "handle_hint")
def hint_run(seq, ctrl):
    sh = f"""SEQ="{seq}"; EVENT_LOG=/dev/stdout; WAN=eth3
hint_direct_known() {{ return 0; }}; regular_cooldown() {{ return 1; }}; agh_blocked() {{ return 1; }}
resolve_ipv4() {{ echo 192.0.2.1; }}; sleep() {{ :; }}
probe() {{ c=${{SEQ%"${{SEQ#?}}"}}; SEQ=${{SEQ#?}}; P_CODE=403; P_TIME=0.1; [ "$c" = 1 ]; }}
vward_isp_control() {{ return {ctrl}; }}
save_state() {{ echo "STATE $2"; }}; add_hint_adaptive() {{ echo "ADD $1"; }}
{hint}handle_hint ir-20.ozone.ru
"""
    return subprocess.run(["sh", "-c", sh], capture_output=True, text=True, timeout=30).stdout
out = hint_run("01", 0)
if "ADD" in out or "STATE DIRECT_OK" not in out:
    fail(f"RED: one failed direct check must not send a site into the VPN: {out}")
out = hint_run("00", 1)
if "ADD" in out or "HINT_ABORT_ISP_UNRELIABLE" not in out:
    fail(f"a failed check while the direct check itself does not work proves nothing: {out}")
out = hint_run("00", 0)
if "ADD ir-20.ozone.ru" not in out:
    fail(f"two failed checks with a working direct check: the hint path goes on (ru_zone decides there): {out}")

# The reconciler's verdict by code (probe_result stubbed: rc|code|time).
cls = func(RECON, "classify_isp_vs_vpn")
def classify(isp, vpn):
    sh = f"""probe_result() {{ if [ "$2" = eth3 ]; then echo "{isp}"; else echo "{vpn}"; fi; }}
WAN=eth3; WG=nwg1
{cls}classify_isp_vs_vpn h 192.0.2.1"""
    return subprocess.run(["sh", "-c", sh], capture_output=True, text=True, timeout=30).stdout.split("|")[0].strip()
for code in ("400", "401", "403", "404"):
    if classify(f"0|{code}|0.2", "0|200|0.3") != "ISP_OK":
        fail(f"RED: {code} directly is the server answering: {classify(f'0|{code}|0.2', '0|200|0.3')}")
if classify("0|451|0.2", "0|200|0.3") != "ISP_BAD":
    fail("451 directly with an answer through the VPN stays ISP_BAD")
if classify("0|200|0.2", "0|200|0.3") != "ISP_OK":
    fail("200 directly is ISP_OK")
if "2??|3??|400|401|403|404)" not in AUDIT:
    fail("the night audit must count 400/401/403/404 directly as ISP_OK")
print("PROBE_CODES=PASS")
