"""A stand-in daemon for the tests: a real, visible process whose command line starts with its
own path (the way the library knows a running program), that only waits.

It used to be a copy of `sleep`. Where `sleep` is one multi-call program (uutils coreutils on the
CI runner image since 11.2026, BusyBox), a copy under another name does not know what to be and
ends at once: the «running» cases failed there. This one execs the Python that runs the tests
with the stand-in's path as its name; the process keeps its PID."""
from pathlib import Path

DAEMON = '''#!/usr/bin/env python3
import os, sys
secs = sys.argv[1] if len(sys.argv) > 1 else "300"
os.execv(sys.executable, [os.path.abspath(sys.argv[0]), "-c", "import time; time.sleep(float(%r))" % secs])
'''


def write_daemon(path) -> None:
    path = Path(path)
    path.write_text(DAEMON)
    path.chmod(0o755)
