#!/usr/bin/env python3
"""P-7 P0-DNS: deleting a server removes only its active rules; failures roll back.
The admission stub represents an idle updater; no router or network is accessed.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
RUNNING = "interface Wireguard0\n!\ndns-proxy\n    route object-group Mine Wireguard0 auto\n!\n"
def fail(msg):
    raise SystemExit("SMARTDNS_CLEAR=FAIL: " + msg)
FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(1 if cfg.with_name("save-fail").exists() else 0)
if cfg.with_name("no-doh").exists() and cmd.startswith("dns-proxy https"):
    print("\x1b[KCommand::Base error[7405600]: no such command: https.\n\x1b[K"); sys.exit(0)
if cfg.with_name("refuse").exists() and cmd.startswith("dns-proxy no "):
    print("Core::Configurator: error: synthetic refusal of the form\n["); sys.exit(0)
lines = cfg.read_text().splitlines()
ctx = cmd.startswith("dns-proxy ")
body = cmd[len("dns-proxy "):] if ctx else cmd
neg = body.startswith("no ")
if neg: body = body[3:]
out, inblock = [], False
for l in lines:
    if l == "dns-proxy": inblock = True
    elif l == "!": inblock = False
    if neg and ((ctx and inblock and l.strip().startswith(body)) or (not ctx and not l.startswith(" ") and l.startswith(body))):
        continue
    out.append(l)
if not neg:
    if ctx:
        i = out.index("dns-proxy"); j = out.index("!", i); out.insert(j, "    " + body)
    else:
        out.append(body)
cfg.write_text("\n".join(out) + "\n")
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=Mine\n"); devconf.chmod(0o600)
    pol = tmp / "policy"; pol.mkdir()
    (tmp / "root/tmp").mkdir(parents=True)
    (tmp / "etc").mkdir()
    (tmp / "etc/smartdns.conf").write_text("SMARTDNS_URL=https://doh.example/dns-query/synthetic-token\n")
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_POLICY_STATE": str(pol),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_POLICY_SYNC_BIN": str(tmp / "no-sync"),
    }
    admission = tmp / "admission.sh"
    admission.write_text("vward_admission_enter() { return 0; }\nvward_admission_leave() { return 0; }\n")
    env["VWARD_ADMISSION_LIB"] = str(admission)
    env["VWARD_DOH_RETRY_DELAY"] = "0"
    env["VWARD_ADGUARD_CONFIG"] = str(tmp / "missing.yaml")
    own = "https://doh.example/dns-query/synthetic-token"
    other = "https://other.example/dns-query"
    conf = tmp / "etc/smartdns.conf"
    original = "SMARTDNS_URL=" + own + "\nSMARTDNS_STORE=keenetic\n"
    rows = ["https upstream " + own + " domain claude.ai", "https upstream " + own + " domain chatgpt.com", "https upstream " + other + " domain other.example"]
    def reset():
        conf.write_text(original)
        cfg.write_text(RUNNING.replace("    route", "    " + "\n    ".join(rows) + "\n    route"))
    def run(*args):
        return subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, timeout=30)
    reset()
    r = run("smartdns-server", "clear")
    if r.returncode or "result=changed" not in r.stdout or own in cfg.read_text():
        fail("active rules survived clear: " + r.stdout + cfg.read_text())
    if other not in cfg.read_text() or conf.read_text() != "SMARTDNS_STORE=keenetic\n":
        fail("another server or store preference was changed")
    if "synthetic-token" in (tmp / "audit.log").read_text():
        fail("the server token leaked into the audit log")
    if run("smartdns-server", "clear").stdout.strip() != "result=unchanged":
        fail("second clear is not idempotent")
    for flag in ("refuse", "save-fail"):
        reset()
        before = cfg.read_text()
        (tmp / flag).touch()
        r = run("smartdns-server", "clear")
        (tmp / flag).unlink()
        if not r.returncode or "result=changed" in r.stdout or conf.read_text() != original or set(cfg.read_text().splitlines()) != set(before.splitlines()):
            fail(flag + " did not retain configuration and restore rules: " + r.stdout)
    # Removing a domain includes its subdomains and must report AGH failure.
    reset()
    cfg.write_text(cfg.read_text().replace("domain claude.ai", "domain api.claude.ai"))
    r = run("smartdns-domain", "remove", "claude.ai")
    if r.returncode or "domain api.claude.ai" in cfg.read_text():
        fail("subdomain was left in Keenetic: " + r.stdout)
    # Compatibility switch: explicitly retain the previous address-only clear.
    reset()
    switches = tmp / "etc/route-engine/domain-lists.conf"
    switches.parent.mkdir(parents=True, exist_ok=True)
    switches.write_text("smartdns_clear_rules=0\n")
    r = run("smartdns-server", "clear")
    if r.returncode or own not in cfg.read_text() or "SMARTDNS_URL=" in conf.read_text():
        fail("smartdns_clear_rules=0 did not retain legacy clear")
    switches.unlink()
    # A removed server must not return from saved group state on a later bypass.
    saved_dir = tmp / "etc/route-engine/domain-lists"
    saved_dir.mkdir(parents=True, exist_ok=True)
    saved = saved_dir / "domain-list4"
    saved_original = ("route=ISP\tauto\n" + "doh=https upstream " + own + " domain claude.ai\n" +
                      "agh=claude.ai\t" + own + "\n" + "doh=https upstream " + other + " domain other.example\n" +
                      "agh=other.example\t" + other + "\n")
    reset(); saved.write_text(saved_original); saved.chmod(0o600)
    r = run("smartdns-server", "clear")
    if r.returncode or own in saved.read_text() or other not in saved.read_text() or not saved.read_text().startswith("route=ISP\tauto\n"):
        fail("saved state can resurrect removed server: " + r.stdout + saved.read_text())
    # Refuse a symlink after editing the first snapshot; the first edit and DNS roll back.
    reset(); saved.write_text(saved_original)
    target = tmp / "untouched"; target.write_text(saved_original)
    linked = saved_dir / "domain-list9"; linked.symlink_to(target)
    r = run("smartdns-server", "clear")
    linked.unlink()
    if not r.returncode or saved.read_text() != saved_original or target.read_text() != saved_original or conf.read_text() != original or own not in cfg.read_text():
        fail("saved-state failure did not roll back: " + r.stdout)
    # A header-read error must abort; it is not an unrelated file (grep rc=1).
    source = HELPER.read_text()
    prune = re.search(r'^smartdns_prune_saved\(\) \{\n.*?^\}\n', source, re.M | re.S)
    assert prune, 'saved cleanup function missing'
    script = ('LISTS_STATE="' + str(saved_dir) + '"\n' +
              'valid_group() { return 0; }; grep() { return 2; }; die() { exit 19; }\n' +
              prune.group(0) + 'smartdns_prune_saved\n')
    read_error = subprocess.run(['sh','-c',script],capture_output=True,text=True)
    if read_error.returncode != 19 or saved.read_text() != saved_original:
        fail('snapshot read error was ignored')
    # Both stores together, with real AGH control and a fake HTTP transport.
    fixture = ast.parse((ROOT / "tests/repository/check-ads-agh-smartdns.py").read_text())
    fake_curl = next(ast.literal_eval(n.value) for n in fixture.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "FAKE_CURL" for t in n.targets))
    state = tmp / "agh.json"
    curl = tmp / "curl"
    fake_curl = fake_curl.replace('Path(out).write_text(json.dumps(res))',
        'if method == "POST" and st.get("fail_after_apply") and st.get("posts") == 1: sys.exit(22)\nPath(out).write_text(json.dumps(res))')
    curl.write_text(fake_curl.replace("@STATE@", str(state))); curl.chmod(0o755)
    auth = tmp / "agh.auth"; auth.write_text("admin:pw\n"); auth.chmod(0o600)
    yaml = tmp / "agh.yaml"
    yaml.write_text("dns:\n  upstream_dns:\n    - '[/claude.ai/]" + own + "'\n")
    env.update({"VWARD_ADGUARD_CONFIG": str(yaml), "VWARD_ADS_CONTROL_BIN": str(ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh"),
                "VWARD_ADS_LIB": str(ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"),
                "VWARD_ADS_ETC": str(tmp / "ads"), "VWARD_ADS_STATE": str(tmp / "ads-state"),
                "VWARD_ADS_LOG_DIR": str(tmp / "ads-log"), "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(curl),
                "VWARD_ADS_AGH_AUTH_FILE": str(auth), "VWARD_ADS_CONTROL_LOCK": str(tmp / "ads.lock"),
                "AGH_API_BASE": "http://192.0.2.1:3001/control", "TMPDIR": str(tmp)})
    upstreams = ["[/claude.ai/]" + own, "[/claude.ai/]" + other, "9.9.9.9"]
    for flag in (None, "refuse", "save-fail", "agh-refuse", "agh-partial"):
        reset()
        state.write_text(json.dumps({"up": upstreams, "ignore_posts": flag == "agh-refuse", "fail_after_apply": flag == "agh-partial"}))
        if flag in ("refuse", "save-fail"): (tmp / flag).touch()
        r = run("smartdns-server", "clear")
        if flag in ("refuse", "save-fail"): (tmp / flag).unlink()
        got = json.loads(state.read_text())["up"]
        if flag:
            if not r.returncode or set(got) != set(upstreams) or conf.read_text() != original or own not in cfg.read_text():
                fail("two-store rollback " + flag + ": " + r.stdout + str(got))
        elif r.returncode or got != upstreams[1:] or own in cfg.read_text():
            fail("two-store clear: " + r.stdout + str(got))
    # A failing AGH removal must never be reported as unchanged/successful.
    reset()
    state.write_text(json.dumps({"up": upstreams, "ignore_posts": True}))
    r = run("smartdns-domain", "remove", "claude.ai")
    if not r.returncode or "result=" in r.stdout or own not in cfg.read_text():
        fail("AGH failure was hidden: " + r.stdout)
print("SMARTDNS_CLEAR=PASS")
