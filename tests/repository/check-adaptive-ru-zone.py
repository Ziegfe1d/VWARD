#!/usr/bin/env python3
"""Russian zones never go through the VPN, also when they are already in AdaptiveAuto (01.11.2026).

Viva 1.11: AdaptiveAuto (route ... OpkgTun4) held api.ozon.ru, user-features.wb.ru,
personal-clusters.wildberries.ru, fda.middle-api.magnit.ru ... - kept in the saved list from versions
before ru_zone, put back at every engine start, never taken out (the reconciler needs a direct check
that passes). Now:
- the restore leaves Russian zones out, so they leave the group; the saved list is copied once
  (backup) and the names are kept in adaptive-ru-removed.txt; other names are untouched;
- VWARD_ADAPTIVE_RU=1 with the backup put back restores them (the undo path);
- every add path checks ru_zone (add_adaptive, hints, discovery) with one and the same list.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
DISC = (ROOT / "components/route-tools/scripts/vward-route-discovery.sh").read_text()


def fail(msg):
    raise SystemExit(f"ADAPTIVE_RU_ZONE=FAIL: {msg}")


def func(src, name):
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", src, re.S | re.M)
    if not m:
        fail(f"missing {name}")
    return m.group(0)


if func(ENGINE, "ru_zone") != func(DISC, "ru_zone"):
    fail("discovery must use the route engine's ru_zone list as it is")
for src, name, need in ((ENGINE, "add_adaptive", "ru_zone \"$H\""), (ENGINE, "add_hint_adaptive", "ru_zone \"$H\""),
                        (ENGINE, "restore_adaptive_from_persist", "ru_zone \"$H\"")):
    if need not in func(src, name):
        fail(f"{name} must check ru_zone")
if 'if ru_zone "$HOST"; then' not in DISC:
    fail("discovery must skip Russian zones before adding")

RU = ["api.ozon.ru", "ir-20.ozone.ru", "user-features.wb.ru", "user-vector-info.wb.ru", "rec-ftl.wb.ru",
      "personal-clusters.wildberries.ru", "cart-storage-api.wildberries.ru", "adserver.gear-hub.ru",
      "fda.middle-api.magnit.ru", "drm-prod-statist-diag-yc.mirdomovyat.ru"]
OTHER = ["chatgpt.com", "claude.ai", "rutracker.org"]
CFG = "dns-proxy\n    route object-group AdaptiveAuto OpkgTun4 auto\n!\nobject-group fqdn AdaptiveAuto\n{inc}!\n"
code = func(ENGINE, "shared_config") + func(ENGINE, "valid_fqdn") + func(ENGINE, "restore_time_up") + \
    func(ENGINE, "ru_zone") + func(ENGINE, "state_path") + func(ENGINE, "ru_clean_files") + func(ENGINE, "restore_adaptive_from_persist")
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "bin").mkdir()
        (t / "bin/ndmc").write_text('#!/bin/sh\necho "$2" >> "$T/ndmc.log"\nexit 0\n')
        (t / "bin/ndmc").chmod(0o755)
        script = t / "run.sh"
        script.write_text(f"""T="{t}"; PERSIST="$T/persist"; EVENT_LOG="$T/events"; GROUP=AdaptiveAuto; REFRESH_TS="$T/ts"
