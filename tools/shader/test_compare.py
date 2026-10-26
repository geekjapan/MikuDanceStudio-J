import copy
import tempfile
import unittest
from pathlib import Path

from compare import COLUMNS, CONTRACTS, compare, read


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
            candidate[self.key][contract] = 'OK changed'
            self.assertEqual(compare(self.baseline, candidate)[0]['contract'], contract)

    def test_known_gap_can_improve_without_weakening_other_contracts(self):
        baseline = copy.deepcopy(self.baseline)
        baseline[self.key]['coverage'] = 'ERR missing c4'
        self.assertEqual(compare(baseline, self.baseline), [])

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
