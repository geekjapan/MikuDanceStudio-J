"""Exercise live provenance against real CRT module membership and contents."""
import shutil
import tempfile
import unittest
from pathlib import Path

import check


class SourceClosureTests(unittest.TestCase):
    def test_compiled_crt_modules_are_required(self):
        manifest = check.source_hashes()
        for name in ['digest.rs', 'explog.rs', 'inv.rs', 'tables.rs', 'trig.rs']:
            path = 'rust/crates/mds-crtmath/src/' + name
            self.assertIn(path, manifest)
            omitted = dict(manifest)
            omitted.pop(path)
            with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                check.verify_sources(omitted)

    def test_module_edit_and_addition_fail_end_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in check.source_paths():
                dest = root / path.relative_to(check.ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
            before = check.source_hashes(root)
            module = root / 'rust/crates/mds-crtmath/src/trig.rs'
            original = module.read_bytes()
            module.write_bytes(original + b'\n')
            with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                check.verify_sources(before, root)
            module.write_bytes(original)
            check.verify_sources(before, root)
            (module.parent / 'new_module.rs').write_text('')
            with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                check.verify_sources(before, root)


if __name__ == '__main__':
    unittest.main()
