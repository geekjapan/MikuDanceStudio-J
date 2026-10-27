"""Focused parser and exact-bit comparison checks; no compilers or GPU required."""
import importlib.util
from pathlib import Path
import unittest
import sys

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('frame_check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.counts = check.read_counts('skin-0 1 8 1 1 1\nskin-30 1 8 1 1 1\n')
        self.cases = ''.join(
            f'model skin_tex.pmx\ncase {label}\nworld' + ' 00000000' * 16 +
            '\ncamera' + ' 00000000' * 4 + '\nedge 3f800000\nshadow 0\n' +
            'morph 0 00000000\nbone 0' + ' 00000000' * 16 + '\nend\n'
            for label in ['skin-0', 'skin-30'])
        self.dump = ''.join(
            f'model skin_tex.pmx pmx vertices 1 stride 32\ncase {label}\nv 0' +
            ' 00000000' * 12 + '\nm 0' + ' 00000000' * 16 + '\n'
            for label in ['skin-0', 'skin-30'])

    def test_complete_cases_and_identical_buffers(self):
        check.validate_cases(self.cases, self.counts)
        result = check.compare(self.dump, self.dump, self.counts)
        self.assertTrue(result['conditional_cpu_equal'])
        self.assertEqual(result['compared_words'], 56)

    def test_single_bit_difference_is_reported(self):
        native = self.dump.replace('v 0 00000000', 'v 0 00000001', 1)
        result = check.compare(self.dump, native, self.counts)
        self.assertFalse(result['conditional_cpu_equal'])
        self.assertEqual(result['mismatches'], [{'case': 'skin-0', 'kind': 'v', 'record': 0,
                                                'word': 0, 'rust': '00000000', 'cpp': '00000001'}])

    def test_missing_case_bone_morph_or_extra_qdef_is_rejected(self):
        for bad in [self.cases.replace('bone 0', 'bone 1', 1),
                    self.cases.replace('morph 0 00000000\n', '', 1),
                    self.cases + 'qdef 9 10\n', self.cases.split('end')[0]]:
            with self.subTest(bad=bad[-40:]), self.assertRaises((AssertionError, IndexError)):
                check.validate_cases(bad, self.counts)

    def test_truncated_or_extra_dump_is_rejected(self):
        for bad in [self.dump[:-10], self.dump + 'v 1 00000000\n', self.dump.replace('00000000', 'nan', 1)]:
            with self.subTest(bad=bad[-40:]), self.assertRaises((AssertionError, IndexError)):
                check.compare(self.dump, bad, self.counts)

    def test_native_bone_records_are_explicitly_outside_comparison(self):
        # Insert the bone work record after each case's material records.
        native = self.dump.replace('\nmodel skin_tex', '\nb 0 0' + ' 00000000' * 7 + '\nmodel skin_tex')
        native += 'b 0 0' + ' 00000000' * 7 + '\n'
        result = check.compare(self.dump, native, self.counts)
        self.assertTrue(result['conditional_cpu_equal'])
        self.assertEqual(result['excluded_cpp_bone_morph_records'], 2)


if __name__ == '__main__':
    unittest.main()
