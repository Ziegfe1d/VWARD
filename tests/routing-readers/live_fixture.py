"""Canonical installed paths with the existing NDMC fixture seam, no network."""
import os
import shutil
import subprocess
from fixture import PipelineFixture, LIBDIR, ROOT, SHELL

class LiveFixture(PipelineFixture):
    def __init__(self,vpns=2):
        super().__init__()
        assert vpns in (1,2,3)
        self.prefix=self.p/'installed'
        self.live=self.prefix/'opt/var/lib/vward/routing'
        self.live.mkdir(parents=True,mode=0o700)
        shutil.copytree(self.decision,self.live/'decision')
        (self.live/'decision/context.tsv').write_text('source:M\t1\nsource:S\t1\nsource:A\t1\n'+
            ''.join(f'VPN:Wireguard{i}\tavailable\n' for i in range(vpns)))
        (self.live/'journal').mkdir(mode=0o700)
        self.etc=self.prefix/'opt/etc/vward'
        (self.etc/'services/owned').mkdir(parents=True)
        for name in ('enabled.tsv','categories.tsv'):
            shutil.copy2(self.e/'services'/name,self.etc/'services'/name)
        shutil.copy2(self.e/'device.conf',self.etc/'device.conf')
        (self.etc/'device.conf').chmod(0o600)
        (self.prefix/'tmp').mkdir()
        shutil.copy2(self.e/'device-map.tsv',self.prefix/'tmp/vward-device-map.tsv')
        (self.prefix/'tmp/vward-device-map.tsv').write_text(''.join(
            f'I\tWireguard{i}\tWireguard\tnwg{i}\tprivate\n' for i in range(vpns))+
            'I\tGigabitEthernet1\tGigabitEthernet\teth3\tpublic\n')
        cat=self.prefix/'opt/var/lib/vward/services';cat.mkdir(parents=True)
        shutil.copy2(self.e/'catalog.json',cat/'catalog.json')
        self.route=self.prefix/'opt/var/lib/vward/route-engine';self.route.mkdir()
        shutil.copy2(self.e/'route/adaptive-persist.txt',self.route/'adaptive-persist.txt')
        self.native=self.p/'router-native';self.native.write_bytes((self.e/'running.cfg').read_bytes())
        self.native.write_text(''.join(f'interface Wireguard{i}\n!\n' for i in range(vpns))+'dns-proxy\n!\n')
        self.startup=self.p/'router-startup';self.startup.write_bytes(self.native.read_bytes())
        self.calls=self.p/'native.commands'
        self.ndmc=self.p/'actual-ndmc-fixture'
        self.ndmc.write_text('''#!/usr/bin/env python3
import os,sys,pathlib,shlex,time
base=pathlib.Path(__file__).parent
cfg=base/'router-native';saved=base/'router-startup'
assert len(sys.argv)==3 and sys.argv[1]=='-c'
cmd=sys.argv[2]
with (base/'native.commands').open('a') as out: out.write(str(os.getpid())+'\\t'+cmd+'\\n')
if cmd=='show running-config': print(cfg.read_text(),end='');sys.exit(0)
if cmd.startswith('show interface '):
    name=cmd.removeprefix('show interface ')
    if (base/('interface-unknown-'+name)).exists() or ('interface '+name+'\\n') not in cfg.read_text():
        print('Command:: unknown interface');sys.exit(1)
    print('state: up\\nlink: up\\nonline: unknown');sys.exit(0)
def pause(phase):
    control=base/('native-pause-'+phase)
    if control.exists() and control.read_text().strip()==cmd:
        (base/'native-paused').write_text(str(os.getpid()))
        while not (base/'native-resume').exists():time.sleep(.02)
pause('before')
if cmd=='system configuration save':
    if (base/'save-refuse').exists(): print('Command:: failed');sys.exit(1)
    saved.write_bytes(cfg.read_bytes());sys.exit(0)
t=shlex.split(cmd);neg=False
if t[0]=='no':neg=True;t=t[1:]
lines=cfg.read_text().splitlines(keepends=True)
if t[:2]==['object-group','fqdn']:
    g=t[2];head='object-group fqdn '+g+'\\n'
    if len(t)==3:
        if neg:
            start=lines.index(head);end=lines.index('!\\n',start)+1;del lines[start:end]
        else:
            if head not in lines:lines += [head,'!\\n']
    elif len(t)==5 and t[3]=='include':
        start=lines.index(head);end=lines.index('!\\n',start)
        row='    include '+t[4]+'\\n'
        if neg:
            if row in lines[start:end]:lines.remove(row)
        elif row not in lines[start:end]: lines.insert(end,row)
    else:sys.exit(2)
elif t[0]=='dns-proxy':
    t=t[1:]
    if t[0]=='no':neg=True;t=t[1:]
    if len(t)==5 and t[:2]==['route','object-group'] and t[-1]=='auto':
        row='    '+' '.join(t)+'\\n';start=lines.index('dns-proxy\\n');end=lines.index('!\\n',start)
        if neg:
            if row in lines[start:end]:lines.remove(row)
        elif row not in lines[start:end]:lines.insert(end,row)
    elif t[:2]==['https','upstream']:
        start=lines.index('dns-proxy\\n');end=lines.index('!\\n',start)
        if neg and len(t)==3:
            # The real platform may remove all domains on this URL.
            lines=[line for i,line in enumerate(lines) if not (start<i<end and line.split()[:3]==t[:3])]
        elif not neg and len(t) in (5,6,7,8) and t[-2]=='domain':
            row='    '+' '.join(t)+'\\n'
            if row not in lines[start:end]:lines.insert(end,row)
        else:sys.exit(2)
    else:sys.exit(2)
else:sys.exit(2)
cfg.write_text(''.join(lines))
pause('after')
if (base/'native-lost-reply').exists() and (base/'native-lost-reply').read_text().strip()==cmd:sys.exit(1)
''')
        self.ndmc.chmod(0o755)
        self.env |= {'VWARD_ROOT_PREFIX':str(self.prefix),'VWARD_NDMC':str(self.ndmc),
                     'VWARD_CONSOLE_ETC':str(self.etc),'VWARD_ROUTE_STATE':str(self.route),
                     'VWARD_DEVICE_CONFIG':str(self.etc/'device.conf'),
                     'VWARD_DEVICE_MAP_CACHE':str(self.prefix/'tmp/vward-device-map.tsv'),
                     'VWARD_SERVICES_FETCHED':str(cat/'catalog.json'),
                     'VWARD_SERVICES_BUNDLED':str(self.prefix/'opt/share/vward/console/services-catalog.json'),
                     'VWARD_ADGUARD_CONFIG':str(self.prefix/'opt/etc/AdGuardHome/AdGuardHome.yaml'),
                     'VWARD_CONSOLE_BACKUP_DIR':str(self.prefix/'opt/var/backups/vward/console-config')}
        self.env.pop('VWARD_RS7_DRYRUN',None)
        self.env.pop('AGH_API_BASE',None) # Only AghLiveFixture configures a loopback API.
        self.libs += (LIBDIR/'vward-device-profile.sh',LIBDIR/'vward-routing-admission.sh')
        if (LIBDIR/'vward-routing-live.sh').exists():self.libs += (LIBDIR/'vward-routing-live.sh',)
        if (LIBDIR/'vward-routing-live-agh.sh').exists():self.libs += (LIBDIR/'vward-routing-live-agh.sh',)
        if (LIBDIR/'vward-routing-bootstrap.sh').exists():self.libs += (LIBDIR/'vward-routing-bootstrap.sh',)

    def console(self,*args,preserve_profile=False):
        device=self.etc/'device.conf'
        if not preserve_profile:
            device.write_text('VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\n'
                          'VWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n'
                          'VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\n'
                          'VWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n'
                          'VWARD_POLICY_GROUP=Mine\n')
            device.chmod(0o600)
        env=self.env|{'VWARD_PROFILE_LIB':self.env.get('VWARD_PROFILE_LIB',str(LIBDIR/'vward-device-profile.sh')),
                      'VWARD_ADMISSION_LIB':self.env.get('VWARD_ADMISSION_LIB',str(LIBDIR/'vward-runtime-admission.sh')),
                      'VWARD_DEVICE_CONFIG_OWNER_UID':str(os.getuid()),
                      'VWARD_CONSOLE_EDIT_LOCK':str(self.prefix/'tmp/vward-console-edit.lock'),
                      'VWARD_ROUTE_CHANGE_LOCK':str(self.prefix/'tmp/vward-route-change.lock'),
                      'VWARD_CONSOLE_AUDIT_LOG':str(self.p/'console-audit')}
        # The shared fixture runner reaps OUR whole process group on timeout;
        # a failed console test must not leave native publishers in later tests.
        return self.run('exec "$@"',*SHELL,str(getattr(self,'console_path',ROOT/'components/console/scripts/vward-console-config.sh')),*args,
                        env=env,timeout=45)

    def install_rci(self):
        """Existing profile discovery uses a show-only curl fixture, no network."""
        curl=self.p/'rci-curl-fixture'
        curl.write_text('''#!/usr/bin/env python3
import json,pathlib,sys,time
from urllib.parse import urlsplit,parse_qs
p=pathlib.Path(__file__).parent
u=urlsplit(sys.argv[-1]);q=parse_qs(u.query)
with (p/'rci.calls').open('a') as out:out.write(u.path+'?'+u.query+'\\n')
if (p/'rci-unavailable').exists():sys.exit(22)
names={'Wireguard0':('Wireguard','nwg0','private'),'Wireguard1':('Wireguard','nwg1','private'),'GigabitEthernet1':('GigabitEthernet','eth3','public')}
if u.path=='/rci/show/interface' and not q:
    if (p/'rci-pause').exists():
        (p/'rci-paused').touch()
        while not (p/'rci-resume').exists():time.sleep(.02)
    print(json.dumps({n:{'type':t,'security-level':s} for n,(t,k,s) in names.items()}))
elif u.path=='/rci/show/interface/system-name' and set(q)=={'name'} and len(q['name'])==1 and q['name'][0] in names:
    print(json.dumps(names[q['name'][0]][1]))
else:sys.exit(23)
''')
        curl.chmod(0o755)
        self.env|={'VWARD_CURL_BIN':str(curl),'VWARD_RCI_BASE':'http://127.0.0.1:79/rci',
                   'VWARD_RCI_CALLS':str(self.p/'rci-count'),'VWARD_RCI_FAIL_LOG':str(self.p/'rci-fail')}

    def install_console(self):
        """Copy actual candidate closure, as deployed, without changing map."""
        lib=self.prefix/'opt/lib/vward';lib.mkdir(parents=True)
        for source in LIBDIR.glob('*.sh'):
            dest=lib/source.name;shutil.copy2(source,dest);dest.chmod(0o644)
        shutil.copy2(ROOT/'config/runtime/routing-capabilities.tsv',lib/'routing-capabilities.tsv')
        (lib/'routing-capabilities.tsv').chmod(0o644)
        binpath=self.prefix/'opt/bin';binpath.mkdir()
        self.console_path=binpath/'vward-console-config.sh'
        shutil.copy2(ROOT/'components/console/scripts/vward-console-config.sh',self.console_path)
        self.console_path.chmod(0o755)
        self.env|={'VWARD_PROFILE_LIB':str(lib/'vward-device-profile.sh'),
                   'VWARD_ADMISSION_LIB':str(lib/'vward-runtime-admission.sh')}
