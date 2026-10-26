#!/usr/bin/env python3
"""Smart DNS wins over an IP category, address by address (fix.34.1, r1 and r3). The block
around the address a Smart DNS domain resolves to stays out of the tunnel; the rest of the
category keeps its routes (25.10: meta.ai took all of Meta, copilot.microsoft.com Cloudflare and
Discord). Every Smart DNS domain is resolved, 42 of them too (the limit of 32 is gone); a domain
without an answer keeps its addresses from the run before. The guard switch off holds nothing.
Run in BusyBox ash when it is there (the router's shell)."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = (ROOT / "components/policy-sync/scripts/vward-policy-sync.sh").read_text()
SH = ["busybox", "sh"] if shutil.which("busybox") else ["sh"]


def fail(message: str) -> None:
    raise SystemExit(f"POLICY_SMARTDNS=FAIL: {message}")


def func(name: str) -> str:
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", SYNC, re.S | re.M)
    if not m:
        fail(f"missing shell function {name}")
    return m.group(0)


if 'smartdns_hold "$RUN" "$CATS"' not in SYNC or "head -n 32" in func("smartdns_hold"):
    fail("policy-sync must hold Smart DNS addresses for every domain, without the limit of 32")


def num(a: str) -> int:
    q = [int(x) for x in a.split(".")]
    return ((q[0] * 256 + q[1]) * 256 + q[2]) * 256 + q[3]


def covers(cidr: str, addr: str) -> bool:
    net, ln = cidr.split("/")
    z = 2 ** (32 - int(ln))
    return num(net) // z == num(addr) // z


# 42 Smart DNS domains (Keenetic's dns-proxy has 8, AdGuard Home the other 34), 9 active categories.
DOMAINS = [f"ai{i}.example" for i in range(42)]
ADDR = {d: f"198.18.{i % 6}.{10 + i}" for i, d in enumerate(DOMAINS)}
ADDR["ai7.example"] = "203.0.113.9"          # behind "cloudflare" too
ADDR["ai41.example"] = ""                    # no answer now: the address from the run before
CACHED = "ai41.example 192.0.2.77\nold-gone.example 198.51.100.200\n"
CATS = {
    "cloudflare": ["198.18.0.0/15", "203.0.113.0/24", "104.16.0.0/13"],
    "meta": ["198.18.0.0/16", "157.240.0.0/16"],
    "discord": ["162.159.128.0/17", "192.0.2.0/24"],
    "telegram": ["91.108.4.0/22", "149.154.160.0/20"],
    "google": ["8.8.8.0/24"],
    "fastly": ["151.101.0.0/16"],
    "cloudfront": ["13.32.0.0/15"],
    "twitter": ["104.244.40.0/21"],
    "spotify": ["35.186.224.0/20"],
}
RUNNING = "dns-proxy\n" + "".join(
    f"    https upstream https://doh.example.net/dns-query dot domain {d}\n" for d in DOMAINS[:8]) + "!\n"
AGH = "".join(d + "\n" for d in DOMAINS[8:])

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "catalog").mkdir()
    for c, nets in CATS.items():
        (t / f"catalog/{c}.cidr").write_text("".join(n + "\n" for n in nets))
    (t / "run").write_text(RUNNING)
    (t / "agh").write_text(AGH)
    answers = "".join(f"{d}) a='{a}' ;;\n" for d, a in ADDR.items())
    (t / "nslookup").write_text(
        "#!/bin/sh\necho \"$1\" >> \"${0%/*}/asked\"\ncase \"$1\" in\n" + answers + "*) a= ;;\nesac\n"
        "printf 'Server: 127.0.0.1\\nAddress 1: 127.0.0.1\\n\\nName: %s\\n' \"$1\"\n"
        "[ -z \"$a\" ] || printf 'Address 1: %s\\nAddress 2: 2001:db8::1\\n' \"$a\"\n")
    (t / "nslookup").chmod(0o755)

    def run(guard: str) -> tuple[list[str], str, str]:
        (t / "cats").write_text("".join(c + "\n" for c in CATS))
        (t / "lists.conf").write_text(f"smartdns_guard={guard}\n")
        (t / "resolved").write_text(CACHED)
        for f in ("held", "blocks", "asked", "log"):
            (t / f).unlink(missing_ok=True)
        script = (f'WORK={t}; CATALOG={t}/catalog; SMARTDNS_HELD={t}/held; SMARTDNS_BLOCKS={t}/blocks\n'
                  f'SMARTDNS_ADDR_CACHE={t}/resolved; SMARTDNS_HOLD_PREFIX=24; LISTS_CONF={t}/lists.conf; NSLOOKUP={t}/nslookup\n'
                  f'vward_agh_smartdns_domains() {{ cat {t}/agh; }}\n'
                  f'log() {{ echo "$*" >> {t}/log; }}\n' + func("smartdns_hold") + f'smartdns_hold {t}/run {t}/cats\n')
        r = subprocess.run(SH + ["-c", script], text=True, capture_output=True, timeout=60)
        if r.returncode != 0 or r.stderr:
            fail(f"smartdns_hold: {r.returncode} {r.stderr}")
        read = lambda f: (t / f).read_text() if (t / f).exists() else ""
        return (t / "cats").read_text().split(), read("held"), read("blocks")

    cats, held, blocks = run("1")
    asked = (t / "asked").read_text().split()
    if sorted(set(asked)) != sorted(DOMAINS):
        fail(f"every Smart DNS domain must be resolved (42), asked {len(set(asked))}")
    if cats != list(CATS) or held:
        fail(f"all 9 categories must stay active, none held whole: {cats} {held!r}")
    rows = [line.split("|") for line in blocks.split()]
    got = {(b, d) for b, d, _ in rows}
    want = {(".".join(a.split(".")[:3]) + ".0/24", d) for d, a in ADDR.items() if a}
    want.add(("192.0.2.0/24", "ai41.example"))
    if got != want:
        fail(f"held blocks: {sorted(got ^ want)[:6]}")
    if {c for _, _, c in rows} != {"cloudflare", "meta", "discord"}:
        fail(f"blocks are noted with their categories: {sorted({c for _, _, c in rows})}")
    if "old-gone.example" in (t / "resolved").read_text() or "ai41.example 192.0.2.77" not in (t / "resolved").read_text():
        fail("the address cache keeps the domains that are still Smart DNS, and only those")

    # The routes: the categories' subnets without the held blocks, nothing else lost.
    wanted = "".join(n + "\n" for nets in CATS.values() for n in nets)
    (t / "wanted").write_text(wanted)
    r = subprocess.run(SH + ["-c", f"SMARTDNS_HOLD_PREFIX=24\n{func('smartdns_split')}smartdns_split {t}/blocks {t}/wanted"],
                       text=True, capture_output=True, timeout=60)
    if r.returncode != 0 or r.stderr:
        fail(f"smartdns_split: {r.stderr}")
    routes = r.stdout.split()
    held_addr = [a for a in ADDR.values() if a] + ["192.0.2.77"]
    if any(covers(c, a) for c in routes for a in held_addr):
        fail("a route still takes a Smart DNS address into the tunnel")
    def total(cs: list[str]) -> int:
        spans, size, end = sorted((num(c.split("/")[0]), 2 ** (32 - int(c.split("/")[1]))) for c in set(cs)), 0, -1
        for s, z in spans:
            if s + z > end:
                size += s + z - max(s, end)
                end = s + z
        return size
    block_space = 2 ** 8 * len({b for b, _ in want})
    if total(routes) != total(wanted.split()) - block_space:
        fail(f"only the held blocks may leave the tunnel: {total(wanted.split()) - total(routes)} != {block_space}")
    for c in ("91.108.4.0/22", "149.154.160.0/20", "104.16.0.0/13", "157.240.0.0/16", "8.8.8.0/24"):
        if c not in routes:
            fail(f"a subnet without a Smart DNS address is kept as is: {c}")

    cats, held, blocks = run("0")
    if cats != list(CATS) or held or blocks:
        fail(f"with the Smart DNS guard off nothing is held: {cats} {held!r} {blocks!r}")

api = (ROOT / "web/cgi-bin/api.cgi").read_text()
js = (ROOT / "web/assets/vward-console.js").read_text()
if "(IP-категория $SD_CAT)" not in api or "smartdns_held:$smartdns_held" not in api:
    fail("the diagnostics or the API do not name the category")
if "в ней адрес Smart DNS" not in js:
    fail("the Panel does not say why the category is off")
print("POLICY_SMARTDNS=PASS")
