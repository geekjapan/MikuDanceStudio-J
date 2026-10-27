"""Cheap checks for command construction and profile acceptance boundaries."""
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
import json
import sys
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def profile(selected, win32='0', sse='0', template='0'):
    return (f'DBVT_SELECT_IMPL={selected}\nDBVT_MERGE_IMPL={selected}\n'
            f'DBVT_INT0_IMPL={selected}\nWIN32={win32}\nBT_USE_SSE={sse}\n'
            f'DBVT_USE_TEMPLATE={template}\nBT_HAS_ALIGNED_ALLOCATOR=0\n'
            'BT_USE_DOUBLE_PRECISION=0\n').encode()


class HelperTests(unittest.TestCase):
    def test_msvc_profiles_do_not_share_win32_definition(self):
        output = Path('out') / 'oracle.exe'
        for diagnostic in (False, True):
            command = check.native_command('cl', ['oracle.cpp'], output,
                                           msvc=True, ffi_default=diagnostic)
            self.assertIn('/fp:precise', command)
            self.assertIn('/MD', command)
            self.assertIn('/EHsc', command)
            self.assertIn('/O2', command)
            self.assertEqual('/DWIN32' in command, not diagnostic)
            self.assertEqual(any(str(x).startswith('/FI') for x in command), diagnostic)
            self.assertEqual(command[-1], f'/Fe{output}')
            self.assertFalse(any('BT_HAS_ALIGNED_ALLOCATOR' in str(x) for x in command))

    def test_generic_command_keeps_compiler_argument_paths(self):
        command = check.native_command('clang++', ['path with spaces/oracle.cpp'], Path('out/oracle'), msvc=False)
        self.assertIn('path with spaces/oracle.cpp', command)
        self.assertIn('-ffp-contract=off', command)
        self.assertNotIn('/DWIN32', command)

    def test_profile_mismatch_fails(self):
        check.validate_profile(profile('0'), 'generic')
        check.validate_profile(profile('1', '1', '1', '1'), 'sse')
        check.validate_profile(profile('0', sse='1'), 'generic', ffi_default=True)
        for data, expected, diagnostic in [
            (profile('0'), 'sse', False),
            (profile('1', '1', '1', '1'), 'generic', False),
            (profile('0'), 'generic', True),
            (profile('0').replace(b'BT_HAS_ALIGNED_ALLOCATOR=0', b'BT_HAS_ALIGNED_ALLOCATOR=1'), 'generic', False),
        ]:
            with self.assertRaises(AssertionError):
                check.validate_profile(data, expected, ffi_default=diagnostic)

    def test_select_profiles_are_observably_different(self):
        generic = b'x\nx\nstate|B,0(B,0(1,0;3,0);2,0)|rank|\nx\n'
        sse = b'x\nx\nstate|B,0(1,0;B,0(2,0;3,0))|rank|\nx\n'
        check.validate_select(generic, 'generic')
        check.validate_select(sse, 'sse')
        with self.assertRaises(AssertionError):
            check.validate_select(generic, 'sse')

    def test_failed_process_preserves_logs_and_command(self):
        import sys
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with self.assertRaises(subprocess.CalledProcessError):
                check.run([sys.executable, '-c', 'print("diagnostic"); raise SystemExit(7)'], out, 'failure', capture=True)
            self.assertIn(b'diagnostic', (out / 'failure-stdout.log').read_bytes())
            self.assertTrue((out / 'failure-command.json').is_file())

    def test_process_cwd_and_output_capture(self):
        command = [sys.executable, '-c',
                   'import os, sys; print(os.getcwd()); print("diagnostic", file=sys.stderr)']
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory).resolve()
            for cwd in (check.ROOT, out):
                for capture in (False, True):
                    with self.subTest(cwd=cwd, capture=capture):
                        stdout, stderr = io.StringIO(), io.StringIO()
                        kwargs = {} if cwd == check.ROOT else {'cwd': cwd}
                        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            data = check.run(command, out, 'cwd', capture=capture, **kwargs)
                        self.assertEqual(data.decode().strip(), str(cwd))
                        self.assertEqual((out / 'cwd-stdout.log').read_bytes(), data)
                        self.assertEqual((out / 'cwd-stderr.log').read_bytes().strip(), b'diagnostic')
                        self.assertEqual(json.loads((out / 'cwd-command.json').read_text()), command)
                        self.assertEqual(stdout.getvalue(), check.subprocess.list2cmdline(command) + '\n'
                                         + ('' if capture else data.decode() + '\n'))
                        self.assertEqual(stderr.getvalue(), (out / 'cwd-stderr.log').read_bytes().decode() + '\n')


    def test_all_profile_fields_and_short_select_are_rejected(self):
        valid = profile('1', '1', '1', '1')
        for line in valid.splitlines():
            key, value = line.split(b'=')
            broken = valid.replace(line, key + b'=' + (b'0' if value == b'1' else b'1'))
            with self.subTest(key=key), self.assertRaises(AssertionError):
                check.validate_profile(broken, 'sse')
        for rows in [b'', b'x\nx\nx\n']:
            with self.subTest(rows=rows), self.assertRaisesRegex(AssertionError, 'incomplete directed Select capture'):
                check.validate_select(rows, 'generic')

    def test_corpus_preserves_prefix_and_requires_extension(self):
        data = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        self.assertEqual(check.validate_corpus(data), 2355)
        self.assertEqual(check.validate_corpus(data.replace(b'\n', b'\r\n')), 2355)
        for broken in [b'bad\n' + data, b''.join(data.splitlines(keepends=True)[:2326])]:
            with self.assertRaisesRegex(ValueError, 'frozen operation prefix'):
                check.validate_corpus(broken)

    def test_explicit_numeric_driver_and_capture_wrappers(self):
        source = check.reference_module().RUST_DRIVER
        self.assertIn('Some("mmd-win64-sse")', source)
        self.assertIn('Some("generic-reference")', source)
        self.assertIn('policy.intersects(a, b)', source)
        self.assertNotIn('cfg!', source)
        fixtures = (check.HERE / 'fixtures.rs').read_text()
        for name in ['native_controlled_address_parity', 'ordinary_native_and_production_allocator_query_sets']:
            self.assertIn(f'fn {name}(policy: DbvtPolicy)', fixtures)
            self.assertNotIn(f'#[test]\nfn {name}', fixtures)
            self.assertIn(f'#[test]\nfn {name}', (check.HERE / 'test.rs').read_text())

    def numeric_policy_run(self, out, *, select=None, numeric=None):
        fixtures = check.ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
        captured = (fixtures / 'inline-aabb.tsv').read_bytes()
        generic = captured.splitlines()
        for index in range(27, 51):
            words = generic[index].split(b',')
            words[1] = b'0' if words[1] == b'1' else b'1'
            generic[index] = b','.join(words)
        outputs = {'mmd-win64-sse-numeric': captured,
                   'generic-reference-numeric': b'\n'.join(generic) + b'\n',
                   'mmd-win64-sse-select': b'3,2,1,\n',
                   'generic-reference-select': b'2,3,1,\n'}
        outputs.update(select or {})
        outputs.update(numeric or {})

        def run(command, directory, name, **kwargs):
            if name == 'numeric-build':
                Path(command[-1]).write_bytes(b'mocked numeric binary')
            return outputs.get(name, b'')

        with patch.object(check, 'run', side_effect=run) as mocked:
            check.verify_numeric_policies(out)
        return mocked

    def test_numeric_policies_reject_invalid_select_for_both_policies(self):
        for policy in check.POLICIES.values():
            wrong = b'2,3,1,\n' if policy == 'mmd-win64-sse' else b'1,2,3,\n'
            for data in (b'', b'2,3,', b'1,1,2,\n', b'bad\n',
                         b'2,3,1,\nextra\n', wrong):
                with self.subTest(policy=policy, data=data), tempfile.TemporaryDirectory() as directory:
                    out = Path(directory)
                    with self.assertRaises(ValueError):
                        self.numeric_policy_run(out, select={policy + '-select': data})
                    self.assertFalse((out / 'numeric-policy-results.json').exists())

    def test_numeric_policies_keep_full_schema_and_exact_mismatch_cases(self):
        fixtures = check.ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
        captured = (fixtures / 'inline-aabb.tsv').read_bytes()
        rows = captured.splitlines()
        for policy in check.POLICIES.values():
            for data in (b'', b'\n'.join(rows[:-1]) + b'\n',
                         captured.replace(b',', b',bad,', 1),
                         b'\n'.join([rows[0] + b',0', *rows[1:]]) + b'\n',
                         b'\n'.join([rows[0], rows[0], *rows[2:]]) + b'\n'):
                with self.subTest(policy=policy, data=data[:40]), tempfile.TemporaryDirectory() as directory:
                    out = Path(directory)
                    with self.assertRaises(ValueError):
                        self.numeric_policy_run(out, numeric={policy + '-numeric': data})
                    self.assertFalse((out / 'numeric-policy-results.json').exists())
        for changed in (range(26, 51), range(28, 51), []):
            generic = rows.copy()
            for index in changed:
                words = generic[index].split(b',')
                words[1] = b'0' if words[1] == b'1' else b'1'
                generic[index] = b','.join(words)
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'expected semantic mismatches'):
                    self.numeric_policy_run(Path(directory), numeric={
                        'generic-reference-numeric': b'\n'.join(generic) + b'\n'})

    def test_numeric_policies_accept_exact_policy_results(self):
        for ending in (b'\n', b'\r\n'):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                mocked = self.numeric_policy_run(out, select={
                    'mmd-win64-sse-select': b'3,2,1,' + ending,
                    'generic-reference-select': b'2,3,1,' + ending})
                results = json.loads((out / 'numeric-policy-results.json').read_text())
                self.assertEqual(results, {
                    'mmd-win64-sse': {'numeric_mismatch_cases': [], 'select_matches': True},
                    'generic-reference': {'numeric_mismatch_cases': list(range(27, 51)), 'select_matches': False}})
                binary = json.loads((out / 'numeric-binary.json').read_text())
                self.assertEqual(binary['sha256'], check.hashlib.sha256(b'mocked numeric binary').hexdigest())
                self.assertEqual(binary['source_sha256'], check.hashlib.sha256((out / 'numeric.rs').read_bytes()).hexdigest())
                self.assertEqual(binary['build_command'], 'numeric-build-command.json')
                self.assertEqual([call.args[2] for call in mocked.call_args_list], [
                    'numeric-crt-build', 'numeric-math-build', 'numeric-build',
                    'mmd-win64-sse-numeric', 'mmd-win64-sse-select',
                    'generic-reference-numeric', 'generic-reference-select'])
                for call in mocked.call_args_list[3:]:
                    policy, kind = call.args[2].rsplit('-', 1)
                    self.assertEqual(call.args[0][1:], [policy, 'aabb' if kind == 'numeric' else 'select'])

    def test_replay_rejects_incomplete_or_foreign_captures_before_running_rust(self):
        inputs = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        with tempfile.TemporaryDirectory() as directory:
            captures = Path(directory)
            (captures / 'inputs.tsv').write_bytes(inputs)
            for order in range(4):
                (captures / f'native-{order}.tsv').write_bytes(b'')
            with patch.object(check, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'incomplete Windows-sourced'):
                    check.replay(captures, captures)
                for order in range(4):
                    (captures / f'native-{order}.tsv').write_bytes(b'unit-control\n' * 2355)
                (captures / 'provenance.json').write_text(json.dumps({'commit': 'foreign-checkout'}))
                with self.assertRaisesRegex(ValueError, 'source commit differs'):
                    check.replay(captures, captures)
                run.assert_not_called()

    def test_actual_windows_fixture_bytes_match_provenance(self):
        fixtures = check.ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
        provenance = json.loads((fixtures / 'provenance.json').read_text())
        self.assertEqual(provenance['run_id'], 40465192152)
        self.assertEqual(provenance['zip_sha256'], '4d3247c287eee3e3040f06efe64a60600c3740f947220f8427c8534b5fbc5ecf')
        for name, item in provenance['members'].items():
            self.assertEqual(check.hashlib.sha256((fixtures / name).read_bytes()).hexdigest(), item['sha256'])
        reference = check.reference_module()
        self.assertEqual(len(reference.rows((fixtures / 'inline-aabb.tsv').read_bytes(), 13)), 51)
        for width, name in [(12, 'archive-merge.tsv'), (1, 'archive-intersect.tsv')]:
            self.assertEqual(len(reference.rows((fixtures / name).read_bytes(), width)), 51)



if __name__ == '__main__':
    unittest.main()
