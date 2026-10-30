"""Real console writer with a stateful Keenetic transport; no admission bypass."""
import ast
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'components/console/scripts/vward-console-config.sh'
tree = ast.parse((Path(__file__).with_name('check-console-services.py')).read_text())
constants = {n.targets[0].id: n.value for n in tree.body if isinstance(n, ast.Assign)}
FAKE = ast.literal_eval(constants['FAKE_NDMC'])
DEVICE = ast.literal_eval(constants['DEVICE_CONF'])


class Services:
    def __init__(self, tmp):
        self.tmp = tmp
        self.cfg = tmp / 'running.cfg'
        self.cfg.write_text('interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n!\n')
        self.etc = tmp / 'etc'
        (self.etc / 'services').mkdir(parents=True)
        self.state = self.etc / 'services/enabled.tsv'
        self.cat = tmp / 'catalog.json'
        self.served = tmp / 'served.json'
        self.catalog = {'schema': 1, 'source': 'fixture', 'limit': 300,
                        'categories': [{'id': 'ai', 'title': 'AI'}],
                        'services': [{'id': 'claude.ai', 'title': 'Claude', 'category': 'ai',
                                      'domains': ['anthropic.com', 'claude.ai', 'claude.com']}]}
        self.cat.write_text(json.dumps(self.catalog))
        ndmc = tmp / 'ndmc'
        fake = FAKE.replace('@CFG@', str(self.cfg))
        fake = fake.replace('text = cfg.read_text()', '''
reject = Path(str(cfg) + '.reject')
if reject.exists() and reject.read_text().strip() in cmd:
    reject.unlink(); print('error: refused'); sys.exit(0)
always = Path(str(cfg) + '.reject-always')
if always.exists() and always.read_text().strip() in cmd:
    print('error: refused'); sys.exit(0)
text = cfg.read_text()''')
        fake = fake.replace('if cmd == "system configuration save":', '''
edit = Path(str(cfg) + '.edit-on-save')
if edit.exists() and cmd == 'system configuration save':
    edit.unlink()
    cfg.write_text(cfg.read_text().replace('    include claude.ai\\n', '    include claude.ai\\n    include owner.example\\n'))
if cmd == "system configuration save":'''.replace('\n+', '\n'))
        fake = fake.replace('text = cfg.read_text()', '''
snap = Path(str(cfg) + '.snapshot-edit')
if snap.exists() and cmd == 'show running-config':
    left = int(snap.read_text()) - 1
    if left:
        snap.write_text(str(left))
    else:
        snap.unlink()
        cfg.write_text(cfg.read_text().replace('domain-list0 Wireguard0', 'domain-list0 ISP'))
text = cfg.read_text()'''.replace('\n+', '\n'))
        fake = fake.replace('print("ok"); sys.exit(0)', "print('error: reply lost' if Path(str(cfg) + '.applied-error').exists() and Path(str(cfg) + '.applied-error').read_text() in cmd else 'ok'); sys.exit(0)")
        ndmc.write_text(fake)
        ndmc.chmod(0o755)
        curl = tmp / 'curl'
        curl.write_text('#!/bin/sh\nout=\nwhile [ $# -gt 0 ]; do [ "$1" != -o ] || out=$2; shift; done\n'
                        'cp "' + str(self.served) + '" "$out" || exit 22\nprintf 200\n')
        curl.chmod(0o755)
        dev = tmp / 'device.conf'
        dev.write_text(DEVICE)
        dev.chmod(0o600)
        (tmp / 'root/tmp').mkdir(parents=True)
        self.env = os.environ | {
            'VWARD_NDMC': str(ndmc), 'VWARD_CURL_BIN': str(curl),
            'VWARD_DEVICE_CONFIG': str(dev), 'VWARD_DEVICE_CONFIG_OWNER_UID': str(os.getuid()),
            'VWARD_PROFILE_LIB': str(ROOT / 'components/runtime/lib/vward-device-profile.sh'),
            'VWARD_ADMISSION_LIB': str(ROOT / 'components/runtime/lib/vward-runtime-admission.sh'),
            'VWARD_ROOT_PREFIX': str(tmp / 'root'), 'VWARD_ROUTE_CHANGE_LOCK': str(tmp / 'change.lock'),
            'VWARD_CONSOLE_EDIT_LOCK': str(tmp / 'edit.lock'),
            'VWARD_ROUTE_STATE': str(tmp / 'route'), 'VWARD_CONSOLE_ETC': str(self.etc),
            'VWARD_CONSOLE_BACKUP_DIR': str(tmp / 'backup'), 'VWARD_CONSOLE_AUDIT_LOG': str(tmp / 'audit.log'),
            'VWARD_ADGUARD_CONFIG': str(tmp / 'no-agh.yaml'),
            'VWARD_ADS_CONTROL_BIN': str(tmp / 'no-ads'),
            'VWARD_SERVICES_BUNDLED': str(self.cat), 'VWARD_SERVICES_FETCHED': str(tmp / 'fetched.json'),
            'VWARD_SERVICES_URL': 'https://example.invalid/catalog.json',
            'VWARD_DEVICE_MAP_CACHE': str(tmp / 'map'), 'VWARD_SYSFS_NET': str(tmp / 'sys'),
        }

    def run(self, *args, **env):
        return subprocess.run(['sh', str(HELPER), *args], env=self.env | env,
                              capture_output=True, text=True, timeout=45)

    def foreign(self):
        self.cfg.write_text(self.cfg.read_text().replace('dns-proxy\n',
            'dns-proxy\n    route object-group domain-list7 ISP auto\n') +
            'object-group fqdn domain-list7\n    description "Claude"\n'
            '    include claude.ai\n    include user.example\n!\n')

    def enabled(self, group='domain-list7', pin='auto'):
        self.state.write_text('claude.ai\t' + group + '\t' + pin + '\n')

    def reject(self, command, always=False):
        Path(str(self.cfg) + ('.reject-always' if always else '.reject')).write_text(command)
