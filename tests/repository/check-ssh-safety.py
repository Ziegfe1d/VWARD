#!/usr/bin/env python3
"""SSH to the router always works, whatever VWARD does.

- The cron supervisor marks the SSH server and its sessions (dropbear, sshd) as the last thing
  the kernel may stop when memory runs out (oom_score_adj -1000), once a minute, writing only
  what differs; other programs are left alone.
- Entware's SSH server that is not running starts again within a minute: after a reboot its
  start script took a pid file from before the reboot for a running server (a Viva,
  2026-10-12); a failed start is retried with a growing pause, logged once.
- No home, provider-shared or reserved range ever goes into a tunnel, from the IP categories
  or from the Panel: the router's own answers there (an SSH session from the internet, the
  Panel, DNS) would follow it into the VPN."""

import os
import re
import shutil
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

# keep_ssh: a dropbear from Entware (its program under /opt) counts, Keenetic's own does not.
fns = "".join(re.search(rf"^{n}\(\)\n\{{\n.*?^\}}\n", sup, re.S | re.M).group(0) for n in ("ssh_running", "keep_ssh"))
if "    keep_ssh\n" not in sup.split("watch_services()", 1)[1][:60]:
    fail("the supervisor does not keep the SSH server running every minute")
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp); proc = t / "proc"; proc.mkdir()
    run_ = t / "run"; run_.mkdir()
    init = t / "S51dropbear"
    # Entware's start script on Keenetic: «running» is a live number in the pid file.
    init.write_text(f"""#!/bin/sh
PIDFILE="{run_}/dropbear.pid"
echo "$1" >> "{t}/init.calls"
[ -f $PIDFILE ] && [ -d "{proc}/$(cat $PIDFILE)" ] && {{ echo dropbear already running; exit 0; }}
[ -e "{t}/fail" ] && exit 1
mkdir -p "{proc}/4242"; ln -sf /opt/sbin/dropbear "{proc}/4242/exe"; echo 4242 > $PIDFILE
""")
    init.chmod(0o755)
    (t / "pidof").write_text(f'#!/bin/sh\nfor d in {proc}/*; do [ -L "$d/exe" ] && basename "$d"; done | tr "\\n" " "\n')
    (t / "pidof").chmod(0o755)
    env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}")
    log = t / "sup.log"
    def keep(times=1, state=""):
        body = (f'PROC={proc}\nSSH_INIT={init}\nUNNICE=\nSSH_DOWN=0 SSH_WAIT=1 SSH_SKIP=0\n{state}'
                f'log_event() {{ echo "$*" >> {log}; }}\nsleep() {{ :; }}\n' + fns + "keep_ssh\n" * times)
        r = subprocess.run(["sh", "-c", body], env=env, text=True, capture_output=True, timeout=20)
        if r.returncode != 0:
            fail(f"keep_ssh: {r.returncode} {r.stderr}")
    # After the reboot: the old pid file names process 300, which is something else now.
    (proc / "300").mkdir(); (run_ / "dropbear.pid").write_text("300\n")
    keep()
    if not (proc / "4242").exists() or "SSH_STARTED" not in log.read_text():
        fail(f"a stale pid file must not keep SSH down: {log.read_text() if log.exists() else ''}")
    calls = (t / "init.calls").read_text()
    keep()
    if (t / "init.calls").read_text() != calls:
        fail("a running SSH server must be left alone")
    # Keenetic's own dropbear does not stand in for Entware's.
    shutil.rmtree(proc / "4242"); (proc / "77").mkdir(); os.symlink("/sbin/dropbear", proc / "77" / "exe")
    keep()
    if not (proc / "4242").exists():
        fail("Keenetic's dropbear is not Entware's SSH server")
    # A start that fails: logged once, tried again after a pause, not every minute.
    shutil.rmtree(proc / "4242"); (t / "fail").touch(); log.unlink(); (t / "init.calls").unlink()
    keep(times=4)
    if log.read_text().count("SSH_START_FAILED") != 1 or (t / "init.calls").read_text().count("start") != 2:
        fail(f"failed starts: {log.read_text()!r} {(t / 'init.calls').read_text()!r}")
    # Switched off by the owner (ENABLED=no): not started.
    (t / "fail").unlink(); (t / "init.calls").unlink()
    init.write_text("#!/bin/sh\nENABLED=no\n" + init.read_text().split("\n", 1)[1]); init.chmod(0o755)
    keep()
    if (t / "init.calls").exists():
        fail("ENABLED=no must be respected")

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
