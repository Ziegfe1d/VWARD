#!/usr/bin/env python3
"""Unset production prefix reaches an ordinary closed admission boundary, no host IO."""
from fixture import Fixture,LIBDIR,function_source

with Fixture() as f:
    source=LIBDIR/'vward-routing-live.sh'
    binder=function_source(source,'vrl_paths_bind') if source.exists() and 'vrl_paths_bind()' in source.read_text() else ''
    actual=function_source(LIBDIR/'vward-routing-pipeline.sh','vrb_self_admit')
    # This boundary deliberately REFUSES; no successful lock/admission/transport
    # is substituted, and the test cannot create a real /tmp or /opt directory.
    script='''unset VWARD_ROOT_PREFIX
vrl_paths_bind
'''+actual+'''
vrb_data_ancestry() { return 75; }
rc=0
vrb_self_admit routing-coordinator || rc=$?
[ "$rc" = 75 ] || exit 90
printf 'boundary-refused:%s\n' "$vrl_root"
'''
    r=f.run(binder+'\n'+script)
    assert r.returncode==0 and r.stdout=='boundary-refused:/opt/var/lib/vward/routing\n',(r.returncode,r.stdout,r.stderr)
    point='    VWARD_ROOT_PREFIX=${VWARD_ROOT_PREFIX-}\n'
    assert binder.count(point)==1,'default binding point changed'
    r=f.run(binder.replace(point,'')+'\n'+script)
    assert r.returncode!=0 and 'boundary-refused:' not in r.stdout, 'missing production default normalization was not detected'
print('LIVE_DEFAULT_BINDING=PASS unset production prefix normalized before actual fail-closed admission, no host IO')
