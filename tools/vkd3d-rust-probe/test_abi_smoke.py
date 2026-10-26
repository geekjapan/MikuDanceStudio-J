import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import abi_smoke


class AbiSmokeTests(unittest.TestCase):
    def test_existing_output_is_refused_without_changing_old_files(self):
        for stale in (False, True):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'owned'
                root.mkdir()
                if stale:
                    (root / 'rust').mkdir()
                    (root / 'rust/translated.c_decls.json').write_text('{"definitions": {"native_callback": {}}}')
                    (root / 'rust/translated.rs').write_text('extern "win64" fn f() {} extern "C" fn g() {}')
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                translator = Path(directory) / 'c2rust-transpile'
                translator.write_text('#!/bin/sh\nexit 0\n')
                translator.chmod(0o755)
                with patch.object(sys, 'argv', ['abi_smoke.py', '--c2rust', str(Path(directory) / 'c2rust'),
                                                '--artifacts', str(root)]):
                    with self.assertRaises(FileExistsError):
                        abi_smoke.main()
                after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertEqual(before, after)

    def test_exit_zero_translator_without_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            translator = root / 'c2rust-transpile'
            translator.write_text('#!/bin/sh\nexit 0\n')
            translator.chmod(0o755)
            with patch.object(sys, 'argv', ['abi_smoke.py', '--c2rust', str(root / 'c2rust'),
                                            '--clang', '/usr/bin/true', '--artifacts', str(root / 'owned')]):
                self.assertEqual(abi_smoke.main(), 1)
            result = json.loads((root / 'owned/result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertEqual(set(result['stages']), {'clang-ast', 'transpile'})

    def test_failed_rust_build_aborts_before_link_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "owned"
            calls = []

            def execute(command, log, **kwargs):
                name = log.stem
                calls.append(name)
                log.write_text('fixture\n')
                if name == 'transpile':
                    (root / 'rust').mkdir()
                    (root / 'rust/translated.c_decls.json').write_text('{"definitions": {"native_callback": {}}}')
                    (root / 'rust/translated.rs').write_text('extern "win64" fn f() {} extern "C" fn g() {}')
                return {'exit_code': 1 if name == 'rust-build' else 0}

            with patch.object(sys, 'argv', ['abi_smoke.py', '--c2rust', str(root / 'c2rust'),
                                            '--artifacts', str(root)]):
                with patch.object(abi_smoke, 'run', side_effect=execute):
                    self.assertEqual(abi_smoke.main(), 1)
            result = json.loads((root / 'result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertEqual(calls, ['clang-ast', 'transpile', 'rust-build'])


if __name__ == '__main__':
    unittest.main()
