#!/usr/bin/env python3
"""Resource audit of VWARD on an emulated router.

Flash wear is counted as file operations on /opt: every file opened for
writing, renamed, created or removed (write() calls into an open file are one
operation: the page cache merges them).

Builds the router emulator (tests/perf/emulator/build-rootfs.sh), starts the
daemons, and measures under strace every periodic job, the route engine per DNS
query, the cron supervisor and the Console API:
  * processes started (execve), without the internals of the fake router tools;
  * bytes written and write operations on /opt (USB flash) and /tmp (RAM);
  * CPU time and peak RSS (separate runs without strace);
  * /opt/var and /tmp growth.

Needs root (chroot, mknod, mount proc), strace, busybox and a C compiler.
  run-resource-audit.py [--json OUT] [--markdown OUT] [--budget FILE] [--seconds N]
With --budget the run fails when a job exceeds its limits.
"""
import argparse
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "tests/perf/emulator/build-rootfs.sh"
PATH_ENV = "/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
FAKES = {"/opt/bin/curl", "/opt/bin/ping", "/opt/bin/nslookup", "/opt/bin/wg", "/opt/bin/ps",
         "/bin/ndmc", "/opt/sbin/ip", "/opt/sbin/lighttpd"}

# Periodic jobs from config/cron/root.crontab: (name, command, runs per day).
JOBS = [
    ("route-engine watchdog (S91)", "/opt/etc/init.d/S91vward-route-engine start", 1440),
    ("tunnel health", "/opt/bin/vward-tunnel-health.sh", 1440),
    ("tunnel guard", "/opt/bin/vward-tunnel-guard.sh", 1440),
    ("runtime watchdog (S92)", "/opt/etc/init.d/S92vward-runtime start", 1440),
    ("WAN guard", "/opt/bin/vward-wan-guard.sh", 1440),
    ("ads scheduler", "/opt/bin/vward-ads-privacy-scheduler.sh", 1440),
    ("route reconciler", "/opt/bin/vward-route-reconciler.sh", 288),
    ("Wi-Fi scheduler", "/opt/bin/vward-wifi-client-scheduler.sh", 288),
    ("housekeeping", "/opt/bin/vward-housekeeping.sh", 24),
    ("updater check", "/opt/share/vward/updater/current/vward-update-watch.sh --once", 96),
    ("ads scan (empty query log)", "/opt/bin/vward-ads-privacy-guard.sh scan", 144),
]

# Console API calls a page makes; overview is polled while the page is open.
API = [
    ("api status", "action=status"),
    ("api config-data", "action=config-data"),
    ("api route-data", "action=route-data"),
    ("api security-data", "action=security-data"),
    ("api cron-data", "action=cron-data"),
]

# Emulator daemons, matched from the start of the command line only.
DAEMONS = r"^\s*\d+ (/bin/sh /opt/bin/vward-(route-engine|cron-supervisor)\.sh|tcpdump -ni |/opt/sbin/crond)"
LINE = re.compile(r"^(\d+)\s+(\w+)\((.*)\)\s+=\s+(-?\d+|\?)")


def sh(root, command, env=None, timeout=120, trace=None):
    base = ["env", "-i", f"PATH={PATH_ENV}", "HOME=/root", "VWARD_EMU_DNS_INTERVAL=1"]
    base += [f"{k}={v}" for k, v in (env or {}).items()]
    cmd = base + ["chroot", str(root), "/bin/sh", "-c", command]
    if trace:
        cmd = ["strace", "-f", "-qq", "-y", "-s0", "-o", str(trace),
               "-e", "trace=execve,clone,clone3,fork,vfork,openat,open,creat,write,writev,pwrite64,"
                     "rename,renameat,renameat2,unlink,unlinkat,mkdir,mkdirat,rmdir,ftruncate,truncate"] + cmd
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, text=True)


def rel(root, path):
    s = str(root)
    return path[len(s):] if path.startswith(s) else path


