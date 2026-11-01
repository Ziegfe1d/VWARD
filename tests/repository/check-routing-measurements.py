#!/usr/bin/env python3
"""Check measurement accounting independently of host performance values."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('measure', ROOT / 'tests/perf/measure-routing-host.py')
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class Accounting(unittest.TestCase):
    def test_trace_counts_success_only_and_payload_writes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'trace.1'
            path.write_text('execve("/bin/sh", ["sh"], 0x0) = 0\n'
                            'execve("/absent", ["absent"], 0x0) = -1 ENOENT\n'
                            'clone(child_stack=NULL, flags=SIGCHLD) = 2\n'
                            'clone3({}, 88) = -1 ENOSYS\n'
                            'write(1</case/payload/out>, "abc", 3) = 3\n'
                            'write(2</case/observations>, "x", 1) = 1\n'
                            'write(3</case/payload/no>, "x", 1) = -1 ENOSPC\n'
                            'writev(4</case/payload/gone (deleted)>, [], 2) = 5\n'
                            'sendfile(5</case/payload/copy>, 6</source>, NULL, 12) = 12\n')
            got = measure.trace_counts([path], Path('/case/payload'))
            self.assertEqual(got['executable_launches'], 1)
            self.assertEqual(got['process_creations'], 1)
            self.assertEqual(got['workspace_write_bytes'], 20)
            self.assertEqual(got['executables'], {'sh': 1})

    def test_source_extraction_fails_closed(self):
        with self.assertRaises(ValueError):
            measure.extract_function('different() { :; }', 'wanted')
        source = 'wanted()\n{\n    :\n}\nother()\n{\n    false\n}\n'
        self.assertNotIn('other', measure.extract_function(source, 'wanted'))

    def test_bounds(self):
        for size in (0, 2001):
            with self.assertRaises(ValueError):
                measure.validate_bounds([size], 1, 30)
        for repeat in (0, 6):
            with self.assertRaises(ValueError):
                measure.validate_bounds([8, 300], repeat, 30)
        with self.assertRaises(ValueError):
            measure.validate_bounds([8], 1, 61)

    def test_fixture_has_unique_equal_populations(self):
        config, names, routes = measure.fixture(300)
        self.assertEqual(len(set(names)), 300)
        self.assertEqual(len(set(routes)), 300)
        self.assertEqual(config.count('    include '), 600)
        self.assertEqual(config.count('ip route '), 300)

    def test_rss_parser_rejects_unavailable_metrics(self):
        self.assertEqual(measure.parse_time_rss('1536\n'), 1536)
        for value in ('', '0\n', 'unavailable\n'):
            with self.assertRaises(ValueError):
                measure.parse_time_rss(value)


if __name__ == '__main__':
    unittest.main()
