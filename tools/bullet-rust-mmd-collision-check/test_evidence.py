import unittest
from evidence import admit_capture


class AdmissionBoundaryTests(unittest.TestCase):
    def test_no_source_or_synthetic_input_is_admitted(self):
        for input in (None, {}, {'status': 'PASS'}, b'legal-looking-source'):
            with self.assertRaisesRegex(ValueError, 'not implemented'):
                admit_capture(input)


if __name__ == '__main__':
    unittest.main()