ADAPTIVE_FULL="$T/full"; RU_BACKUP="$T/persist.ru-backup"; RU_REMOVED="$T/ru-removed"; VWARD_ENGINE_SHARED_CONFIG=1
ADAPTIVE="$T/adaptive"; STATE_DIR="$T/st"; VOLATILE_DIR="$T/vol"
change_lock() {{ :; }}; change_unlock() {{ :; }}
vward_running_config() {{ cat "$T/rc"; }}; vward_keenetic_config() {{ cat "$T/rc"; }}
{code}
restore_adaptive_from_persist
""")

        (t / "st").mkdir(exist_ok=True); (t / "vol").mkdir(exist_ok=True)

        def run(group, persist, ru=None):
            (t / "rc").write_text(CFG.format(inc="".join(f"    include {h}\n" for h in group)))
            (t / "persist").write_text("".join(f"{h}\n" for h in persist))
            (t / "ndmc.log").unlink(missing_ok=True)
            env = {"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t)}
            if ru:
                env["VWARD_ADAPTIVE_RU"] = ru
            r = subprocess.run([*shell, str(script)], env=env, capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or r.stderr:
                fail(f"{shell}: rc={r.returncode} {r.stderr[-300:]}")
            return (t / "ndmc.log").read_text().splitlines() if (t / "ndmc.log").exists() else []

        # 1. In the group and in the saved list (the router's state): the restore takes them out.
        (t / "adaptive").write_text("".join(h + "\n" for h in RU + OTHER))
        for h in RU + OTHER:
            (t / "st" / f"{h}.state").write_text("STATUS=AUTO_VPN\n")
        calls = run(RU + OTHER, RU + OTHER)
        gone = {c.split()[-1] for c in calls if c.startswith("no object-group fqdn AdaptiveAuto include ")}
        if gone != set(RU) or any(not c.startswith("no ") for c in calls):
            fail(f"RED: Russian zones must leave AdaptiveAuto, nothing else changes: {calls}")
        if (t / "persist.ru-backup").read_text().split() != RU + OTHER:
            fail("the saved list must be copied before the first removal")
        if sorted((t / "ru-removed").read_text().split()) != sorted(RU):
            fail("the names taken out must be kept")
        if "ADAPTIVE_RU_OUT|n=10|" not in (t / "events").read_text():
            fail("the removal must be in the event log")
        # Owner 02.11: the saved list, the cache and the states are cleaned too (nothing to come back).
        if (t / "persist").read_text().split() != OTHER or (t / "adaptive").read_text().split() != OTHER:
            fail(f"RED: Russian zones must leave adaptive-persist.txt and adaptive-domains.txt: {(t / 'persist').read_text().split()}")
        if any((t / "st" / f"{h}.state").exists() for h in RU) or not all((t / "st" / f"{h}.state").exists() for h in OTHER):
            fail("their .state files go, the others stay")
        # 2. Next start: nothing more to do, the record is not doubled, the backup is not overwritten.
        (t / "persist").write_text("".join(f"{h}\n" for h in OTHER))
        if run(OTHER, OTHER + RU[:1]):
            fail("a Russian name left in the saved list must not be put back")
        if len((t / "ru-removed").read_text().split()) != len(RU) or len((t / "persist.ru-backup").read_text().split()) != len(RU) + len(OTHER):
            fail("the record and the backup must not change on a later start")
        # 2b. The owner removed them by hand in Keenetic, the saved list still has them (02.11 00:47):
        #     a restart does not bring them back, and cleans the saved list.
        (t / "persist").write_text("".join(f"{h}\n" for h in RU[:7] + OTHER))
        calls = run(OTHER, RU[:7] + OTHER)
        if any(c.startswith("object-group fqdn AdaptiveAuto include ") for c in calls) or (t / "persist").read_text().split() != OTHER:
            fail(f"RED: after a manual removal in Keenetic the saved names must not come back: {calls}")
        # 3. Undo: VWARD_ADAPTIVE_RU=1 and the backup as the saved list put them back.
        calls = run(OTHER, (t / "persist.ru-backup").read_text().split(), ru="1")
        back = {c.split()[-1] for c in calls if c.startswith("object-group fqdn AdaptiveAuto include ")}
        if back != set(RU):
            fail(f"the undo must restore exactly the removed names: {sorted(back)}")

# 01.11 item 6: a name in the group that Keenetic would not parse is not sent for removal (three
# «argument parse error» within the engine's restart, 17:12); a refused removal is journaled.
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "bin").mkdir()
    (t / "bin/ndmc").write_text('#!/bin/sh\necho "$2" >> "$T/ndmc.log"\ncase "$2" in *refused.example*) echo "Command::Base: argument parse error.";; esac\nexit 0\n')
    (t / "bin/ndmc").chmod(0o755)
    (t / "run.sh").write_text(f"""T="{t}"; PERSIST="$T/persist"; EVENT_LOG="$T/events"; GROUP=AdaptiveAuto; REFRESH_TS="$T/ts"
ADAPTIVE_FULL="$T/full"; RU_BACKUP="$T/b"; RU_REMOVED="$T/r"; VWARD_ENGINE_SHARED_CONFIG=1
change_lock() {{ :; }}; change_unlock() {{ :; }}
vward_running_config() {{ cat "$T/rc"; }}; vward_keenetic_config() {{ cat "$T/rc"; }}
{code}
restore_adaptive_from_persist
""")
    (t / "rc").write_text(CFG.format(inc="    include bad_name.example\n    include refused.example\n    include ok.example\n"))
    (t / "persist").write_text("ok.example\n")
    subprocess.run(["sh", str(t / "run.sh")], env={"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t)}, capture_output=True, text=True, timeout=60)
    calls = (t / "ndmc.log").read_text()
    ev = (t / "events").read_text()
    if "bad_name" in calls or "PERSIST_RESTORE_SKIP_INVALID|bad_name.example" not in ev:
        fail("RED: an invalid name must not be sent to Keenetic, and must be journaled")
    if "PERSIST_RESTORE_FAIL|no include refused.example|Command::Base: argument parse error." not in ev:
        fail("RED: a refused removal must be journaled with Keenetic's answer: " + ev)
print("ADAPTIVE_RU_ZONE=PASS")
