#!/usr/bin/env python3
"""Configured custom filters cannot turn a routing observation into an ADS write."""
import json
import subprocess
from agh_live_fixture import AghLiveFixture
from fixture import ROOT,SHELL

with AghLiveFixture() as f:
    registry=f.p/'registry.json';registry.write_text('{"sources":[]}')
    custom=f.p/'custom.json';custom.write_text(json.dumps({'sources':[{'id':'custom-0123456789','url':'https://neutral.example.test/list','format':'domains'}]}))
    state=f.p/'ads-state'
    env=f.env|{'VWARD_ADS_SOURCE_REGISTRY':str(registry),'VWARD_ADS_CUSTOM_SOURCES':str(custom),
               'VWARD_ADS_STATE':str(state),'VWARD_ADS_ETC':str(f.p/'ads-etc'),
               'VWARD_ADS_BACKUP_ROOT':str(f.p/'ads-backup'),'VWARD_ADS_LOG_DIR':str(f.p/'ads-log'),
               'VWARD_ADS_LIB':str(f.prefix/'opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh')}
    before=(registry.read_bytes(),custom.read_bytes())
    r=f.run(f.script('vrl_paths_bind && vrl_cache=$(mktemp -d "$1/tmp/observe.XXXXXX") && vrl_agh_observe'),*f.libs,f.prefix,env=env,timeout=8)
    assert r.returncode==0,(r.returncode,r.stderr)
    assert not state.exists(),'routing observer ran ads_source_registry_merge before CONTROL/J2'
    assert (registry.read_bytes(),custom.read_bytes())==before
    r=f.invoke('vward_routing_live_service','refused','svc','vpn','VPN:Wireguard77','default',0,more=env)
    assert r.returncode==75 and not state.exists(),('refused routing action initialized unrelated ADS state',r.returncode,r.stderr)
    assert not any(x[0]=='POST' for x in f.http_calls)
    # Existing CLI still performs its explicit component initialization and
    # retains the custom-source behavior; it never enters a routing writer.
    r=subprocess.run(SHELL+[str(ROOT/'components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh'),'status'],
                     env=env,capture_output=True,text=True,timeout=8)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    merged=json.loads((state/'source-registry.merged.json').read_text())
    assert any(s['id']=='custom-0123456789' for s in merged['sources']),merged
    assert (registry.read_bytes(),custom.read_bytes())==before
print('LIVE_AGH_IMPORT=PASS configured custom-source observation has no ADS write; actual old CLI retains explicit registry initialization')
