#!/usr/bin/env python3
"""Exercise the Keenetic trial and rollback against a local synthetic CLI."""

import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOMAINS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com",
           "ytimg.com", "ggpht.com", "instagram.com", "cdninstagram.com")
OLD = sorted(f"ip name-server {ip} {d} on OpkgTun0" for ip in ("1.1.1.1", "8.8.8.8") for d in DOMAINS)
BUSYBOX = shutil.which("busybox")
SHELL = [BUSYBOX, "sh"] if BUSYBOX else ["sh"]

with tempfile.TemporaryDirectory() as temp:
    fake = Path(temp)
    (fake / "tmp").mkdir()
    profile = fake / "profile.sh"
    profile.write_text(
        'vward_profile_load() { VWARD_TUNNEL_INTERFACE=OpkgTun0; VWARD_TUNNEL_DEVICE=opkgtun0; '
        'VWARD_LAN_ADDRESS=${PILOT_LAN_ADDRESS:-192.168.1.1}; }\n'
        'vward_valid_ipv4() { case "$1" in 192.168.1.1|192.168.2.1|127.0.0.1) return 0 ;; esac; return 1; }\n'
    )
    state, live = fake / "state", fake / "live"
    ndmc = fake / "ndmc"
    ndmc.write_text(r"""#!/usr/bin/env python3
import os, sys
from pathlib import Path
d = Path(os.environ['PILOT_FIXTURE'])
state = d / 'state'
rules = set(state.read_text().splitlines())
cmd = sys.argv[2]
if cmd == 'show running-config':
    print('interface OpkgTun0\n!')
    print('\n'.join(sorted(rules)))
    sys.exit()
with (d / 'mutations').open('a') as stream:
    print(cmd, file=stream)
if cmd.startswith('ip name-server 127.0.0.1:65153 '):
    print('Dns::Manager error[22544486]: invalid IP address: 127.0.0.1.')
    sys.exit(122)
if os.environ.get('PILOT_REJECT_ATTACHMENT') == '1' and cmd.startswith('ip name-server 192.168.1.1:65153 '):
    print('Command::Base error: attachment refused by fixture')
    sys.exit(0)
if cmd.startswith('no ip name-server '):
    rules.discard(cmd[3:])
else:
    assert cmd.startswith('ip name-server '), cmd
    rules.add(cmd)
state.write_text(''.join(f'{rule}\n' for rule in sorted(rules)))
local = [r for r in rules if ':65153 ' in r]
target = 'ip name-server 1.1.1.1 cdninstagram.com on OpkgTun0'
lost = d / 'lost-live-rule'
if cmd == target:
    if local and os.environ.get('PILOT_DROP_DURING_RESTORE') == '1':
        lost.touch()
    elif not local and os.environ.get('PILOT_DROP_PERSISTS') != '1':
        lost.unlink(missing_ok=True)
active = [r.split()[2:4] for r in sorted(rules) if r != target or not lost.exists()]
(d / 'live').write_text('dns_server = 192.0.2.53:53 .\n' +
                       ''.join(f'dns_server = {ip if ":" in ip else ip + ":53"} {name}.\n' for ip, name in active))
if os.environ.get('PILOT_LOST_ATTACHMENT_REPLY') == '1' and cmd == 'ip name-server 192.168.1.1:65153 ggpht.com':
    sys.exit(1)
if os.environ.get('PILOT_STALE_ATTACHMENT') == '1' and cmd == 'no ip name-server 192.168.1.1:65153 ytimg.com':
    with (d / 'live').open('a') as stream:
        print('dns_server = 192.168.1.1:65153 ytimg.com.', file=stream)
if os.environ.get('PILOT_LOST_REPLY') == '1' and cmd == 'no ip name-server 1.1.1.1 cdninstagram.com on OpkgTun0':
    sys.exit(1)
""")
    binary = fake / "vward-dns"
    binary.write_text(f"""#!/bin/sh
case "$1:$3" in
    domains:) printf '%s\n' {' '.join(DOMAINS)} ;;
    probe:53) [ "${{PILOT_BAD_PROBE:-0}}" != 1 ] || exit 1
              [ "${{PILOT_CACHE_ONLY:-0}}" = 1 ] || echo yes > "$PILOT_FIXTURE/forwarded" ;;
    probe:65153) [ -z "$4" ] || [ "$4:$5" = '-address:192.168.1.1' ] ;;
    health:65153) [ -z "$4" ] || [ "$4:$5" = '-address:192.168.1.1' ] || exit 1
                 if [ -s "$PILOT_FIXTURE/forwarded" ]; then echo '2 2'; else echo '1 1'; fi ;;
    *) exit 1 ;;
esac
""")
    for cmd in (ndmc, binary):
        cmd.chmod(0o700)
    env = os.environ | {
        "PILOT_FIXTURE": temp, "VWARD_ROOT_PREFIX": temp, "VWARD_PROFILE_LIB": str(profile),
        "VWARD_DNS_BIN": str(binary), "VWARD_NDMC": str(ndmc),
        "VWARD_NDNPROXY_CONF": str(live), "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    pending = fake / "opt/var/lib/vward/dns-pilot/pending"

    # Keenetic's shell has awk but no comm applet.
    invoke = 'comm() { echo "comm: not found" >&2; return 127; }; . "$0"'
    pilot = SHELL + ["-c", invoke, str(HERE / "pilot.sh")]

    def call(action, **settings):
        return subprocess.run(pilot + [action], env=env | settings, text=True, capture_output=True, timeout=60)

    def set_rules(rules):
        state.write_text("".join(f"{rule}\n" for rule in rules))
        entries = [r.split()[2:4] for r in sorted(rules)]
        live.write_text("dns_server = 192.0.2.53:53 .\n" +
                        "".join(f"dns_server = {ip} {name}\n" for ip, name in entries))

    def assert_restored(expected=OLD):
        assert sorted(state.read_text().splitlines()) == expected
        assert live.read_text().splitlines()[0] == "dns_server = 192.0.2.53:53 ."
        active = sorted(f"ip name-server {server.removesuffix(':53')} {name.rstrip('.')} on OpkgTun0"
                        for _, _, server, name in map(str.split, live.read_text().splitlines()[1:]))
        assert active == expected, active
        assert not pending.exists()

    set_rules([])
    result = call("plan")
    assert result.returncode == 0 and "current_rules=0 active_rules=0" in result.stdout, result
    assert not (fake / "mutations").exists(), "planning wrote the router"
    result = call("trial", VWARD_DNS_PILOT_HOLD_SECONDS="181")
    assert result.returncode and "invalid_hold_seconds" in result.stderr, result
    assert not (fake / "mutations").exists()
    for unverified in ("", "dns_server =\n", "dns_server = 9.9.9.9:53 *.www.youtube.com.\n"):
        live.write_text(unverified)
        result = call("trial")
        assert result.returncode and "live_rules_unverified" in result.stderr, result
        assert not (fake / "mutations").exists(), "pilot changed an unverified baseline"
    set_rules(OLD[:1])
    result = call("plan")
    assert result.returncode and "dns_scope_differs_from_expected" in result.stderr, result
    set_rules(OLD)
    result = call("plan")
    assert result.returncode == 0 and "plan_ready" in result.stdout, result
    assert not (fake / "mutations").exists(), "planning wrote the router"
    state.write_text(state.read_text() + "ip name-server 9.9.9.9 www.youtube.com\n")
    result = call("trial")
    assert result.returncode and "dns_scope_differs_from_expected" in result.stderr, result
    assert not (fake / "mutations").exists(), "pilot touched a foreign DNS rule"
    set_rules(OLD)

    # A correct running-config can coexist with only one active DNS rule.
    live.write_text("dns_server = 8.8.8.8 youtube.com\n")
    result = call("plan")
    assert result.returncode and "live_rules_unverified" in result.stderr, result
    result = call("trial")
    assert result.returncode and "live_rules_unverified" in result.stderr, result
    assert not (fake / "mutations").exists(), "an unverified live baseline was changed"
    set_rules(OLD)

    result = call("trial")
    assert (result.returncode == 0 and "result=trial_verified" in result.stdout
            and "result=original_dns_configuration_restored" in result.stdout), result
    assert_restored()

    # The current Viva baseline contains no old media rules. Rejection and
    # recovery must never bring those old rules back.
    for settings, marker in (({}, "trial_verified"),
                             ({"PILOT_LOST_ATTACHMENT_REPLY": "1"}, "attach_failed")):
        (fake / "forwarded").unlink(missing_ok=True)
        (fake / "mutations").unlink()
        set_rules([])
        result = call("trial", **settings)
        assert (result.returncode == bool(settings) and marker in result.stdout + result.stderr
                and "original_dns_configuration_restored" in result.stdout), result
        assert_restored([])
        assert all(":65153 " in line for line in (fake / "mutations").read_text().splitlines())

    (fake / "forwarded").unlink(missing_ok=True)
    result = call("trial", PILOT_STALE_ATTACHMENT="1")
    assert result.returncode and "dns_restore_unverified" in result.stderr, result
    assert pending.read_text() == "pilot_address=192.168.1.1\n"
    set_rules([])
    result = call("restore")
    assert result.returncode == 0, result
    assert_restored([])

    pending.write_text("pilot_address=192.168.1.1\n" + OLD[0] + "\n")
    result = call("restore")
    assert result.returncode and "invalid_recovery_record" in result.stderr, result
    pending.write_text("pilot_address=192.168.1.1\n")
    set_rules(["ip name-server 192.168.1.1:65153 cdninstagram.com"])
    result = call("restore", PILOT_LAN_ADDRESS="192.168.2.1")
    assert result.returncode == 0, result
    assert_restored([])

    (fake / "forwarded").unlink(missing_ok=True)
    with subprocess.Popen(pilot + ["trial"], env=env | {"VWARD_DNS_PILOT_HOLD_SECONDS": "90"},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            # The binary fixture emits nothing before this pair of shell writes.
            assert select.select([process.stdout], [], [], 12)[0], "trial never reached the hold"
            assert process.stdout.readline() == b"result=trial_verified\n"
            assert process.stdout.readline() == b"result=trial_hold seconds=90\n"
            assert len(state.read_text().splitlines()) == 8 and pending.exists()
            process.terminate()
            output, errors = process.communicate(timeout=12)
            assert process.returncode == 130 and b"original_dns_configuration_restored" in output, (output, errors)
        finally:
            if process.poll() is None:
                process.kill()
    assert_restored([])
    set_rules(OLD)

    (fake / "forwarded").unlink(missing_ok=True)
    result = call("trial", PILOT_REJECT_ATTACHMENT="1")
    assert result.returncode and "attach_failed" in result.stderr, result
    assert "ndmc_failed rc=0 command=ip name-server 192.168.1.1:65153 " in result.stderr, result
    assert "attachment refused by fixture" in result.stderr, result
    assert_restored()

    (fake / "forwarded").unlink(missing_ok=True)
    result = call("trial", PILOT_DROP_DURING_RESTORE="1")
    assert result.returncode == 0 and "original_dns_configuration_restored" in result.stdout, result
    assert not (fake / "lost-live-rule").exists(), "rollback left a configured rule inactive"
    assert_restored()

    (fake / "forwarded").unlink(missing_ok=True)
    result = call("trial", PILOT_DROP_DURING_RESTORE="1", PILOT_DROP_PERSISTS="1")
    assert result.returncode and "dns_restore_unverified" in result.stderr, result
    assert "original_dns_configuration_restored" not in result.stdout and pending.exists(), result
    result = call("restore")
    assert result.returncode == 0, result
    assert not (fake / "lost-live-rule").exists(), "manual recovery did not restore live DNS"
    assert_restored()
    (fake / "forwarded").unlink(missing_ok=True)
    result = call("trial", PILOT_LOST_REPLY="1")
    assert result.returncode and "attach_failed" in result.stderr, result
    assert_restored()
    result = call("trial", PILOT_BAD_PROBE="1")
    assert result.returncode and "keenetic_probe_failed" in result.stderr, result
    assert_restored()
    result = call("trial", PILOT_CACHE_ONLY="1")
    assert result.returncode and "queries_not_seen_by_vward_dns" in result.stderr, result
    assert_restored()

    # A detached recovery has the same effect if the shell was killed before cleanup.
    pending.write_text("\n".join(OLD) + "\n")
    set_rules([*OLD[1:], "ip name-server 127.0.0.1:65153 cdninstagram.com"])
    result = call("restore")
    assert result.returncode == 0, result
    assert_restored()

    # The address recorded before a trial remains the scope of a detached recovery.
    pending.write_text("pilot_address=192.168.1.1\n" + "\n".join(OLD) + "\n")
    set_rules([*OLD[1:], "ip name-server 192.168.1.1:65153 cdninstagram.com"])
    result = call("restore", PILOT_LAN_ADDRESS="192.168.2.1")
    assert result.returncode == 0, result
    assert_restored()

print("VWARD_DNS_PILOT=PASS")
