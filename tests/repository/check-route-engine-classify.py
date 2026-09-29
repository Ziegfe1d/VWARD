#!/usr/bin/env python3
"""The live path checks a DNS name against every list in one awk pass."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(msg):
    print(f"ROUTE_ENGINE_CLASSIFY=FAIL: {msg}")
    sys.exit(1)


fn = ENGINE[ENGINE.index("classify_host()\n"):ENGINE.index("# HINT / PRELOAD V5")].rsplit("# ----", 1)[0]
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    files = {
        "LIST_WATCH_MAP": "youtube.com domain-list3\nnetflix.com domain-list5\n",
        "MANUAL": "Example.org\n  *.wild.net  \n# comment.com\n\n",
        "SMARTDNS": "claude.ai\n",
        "SKIP_DOMAINS": "skip.me\n*.sub.skip\n",
        "HINTS": "googlevideo.com\nexample.org\n",
    }
    env = {"PATH": "/usr/bin:/bin"}
    for name, body in files.items():
        (tmp / name).write_text(body)
        env[name] = str(tmp / name)
    cases = {
        "www.youtube.com": ["W domain-list3"],
        "youtube.com.evil": [],
        "example.org": ["M", "H"],
        "a.example.org": ["M", "H"],
        "wild.net": [],
        "x.wild.net": ["M"],
        "api.claude.ai": ["S"],
        "skip.me": ["K"],
        "sub.skip": [],
        "a.sub.skip": ["K"],
        "r1.googlevideo.com": ["H"],
        "comment.com": [],
        "other.com": [],
    }
    for shell in shells:
        for host, want in cases.items():
            r = subprocess.run(shell + ["-c", fn + '\nclassify_host "$1"', "x", host], env=env, text=True, capture_output=True)
            got = r.stdout.split("\n")[:-1] if r.stdout else []
            if r.returncode != 0 or got != want:
                fail(f"{shell[0]}: {host}: {got} {r.stderr.strip()}, want {want}")
    # The resident classifier (one awk holding the lists) answers the same, in one shell;
    # a list that changes restarts it; a dead one leaves the name to the scan, then restarts.
    script = fn + '''
VOLATILE_DIR="$1"; shift
for h in "$@"; do classifier_check; printf '%s=' "$h"; classify_host "$h" | tr '\\n' ','; echo; done
echo "pid=$CLS_PID"
echo "extra.example" >> "$MANUAL"; sleep 1; touch "$MANUAL"
classifier_check; printf 'extra=%s\\n' "$(classify_host a.extra.example | tr '\\n' ',')"
kill "$CLS_PID"; sleep 0.3
printf 'dead=%s\\n' "$(classify_host x.wild.net | tr '\\n' ',')"
classifier_check; printf 'again=%s ready=%s\\n' "$(classify_host r1.googlevideo.com | tr '\\n' ',')" "$CLS_READY"
classifier_stop
'''
    for shell in shells:
        (tmp / "MANUAL").write_text(files["MANUAL"])
        vol = tmp / f"vol-{shell[0]}"
        r = subprocess.run(shell + ["-c", script, "x", str(vol), *cases], env=env, text=True, capture_output=True, timeout=60)
        lines = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        for host, want in cases.items():
            if lines.get(host) != "".join(t + "," for t in want):
                fail(f"{shell[0]} resident: {host}: {lines.get(host)!r} want {want} ({r.stderr.strip()[-300:]})")
        if lines.get("extra") != "M," or lines.get("dead") != "M," or not lines.get("again", "").startswith("H, ready=1"):
            fail(f"{shell[0]} resident: restart on a changed list, scan while dead, restart after: {lines}")
    (tmp / "MANUAL").write_text(files["MANUAL"])
    # No lists at all: nothing printed, and awk must not wait on stdin.
    empty = {"PATH": "/usr/bin:/bin"}
    for name in files:
        empty[name] = str(tmp / "missing" / name)
    r = subprocess.run(["sh", "-c", fn + '\nclassify_host a.example'], env=empty, text=True, capture_output=True, stdin=subprocess.PIPE, timeout=10)
    if r.returncode != 0 or r.stdout:
        fail(f"empty lists: {r.stdout!r} {r.stderr!r}")

host = ENGINE[ENGINE.index("handle_host()\n"):]
order = [host.index(x) for x in ('HOST_LISTS=$(classify_host "$HOST")', "*M*|*S*) return", 'if is_adaptive "$HOST"', "*K*) return", 'handle_hint "$HOST"', 'handle_new "$HOST"')]
if order != sorted(order):
    fail("live path order must stay: my domains and Smart DNS, AdaptiveAuto, skip list, hints, new")
if "parent_list_match" in host[:host.index('handle_new "$HOST"')]:
    fail("the live path must not start a process per list")

print("ROUTE_ENGINE_CLASSIFY=PASS")
