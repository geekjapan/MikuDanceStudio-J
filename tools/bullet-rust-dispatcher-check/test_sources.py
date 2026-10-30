import tempfile
import unittest
from pathlib import Path
from check import snapshot


class SourceTests(unittest.TestCase):
    def test_membership_addition_and_raw_crlf_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'rust/crates/mds-bullet/src/core'
            folder.mkdir(parents=True)
            source = folder / 'a.rs';source.write_bytes(b'fn f() {}\n')
            before = snapshot(root)
            source.write_bytes(b'fn f() {}\r\n')
            self.assertNotEqual(before, snapshot(root))
            source.write_bytes(b'fn f() {}\n')
            (folder / 'new.rs').write_bytes(b'')
            self.assertNotEqual(before, snapshot(root))


if __name__ == '__main__': unittest.main()
