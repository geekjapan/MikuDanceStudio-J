import json
import shutil
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
                    shutil.copytree(Path(__file__).parent / 'abi-fixtures/generated', root / 'rust')
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

    def test_actual_generated_layout_reaches_build_link_and_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'owned'
            calls = []

            def execute(command, log, **kwargs):
                calls.append(log.stem)
                if log.stem == 'transpile':
                    shutil.copytree(Path(__file__).parent / 'abi-fixtures/generated', root / 'rust')
                if log.stem == 'rust-build':
                    self.assertEqual(Path(command[6]), (root / 'rust/src/translated.rs').resolve())
                    self.assertTrue(Path(command[6]).is_file())
                log.write_text('C to Rust Win64 direct/vtable 204; Rust to C Win64 direct/vtable/NoProto 120; C ABI 86\n')
                return {'exit_code': 0}

            with patch.object(sys, 'argv', ['abi_smoke.py', '--c2rust', str(root / 'c2rust'),
                                            '--artifacts', str(root)]):
                with patch.object(abi_smoke, 'run', side_effect=execute):
                    self.assertEqual(abi_smoke.main(), 0)
            self.assertEqual(calls, ['clang-ast', 'transpile', 'rust-build', 'c-link', 'abi-run'])
            self.assertEqual(json.loads((root / 'result.json').read_text())['status'], 'success')

    def test_missing_ambiguous_or_outside_generated_files_fail_before_build(self):
        for invalid in ('source-missing', 'map-missing', 'source-duplicate', 'map-duplicate',
                        'old-layout', 'source-outside', 'map-outside'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'owned'
                calls = []

                def execute(command, log, **kwargs):
                    calls.append(log.stem)
                    log.write_text('fixture\n')
                    if log.stem == 'transpile':
                        shutil.copytree(Path(__file__).parent / 'abi-fixtures/generated', root / 'rust')
                        name = 'translated.c_decls.json' if invalid.startswith('map-') else 'translated.rs'
                        path = root / 'rust/src' / name
                        if invalid.endswith('missing'):
                            path.unlink()
                        elif invalid.endswith('duplicate'):
                            shutil.copy2(path, root / 'rust' / name)
                        elif invalid == 'old-layout':
                            for child in path.parent.iterdir():
                                child.rename(root / 'rust' / child.name)
                        else:
                            outside = Path(directory) / name
                            path.rename(outside)
                            path.symlink_to(outside)
                    return {'exit_code': 0}

                with patch.object(sys, 'argv', ['abi_smoke.py', '--c2rust', str(root / 'c2rust'),
                                                '--artifacts', str(root)]):
                    with patch.object(abi_smoke, 'run', side_effect=execute):
                        self.assertEqual(abi_smoke.main(), 1)
                self.assertEqual(calls, ['clang-ast', 'transpile'])
                result = json.loads((root / 'result.json').read_text())
                self.assertIn('generated output', result['error'])

    def test_failed_rust_build_aborts_before_link_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "owned"
            calls = []

            def execute(command, log, **kwargs):
                name = log.stem
                calls.append(name)
                log.write_text('fixture\n')
                if name == 'transpile':
                    shutil.copytree(Path(__file__).parent / 'abi-fixtures/generated', root / 'rust')
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
