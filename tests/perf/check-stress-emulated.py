#!/usr/bin/env python3
"""Stress on the router emulator: long random faults, the Panel's API under load, races, a full disk.

  soak       N emulated minutes (default 180) of random faults, a new mix every 3-8 minutes
             (no internet, silent VPN, no DNS, Keenetic slow or refusing, AdGuard Home silent
             or restarting, jobs killed or started twice), then 10 healthy minutes. As in the
             chaos run: no hang, no shell error, no change repeated without end, no lock left,
             everything back at the end; and nothing grows without end (processes, /tmp, logs).
  api-load   16 browsers at once read the Panel's API for 60 s while the minute jobs run:
             every answer JSON, none over 30 s, no api.cgi left running, no temp files left.
  api-race   the same change sent from 12 tabs at once (12 domains to «Всегда через VPN» and
             12 to the list of another section, then removed): every change the API said it
             made is there, nothing else is lost, the files stay whole.
  disk-full  /tmp and then the state folder on /opt full for 5 minutes, then free again: no
             hang, no state file left empty or broken, the guards work on afterwards.
  big        a busy home: AdGuard Home's query log of 150 000 queries, 5 000 domains of one's
             own, 20 000 picked by the route engine, 500 «always through VPN»: the ad scan,
             the route reconciler and the Panel's pages stay within time and memory
             (the emulator is ~10x faster than a MIPS router: 10 s here is ~2 minutes there).
Needs root (chroot, mount).
  check-stress-emulated.py [--stage NAME] [--minutes N] [--seed N] [--report FILE]
"""
import argparse
import collections
import concurrent.futures
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


crawl = load("crawl", "tests/perf/check-panel-crawl-emulated.py")
chaos = crawl.chaos

FAULT_MIXES = [
    ["wan"], ["tunnel"], ["dns"], ["wan-flap"], ["ndmc-refuse", "tunnel"], ["ndmc-slow"],
    ["agh"], ["agh-loop"], ["agh", "agh-down"], ["kill"], ["twice"], ["wan", "agh"],
    ["tunnel", "kill"], ["dns", "agh"], ["wan-flap", "tunnel"], [],
]
READ_ACTIONS = ["status", "route-data", "config-data", "security-data", "ads-data", "diagnostics",
                "stability", "cron-data", "lists-data", "awg-data", "update-data", "wifi-data",
                "tunnel-quality", "backup-data", "services-data"]


def ps_count(root):
    """Processes whose root is the emulator (chroot): what VWARD left running."""
    n, names = 0, collections.Counter()
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if os.readlink(p / "root") == str(root):
                n += 1
                names[(p / "comm").read_text().strip()] += 1
        except OSError:
            pass
    return n, names


