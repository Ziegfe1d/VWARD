#!/usr/bin/env python3
"""VWARD Panel speed on the router emulator: what every page and every switch costs.

Diagnostic tool (owner 08.11: «каждый тумблер за 1-2 секунды»), not a gate. Builds the
emulator of tests/perf/run-resource-audit.py and runs the Panel API (api.cgi) under strace
for every data request the Panel's pages make (LOADERS of vward-console.js) and for the
switches/buttons (POST), counting:
  * processes started (execve, the fake router tools counted once each, their insides not);
  * ndmc calls, of them «show running-config» (fake ndmc log), RCI requests (fake curl log);
  * the wall time here (x86, not the router).

Estimate for the owner's Keenetic (an estimate, not a measurement): processes x 10 ms
(owner 07.11: BusyBox 1.37 on the Viva, ~10 ms a process) + every «show running-config»
x 4 s (owner: 4 s a read) + every other ndmc x 0.3 s + every RCI request x 0.1 s.
A switch that starts a background job is measured to the API answer; the job itself
separately ("job" column) when it ends within the timeout.

  measure-panel.py [--json OUT] [--markdown OUT] [--runs N]
Needs root (chroot), strace, busybox, cc, jq, openssl (as run-resource-audit.py).
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("audit", REPO / "tests/perf/run-resource-audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

PROC_MS, RUNCFG_S, NDMC_S, RCI_S = 10, 4.0, 0.3, 0.1
CGI = "/opt/share/vward/console/www/cgi-bin/api.cgi"

# Page -> the data requests it makes at opening (PAGES[].data of vward-console.js, plus the
# «off» and «notes» every page adds).
PAGES = {
    "Обзор": ["status", "route-data", "wifi-data", "ads-data", "ads-view&view=stats", "lists-data", "awg-data", "tunnel-quality"],
    "Сеть": ["status", "security-data", "config-data", "wifi-data"],
    "VPN": ["status", "security-data", "config-data", "route-data", "awg-data", "ext-update-data", "tunnel-quality"],
    "Маршруты": ["route-data", "security-data", "status", "config-data", "lists-data", "services-data"],
    "Реклама": ["ads-data", "security-data", "ads-view&view=publish-status", "ads-https-data"],
    "DNS (ИИ)": ["ai-data", "status", "config-data"],
    "Компоненты": ["status", "ads-data", "ads-view&view=agh", "security-data", "ext-update-data", "awg-data"],
    "Система": ["status", "diagnostics", "security-data", "config-data", "stability", "cron-data", "cleanup-data", "backup-data", "update-data", "ext-update-data"],
    "Настройки": ["security-data", "auth", "status", "config-data"],
}
COMMON = ["vward-off", "notes"]
EXTRA_GET = ["journal-data", "list-data&name=vpn-sites", "list-addrs&name=vpn-sites", "services-data&id=youtube"]

# Switches and buttons: (label, action, form fields, background job?).
POSTS = [
    ("Агенты: режим Наблюдение/Действие", "config", {"op": "agents-mode", "target": "network", "value": "watch"}, False),
    ("Компонент вкл/выкл (Сверка маршрутов)", "config", {"op": "component", "target": "route-reconciler", "value": "1"}, False),
    ("Автоподбор вкл/выкл", "config", {"op": "adaptive-mode", "value": "1"}, False),
    ("Агент VPN вкл/выкл", "config", {"op": "tunnel-guard", "value": "1"}, False),
    ("Агент интернета вкл/выкл", "config", {"op": "wan-guard", "value": "1"}, False),
    ("Классификатор вкл/выкл", "config", {"op": "classifier", "value": "1"}, False),
    ("Домен в список (добавить)", "config", {"op": "route-domain", "action": "add", "target": "example.org"}, False),
    ("Домен из списка (убрать)", "config", {"op": "route-domain", "action": "remove", "target": "example.org"}, False),
    ("Список: путь Авто/VPN/Напрямую", "config", {"op": "list-mode", "target": "vpn-sites", "value": "vpn"}, False),
    ("Журнал: хранение", "config", {"op": "journal", "target": "keep_days", "value": "14"}, False),
    ("Wi-Fi: параметр", "config", {"op": "wifi", "target": "CONTROL_ENABLED", "value": "0"}, False),
    ("Сервис вкл (YouTube через VPN)", "services", {"op": "on", "id": "youtube", "tunnel": "Wireguard1"}, True),
    ("Сервис выкл", "services", {"op": "off", "id": "youtube"}, True),
    ("ИИ-сервис: Smart DNS/VPN/Провайдер", "services", {"op": "ai", "id": "chatgpt", "tunnel": "isp"}, True),
    ("Реклама: пауза", "ads-control", {"op": "pause"}, False),
    ("Реклама: продолжить", "ads-control", {"op": "resume"}, False),
    ("Обновления: проверить", "control", {"op": "update-check"}, True),
]


def log_lines(root, name):
    p = root / "emu" / name
    return p.read_text(errors="replace").splitlines() if p.exists() else []


def one(root, work, label, env, runs):
    """Processes/ndmc/RCI of one API call (median of runs) and the wall time."""
    rows = []
    for i in range(runs):
        before = {n: len(log_lines(root, n)) for n in ("config-reads.log", "ndmc-all.log", "rci.log", "ndmc-changes.log")}
        trace = work / f"t-{abs(hash(label))}-{i}.trace"
        t0 = time.monotonic()
        r = audit.sh(root, CGI, env, trace=trace, timeout=300)
        wall = time.monotonic() - t0
        s = audit.parse(trace, root)
        after = {n: log_lines(root, n)[before[n]:] for n in before}
        body = r.stdout.split("\n\n", 1)[-1].strip()[:300]
        rows.append({"execs": s["execs"], "runcfg": len(after["config-reads.log"]), "ndmc": len(after["ndmc-all.log"]),
                     "rci": len(after["rci.log"]), "changes": len(after["ndmc-changes.log"]), "wall_ms": round(wall * 1000),
                     "opt_ops": s["opt_ops"], "top": sorted(s["programs"].items(), key=lambda x: -x[1])[:6],
                     "ndmc_cmds": sorted(set(after["ndmc-all.log"]))[:8], "answer": body})
    rows.sort(key=lambda x: x["execs"])
    m = rows[len(rows) // 2]
    m["runs_execs"] = [x["execs"] for x in rows]
    m["estimate_s"] = round(m["execs"] * PROC_MS / 1000 + m["runcfg"] * RUNCFG_S + max(0, m["ndmc"] - m["runcfg"]) * NDMC_S + m["rci"] * RCI_S, 1)
    return m


def wait_jobs(root, timeout=240):
    """The background job of the last switch: until no detached helper runs (or timeout)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        out = subprocess.run(["ps", "-eo", "args"], stdout=subprocess.PIPE, text=True).stdout
        if not any("vward-console-config.sh" in l and str(root) not in l and "ps -eo" not in l for l in out.splitlines()):
            return round(time.monotonic() - t0, 1)
        time.sleep(0.5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--markdown")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("measure-panel: needs root")
    tmp = Path(tempfile.mkdtemp(prefix="vward-panel."))
    root, work = tmp / "root", tmp / "work"
    work.mkdir()
    subprocess.run([str(audit.BUILD), str(root)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
    subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
    report = {"version": (REPO / "VERSION").read_text().strip(), "assumptions": {"proc_ms": PROC_MS, "runcfg_s": RUNCFG_S, "ndmc_s": NDMC_S, "rci_s": RCI_S},
              "get": {}, "post": {}, "pages": {}}
    try:
        (root / "opt/var/run/vward").mkdir(parents=True, exist_ok=True)
        base = {"REMOTE_ADDR": "192.0.2.20", "HTTP_HOST": "192.0.2.1:8088", "SERVER_PORT": "8088"}
        gets = sorted({q for qs in PAGES.values() for q in qs} | set(COMMON) | set(EXTRA_GET))
        # Cold: every cache empty (the first opening after boot or after a change).
        for q in gets:
            shutil.rmtree(root / "tmp/vward-console-cache", ignore_errors=True)
            shutil.rmtree(root / "tmp/vward-keenetic", ignore_errors=True)
            env = base | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=" + q}
            report["get"][q] = {"cold": one(root, work, "c" + q, env, 1)}
        # Warm: right after another request (caches filled, the 15 s refresh of an open page).
        for q in gets:
            env = base | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=" + q}
            report["get"][q]["warm"] = one(root, work, "w" + q, env, a.runs)
        for page, qs in PAGES.items():
            qs = qs + COMMON
            # The browser asks them at once; lighttpd runs them side by side: the page is
            # complete with the slowest, the router works the sum.
            report["pages"][page] = {
                "requests": len(qs),
                "cold_max_s": max(report["get"][q]["cold"]["estimate_s"] for q in qs),
                "cold_sum_s": round(sum(report["get"][q]["cold"]["estimate_s"] for q in qs), 1),
                "warm_max_s": max(report["get"][q]["warm"]["estimate_s"] for q in qs),
                "warm_sum_s": round(sum(report["get"][q]["warm"]["estimate_s"] for q in qs), 1),
                "slowest": max(qs, key=lambda q: report["get"][q]["cold"]["estimate_s"]),
            }
        for label, action, fields, job in POSTS:
            body = "&".join(f"{k}={v}" for k, v in fields.items())
            bodyf = work / "body"
            bodyf.write_text(body)
            env = base | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=" + action, "HTTP_X_VWARD_REQUEST": "console",
                          "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body))}
            # stdin carries the form: run through a tiny wrapper inside the chroot.
            (root / "tmp/body").write_text(body)
            cmd_env = env | {"VWARD_MEASURE_BODY": "/tmp/body"}
            r = one_post(root, work, label, cmd_env, job)
            report["post"][label] = r
    finally:
        for p in audit.pids(audit.DAEMONS):
            try:
                os.kill(p, 9)
            except OSError:
                pass
        time.sleep(0.5)
        subprocess.run(["umount", str(root / "opt")])
        subprocess.run(["umount", str(root / "proc")])
        shutil.rmtree(tmp, ignore_errors=True)
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    md = to_markdown(report)
    if a.markdown:
        Path(a.markdown).write_text(md)
    print(md)


def one_post(root, work, label, env, job):
    before = {n: len(log_lines(root, n)) for n in ("config-reads.log", "ndmc-all.log", "rci.log", "ndmc-changes.log")}
    trace = work / f"p-{abs(hash(label))}.trace"
    t0 = time.monotonic()
    cmd = f"{CGI} < /tmp/body"
    r = audit.sh(root, cmd, env, trace=trace, timeout=300)
    wall = time.monotonic() - t0
    s = audit.parse(trace, root)
    jwait = wait_jobs(root) if job else None
    after = {n: log_lines(root, n)[before[n]:] for n in before}
    m = {"execs": s["execs"], "runcfg": len(after["config-reads.log"]), "ndmc": len(after["ndmc-all.log"]), "rci": len(after["rci.log"]),
         "changes": len(after["ndmc-changes.log"]), "wall_ms": round(wall * 1000), "job_s_here": jwait, "opt_ops": s["opt_ops"],
         "top": sorted(s["programs"].items(), key=lambda x: -x[1])[:6], "answer": r.stdout.split("\n\n", 1)[-1].strip()[:300]}
    m["estimate_s"] = round(m["execs"] * PROC_MS / 1000 + m["runcfg"] * RUNCFG_S + max(0, m["ndmc"] - m["runcfg"]) * NDMC_S + m["rci"] * RCI_S, 1)
    return m


def to_markdown(r):
    out = [f"## Панель VWARD {r['version']}: стоимость запросов на эмуляторе", "",
           f"Оценка для Keenetic: процессы × {PROC_MS} мс + show running-config × {RUNCFG_S} с + прочие ndmc × {NDMC_S} с + RCI × {RCI_S} с.", "",
           "| Страница | запросов | холодная: самый долгий / сумма, с | тёплая: самый долгий / сумма, с | самый долгий запрос |", "|---|---:|---:|---:|---|"]
    for p, v in r["pages"].items():
        out.append(f"| {p} | {v['requests']} | {v['cold_max_s']} / {v['cold_sum_s']} | {v['warm_max_s']} / {v['warm_sum_s']} | {v['slowest']} |")
    out += ["", "| Запрос (GET) | холодный: процессов / runcfg / ndmc / RCI → оценка, с | тёплый: процессов / runcfg / ndmc / RCI → оценка, с | здесь, мс |", "|---|---|---|---:|"]
    for q, v in r["get"].items():
        c, w = v["cold"], v["warm"]
        out.append(f"| {q} | {c['execs']} / {c['runcfg']} / {c['ndmc']} / {c['rci']} → {c['estimate_s']} | {w['execs']} / {w['runcfg']} / {w['ndmc']} / {w['rci']} → {w['estimate_s']} | {w['wall_ms']} |")
    out += ["", "| Тумблер / кнопка (POST) | процессов | runcfg | ndmc | RCI | изменений ndm | оценка ответа, с | фон здесь, с | ответ |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for label, m in r["post"].items():
        ans = m["answer"].replace("|", "\\|")[:80]
        out.append(f"| {label} | {m['execs']} | {m['runcfg']} | {m['ndmc']} | {m['rci']} | {m['changes']} | {m['estimate_s']} | {m['job_s_here'] if m['job_s_here'] is not None else '—'} | {ans} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
