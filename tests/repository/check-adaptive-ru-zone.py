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

RU = ["api.ozon.ru", "user-features.wb.ru", "user-vector-info.wb.ru", "rec-ftl.wb.ru",
      "personal-clusters.wildberries.ru", "cart-storage-api.wildberries.ru", "adserver.gear-hub.ru",
      "fda.middle-api.magnit.ru", "drm-prod-statist-diag-yc.mirdomovyat.ru"]
OTHER = ["chatgpt.com", "claude.ai", "rutracker.org"]
CFG = "dns-proxy\n    route object-group AdaptiveAuto OpkgTun4 auto\n!\nobject-group fqdn AdaptiveAuto\n{inc}!\n"
code = func(ENGINE, "shared_config") + func(ENGINE, "valid_fqdn") + func(ENGINE, "restore_time_up") + \
    func(ENGINE, "ru_zone") + func(ENGINE, "restore_adaptive_from_persist")
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
change_lock() {{ :; }}; change_unlock() {{ :; }}
vward_running_config() {{ cat "$T/rc"; }}; vward_keenetic_config() {{ cat "$T/rc"; }}
{code}
restore_adaptive_from_persist
""")

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
        calls = run(RU + OTHER, RU + OTHER)
        gone = {c.split()[-1] for c in calls if c.startswith("no object-group fqdn AdaptiveAuto include ")}
        if gone != set(RU) or any(not c.startswith("no ") for c in calls):
            fail(f"RED: Russian zones must leave AdaptiveAuto, nothing else changes: {calls}")
        if (t / "persist.ru-backup").read_text().split() != RU + OTHER:
            fail("the saved list must be copied before the first removal")
        if sorted((t / "ru-removed").read_text().split()) != sorted(RU):
            fail("the names taken out must be kept")
        if "ADAPTIVE_RU_OUT|n=9|" not in (t / "events").read_text():
            fail("the removal must be in the event log")
        # 2. Next start: nothing more to do, the record is not doubled, the backup is not overwritten.
        (t / "persist").write_text("".join(f"{h}\n" for h in OTHER))
        if run(OTHER, OTHER + RU[:1]):
            fail("a Russian name left in the saved list must not be put back")
        if len((t / "ru-removed").read_text().split()) != len(RU) or len((t / "persist.ru-backup").read_text().split()) != 12:
            fail("the record and the backup must not change on a later start")
        # 3. Undo: VWARD_ADAPTIVE_RU=1 and the backup as the saved list put them back.
        calls = run(OTHER, (t / "persist.ru-backup").read_text().split(), ru="1")
        back = {c.split()[-1] for c in calls if c.startswith("object-group fqdn AdaptiveAuto include ")}
        if back != set(RU):
            fail(f"the undo must restore exactly the removed names: {sorted(back)}")

print("ADAPTIVE_RU_ZONE=PASS")
