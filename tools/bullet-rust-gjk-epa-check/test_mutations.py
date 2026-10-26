import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mutations


WORDS = '\t'.join(['0', '0', '0', '0', '0', '0', '0', '0'] + ['00000000'] * 9)
CHANGED = WORDS.replace('00000000', '3f800000', 1)
INPUT = ' '.join(['12', '0', '1'] + ['00000000'] * 33)
WORDS = '12' + WORDS[1:]
CHANGED = '12' + CHANGED[1:]
COMPARISON = f'''thread '{mutations.TEST}' (5086382) panicked at /fixture/gjk_epa.rs:99:5:
MDS_GJK_EPA_NATIVE_MISMATCH_BEGIN
query 12 input {INPUT} actual {CHANGED} expected {WORDS}
MDS_GJK_EPA_NATIVE_MISMATCH_END

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
'''


class MutationClassification(unittest.TestCase):
    def result(self, log=COMPARISON, code=101):
        return subprocess.CompletedProcess([], code, log, '')

    def test_only_native_comparison_counts_and_keeps_actual_fields(self):
        self.assertEqual(mutations.classify(self.result()), {
            'status': 'rejected', 'returncode': 101,
            'differences': [[12, 'adapter.witness0.x', '3f800000', '00000000']],
        })

    def test_reject_non_comparison_failures(self):
        panic_prefix = f"thread '{mutations.TEST}' panicked at /fixture/gjk_epa.rs:1:5:\n"
        for reason in ['unreviewed GJK/EPA host profile; run the native capture workflow',
                       'called `Result::unwrap()` on an `Err` value: missing configuration',
                       'assertion `left == right` failed: invalid input count',
                       'other panic']:
            with self.subTest(reason=reason):
                self.assertNotEqual(mutations.classify(self.result(panic_prefix + reason))['status'], 'rejected')
        for log, code in [(COMPARISON, -9), (COMPARISON, 1), (COMPARISON, 0),
                          (COMPARISON + 'thread other panicked at elsewhere', 101),
                          (COMPARISON.replace('gjk_epa.rs:', 'shape.rs:'), 101),
                          (COMPARISON.replace('query 12', 'query 1801'), 101),
                          (COMPARISON.replace(CHANGED, WORDS), 101),
                          (COMPARISON.replace('3f800000', 'NaN'), 101),
                          (COMPARISON.replace('0 passed; 1 failed', '0 passed; 2 failed'), 101),
                          ('error: could not compile test\n' + COMPARISON, 1)]:
            with self.subTest(log=log, code=code):
                self.assertNotEqual(mutations.classify(self.result(log, code))['status'], 'rejected')

    def test_variable_query_schema_records_success_and_missing_fields(self):
        expected = WORDS.split('\t')
        actual = expected[:1] + ['1', '0'] + ['3f800000'] * 10 + expected[3:]
        log = COMPARISON.replace(CHANGED, '\t'.join(actual))
        result = mutations.classify(self.result(log))
        self.assertEqual(result['status'], 'rejected')
        self.assertIn([12, 'distance.success', '1', '0'], result['differences'])
        self.assertIn([12, 'distance.witness0.x', '3f800000', None], result['differences'])

    def test_windows_paths_are_escaped_rust_literals(self):
        from pathlib import PureWindowsPath
        kernel = PureWindowsPath(r'C:\runner\new\gjk_epa.rs')
        source = mutations.harness_source(kernel)
        self.assertIn('#[path=' + json.dumps(str(kernel)) + ']', source)
        self.assertIn(r'C:\\runner\\new\\gjk_epa.rs', source)

    def test_zero_exit_requires_one_passing_test(self):
        self.assertEqual(mutations.classify(self.result('test result: ok. 1 passed; 0 failed;', 0))['status'], 'passed')
        self.assertNotEqual(mutations.classify(self.result('test result: ok. 0 passed; 0 failed;', 0))['status'], 'passed')

    def test_compile_failure_timeout_and_signal_are_not_caught_mutants(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for responses, expected in [([self.result('compile error', 1)], 'compile-failure'),
                                        ([subprocess.TimeoutExpired('rustc', 120)], 'timeout'),
                                        ([self.result('', 0), subprocess.TimeoutExpired('test', 60)], 'timeout'),
                                        ([self.result('', 0), self.result(COMPARISON, -9)], 'non-comparison-failure')]:
                with self.subTest(expected=expected), patch.object(mutations.subprocess, 'run', side_effect=responses):
                    self.assertEqual(mutations.run_harness('', directory, directory / 'crt.rlib', {})['status'], expected)

    def test_failing_baseline_stops_before_any_mutants(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('sys.argv', ['mutations.py', '--out-dir', temp, '--crt-rlib', 'crt.rlib']), \
                    patch.dict('os.environ', {'MDS_GJK_EPA_NATIVE': 'invalid', 'MDS_GJK_EPA_INPUTS': 'invalid'}), \
                    patch.object(mutations, 'run_harness', return_value={'status': 'non-comparison-failure'}) as run:
                with self.assertRaisesRegex(SystemExit, 'baseline did not pass'):
                    mutations.main()
                self.assertEqual(run.call_count, 1)
                self.assertFalse(any(k.startswith('MDS_GJK_EPA_') for k in run.call_args.args[3]))
            self.assertEqual(json.loads((Path(temp) / 'evidence.json').read_text())['baseline']['status'], 'non-comparison-failure')
            self.assertEqual(json.loads((Path(temp) / 'results.json').read_text()), {})


if __name__ == '__main__':
    unittest.main()
