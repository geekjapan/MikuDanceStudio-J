"""Measured profile controls reject producer, transport, and semantic drift."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import check
import measured_profiles
from test_capture import mutations


class MeasuredProfileTests(unittest.TestCase):
    def test_x64_fixture_has_only_measured_nine_words(self):
        fixture = check.ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
        baseline = (fixture / 'native.tsv').read_bytes()
        x64 = (fixture / 'native-x64.tsv').read_bytes()
        expected = [[case, 'query.axis.' + axis, '7fc00000', 'ffc00000']
                    for case in [1252, 1253, 1411] for axis in 'xyz']
        self.assertEqual(check.inventory(baseline, x64, 1800), expected)
        manifest = json.loads(Path(measured_profiles.__file__).with_name('measured-profiles.json').read_text())
        self.assertEqual(set(manifest['profiles']), {'macos-arm64', 'linux-arm64', 'linux-x64', 'windows-x64'})
        for host, profile in manifest['profiles'].items():
            self.assertEqual(profile['exact_frozen_compact_differences'], expected if host.endswith('x64') else [])
            self.assertEqual(len(profile['streams']), 12)
            self.assertEqual(set(profile['commands']), {'native-command.json', 'effective-native-command.json', 'observed-command.json'})

    def test_windows_fixture_and_test_source_keep_binary_checkout_transport(self):
        manifest = json.loads(Path(measured_profiles.__file__).with_name('measured-profiles.json').read_text())
        for name in ['rust/crates/mds-bullet/tests/gjk_pair_data/native-x64.tsv',
                     'rust/crates/mds-bullet/tests/pure_bullet/gjk_pair.rs']:
            self.assertEqual(manifest['verification_sha256']['windows-x64'][name],
                             measured_profiles.sha((check.ROOT / name).read_bytes()))

    def test_unknown_host_and_changed_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(check, 'host', return_value='unknown'):
                with self.assertRaisesRegex(ValueError, 'Unknown'):
                    measured_profiles.validate(Path(temp), host=check.host, inventory=check.inventory,
                                               source_hashes=check.source_hashes, stream=check.stream,
                                               transport=check.transport)
            with patch.object(check, 'host', return_value='macos-arm64'), patch.object(check, 'source_hashes', return_value={}):
                with self.assertRaisesRegex(ValueError, 'source closure'):
                    measured_profiles.validate(Path(temp), host=check.host, inventory=check.inventory,
                                               source_hashes=check.source_hashes, stream=check.stream,
                                               transport=check.transport)

    def test_cli_main_with_support_first_reaches_real_validator(self):
        script = textwrap.dedent("""
            import ast
            import importlib.util
            from pathlib import Path
            import sys
            outer = Path(sys.argv[1]).resolve()
            output = Path(sys.argv[2])
            sys.path.insert(0, str(outer.parent))
            spec = importlib.util.spec_from_file_location('__main__', outer)
            module = importlib.util.module_from_spec(spec)
            sys.modules['__main__'] = module
            sys.argv = [str(outer), '--help']
            try:
                spec.loader.exec_module(module)
            except SystemExit as error:
                assert error.code == 0
            assert Path(sys.path[0]).name == 'bullet-rust-support-check'
            import check
            assert Path(check.__file__).parent.name == 'bullet-rust-support-check'
            from measured_profiles import validate
            capture = next(node for node in ast.parse(outer.read_text()).body
                           if isinstance(node, ast.FunctionDef) and node.name == 'capture')
            call, = [node for node in ast.walk(capture) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'validate']
            # Evaluate the production call with its real __main__ globals and validator.
            expression = compile(ast.Expression(call), str(outer), 'eval')
            scope = dict(vars(module), validate=validate, output=output)
            try:
                eval(expression, scope)
            except ValueError as error:
                assert str(error) == 'Outer GJK compiler or toolchain differs from measured profile', str(error)
                print('real validator rejected compiler drift')
            else:
                raise AssertionError('Compiler drift was accepted')
        """)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'provenance.txt').write_text('deliberately unreviewed compiler')
            result = subprocess.run([sys.executable, '-c', script, check.__file__, temp],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('real validator rejected compiler drift', result.stdout)

    def test_command_root_relocation_keeps_every_flag(self):
        command = ['cl', '/O2', '/fp:precise', '/IC:\\repo\\shim', '/Fe:C:\\out\\native.exe']
        expected = ['cl', '/O2', '/fp:precise', '/I$ROOT/shim', '/Fe:$CAPTURE/native.exe']
        self.assertEqual(measured_profiles.canonical_command(command, 'C:/repo', 'C:/out'), expected)
        command[2] = '/fp:fast'
        self.assertNotEqual(measured_profiles.canonical_command(command, 'C:/repo', 'C:/out'), expected)

    def test_baseline_requires_intended_test_and_no_filtered_or_ignored_tests(self):
        good = f'test {mutations.TEST} ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;'
        self.assertEqual(mutations.classify(SimpleNamespace(returncode=0, stdout=good, stderr=''))['status'], 'passed')
        for broken in [good.replace('0 filtered', '3 filtered'), good.replace('0 ignored', '1 ignored'), good.replace(mutations.TEST, 'other')]:
            self.assertEqual(mutations.classify(SimpleNamespace(returncode=0, stdout=broken, stderr=''))['status'], 'validation-gap')


if __name__ == '__main__':
    unittest.main()
