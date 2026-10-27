"""Native profile boundary checks without a native compiler build."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_shader_inputs import source_identity, sha


class NativeProfileTest(unittest.TestCase):
    def test_frozen_reference_and_generated_difference(self):
        reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())
        self.assertEqual(len(reference['production_units']), 24)
        self.assertEqual(sha(Path(__file__).with_name('shader_matrix.py')), reference['matrix_sha256'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['unit.c', 'generated.tab.c', 'config.h']:
                (root / name).write_text('original')
            expected = {'source_files': {name: sha(root / name) for name in ['unit.c', 'generated.tab.c']},
                        'target_configuration': {'config.h': sha(root / 'config.h')}}
            self.assertTrue(source_identity(root, expected)['identical_source_profile'])
            (root / 'generated.tab.c').write_text('new generator')
            (root / 'config.h').write_text('new target')
            result = source_identity(root, expected)
            self.assertFalse(result['identical_source_profile'])
            self.assertEqual(result['generated_source_differences'], ['generated.tab.c'])
            (root / 'unit.c').write_text('changed source')
            with self.assertRaises(RuntimeError):
                source_identity(root, expected)

    def test_failure_keeps_partial_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / 'capture'
            completed = subprocess.run([sys.executable, str(Path(__file__).with_name('check_shader_inputs.py')),
                '--header', str(root / 'missing.h'), '--native-library', str(root / 'missing-library'),
                '--artifacts', str(artifacts), '--native-only', '--cc', 'missing-caller-compiler'], capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            result = json.loads((artifacts / 'result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertEqual(result['translated_comparison'], 'not_run')
            self.assertEqual(result['cases'], [])
            self.assertEqual(result['commands'][0]['command'], ['missing-caller-compiler', '--version'])
            self.assertIsNone(result['commands'][0]['exit_code'])
            seal = json.loads((artifacts / 'seal.json').read_text())
            self.assertEqual(seal['result.json'], sha(artifacts / 'result.json'))


if __name__ == '__main__':
    unittest.main()
