#!/usr/bin/env python3
"""Actual installed-style console entrypoint reaches common coordinator, no nested CLI."""
import shutil
from live_fixture import LiveFixture,LIBDIR,ROOT

with LiveFixture() as f:
    (f.live/'decision/bindings.tsv').write_text('')
    lib=f.prefix/'opt/lib/vward';lib.mkdir(parents=True)
    for source in LIBDIR.glob('*.sh'):
        dest=lib/source.name;shutil.copy2(source,dest);dest.chmod(0o644)
    shutil.copy2(ROOT/'config/runtime/routing-capabilities.tsv',lib/'routing-capabilities.tsv')
    assert (lib/'routing-capabilities.tsv').read_bytes()==b'routing-runtime\t2\n'
    (lib/'routing-capabilities.tsv').chmod(0o644)
    binpath=f.prefix/'opt/bin';binpath.mkdir()
    cli=binpath/'vward-console-config.sh';shutil.copy2(ROOT/'components/console/scripts/vward-console-config.sh',cli);cli.chmod(0o755)
    f.console_path=cli
    f.env|={'VWARD_PROFILE_LIB':str(lib/'vward-device-profile.sh'),'VWARD_ADMISSION_LIB':str(lib/'vward-runtime-admission.sh')}
    r=f.console('service','on','svc','Wireguard1')
    assert r.returncode==0 and 'result=changed' in r.stdout,('real CLI did not reach common writer',r.returncode,r.stdout,r.stderr)
    assert '\tvpn\tVPN:Wireguard1\tdefault\t' in (f.live/'decision/choices.tsv').read_text()
    assert (f.etc/'services/enabled.tsv').read_text().rstrip().endswith('\tWireguard1')
    assert ' Wireguard1 auto' in f.native.read_text() and f.startup.read_bytes()==f.native.read_bytes()
    journals=[p for p in (f.live/'journal').iterdir() if not p.name.startswith('.')]
    assert journals and all((p/'state').read_text()=='committed\n' for p in journals)
    assert not list((f.prefix/'opt/var/backups/vward/console-config/service-transactions').glob('*/pending')),'outer CLI used old transaction/child CLI'
    r=f.console('service','off','svc');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert 'object-group fqdn domain-list' not in f.native.read_text()
    assert '\tauto\t-\t-\t' in (f.live/'decision/choices.tsv').read_text()
    before=f.native.read_bytes()
    r=f.console('service','on','svc','Wireguard77')
    assert r.returncode!=0 and f.native.read_bytes()==before,'missing explicit tunnel silently became provider'
    choices=f.live/'decision/choices.tsv';original=choices.read_bytes()
    for mode,target,dns in (('dns','ISP','policy1'),('isp','ISP','default')):
        choices.write_text(f'schema\t1\nservice\tsvc\t7\t{mode}\t{target}\t{dns}\t7\n')
        selected=choices.read_bytes();calls=f.calls.read_text()
        r=f.console('service','off','svc')
        assert r.returncode==0 and 'result=unchanged' in r.stdout and choices.read_bytes()==selected and f.native.read_bytes()==before and f.calls.read_text()==calls,('off erased other intent or probed a backend',mode,r.returncode,r.stdout,r.stderr)
    choices.write_bytes(original)
    for corruption in ('missing-capsule','wrong-abi','missing-code'):
        capsule=lib/'routing-capabilities.tsv'
        if corruption=='missing-capsule':capsule.unlink()
        elif corruption=='wrong-abi':capsule.write_text('routing-runtime\t9999\n')
        else:
            capsule.write_text('routing-runtime\t2\n');(lib/'vward-routing-live-agh.sh').unlink()
        calls=f.calls.read_text()
        r=f.console('service','on','svc','Wireguard0')
        assert r.returncode==75 and f.native.read_bytes()==before and f.calls.read_text()==calls,('incomplete deployment fell back to legacy mutation',corruption,r.returncode,r.stdout,r.stderr)
print('LIVE_CONSOLE_ENTRY=PASS actual copied CLI/profile/libs -> common J2/native/registry/save/off; no old child transaction, missing tunnel refusal')
