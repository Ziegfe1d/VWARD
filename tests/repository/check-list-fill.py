#!/usr/bin/env python3
"""Keenetic domain lists grow from the domain catalog, and only what VWARD added goes.

A stand-in for ndmc keeps the running-config in a file and applies include
changes; a stand-in resolver answers for every domain but the "dead" ones.
"""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILL = ROOT / "components/route-tools/scripts/vward-list-fill.sh"

FAKE_NDMC = r"""#!/bin/sh
CFG="@CFG@"
[ "$1" = -c ] || exit 2
cmd=$2
echo "$cmd" >> "$CFG.log"
case "$cmd" in
  "show running-config") cat "$CFG"; exit 0 ;;
  "system configuration save") echo saved; exit 0 ;;
esac
set -- $cmd
if [ "$1" = no ]; then shift; mode=del; else mode=add; fi
[ "$1 $2" = "object-group fqdn" ] || { echo "error: unknown command"; exit 1; }
g=$3 k=$4 d=$5
awk -v g="$g" -v k="$k" -v d="$d" -v m="$mode" '
  /^object-group fqdn / {if (cur==g && m=="add" && !done) {print "    " k " " d; done=1} cur=$3; print; next}
  /^!/ {if (cur==g && m=="add" && !done) {print "    " k " " d; done=1} cur=""; print; next}
  cur==g && $1==k && $2==d && m=="del" {next}
  {print}' "$CFG" > "$CFG.new" && mv "$CFG.new" "$CFG"
echo ok
"""

FAKE_RESOLVE = r"""#!/bin/sh
grep -qxF "$1" "@DEAD@" && exit 1
exit 0
"""

RUNNING = """object-group fqdn domain-list0
    description "Telegram"
    include telegram.org
!
object-group fqdn domain-list1
    description "YouTube"
    include youtube.com
    include ytimg.com
    exclude yt-extra.example
!
object-group fqdn domain-list5
    description "Разное"
    include mine.example
!
object-group fqdn domain-list7
    description "Steam"
!
object-group fqdn AdaptiveAuto
    include other.example
!
"""

CATALOG = [
    "youtube.com|v2fly|youtube", "www.youtube.com|v2fly|youtube", "ytimg.com|v2fly|youtube", "googlevideo.com|v2fly|youtube",
    "youtu.be|v2fly|youtube", "ggpht.com|v2fly|youtube", "dead-yt.example|v2fly|youtube", "youtube.com|itdog|youtube",
    "googlevideo.com|itdog|youtube", "yt-extra.example|v2fly|youtube-extra", "extra-yt.example|v2fly|youtube-extra",
    "telegram.org|v2fly|telegram", "t.me|v2fly|telegram", "telegram.me|v2fly|telegram", "tdesktop.com|itdog|telegram",
    "steampowered.com|v2fly|steam", "steamcommunity.com|v2fly|steam",
] + [f"site{i}.ru|itdog|russia-inside" for i in range(2000)] + ["youtube.com|itdog|russia-inside", "ytimg.com|itdog|russia-inside"]


