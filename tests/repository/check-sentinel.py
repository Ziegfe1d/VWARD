#!/usr/bin/env python3
"""vward-sentinel, the real-time watcher, built for this machine and run against a /proc
of its own (PROC=), a DNS stand-in and an ACT that records what it is asked:

- a watched program above its limit 3 samples in a row: «leak NAME RSS», once (rate);
- a watched program that disappears: «down NAME» after 3 samples;
- memory below MEM_LOW_KB: «mem-low»; load at the CPU count or memory short: busy flag;
- DNS answers (NXDOMAIN counts) are counted with their time; two misses: «dns-fail»;
- an interface going down (the kernel's netlink, in a network namespace of its own):
  «link DEV down» at once, and «link DEV up»; one not watched is ignored;
- the state file carries all of it; the hourly line goes to HOURS_FILE.
The router builds (MIPS, ARM) are checked by tools/vward-sentinel/build.sh --check in CI."""

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/vward-sentinel/sentinel.c"


def fail(message: str) -> None:
    raise SystemExit(f"SENTINEL=FAIL: {message}")


def wait_for(cond, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # SENTINEL_RUN runs a router build instead, e.g. "qemu-mipsel-static out/vward-sentinel-linux-mipsle".
    if os.environ.get("SENTINEL_RUN"):
        binary = os.environ["SENTINEL_RUN"]
    else:
        binary = tmp / "vward-sentinel"
        cc = shutil.which("cc") or shutil.which("gcc")
        r = subprocess.run([cc, "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(binary), str(SRC)], capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"does not build: {r.stderr[-800:]}")
        binary = str(binary)

    proc = tmp / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "cpuinfo").write_text("".join(f"processor\t: {i}\n\n" for i in range(4)))
    (proc / "stat").write_text("cpu  100 0 100 1000 0 0 0 0 0 0\n")

    def mem(kb):
        (proc / "meminfo").write_text(f"MemTotal:  250000 kB\nMemAvailable:   {kb} kB\n")

    def load(v):
        (proc / "loadavg").write_text(f"{v} 0.50 0.40 1/80 999\n")

    def rss(pid, kb, jiffies=10):
        (proc / str(pid) / "stat").write_text(f"{pid} (sh) S 1 1 1 0 -1 0 0 0 0 0 {jiffies} 5 0 0 20 0 1 0 100 0 0\n")
        (proc / str(pid) / "status").write_text(f"Name:\tsh\nVmRSS:\t  {kb} kB\n")

    mem(60000); load("0.30"); rss(4242, 5000)
    run = tmp / "run"; run.mkdir()
    (run / "engine.pid").write_text("4242\n")
    act = tmp / "act.sh"
    act.write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/acts"\n')
    act.chmod(0o755)

    # DNS stand-in: answers NXDOMAIN with the query's id while it runs.
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("127.0.0.1", 0))
    dns_port = dns.getsockname()[1]
    dns_on = threading.Event(); dns_on.set()
    asked = []

    def serve():
        dns.settimeout(0.2)
        while not stopping.is_set():
            try:
                q, addr = dns.recvfrom(512)
            except OSError:
                continue
            asked.append(q)
            if dns_on.is_set():
                dns.sendto(q[:2] + bytes([0x81, 0x83]) + q[4:], addr)
    stopping = threading.Event()
    threading.Thread(target=serve, daemon=True).start()

    # AdGuard Home in the DNS chain (CHAIN=): its own stand-in, asked every second here.
    chain = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    chain.bind(("127.0.0.1", 0))
    chain_on = threading.Event(); chain_on.set()

    def serve_chain():
        chain.settimeout(0.2)
        while not stopping.is_set():
            try:
                q, addr = chain.recvfrom(512)
            except OSError:
                continue
            if chain_on.is_set():
                chain.sendto(q[:2] + bytes([0x81, 0x80]) + q[4:], addr)
    threading.Thread(target=serve_chain, daemon=True).start()

    state = tmp / "state"
    conf = tmp / "sentinel.conf"
    conf.write_text(f"STATE_DIR={state}\nACT={act}\nHOURS_FILE={tmp}/hours.tsv\nPROC={proc}\nSAMPLE_MS=200\nSTATE_MS=300\n"
                    f"DNS=127.0.0.1:{dns_port}\nDNS_EVERY=1\nDNS_NAME=vward-probe.invalid\nMEM_LOW_KB=16384\nBUSY_MEM_KB=24576\n"
                    f"CHAIN=127.0.0.1:{chain.getsockname()[1]}\nCHAIN_EVERY=1\nCHAIN_MISS=3\n"
                    f"WATCH=engine:{run}/engine.pid:16384\nWATCH=panel:{run}/none.pid:24576\n")
    p = subprocess.Popen(binary.split() + [str(conf)])

    def acts():
        f = tmp / "acts"
        return f.read_text().splitlines() if f.exists() else []

    def st():
        f = state / "state"
        d = {}
        for l in (f.read_text().splitlines() if f.exists() else []):
            k, _, v = l.partition("=")
            d[k] = d[k] + "\n" + v if k in d else v
        return d

    try:
        if not wait_for(lambda: st().get("dns_ok", "0") != "0", 6):
            fail(f"no DNS answer counted: {st()}")
        if asked and b"\x0bvward-probe\x07invalid\x00\x00\x01\x00\x01" not in asked[0]:
            fail("the probe asks vward-probe.invalid, type A")
        # The chain: answers counted; three misses in a row are «chain-fail» within seconds.
        if not wait_for(lambda: st().get("chain_ok", "0") != "0", 6):
            fail(f"no answer of AdGuard Home in the chain counted: {st()}")
        chain_on.clear()
        if not wait_for(lambda: "chain-fail" in acts(), 15):
            fail(f"AdGuard Home silent in the chain is reported: {acts()} {st()}")
        if acts().count("chain-fail") != 1:
            fail(f"one event, not one a miss: {acts()}")
        chain_on.set()
        if not wait_for(lambda: st().get("chain_miss") == "0", 6):
            fail(f"answering again clears the misses: {st()}")
        # A leak: over the limit 3 samples in a row.
        rss(4242, 20000)
        if not wait_for(lambda: "leak engine 20000" in acts(), 4):
            fail(f"a program over its limit is reported: {acts()}")
        time.sleep(1)
        if acts().count("leak engine 20000") != 1:
            fail(f"reported once, not every sample: {acts()}")
        # Memory short: mem-low and the busy flag.
        mem(12000)
        if not wait_for(lambda: "mem-low" in acts() and (state / "busy").exists(), 4):
            fail(f"low memory: {acts()} busy={(state / 'busy').exists()}")
        mem(60000); load("5.10")
        time.sleep(0.8)
        if not (state / "busy").exists():
            fail("load at the CPU count keeps the router busy")
        load("0.20")
        if not wait_for(lambda: not (state / "busy").exists(), 3):
            fail("the busy flag goes when the router is quiet again")
        # The program disappears.
        shutil.rmtree(proc / "4242")
        if not wait_for(lambda: "down engine" in acts(), 4):
            fail(f"a program that is gone is reported: {acts()}")
        # DNS stops answering: two misses, one event.
        dns_on.clear()
        if not wait_for(lambda: "dns-fail" in acts(), 15):
            fail(f"DNS without answers is reported: {acts()} {st()}")
        # The action is written the moment the watcher decides; its state file a sample later.
        wait_for(lambda: int(st().get("dns_fail", "0")) >= 1, 5)
        s = st()
        if not s.get("watch", "").startswith("engine|") or int(s["dns_fail"]) < 1 or s["busy"] != "0" or s["cpus"] != "4":
            fail(f"state: {s}")
        if "panel" in " ".join(acts()):
            fail("a program never seen running is not reported as gone")
    finally:
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=5)
        stopping.set()
    if "STOP" not in (state / "events.log").read_text():
        fail("a clean stop is logged")

    # The kernel's events: in a network namespace of its own, its loopback down and up.
    ip = [shutil.which("ip")] if shutil.which("ip") else ([shutil.which("busybox"), "ip"] if shutil.which("busybox") else None)
    if os.geteuid() == 0 and ip and shutil.which("unshare"):
        ipc = " ".join(ip)

        def netlink(watched):
            (tmp / "acts").unlink(missing_ok=True)
            conf.write_text(f"STATE_DIR={state}\nACT={act}\nHOURS_FILE={tmp}/hours.tsv\nPROC={proc}\nSAMPLE_MS=200\nIFACE={watched}\n")
            script = (f'{ipc} link set lo up; {binary} {conf} & S=$!; sleep 0.5; {ipc} link set lo down; sleep 0.5; '
                      f'{ipc} link set lo up; sleep 0.5; kill $S; wait $S')
            r = subprocess.run(["unshare", "-n", "sh", "-c", script], capture_output=True, text=True, timeout=30)
            return r, acts()
        r, got = netlink("lo")
        if r.returncode != 0 and "Operation not permitted" in r.stderr:
            print("SENTINEL_NETLINK=SKIPPED (no network namespace here)")
        else:
            if got != ["link lo down", "link lo up"]:
                fail(f"netlink: a watched interface down and up, at once: {got} {r.stderr[-300:]}")
            if netlink("vw0")[1]:
                fail("an interface not watched is ignored")
            print("SENTINEL_NETLINK=PASS")
    else:
        print("SENTINEL_NETLINK=SKIPPED (needs root, ip and unshare)")

# The router builds are pinned and reproducible.
sums = (ROOT / "tools/vward-sentinel/SHA256SUMS").read_text().split()
if sorted(sums[1::2]) != sorted(f"vward-sentinel-linux-{a}" for a in ("mipsle", "mips", "arm64", "arm")):
    fail(f"SHA256SUMS names the four router builds: {sums}")
print("SENTINEL=PASS")
