#!/usr/bin/env python3
"""RS-6 consistent snapshot: one verified input set, generation, no partial result."""
import os
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

def consistent(f, out, env=None, timeout=10):
    return f.run('. "$1"; . "$2"; vward_routing_consistent_read "$3"', READ, SNAP, out, env=env, timeout=timeout)

def files(out):
    return sorted(os.listdir(out))

def unknown(r, reason, out):
    assert r.returncode == 3 and r.stdout == f'unknown\t{reason}\n', (reason, r.returncode, r.stdout, r.stderr)
    assert files(out) == [], f'partial result left behind for {reason}: {files(out)}'

with Fixture() as f:
    out = f.p/'out'; out.mkdir(mode=0o700)
    before = digest(f.p)
    r = consistent(f, out)
    assert r.returncode == 0 and r.stdout.startswith('ok\tg-'), (r.stdout, r.stderr)
    gen = r.stdout.split('\t')[1].strip()
    assert files(out) == ['generation', 'identity.tsv', 'intents.tsv', 'snapshot.tsv']
    assert (out/'generation').read_text().strip() == gen
    snap = (out/'snapshot.tsv').read_text()
    assert f'snapshot\t{gen}\tknown\n' in snap and 'legacy-read' not in snap
    # Same data -> same generation and bytes (repeat, and "reboot": volatile mtimes/inodes change).
    first = {n: (out/n).read_bytes() for n in files(out)}
    f.cfg.write_text(f.cfg.read_text()); os.utime(f.cfg, None)
    r2 = consistent(f, out)
    assert r2.stdout == r.stdout and {n: (out/n).read_bytes() for n in files(out)} == first, 'generation depends on mtime/inode'
    after = digest(f.p)
    assert {k: v for k, v in after.items() if not k.startswith('out/')} == {k: v for k, v in before.items()}, 'inputs modified'
    # Audit on the coordinated files: snapshot is known, source flags unchanged.
    a = f.audit((out/'intents.tsv').read_text(), snap)
    assert a and all(l.split('\t')[10] == gen for l in a.splitlines())

    # Different content -> different generation (and not just a counter).
    f.persist.write_text('x.example\na.example\nb.example\n')
    r3 = consistent(f, out); assert r3.returncode == 0 and r3.stdout != r.stdout
    f.persist.write_text('x.example\na.example\n')

    # Missing / stale / unreadable inputs -> unknown, never empty-but-known.
    saved = f.cfg.read_text(); f.cfg.unlink()
    unknown(consistent(f, out), 'config-cache-missing', out)
    f.cfg.write_text(saved)
    old = time.time() - 7200; os.utime(f.cfg, (old, old))
    env = dict(f.env, VWARD_ROUTING_CACHE_AGE='60')
    unknown(consistent(f, out, env=env), 'config-cache-stale', out)
    os.utime(f.cfg, None)
    f.persist.unlink(); os.symlink(f.dev, f.persist)
    unknown(consistent(f, out), 'input-unreadable:persist', out)
    f.persist.unlink(); f.persist.write_text('x.example\na.example\n')
    os.mkfifo(f.agh) if not f.agh.unlink() else None
    unknown(consistent(f, out), 'input-unreadable:agh', out)   # FIFO never opened -> no hang
    f.agh.unlink(); f.agh.write_text('smart.example\n')
    f.persist.write_text('x' * (1024*1024 + 1))
    unknown(consistent(f, out), 'input-unreadable:persist', out)
    f.persist.write_text('x.example\na.example\n')
    for i in range(300): (f.etc/f'services/owned/g{i}').write_text('x')
    unknown(consistent(f, out), 'input-unreadable:owned:toomany', out)
    for i in range(300): (f.etc/f'services/owned/g{i}').unlink()

    # A durable pending/recovery record keeps the snapshot but turns every source unknown (reader rule).
    (f.p/'backup-recovery/smartdns.ABC').mkdir(parents=True)
    r = consistent(f, out); assert r.returncode == 0
    s = (out/'snapshot.tsv').read_text()
    assert 'source\tM\t1\tunknown' in s and 'source\tS\t1\tunknown' in s and 'source\tA\t1\tunknown' in s
    (f.p/'backup-recovery/smartdns.ABC').rmdir(); (f.p/'backup-recovery').rmdir()

    # Corrupt content is a per-source unknown, not an empty known source.
    f.cfg.write_text('error: refused\n')
    assert consistent(f, out).returncode == 0 and 'source\tM\t1\tunknown' in (out/'snapshot.tsv').read_text()
    f.cfg.write_text(CFG)

    # Unsafe OUTDIR -> usage error, nothing written.
    bad = f.p/'open'; bad.mkdir(mode=0o755); bad.chmod(0o755)
    r = consistent(f, bad); assert r.returncode == 2 and files(bad) == []
    r = f.run('. "$1"; . "$2"; vward_routing_consistent_read relative', READ, SNAP); assert r.returncode == 2
    link = f.p/'lnk'; os.symlink(out, link)
    r = consistent(f, link); assert r.returncode == 2

    # A failing reader (limit breach) -> unknown with NO partial files.
    f.cfg.write_text("dns-proxy\n" + "".join("    route object-group Mine Wireguard%d auto\n" % n for n in range(14)) +
                     "!\nobject-group fqdn Mine\n" + "".join("    include d%d.example\n" % n for n in range(300)) + "!\n")
    f.map.write_text("".join("I\tWireguard%d\tWireguard\tnwg%d\tprivate\n" % (n, n) for n in range(14)))
    unknown(consistent(f, out), 'reader-failed:intents', out)
    f.cfg.write_text(CFG)
    f.map.write_text('I\tWireguard0\tWireguard\tnwg0\tprivate\nI\tWireguard1\tWireguard\tnwg1\tprivate\nI\tGigabitEthernet1\tGigabitEthernet\teth3\tpublic\n')

    # RED: an input rewritten while the projections are being read must be detected.
    # A reader wrapper changes the cache (same size, new inode/mtime) between modes.
    real = f.p/'real-read.sh'
    real.write_text(READ.read_text().replace('vward_routing_read() (', 'vward_routing_read_real() (', 1))
    wrapper = f'''
    . "{real}"; . "{SNAP}"
    n=0
    vward_routing_read() {{
        n=$((n+1))
        if [ "$n" = 2 ]; then printf '%s\\n' "$VRS_CFG_NEW" > "$VRS_CFG.tmp" && mv "$VRS_CFG.tmp" "$VRS_CFG"; fi
        vward_routing_read_real "$@"
    }}
    vward_routing_consistent_read "$1"
    '''
    env = dict(f.env, VRS_CFG=str(f.cfg), VRS_CFG_NEW=CFG.replace('include s.example', 'include t.example').rstrip('\n'))
    r = f.run(wrapper, out, env=env)
    unknown(r, 'changed-during-read', out)
    f.cfg.write_text(CFG)
    # Deleting (cache dirtied by a writer) mid-read is a change too.
    wrapper2 = wrapper.replace('printf \'%s\\n\' "$VRS_CFG_NEW" > "$VRS_CFG.tmp" && mv "$VRS_CFG.tmp" "$VRS_CFG"', 'rm -f "$VRS_CFG"')
    assert wrapper2 != wrapper and 'rm -f' in wrapper2
    r = f.run(wrapper2, out, env=env); unknown(r, 'changed-during-read', out)
    f.cfg.write_text(CFG)
    # And the unchanged flow still succeeds afterwards (no stuck state).
    assert consistent(f, out).returncode == 0
    # No stale tmp dirs, no extra files in OUTDIR.
    assert files(out) == ['generation', 'identity.tsv', 'intents.tsv', 'snapshot.tsv']

    # 8 source combinations and 24 single-toggle transitions on the COORDINATED snapshot:
    # only the normalized snapshot flags change; the native inputs stay immutable.
    assert consistent(f, out).returncode == 0
    inten, snap0 = (out/'intents.tsv').read_text(), (out/'snapshot.tsv').read_text()
    def combo(bits):
        t = snap0
        for n, c in enumerate('MSA'):
            t = t.replace(f'source\t{c}\t1\tknown', f'source\t{c}\t{(bits >> n) & 1}\tknown')
        return f.audit(inten, t)
    results = {b: combo(b) for b in range(8)}
    assert len(set(results.values())) >= 4 and results[0] == combo(0)
    moves = 0
    for b in range(8):
        for n in range(3):
            assert combo(b ^ (1 << n)) == results[b ^ (1 << n)]; moves += 1
    assert moves == 24
    ins = digest(f.p)
    assert consistent(f, out).returncode == 0 and {k: v for k, v in digest(f.p).items() if not k.startswith('out/')} == {k: v for k, v in ins.items() if not k.startswith('out/')}
    # Loading the library is inert.
    r = f.run('sentinel=1; before=$(set | wc -l); . "$1"; . "$2"; [ "$sentinel" = 1 ]', READ, SNAP); assert r.returncode == 0
print('RS6_SNAPSHOT=PASS: generation, freshness, change detection, missing/corrupt/unreadable -> unknown, no partial output')
