#!/usr/bin/env python3
"""fix.35.3: an expired Smart DNS server is taken out although its own address is already gone.

Owner, 02.11.2026: the subscription of the old Smart DNS server ended. AdGuard Home held 39 upstream
lines: 4 general Quad9 addresses and 35 domain rows [/domain/]<old DoH server>; the own address
(SMARTDNS_URL) had been cleared earlier, and «smartdns-server clear» stopped at the empty address
(«unchanged») before smartdns_take_rows/smartdns_prune_saved - the rows stayed and the Panel showed
no button. Now the owner picks the server (by host) or pastes its exact address; only its domain rows
go from both stores and from the saved list states, the general upstreams, other servers and foreign
rows stay. The old server is dead in this test: no answer from it is needed. No router or network.
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
OLD = "https://old-smartdns.example:8443/dns-query/expired-secret"
OTHER = "https://other.example/dns-query"
NEW = "https://new-smartdns.example/dns-query/new-secret"
QUAD9 = ["9.9.9.10", "149.112.112.10", "2620:fe::10", "2620:fe::fe:10"]
DOMAINS = ["aistudio.google.com", "chatgpt.com", "gpt3-openai.com", "oaistatic.com", "claude.ai", "claude.app", "claude.com",
           "claude.new", "githubcopilot.com", "copilot-proxy.githubusercontent.com", "copilot-telemetry.githubusercontent.com",
           "copilot.microsoft.com", "cursor.com", "cursor-cdn.com", "cursor.sh", "cursorapi.com", "deepl.com", "deepseek.com",
           "elevenlabs.io", "grammarly.com", "grammarly.io", "grok.com", "x.ai", "kilo.ai", "meta.ai", "meta.com",
           "meta-ohttp-config-prod.fastly-edge.com", "notebooklm.google", "notebooklm.google.com", "notebook.google",
           "perplexity.ai", "perplexity.com", "perplexity-ai.cloudflareaccess.com", "browser-intake-datadoghq.com", "pollo.ai"]
FOREIGN = "[/user-added.example/]" + OTHER
SECRETS = ("expired-secret", "new-secret", "second-secret")


def fail(msg):
    raise SystemExit("SMARTDNS_ORPHAN_CLEAR=FAIL: " + msg)


assert len(DOMAINS) == 35 and len(set(DOMAINS)) == 35

FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(0)
lines = cfg.read_text().splitlines()
ctx = cmd.startswith("dns-proxy ")
body = cmd[len("dns-proxy "):] if ctx else cmd
neg = body.startswith("no ")
if neg: body = body[3:]
out, inblock = [], False
for l in lines:
    if l == "dns-proxy": inblock = True
    elif l == "!": inblock = False
    if neg and ctx and inblock and l.strip().startswith(body):
        continue
    out.append(l)
if not neg and ctx:
    i = out.index("dns-proxy"); j = out.index("!", i); out.insert(j, "    " + body)
cfg.write_text("\n".join(out) + "\n")
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cfg = tmp / "running.cfg"
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=Mine\n"); devconf.chmod(0o600)
    (tmp / "policy").mkdir(); (tmp / "root/tmp").mkdir(parents=True); (tmp / "etc").mkdir()
    adm = tmp / "admission.sh"; adm.write_text("vward_admission_enter() { return 0; }\nvward_admission_leave() { return 0; }\n")
    # The old server is dead (seeded answer «does not answer»): clear must not depend on it.
    alive = tmp / "alive"; alive.mkdir()
    k = subprocess.run(["sh", "-c", 'printf %s "$U" | cksum | cut -d" " -f1'], env={"U": OLD, "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True).stdout.strip()
    (alive / k).write_text("1\n")
    # AdGuard Home: the production control script over a fake HTTP transport.
    fixture = ast.parse((ROOT / "tests/repository/check-ads-agh-smartdns.py").read_text())
    fake_curl = next(ast.literal_eval(n.value) for n in fixture.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "FAKE_CURL" for t in n.targets))
    state = tmp / "agh.json"
    curl = tmp / "curl"; curl.write_text(fake_curl.replace("@STATE@", str(state))); curl.chmod(0o755)
    auth = tmp / "agh.auth"; auth.write_text("admin:pw\n"); auth.chmod(0o600)
    lib = (ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh").read_text()
    patched = tmp / "ads-lib.sh"
    patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    yaml = tmp / "agh.yaml"
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"), "VWARD_ADMISSION_LIB": str(adm),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_POLICY_STATE": str(tmp / "policy"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_POLICY_SYNC_BIN": str(tmp / "no-sync"),
        "VWARD_DOH_RETRY_DELAY": "0", "VWARD_SNAPSHOT_RETRY": "0", "VWARD_DOH_ALIVE": "1", "VWARD_DOH_ALIVE_DIR": str(alive),
        "VWARD_ADGUARD_CONFIG": str(yaml), "VWARD_ADS_CONTROL_BIN": str(ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh"),
        "VWARD_ADS_LIB": str(patched), "VWARD_ADS_ETC": str(tmp / "ads"), "VWARD_ADS_STATE": str(tmp / "ads-state"),
        "VWARD_ADS_LOG_DIR": str(tmp / "ads-log"), "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(curl),
        "VWARD_ADS_AGH_AUTH_FILE": str(auth), "VWARD_ADS_CONTROL_LOCK": str(tmp / "ads.lock"),
        "AGH_API_BASE": "http://192.0.2.1:3001/control", "TMPDIR": str(tmp),
    }
    conf = tmp / "etc/smartdns.conf"
    saved_dir = tmp / "etc/route-engine/domain-lists"; saved_dir.mkdir(parents=True)
    saved = saved_dir / "domain-list4"
    saved_start = ("route=ISP\tauto\ndoh=https upstream " + OLD + " dnsm on ISP domain chatgpt.com\nagh=chatgpt.com\t" + OLD + "\n"
                   "doh=https upstream " + OTHER + " domain other.example\nagh=other.example\t" + OTHER + "\n")
    keen = ["https upstream " + OLD + " dnsm on ISP domain claude.ai", "https upstream " + OLD + " dnsm on ISP domain chatgpt.com",
            "https upstream " + OTHER + " domain other.example"]
    agh_start = QUAD9 + ["[/" + d + "/]" + OLD for d in DOMAINS] + [FOREIGN]

    def sync_yaml():
        # AdGuard Home keeps its configuration file in step with the API (the fake writes JSON only).
        up = json.loads(state.read_text())["up"]
        yaml.write_text("dns:\n  upstream_dns:\n" + "".join("    - '" + u + "'\n" for u in up))

    def reset(own_conf="SMARTDNS_STORE=auto\n", agh=None, extra=None):
        conf.write_text(own_conf)
        state.write_text(json.dumps({"up": list(agh or agh_start)}))
        sync_yaml()
        cfg.write_text(RUNNING.replace("    route", "    " + "\n    ".join(keen + (extra or [])) + "\n    route"))
        saved.write_text(saved_start); saved.chmod(0o600)
        for d in (tmp / "backup-recovery").glob("smartdns.*"):
            shutil.rmtree(d)

    def doh():
        return {l.strip() for l in cfg.read_text().splitlines() if l.strip().startswith("https upstream")}

    def agh():
        return json.loads(state.read_text())["up"]

    def run(*args, stdin=""):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, input=stdin, timeout=120)
        for s in SECRETS:
            if s in r.stdout or s in r.stderr:
                fail(f"{args}: a server token was printed")
        return r

    def last(r):
        lines = r.stdout.strip().splitlines()
        return lines[-1] if lines else ""

    # 1. The own address is gone, the rows of the expired server stay: the own-server button alone
    #    changes nothing (another server is never taken unasked).
    reset()
    before_cfg, before_agh = cfg.read_text(), agh()
    r = run("smartdns-server", "clear")
    if last(r) != "result=unchanged" or cfg.read_text() != before_cfg or agh() != before_agh:
        fail("clear without a choice must not take another server: " + r.stdout)
    # 2. RED before fix.35.3: the owner chooses the old server by host - all its rows go from both
    #    stores and from the saved list state; the 4 Quad9 lines, the other server and a foreign row stay.
    r = run("smartdns-server", "clear", stdin="host:OLD-SMARTDNS.example\n")
    if r.returncode or last(r) != "result=changed":
        fail("RED: the expired server chosen by host must be cleared: " + r.stdout + r.stderr[-300:])
    if "cleared=keenetic:2,agh:35,saved:1" not in r.stdout:
        fail("the Panel report must count what was cleared (2 Keenetic lines, 35 rows, 1 saved state): " + r.stdout)
    got = agh()
    if got != QUAD9 + [FOREIGN]:
        fail(f"AdGuard Home must keep the 4 Quad9 lines and the foreign row only: before 39+1, after {len(got)}: {got}")
    if doh() != {keen[2]}:
        fail("Keenetic must keep the other server's line only: " + str(doh()))
    sv = saved.read_text()
    if OLD in sv or OTHER not in sv or not sv.startswith("route=ISP\tauto\n"):
        fail("the saved list state must lose the old server only: " + sv)
    if conf.read_text() != "SMARTDNS_STORE=auto\n":
        fail("the store preference must stay: " + conf.read_text())
    if list((tmp / "backup-recovery").glob("smartdns.*")):
        fail("a confirmed clear must not leave recovery data")
    audit = (tmp / "audit.log").read_text()
    if any(s in audit for s in SECRETS):
        fail("a server token leaked into the audit log")
    # 3. Repeat (AdGuard Home has saved its file): idempotent, nothing else touched.
    sync_yaml()
    before_cfg, before_agh, before_sv = cfg.read_text(), agh(), saved.read_text()
    r = run("smartdns-server", "clear", stdin="host:old-smartdns.example\n")
    if last(r) != "result=unchanged" or cfg.read_text() != before_cfg or agh() != before_agh or saved.read_text() != before_sv:
        fail("a repeated clear must be unchanged: " + r.stdout)
    # 4. The next reconcile: the list goes back to the provider from its saved state - the old
    #    server does not come back, the other server's line does (it was in the saved state).
    cfg.write_text("object-group fqdn domain-list4\n    include chatgpt.com\n    include other.example\n!\n" +
                   cfg.read_text().replace("    route object-group Mine", "    route object-group domain-list4 Wireguard0 auto\n    route object-group Mine"))
    env_live = dict(env); env_live["VWARD_DOH_ALIVE"] = "0"
    r = subprocess.run(["sh", str(HELPER), "domain-list", "domain-list4", "bypass"], env=env_live, text=True, capture_output=True, timeout=120)
    if r.returncode or "result=changed" not in r.stdout:
        fail("bypass after the clear failed: " + r.stdout + r.stderr[-300:])
    sync_yaml()
    if any(OLD in l for l in doh()) or any(OLD in u for u in agh()):
        fail("RED: the expired server came back with the saved list state: " + str(doh()) + str(agh()))
    if agh()[:4] != QUAD9:
        fail("the general upstreams changed on the reconcile: " + str(agh()))
    # 5. Two addresses on one host (two tokens): no guess - an error and nothing changed; the exact
    #    address pasted by the owner takes only its own rows.
    second = OLD.replace("expired-secret", "second-secret")
    reset(agh=agh_start + ["[/pollo2.example/]" + second])
    before_cfg, before_agh = cfg.read_text(), agh()
    r = run("smartdns-server", "clear", stdin="host:old-smartdns.example\n")
    if last(r) != "error=smartdns_server_ambiguous" or cfg.read_text() != before_cfg or agh() != before_agh:
        fail("several addresses on one host must not be guessed: " + r.stdout)
    r = run("smartdns-server", "clear", stdin=OLD + "\n")
    if r.returncode or last(r) != "result=changed" or agh() != QUAD9 + [FOREIGN, "[/pollo2.example/]" + second] or doh() != {keen[2]}:
        fail("the pasted exact address must take only its own rows: " + r.stdout + str(agh()))
    # 6. A new own server is already set: clearing the old host keeps the new own address.
    reset(own_conf="SMARTDNS_URL=" + NEW + "\nSMARTDNS_STORE=auto\n")
    r = run("smartdns-server", "clear", stdin="host:old-smartdns.example\n")
    if r.returncode or last(r) != "result=changed" or conf.read_text() != "SMARTDNS_URL=" + NEW + "\nSMARTDNS_STORE=auto\n":
        fail("the new own server must stay when the old one is cleared: " + r.stdout + conf.read_text())
    if agh() != QUAD9 + [FOREIGN]:
        fail("old rows left with a new own server: " + str(agh()))
    # 7. The own address of the same host (another token) is the owner's: clearing that host takes it too.
    reset(own_conf="SMARTDNS_URL=" + OLD.replace("expired-secret", "older") + "\nSMARTDNS_STORE=auto\n")
    r = run("smartdns-server", "clear", stdin="host:old-smartdns.example\n")
    if r.returncode or last(r) != "result=changed" or conf.read_text() != "SMARTDNS_STORE=auto\n" or agh() != QUAD9 + [FOREIGN]:
        fail("the own address of the cleared host must go with it: " + r.stdout + conf.read_text())
    # 8. The local AdGuard Home API does not apply the change: an honest error, Keenetic back as it
    #    was, no «result=», the expired rows still listed (nothing reported as cleared).
    reset()
    st = json.loads(state.read_text()); st["ignore_posts"] = True; state.write_text(json.dumps(st))
    before_doh = doh()
    r = run("smartdns-server", "clear", stdin="host:old-smartdns.example\n")
    if not r.returncode or "result=" in r.stdout or "cleared=" in r.stdout or doh() != before_doh or agh() != agh_start:
        fail("an AdGuard Home refusal must be an error with everything kept: " + r.stdout)
    for d in (tmp / "backup-recovery").glob("smartdns.*"):
        shutil.rmtree(d)
    # 9. A malformed selector is refused before anything is read or written.
    reset()
    for bad in ("host:", "host:bad host", "host:-x.example", "http://old-smartdns.example/q", "old-smartdns.example"):
        r = run("smartdns-server", "clear", stdin=bad + "\n")
        if last(r) != "error=invalid_value" or agh() != agh_start:
            fail(f"selector {bad!r} must be refused: " + r.stdout)
    # 10. The API passes the host to the helper on stdin and the Panel lists every server in use.
    api = (ROOT / "web/cgi-bin/api.cgi").read_text()
    for need in ('form_only op url store host', 'SSURL="host:$SSHOST"', 'server_rows:', 'alive_host: $alive_host'):
        if need not in api:
            fail("api.cgi: missing " + need)
    js = (ROOT / "web/assets/vward-console.js").read_text()
    for need in ("function sdServers(a, sd)", "'sd-drop': c => smartdnsServer('clear', '', c.id.slice(8))", "Выполнено не полностью"):
        if need not in js:
            fail("Panel: missing " + need)
print("SMARTDNS_ORPHAN_CLEAR=PASS")
