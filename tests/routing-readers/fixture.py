"""Shared synthetic native-router fixture for the RS-6 identity/snapshot/shadow checks.

Only files under a temporary directory are touched. Transport binaries are
poisoned so any accidental ndmc/curl call fails the test.
"""
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIBDIR = ROOT / 'components/runtime/lib'
READ, AUDIT = LIBDIR / 'vward-routing-read.sh', LIBDIR / 'vward-routing-audit.sh'
SNAP, SHADOW = LIBDIR / 'vward-routing-snapshot.sh', LIBDIR / 'vward-routing-shadow.sh'
SHELL = [os.environ['RS6_BUSYBOX'], 'ash'] if os.environ.get('RS6_BUSYBOX') else ['sh']

CFG = ('interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n'
       '    route object-group Mine Wireguard0 auto\n'
       '    route object-group domain-list0 Wireguard0 auto\n'
       '    route object-group AdaptiveAuto Wireguard0 auto\n'
       '    https upstream https://dns.example/secret-token domain smart.example\n!\n'
       'object-group fqdn Mine\n    include x.example\n    include smart.example\n!\n'
       'object-group fqdn domain-list0\n    include x.example\n    include s.example\n!\n'
       'object-group fqdn AdaptiveAuto\n    include x.example\n!\n')


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}


class Fixture:
    def __init__(self):
        self._td = tempfile.TemporaryDirectory()
        p = self.p = Path(self._td.name)
        self.etc, self.state, self.cache = p/'etc', p/'state', p/'cache'
        (self.etc/'services/owned').mkdir(parents=True)
        (self.etc/'route-engine/domain-lists').mkdir(parents=True)
        self.state.mkdir(); self.cache.mkdir(); (p/'backup').mkdir()
        self.dev = self.etc/'device.conf'
        self.dev.write_text('VWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_WAN_DEVICE=eth3\n')
        self.cfg = self.cache/'running-config'; self.cfg.write_text(CFG)
        self.map = self.cache/'device-map.tsv'
        self.map.write_text('I\tWireguard0\tWireguard\tnwg0\tprivate\nI\tWireguard1\tWireguard\tnwg1\tprivate\n'
                            'I\tGigabitEthernet1\tGigabitEthernet\teth3\tpublic\n')
        self.enabled = self.etc/'services/enabled.tsv'; self.enabled.write_text('svc\tdomain-list0\tauto\n')
        self.cats = self.etc/'services/categories.tsv'; self.cats.write_text('ai\tWireguard0\n')
        self.catalog = p/'catalog.json'
        self.catalog.write_text('{"schema":1,"services":[{"id":"svc","title":"Service","category":"ai","domains":["x.example","s.example"]},'
                                '{"id":"off","title":"Off","category":"ai","domains":["off.example"]}]}')
        self.persist = self.state/'adaptive-persist.txt'; self.persist.write_text('x.example\na.example\n')
        self.agh = self.cache/'agh-domains'; self.agh.write_text('smart.example\n')
        self.proof = self.etc/'services/owned/domain-list0'
        self.proof.write_text('include s.example\ninclude x.example\nroute=Wireguard0\tauto\n'); self.proof.chmod(0o600)
        self.env = os.environ | {
            'VWARD_CONSOLE_ETC': str(self.etc), 'VWARD_ROUTE_STATE': str(self.state),
            'VWARD_KCACHE': str(self.cache), 'VWARD_DEVICE_CONFIG': str(self.dev),
            'VWARD_DEVICE_MAP_CACHE': str(self.map), 'VWARD_SERVICES_FETCHED': str(self.catalog),
            'VWARD_SERVICES_BUNDLED': str(p/'missing-catalog'), 'VWARD_ROUTING_AGH_DOMAINS': str(self.agh),
            'VWARD_CONSOLE_BACKUP_DIR': str(p/'backup'), 'VWARD_NDMC': '/forbidden/ndmc',
            'VWARD_CURL_BIN': '/forbidden/curl', 'VWARD_ROUTING_CACHE_AGE': '3600'}

    def close(self): self._td.cleanup()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def run(self, script, *args, env=None, timeout=5):
        return subprocess.run(SHELL + ['-c', script, 'x', *map(str, args)], env=env or self.env,
                              text=True, capture_output=True, timeout=timeout)

    def read(self, mode):
        r = self.run('. "$1"; vward_routing_read "$2"', READ, mode, timeout=3)
        assert r.returncode == 0, (mode, r.stderr)
        assert 'secret-token' not in r.stdout
        return r.stdout

    def audit(self, intents, snapshot):
        with tempfile.TemporaryDirectory() as td:
            ip, sp = Path(td)/'i', Path(td)/'s'; ip.write_text(intents); sp.write_text(snapshot)
            r = subprocess.run(['sh', '-c', '. "$1"; vward_routing_audit "$2" "$3"', 'a', str(AUDIT), str(ip), str(sp)],
                               text=True, capture_output=True, timeout=5)
            assert r.returncode == 0, r.stderr
            return r.stdout
