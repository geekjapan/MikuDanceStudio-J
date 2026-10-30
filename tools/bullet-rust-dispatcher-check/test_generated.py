import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import check
from observe import copy_rust, instrument_rust


class GeneratedTests(unittest.TestCase):
    def test_exact_membership_and_raw_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'generated-sources'
            source.mkdir()
            cpp = source / 'observer.cpp'
            cpp.write_bytes(b'#include "btCollisionDispatcher.h"\n')
            before = check.generated_snapshot(source)
            # The old named-key rehash missed newly searchable headers.
            old = {str(cpp): hashlib.sha256(cpp.read_bytes()).hexdigest()}
            header = source / 'btCollisionDispatcher.h'
            header.write_bytes(b'#error shadow\n')
            self.assertEqual(old, {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in old})
            self.assertNotEqual(before, check.generated_snapshot(source))
            header.unlink()
            self.assertEqual(before, check.generated_snapshot(source))
            cpp.write_bytes(b'#include "btCollisionDispatcher.h"\r\n')
            self.assertNotEqual(before, check.generated_snapshot(source))
            cpp.unlink()
            self.assertNotEqual(before, check.generated_snapshot(source))
            (root / 'compiler.stdout').write_bytes(b'log')
            (root / 'original.exe').write_bytes(b'binary')
            self.assertEqual({}, check.generated_snapshot(source))

    def test_finally_records_added_replaced_and_deleted_sources_on_failure(self):
        for change in ['add', 'replace', 'delete', 'none']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)
                def fail(command, **kwargs):
                    tree = out / 'generated-sources'
                    cpp = tree / 'btCollisionDispatcher.cpp'
                    if change == 'add': (tree / 'btCollisionDispatcher.h').write_bytes(b'#error shadow\n')
                    if change == 'replace': cpp.write_bytes(cpp.read_bytes() + b'\r\n')
                    if change == 'delete': cpp.unlink()
                    return subprocess.CompletedProcess(command, 1, b'', b'intentional failure')
                error = RuntimeError if change == 'none' else AssertionError
                with patch.object(sys, 'argv', ['check.py', '--out-dir', str(out)]), patch.object(check.subprocess, 'run', side_effect=fail), patch.object(check.platform, 'platform', return_value='test-host'):
                    with self.assertRaises(error): check.main()
                before = json.loads((out / 'generated-producers-start.json').read_text())
                after = json.loads((out / 'generated-producers-finally.json').read_text())
                status = json.loads((out / 'status.json').read_text())
                self.assertEqual(status['status'], 'FAIL')
                self.assertEqual(before == after, change == 'none')
                self.assertEqual(status['integrity'], 'PASS' if change == 'none' else 'FAIL')

    def test_observer_copy_changes_only_dispatcher_instrumentation(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            destination = out / 'generated-sources'
            runner = copy_rust(check.ROOT, destination, out / 'observer.diff')
            self.assertEqual(runner.read_bytes(), (check.HERE / 'runner.rs').read_bytes())
            core = Path('rust/crates/mds-bullet/src/core')
            for source in (check.ROOT / core).rglob('*.rs'):
                copied = destination / source.relative_to(check.ROOT)
                expected = instrument_rust(source.read_text()) if source.name == 'dispatcher.rs' else source.read_text()
                self.assertEqual(copied.read_text(), expected)
            self.assertNotIn('observer.diff', check.generated_snapshot(destination))

    def test_include_measurement_parses_both_compilers(self):
        with tempfile.TemporaryDirectory() as temporary:
            header = Path(temporary) / 'space here.h'
            header.write_bytes(b'')
            self.assertEqual(check.include_paths(f'.. {header}\n'.encode()), [header.resolve()])
            self.assertEqual(check.include_paths(f'Note: including file:  {header}\r\n'.encode(), True), [header.resolve()])


if __name__ == '__main__': unittest.main()
