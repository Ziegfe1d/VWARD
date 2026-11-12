#!/usr/bin/env python3
"""The Panel's list operations go through the Go routing core when it is installed (owner
11.11.2026): list-domain add/remove, list clear/delete/merge and a list's move from one tunnel
to another call «vward-core list ...» and send nothing through ndmc themselves; the core's
answer becomes the Panel's (changed, unchanged, refused, blocked, failed). Without the core,
or with route-engine/core.panel.off, the shell writes as before. Exclusions stay with the shell.
The core's own correctness is tested in tools/vward-core (internal/listops, over HTTP RCI)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
sys.path.insert(0, str(Path(__file__).parent))
SRC = (Path(__file__).parent / "check-console-config.py").read_text()
FAKE_NDMC = SRC[SRC.index('FAKE_NDMC = r"""') + len('FAKE_NDMC = r"""'):SRC.index('"""', SRC.index('FAKE_NDMC = r"""') + 20)]
RUNNING = """interface Wireguard0
!
interface OpkgTun4
!
object-group fqdn domain-list1
    description "Youtube"
    include youtube.com
    exclude music.youtube.com
!
object-group fqdn domain-list2
    include ytimg.com
!
object-group fqdn MyVPN
    include old.example
!
object-group fqdn AdaptiveAuto
    include slow.example
!
dns-proxy
    route object-group domain-list1 Wireguard0 auto
    route object-group domain-list2 Wireguard0 auto
!
"""
FAKE_CORE = """#!/bin/sh
echo "$@" >> "@T@/core.calls"
r=$(cat "@T@/core.result" 2>/dev/null || echo changed)
echo "RESULT=$r"
[ "$r" = changed ] || [ "$r" = unchanged ] || { echo "WHY=fake $r"; exit 1; }
"""


def fail(m):
    raise SystemExit(f"CONSOLE_CORE_LISTS=FAIL: {m}")


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    etc = tmp / "etc"
    (etc / "route-engine").mkdir(parents=True)
    state = tmp / "state"
    state.mkdir()
    (tmp / "root/tmp").mkdir(parents=True)
    cfg = tmp / "running.cfg"
    cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"
    ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg)))
    ndmc.chmod(0o755)
    profile = tmp / "profile.sh"
    profile.write_text("vward_profile_load(){ VWARD_POLICY_GROUP=MyVPN; VWARD_TUNNEL_INTERFACE=Wireguard0; }\n"
                       "vward_valid_ndm_name(){ return 0; }\n"
                       "vward_device_map(){ :; }\nvward_map_tunnels(){ printf 'Wireguard0 nwg0\\nOpkgTun4 opkgtun4\\n'; }\n")
    core = tmp / "vward-core"
    core.write_text(FAKE_CORE.replace("@T@", str(tmp)))
    core.chmod(0o755)
    env = os.environ | {
        "VWARD_CONSOLE_ETC": str(etc), "VWARD_ROUTE_STATE": str(state),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"), "VWARD_NDMC": str(ndmc),
        "VWARD_CONSOLE_EDIT_LOCK": str(tmp / "edit.lock"), "VWARD_CONSOLE_SETTINGS_LOCK": str(tmp / "settings.lock"),
        "VWARD_AGENTS_CONF": str(tmp / "agents.conf"), "VWARD_PROFILE_LIB": str(profile),
        "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_CORE_BIN": str(core), "VWARD_CORE_JOURNAL": str(tmp / "journal"),
    }

    def run(*args):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, timeout=60)
        return r.returncode, (r.stdout + r.stderr).strip().splitlines()

    def writes():
        log = Path(str(cfg) + ".log")
        out = [l for l in log.read_text().splitlines() if l not in ("show running-config", "system configuration save")] if log.exists() else []
        log.unlink(missing_ok=True)
        return out

    def calls():
        p = tmp / "core.calls"
        out = []
        for l in (p.read_text().splitlines() if p.exists() else []):
            w = l.split()
            if w[1:2] == ["--journal"]:
                w = w[:1] + w[3:]
            out.append(" ".join(w))
        p.unlink(missing_ok=True)
        return out

    # Through the core: the right call, nothing written through ndmc, the core's answer.
    cases = [
        (("list-domain", "add", "domain-list1", "ytimg.com"), "list add domain-list1 ytimg.com"),
        (("list-domain", "remove", "domain-list1", "youtube.com"), "list remove domain-list1 youtube.com"),
        (("list", "clear", "domain-list2"), "list clear domain-list2"),
        (("list", "merge", "domain-list2", "domain-list1"), "list merge domain-list2 domain-list1"),
        (("list", "delete", "domain-list2"), "list delete domain-list2"),
        (("domain-list", "domain-list1", "OpkgTun4"), "list route domain-list1 OpkgTun4"),
        (("list-domain", "exclude", "domain-list1", "kids.youtube.com"), "list exclude domain-list1 kids.youtube.com"),
        (("list-domain", "unexclude", "domain-list1", "music.youtube.com"), "list unexclude domain-list1 music.youtube.com"),
        (("route-domain", "add", "mine.example.com"), "list add MyVPN mine.example.com"),
        (("route-domain", "remove", "old.example"), "list remove MyVPN old.example"),
        (("adaptive", "remove", "slow.example"), "list unadapt slow.example"),
        (("adaptive", "pin", "slow.example"), "list pin MyVPN slow.example"),
    ]
    for args, want in cases:
        rc, out = run(*args)
        got = calls()
        if rc != 0 or "result=changed" not in out or got != [want] or writes():
            fail(f"{args}: rc={rc} out={out} core={got}")
    (tmp / "core.result").write_text("unchanged")
    rc, out = run("list-domain", "add", "domain-list1", "new.example.com")
    if rc != 0 or "result=unchanged" not in out:
        fail(f"unchanged: {out}")
    calls()
    for res, err in (("refused", "error=core_refused"), ("blocked", "error=core_journal_blocked"),
                     ("failed", "error=router_rejected"), ("unknown", "error=verification_failed")):
        (tmp / "core.result").write_text(res)
        rc, out = run("list-domain", "add", "domain-list1", "x.example.com")
        if rc == 0 or err not in out or writes():
            fail(f"{res}: rc={rc} {out}")
        if "fake " + res not in (tmp / "audit.log").read_text():
            fail(f"{res}: the core's reason is not in the journal")
    calls()
    (tmp / "core.result").write_text("changed")
    # core.panel.off, or no core: the shell writes as before.
    (etc / "route-engine/core.panel.off").write_text("")
    rc, out = run("list-domain", "add", "domain-list1", "shell.example.com")
    if rc != 0 or calls() or writes() != ["object-group fqdn domain-list1 include shell.example.com"]:
        fail(f"core.panel.off: {out}")
    (etc / "route-engine/core.panel.off").unlink()
    env["VWARD_CORE_BIN"] = str(tmp / "missing")
    rc, out = run("list-domain", "add", "domain-list1", "shell2.example.com")
    if rc != 0 or writes() != ["object-group fqdn domain-list1 include shell2.example.com"]:
        fail(f"no core: {out}")
print("CONSOLE_CORE_LISTS=PASS")
