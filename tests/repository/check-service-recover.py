#!/usr/bin/env python3
"""fix.35.3.1: an unfinished service operation has a way out (service-recover).

03.11.2026 04:49-04:50: «service on» / «ai chatgpt.com» refused with service_recovery_required; the same
refusal since 02.11 06:17. A pending service transaction (a killed run, or a rollback whose DNS part
could not be confirmed) blocked every service operation for ever: nothing in VWARD could end it.
service-recover compares Keenetic and VWARD's files with the operation's own before and after:
completed or rolled back -> closed (evidence moved, never deleted); partly done -> the operation's own
compensation, then checked again; an owner's edit or DNS rows on the wrong side -> stays pending with
the reason; «accept» is the owner's explicit choice to keep the router as it is. A running operation
is never touched. The real helper, locks and a stateful Keenetic transport; no router or network.
"""
import os
import signal
import threading
import time
import json
import shutil
import tempfile
from pathlib import Path
import service_fixture as fixture

os.environ["VWARD_DOH_ALIVE"] = "0"


def fail(msg):
    raise SystemExit("SERVICE_RECOVER=FAIL: " + msg)


def last(r):
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def pending_of(s):
    return list((s.tmp / "backup/service-transactions").glob("*/pending"))


def resolved_of(s):
    return list((s.tmp / "backup/service-transactions.resolved").glob("txn.*"))


def killed_refresh(s, owner_edit=False):
    """services-refresh killed (SIGKILL) after one real include: a pending, partly done operation."""
    assert s.run("service", "on", "claude.ai", "auto").returncode == 0
    before = s.cfg.read_text()
    newer = json.loads(json.dumps(s.catalog)); newer["services"][0]["domains"].append("new.example")
    s.served.write_text(json.dumps(newer))
    helper = s.tmp / "fault-helper.sh"
    pidfile, entered, resume = (s.tmp / n for n in ("pid", "entered", "resume"))
    helper.write_text(fixture.HELPER.read_text().replace("ETC=", '[ -e "' + str(pidfile) + '" ] || echo $$ > "' + str(pidfile) + '"\nETC=', 1))
    ndmc = Path(s.env["VWARD_NDMC"]); body = ndmc.read_text()
    pause = ('\ndef fault_pause():\n'
             '    if cmd != "object-group fqdn domain-list0 include new.example": return\n'
             f'    Path({str(entered)!r}).touch()\n'
             f'    while not Path({str(resume)!r}).exists():\n'
             '        import time; time.sleep(0.01)\n')
    body = body.replace('def save():', pause + '\ndef save():')
    body = body.replace('cfg.write_text("\\n".join(lines) + "\\n");', 'cfg.write_text("\\n".join(lines) + "\\n"); fault_pause();')
    ndmc.write_text(body)
    original = fixture.HELPER
    fixture.HELPER = helper
    out = []
    try:
        t = threading.Thread(target=lambda: out.append(s.run("services-refresh", "run")))
        t.start()
        deadline = time.monotonic() + 25
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered.exists(), "barrier not reached"
        os.kill(int(pidfile.read_text()), signal.SIGKILL)
        resume.touch()
        t.join(30)
    finally:
        fixture.HELPER = original
        resume.touch()
    for p in (s.tmp / "change.lock", s.tmp / "edit.lock"):
        shutil.rmtree(p, ignore_errors=True)
    if owner_edit:
        s.cfg.write_text(s.cfg.read_text().replace("    include claude.com\n", "    include claude.com\n    include owner.example\n"))
    assert pending_of(s), "the kill left no pending operation"
    return before


