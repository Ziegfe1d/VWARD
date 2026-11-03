#!/usr/bin/env python3
"""Server selection and saved DNS restoration serialize EDIT -> CHANGE."""
import ast
import tempfile
import threading
import time
from pathlib import Path
import service_fixture as fixture
from doh_fixture import responder

tree = ast.parse(Path(__file__).with_name('check-ai-catalog-cycle.py').read_text())
DNS = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'DNS')
OLD = 'https://old.example.test/dns-query/synthetic'
NEW = 'https://new.example.test/dns-query/synthetic'
with tempfile.TemporaryDirectory() as td:
    s = fixture.Services(Path(td)); responder(Path(td), s.env); s.foreign()
    s.cfg.write_text(s.cfg.read_text().replace('domain-list7 ISP auto', 'domain-list7 Wireguard0 auto'))
    saved = s.etc/'route-engine/domain-lists/domain-list7'; saved.parent.mkdir(parents=True)
    saved.write_text('route=ISP\tauto\ndoh=https upstream '+OLD+' dnsm on ISP domain claude.ai\n')
    (s.etc/'smartdns.conf').write_text('SMARTDNS_URL='+OLD+'\n')
    ndmc = Path(s.env['VWARD_NDMC'])
    ndmc.write_text(ndmc.read_text().replace('if w[:1] == ["dns-proxy"]:', DNS+'\nif w[:1] == ["dns-proxy"]:'))
    entered, resume, setter_entered = (s.tmp/n for n in ('probe-entered','resume','setter-entered'))
    curl = Path(s.env['VWARD_CURL_BIN'])
    curl.write_text(curl.read_text().replace('sys.stdin.read()', f'''request=sys.stdin.read()
import time
if 'old.example.test' in request:
    Path({str(entered)!r}).touch()
    while not Path({str(resume)!r}).exists(): time.sleep(0.01)'''))
    source = fixture.HELPER
    setter = s.tmp/'setter.sh'
    start = '        set) IFS= read -r ss_url || die invalid_value 64'
    body = source.read_text(); assert body.count(start) == 1
    setter.write_text(body.replace(start, start+f'\n             : > "{setter_entered}"'))
    out = {}; failure = None
    a = threading.Thread(target=lambda: out.update(bypass=s.run('domain-list','domain-list7','bypass')))
    a.start()
    b = None
    try:
        deadline = time.monotonic()+20
        while not entered.exists() and a.is_alive() and time.monotonic()<deadline: time.sleep(0.01)
        assert entered.exists(), out
        lock_pid = (s.tmp/'change.lock/pid').read_text().strip()
        import os
        os.kill(int(lock_pid), 0)
        fixture.HELPER = setter
        # stdin is deliberately supplied as the real server API does.
        import subprocess
        b = threading.Thread(target=lambda: out.update(setter=subprocess.run(
            ['sh',str(setter),'smartdns-server','set'],input=NEW+'\n',env=s.env,text=True,capture_output=True,timeout=25)))
        b.start()
        while not setter_entered.exists() and b.is_alive() and time.monotonic()<deadline: time.sleep(0.01)
        assert setter_entered.exists()
        b.join(0.4)
        assert 'setter' not in out, ('replacement passed while old saved DNS was being restored', lock_pid, Path('/proc',lock_pid).exists(), out.get('setter'))
    finally:
        fixture.HELPER = source; resume.touch(); a.join(30)
        if b: b.join(30)
    assert out['bypass'].returncode == 0 and out['setter'].returncode == 0, out
    assert (s.etc/'smartdns.conf').read_text() == 'SMARTDNS_URL='+NEW+'\n'
print('SMARTDNS_SET_RACE=PASS')
