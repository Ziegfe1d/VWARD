#!/usr/bin/env python3
"""Actual existing AGH worker, exact URI+domain delta, real lock guard, DATA API."""
import json,os
from pathlib import Path
from fixture import Fixture,ROOT,function_source
control=ROOT/'components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh'
common=ROOT/'components/ads-privacy-guard/lib/vward-ads-privacy-common.sh'
with Fixture() as f:
    state=f.p/'agh.json';pairs=f.p/'pairs';taken=f.p/'taken'
    uri='https://dns.example.test/dns-query';other='https://other.example.test/dns-query'
    baseline={'upstream_dns':[f'[/x.example/y.example/]{uri}',f'[/x.example/]{other}','9.9.9.9'],'upstream_dns_file':''}
    state.write_text(json.dumps(baseline));pairs.write_text('x.example\t'+uri+'\n')
    functions=f.p/'functions'
    functions.write_text(''.join(function_source(common,n) for n in ('ads_epoch','ads_num','ads_pid_start','ads_read_line','ads_lock_create','ads_lock_acquire','ads_lock_release'))+
                         ''.join(function_source(control,n) for n in ('agfail','aget','agh_unchanged','agh_evidence','agh_guarded_back','valid_url','ads_smartdns_locked')))
    shim=f.p/'bin';shim.mkdir()
    if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH']}
    script='''
    . "$1"
    model=$2; A1=$3; A2=$4; W=$5; CONTROL_LOCK=$W/lock
    ADS_JQ=$(command -v jq); AG_SET=smartdns-take-pairs; CL_HELD=1
    ads_log() { :; }
    ads_agh_api_get() { [ "$1" = dns_info ] && cat "$model" > "$2"; }
    ads_agh_api_post() {
        [ "$1" = dns_config ] || return 1
        "$ADS_JQ" --slurpfile n "$2" '.upstream_dns=$n[0].upstream_dns' "$model" > "$W/next" && mv "$W/next" "$model"
    }
    [ "$6" = unlocked ] || ads_lock_acquire "$CONTROL_LOCK" 30 || exit 75
    ads_smartdns_locked
    '''
    r=f.run(script,functions,state,pairs,taken,f.p,'unlocked',env=env)
    assert r.returncode==75 and json.loads(state.read_text())==baseline,'CL_HELD alone bypassed the actual lock'
    r=f.run(script,functions,state,pairs,taken,f.p,'locked',env=env)
    assert r.returncode==0,(r.stdout,r.stderr)
    assert json.loads(state.read_text())['upstream_dns']==[f'[/y.example/]{uri}',f'[/x.example/]{other}','9.9.9.9'],'exact pair removal changed an independent URL/domain'
    assert taken.read_text()=='x.example\t'+uri+'\n'
print('B_AGH_LOCKED=PASS real worker/control lock, exact own pair, shared-row/other-URI/plain preservation')
