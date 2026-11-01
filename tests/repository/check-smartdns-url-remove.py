#!/usr/bin/env python3
"""Smart DNS removal on KeeneticOS 5.1.8: only «dns-proxy no https upstream URL» works (01.11.2026).

Owner, Viva 1.11 23:50: 8 lines of one dead server; «dns-proxy no <line>» and the forms with the domain
gave «argument parse error» or removed nothing; the URL form took all 8. doh_remove_url uses it as
the last form: the read must be unchanged, the other lines of the same server go back as they were,
other servers' lines stay, anything else -> every line of the server back, error. Cases: the whole
server (clear), one domain of a shared server, partial removal by Keenetic, an ndmc error, the
configuration changed meanwhile, a line that cannot be put back.
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
RUNNING = "interface Wireguard0\n!\ndns-proxy\n    route object-group Mine Wireguard0 auto\n!\n"


def fail(msg):
    raise SystemExit("SMARTDNS_URL_REMOVE=FAIL: " + msg)


# KeeneticOS 5.1.8 as observed: removal only by server URL (4 words), longer «no» forms are refused.
FAKE = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@"); d = cfg.parent
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(0)
lines = cfg.read_text().splitlines()
i = lines.index("dns-proxy"); j = lines.index("!", i)
if cmd.startswith("dns-proxy no "):
    w = cmd.split()
    if (d / "change-before").exists():
        (d / "change-before").unlink()
        lines.insert(j, "    https upstream https://third.example/q domain new.example")
        cfg.write_text("\n".join(lines) + "\n")
        print("Command::Base: argument parse error."); sys.exit(0)
    if w[2:4] == ["route", "object-group"]:
        cfg.write_text("\n".join(l for l in lines if not l.strip().startswith(" ".join(w[2:6]))) + "\n"); sys.exit(0)
    if len(w) != 5 or w[2:4] != ["https", "upstream"]:
        print("Command::Base: argument parse error."); sys.exit(0)
    if (d / "url-error").exists():
        print("Core::Configurator: error: synthetic"); sys.exit(0)
    if (d / "change-once").exists():
        (d / "change-once").unlink()
        lines.insert(j, "    https upstream https://third.example/q domain new.example")
        cfg.write_text("\n".join(lines) + "\n"); sys.exit(0)
    gone = [l for l in lines if l.strip().startswith("https upstream " + w[4] + " ")]
    if (d / "partial").exists(): gone = gone[:2]
    cfg.write_text("\n".join(l for l in lines if l not in gone) + "\n"); sys.exit(0)
if cmd.startswith("dns-proxy route "):
    lines.insert(j, "    " + cmd[len("dns-proxy "):]); cfg.write_text("\n".join(lines) + "\n"); sys.exit(0)
if cmd.startswith("dns-proxy https upstream "):
    body = cmd[len("dns-proxy "):]
    if (d / "refuse-add").exists() and body.endswith((d / "refuse-add").read_text().strip()):
        print("Core::Configurator: error: synthetic refusal"); sys.exit(0)
    lines.insert(j, "    " + body); cfg.write_text("\n".join(lines) + "\n"); sys.exit(0)
sys.exit(0)
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cfg = tmp / "running.cfg"
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=Mine\n"); devconf.chmod(0o600)
    (tmp / "policy").mkdir(); (tmp / "root/tmp").mkdir(parents=True); (tmp / "etc").mkdir()
    adm = tmp / "admission.sh"; adm.write_text("vward_admission_enter() { return 0; }\nvward_admission_leave() { return 0; }\n")
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"), "VWARD_ADMISSION_LIB": str(adm),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_POLICY_STATE": str(tmp / "policy"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_POLICY_SYNC_BIN": str(tmp / "no-sync"),
        "VWARD_DOH_RETRY_DELAY": "0", "VWARD_SNAPSHOT_RETRY": "0", "VWARD_ADGUARD_CONFIG": str(tmp / "missing.yaml"),
    }
    own = "https://doh.example/dns-query/synthetic-token"
    other = "https://other.example/dns-query"
    doms = ["claude.ai", "claude.app", "claude.com", "claude.new", "chatgpt.com", "gpt3-openai.com", "oaistatic.com", "openai.com"]
    rows = ["https upstream " + own + " dnsm on ISP domain " + x for x in doms] + ["https upstream " + other + " dnsm on ISP domain other.example"]
    conf = tmp / "etc/smartdns.conf"

    def reset(with_url=True):
        for f in ("url-error", "change-once", "change-before", "partial", "refuse-add"):
            (tmp / f).unlink(missing_ok=True)
        conf.write_text(("SMARTDNS_URL=" + own + "\n" if with_url else "") + "SMARTDNS_STORE=keenetic\n")
        cfg.write_text(RUNNING.replace("    route", "    " + "\n    ".join(rows) + "\n    route"))

    def doh():
        return {l.strip() for l in cfg.read_text().splitlines() if l.strip().startswith("https upstream")}

    def run(*args):
        return subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, timeout=60)

    # 1. Clear: all 8 lines of the server go in one command; the other server stays.
    reset()
    r = run("smartdns-server", "clear")
    if r.returncode or "result=changed" not in r.stdout or doh() != {rows[-1]}:
        fail("RED: clear on 5.1.8 must remove all 8 lines of the server by URL: " + r.stdout + str(doh()))
    if "synthetic-token" in (tmp / "audit.log").read_text():
        fail("the server token leaked into the audit log")
    # 2. One domain of a shared server: the other 7 go back exactly, the other server untouched.
    reset()
    r = run("smartdns-domain", "remove", "chatgpt.com")
    if r.returncode or doh() != set(rows) - {rows[4]}:
        fail("one domain of a shared server: the others must be put back: " + r.stdout + str(sorted(set(rows) - doh())))
    # 3. ndmc refuses the URL form: nothing changes, an error.
    reset(); before = doh(); (tmp / "url-error").touch()
    r = run("smartdns-domain", "remove", "chatgpt.com")
    if "result=changed" in r.stdout or doh() != before:
        fail("an ndmc error must change nothing: " + r.stdout)
    # 4. Keenetic removes only part: every line of the server back, unsafe error.
    reset(); before = doh(); (tmp / "partial").touch()
    r = run("smartdns-domain", "remove", "chatgpt.com")
    if "error=doh_remove_unsafe" not in r.stdout or doh() != before:
        fail("partial removal must restore every line and abort: " + r.stdout + str(before - doh()))
    # 5. A line of the server cannot be put back: everything back as far as possible, unsafe error.
    reset(); before = doh(); (tmp / "refuse-add").write_text("domain claude.new")
    r = run("smartdns-domain", "remove", "chatgpt.com")
    if "error=doh_remove_unsafe" not in r.stdout or "result=changed" in r.stdout:
        fail("a line that cannot be put back must abort: " + r.stdout)
    (tmp / "refuse-add").unlink()
    # 6a. Another program adds a line before the removal by server: the read differs, nothing is done
    #     then; the next try reads again and succeeds; the new line is kept.
    newl = "https upstream https://third.example/q domain new.example"
    reset(); (tmp / "change-before").touch()
    r = run("smartdns-domain", "remove", "chatgpt.com")
    if doh() != (set(rows) - {rows[4]}) | {newl}:
        fail("a configuration changed before the step must not lose lines: " + r.stdout + str(sorted(((set(rows) - {rows[4]}) | {newl}) ^ doh())))
    # 6b. It changes during the removal by server (Keenetic applied another change instead): abort,
    #     every line of the server back, the new line kept, nothing lost.
    reset(); before = doh(); (tmp / "change-once").touch()
    r = run("smartdns-domain", "remove", "chatgpt.com")
    if "error=doh_remove_unsafe" not in r.stdout or doh() != before | {newl}:
        fail("a configuration changed during the step must abort without loss: " + r.stdout + str(sorted((before | {newl}) ^ doh())))
    # 7. The lines use another address of the same server (another token): the Panel's button cleared
    #    the address only. Now the one same-host address is cleared; a second clear is «unchanged».
    reset()
    conf.write_text("SMARTDNS_URL=https://doh.example/dns-query/older-token\nSMARTDNS_STORE=keenetic\n")
    r = run("smartdns-server", "clear")
    if r.returncode or "result=changed" not in r.stdout or doh() != {rows[-1]} or "cleared=keenetic:8," not in r.stdout:
        fail("RED: the same server under another token must be cleared, with a report: " + r.stdout + str(doh()))
    r = run("smartdns-server", "clear")
    if r.stdout.strip().splitlines()[-1] != "result=unchanged" or doh() != {rows[-1]}:
        fail("a second clear must be idempotent and never touch another server: " + r.stdout)
    # 8. A list back to the provider while its saved Smart DNS server does not answer (the subscription
    #    ended): the saved lines are NOT put back - the domains stay on the ordinary DNS - and the
    #    report says so; a live server's lines come back as before.
    alive = tmp / "alive"; alive.mkdir()
    env["VWARD_DOH_ALIVE_DIR"] = str(alive)
    def seed(url, rc):
        k = subprocess.run(["sh", "-c", 'printf %s "$U" | cksum | cut -d" " -f1'], env={"U": url, "PATH": "/usr/bin:/bin"},
                           capture_output=True, text=True).stdout.strip()
        (alive / k).write_text(f"{rc}\n")
    saved_dir = tmp / "etc/route-engine/domain-lists"; saved_dir.mkdir(parents=True, exist_ok=True)
    grp = "object-group fqdn domain-list4\n    include chatgpt.com\n    include other.example\n!\n"
    for own_rc, want_back in ((1, False), (0, True)):
        seed(own, own_rc); seed(other, 0)
        conf.write_text("SMARTDNS_STORE=keenetic\n")
        cfg.write_text(grp + RUNNING.replace("    route object-group Mine", "    route object-group domain-list4 Wireguard0 auto\n    route object-group Mine"))
        sv = saved_dir / "domain-list4"
        sv.write_text("route=ISP\tauto\ndoh=" + rows[4] + "\ndoh=" + rows[-1] + "\n"); sv.chmod(0o600)
        r = run("domain-list", "domain-list4", "bypass")
        if r.returncode or "result=changed" not in r.stdout:
            fail(f"bypass failed (server answers={own_rc == 0}): " + r.stdout + r.stderr[-300:])
        got = doh()
        if (rows[4] in got) != want_back or rows[-1] not in got:
            fail(f"RED: a dead server's saved line must not come back, a live one must (dead={own_rc == 1}): {sorted(got)}")
        audit = (tmp / "audit.log").read_text()
        if own_rc == 1 and ("smartdns_dead=1" not in audit or "synthetic-token" in audit):
            fail("the skipped line must be reported, without the address")
print("SMARTDNS_URL_REMOVE=PASS")
