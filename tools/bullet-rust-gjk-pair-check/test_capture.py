"""Capture failure paths retain evidence without approving numerical differences."""
import importlib.util
import json
from pathlib import Path
import subprocess
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
        with tempfile.TemporaryDirectory(prefix='outer-quoted-"-日本-') as temp:
            directory = Path(temp)
            with patch.object(mutations.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='compile failed')):
                result = mutations.run_harness(None, None, directory, directory / 'crt.rlib', {})
            self.assertEqual(result['status'], 'validation-gap')
            self.assertEqual(result['reason'], 'compile-failure')
            harness = (directory / 'harness.rs').read_text()
            for path in __import__('re').findall(r'#\[path = ("(?:\\.|[^"\\])*")\]', harness):
                self.assertTrue(Path(json.loads(path)).is_file())

    def test_semantic_marker_required(self):
        input_line = (FIXTURE / 'inputs.tsv').read_text().splitlines()[0]
        expected = (FIXTURE / 'native.tsv').read_text().splitlines()[0]
        words = expected.split('\t')
        words[5] = '80000000'
        actual = '\t'.join(words)
        log = (f"thread '{mutations.TEST}' panicked at /source/gjk_pair.rs:210:5:\n"
               f'MDS_GJK_PAIR_NATIVE_MISMATCH_BEGIN\ninput {input_line} actual {actual} expected {expected}\n'
               'MDS_GJK_PAIR_NATIVE_MISMATCH_END\n'
               'test result: FAILED. 0 passed; 1 failed; 0 ignored;')
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


if __name__ == '__main__':
    unittest.main()
