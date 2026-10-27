"""Capture failure paths retain evidence without approving numerical differences."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import check
spec = importlib.util.spec_from_file_location("outer_mutations", Path(__file__).with_name("mutations.py"))
mutations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutations)
from host_profiles import fields, rows

FIXTURE = check.ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'


class CaptureTests(unittest.TestCase):
    def test_all_frozen_variable_width_rows(self):
        for filename, count, start in [('native.tsv', 1800, 0), ('fallback-native.tsv', 6, 5075)]:
            data = (FIXTURE / filename).read_bytes()
            self.assertEqual(len(rows(data, 'gjk-pair', count, start)), count)
        contact = ['00000000'] * 21 + ['1', '0']
        base = ['0', '0', '-1', '0', '0'] + ['00000000'] * 4
        for count in range(5):
            for lateral in [0, 1]:
                record = contact[:-1] + [str(lateral)] + ['00000000'] * (6 * lateral)
                words = base + [str(count), '00000000'] + record * count
                self.assertEqual(len(fields('gjk-pair', words)), len(words) - 1)
                with self.assertRaises(ValueError):
                    fields('gjk-pair', words + ['00000000'])
        for index, value in [(1, '2'), (2, '10'), (3, '-1'), (4, '13'), (5, 'nan'), (9, '5')]:
            words = base + ['0', '00000000']
            words[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                fields('gjk-pair', words)

    def test_transport_is_recorded_without_numeric_changes(self):
        lf = (FIXTURE / 'native.tsv').read_bytes()
        for data, ending in [(lf, 'LF'), (lf.replace(b'\n', b'\r\n'), 'CRLF')]:
            text, facts = check.stream(data, 1800)
            self.assertEqual(text, lf)
            self.assertEqual(facts['line_ending'], ending)
        for data in [lf[:-1], lf.replace(b'\n', b'\r\n', 1), lf + b'\n']:
            with self.assertRaises(ValueError):
                check.stream(data, 1800)
        for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']:
            changed = lf.replace(b'00000000', word, 1)
            self.assertTrue(check.inventory(lf, changed, 1800))

    def test_generated_input_transport_preserves_raw_and_frozen_binding(self):
        generated = subprocess.check_output([sys.executable, Path(check.__file__).with_name('cases.py')]).replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(generated).hexdigest(),
                         'c2d062c601c5cc2a8f9cbf269fb3aec3974511d70d2a7003719c9cf953091522')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for ending, label in [(b'\n', 'LF'), (b'\r\n', 'CRLF')]:
                raw = generated.replace(b'\n', ending)
                self.assertEqual(check.capture_inputs(output, raw), generated)
                self.assertEqual((output / 'inputs.tsv').read_bytes(), raw)
                facts = json.loads((output / 'input-transport.json').read_text())
                for filename, count in [('inputs.tsv', 5081), ('compact-inputs.tsv', 1800), ('fallback-inputs.tsv', 6)]:
                    data = (output / filename).read_bytes()
                    self.assertEqual(facts[filename]['rows'], count)
                    self.assertEqual(facts[filename]['line_ending'], label)
                    self.assertEqual(facts[filename]['raw_sha256'], hashlib.sha256(data).hexdigest())
                    self.assertEqual(facts[filename]['lf_sha256'], hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest())
                for filename, frozen in [('compact-inputs.tsv', 'inputs.tsv'), ('fallback-inputs.tsv', 'fallback-inputs.tsv')]:
                    self.assertEqual((output / filename).read_bytes().replace(b'\r\n', b'\n'), (FIXTURE / frozen).read_bytes())
                if label == 'CRLF':
                    self.assertEqual(facts['inputs.tsv']['raw_sha256'],
                                     '48f581294a697e2cf9961fa3c77abe7f0fc7223fa15310a283c2f9f8a123836a')
            lines = generated.splitlines(keepends=True)
            changed_last = lines[-1].split(b'\t')
            changed_last[4] = b'80000000' if changed_last[4] != b'80000000' else b'00000000'
            corruptions = [generated[:-1], generated + b'\n', generated.replace(b'\n', b'\r\n', 1),
                           generated.replace(b'\n', b'\r', 1), generated.replace(b'\n', b'\r\r\n', 1),
                           b''.join(lines[:-1]), generated.replace(b'\t', b' ', 1),
                           generated.replace(b'00000000', b'80000000', 1),
                           b''.join([lines[1], lines[0], *lines[2:]]),
                           b''.join([lines[0], lines[0], *lines[2:]]),
                           b''.join(lines[:-1]) + b'\t'.join(changed_last)]
            for index, broken in enumerate(corruptions):
                with self.subTest(index=index), self.assertRaises((ValueError, AssertionError)):
                    check.capture_inputs(output, broken)
                self.assertEqual((output / 'inputs.tsv').read_bytes(), broken)

    def test_failure_always_records_integrity_and_unknown_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'capture'
            with patch.object(check.sys, 'argv', ['check.py', '--out-dir', str(output)]), patch.object(check, 'capture', side_effect=ValueError('deliberate compile failure')):
                with self.assertRaisesRegex(ValueError, 'deliberate'):
                    check.main()
            self.assertTrue(json.loads((output / 'integrity.json').read_text())['source_and_fixtures_unchanged'])
            facts = json.loads((output / 'host-profile.json').read_text())
            self.assertEqual(facts['collection'], 'incomplete')
            self.assertEqual(facts['compatibility'], 'FAIL')
            self.assertFalse(facts['profile_known'])
            self.assertEqual(facts['mutations'], 'not-run')
            self.assertIn('source-before.json', json.loads((output / 'sha256.json').read_text()))

    def test_complete_collection_still_fails_unknown_profile(self):
        compact = (FIXTURE / 'native.tsv').read_bytes()
        last = compact.splitlines()[-1].split(b'\t', 1)[1]
        full = compact + b''.join(str(i).encode() + b'\t' + last + b'\n' for i in range(1800, 5075))
        full += (FIXTURE / 'fallback-native.tsv').read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for implementation in ['native', 'observed', 'rust']:
                for prefix, data in [('', full), ('compact-', compact), ('fallback-', (FIXTURE / 'fallback-native.tsv').read_bytes())]:
                    (output / f'{prefix}{implementation}.tsv').write_bytes(data)
            facts = check.audit(output)
            self.assertEqual(facts['collection'], 'complete')
            self.assertEqual(facts['compatibility'], 'FAIL')
            self.assertEqual(len(facts['streams']), 9)
            self.assertFalse(facts['profile_known'])
            self.assertEqual(facts['native_rust_differences'], [])
            changed = full.replace(b'00000000', b'ffc00000', 1)
            (output / 'rust.tsv').write_bytes(changed)
            facts = check.audit(output)
            self.assertEqual(facts['collection'], 'complete')
            self.assertEqual(facts['compatibility'], 'FAIL')
            self.assertTrue(facts['native_rust_differences'])

    def test_failing_baseline_prevents_mutant_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            argv = ['mutations.py', '--out-dir', temp, '--crt-rlib', temp + '/crt.rlib',
                    '--inputs', str(FIXTURE / 'inputs.tsv'), '--native', str(FIXTURE / 'native.tsv')]
            with patch.object(mutations.sys, 'argv', argv), patch.object(mutations, 'run_harness', return_value={'status': 'validation-gap'}) as run:
                with self.assertRaisesRegex(SystemExit, 'Mandatory baseline-default failed'):
                    mutations.main()
            self.assertEqual(run.call_count, 1)
            self.assertFalse(any(k.startswith('MDS_GJK_PAIR_') for k in run.call_args.args[-1]))

    def test_compile_failure_and_generated_path_are_validation_gaps(self):
        with tempfile.TemporaryDirectory(prefix='outer spaces 日本-') as temp:
            directory = Path(temp)
            with patch.object(mutations.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='compile failed')):
                result = mutations.run_harness('contact', (check.ROOT / 'rust/crates/mds-bullet/src/core/contact.rs').read_text(), directory, directory / 'crt.rlib', {})
            self.assertEqual(result['status'], 'validation-gap')
            self.assertEqual(result['reason'], 'compile-failure')
            harness = (directory / 'harness.rs').read_text(encoding='utf-8')
            for path in __import__('re').findall(r'#\[path = ("(?:\\.|[^"\\])*")\]', harness):
                self.assertTrue(Path(json.loads(path)).is_file())

    def test_windows_valid_unicode_and_virtual_quoted_paths_compile(self):
        with tempfile.TemporaryDirectory(prefix='outer spaces 日本-') as temp:
            directory = Path(temp)
            module = directory / 'module 日本.rs'
            module.write_text('pub const VALUE: u8 = 1;\n', encoding='utf-8')
            quoted = PureWindowsPath('C:/space 日本/with "quotes"/module.rs')
            source = directory / 'paths.rs'
            source.write_text(f'#[path = {mutations.rust_path_literal(module)}] mod module;\n'
                              f'const PATH: &str = {mutations.rust_path_literal(quoted)};\n', encoding='utf-8')
            result = subprocess.run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021',
                                     '--crate-type=lib', '--emit=metadata', str(source),
                                     '-o', str(directory / 'paths.rmeta')], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((directory / 'paths.rmeta').is_file())
            self.assertEqual(json.loads(mutations.rust_path_literal(quoted)), quoted.as_posix())

    def test_existing_workflow_caller_keeps_log_outside_capture(self):
        workflow = (check.ROOT / '.github/workflows/bullet-primitives.yml').read_text()
        block = workflow.split('      - name: Recapture outer GJK and mixed persistent manifolds\n', 1)[1].split('      - name:', 1)[0]
        commands = block.split('        run: |\n', 1)[1]
        self.assertIn('set -o pipefail', commands)
        with tempfile.TemporaryDirectory(prefix='outer caller 日本 ') as temp:
            root = Path(temp)
            injected = root / 'bin'
            injected.mkdir()
            launcher = injected / 'python3'
            launcher.write_text('#!' + sys.executable + '\nimport sys\nsys.path.insert(0, ' + repr(str(Path(check.__file__).parent)) + ')\n'
                                'import check\nfrom unittest.mock import patch\ndel sys.argv[1]\n'
                                'with patch.object(check, "capture", side_effect=ValueError("caller reached capture")):\n    check.main()\n')
            launcher.chmod(0o755)
            # The workflow uses bash on Linux, so exercise its exact shell commands there.
            if os.name != 'nt':
                environment = dict(os.environ, RUNNER_TEMP=temp, PATH=str(injected) + os.pathsep + os.environ['PATH'])
                old_environment = dict(environment, RUNNER_TEMP=str(root / 'old'))
                old_commands = commands.replace('gjk-pair-check.log', 'gjk-pair/check.log')
                old_result = subprocess.run(['bash', '-c', old_commands], env=old_environment, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(old_result.returncode, 0)
                self.assertIn('Capture directory must be empty', old_result.stdout)
                self.assertFalse((root / 'old/bullet-native/gjk-pair/integrity.json').exists())
                result = subprocess.run(['bash', '-c', commands], env=environment, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                capture = root / 'bullet-native/gjk-pair'
                self.assertTrue((capture / 'integrity.json').is_file(), result.stdout + result.stderr)
                log = root / 'bullet-native/gjk-pair-check.log'
                self.assertIn('caller reached capture', log.read_text())
                before = {p.name: p.read_bytes() for p in capture.iterdir() if p.is_file()}
                result = subprocess.run(['bash', '-c', commands], env=environment, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Capture directory must be empty', log.read_text())
                self.assertEqual(before, {p.name: p.read_bytes() for p in capture.iterdir() if p.is_file()})

    def test_full_baseline_requires_exact_generator_and_complete_native_schema(self):
        generated = subprocess.check_output([__import__('sys').executable, Path(check.__file__).with_name('cases.py')]).replace(b'\r\n', b'\n')
        compact = (FIXTURE / 'native.tsv').read_bytes()
        last = compact.splitlines()[-1].split(b'\t', 1)[1]
        native = compact + b''.join(str(i).encode() + b'\t' + last + b'\n' for i in range(1800, 5075))
        native += (FIXTURE / 'fallback-native.tsv').read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs_path, native_path = root / 'inputs.tsv', root / 'native.tsv'
            environment = dict(os.environ, MDS_GJK_PAIR_INPUTS=str(inputs_path), MDS_GJK_PAIR_NATIVE=str(native_path))
            for ending in [b'\n', b'\r\n']:
                inputs_path.write_bytes(generated.replace(b'\n', ending))
                native_path.write_bytes(native.replace(b'\n', ending))
                facts = mutations.full_baseline(root, environment)
                self.assertEqual(facts['status'], 'validated')
                self.assertEqual((root / 'baseline-inputs.tsv').read_bytes(), inputs_path.read_bytes())
                self.assertEqual((root / 'baseline-native.tsv').read_bytes(), native_path.read_bytes())
            def damaged(data):
                lines = data.splitlines(keepends=True)
                return [b''.join(lines[:2]), b''.join(lines[:-1]),
                        b''.join([lines[0], lines[0], *lines[2:]]),
                        b''.join([lines[1], lines[0], *lines[2:]]),
                        data.replace(b'00000000', b'80000000', 1),
                        data.replace(b'\t', b' ', 1), data[:-1],
                        data.replace(b'\n', b'\r\n', 1)]
            for kind, corruptions in [('inputs', damaged(generated)), ('native', damaged(native))]:
                for index, broken in enumerate(corruptions):
                    # Schema-valid substituted native bits require the real semantic comparison.
                    if kind == 'native' and index == 4:
                        continue
                    inputs_path.write_bytes(broken if kind == 'inputs' else generated)
                    native_path.write_bytes(broken if kind == 'native' else native)
                    with self.subTest(kind=kind, index=index), patch.object(mutations.subprocess, 'check_output', return_value=generated), patch.object(mutations.subprocess, 'run') as compile_call:
                        facts = mutations.run_harness(None, None, root / f'{kind}-{index}', root / 'crt.rlib', environment)
                    self.assertEqual(facts['reason'], 'invalid-full-baseline')
                    compile_call.assert_not_called()
            inputs_path.write_bytes(generated)
            native_path.write_bytes(native.replace(b'00000000', b'NaN', 1))
            self.assertEqual(mutations.full_baseline(root, environment)['status'], 'validation-gap')

    def test_semantic_marker_required(self):
        input_line = (FIXTURE / 'inputs.tsv').read_text().splitlines()[0]
        expected = (FIXTURE / 'native.tsv').read_text().splitlines()[0]
        words = expected.split('\t')
        words[5] = '80000000'
        actual = '\t'.join(words)
        log = (f"thread '{mutations.TEST}' panicked at /source/gjk_pair.rs:210:5:\n"
               f'MDS_GJK_PAIR_NATIVE_MISMATCH_BEGIN\ninput {input_line} actual {actual} expected {expected}\n'
               'MDS_GJK_PAIR_NATIVE_MISMATCH_END\n'
               'test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;')
        result = SimpleNamespace(returncode=101, stdout=log, stderr='')
        self.assertEqual(mutations.classify(result)['status'], 'rejected')
        for damaged in [log.replace('MDS_GJK_PAIR_NATIVE_MISMATCH_BEGIN', 'other'),
                        log.replace(actual, expected), log.replace('80000000', 'NaN'),
                        log.replace('input ' + input_line, 'input invalid'), log + 'panicked at elsewhere']:
            self.assertEqual(mutations.classify(SimpleNamespace(returncode=101, stdout=damaged, stderr=''))['status'], 'validation-gap')
        for code in [1, 2, 127]:
            self.assertEqual(mutations.classify(SimpleNamespace(returncode=code, stdout=log, stderr=''))['status'], 'validation-gap')

    def test_observer_msvc_replaces_executable_and_includes_before_link(self):
        import observe
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            src = check.ROOT / 'recipes/bullet275/bullet-src/src'
            exe = output / 'native.exe'
            command = ['cl', '/O2', '/fp:precise', f'/Fe:{exe}', '/link', '/OPT:REF']
            with patch.object(observe.subprocess, 'run') as compile_call, patch.object(observe.subprocess, 'check_output', return_value=b''):
                (output / 'native.tsv').write_bytes(b'')
                with self.assertRaises(AssertionError):
                    observe.observe(src, command, exe, b'', output, {})
            effective = compile_call.call_args.args[0]
            self.assertIn(f'/Fe:{output / "native-observed.exe"}', effective)
            self.assertNotIn(f'/Fe:{exe}', effective)
            self.assertTrue(all(i < effective.index('/link') for i, arg in enumerate(effective) if arg.startswith('/I')))
            self.assertIn('/fp:precise', effective)


    def test_fallback_history_mismatch_is_rejected(self):
        generated = subprocess.check_output([sys.executable, Path(check.__file__).with_name('cases.py')])
        native = b''.join(f'{i}\tnative\n'.encode() for i in range(5081))
        def output(command, **kwargs):
            if '-Vv' in command:
                return 'test rustc'
            if str(command[-1]).endswith('cases.py'):
                return generated
            return b'independent mismatch\n' if 'input' in kwargs and kwargs['input'] != generated else native
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(check, 'test_fallback_coverage'), patch.object(check, 'compiler_version', return_value='test'), patch.object(check.platform, 'platform', return_value='test platform'), patch.object(check, 'native_command', side_effect=lambda cmd, *args: list(map(str, cmd))), patch.object(check, 'run'), patch.object(check, 'observe'), patch.object(check.subprocess, 'check_output', side_effect=output), patch.object(mutations, 'run_harness', return_value={}):
                # capture loads its runner by filename, so replace that loader's module too.
                with patch.object(check.importlib.util, 'module_from_spec', return_value=mutations), patch('importlib.machinery.SourceFileLoader.exec_module', return_value=None):
                    with self.assertRaisesRegex(AssertionError, 'Fallback requires prior history'):
                        check.capture(root, {})
            self.assertEqual((root / 'fallback-independent-native.tsv').read_bytes(), b'independent mismatch\n')

    def test_observer_failure_blocks_profile_and_mutations_with_complete_streams(self):
        import measured_profiles
        generated = subprocess.check_output([sys.executable, Path(check.__file__).with_name('cases.py')])
        compact = (FIXTURE / 'native.tsv').read_bytes()
        last = compact.splitlines()[-1].split(b'\t', 1)[1]
        native = compact + b''.join(str(i).encode() + b'\t' + last + b'\n' for i in range(1800, 5075))
        fallback = (FIXTURE / 'fallback-native.tsv').read_bytes()
        native += fallback
        for error in [AssertionError(), AssertionError('coverage missing'), None]:
            with self.subTest(error=repr(error)), tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                write_json = check.write_json
                write_json(output / 'mutation-gate.json', {'status': 'not-run'})
                def command_output(command, **kwargs):
                    if '-Vv' in command:
                        return 'test rustc'
                    if str(command[-1]).endswith('cases.py'):
                        return generated
                    return native if kwargs['input'] == generated else fallback
                def observed(*args):
                    (output / 'observed.tsv').write_bytes(native)
                    if error is not None:
                        raise error
                def harness(*args):
                    (output / 'rust.tsv').write_bytes(native)
                    return {'status': 'passed'}
                with patch.object(check, 'test_fallback_coverage'), patch.object(check, 'compiler_version', return_value='test'), patch.object(check.platform, 'platform', return_value='test platform'), patch.object(check, 'native_command', side_effect=lambda cmd, *args: list(map(str, cmd))), patch.object(check, 'run') as run, patch.object(check, 'observe', side_effect=observed), patch.object(check.subprocess, 'check_output', side_effect=command_output), patch.object(mutations, 'run_harness', side_effect=harness), patch.object(measured_profiles, 'validate', return_value={'test': 'approved'}) as validate:
                    with patch.object(check.importlib.util, 'module_from_spec', return_value=mutations), patch('importlib.machinery.SourceFileLoader.exec_module', return_value=None):
                        if error is None:
                            check.capture(output, {})
                        else:
                            with self.assertRaisesRegex(ValueError, 'observer coverage failed') as failure:
                                check.capture(output, {})
                            self.assertIs(failure.exception.__cause__, error)
                facts = json.loads((output / 'host-profile.json').read_text())
                self.assertEqual(facts['collection'], 'complete')
                self.assertEqual(len(facts['streams']), 9)
                self.assertTrue(facts['native_observed_equal'])
                self.assertEqual(facts['native_rust_differences'], [])
                self.assertEqual(facts['compatibility'], 'FAIL')
                self.assertFalse(facts['profile_known'])
                self.assertEqual((output / 'fallback-independent-native.tsv').read_bytes(), fallback)
                if error is not None:
                    validate.assert_not_called()
                    self.assertEqual(run.call_count, 3)
                    self.assertFalse((output / 'measured-profile.json').exists())
                    self.assertEqual(json.loads((output / 'observer-failure.json').read_text()),
                                     {'type': 'AssertionError', 'error': str(error)})
                    self.assertEqual(json.loads((output / 'mutation-gate.json').read_text())['status'], 'not-run')
                else:
                    validate.assert_called_once()
                    self.assertEqual(run.call_count, 4)
                    self.assertEqual(Path(run.call_args.args[0][1]).name, 'mutations.py')
                    self.assertFalse((output / 'observer-failure.json').exists())
                    self.assertEqual(json.loads((output / 'measured-profile.json').read_text()), {'test': 'approved'})
                    self.assertEqual(json.loads((output / 'mutation-gate.json').read_text())['status'], 'passed')

    def test_observer_guards_reject_each_missing_evidence(self):
        import observe
        complete = [f'outer-{branch} {a} {b}' for a, b in observe.PAIRS
                    for branch in ['penetration-adapter', 'distance-fallback', 'emitted']]
        complete += [f'outer-{label} 8 0' for label in ['max-distance', 'duplicate', 'near-origin', 'penetration-replaced', 'tail']]
        complete += ['manifold-depth 0', 'manifold-depth 1', 'manifold-refresh']
        for branch in ['penetration-adapter', 'distance-fallback', 'emitted']:
            with self.subTest(branch=branch), self.assertRaises(AssertionError):
                observe.require_fallback_coverage([event for event in complete if event != f'outer-{branch} 8 0'])
        with self.assertRaisesRegex(AssertionError, 'sphere-box'):
            observe.require_fallback_coverage([])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / 'native.tsv').write_bytes(b'native\n')
            src = check.ROOT / 'recipes/bullet275/bullet-src/src'
            def attempt(events, stdout=b'native\n'):
                def observed(command, **kwargs):
                    kwargs['stderr'].write(('\n'.join(events) + '\n').encode())
                    return stdout
                with patch.object(observe.subprocess, 'run'), patch.object(observe.subprocess, 'check_output', side_effect=observed):
                    return observe.observe(src, ['compiler'], output / 'native', b'', output, {})
            self.assertEqual(len(attempt(complete)), 3)
            with self.assertRaisesRegex(AssertionError, 'Observer changed output'):
                attempt(complete, b'changed\n')
            for missing in ['outer-max-distance 8 0', 'outer-duplicate 8 0', 'outer-near-origin 8 0', 'outer-penetration-replaced 8 0', 'outer-tail 8 0', 'manifold-depth 0', 'manifold-depth 1', 'manifold-refresh']:
                with self.subTest(missing=missing), self.assertRaises(AssertionError):
                    attempt([event for event in complete if event != missing])
            anchors = ['checkSimplex=true;', 'if (m_curIter++ > gGjkMaxIter)\n\t\t\t\t  {', 'resultOut->refreshContactPoints();', 'if (depth > m_manifoldPtr->getContactBreakingThreshold())']
            read_text = Path.read_text
            for anchor in anchors:
                def changed(path, *args, **kwargs):
                    return read_text(path, *args, **kwargs).replace(anchor, '')
                with self.subTest(anchor=anchor), patch.object(Path, 'read_text', changed), self.assertRaises(AssertionError):
                    attempt(complete)


if __name__ == '__main__':
    unittest.main()
