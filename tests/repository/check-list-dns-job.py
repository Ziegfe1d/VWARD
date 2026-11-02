#!/usr/bin/env python3
"""Slow DNS list changes use the existing detached job, not a 20s HTTP mutation."""
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
js = (ROOT / 'web/assets/vward-console.js').read_text()
assert 'async function listModeWrite(' in js, 'LIST_DNS_JOB=FAIL: list-mode still uses synchronous config POST'
a = js.index('async function listModeWrite(')
fn = js[a:js.index('\n}\n', a)+3]
code = '''const seen=[];
const bgJob=async f=>{seen.push(f);return {ok:true,done:true,x:{ok:true,result:'changed'}}};
''' + fn + '''
(async()=>{
 const x=await listModeWrite('domain-list3','dns');
 if(!x.ok||seen.length!==1||seen[0].op!=='list-mode'||seen[0].id!=='domain-list3'||seen[0].tunnel!=='dns') throw Error(JSON.stringify(seen));
})().catch(e=>{console.error(e);process.exit(1)});
'''
r = subprocess.run(['node', '-e', code], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
print('LIST_DNS_JOB=PASS')