def parse(trace, root):
    """Counts from one strace log, fake-tool internals excluded."""
    parent, fake, execs = {}, set(), []
    stats = {"execs": 0, "opt_bytes": 0, "opt_ops": 0, "tmp_bytes": 0, "tmp_ops": 0, "opt_files": {}}
    lines = trace.read_text(errors="replace").splitlines()
    for line in lines:
        m = LINE.match(line)
        if not m:
            continue
        pid, call, args, ret = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if call in ("clone", "clone3", "fork", "vfork") and ret.isdigit():
            parent[int(ret)] = pid
            if pid in fake:
                fake.add(int(ret))
    def excluded(pid):
        seen = 0
        while pid in parent and seen < 64:
            pid = parent[pid]
            seen += 1
            if pid in fake:
                return True
        return False
    for line in lines:
        m = LINE.match(line)
        if not m:
            continue
        pid, call, args, ret = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if call == "execve" and ret == "0":
            path = rel(root, args.split('"')[1]) if '"' in args else "?"
            if excluded(pid) or pid in fake:
                continue
            if path in FAKES:
                fake.add(pid)
            execs.append(path)
            continue
        if excluded(pid) or pid in fake:
            continue
        paths = [rel(root, p) for p in re.findall(r"<([^<>]*)>", args)]
        if call in ("write", "writev", "pwrite64") and paths and ret.isdigit():
            p = paths[0]
            if p.startswith("/opt/"):
                stats["opt_bytes"] += int(ret)
                p = re.sub(r"\.(tmp\.)?\d+$|\.\d+$", ".*", p)
                stats["opt_files"][p] = stats["opt_files"].get(p, 0) + int(ret)
            elif p.startswith("/tmp/"):
                stats["tmp_bytes"] += int(ret)
        elif call in ("openat", "open", "creat") and ret != "-1":
            quoted = re.findall(r'"([^"]*)"', args)
            if quoted and ("O_WRONLY" in args or "O_RDWR" in args or call == "creat"):
                p = quoted[0]
                if p.startswith("/opt/"):
                    stats["opt_ops"] += 1
                elif p.startswith("/tmp/"):
                    stats["tmp_ops"] += 1
        elif call in ("rename", "renameat", "renameat2", "unlink", "unlinkat", "mkdir", "mkdirat", "rmdir", "truncate", "ftruncate") and not ret.startswith("-"):
            quoted = re.findall(r'"([^"]*)"', args) + paths
            if any(q.startswith("/opt/") for q in quoted):
                stats["opt_ops"] += 1
    stats["execs"] = len(execs) - 1  # the chroot shell itself
    stats["programs"] = {}
    for e in execs[1:]:
        name = os.path.basename(e)
        stats["programs"][name] = stats["programs"].get(name, 0) + 1
    return stats


def cpu_run(root, command, env=None):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.monotonic()
    sh(root, command, env)
    wall = time.monotonic() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return cpu, wall, after.ru_maxrss


def measure(root, work, name, command, runs=3, env=None):
    sh(root, command, env)  # warm-up: first run initialises state
    totals = {"execs": 0, "opt_bytes": 0, "opt_ops": 0, "tmp_bytes": 0, "tmp_ops": 0}
    programs, files = {}, {}
    for i in range(runs):
        trace = work / f"{re.sub(r'[^a-z0-9]+', '-', name.lower())}-{i}.trace"
        sh(root, command, env, trace=trace)
        s = parse(trace, root)
        for k in totals:
            totals[k] += s[k]
        for k, v in s["programs"].items():
            programs[k] = programs.get(k, 0) + v
        for k, v in s["opt_files"].items():
            files[k] = files.get(k, 0) + v
    cpu = wall = 0.0
    for _ in range(runs):
        c, w, _ = cpu_run(root, command, env)
        cpu += c
        wall += w
    result = {k: round(v / runs, 1) for k, v in totals.items()}
    result["cpu_ms"] = round(cpu / runs * 1000, 1)
    result["wall_ms"] = round(wall / runs * 1000, 1)
    result["top_programs"] = sorted(((k, round(v / runs, 1)) for k, v in programs.items()), key=lambda x: -x[1])[:8]
    result["opt_files"] = sorted(((k, round(v / runs)) for k, v in files.items()), key=lambda x: -x[1])[:6]
    return result