def fail(msg):
    raise SystemExit(f"LIST_FILL=FAIL: {msg}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    etc = tmp / "etc"; etc.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    dead = tmp / "dead"; dead.write_text("dead-yt.example\n")
    resolve = tmp / "resolve"; resolve.write_text(FAKE_RESOLVE.replace("@DEAD@", str(dead))); resolve.chmod(0o755)
    (etc / "hints-catalog.tsv").write_text("\n".join(CATALOG) + "\n")
    (etc / "hints-includes.tsv").write_text("v2fly|youtube|youtube-extra\n")
    (tmp / "root/tmp").mkdir(parents=True)
    refresh = tmp / "groups-refresh"
    env = os.environ | {
        "VWARD_ROUTE_ETC": str(etc), "VWARD_LIST_FILL_STATE": str(tmp / "state"), "VWARD_LIST_FILL_LOG": str(tmp / "fill.log"),
        "VWARD_NDMC": str(ndmc), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"), "VWARD_LIST_FILL_LOCK": str(tmp / "fill.lock"), "VWARD_ROUTE_REFRESH_TS": str(refresh),
        "VWARD_LIST_FILL_RESOLVE": str(resolve), "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_COMPONENT_STATE": str(tmp / "components"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    shells = [["sh"]] + ([["busybox", "sh"]] if __import__("shutil").which("busybox") else [])

    def run(*args, shell=("sh",), extra=None):
        r = subprocess.run([*shell, str(FILL), *args], env=env | (extra or {}), text=True, capture_output=True, timeout=120)
        return r.returncode, (r.stdout.strip().splitlines() or [""])[-1], r

    def group(name, kind="include"):
        cur, out = None, []
        for line in cfg.read_text().splitlines():
            if line.startswith("object-group fqdn "):
                cur = line.split()[2]
            elif line.startswith("!"):
                cur = None
            elif cur == name and line.split()[:1] == [kind]:
                out.append(line.split()[1])
        return out

    def status(g):
        return dict(l.split("=", 1) for l in run("status", g)[1:][1].stdout.strip().splitlines())

    for shell in shells:
        tag = shell[0]
        cfg.write_text(RUNNING); (tmp / "running.cfg.log").write_text("")
        for p in (tmp / "state").glob("*"):
            p.unlink()
        (etc / "list-fill.conf").unlink(missing_ok=True)
        dead.write_text("dead-yt.example\n")

        rc, out, r = run("run", shell=shell)
        if (rc, out) != (0, "result=changed"):
            fail(f"{tag} first run: {rc} {out} {r.stderr[-500:]}")
        # YouTube by its content; the country-size category is not a service.
        if group("domain-list1") != ["youtube.com", "ytimg.com", "extra-yt.example", "ggpht.com", "googlevideo.com", "youtu.be"]:
            fail(f"{tag} YouTube list: {group('domain-list1')}")
        # Telegram and Steam by name; a list of its own with no category stays as it is.
        if group("domain-list0") != ["telegram.org", "t.me", "tdesktop.com", "telegram.me"] or group("domain-list7") != ["steamcommunity.com", "steampowered.com"]:
            fail(f"{tag} by name: {group('domain-list0')} {group('domain-list7')}")
        if group("domain-list5") != ["mine.example"] or group("AdaptiveAuto") != ["other.example"]:
            fail(f"{tag} untouched lists changed")
        log = (tmp / "running.cfg.log").read_text()
        if log.count("system configuration save") != 1 or refresh.read_text().strip() != "0":
            fail(f"{tag} one save for the night and the route engine told: {log}")
        st = status("domain-list1")
        if (st["mode"], st["categories"], st["added"], st["vward"], st["undo"]) != ("auto", "youtube", "4", "4", "1"):
            fail(f"{tag} status: {st}")

        # Nothing new: no change, no save.
        rc, out, _ = run("run", shell=shell)
        if out != "result=unchanged" or (tmp / "running.cfg.log").read_text().count("system configuration save") != 1:
            fail(f"{tag} second run: {out}")

        # The owner takes ggpht.com out; the catalog drops youtu.be and youtube.com.
        subprocess.run([str(ndmc), "-c", "no object-group fqdn domain-list1 include ggpht.com"], check=True, capture_output=True)
        cat = [l for l in CATALOG if not l.startswith(("youtu.be|", "youtube.com|v2fly", "youtube.com|itdog|youtube"))]
        (etc / "hints-catalog.tsv").write_text("\n".join(cat) + "\n")
        run("run", "domain-list1", shell=shell)
        g1 = group("domain-list1")
        if "ggpht.com" in g1 or "youtu.be" in g1 or "youtube.com" not in g1:
            fail(f"{tag} declined, dropped from catalog, the owner's own entry: {g1}")
        (etc / "hints-catalog.tsv").write_text("\n".join(CATALOG) + "\n")

        # A domain VWARD added stops answering: it goes on the third night only.
        dead.write_text("dead-yt.example\ngooglevideo.com\n")
        for night in (1, 2):
            run("run", "domain-list1", shell=shell)
            if "googlevideo.com" not in group("domain-list1"):
                fail(f"{tag} removed after {night} silent night(s)")
        run("run", "domain-list1", shell=shell)
        if "googlevideo.com" in group("domain-list1"):
            fail(f"{tag} silent three nights must go")
        dead.write_text("dead-yt.example\n")

        # Undo the last run: the domain comes back.
        rc, out, _ = run("undo", "domain-list1", shell=shell)
        if out != "result=changed" or "googlevideo.com" not in group("domain-list1") or status("domain-list1")["undo"] != "0":
            fail(f"{tag} undo: {out} {group('domain-list1')}")

        # Switched off: the list is left alone.  Categories by hand.
        if run("set", "domain-list7", "off", shell=shell)[1] != "result=changed":
            fail(f"{tag} set off")
        subprocess.run([str(ndmc), "-c", "no object-group fqdn domain-list7 include steampowered.com"], check=True, capture_output=True)
        run("run", "domain-list7", shell=shell)
        if group("domain-list7") != ["steamcommunity.com"]:
            fail(f"{tag} an off list must not change: {group('domain-list7')}")
        run("set", "domain-list5", "telegram", shell=shell)
        run("run", "domain-list5", shell=shell)
        if "t.me" not in group("domain-list5") or "mine.example" not in group("domain-list5"):
            fail(f"{tag} categories by hand: {group('domain-list5')}")

        # The limit: what does not fit waits.
        cfg.write_text(cfg.read_text() + "object-group fqdn domain-list9\n    description \"Telegram\"\n    include a.example\n!\n")
        run("run", "domain-list9", shell=shell, extra={"VWARD_LIST_FILL_MAX": "3"})
        st = status("domain-list9")
        if group("domain-list9") != ["a.example", "t.me", "tdesktop.com"] or st["full"] != "1" or st["pending"] != "2":
            fail(f"{tag} limit: {group('domain-list9')} {st}")

        # Bad input never reaches the router.
        calls = (tmp / "running.cfg.log").read_text()
        for args, want in ((("set", "AdaptiveAuto", "off"), "error=invalid_group"), (("set", "domain-list1", "a b"), "error=invalid_value"),
                           (("run", "domain-list1;x"), "error=invalid_group"), (("undo", "x"), "error=invalid_group")):
            if run(*args, shell=shell)[1] != want:
                fail(f"{tag} {args}: {run(*args, shell=shell)[1]}")
        if (tmp / "running.cfg.log").read_text() != calls:
            fail(f"{tag} bad input reached the router")
        # Another run in progress: this one leaves; a lock left by a dead run is taken over.
        (tmp / "fill.lock").mkdir(); (tmp / "fill.lock/pid").write_text(str(os.getpid()))
        if run("run", "domain-list1", shell=shell)[:2] != (75, "error=list_fill_busy"):
            fail(f"{tag} busy: {run('run', 'domain-list1', shell=shell)[:2]}")
        (tmp / "fill.lock/pid").write_text("999999")
        if run("run", "domain-list1", shell=shell)[0] != 0 or (tmp / "fill.lock").exists():
            fail(f"{tag} stale lock")
        if not (tmp / "fill.log").read_text().count("LIST_ADD|domain-list1|googlevideo.com"):
            fail(f"{tag} journal")

    # From the Console: the config helper hands the job to vward-list-fill.sh.
    helper = ROOT / "components/console/scripts/vward-console-config.sh"
    cenv = env | {"VWARD_LIST_FILL_BIN": str(FILL), "VWARD_CONSOLE_ETC": str(tmp / "cetc"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
                  "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup")}
    def helper_run(*args):
        r = subprocess.run(["sh", str(helper), *args], env=cenv, text=True, capture_output=True, timeout=120)
        return r.returncode, (r.stdout.strip().splitlines() or [""])[-1]
    if helper_run("list-fill", "set", "domain-list1", "youtube:telegram") != (0, "result=changed"):
        fail(f"console set: {helper_run('list-fill', 'set', 'domain-list1', 'youtube:telegram')}")
    if "domain-list1=youtube,telegram" not in (etc / "list-fill.conf").read_text():
        fail("categories from the Console")
    for args, want in ((("list-fill", "run", "AdaptiveAuto"), (64, "error=invalid_group")), (("list-fill", "drop", "domain-list1"), (64, "error=invalid_operation")),
                       (("list-fill", "run", "domain-list1", "x"), (64, "error=usage"))):
        if helper_run(*args) != want:
            fail(f"console {args}: {helper_run(*args)}")
    if helper_run("list-fill", "run", "domain-list1")[0] != 0:
        fail("console run")

print("LIST_FILL=PASS")
