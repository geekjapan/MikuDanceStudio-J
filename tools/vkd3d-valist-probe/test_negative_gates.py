"""Cheap rejection-gate controls; no compiler or native process is launched."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run as probe


class NegativeGates(unittest.TestCase):
    def test_runtime_requires_exact_exit_and_field(self):
        for field in probe.RUNTIME_REJECTIONS.values():
            good = f'original-format=fixture\nVALIST_REJECT field={field}\n'
            probe.check_runtime_rejection(86, good, field)
            for code, output in [
                (0, good), (1, good), (-6, good), (139, good), (86, ''),
                (86, 'assertion failed'), (86, 'VALIST_REJECT field=other\n'),
                (86, good + good), (86, good + 'VALIST_REJECT field=other\n'),
                (86, good.replace('field=', 'field=prefix_')),
            ]:
                with self.subTest(field=field, code=code, output=output):
                    with self.assertRaises(AssertionError):
                        probe.check_runtime_rejection(code, output, field)

    def test_compile_requires_all_three_intended_type_errors(self):
        source = Path(__file__).with_name('probe.rs')
        diagnostics = []
        for text, label in [
            ('let _ = Slot { double: 3.25f32 };', 'expected `f64`, found `f32`'),
            ('let _ = Slot { int: -7i8 };', 'expected `i32`, found `i8`'),
            ('let _ = Slot { wide: 1u128 };', 'expected `i64`, found `u128`'),
        ]:
            diagnostics.append({'level': 'error', 'code': {'code': 'E0308'},
                                'spans': [{'is_primary': True, 'file_name': str(source),
                                           'text': [{'text': text}], 'label': label}]})
        diagnostics.append({'level': 'error', 'code': None,
                            'message': 'aborting due to 3 previous errors'})

        def check(items, code=1):
            probe.check_compile_rejection(code, '\n'.join(map(json.dumps, items)), source)

        check(diagnostics)
        variants = [[], diagnostics[:-1], diagnostics[1:], diagnostics + diagnostics[:1],
                    diagnostics + [{'level': 'error', 'code': {'code': 'E9999'}}]]
        for key, value in [('code', {'code': 'E0425'}), ('spans', []),
                           ('spans', [{'is_primary': True, 'file_name': 'other.rs',
                                       'text': [{'text': 'unrelated'}], 'label': 'wrong'}])]:
            altered = copy.deepcopy(diagnostics)
            altered[0][key] = value
            variants.append(altered)
        for member, value in [('text', [{'text': 'let _ = Slot { double: 0f32 };'}]),
                              ('label', 'expected `i32`, found `f32`')]:
            altered = copy.deepcopy(diagnostics)
            altered[0]['spans'][0][member] = value
            variants.append(altered)
        for items in variants:
            with self.subTest(items=items), self.assertRaises(AssertionError):
                check(items)
        for code in [0, -6, 2]:
            with self.subTest(code=code), self.assertRaises(AssertionError):
                check(diagnostics, code)
        with self.assertRaises(ValueError):
            probe.check_compile_rejection(1, 'compiler crashed', source)

    def test_timeout_fails_and_writes_integrity_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['run.py', '--out', directory, '--expect', 'apple-arm64']
            with patch.object(sys, 'argv', argv), \
                    patch.object(probe.platform, 'system', return_value='Darwin'), \
                    patch.object(probe.platform, 'machine', return_value='arm64'), \
                    patch.object(probe.platform, 'platform', return_value='test-host'), \
                    patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('rustc', 60)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    probe.main()
            receipt = json.loads((Path(directory) / 'receipt.json').read_text())
            self.assertTrue(receipt['source_unchanged'])


if __name__ == '__main__':
    unittest.main()
