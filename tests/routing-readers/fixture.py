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
OBSERVE = LIBDIR / 'vward-routing-observe.sh'
PLAN = LIBDIR / 'vward-routing-plan.sh'
JOURNAL = LIBDIR / 'vward-routing-journal.sh'
DRYRUN = LIBDIR / 'vward-routing-dryrun.sh'
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
            'VWARD_ADMISSION_LIB': str(LIBDIR/'vward-runtime-admission.sh'),
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
        # A timeout must also reap our own worker descendants. It neither
        # extends the budget nor leaves orphans mutating a later fixture.
        import signal
        p = subprocess.Popen(SHELL + ['-c', script, 'x', *map(str, args)], env=env or self.env,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            raise
        return subprocess.CompletedProcess(p.args, p.returncode, out, err)

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


def legacy_fn(path, name, prefix, call, extra_sub=None):
    """Run ONE real function of a production script (never the whole daemon)."""
    import re
    src = (ROOT/path).read_text()
    m = re.search(r"^" + name + r"\(\)\s*\{\n.*?^\}\n", src, re.M | re.S)
    assert m, name
    body = m.group(0)
    for a, b in (extra_sub or []):
        assert a in body, a
        body = body.replace(a, b)
    return subprocess.run(["sh", "-c", prefix + "\n" + body + "\n" + call], capture_output=True, text=True, timeout=5)


def function_source(path, name):
    """Extract one real shell function, including nested/one-line/subshell forms.

    Never source a daemon/CLI just to import its helpers. No body replacement.
    """
    import re
    src=Path(path).read_text()
    m=re.search(r'^(?P<indent>[ \t]*)'+re.escape(name)+r'\(\)[ \t]*(?:\n[ \t]*)?(?P<open>[{(])(?P<tail>[^\n]*)\n',src,re.M)
    assert m,name
    close='}' if m['open']=='{' else ')'
    if m['tail'].rstrip().endswith(close):return m[0]
    end=re.search('^'+re.escape(m['indent']+close)+r'[ \t]*\n',src[m.end():],re.M)
    assert end,name
    return src[m.start():m.end()+end.end()]


def probe_context(ref='a1'):
    # A current native clock fact for short reader/planner fixtures only.
    # Long connected tests pin an explicit DATA clock instead.
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    now=int(float(Path('/proc/uptime').read_text().split()[0]))
    return f'probe:{ref}\tfresh\nprobe-boot:{ref}\t{boot}\nprobe-until:{ref}\t{now+55}\n'


class PipelineFixture(Fixture):
    """Existing DATA router fixture plus the real internal console/AGH workers."""
    def __init__(self):
        super().__init__()
        self.j=self.p/'journal';self.j.mkdir(mode=0o700)
        self.e=self.j/'.emu';self.e.mkdir(mode=0o700)
        self.decision=self.e/'decision';self.decision.mkdir(mode=0o700)
        # parents=True applies mode only to the leaf; CI's umask022 otherwise
        # leaves services0755 and correctly closes the private DATA gate.
        (self.e/'services').mkdir(mode=0o700)
        (self.e/'services/owned').mkdir(mode=0o700)
        for name in ('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs','upstreams'):
            p=self.decision/(name+'.tsv');p.write_text('');p.chmod(0o600)
        (self.decision/'version.tsv').write_text('routing-state\t2\n')
        (self.decision/'choices.tsv').write_text('schema\t1\n')
        (self.decision/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\nsvc\ty.example\texact\tconfirmed\tipv4\tknown\n')
        (self.decision/'context.tsv').write_text('source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\nVPN:Wireguard1\tavailable\n')
        (self.e/'running.cfg').write_text('interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n!\n')
        (self.e/'running.cfg').chmod(0o600)
        (self.e/'device.conf').write_bytes(self.dev.read_bytes())
        (self.e/'device-map.tsv').write_bytes(self.map.read_bytes())
        (self.e/'catalog.json').write_bytes(self.catalog.read_bytes())
        (self.e/'agh-domains').write_text('')
        (self.e/'services/enabled.tsv').write_text('');(self.e/'services/enabled.tsv').chmod(0o600)
        (self.e/'services/categories.tsv').write_text('ai\tWireguard0\n')
        (self.e/'route').mkdir(mode=0o700);(self.e/'route/adaptive-persist.txt').write_text('')
        shim=self.p/'poison';shim.mkdir();self.trace=self.p/'transport'
        for name in ('ndmc','curl','comm','cksum','nslookup','ip'):
            p=shim/name;p.write_text('#!/bin/sh\necho called >> "'+str(self.trace)+'"\nexit 99\n');p.chmod(0o755)
        if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
        self.env|={'PATH':str(shim)+':'+os.environ['PATH'],'VWARD_RS7_DRYRUN':'1'}
        console=ROOT/'components/console/scripts/vward-console-config.sh'
        control=ROOT/'components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh'
        common=ROOT/'components/ads-privacy-guard/lib/vward-ads-privacy-common.sh'
        functions=self.p/'console-functions'
        functions.write_text(''.join(function_source(console,n) for n in ('dir_lock','group_set','vward_routing_console_group_locked','doh_lines','doh_present','doh_remove_url',
                             'new_tmp','install_tmp','backup_file','valid_group','smartdns_prune_saved'))+
                             ''.join(function_source(common,n) for n in ('ads_epoch','ads_num','ads_pid_start','ads_read_line','ads_lock_create','ads_lock_acquire','ads_lock_release'))+
                             ''.join(function_source(common,n) for n in ('agfail','aget','agh_unchanged','agh_evidence','agh_guarded_back','valid_url','ads_smartdns_locked')))
        self.libs=(READ,OBSERVE,SNAP,AUDIT,LIBDIR/'vward-routing-project.sh',PLAN,JOURNAL,DRYRUN,
                   LIBDIR/'vward-runtime-admission.sh',LIBDIR/'vward-routing-workers.sh',LIBDIR/'vward-routing-migrate.sh',
                   LIBDIR/'vward-routing-dns.sh',LIBDIR/'vward-routing-lifecycle.sh',LIBDIR/'vward-routing-legacy.sh',LIBDIR/'vward-routing-state.sh',LIBDIR/'vward-routing-outcome.sh',LIBDIR/'vward-routing-dispatch.sh',LIBDIR/'vward-routing-pipeline.sh',functions)

    clock = None
    def script(self,command):
        if self.clock is not None:
            boot, now = self.clock
            assert len(boot)==36 and all(c in '0123456789abcdef-' for c in boot) and isinstance(now,int)
            command = 'vr2_clock_read() { printf \'%s %s\\n\' '+boot+' '+str(now)+'; };\n'+command
        return ('for lib in '+' '.join('"${'+str(i)+'}"' for i in range(1,len(self.libs)+1))+
                '; do . "$lib"; done\nshift '+str(len(self.libs))+'\n'+command)

    def invoke(self,name,*args,more=None,timeout=45):
        return self.run(self.script('"$@"'),*self.libs,name,*args,env=self.env|(more or {}),timeout=timeout)

    def configure_dns(self,store):
        (self.decision/'policies.tsv').write_text(f'policy1\t{store}\tavailable\tactive\tnone\t1\turl1\n')
        (self.decision/'upstreams.tsv').write_text('url1\thttps://dns.example.test/dns-query\n')
        p=self.decision/'context.tsv';p.write_text(p.read_text()+f'storage:{store}\tavailable\nscope:subtree\tavailable\n')
        p=self.decision/'bindings.tsv';p.write_text(p.read_text().replace('exact','subtree'))
        p=self.e/'agh.json';p.write_text('{"upstream_dns":["9.9.9.9"],"upstream_dns_file":"","protection_enabled":true}\n');p.chmod(0o600)
