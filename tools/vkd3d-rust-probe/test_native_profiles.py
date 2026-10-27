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
            root = Path(directory) / 'vkd3d-2.1'
            for key, base in [('source_files', root), ('target_configuration', root),
                              ('external_headers', root.parent)]:
                for name in reference[key]:
                    path = base / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('original')
                    reference[key][name] = sha(path)
            self.assertTrue(source_identity(root, reference)['identical_source_profile'])
            for name in reference['source_files']:
                with self.subTest(changed=name):
                    path = root / name
                    path.write_text('changed')
                    if name in reference['generated_files']:
                        result = source_identity(root, reference)
                        self.assertFalse(result['identical_source_profile'])
                        self.assertEqual(result['generated_source_differences'], [name])
                        self.assertEqual(result['files'][name], sha(path))
                    else:
                        receipt = {}
                        with self.assertRaisesRegex(RuntimeError, 'non-generated reference source differs'):
                            source_identity(root, reference, receipt)
                        self.assertFalse(receipt['identical_source_profile'])
                        self.assertEqual(receipt['files'][name], sha(path))
                    path.write_text('original')
            for key, base in [('source_files', root), ('external_headers', root.parent),
                              ('target_configuration', root)]:
                for name in reference[key]:
                    with self.subTest(missing=name):
                        path = base / name
                        path.unlink()
                        receipt = {}
                        with self.assertRaisesRegex(RuntimeError, 'missing required producer inputs'):
                            source_identity(root, reference, receipt)
                        self.assertIn(name, receipt['missing_inputs'])
                        self.assertFalse(receipt['identical_source_profile'])
                        path.write_text('original')
            for name in reference['target_configuration']:
                path = root / name
                path.write_text('new target')
                result = source_identity(root, reference)
                self.assertFalse(result['identical_source_profile'])
                self.assertEqual(result['generated_source_differences'], [])
                self.assertEqual(result['target_configuration_differences'], [name])
                self.assertEqual(result['target_configuration'][name], sha(path))
                path.write_text('original')
            for name in reference['external_headers']:
                path = root.parent / name
                path.write_text('new external header')
                with self.assertRaisesRegex(RuntimeError, 'external producer headers differ'):
                    source_identity(root, reference)
                path.write_text('original')
            unknown = root / 'libs/vkd3d-shader/unknown.tab.h'
            unknown.write_text('unclassified')
            with self.assertRaisesRegex(RuntimeError, 'unclassified producer inputs'):
                source_identity(root, reference)
            reference['source_files']['libs/vkd3d-shader/unknown.tab.h'] = sha(unknown)
            unknown.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'non-generated reference source differs'):
                source_identity(root, reference)
            reference['generated_files'].append('libs/vkd3d-shader/unknown.tab.h')
            with self.assertRaisesRegex(RuntimeError, 'unknown or missing generated source classification'):
                source_identity(root, reference)

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
            partial = root / 'source-failure'
            completed = subprocess.run([sys.executable, str(Path(__file__).with_name('check_shader_inputs.py')),
                '--header', str(root / 'missing.h'), '--native-library', str(root / 'missing-library'),
                '--artifacts', str(partial), '--native-only', '--source', str(root / 'missing-source')],
                capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            result = json.loads((partial / 'result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertFalse(result['source']['identical_source_profile'])
            self.assertIn('libs/vkd3d-shader/hlsl.h', result['source']['missing_inputs'])
            self.assertEqual(result['cases'], [])
            self.assertEqual(result['commands'], [])
            seal = json.loads((partial / 'seal.json').read_text())
            self.assertEqual(seal['result.json'], sha(partial / 'result.json'))


if __name__ == '__main__':
    unittest.main()
