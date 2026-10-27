"""Matrix acceptance requires successful outputs and separate explicit rejections."""
from pathlib import Path
import tempfile
import unittest

import shader_matrix
from check_shader_inputs import require, spirv_layout


class MatrixTest(unittest.TestCase):
    def compare(self, defect=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'native.so'
            library.touch()

            def run(command, log, **kwargs):
                output = Path(command[4])
                negative = output.name.startswith(('missing_float_controls.', 'invalid_pixel_semantic.'))
                status, data, diagnostics = ('-4', b'', b'E2004' if 'missing_float_controls' in output.name else b'E5013') if negative else ('0', b'compiled', b'')
                if defect == 'normal_rejection' and not negative:
                    status, data, diagnostics = '-4', b'', b'E2004'
                if defect == 'negative_success' and negative:
                    status, data = '0', b'compiled'
                if defect == 'wrong_negative_diagnostic' and negative:
                    diagnostics = b'other error'
                if defect == 'empty_success' and not negative:
                    data = b''
                if defect == 'mismatch' and not negative and output.suffix == '.rust':
                    data = b'different'
                if defect == 'diagnostics_mismatch' and output.suffix == '.rust':
                    diagnostics += b'different'
                if defect == 'process_failure':
                    return {'exit_code': 1}
                output.write_bytes(data)
                Path(str(output) + '.status').write_text(status)
                Path(str(output) + '.diagnostics').write_bytes(diagnostics)
                return {'exit_code': 0}

            return shader_matrix.compare(root / 'driver', library, root, run)

    def test_full_success_keeps_negative_controls_separate(self):
        result = self.compare()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(result['cases']), 48)
        self.assertTrue(all(case['status'] == 'success' for case in result['cases']))
        self.assertEqual(len(result['negative_controls']), 2)
        self.assertTrue(all(case['status'] == 'expected_rejection' for case in result['negative_controls']))

    def test_invalid_acceptance_is_rejected(self):
        for defect in ('normal_rejection', 'negative_success', 'wrong_negative_diagnostic',
                       'empty_success', 'mismatch', 'diagnostics_mismatch', 'process_failure'):
            with self.subTest(defect=defect):
                self.assertEqual(self.compare(defect)['status'], 'comparison_failure')

    def test_checks_survive_python_optimization(self):
        with self.assertRaises(RuntimeError):
            require(False, 'must fail')
        for invalid in (b'', b'abcd' * 5):
            with self.assertRaises(RuntimeError):
                spirv_layout(invalid)


if __name__ == '__main__':
    unittest.main()
