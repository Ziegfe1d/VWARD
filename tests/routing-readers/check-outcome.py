#!/usr/bin/env python3
"""The actual OFF pipeline emits a single honest configuration outcome."""
import json,re,subprocess,hashlib
from fixture import PipelineFixture,ROOT,SHELL,function_source
def consumers(f,path,obj):
    api=function_source(ROOT/'web/cgi-bin/api.cgi','routing_b_outcome_json')
    r=f.run(api+'\nJQ=jq;routing_b_outcome_json "$1"',path)
    assert r.returncode==0 and json.loads(r.stdout)==obj,(r.returncode,r.stdout,r.stderr)
    js=(ROOT/'web/assets/vward-console.js').read_text()
    esc=next(x for x in js.splitlines() if x.startswith('const esc ='))
    fn=re.search(r'^function routingOutcomeNote\(o\) \{.*?^\}\n',js,re.M|re.S).group()
    program=esc+'\n'+fn+'\nconst o=JSON.parse(require("fs").readFileSync(0,"utf8"));process.stdout.write(routingOutcomeNote(o));'
    ui=subprocess.run(['node','-e',program],input=r.stdout,capture_output=True,text=True,timeout=5)
    assert ui.returncode==0 and 'не подключён' in ui.stdout and 'Путь устройства не проверен' in ui.stdout,ui.stderr
    assert '<button' not in ui.stdout and 'data-' not in ui.stdout,'DTO presentation added an action'
    for field,value in [('client_verified',True),('client_path_verified',True),('activation','live')]:
        bad=f.p/'bad-outcome.json';bad.write_text(json.dumps(obj|{field:value})+'\n');bad.chmod(0o600)
        (f.p/'bad-outcome.json.sha').write_text(hashlib.sha256(bad.read_bytes()).hexdigest()+'\n')
        r=f.run(api+'\nJQ=jq;routing_b_outcome_json "$1"',bad)
        assert r.returncode==75 and not r.stdout,'API accepted a proof/activation it cannot establish'
with PipelineFixture() as f:
    r=f.invoke('vward_routing_pipeline2',f.j,'vpn','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    path=f.j/'vpn/prepared/outcome.json'
    assert path.exists(),'connected pipeline did not emit its common JSON outcome'
    obj=json.loads(path.read_text())
    assert obj['schema']==2 and obj['activation']=='off' and obj['client_verified'] is False
    assert obj['evidence']=='configuration' and obj['desired']['mode']=='vpn'
    assert obj['configured']['state']=='verified' and obj['configured']['persisted'] is True
    assert {x['source'] for x in obj['sources']}=={'S'}
    assert obj['coverage']['total']==2 and obj['coverage']['known']==2
    assert 'https://' not in path.read_text() and 'secret-token' not in path.read_text()
    consumers(f,path,obj)
    # A new read over a changed config cannot reuse the old operation's success.
    p=f.e/'running.cfg';p.write_text(p.read_text().replace('include x.example','include edited.example'))
    r=f.invoke('vward_routing_outcome_read2',f.j,'vpn')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    obj=json.loads(r.stdout)
    assert obj['configured']['state'] in ('partial','unknown') and obj['client_verified'] is False
    assert obj['configured']['persisted'] is False
with PipelineFixture() as f:
    (f.e/'save-fails').touch()
    r=f.invoke('vward_routing_pipeline2',f.j,'uncertain','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    obj=json.loads((f.j/'uncertain/prepared/outcome.json').read_text())
    assert obj['desired']['mode']=='vpn' and obj['configured']['state']=='unknown'
    assert obj['configured']['persisted'] is False and obj['client_verified'] is False
with PipelineFixture() as f:
    (f.decision/'bindings.tsv').write_text((f.decision/'bindings.tsv').read_text().replace('confirmed','unknown'))
    r=f.invoke('vward_routing_pipeline2',f.j,'blocked','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    previews=list(f.j.glob('.operation.*/outcome.json'))
    assert len(previews)==1 and not (f.j/'blocked').exists(),'denied preview created an execution capability'
    obj=json.loads(previews[0].read_text())
    assert obj['operation']['state']=='blocked' and obj['configured']['state']=='unknown'
    assert obj['coverage']['unknown']==2 and obj['desired']['mode']=='vpn'
    consumers(f,previews[0],obj)
with PipelineFixture() as f:
    (f.decision/'evidence.tsv').write_text('M\tm1\tx.example\texact\tISP\tdefault\t1\texplicit\t0\t-\nM\tm2\ty.example\texact\tVPN:Wireguard0\tdefault\t1\texplicit\t0\t-\n')
    r=f.invoke('vward_routing_pipeline2',f.j,'mixed','svc','auto','-','-',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    obj=json.loads((f.j/'mixed/prepared/outcome.json').read_text())
    assert obj['configured']['state']=='mixed' and obj['client_verified'] is False
    assert {s['source'] for s in obj['sources']}=={'M'}
    consumers(f,f.j/'mixed/prepared/outcome.json',obj)
print('B_COMMON_OUTCOME=PASS connected desired/configured/sources/coverage, save uncertainty and later edit never client proof; OFF only')
