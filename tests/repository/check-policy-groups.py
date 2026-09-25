#!/usr/bin/env python3
"""IP categories: DNS routes name the tunnel by its interface (Wireguard0) on
Keenetic, older setups by the kernel device (nwg0).  Both must count, or no
domain is seen as going through the tunnel and no IP category turns on."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = (ROOT / "components/policy-sync/scripts/vward-policy-sync.sh").read_text()
FUNC = SYNC[SYNC.index("collect_vpn_domains()\n"):SYNC.index("collect_categories()\n")]

RUN = """dns-proxy
    route object-group domain-list0 Wireguard0 auto
    route object-group domain-list1 nwg0 auto
    route object-group domain-list4 ISP auto
!
object-group fqdn domain-list0
    include telegram.org
!
object-group fqdn domain-list1
    include youtube.com
!
object-group fqdn domain-list4
    include claude.ai
!
"""

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "run").write_text(RUN)
    script = f'WORK="{tmp}"; WG=nwg0; VWARD_TUNNEL_INTERFACE=Wireguard0\n{FUNC}\ncollect_vpn_domains "{tmp}/run"\n'
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=True).stdout.split()
    if out != ["telegram.org", "youtube.com"]:
        raise SystemExit(f"FAIL: tunnel domains {out}")
print("POLICY_GROUPS=PASS")