def pids(pattern):
    out = subprocess.run(["ps", "-eo", "pid,args"], stdout=subprocess.PIPE, text=True).stdout
    return [int(l.split()[0]) for l in out.splitlines()[1:] if re.search(pattern, l)]


def rss_kb(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def trace_daemon(root, work, pid, seconds, name):
    trace = work / f"daemon-{name}.trace"
    subprocess.run(["timeout", str(seconds), "strace", "-f", "-qq", "-y", "-s0", "-o", str(trace), "-p", str(pid),
                    "-e", "trace=execve,clone,clone3,fork,vfork,openat,open,creat,write,writev,rename,renameat,renameat2,unlink,unlinkat,mkdir,mkdirat,rmdir"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = parse(trace, root)
    s["execs"] += 1  # parse() drops the first exec as the wrapper; daemons have none
    return s


def du_kb(path):
    out = subprocess.run(["du", "-sk", str(path)], stdout=subprocess.PIPE, text=True).stdout
    return int(out.split()[0]) if out else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--markdown")
    ap.add_argument("--budget")
    ap.add_argument("--seconds", type=int, default=60)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("run-resource-audit: needs root (chroot, mknod, mount proc)")
    for tool in ("strace", "busybox", "cc", "jq", "openssl"):
        if not shutil.which(tool):
            sys.exit(f"run-resource-audit: {tool} is required")

    tmp = Path(tempfile.mkdtemp(prefix="vward-audit."))
    root, work = tmp / "root", tmp / "work"
    work.mkdir()
    subprocess.run([str(BUILD), str(root)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
    # /opt as its own mount point, like the USB disk: df and free-space gates work.
    subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
    report = {"version": (REPO / "VERSION").read_text().strip(), "jobs": {}, "daemons": {}, "api": {}, "console": {}}
    try:
        # A router that has run the updater has its run directory.
        (root / "opt/var/run/vward").mkdir(parents=True, exist_ok=True)
        sh(root, "/opt/etc/init.d/S90crond start")
        sh(root, "/opt/etc/init.d/S91vward-route-engine start")
        sh(root, "/opt/etc/init.d/S92vward-runtime start")
        opt0, tmp0 = du_kb(root / "opt/var"), du_kb(root / "tmp")

        for name, command, per_day in JOBS:
            r = measure(root, work, name, command)
            r["per_day"] = per_day
            report["jobs"][name] = r

        engine = pids(r"^\s*\d+ /bin/sh /opt/bin/vward-route-engine\.sh")
        if engine:
            s = trace_daemon(root, work, engine[0], a.seconds, "route-engine")
            s["queries"] = a.seconds  # fake tcpdump: one query per second
            s["rss_kb"] = sum(rss_kb(p) for p in pids(r"^\s*\d+ (/bin/sh /opt/bin/vward-route-engine\.sh|tcpdump -ni |awk -v window=)"))
            report["daemons"]["route engine"] = s
        sup = pids(r"^\s*\d+ /bin/sh /opt/bin/vward-cron-supervisor\.sh")
        if sup:
            s = trace_daemon(root, work, sup[0], a.seconds, "cron-supervisor")
            s["rss_kb"] = rss_kb(sup[0])
            report["daemons"]["cron supervisor"] = s
        for name, d in report["daemons"].items():
            d["seconds"] = a.seconds

        cgi = "/opt/share/vward/console/www/cgi-bin/api.cgi"
        for name, query in API:
            env = {"REQUEST_METHOD": "GET", "QUERY_STRING": query, "REMOTE_ADDR": "192.0.2.20"}
            report["api"][name] = measure(root, work, name, cgi, runs=2, env=env)

        www = root / "opt/share/vward/console/www"
        for f in ("index.html", "assets/vward-console.css", "assets/vward-console.js"):
            data = (www / f).read_bytes()
            gz = subprocess.run(["gzip", "-9c"], input=data, stdout=subprocess.PIPE).stdout
            report["console"][f] = {"bytes": len(data), "gzip": len(gz)}

        report["growth"] = {"opt_var_kb": du_kb(root / "opt/var") - opt0, "tmp_kb": du_kb(root / "tmp") - tmp0,
                            "tmp_files": sum(1 for _ in (root / "tmp").rglob("*"))}
    finally:
        for p in pids(DAEMONS):
            try:
                os.kill(p, 9)
            except OSError:
                pass
        time.sleep(0.5)
        subprocess.run(["umount", str(root / "opt")])
        subprocess.run(["umount", str(root / "proc")])
        shutil.rmtree(tmp, ignore_errors=True)

    daily = {"execs": 0, "opt_bytes": 0, "opt_ops": 0, "cpu_s": 0.0}
    for r in report["jobs"].values():
        daily["execs"] += r["execs"] * r["per_day"]
        daily["opt_bytes"] += r["opt_bytes"] * r["per_day"]
        daily["opt_ops"] += r["opt_ops"] * r["per_day"]
        daily["cpu_s"] += r["cpu_ms"] * r["per_day"] / 1000
    for d in report["daemons"].values():
        scale = 86400 / d["seconds"]
        daily["execs"] += d["execs"] * scale
        daily["opt_bytes"] += d["opt_bytes"] * scale
        daily["opt_ops"] += d["opt_ops"] * scale
    report["daily"] = {k: round(v, 1) for k, v in daily.items()}

    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    md = to_markdown(report)
    if a.markdown:
        Path(a.markdown).write_text(md)
    print(md)
    if a.budget:
        failures = check_budget(report, json.loads(Path(a.budget).read_text()))
        for f in failures:
            print(f"BUDGET FAIL: {f}")
        if failures:
            sys.exit(1)
        print("RESOURCE_BUDGET=PASS")


def to_markdown(r):
    out = [f"## VWARD {r['version']}: ресурсы на эмуляторе роутера", "",
           "| Задание | запусков/сутки | процессов | CPU, мс | запись /opt, байт | файловых операций /opt | запись /tmp, байт |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for name, j in r["jobs"].items():
        out.append(f"| {name} | {j['per_day']} | {j['execs']} | {j['cpu_ms']} | {j['opt_bytes']} | {j['opt_ops']} | {j['tmp_bytes']} |")
    out += ["", "| Демон | за, с | процессов | запись /opt, байт | операций /opt | RSS, КБ |", "|---|---:|---:|---:|---:|---:|"]
    for name, d in r["daemons"].items():
        out.append(f"| {name} | {d['seconds']} | {d['execs']} | {d['opt_bytes']} | {d['opt_ops']} | {d.get('rss_kb', 0)} |")
    out += ["", "| Console API | процессов | CPU, мс | время, мс |", "|---|---:|---:|---:|"]
    for name, j in r["api"].items():
        out.append(f"| {name} | {j['execs']} | {j['cpu_ms']} | {j['wall_ms']} |")
    out += ["", "| Файл Console | байт | gzip |", "|---|---:|---:|"]
    for name, c in r["console"].items():
        out.append(f"| {name} | {c['bytes']} | {c['gzip']} |")
    d = r["daily"]
    out += ["", f"В сутки: процессов {int(d['execs'])}, CPU периодических заданий {d['cpu_s']} с, "
            f"запись на /opt {int(d['opt_bytes'] / 1024)} КБ, файловых операций на /opt {int(d['opt_ops'])}."]
    return "\n".join(out) + "\n"


def check_budget(report, budget):
    failures = []
    for name, limits in budget.get("jobs", {}).items():
        j = report["jobs"].get(name)
        if j is None:
            failures.append(f"{name}: not measured")
            continue
        for key, limit in limits.items():
            if j[key] > limit:
                failures.append(f"{name}: {key} {j[key]} > {limit}")
    for name, limits in budget.get("daemons", {}).items():
        d = report["daemons"].get(name)
        if d is None:
            failures.append(f"{name}: not measured")
            continue
        for key, limit in limits.items():
            value = d[key] * 60 / d["seconds"] if key in ("execs", "opt_ops") else d[key]
            if value > limit:
                failures.append(f"{name}: {key} per minute {round(value, 1)} > {limit}")
    for key, limit in budget.get("daily", {}).items():
        if report["daily"][key] > limit:
            failures.append(f"daily {key} {report['daily'][key]} > {limit}")
    return failures


if __name__ == "__main__":
    main()
