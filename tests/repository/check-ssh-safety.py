#!/usr/bin/env python3
"""SSH to the router always works, whatever VWARD does.

- The cron supervisor marks the SSH server and its sessions (dropbear, sshd) as the last thing
  the kernel may stop when memory runs out (oom_score_adj -1000), once a minute, writing only
  what differs; other programs are left alone.
- No home, provider-shared or reserved range ever goes into a tunnel, from the IP categories
  or from the Panel: the router's own answers there (an SSH session from the internet, the
  Panel, DNS) would follow it into the VPN."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"SSH_SAFETY=FAIL: {message}")


sup = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
m = re.search(r"^protect_ssh\(\)\n\{\n.*?^\}\n", sup, re.S | re.M)
if not m or "    protect_ssh\n" not in sup.split("watch_services()", 1)[1][:80]:
    fail("the supervisor does not protect SSH every minute")
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    for pid, adj in (("101", "0"), ("102", "-1000"), ("103", "0"), ("200", "0")):
        (t / pid).mkdir(); (t / pid / "oom_score_adj").write_text(adj + "\n")
    (t / "pidof").write_text('#!/bin/sh\ncase "$*" in "dropbear sshd") echo "101 102 103 999" ;; esac\n')
    (t / "pidof").chmod(0o755)
    env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}")
    script = f'PROC={t}\n' + m.group(0) + "protect_ssh\n"
    r = subprocess.run(["sh", "-c", script], env=env, text=True, capture_output=True, timeout=20)
    if r.returncode != 0 or r.stderr:
        fail(f"protect_ssh: {r.returncode} {r.stderr}")
    got = {p: (t / p / "oom_score_adj").read_text().strip() for p in ("101", "102", "103", "200")}
    if got != {"101": "-1000", "102": "-1000", "103": "-1000", "200": "0"}:
        fail(f"oom_score_adj after protect_ssh: {got}")

RANGES = "0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 198.18.0.0/15 224.0.0.0/3"
for path in ("components/policy-sync/scripts/vward-policy-sync.sh", "components/console/scripts/vward-console-config.sh"):
    if f'split("{RANGES}"' not in (ROOT / path).read_text():
        fail(f"{path}: the reserved ranges are not the shared list")
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
m = re.search(r"\| awk -F'\[\./\]' '\n(.*?)' \|\| die private_subnet 64", helper, re.S)
if not m:
    fail("the Panel's subnet into a tunnel is not checked against the reserved ranges")
for cidr, private in (("192.168.1.0/24", True), ("10.20.0.0/16", True), ("100.64.0.0/10", True), ("172.0.0.0/8", True),
                      ("149.154.160.0/20", False), ("91.108.4.0/22", False), ("8.8.8.8/32", False), ("230.0.0.0/8", True)):
    r = subprocess.run(["awk", "-F[./]", m.group(1)], input=cidr + "\n", text=True, capture_output=True)
    if (r.returncode == 0) != private:
        fail(f"{cidr}: private={r.returncode == 0}, expected {private}")
if "private_subnet:" not in (ROOT / "web/assets/vward-console.js").read_text():
    fail("the Panel has no words for private_subnet")
print("SSH_SAFETY=PASS")
