"""Local pure checks are separate from GHA-only generation/compiler controls."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import friction_rust as rust
from hooks import inverse, replace


class Local(unittest.TestCase):
    def test_observed_requires_bool(self):
        for value in (0, 1, None, 'true'):
            with self.assertRaisesRegex(ValueError, 'actual observed boolean'):
                rust.consumer(None, value)

    def test_unique_anchor_and_full_inverse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'point.rs').write_bytes(b'before\r\nwrite();\r\nafter\r\n')
            originals = {'point.rs': (root / 'point.rs').read_bytes()}
            changes = []
            replace(root, 'point.rs', 'write();\n', 'write();\nhook();\n', changes)
            self.assertEqual((root / 'point.rs').read_bytes(), b'before\r\nwrite();\r\nhook();\r\nafter\r\n')
            inverse(root, changes, originals)
            with self.assertRaisesRegex(ValueError, 'exact inverse hook range'):
                (root / 'point.rs').write_bytes(b'wrong')
                inverse(root, changes, originals)

    def test_duplicate_anchor_rejected_without_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'point.rs').write_bytes(b'write();\nwrite();\n')
            with self.assertRaisesRegex(ValueError, 'one exact hook anchor'):
                replace(root, 'point.rs', 'write();', 'hook();', [])
            self.assertEqual((root / 'point.rs').read_bytes(), b'write();\nwrite();\n')

    def test_preflight_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / rust.CONTACT
            target.parent.mkdir(parents=True)
            target.write_bytes(b'unreviewed source')
            with self.assertRaisesRegex(ValueError, 'frozen Rust source identity'):
                rust.preflight(root)


@unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true', 'GHA-only full generation/compiler')
class Hosted(unittest.TestCase):
    def test_real_generation_and_complete_inverse(self):
        here = Path(__file__).resolve().parent
        source = here.parents[1]
        for observed in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for path in rust.SOURCE_SHA256:
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / path, target)
                rust.preflight(root)
                original = rust.originals(root, rust.SOURCE_PATHS + (rust.RUNNER,))
                changes = rust.original_fixtures(root, here)
                if observed:
                    changes += rust.instrument(root, here)
                changes += rust.consumer(root, observed)
                inverse(root, changes, original)
                runner = (root / rust.RUNNER).read_text()
                self.assertNotIn('if p.lateral_initialized {for v in p.lateral_directions', runner)
                self.assertIn('p.lateral_directions.map(|v|v.0.map(f32::to_bits))', runner)
                self.assertEqual('friction_rust::incoming()' in (root / rust.CONTACT).read_text(), observed)
                owner = (root / rust.OWNER).read_text()
                self.assertEqual(owner.count('friction_rust::fixture_begin()'), int(observed))
                self.assertEqual(owner.count('friction_rust::fixture_end()'), int(observed))

    def test_runtime_lifetimes_writes_and_physical_retention(self):
        here = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(here / 'friction_rust.rs', root / 'friction_rust.rs')
            (root / 'main.rs').write_text(RUNTIME_CONTROL)
            subprocess.run(['rustc', '--edition=2021', str(root / 'main.rs'), '-o', str(root / 'probe')], check=True)
            result = subprocess.run([str(root / 'probe')], check=True, capture_output=True, text=True)
            rows = [line.split() for line in result.stdout.splitlines()]
            self.assertEqual(rows[0], ['FH', '3', 'rust-observed', 'ordinary', '0' * 64, '3'])
            self.assertEqual([row[3] for row in rows if row[0] == 'FW'], ['PLANE_BOTH', 'VELOCITY_DIR1', 'FIXTURE_W'])
            self.assertEqual(len([row for row in rows if row[0] == 'FP']), 4)
            self.assertEqual([row[8] for row in rows if row[0] == 'FD'], ['3', '3', '0', '0'])
            self.assertEqual(rows[-1][0], 'FZ')
            self.assertEqual(int(rows[-1][1]), len(rows) - 2)
            self.assertEqual(rows[-1][-1], '6')
            self.assertTrue(any(row[0] == 'FV' for row in rows))


RUNTIME_CONTROL = r'''
mod friction_rust;
use friction_rust as f;
fn main() {
    f::begin("rust-observed", "ordinary", &"0".repeat(64), 3); f::command(0, "D");
    f::allocate(7, [0, 1]); f::enter(7);
    f::incoming(); f::insert(0, 0, false); f::incoming(); f::insert(1, 1, false); f::leave(7);
    f::solver_map([7].into_iter());
    f::solver_begin(0, 0, false); f::choice(false); f::solver_write(false); f::solver_end(true);
    f::solver_begin(0, 0, true); f::choice(true); f::solver_write(true); f::solver_end(true);
    f::snapshot(0, 7, 2); let mask = f::point(0, 0, 7, false);
    assert_eq!(mask, 3); f::directions(0, 0, mask, [[1,2,3],[4,5,6]]);
    f::enter(7); f::refresh_begin(2); f::refresh_point(1, false, false);
    f::refresh_point(0, true, false); f::remove(0, 2); f::refresh_end();
    f::incoming(); f::insert(0, 1, true); f::leave(7);
    let mask = f::point(0, 0, 7, false); assert_eq!(mask, 0);
    f::directions(0, 0, mask, [[11,12,13],[14,15,16]]);
    f::command_end(); f::command(1, "W"); f::fixture_begin(); f::fixture(7, 0); f::fixture_end();
    f::command_end(); f::command(2, "X"); f::enter(7); f::clear(1); f::leave(7); f::release(7);
    f::allocate(7, [0,1]); f::enter(7); f::clear(0); f::leave(7); f::release(7);
    f::command_end(); f::finish();
}
'''


if __name__ == '__main__':
    unittest.main()
