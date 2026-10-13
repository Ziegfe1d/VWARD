#!/usr/bin/env python3
"""Smart DNS's local DoH client is kept running (Viva 2026-10-13: https-dns-proxy crashed in
libnghttp2 at night, and the AI services behind Smart DNS stayed broken until it was started by
hand). AdGuard Home sends Smart DNS domains to [/a.com/]127.0.0.1:5453; when nothing listens
there, the client's own start script runs again. Listening: left alone. Not used by AdGuard Home:
left alone. Three restarts within 6 hours: the HTTPS library is taken for broken (curl's repair).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"


def fail(message: str) -> None:
    raise SystemExit(f"DOH_KEEP=FAIL: {message}")


busybox = shutil.which("busybox") or fail("busybox is needed")
LISTEN = "  12: 0100007F:154D 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 1 2 0000000000000000 0\n"
HEAD = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops\n"

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "net").mkdir()
    (t / "init.d").mkdir()
    agh = t / "AdGuardHome.yaml"
    agh.write_text("dns:\n  upstream_dns:\n    - '[/claude.ai/chatgpt.com/]127.0.0.1:5453'\n    - https://dns.example/dns-query\n")
    start = t / "init.d/S98smart-doh"
    start.write_text(f'#!/bin/sh\necho "$1" >> "{t}/starts"\n[ -e "{t}/broken" ] || printf "%s%s" "{HEAD.strip()}\n" "{LISTEN.strip()}" > "{t}/net/udp"\n')
    start.chmod(0o755)
    (t / "init.d/S90other").write_text("#!/bin/sh\necho other >> \"%s/other\"\n" % t)
    (t / "init.d/S90other").chmod(0o755)
    env = os.environ | {"VWARD_ADGUARD_CONFIG": str(agh), "VWARD_PROC_NET": str(t / "net"), "VWARD_INITD": str(t / "init.d"),
                        "VWARD_DOH_RESTARTS": str(t / "restarts"), "VWARD_TLS_BROKEN_FLAG": str(t / "tls.broken"),
                        "VWARD_DOH_SETTLE": "0"}

    def run() -> int:
        (t / "net/tcp").write_text(HEAD)
        return subprocess.run([busybox, "sh", "-c", f'. "{LIB}"; vward_doh_keep'], env=env, capture_output=True, text=True).returncode

    # Not listening: its start script runs, it listens again.
    (t / "net/udp").write_text(HEAD)
    rc = run()
    if rc != 10 or not (t / "starts").exists() or (t / "other").exists():
        fail(f"a silent Smart DNS client is not started by its own script: rc={rc}")
    # Listening: left alone.
    n = len((t / "starts").read_text().splitlines())
    if run() != 0 or len((t / "starts").read_text().splitlines()) != n:
        fail("a listening client is restarted")
    # A start that does not help: 11, and the third restart in 6 hours marks the HTTPS library.
    (t / "broken").write_text("")
    (t / "net/udp").write_text(HEAD)
    if run() != 11:
        fail("a start that did not help is not reported")
    if (t / "tls.broken").exists():
        fail("two restarts already mark the library")
    run()
    if not (t / "tls.broken").exists():
        fail("three restarts within 6 hours do not mark the HTTPS library for repair")
    # AdGuard Home no longer uses a local client: nothing to keep.
    agh.write_text("dns:\n  upstream_dns:\n    - https://dns.example/dns-query\n")
    n = len((t / "starts").read_text().splitlines())
    if run() != 0 or len((t / "starts").read_text().splitlines()) != n:
        fail("a client AdGuard Home does not use is started")

print("DOH_KEEP=PASS")