# 1. A killed run: blocked (RED before fix.35.3.1 - no way out), status names it, resolve undoes only
#    its own change, the evidence moves to «resolved», the next service operation works.
with tempfile.TemporaryDirectory() as d:
    s = fixture.Services(Path(d))
    before = killed_refresh(s)
    if "include new.example" not in s.cfg.read_text():
        fail("the fixture did not apply the first include")
    r = s.run("service", "off", "claude.ai")
    if "error=service_recovery_required" not in r.stdout:
        fail("a pending operation must still block: " + r.stdout)
    txn = pending_of(s)[0].parent
    st = s.run("service-recover", "status")
    rows = [l for l in st.stdout.splitlines() if l.startswith("info.txn=")]
    if last(st) != "result=checked" or len(rows) != 1:
        fail("RED: status must list the pending operation: " + st.stdout + st.stderr[-300:])
    f = rows[0][len("info.txn="):].split("|")
    if f[0] != txn.name or not f[1].startswith("services-refresh") or f[3] != "partial" or "domain-list0" not in f[4]:
        fail("status fields: " + rows[0])
    evidence = sorted(p.name for p in txn.iterdir())
    r = s.run("service-recover", txn.name, "resolve")
    if last(r) != "result=changed" or "info.state=partial" not in r.stdout:
        fail("RED: resolve must compensate the operation's own change: " + r.stdout + r.stderr[-300:])
    if s.cfg.read_text() != before:
        fail("the compensation must give back exactly the list before the killed run")
    if pending_of(s) or len(resolved_of(s)) != 1:
        fail("closed: no pending left, the evidence kept in «resolved»")
    kept = resolved_of(s)[0]
    if "state=rolled_back" not in (kept / "resolved").read_text() or not set(evidence) - {"pending"} <= {p.name for p in kept.iterdir()}:
        fail("the resolved folder must hold the evidence and the state: " + str(sorted(p.name for p in kept.iterdir())))
    if (kept.stat().st_mode & 0o077) or (kept.parent.stat().st_mode & 0o077):
        fail("the evidence must stay private")
    r = s.run("service", "off", "claude.ai")
    if r.returncode or "result=changed" not in r.stdout:
        fail("after the recovery the service operations work again: " + r.stdout)
    if s.run("service-recover", "status").stdout.count("info.txn=") != 0:
        fail("status after the recovery")

# 2. A killed run whose list the owner edited meanwhile: no undo over the owner's edit, the reason is
#    said and it stays pending; «accept» is the owner's way out and keeps the edit.
with tempfile.TemporaryDirectory() as d:
    s = fixture.Services(Path(d))
    killed_refresh(s, owner_edit=True)
    txn = pending_of(s)[0].parent
    r = s.run("service-recover", txn.name, "resolve")
    if r.returncode == 0 or "error=service_recovery_unverified" not in r.stdout or not pending_of(s):
        fail("an owner's edit must not be compensated away: " + r.stdout)
    if "owner.example" not in s.cfg.read_text():
        fail("the owner's edit was lost")
    r = s.run("service-recover", txn.name, "accept")
    if last(r) != "result=changed" or pending_of(s) or "owner.example" not in s.cfg.read_text():
        fail("accept must close it and keep the router as it is: " + r.stdout)
    if "state=accepted:" not in (resolved_of(s)[0] / "resolved").read_text():
        fail("accept is recorded as the owner's choice")

# 3. A rollback whose DNS part could not be confirmed (the list's Smart DNS row was put back into
#    AdGuard Home, then the operation failed): the row on the wrong side keeps it pending (dns:);
#    once AdGuard Home no longer holds it the same resolve closes it as rolled back.
with tempfile.TemporaryDirectory() as d:
    s = fixture.Services(Path(d))
    assert s.run("service", "on", "claude.ai", "auto").returncode == 0
    saved = s.etc / "route-engine/domain-lists/domain-list0"
    with saved.open("a") as f:
        f.write("agh=claude.ai\thttps://dns.example/dns-query\n")
    ads = s.tmp / "ads"
    ads.write_text('#!/bin/sh\necho CONTROL=PASS\n'); ads.chmod(0o755)
    s.env["VWARD_ADS_CONTROL_BIN"] = str(ads)
    ndmc = Path(s.env["VWARD_NDMC"])
    ndmc.write_text(ndmc.read_text().replace('if cmd == "system configuration save":',
        'if cmd == "system configuration save" and "object-group fqdn domain-list0" not in cfg.read_text():\n'
        '    print("error: save refused"); sys.exit(0)\nif cmd == "system configuration save":'))
    r = s.run("service", "off", "claude.ai")
    if "error=rollback_incomplete" not in r.stdout or not pending_of(s):
        fail("fixture: the DNS-touching rollback must stay unconfirmed: " + r.stdout)
    txn = pending_of(s)[0].parent
    yaml = Path(s.env["VWARD_ADGUARD_CONFIG"])
    yaml.write_text("dns:\n  upstream_dns:\n    - 9.9.9.10\n    - '[/claude.ai/]https://dns.example/dns-query'\n")
    r = s.run("service-recover", txn.name, "resolve")
    if r.returncode == 0 or "error=service_recovery_unverified" not in r.stdout or "dns:domain-list0" not in r.stdout:
        fail("a Smart DNS row active while its list is in VPN must not be closed: " + r.stdout)
    if not pending_of(s):
        fail("the unverified operation must stay pending")
    yaml.write_text("dns:\n  upstream_dns:\n    - 9.9.9.10\n")
    r = s.run("service-recover", txn.name, "resolve")
    if last(r) != "result=changed" or "info.state=rolled_back" not in r.stdout or pending_of(s):
        fail("the row back on its side: rolled back, closed: " + r.stdout)
    if "https://dns.example" in r.stdout or "https://dns.example" in (s.tmp / "audit.log").read_text():
        fail("a Smart DNS address reached the output or the journal")

