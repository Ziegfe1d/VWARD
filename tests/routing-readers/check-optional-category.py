#!/usr/bin/env python3
"""A genuinely absent optional pin file is default; invalid files are unknown."""
from fixture import Fixture

with Fixture() as f:
    baseline=f.read('intents')
    f.cats.unlink()
    assert 'source\tS\t1\tknown\n' in f.read('snapshot')
    assert f.read('intents')==baseline,'absent pin changed the existing profile-default intent'
    f.cats.symlink_to(f.p/'missing')
    assert 'source\tS\t1\tunknown\n' in f.read('snapshot'),'dangling alias was accepted as absence'
    f.cats.unlink();f.cats.mkdir()
    assert 'source\tS\t1\tunknown\n' in f.read('snapshot'),'directory was accepted as absence'
    f.cats.rmdir();f.cats.write_text('not-a-valid-category-row\n')
    assert 'source\tS\t1\tunknown\n' in f.read('snapshot'),'malformed pin was accepted as absence'
print('OPTIONAL_CATEGORY=PASS true absence uses profile default; alias/directory/malformed stay unknown')
