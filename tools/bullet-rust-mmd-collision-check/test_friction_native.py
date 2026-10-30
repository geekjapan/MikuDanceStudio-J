"""Pure boundary controls locally; complete generation/inverse controls on GHA."""
from pathlib import Path
import os
import shutil
import tempfile
import unittest

import friction_native as native
from hooks import inverse, replace


class NativeBoundaries(unittest.TestCase):
    def test_local_generation_cannot_start(self):
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            self.skipTest('local-only boundary')
        with self.assertRaisesRegex(ValueError, 'GHA-only'):
            native.generate(Path('/unused'), observed=True, corpus=b'X\n')

    def test_exact_inverse_and_duplicate_anchor_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'point.h'
            original = b'ctor\r\n{\r\n}\r\n'
            source.write_bytes(original)
            edits = []
            replace(root, 'point.h', 'ctor\n{\n}', 'ctor\n{\nguard();\n}', edits)
            inverse(root, edits, {'point.h': original})
            self.assertEqual(source.read_bytes(), b'ctor\r\n{\r\nguard();\r\n}\r\n')
            source.write_bytes(b'ctor\nctor\n')
            with self.assertRaisesRegex(ValueError, 'one exact hook anchor'):
                replace(root, 'point.h', 'ctor', 'observed', [])


@unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true', 'complete generation is hosted-only')
class HostedNativeGeneration(unittest.TestCase):
    def test_both_variants_full_inverse_and_library_fence(self):
        source = Path(__file__).resolve().parents[2]
        for observed in (False, True):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for base in (native.NATIVE.rstrip('/'), 'rust/crates/mds-bullet-sys/shim', native.HERE.rstrip('/')):
                    shutil.copytree(source / base, root / base, ignore=shutil.ignore_patterns('__pycache__'))
                edits, originals, census = native.generate(root, observed=observed, corpus=b'H diagnostic dynamics\nX\n')
                self.assertTrue(census)
                inverse(root, edits, originals)
                if not observed:
                    self.assertEqual(set(originals), {native.CONSUMER})
                    for p in native.library_paths(source):
                        self.assertEqual(p.read_bytes(), (root / p.relative_to(source)).read_bytes())
                consumer = (root / native.CONSUMER).read_text()
                self.assertNotIn('if(p.m_lateralFrictionInitialized){vector(', consumer)
                self.assertIn('friction_native::directions(m,i,j,op=="W")', consumer)
                self.assertEqual(any(change['path'] == native.SHIM for change in edits), observed)
                self.assertFalse(any(change['path'].endswith('.rs') for change in edits))


if __name__ == '__main__':
    unittest.main()