def du(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def tmp_files(root):
    return {str(p.relative_to(root)) for p in (root / "tmp").rglob("*") if p.is_file()}


def recovered(root, scenario, findings):
    gs = chaos.guard_state(root)
    if gs.get("FAILOPEN_ACTIVE") == "1":
        findings.append((scenario, "not recovered", "tunnel guard still in fail-open"))
    if not chaos.engine_running(root):
        findings.append((scenario, "not recovered", "route engine not running"))
    if "ip name-server 192.0.2.1:65053" not in (root / "emu/running-config").read_text().splitlines():
        findings.append((scenario, "not recovered", "AdGuard Home not back in the DNS chain"))


def stage_soak(root, minutes, seed, findings, info):
    rnd = random.Random(seed)
    minute, left, flags, prev_stale = 0, 0, [], []
    plan = []
    start_ps, _ = ps_count(root)
    sizes = []
    before = len(chaos.ndmc_changes(root))
    t0 = time.time()
    window = collections.Counter()
    for i in range(minutes + 10):
        if left == 0:
            flags = rnd.choice(FAULT_MIXES) if i < minutes else []
            left = rnd.randint(3, 8) if i < minutes else 10
            plan.append((i + 1, "+".join(flags) or "healthy"))
        left -= 1
        minute += 1
        chaos.advance(root)
        chaos.set_faults(root, flags, minute)
        sub = []
        chaos.run_round(root, minute, flags, sub, "soak")
        findings += [("soak", f"minute {m} {job}: {what}", d) for _, m, job, what, d in sub]
        now_stale = chaos.stale_locks(root)
        findings += [("soak", f"minute {minute}: stale lock", l) for l in now_stale if l in prev_stale]
        prev_stale = now_stale
        if minute % 10 == 0:
            n, names = ps_count(root)
            sizes.append((minute, n, du(root / "tmp"), du(root / "opt/var/log"), du(root / "opt/var/lib")))
    # A change repeated without end: more than 6 times the same command within 30 minutes.
    changes = chaos.ndmc_changes(root)[before:]
    refused_f = root / "emu/ndmc-refused.log"
    info["soak_changes"] = len(changes)
    for cmd, n in collections.Counter(c for c in changes if c != "system configuration save").items():
        if n > max(chaos.LOOP_LIMIT, minutes // 10):
            findings.append(("soak", f"loop: {n} times in {minutes} min", cmd[:160]))
    for _ in range(2):  # the last healthy minutes settle everything
        minute += 1; chaos.advance(root); chaos.set_faults(root, [], minute); chaos.run_round(root, minute, [], [], "soak")
    recovered(root, "soak", findings)
    end_ps, names = ps_count(root)
    # Daemons (route engine, crond, supervisor, sentinel) may run; nothing may pile up.
    if end_ps > start_ps + 4:
        findings.append(("soak", "processes pile up", f"{start_ps} -> {end_ps}: {dict(names.most_common(6))}"))
    if len(sizes) >= 4:
        _, _, t_mid, l_mid, s_mid = sizes[len(sizes) // 2]
        _, _, t_end, l_end, s_end = sizes[-1]
        if t_end > max(4 * t_mid, t_mid + 2_000_000):
            findings.append(("soak", "/tmp grows", f"{t_mid} -> {t_end} bytes"))
        if l_end > l_mid + 5_000_000:
            findings.append(("soak", "logs grow", f"{l_mid} -> {l_end} bytes"))
        if s_end > s_mid + 5_000_000:
            findings.append(("soak", "state grows", f"{s_mid} -> {s_end} bytes"))
    info["soak"] = {"minutes": minute, "seconds": round(time.time() - t0), "plan": plan, "samples": sizes}
    return minute


def api_get(root, action):
    q = "action=" + action
    t = time.time()
    status, headers, out, err = crawl.cgi(root, "GET", q, b"", "")
    return action, status, headers.get("Content-Type", ""), out, err, time.time() - t


def api_post(root, query, form):
    body = urllib.parse.urlencode(form).encode()
    status, headers, out, err = crawl.cgi(root, "POST", query, body, "")
    try:
        return json.loads(out)
    except ValueError:
        return {"raw": out.decode(errors="replace")[:200], "status": status}


def stage_api_load(root, minute, findings, info):
    before_tmp = tmp_files(root)
    start_ps, _ = ps_count(root)
    stop = time.time() + 60
    results = []

    def browser(k):
        r = []
        i = k
        while time.time() < stop:
            r.append(api_get(root, READ_ACTIONS[i % len(READ_ACTIONS)]))
            i += 1
        return r

    with concurrent.futures.ThreadPoolExecutor(17) as ex:
        futs = [ex.submit(browser, k) for k in range(16)]
        while time.time() < stop:  # the minute jobs go on meanwhile
            minute += 1
            chaos.advance(root)
            sub = []
            chaos.run_round(root, minute, [], sub, "api-load")
            findings += [("api-load", f"job {job}: {what}", d) for _, _, job, what, d in sub]
        for f in futs:
            results += f.result()
    times = sorted(r[5] for r in results)
    for action, status, ctype, out, err, took in results:
        if status >= 500:
            findings.append(("api-load", f"{action}: HTTP {status}", out[:120].decode(errors="replace")))
        elif "json" in ctype:
            try:
                json.loads(out)
            except ValueError:
                findings.append(("api-load", f"{action}: not JSON", out[:120].decode(errors="replace")))
        if took > 30:
            findings.append(("api-load", f"{action}: {took:.0f} s", ""))
        e = err.decode(errors="replace")
        if chaos.SHELL_ERRORS.search(e) and not chaos.SHELL_OK.search(e):
            findings.append(("api-load", f"{action}: shell said", e.strip()[-200:]))
    time.sleep(2)
    _, names = ps_count(root)
    if names.get("api.cgi", 0):
        findings.append(("api-load", "api.cgi left running", str(names["api.cgi"])))
    # Temporary files (name.tmp, name.new.PID, name.PID; p.1-style files rewritten each minute are fine) of answers that have all ended.
    left = sorted(f for f in tmp_files(root) - before_tmp
                  if ".tmp" in f or ".new." in f or (f.rsplit(".", 1)[-1].isdigit() and len(f.rsplit(".", 1)[-1]) >= 3))
    if left:
        findings.append(("api-load", "temp files left", ", ".join(left[:8])))
    info["api_load"] = {"requests": len(results), "p50": round(times[len(times) // 2], 2) if times else 0,
                        "p95": round(times[int(len(times) * 0.95)], 2) if times else 0, "max": round(times[-1], 2) if times else 0}
    return minute


def file_set(path):
    if not path.exists():
        return set()
    return {l.split("#")[0].split("|")[0].strip().lower() for l in path.read_text().splitlines() if l.strip()}


# (name, the API call for one domain, the file that must hold it afterwards)
RACES = [
    ("force-vpn", lambda op, d: ("action=config", {"op": "force-vpn", "action": op, "target": d}),
     "opt/etc/vward/route-engine/force-vpn.conf"),
    ("ads allow", lambda op, d: ("action=ads-control", {"op": "allow" if op == "add" else "remove-override", "domain": d, "scope": "exact"}),
     "opt/etc/vward/ads-privacy-guard/allowlist.tsv"),
]


def stage_api_race(root, findings, info):
    names = [f"stress{n}.example.org" for n in range(12)]
    out = {}
    for race, call, file in RACES:
        for op in ("add", "remove"):
            with concurrent.futures.ThreadPoolExecutor(12) as ex:
                res = list(ex.map(lambda d: (d, api_post(root, *call(op, d))), names))
            said = [d for d, r in res if r.get("ok") and r.get("result", "changed") in ("changed", "unchanged") or str(r.get("result", "")).startswith("CONTROL=PASS")]
            refused = [(d, r.get("error") or r.get("raw")) for d, r in res if not r.get("ok")]
            have = file_set(root / file)
            lost = [d for d in said if (d in have) != (op == "add")]
            out[f"{race} {op}"] = {"changed": len(said), "refused": refused[:4], "lost": lost}
            if lost:
                findings.append(("api-race", f"{race} {op}: {len(lost)} of {len(said)} changes the API reported are not in the file",
                                 ", ".join(lost[:6])))
            odd = [e for _, e in refused if e not in ("route_change_busy", "updater_busy", "busy")]
            if odd:
                findings.append(("api-race", f"{race} {op}: unexpected errors", str(odd[:4])))
            if len(refused) > len(names) // 2:
                findings.append(("api-race", f"{race} {op}: most changes refused as busy", str(len(refused))))
    info["api_race"] = out


def fill(path):
    """Fills the file system under PATH; returns the filler file."""
    f = path / ".stress-filler"
    try:
        with open(f, "wb") as fh:
            while True:
                fh.write(b"\0" * 4096)
    except OSError:
        pass
    return f


def state_problems(root):
    bad = []
    for base in ("opt/var/lib/vward", "opt/var/run/vward", "tmp"):
        for p in (root / base).rglob("*"):
            if p.is_file() and p.name in ("state", "status") or p.suffix in (".state", ".status", ".json"):
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                if not data.strip():
                    bad.append(f"{p.relative_to(root)} empty")
                elif p.suffix == ".json":
                    try:
                        json.loads(data)
                    except ValueError:
                        bad.append(f"{p.relative_to(root)} broken JSON")
    return bad


def stage_disk_full(root, minute, findings, info):
    before = set(state_problems(root))
    t_mnt = root / "tmp"
    # The route engine keeps pipes in /tmp: stopped while /tmp moves to a small RAM disk.
    chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine stop", timeout=30)
    saved = Path(tempfile.mkdtemp(prefix="vward-stress-tmp."))
    subprocess.run(["cp", "-a", f"{t_mnt}/.", str(saved)], check=True)
    # A small RAM disk: what /tmp holds now plus 4 MB, filled up below.
    t_size = du(saved) // 1024 + 4096
    subprocess.run(["mount", "-t", "tmpfs", "-o", f"size={t_size}k,mode=1777", "tmpfs", str(t_mnt)], check=True)
    subprocess.run(["cp", "-a", f"{saved}/.", str(t_mnt)], check=True)
    shutil.rmtree(saved, ignore_errors=True)
    chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine start")
    lib = root / "opt/var/lib/vward"
    lib_copy = Path(tempfile.mkdtemp(prefix="vward-stress-lib."))
    shutil.copytree(lib, lib_copy / "lib", symlinks=True)
    subprocess.run(["mount", "-t", "tmpfs", "-o", f"size={du(lib_copy) // 1024 + 8192}k", "tmpfs", str(lib)], check=True)
    subprocess.run(["cp", "-a", f"{lib_copy}/lib/.", str(lib)], check=True)
    try:
        for where, path in (("/tmp", t_mnt), ("/opt state", lib)):
            filler = fill(path)
            for i in range(5):
                minute += 1
                chaos.advance(root)
                chaos.set_faults(root, ["tunnel"] if i == 2 else [], minute)
                sub = []
                chaos.run_round(root, minute, [], sub, "disk-full")
                findings += [("disk-full", f"{where} full, {job}: {what}", d) for _, _, job, what, d in sub
                             if what.startswith("hang")]
            filler.unlink(missing_ok=True)
            for i in range(4):
                minute += 1
                chaos.advance(root)
                chaos.set_faults(root, [], minute)
                sub = []
                chaos.run_round(root, minute, [], sub, "disk-full")
                findings += [("disk-full", f"after {where} full, {job}: {what}", d) for _, _, job, what, d in sub]
            now = set(state_problems(root)) - before
            findings += [("disk-full", f"after {where} full: state file", p) for p in sorted(now)]
        recovered(root, "disk-full", findings)
    finally:
        chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine stop", timeout=30)
        subprocess.run(["umount", "-l", str(lib)], check=False)
        subprocess.run(["umount", "-l", str(t_mnt)], check=False)
        chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine start")
        shutil.rmtree(lib_copy, ignore_errors=True)
    info["disk_full"] = "done"
    return minute


def rss_now(root):
    """(total, largest) resident memory in KB of the processes inside the emulator."""
    total = big = 0
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if os.readlink(p / "root") != str(root):
                continue
            for line in (p / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1]); total += kb; big = max(big, kb)
        except (OSError, ValueError):
            pass
    return total, big


def timed(root, cmd, timeout=300):
    """Runs CMD in the emulator: (rc, output, seconds, peak total RSS KB, peak single RSS KB)."""
    import threading
    peak = [0, 0]
    done = threading.Event()

    def watch():
        while not done.is_set():
            t, b = rss_now(root)
            peak[0], peak[1] = max(peak[0], t), max(peak[1], b)
            done.wait(0.05)
    base, _ = rss_now(root)  # daemons already running (route engine)
    th = threading.Thread(target=watch, daemon=True)
    th.start()
    t = time.time()
    rc, out, _ = chaos.sh(root, cmd, timeout=timeout)
    took = time.time() - t
    done.set(); th.join()
    return rc, out, took, max(0, peak[0] - base), peak[1]


def stage_big(root, findings, info):
    rnd = random.Random(7)
    words = ["video", "cdn", "api", "ads", "track", "img", "static", "mail", "news", "shop", "games", "music"]
    doms = [f"{rnd.choice(words)}{n % 3000}.{rnd.choice(words)}-{n % 997}.example" for n in range(150000)]
    data = root / "opt/etc/AdGuardHome/data"
    data.mkdir(parents=True, exist_ok=True)
    with open(data / "querylog.json", "w") as f:
        for n, d in enumerate(doms):
            f.write(json.dumps({"T": f"2026-10-05T10:{n // 6000 % 60:02d}:{n // 100 % 60:02d}.0+03:00", "QH": d, "QT": "A", "QC": "IN",
                                "CP": "", "Upstream": "udp://9.9.9.10:53", "IP": f"192.0.2.{10 + n % 40}", "Result": {}, "Elapsed": 1000}) + "\n")
    own = "".join(f"    include own{n}.example.net\n" for n in range(5000))
    rc = root / "emu/running-config"
    rc.write_text(rc.read_text().replace("object-group fqdn vpn-sites\n", "object-group fqdn vpn-sites\n" + own, 1))
    (root / "opt/var/lib/vward/route-engine").mkdir(parents=True, exist_ok=True)
    (root / "opt/var/lib/vward/route-engine/adaptive-persist.txt").write_text("".join(f"auto{n}.example.com\n" for n in range(20000)))
    (root / "opt/etc/vward/route-engine").mkdir(parents=True, exist_ok=True)
    (root / "opt/etc/vward/route-engine/force-vpn.conf").write_text("".join(f"force{n}.example.org\n" for n in range(500)))
    conf = root / "opt/etc/vward/ads-privacy-guard/ads-privacy-guard.conf"
    conf.write_text(conf.read_text() + "\nQUERY_SOURCE=file\nSCAN_TAIL_LINES=20000\n")
    res = {}
    for name, cmd, limit_s in (
        ("ads scan", "VWARD_ADS_FORCE_SCAN=1 /opt/bin/vward-ads-privacy-guard.sh", 30),
        ("route reconciler", "/opt/bin/vward-route-reconciler.sh", 30),
        ("ads scheduler", "/opt/bin/vward-ads-privacy-scheduler.sh", 20),
        ("tunnel guard", "/opt/bin/vward-tunnel-guard.sh", 10),
    ):
        rc_, out, took, rss, rss1 = timed(root, cmd)
        res[name] = {"s": round(took, 1), "rss_kb": rss, "largest_kb": rss1, "out": " ".join((out or "").split()[:3])}
        if rc_ == "timeout" or took > limit_s:
            findings.append(("big", f"{name}: {took:.0f} s (limit {limit_s} s here)", ""))
        # A KN-1913 has 256 MB and AdGuard Home, Xray and the firmware live there too.
        if rss > 48000:
            findings.append(("big", f"{name}: {rss // 1024} MB of memory at once", ""))
        for line in (out or "").splitlines():
            if chaos.SHELL_ERRORS.search(line) and not chaos.SHELL_OK.search(line):
                findings.append(("big", f"{name}: shell error", line.strip()[:200]))
    for action in ("route-data", "config-data", "lists-data", "status", "ads-data", "list-data&name=vpn-sites"):
        a, status, ctype, out, err, took = api_get(root, action)
        res["api " + action] = {"s": round(took, 2), "bytes": len(out)}
        if status >= 500 or took > 5:
            findings.append(("big", f"api {action}: HTTP {status}, {took:.1f} s", out[:100].decode(errors="replace")))
        if "json" in ctype:
            try:
                json.loads(out)
            except ValueError:
                findings.append(("big", f"api {action}: not JSON", out[:100].decode(errors="replace")))
    info["big"] = res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", action="append", choices=["soak", "api-load", "api-race", "disk-full", "big"])
    ap.add_argument("--minutes", type=int, default=180)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("VWARD_STRESS_SEED", "1")))
    ap.add_argument("--report")
    args = ap.parse_args()
    if os.geteuid() != 0:
        print("STRESS_EMULATED=SKIP (needs root)")
        return 0
    stages = args.stage or ["api-race", "api-load", "disk-full", "big", "soak"]
    tmp = Path(tempfile.mkdtemp(prefix="vward-stress."))
    root = chaos.build(tmp)
    findings, info = [], {"seed": args.seed}
    minute = 0
    try:
        chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine start")
        for st in stages:
            t0 = time.time()
            if st == "soak":
                minute = stage_soak(root, args.minutes, args.seed, findings, info)
            elif st == "api-load":
                minute = stage_api_load(root, minute, findings, info)
            elif st == "api-race":
                stage_api_race(root, findings, info)
            elif st == "big":
                stage_big(root, findings, info)
            elif st == "disk-full":
                minute = stage_disk_full(root, minute, findings, info)
            print(f"{st:10} {time.time() - t0:6.0f} s", flush=True)
    finally:
        chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine stop", timeout=30)
        chaos.sh(root, "/opt/etc/init.d/S92vward-runtime stop", timeout=30)
        for m in ("opt", "proc"):
            subprocess.run(["umount", "-l", str(root / m)], check=False)
    seen = set()
    findings = [f for f in findings if not (f in seen or seen.add(f))]
    if args.report:
        Path(args.report).write_text(json.dumps({"info": info, "findings": findings}, ensure_ascii=False, indent=1))
    for k in ("api_load", "api_race", "big"):
        if k in info:
            print(k, json.dumps(info[k], ensure_ascii=False))
    if "soak" in info:
        print("soak", info["soak"]["minutes"], "min,", info["soak"]["seconds"], "s; samples (minute, processes, /tmp, logs, state):",
              info["soak"]["samples"][-3:])
    for f in findings:
        print("FINDING", f)
    shutil.rmtree(tmp, ignore_errors=True)
    print("STRESS_EMULATED=" + ("FAIL" if findings else "PASS"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
