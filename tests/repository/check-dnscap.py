#!/usr/bin/env python3
"""vward-dnscap, the route engine's DNS capture without libpcap (tcpdump died with
libpcap 1.10.6 on MIPS), built for this machine:

- packets from stdin (--stdin): a query from the LAN to the router's DNS prints
  «q A? name.» (AAAA, HTTPS too), the line the engine's awk reads from tcpdump;
- skipped: other query types, answers, a query from another subnet or from the DNS
  address itself, to another address or port, a later fragment, a name with characters
  a domain never has or with a compression pointer; Ethernet padding is cut off;
- DNS over TCP: a segment that starts a message;
- live (root only): a packet socket on lo with its kernel filter sees a real UDP query.
DNSCAP_RUN runs a router build instead (qemu), as CI does for MIPS and ARM."""

import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/vward-dnscap/dnscap.c"
LAN, DNS = "10.9.0.0/24", "10.9.0.1"


def fail(message: str) -> None:
    raise SystemExit(f"DNSCAP=FAIL: {message}")


def query(name: str, qtype: int, flags: int = 0x0100) -> bytes:
    labels = b"".join(bytes([len(x)]) + x for x in name.encode("latin-1").split(b"."))
    return struct.pack(">HHHHHH", 7, flags, 1, 0, 0, 0) + labels + b"\0" + struct.pack(">HH", qtype, 1)


def ipv4(src: str, dst: str, proto: int, payload: bytes, frag: int = 0, pad: int = 0) -> bytes:
    hdr = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 1, frag, 64, proto, 0,
                      socket.inet_aton(src), socket.inet_aton(dst))
    return hdr + payload + b"\0" * pad


def udp(dport: int, data: bytes) -> bytes:
    return struct.pack(">HHHH", 40000, dport, 8 + len(data), 0) + data


def tcp(dport: int, data: bytes) -> bytes:
    return struct.pack(">HHIIBBHHH", 40001, dport, 1, 0, 5 << 4, 0x18, 1024, 0, 0) + data


with tempfile.TemporaryDirectory() as tmp:
    if os.environ.get("DNSCAP_RUN"):
        run = os.environ["DNSCAP_RUN"].split()
    else:
        binary = Path(tmp) / "vward-dnscap"
        cc = shutil.which("cc") or shutil.which("gcc")
        r = subprocess.run([cc, "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(binary), str(SRC)], capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"does not build: {r.stderr[-800:]}")
        run = [str(binary)]

    r = subprocess.run(run + ["--version"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.startswith("vward-dnscap "):
        fail(f"--version: {r.returncode} {r.stdout!r}")
    for bad in (["br0", "10.9.0.0/33", DNS], ["br0", LAN, "10.9.0"], ["br0", LAN]):
        if subprocess.run(run + bad, capture_output=True).returncode != 64:
            fail(f"bad arguments accepted: {bad}")

    c = "10.9.0.23"
    packets = [
        ipv4(c, DNS, 17, udp(53, query("Example.COM", 1))),
        ipv4(c, DNS, 17, udp(53, query("v6.example.net", 28))),
        ipv4(c, DNS, 17, udp(53, query("svc.example.org", 65)), pad=6),
        ipv4(c, DNS, 17, udp(53, query("mail.example.com", 15))),            # MX
        ipv4(c, DNS, 17, udp(53, query("answer.example.com", 1, 0x8180))),   # an answer
        ipv4("10.8.0.5", DNS, 17, udp(53, query("other-lan.example", 1))),
        ipv4(DNS, DNS, 17, udp(53, query("router-self.example", 1))),
        ipv4(c, "10.9.0.2", 17, udp(53, query("other-dst.example", 1))),
        ipv4(c, DNS, 17, udp(5353, query("mdns.example", 1))),
        ipv4(c, DNS, 17, udp(53, query("frag.example", 1)), frag=0x0010),
        ipv4(c, DNS, 17, udp(53, query("bad name.example", 1))),
        ipv4(c, DNS, 17, udp(53, query("a.b", 1)[:12] + b"\xc0\x0c" + struct.pack(">HH", 1, 1))),
        ipv4(c, DNS, 17, udp(53, query("short.example", 1)[:20])),           # cut short
        ipv4(c, DNS, 6, tcp(53, struct.pack(">H", len(query("tcp.example.com", 1))) + query("tcp.example.com", 1))),
        ipv4(c, DNS, 6, tcp(53, b"")),                                          # a bare ACK
        b"\x60" + b"\0" * 39,                                                  # IPv6
        ipv4(c, DNS, 17, udp(53, query("last.example", 1))),
    ]
    stream = b"".join(struct.pack(">H", len(p)) + p for p in packets)
    r = subprocess.run(run + ["--stdin", LAN, DNS], input=stream, capture_output=True, timeout=30)
    got = r.stdout.decode().splitlines()
    want = ["q A? Example.COM.", "q AAAA? v6.example.net.", "q HTTPS? svc.example.org.", "q A? tcp.example.com.", "q A? last.example."]
    if r.returncode != 0 or got != want:
        fail(f"stdin packets: rc={r.returncode} got {got} want {want} {r.stderr[-300:]!r}")

    # The engine's awk takes the name after «A?» exactly as it does from tcpdump.
    awk = subprocess.run(["awk", '{for (i=1;i<NF;i++) if ($i=="A?"||$i=="AAAA?"||$i=="HTTPS?") {h=tolower($(i+1)); sub(/\\.$/,"",h); print h; break}}'],
                         input=r.stdout, capture_output=True)
    if awk.stdout.decode().split() != ["example.com", "v6.example.net", "svc.example.org", "tcp.example.com", "last.example"]:
        fail(f"engine awk reads {awk.stdout!r}")

    live = "skipped (not root)"
    if os.geteuid() == 0:
        out = Path(tmp) / "live.out"
        with open(out, "wb") as fh:
            p = subprocess.Popen(run + ["lo", "127.0.0.0/8", "127.0.0.53"], stdout=fh, stderr=subprocess.PIPE)
            time.sleep(0.5)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(query("live.example", 1), ("127.0.0.53", 53))
            s.sendto(query("live-other.example", 1), ("127.0.0.53", 54))
            time.sleep(0.5)
            p.terminate()
            err = p.communicate(timeout=5)[1]
        if out.read_text().splitlines() != ["q A? live.example."]:
            fail(f"live on lo: {out.read_text()!r} {err[-300:]!r}")
        live = "lo PASS"
        bad = subprocess.run(run + ["no-such-dev0", LAN, DNS], capture_output=True, text=True, timeout=10)
        if bad.returncode != 2 or "no device" not in bad.stderr:
            fail(f"missing device: {bad.returncode} {bad.stderr!r}")

print(f"DNSCAP=PASS (live: {live})")
