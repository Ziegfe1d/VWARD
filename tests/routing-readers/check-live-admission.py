#!/usr/bin/env python3
"""Old native commands cannot bypass an accepted common choice or persistent J2 barrier."""
from pathlib import Path
import shlex
from fixture import PipelineFixture, digest

GUARD = Path(__file__).resolve().parents[2] / 'components/runtime/lib/vward-routing-admission.sh'
with PipelineFixture() as f:
    r = f.invoke('vward_routing_pipeline2', f.j, 'isp-pin', 'svc', 'isp', 'ISP', 'default', 0)
    assert r.returncode == 0, (r.stdout, r.stderr)
    with (f.e / 'running.cfg').open('a') as out:
        out.write('object-group fqdn Shared\n    include x.example\n    include outside.example\n!\n')
        out.write('object-group fqdn Other\n\tinclude outside.example  \t\n!\n')
    stage = f.p / 'live-admission-stage'
    r = f.run(f.script('vrb_envelope "$1" snapshot || exit $?; mkdir "$2" || exit $?; '
                      'cp "$vrb_e/running.cfg" "$vrb_e/running-config" || exit $?; '
                      'vward_routing_consistent_read2 "$2" "$vrb_e/decision"'), *f.libs, f.j, stage)
    assert r.returncode == 0, (r.stdout, r.stderr)
    native = (f.e / 'running.cfg').read_bytes()
    before = digest(f.decision)

    def gate(command):
        return f.run(f.script('. ' + shlex.quote(str(GUARD)) + '\n'
                              'vward_routing_legacy_command_gate "$@"'), *f.libs, stage, f.j, command)

    for command, expected in (
        ('show running-config', 0),
        ('object-group fqdn Other include outside.example', 0),
        ('object-group fqdn Other include x.example', 75),
        ('no object-group fqdn Other include x.example', 75),
        ('no object-group fqdn Shared', 75),
        ('dns-proxy route object-group Shared Wireguard1 auto', 75),
        ('dns-proxy no route object-group Shared Wireguard0 auto', 75),
        ('ip name-server 192.0.2.53:65053 x.example', 75),
        ('no ip name-server 192.0.2.53 domain x.example', 75),
        ('dns-proxy https upstream https://neutral.example.test/dns-query domain x.example', 75),
        ('dns-proxy no https upstream https://neutral.example.test/dns-query', 75),
        ('dns-proxy no https upstream https://neutral.example.test/dns-query domain outside.example', 75),
        ('object-group fqdn Other unsupported body', 75),
        ('system configuration save', 0),
        ('interface WifiMaster0/AccessPoint0 up', 0),
    ):
        r = gate(command)
        assert r.returncode == expected, (command, expected, r.returncode, r.stdout, r.stderr)
    assert (f.e / 'running.cfg').read_bytes() == native and digest(f.decision) == before
    assert not f.trace.exists(), 'eligibility invoked real ndmc/curl instead of refusing before transport'
    # Malformed scope never becomes a shell program or an unguarded native command.
    r = gate('object-group fqdn Other include x.example; echo injected')
    assert r.returncode != 0 and not f.trace.exists()
    # A durable unknown blocks unrelated writes/save too, but keeps diagnostics readable.
    (f.e / 'save-fails').touch()
    (f.e / 'running.cfg').write_bytes(native[:native.index(b'object-group fqdn Shared')])
    r = f.invoke('vward_routing_pipeline2', f.j, 'unknown', 'svc', 'vpn', 'VPN:Wireguard0', 'default', 1)
    assert r.returncode == 3, (r.stdout, r.stderr)
    for command, expected in (('object-group fqdn Other include outside.example', 75),
                              ('system configuration save', 75), ('show running-config', 0)):
        r = gate(command)
        assert r.returncode == expected, (command, r.returncode, r.stdout, r.stderr)
print('LIVE_LEGACY_ADMISSION=PASS explicit pin + native domains/group scopes + persistent unknown; no write')
