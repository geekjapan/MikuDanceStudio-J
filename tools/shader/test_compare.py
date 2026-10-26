import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from compare import COLUMNS, CONTRACTS, UNIT_CONTRACTS, compare, read


class Contracts(unittest.TestCase):
    def setUp(self):
        self.key = ('ray-mmd/Main.fx', 'ps_3_0', 'PS', '', 'fnv1a64:1234')
        self.row = dict(zip(COLUMNS[:5], self.key))
        self.row.update({name: 'OK ' for name in CONTRACTS})
        self.row['scan'] = 'OK descriptor:0:1:3;in:TEXCOORD:0:0:0:3'
        self.row['reflection'] = 'OK World=c0+4'
        self.row['error'] = ''
        self.row['reflection_origin'] = 'ctab'
        self.baseline = {self.key: self.row}

    def test_new_success_cannot_replace_lost_native_success(self):
        candidate = {('new', *self.key[1:]): self.row}
        self.assertEqual(len(compare(self.baseline, candidate)), 1)
        candidate[self.key] = dict(self.row, wgsl='ERR backend failed')
        self.assertEqual(compare(self.baseline, candidate)[0]['contract'], 'wgsl')

    def test_scan_and_register_changes_fail_independently(self):
        for contract in ('scan', 'reflection', 'coverage', 'probe', 'reparse'):
            candidate = copy.deepcopy(self.baseline)
            candidate[self.key][contract] = 'ERR changed' if contract in UNIT_CONTRACTS else 'OK changed'
            self.assertEqual(compare(self.baseline, candidate)[0]['contract'], contract)

    def test_known_gap_can_improve_without_weakening_other_contracts(self):
        baseline = copy.deepcopy(self.baseline)
        baseline[self.key]['coverage'] = 'ERR missing c4'
        self.assertEqual(compare(baseline, self.baseline), [])

    def test_known_failure_must_remain_identical_or_improve_to_success(self):
        for contract in CONTRACTS:
            baseline = copy.deepcopy(self.baseline)
            baseline[self.key][contract] = 'ERR missing c4'
            self.assertEqual(compare(baseline, baseline), [])
            self.assertEqual(compare(baseline, self.baseline), [])
            for changed in ('ERR missing c9', 'UNAVAILABLE'):
                with self.subTest(contract=contract, changed=changed):
                    candidate = copy.deepcopy(baseline)
                    candidate[self.key][contract] = changed
                    self.assertEqual(compare(baseline, candidate)[0]['contract'], contract)

    def test_final_error_requires_same_diagnostic_or_complete_compile_success(self):
        baseline = copy.deepcopy(self.baseline)
        baseline[self.key].update(wgsl='ERR backend failed', error='backend failed')
        self.assertEqual(compare(baseline, baseline), [])
        self.assertEqual(compare(baseline, self.baseline), [])
        for changed in ('different failure', ''):
            candidate = copy.deepcopy(baseline)
            candidate[self.key]['error'] = changed
            self.assertEqual(compare(baseline, candidate)[0]['contract'], 'error')
        candidate = copy.deepcopy(baseline)
        candidate[self.key]['wgsl'] = 'OK '
        candidate[self.key]['error'] = 'different failure'
        self.assertEqual(compare(baseline, candidate)[0]['contract'], 'error')
        candidate = copy.deepcopy(self.baseline)
        candidate[self.key]['error'] = 'unexpected failure'
        self.assertEqual(compare(self.baseline, candidate)[0]['contract'], 'error')

    def test_cli_returns_failure_for_changed_gap_or_lost_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / 'baseline.tsv'
            candidate = Path(directory) / 'candidate.tsv'
            header = 'mds-shader-contracts-v1\ncompiler\tvkd3d 2.1\n' + '\t'.join(COLUMNS) + '\n'
            row = dict(self.row, coverage='ERR missing c4')
            baseline.write_text(header + '\t'.join(row[name] for name in COLUMNS) + '\n')
            for changed, expected in (('ERR missing c9', 1), ('UNAVAILABLE', 1),
                                      ('ERR missing c4', 0), ('OK ', 0)):
                row['coverage'] = changed
                candidate.write_text(header + '\t'.join(row[name] for name in COLUMNS) + '\n')
                result = subprocess.run([sys.executable, str(Path(__file__).with_name('compare.py')),
                                         str(baseline), str(candidate)], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_early_pipeline_diagnostic_remains_protected(self):
        before = dict(self.row, spirv='UNAVAILABLE', wgsl='UNAVAILABLE',
                      msl='UNAVAILABLE', hlsl='UNAVAILABLE', error='vkd3d failure A')
        baseline = {self.key: before}
        for error in ('vkd3d failure B', ''):
            candidate = {self.key: dict(before, error=error)}
            self.assertEqual(compare(baseline, candidate)[0]['contract'], 'error')
        candidate = {self.key: dict(before, spirv='OK ', wgsl='ERR B', msl='OK ',
                                    hlsl='OK ', error='B')}
        self.assertEqual(compare(baseline, candidate)[0]['contract'], 'error')
        self.assertEqual(compare(baseline, self.baseline), [])

    def test_cli_allows_producer_consistent_partial_backend_improvement(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / 'baseline.tsv'
            candidate = Path(directory) / 'candidate.tsv'
            header = 'mds-shader-contracts-v1\ncompiler\tvkd3d 2.1\n' + '\t'.join(COLUMNS) + '\n'
            before = dict(self.row, wgsl='ERR A', msl='ERR B', error='A')
            baseline.write_text(header + '\t'.join(before[name] for name in COLUMNS) + '\n')
            after = dict(before, wgsl='OK ', error='B')
            cases = [(after, 0), (dict(after, error='arbitrary summary'), 1),
                     (dict(after, error=''), 1),
                     (dict(after, msl='ERR C', error='C'), 1),
                     (dict(after, hlsl='UNAVAILABLE'), 1)]
            for row, expected in cases:
                with self.subTest(row=row):
                    candidate.write_text(header + '\t'.join(row[name] for name in COLUMNS) + '\n')
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name('compare.py')),
                                             str(baseline), str(candidate)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_unit_success_payloads_are_rejected_by_reader_cli_and_direct_compare(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / 'baseline.tsv'
            candidate = Path(directory) / 'candidate.tsv'
            header = 'mds-shader-contracts-v1\ncompiler\tvkd3d 2.1\n' + '\t'.join(COLUMNS) + '\n'
            before = dict(self.row, wgsl='ERR A', error='A')
            baseline.write_text(header + '\t'.join(before[name] for name in COLUMNS) + '\n')
            for contract in UNIT_CONTRACTS:
                row = dict(self.row)
                row[contract] = 'OK fake'
                with self.subTest(contract=contract):
                    candidate.write_text(header + '\t'.join(row[name] for name in COLUMNS) + '\n')
                    with self.assertRaises(ValueError):
                        read(candidate)
                    with self.assertRaises(ValueError):
                        compare({self.key: before}, {self.key: row})
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name('compare.py')),
                                             str(baseline), str(candidate)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn(contract, result.stderr)
            row = dict(self.row, scan='OK sampler metadata', reflection='OK World=c0+4',
                       probe='OK World=c0+4')
            candidate.write_text(header + '\t'.join(row[name] for name in COLUMNS) + '\n')
            self.assertEqual(read(candidate)[self.key], row)
            self.assertEqual(compare({self.key: row}, {self.key: row}), [])

    def test_reader_decodes_cells_and_rejects_empty_or_duplicate_captures(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.tsv'
            header = 'mds-shader-contracts-v1\ncompiler\tvkd3d 2.1\n' + '\t'.join(COLUMNS) + '\n'
            row = dict(self.row, error='line%09one%0Atwo%25')
            text = '\t'.join(row[name] for name in COLUMNS) + '\n'
            path.write_text(header + text)
            self.assertEqual(read(path)[self.key]['error'], 'line\tone\ntwo%')
            for bad in (header, header + text + text):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    read(path)


if __name__ == '__main__':
    unittest.main()
