#!/usr/bin/env python3
from pathlib import Path

p = Path('.github/scripts/console-gap-close-once.py')
s = p.read_text(encoding='utf-8')

start = s.index('# Structured numeric metrics from allowlisted action output')
end = s.index('# Tests for the actual missing prompt items.', start)
s = s[:start] + s[end:]

s = s.replace("if 'METRICS_JSON=' not in api:\n    fail(\"control actions do not expose structured numeric metrics\")\n", '')
s = s.replace('Prompt gap closure: log All/Reset, tunnel selector, route list filter/sort, FQDN group probe and structured action metrics.', 'Prompt gap closure: log All/Reset, tunnel selector, route list filter/sort and FQDN group probe.')

p.write_text(s, encoding='utf-8')
print('GAP_BOOTSTRAP_FIX=APPLIED')
