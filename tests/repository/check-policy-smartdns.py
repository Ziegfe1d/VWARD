#!/usr/bin/env python3
"""Smart DNS wins over an IP category. A category whose subnets hold the address a Smart DNS
domain resolves to (Cloudflare carries such sites) would take that domain into the tunnel, so
policy-sync leaves it off and notes why; the Smart DNS guard switch off lets it through. The
diagnostics name the category, the Panel says why it is off."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = (ROOT / "components/policy-sync/scripts/vward-policy-sync.sh").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"POLICY_SMARTDNS=FAIL: {message}")


m = re.search(r"^smartdns_hold\(\)\n\{\n.*?^\}\n", SYNC, re.S | re.M)
if not m or 'smartdns_hold "$RUN" "$CATS"' not in SYNC:
    fail("policy-sync does not hold back categories that hold Smart DNS addresses")

RUNNING = """dns-proxy
    https upstream https://doh.example.net/dns-query dot domain example-ai.com
!
"""

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "catalog").mkdir()
    (t / "catalog/cloudflare.cidr").write_text("198.51.0.0/16\n203.0.113.0/24\n")
    (t / "catalog/telegram.cidr").write_text("192.0.2.0/24\n")
    (t / "catalog/meta.cidr").write_text("198.18.0.0/15\n")
    (t / "run").write_text(RUNNING)
    (t / "nslookup").write_text("#!/bin/sh\nprintf 'Server: 127.0.0.1\\nAddress 1: 127.0.0.1\\n\\nName: %s\\nAddress 1: 198.51.100.7\\nAddress 2: 2001:db8::1\\n' \"$1\"\n")
    (t / "nslookup").chmod(0o755)

    def run(guard: str) -> tuple[list[str], str]:
        (t / "cats").write_text("cloudflare\nmeta\ntelegram\n")
        (t / "lists.conf").write_text(f"smartdns_guard={guard}\n")
        script = (f'WORK={t}; CATALOG={t}/catalog; SMARTDNS_HELD={t}/held; LISTS_CONF={t}/lists.conf; NSLOOKUP={t}/nslookup\n'
                  f'log() {{ echo "$*" >> {t}/log; }}\n' + m.group(0) + f'smartdns_hold {t}/run {t}/cats\n')
        r = subprocess.run(["sh", "-c", script], text=True, capture_output=True, timeout=30)
        if r.returncode != 0 or r.stderr:
            fail(f"smartdns_hold: {r.returncode} {r.stderr}")
        held = (t / "held").read_text() if (t / "held").exists() else ""
        return (t / "cats").read_text().split(), held

    cats, held = run("1")
    if cats != ["meta", "telegram"] or held != "cloudflare|example-ai.com\n":
        fail(f"the category with the Smart DNS address must stay off and be noted: {cats} {held!r}")
    cats, held = run("0")
    if cats != ["cloudflare", "meta", "telegram"] or held:
        fail(f"with the Smart DNS guard off nothing is held: {cats} {held!r}")

api = (ROOT / "web/cgi-bin/api.cgi").read_text()
js = (ROOT / "web/assets/vward-console.js").read_text()
if "(IP-категория $SD_CAT)" not in api or "smartdns_held:$smartdns_held" not in api:
    fail("the diagnostics or the API do not name the category")
if "в ней адрес Smart DNS" not in js:
    fail("the Panel does not say why the category is off")
print("POLICY_SMARTDNS=PASS")
