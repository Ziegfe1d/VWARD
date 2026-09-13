#!/usr/bin/env python3
from pathlib import Path

# Old route-data binding assertion assumed route-data was the final case item.
p = Path('tests/repository/check-console-bindings.py')
s = p.read_text(encoding='utf-8')
old = "if 'action=route-data' not in html or 'route-data)' not in api:"
new = "if 'action=route-data' not in html or 'route-data' not in api:"
if s.count(old) != 1:
    raise SystemExit('route-data assertion marker mismatch')
p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Component actions yield to active updater transactions. Updater actions themselves
# delegate lock/recovery semantics to VWARD Update Engine.
p = Path('web/cgi-bin/api.cgi')
s = p.read_text(encoding='utf-8')
old = '''    [ ! -e /opt/var/run/vward/updater.lock ] || {
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    }

    CMD=""; ARG=""; REQUIRED=""; LABEL=""
'''
new = '''    if [ "$ACTION" = control ] && [ -e /opt/var/run/vward/updater.lock ]; then
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    fi

    CMD=""; ARG=""; REQUIRED=""; LABEL=""
'''
if s.count(old) != 1:
    raise SystemExit('updater lock guard marker mismatch')
s = s.replace(old, new, 1)

# BusyBox/POSIX awk: use split() return value, not length(array).
old = '''        {split($0,b,"/"); if(length(b)!=2) next; net=ipn(b[1]); p=b[2]+0; if(p<0||p>32) next; size=2^(32-p); base=int(net/size)*size; if(target>=base && target<base+size){print $0; exit}}
'''
new = '''        {n=split($0,b,"/"); if(n!=2) next; net=ipn(b[1]); p=b[2]+0; if(p<0||p>32) next; size=2^(32-p); base=int(net/size)*size; if(target>=base && target<base+size){print $0; exit}}
'''
if s.count(old) != 1:
    raise SystemExit('CIDR matcher marker mismatch')
p.write_text(s.replace(old, new, 1), encoding='utf-8')

print('FINAL_CONTROL_PLANE_FIX=APPLIED')
