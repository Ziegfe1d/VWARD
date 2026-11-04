"""Local AGH mirror for orchestration tests; real AGH executor has its own fault suite."""
from pathlib import Path


def install(tmp, env):
    yaml = Path(tmp)/'agh.yaml'
    yaml.write_text("dns:\n  upstream_dns:\n    - 9.9.9.10\n")
    control = Path(tmp)/'ads-control'
    control.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
p=Path(os.environ['VWARD_ADGUARD_CONFIG']); lines=p.read_text().splitlines()
op=sys.argv[2]
def rows():
    result=[]
    for l in lines:
        v=l.strip().removeprefix('- ').strip("'\\\"")
        if v.startswith('[/') and '/]' in v:
            ds,u=v[2:].split('/]',1)
            result.extend((d,u) for d in ds.split('/'))
    return result
r=rows()
if op=='smartdns-check':
    pairs=[tuple(l.split('\\t')) for l in Path(sys.argv[3]).read_text().splitlines()]
    if not all(pair in r for pair in pairs):
        print('ERROR=smartdns_binding_missing'); sys.exit(1)
    print('CONTROL=PASS'); print('CHANGED=0'); sys.exit(0)
elif op=='smartdns-put':
    for line in Path(sys.argv[3]).read_text().splitlines():
        d,u=line.split('\\t')
        if not any(d==a for a,b in r): r.append((d,u))
elif op=='smartdns-take':
    ds=Path(sys.argv[3]).read_text().splitlines()
    taken=[(d,u) for d,u in r if any(d==a or d.endswith('.'+a) for a in ds)]
    Path(sys.argv[4]).write_text(''.join(d+'\\t'+u+'\\n' for d,u in taken))
    r=[row for row in r if row not in taken]
else:
    print('ERROR=invalid_operation'); sys.exit(1)
p.write_text("dns:\\n  upstream_dns:\\n    - 9.9.9.10\\n"+''.join("    - '[/"+d+"/]"+u+"'\\n" for d,u in r))
print('CONTROL=PASS')
''')
    control.chmod(0o755)
    pidof = Path(tmp)/'agh-pidof'
    pidof.write_text('#!/bin/sh\n[ "$1" = AdGuardHome ]\n'); pidof.chmod(0o755)
    env.update(VWARD_ADGUARD_CONFIG=str(yaml), VWARD_ADS_CONTROL_BIN=str(control), VWARD_PIDOF_BIN=str(pidof))
    return yaml
