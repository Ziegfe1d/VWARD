#!/usr/bin/env python3
"""A return file and its DNS proof may have the same basename/second/PID."""
import sys,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/routing-readers'))
from fixture import function_source,SHELL
with tempfile.TemporaryDirectory() as td:
    p=Path(td);(p/'return').mkdir();(p/'proof').mkdir()
    for d,text in [('return','before return'),('proof','before proof')]:
        f=p/d/'domain-list0';f.write_text(text);f.chmod(0o400)
    script=function_source(ROOT/'components/console/scripts/vward-console-config.sh','backup_file')+'''
    date() { printf '%s\\n' fixed; }
    BACKUP_DIR=$1/backup;BACKUP_KEEP=20
    backup_file "$1/return/domain-list0" && backup_file "$1/proof/domain-list0"
    '''
    r=subprocess.run(SHELL+['-c',script,'test',str(p)],capture_output=True,text=True,timeout=5)
    assert r.returncode==0,(r.returncode,r.stderr)
    files=list((p/'backup').iterdir())
    assert len(files)==2 and {f.read_text() for f in files}=={'before return','before proof'},'second backup overwrote the first'
    assert all(f.stat().st_mode&0o777==0o400 for f in files)
print('CONSOLE_BACKUP_COLLISION=PASS distinct private0400 originals under the same second/PID/basename')
