from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import apply_c2rust_patch


class ApplyPatchTests(unittest.TestCase):
    def test_wrong_revision_aborts_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(apply_c2rust_patch.subprocess, 'check_output', return_value='wrong\n') as git:
                with self.assertRaisesRegex(ValueError, 'revision differs'):
                    apply_c2rust_patch.apply(root, root / 'artifacts')
                self.assertEqual(git.call_count, 1)

    def test_dirty_pinned_source_aborts_before_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(apply_c2rust_patch.subprocess, 'check_output',
                              side_effect=[apply_c2rust_patch.REVISION + '\n', ' M source.rs\n']) as git:
                with self.assertRaisesRegex(ValueError, 'must be clean'):
                    apply_c2rust_patch.apply(root, root / 'artifacts')
                self.assertEqual(git.call_count, 2)


if __name__ == '__main__':
    unittest.main()