# 4. A running operation (its pid alive) is never touched; a bad id is refused.
with tempfile.TemporaryDirectory() as d:
    s = fixture.Services(Path(d))
    assert s.run("service", "on", "claude.ai", "auto").returncode == 0
    txn = s.tmp / "backup/service-transactions/txn.Ab12Cd"
    txn.mkdir(parents=True); txn.chmod(0o700)
    for n in ("groups", "undo", "pending"):
        (txn / n).write_text("")
    (txn / "pid").write_text(str(os.getpid()) + "\n")
    (txn / "op").write_text("service on claude.ai\n")
    r = s.run("service-recover", "txn.Ab12Cd", "resolve")
    if "error=service_recovery_running" not in r.stdout or not (txn / "pending").exists():
        fail("a running operation must not be resolved: " + r.stdout)
    st = s.run("service-recover", "status")
    if "|running|" not in st.stdout:
        fail("status must say it runs: " + st.stdout)
    for bad in ("txn.../x", "../../etc", "txn.ab"):
        if "error=invalid_value" not in s.run("service-recover", bad, "resolve").stdout:
            fail("bad id accepted: " + bad)
# 5. The Panel sees it: services-data lists the pending operation (no helper run, no secrets); the
#    POST «recover» needs a valid id, and «accept» a confirmation.
import subprocess
API = fixture.ROOT / "web/cgi-bin/api.cgi"
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    txn = d / "backup/service-transactions/txn.Zz09Yy"; txn.mkdir(parents=True)
    (txn / "pending").write_text(""); (txn / "groups").write_text("domain-list3\n")
    (txn / "op").write_text("service on chatgpt.com auto\n"); (txn / "dns-risk.domain-list3").write_text("")
    cat = d / "cat.json"; cat.write_text(json.dumps({"schema": 1, "categories": [], "services": [{"id": "a.example", "title": "A", "category": "ai", "domains": ["a.example"]}]}))
    env = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=services-data", "JQ": shutil.which("jq"),
                        "VWARD_CONSOLE_BACKUP_DIR": str(d / "backup"), "VWARD_SERVICES_BUNDLED": str(cat),
                        "VWARD_SERVICES_FETCHED": str(d / "none.json"), "VWARD_CONSOLE_ETC": str(d / "etc"),
                        "VWARD_PROFILE_LIB": str(d / "none.sh"), "VWARD_ROOT_PREFIX": str(d / "root")}
    r = subprocess.run(["sh", str(API)], env=env, text=True, capture_output=True, timeout=60)
    body = json.loads(r.stdout.split("\n\n", 1)[-1])
    rec = body.get("recovery")
    if rec != [{"id": "txn.Zz09Yy", "op": "service on chatgpt.com auto", "since": rec[0]["since"] if rec else "", "groups": ["domain-list3"],
                "running": False, "dns": 1, "owner_edit": 0}]:
        fail("RED: services-data must list the unfinished operation: " + r.stdout[-400:])
api = API.read_text()
for need in ('if [ "$SOP" = recover ]; then', 'SERVICE_RECOVER_ACCEPT', 'ARGS="service-recover $SID $SRM"', "recovery: $recovery"):
    if need not in api:
        fail("api.cgi lacks " + need)
js = (fixture.ROOT / "web/assets/vward-console.js").read_text()
for need in ("function recoveryPanel(list)", "recoveryPanel(a && a.recovery)", "recoveryPanel(V.recovery)", "'svrec-accept': c => svRecover(c.id.slice(13), 'accept')"):
    if need not in js:
        fail("Panel lacks " + need)
print("SERVICE_RECOVER=PASS")
