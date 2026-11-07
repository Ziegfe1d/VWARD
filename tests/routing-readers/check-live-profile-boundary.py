#!/usr/bin/env python3
"""Common service entry preserves the existing profile trust/WAN boundary."""
from live_fixture import LiveFixture

fail=[]
for scenario in ('writable-profile','wan-interface','readonly-profile'):
    with LiveFixture() as f:
        (f.live/'decision/bindings.tsv').write_text('')
        f.install_console()
        # The actual ordinary off installs the same valid fixture profile as
        # other console tests, without starting a route or probing a backend.
        r=f.console('service','off','svc');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        if scenario=='writable-profile':
            (f.etc/'device.conf').chmod(0o666)
            target='Wireguard0'
        elif scenario=='readonly-profile':
            (f.etc/'device.conf').chmod(0o400)
            target='Wireguard0'
        else:
            # Provider PPTP/L2TP still is WAN, even when its kernel-device
            # setting is stale. NDM interface identity must independently win.
            device_map=f.prefix/'tmp/vward-device-map.tsv'
            rows=[row for row in device_map.read_text().splitlines() if '\tGigabitEthernet1\t' not in row]
            device_map.write_text('\n'.join(rows)+'\nI\tGigabitEthernet1\tPptp\tppp0\tpublic\n')
            f.native.write_text(f.native.read_text()+'interface GigabitEthernet1\n!\n')
            target='GigabitEthernet1'
        before=f.native.read_bytes();choices=(f.live/'decision/choices.tsv').read_bytes()
        r=f.console('service','on','svc',target,preserve_profile=True)
        if scenario=='readonly-profile':
            assert r.returncode==0 and ' Wireguard0 auto' in f.native.read_text(),('valid private0400 was refused',r.returncode,r.stdout,r.stderr)
            continue
        if not (r.returncode!=0 and f.native.read_bytes()==before and (f.live/'decision/choices.tsv').read_bytes()==choices):
            fail.append((scenario,r.returncode,r.stdout,r.stderr))
        if scenario=='wan-interface' and '\tshow interface GigabitEthernet1\n' in f.calls.read_text():
            fail.append((scenario,'WAN was queried as a VPN candidate'))
assert not fail,fail
print('LIVE_PROFILE_BOUNDARY=PASS writable profile refuses; provider WAN excluded by NDM identity despite stale kernel-device setting')
