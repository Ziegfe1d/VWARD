#!/usr/bin/env python3
"""RS-6 native file adapters; transport, writers and cache refresh forbidden."""
import hashlib
import os
import re
import shlex
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'components/runtime/lib/vward-routing-read.sh'
AUDIT = ROOT / 'components/runtime/lib/vward-routing-audit.sh'
assert LIB.is_file(), 'RS6_READERS=FAIL: native read adapters missing (expected RED)'

def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

with tempfile.TemporaryDirectory() as d:
    p = Path(d)
    etc, state, cache = p/'etc', p/'state', p/'cache'
    (etc/'services/owned').mkdir(parents=True)
    (etc/'route-engine/domain-lists').mkdir(parents=True)
    state.mkdir(); cache.mkdir()
    dev = etc/'device.conf'
    dev.write_text('VWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_WAN_DEVICE=eth3\n')
    cfg = cache/'running-config'
    cfg.write_text('interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n'
        '    route object-group Mine Wireguard0 auto\n'
        '    route object-group domain-list0 Wireguard0 auto\n'
        '    route object-group AdaptiveAuto Wireguard0 auto\n'
        '    https upstream https://dns.example/secret-token domain smart.example\n!\n'
        'object-group fqdn Mine\n    include x.example\n    include smart.example\n!\n'
        'object-group fqdn domain-list0\n    include x.example\n    include s.example\n!\n'
        'object-group fqdn AdaptiveAuto\n    include x.example\n!\n')
    mapping = cache/'device-map.tsv'
    mapping.write_text('I\tWireguard0\tWireguard\tnwg0\tprivate\nI\tWireguard1\tWireguard\tnwg1\tprivate\n'
                       'I\tGigabitEthernet1\tGigabitEthernet\teth3\tpublic\n')
    services = etc/'services/enabled.tsv'
    services.write_text('svc\tdomain-list0\tauto\n')
    cats = etc/'services/categories.tsv'; cats.write_text('ai\tWireguard0\n')
    catalog = p/'catalog.json'
    catalog.write_text('{"schema":1,"services":[{"id":"svc","title":"Service","category":"ai","domains":["x.example","s.example"]},'
                       '{"id":"off","title":"Off","category":"ai","domains":["off.example"]}]}')
    persist = state/'adaptive-persist.txt'; persist.write_text('x.example\na.example\n')
    agh = cache/'agh-domains'; agh.write_text('smart.example\n')
    saved = etc/'route-engine/domain-lists/Mine'; saved.write_text('route=ISP\tauto\nagh=smart.example\thttps://dns.example/secret-token\n')
    (etc/'route-engine/force-vpn.conf').write_text('except.example\n')
    (etc/'policy-sync').mkdir(); (etc/'policy-sync/excluded.categories').write_text('owner-choice\n')
    proof = etc/'services/owned/domain-list0'
    proof.write_text('include s.example\ninclude x.example\nroute=Wireguard0\tauto\n'); proof.chmod(0o600)
    env = os.environ | {'VWARD_CONSOLE_ETC':str(etc), 'VWARD_ROUTE_STATE':str(state),
        'VWARD_KCACHE':str(cache), 'VWARD_DEVICE_CONFIG':str(dev),
        'VWARD_DEVICE_MAP_CACHE':str(mapping), 'VWARD_SERVICES_FETCHED':str(catalog),
        'VWARD_SERVICES_BUNDLED':str(p/'missing-catalog'), 'VWARD_ROUTING_AGH_DOMAINS':str(agh),
        'VWARD_CONSOLE_BACKUP_DIR':str(p/'backup'), 'VWARD_NDMC':'/forbidden/ndmc',
        'VWARD_CURL_BIN':'/forbidden/curl'}
    def read(mode, shell=None):
        shell = shell or ([os.environ["RS6_BUSYBOX"],"ash"] if os.environ.get("RS6_BUSYBOX") else ["sh"])
        r = subprocess.run(shell+['-c', '. "$1"; vward_routing_read "$2"', 'reader',str(LIB),mode],
                           env=env, text=True, capture_output=True, timeout=3)
        assert r.returncode == 0, (mode,r.stderr)
        assert 'secret-token' not in r.stdout
        return r.stdout
    def evaluate(i,s):
        # Only tests write normalized files; the runtime adapter writes stdout.
        with tempfile.TemporaryDirectory() as td:
            ip,sp=Path(td)/'i',Path(td)/'s'; ip.write_text(i); sp.write_text(s)
            r=subprocess.run(['sh','-c','. "$1"; vward_routing_audit "$2" "$3"','audit',str(AUDIT),str(ip),str(sp)],
                             text=True,capture_output=True,timeout=3)
            assert r.returncode==0,r.stderr
            rows=[line.split('\t') for line in r.stdout.splitlines()]
            assert all(row[-1]=='unknown' for row in rows)
            assert all(row[7] in ('unknown','unresolved','inactive') for row in rows)
            return rows
    original=digest(p)
    i,s=read('intents'),read('snapshot')
    rows=evaluate(i,s)
    assert {r[0] for r in rows}=={'x.example','s.example','smart.example','a.example'}
    x=next(r for r in rows if r[0]=='x.example')
    assert all(source+':' in x[1] for source in 'MSA'),x
    assert 'off.example' not in i and 'except.example' not in i
    assert 'vward@reference' in x[5] and '@managed' not in s
    assert 'smartdns' in i and 'health\tDNS\tunknown' in s and 'health\tAGH\tunknown' in s
    assert 'snapshot\tlegacy-read\tunknown' in s
    assert read('intents')==i and read('snapshot')==s and digest(p)==original
    # Execute the existing decision/read functions against this same native fixture.
    def legacy(path,name,prefix,call):
        source=(ROOT/path).read_text()
        match=re.search(r"^"+name+r"\(\)\s*\{\n.*?^\}\n",source,re.M|re.S)
        assert match,name
        return subprocess.run(["sh","-c",prefix+"\n"+match.group(0)+"\n"+call],capture_output=True,text=True,timeout=3)
    q=shlex.quote
    with tempfile.TemporaryDirectory() as td:
        w=Path(td)
        manual=w/"manual"; manual.write_text("x.example\nsmart.example\n")
        check=legacy("components/route-engine/scripts/vward-route-engine.sh","is_manual_known", "MANUAL="+q(str(manual)), "is_manual_known x.example")
        assert check.returncode==0 and any(line.startswith("M\t") and "\tx.example\t" in line for line in i.splitlines())
        check=legacy("components/route-reconciler/scripts/vward-route-reconciler.sh","adaptive_names",
                     "vward_keenetic_config() { cat "+q(str(cfg))+"; }; vward_running_config() { cat "+q(str(cfg))+"; }", "adaptive_names")
        assert check.returncode==0 and check.stdout=="x.example\n"
        assert "\ta.example\t" in i  # persist intent retained although runtime group lacks it
        check=legacy("components/policy-sync/scripts/vward-policy-sync.sh","collect_vpn_domains",
                     "WORK="+q(td)+"; WG=nwg0; VWARD_TUNNEL_INTERFACE=Wireguard0", "collect_vpn_domains "+q(str(cfg)))
        assert check.returncode==0 and set(check.stdout.splitlines())=={"x.example","s.example","smart.example"}
        configured={row.split("\t")[2] for row in s.splitlines() if row.startswith("route\t")}
        assert configured==set(check.stdout.splitlines())
        (w/"q").write_text("Wireguard0\t0\t10\t0\t2\t0\t10\t5\nWireguard1\t0\t20\t0\t2\t0\t20\t6\n")
        check=legacy("components/tunnel-guard/scripts/vward-tunnel-guard.sh","lists_best","LW="+q(td),"lists_best Wireguard0")
        assert check.returncode==0 and check.stdout=="Wireguard1\n" and "health\tVPN:Wireguard1\tunknown" in s
        check=legacy("components/console/scripts/vward-console-config.sh","service_target",
                     "JQ=jq; SV_CAT="+q(str(catalog))+"; SERVICES_CATS="+q(str(cats))+"; is_tunnel() { [ \"$1\" = Wireguard0 ] || [ \"$1\" = Wireguard1 ]; }",
                     "service_target auto svc")
        assert check.returncode==0 and check.stdout=="Wireguard0\n"
        assert all("\tVPN:Wireguard0\t" in line for line in i.splitlines() if line.startswith("S\t"))
    print("RS6_LEGACY_COMPARISON=PASS: route-engine/reconciler/policy-sync/tunnel-guard/services; differences documented")
    # Compare audit alone versus read+audit on identical inputs; host timing only.
    timings=[]
    for _ in range(3):
        start=time.perf_counter(); baseline=evaluate(i,s); middle=time.perf_counter()
        observed=evaluate(read("intents"),read("snapshot")); end=time.perf_counter()
        assert baseline==observed
        timings.append((round(middle-start,6),round(end-middle,6)))
    print("RS6_HOST_COST="+repr(timings)+" normalized_bytes="+str(len((i+s).encode())))
    # All eight combinations and 24 directed transitions with immutable native inputs.
    outputs={}
    for bits in range(8):
        ss=s
        for n,source in enumerate('MSA'):
            ss=ss.replace('source\t'+source+'\t1\tknown', 'source\t'+source+'\t'+str((bits>>n)&1)+'\tknown')
        outputs[bits]=evaluate(i,ss)
    assert len(outputs)==8
    transitions=0
    for bits in range(8):
        for n in range(3):
            target=bits^(1<<n)
            assert outputs[target]==evaluate(i,s.replace('source\tM\t1\tknown','source\tM\t'+str(target&1)+'\tknown')
                .replace('source\tS\t1\tknown','source\tS\t'+str((target>>1)&1)+'\tknown')
                .replace('source\tA\t1\tknown','source\tA\t'+str((target>>2)&1)+'\tknown'))
            transitions+=1
    assert transitions==24 and digest(p)==original
    # Conflicting service pin, partially shared domains and ISP route stay explicit.
    cats.write_text('ai\tWireguard1\n')
    assert any(r[7]=='unresolved' for r in evaluate(read('intents'),read('snapshot')))
    cats.write_text('ai\tWireguard0\n')
    cfg.write_text(cfg.read_text().replace('Mine Wireguard0 auto','Mine ISP auto'))
    assert any(r[7]=='unresolved' for r in evaluate(read('intents'),read('snapshot')))
    cfg.write_text(cfg.read_text().replace('Mine ISP auto','Mine Wireguard0 auto'))
    # Manual edit invalidates private proof; stale name/matching catalog never grants rights.
    proof.write_text('include x.example\n'); proof.chmod(0o600)
    assert '@vward@' not in read('snapshot')
    proof.chmod(0o666)
    assert '@vward@' not in read('snapshot')
    # Review regression: indented declarations are not top-level FQDN groups.
    valid_cfg=cfg.read_text()
    cfg.write_text("dns-proxy\n    route object-group Mine ISP auto\n!\ninterface Wireguard0\n    object-group fqdn Mine\n    include phantom.example\n!\n")
    assert "phantom.example" not in read("snapshot"), "nested fake group was invented"
    assert "source\tM\t1\tunknown" in read("snapshot")
    cfg.write_text(valid_cfg)
    # Nonregular cache input must return unknown instead of waiting on a pipe.
    cfg.unlink(); os.mkfifo(cfg)
    assert "source\tM\t1\tunknown" in read("snapshot")
    cfg.unlink(); cfg.write_text(valid_cfg)
    # Missing/empty lists, failed reads, malformed/unknown targets, lost cache after reboot.
    cfg.write_text(cfg.read_text().replace('    include x.example\n    include smart.example\n',''))
    evaluate(read('intents'),read('snapshot'))
    cfg.unlink()
    assert 'source\tM\t1\tunknown' in read('snapshot')
    evaluate(read('intents'),read('snapshot'))
    cfg.write_text('error: snapshot refused\n')
    assert 'route\t' not in read('snapshot')
    mapping.unlink(); agh.unlink(); persist.unlink(); services.unlink(); catalog.write_text('{broken')
    i2,s2=read('intents'),read('snapshot')
    assert i2=='' and all('source\t'+c+'\t1\tunknown' in s2 for c in 'MSA')
    evaluate(i2,s2)
    # Expansion must obey RS5 limits before stdout (300 native domains x14 routes).
    cfg.write_text("dns-proxy\n"+"".join("    route object-group Mine Wireguard%d auto\n"%n for n in range(14))+"!\nobject-group fqdn Mine\n"+
                   "".join("    include d%d.example\n"%n for n in range(300))+"!\n")
    mapping.write_text("".join("I\tWireguard%d\tWireguard\tnwg%d\tprivate\n"%(n,n) for n in range(14)))
    for mode in ("intents","snapshot"):
        shell=([os.environ["RS6_BUSYBOX"],"ash"] if os.environ.get("RS6_BUSYBOX") else ["sh"])
        result=subprocess.run(shell+["-c", '. "$1"; vward_routing_read "$2"', "reader",str(LIB),mode],env=env,text=True,capture_output=True,timeout=3)
        assert result.returncode==2 and result.stdout=="", "expanded output breached RS5 limit: "+mode
    # RS5 bounds apply to the UNION of both projections as well as each file.
    cfg.write_text("dns-proxy\n    route object-group AdaptiveAuto Wireguard0 auto\n!\nobject-group fqdn AdaptiveAuto\n"+
                   "".join("    include old%d.example\n"%n for n in range(900))+"!\n")
    persist.write_text("".join("new%d.example\n"%n for n in range(900)))
    for mode in ("intents","snapshot"):
        shell=([os.environ["RS6_BUSYBOX"],"ash"] if os.environ.get("RS6_BUSYBOX") else ["sh"])
        result=subprocess.run(shell+["-c", '. "$1"; vward_routing_read "$2"', "reader",str(LIB),mode],env=env,text=True,capture_output=True,timeout=3)
        assert result.returncode==2 and result.stdout=="", "combined domain union breached RS5 limit: "+mode
    # Source loading itself is inert, including the caller environment.
    r=subprocess.run(['sh','-c','sentinel=preserved; original_path=$PATH; original_ifs=$IFS; . "$1"; [ "$sentinel" = preserved ] && [ "$PATH" = "$original_path" ] && [ "$IFS" = "$original_ifs" ]','load',str(LIB)],
                     env=env,capture_output=True,text=True,timeout=3)
    assert r.returncode==0,r.stderr
    print('RS6_READERS=PASS: native M/S/A, 8 states/24 transitions, repeats, unknown, conflicts, rights, purity')
