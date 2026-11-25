#!/usr/bin/env python3
"""Exercise the Keenetic trial and rollback against a local synthetic CLI."""

import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOMAINS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com",
           "ytimg.com", "ggpht.com", "instagram.com", "cdninstagram.com")
OLD = sorted(f"ip name-server {ip} {d} on OpkgTun0" for ip in ("1.1.1.1", "8.8.8.8") for d in DOMAINS)

with tempfile.TemporaryDirectory() as temp:
    fake = Path(temp)
    (fake / "tmp").mkdir()
    profile = fake / "profile.sh"
    profile.write_text("vward_profile_load() { VWARD_TUNNEL_INTERFACE=OpkgTun0; VWARD_TUNNEL_DEVICE=opkgtun0; }\n")
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
if cmd.startswith('no ip name-server '):
    rules.discard(cmd[3:])
else:
    assert cmd.startswith('ip name-server '), cmd
    rules.add(cmd)
state.write_text('\n'.join(sorted(rules)) + '\n')
local = [r.split()[2:4] for r in rules if r.startswith('ip name-server 127.0.0.1:65153 ')]
(d / 'live').write_text(''.join(f'dns_server = {ip} {name}\n' for ip, name in local))
if os.environ.get('PILOT_LOST_REPLY') == '1' and cmd == 'no ip name-server 1.1.1.1 cdninstagram.com on OpkgTun0':
    sys.exit(1)
""")
    binary = fake / "vward-dns"
    binary.write_text(f"""#!/bin/sh
case "$1:$3" in
    domains:) printf '%s\n' {' '.join(DOMAINS)} ;;
    probe:53) [ "${{PILOT_BAD_PROBE:-0}}" != 1 ] || exit 1
              [ "${{PILOT_CACHE_ONLY:-0}}" = 1 ] || echo yes > "$PILOT_FIXTURE/forwarded" ;;
    probe:65153) exit 0 ;;
    health:65153) if [ -s "$PILOT_FIXTURE/forwarded" ]; then echo '2 2'; else echo '1 1'; fi ;;
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

    def call(action, **settings):
        return subprocess.run(["sh", str(HERE / "pilot.sh"), action], env=env | settings,
                              text=True, capture_output=True, timeout=60)

    def assert_restored():
        assert sorted(state.read_text().splitlines()) == OLD
        assert not pending.exists()

    state.write_text("\n".join(OLD) + "\n")
    result = call("plan")
    assert result.returncode == 0 and "plan_ready" in result.stdout, result
    assert not (fake / "mutations").exists(), "planning wrote the router"
    state.write_text(state.read_text() + "ip name-server 9.9.9.9 www.youtube.com\n")
    result = call("trial")
    assert result.returncode and "dns_scope_differs_from_expected" in result.stderr, result
    assert not (fake / "mutations").exists(), "pilot touched a foreign DNS rule"
    state.write_text("\n".join(OLD) + "\n")

    result = call("trial")
    assert (result.returncode == 0 and "result=trial_verified" in result.stdout
            and "result=original_dns_configuration_restored" in result.stdout), result
    assert_restored()
    (fake / "forwarded").unlink()
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
    state.write_text("\n".join([*OLD[1:], "ip name-server 127.0.0.1:65153 cdninstagram.com"]) + "\n")
    result = call("restore")
    assert result.returncode == 0, result
    assert_restored()

print("VWARD_DNS_PILOT=PASS")
