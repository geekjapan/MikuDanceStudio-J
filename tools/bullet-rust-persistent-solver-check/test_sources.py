"""Exercise live provenance against compiled modules and compile-time fixtures."""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

import check


COMPILED_CONTACT_INPUTS = [
    'rust/crates/mds-bullet/tests/pure_bullet/' + name + '.rs'
    for name in ['contacts', 'box_box', 'capsule_capsule']
] + [
    'rust/crates/mds-bullet/tests/' + folder + '/' + name + '.tsv'
    for folder in ['contact_data', 'box_box_data', 'capsule_capsule_data']
    for name in ['inputs', 'native']
]


class SourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        for path in check.source_paths():
            dest = cls.root / path.relative_to(check.ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        shutil.copytree(check.ROOT / 'rust/crates/mds-bullet/tests',
                        cls.root / 'rust/crates/mds-bullet/tests', dirs_exist_ok=True, symlinks=True)

    def test_compiled_contact_inputs_cannot_be_omitted(self):
        before = check.source_hashes(self.root)
        for path in COMPILED_CONTACT_INPUTS:
            with self.subTest(path=path):
                omitted = dict(before)
                omitted.pop(path, None)
                with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                    check.verify_sources(omitted, self.root)

    def test_compiled_contact_input_edits_fail_end_integrity(self):
        before = check.source_hashes(self.root)
        for path in COMPILED_CONTACT_INPUTS:
            with self.subTest(path=path):
                module = self.root / path
                original = module.read_bytes()
                try:
                    module.write_bytes(original + b'\n')
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.verify_sources(before, self.root)
                finally:
                    module.write_bytes(original)
        check.verify_sources(before, self.root)

    def test_test_and_fixture_additions_fail_end_integrity(self):
        before = check.source_hashes(self.root)
        folder = self.root / 'rust/crates/mds-bullet/tests/new_nested_inputs'
        folder.mkdir()
        try:
            for name in ['module.rs', 'fixture.tsv']:
                with self.subTest(name=name):
                    added = folder / name
                    try:
                        added.write_bytes(b'new\r\ninput\n')
                        with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                            check.verify_sources(before, self.root)
                    finally:
                        added.unlink()
        finally:
            folder.rmdir()
        check.verify_sources(before, self.root)

    def test_compiled_contact_input_deletions_fail_end_integrity(self):
        before = check.source_hashes(self.root)
        for path in COMPILED_CONTACT_INPUTS:
            with self.subTest(path=path):
                module = self.root / path
                original = module.read_bytes()
                try:
                    module.unlink()
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.verify_sources(before, self.root)
                finally:
                    module.write_bytes(original)
        check.verify_sources(before, self.root)

    def test_directory_symlink_is_rejected_at_snapshot_and_end(self):
        folder = self.root / 'rust/crates/mds-bullet/tests/contact_data'
        before = check.source_hashes(self.root)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'contact_data'
            shutil.copytree(folder, target, symlinks=True)
            try:
                probe = Path(directory) / 'probe'
                probe.symlink_to(target, target_is_directory=True)
                probe.unlink()
            except (OSError, NotImplementedError) as error:
                self.skipTest(f'directory symlink unavailable: {error}')
            shutil.rmtree(folder)
            try:
                folder.symlink_to(target, target_is_directory=True)
                with self.subTest(phase='snapshot'):
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.source_hashes(self.root)
                (target / 'inputs.tsv').write_bytes(b'changed through directory symlink\n')
                with self.subTest(phase='end after replacement'):
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.verify_sources(before, self.root)
            finally:
                folder.unlink(missing_ok=True)
                shutil.copytree(check.ROOT / 'rust/crates/mds-bullet/tests/contact_data',
                                folder, symlinks=True)
        check.verify_sources(before, self.root)

    def test_directory_replacement_is_rejected_by_main_finally(self):
        folder = self.root / 'rust/crates/mds-bullet/tests/contact_data'
        source_hashes = check.source_hashes
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'contact_data'
            try:
                probe = Path(directory) / 'probe'
                probe.symlink_to(folder, target_is_directory=True)
                probe.unlink()
            except (OSError, NotImplementedError) as error:
                self.skipTest(f'directory symlink unavailable: {error}')

            def replace_directory(*args, **kwargs):
                shutil.move(folder, target)
                folder.symlink_to(target, target_is_directory=True)
                (target / 'inputs.tsv').write_bytes(b'changed during capture\n')
                raise RuntimeError('stop before native execution')

            original = (folder / 'inputs.tsv').read_bytes()
            try:
                with patch.object(check, 'ROOT', self.root), \
                        patch.object(check, 'source_hashes', side_effect=lambda *args: source_hashes(self.root)), \
                        patch.object(check.subprocess, 'run', side_effect=replace_directory) as run, \
                        patch.object(sys, 'argv', ['check.py', '--out-dir', str(Path(directory) / 'out')]):
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.main()
                    self.assertEqual(run.call_count, 1)
                    self.assertIn('unittest', run.call_args.args[0])
            finally:
                if target.exists():
                    folder.unlink(missing_ok=True)
                    shutil.move(target, folder)
                    (folder / 'inputs.tsv').write_bytes(original)

    def test_tests_root_symlink_is_rejected(self):
        folder = self.root / 'rust/crates/mds-bullet/tests'
        before = check.source_hashes(self.root)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'tests'
            try:
                probe = Path(directory) / 'probe'
                probe.symlink_to(folder, target_is_directory=True)
                probe.unlink()
            except (OSError, NotImplementedError) as error:
                self.skipTest(f'directory symlink unavailable: {error}')
            shutil.move(folder, target)
            try:
                folder.symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                    check.source_hashes(self.root)
                with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                    check.verify_sources(before, self.root)
            finally:
                folder.unlink(missing_ok=True)
                shutil.move(target, folder)
        check.verify_sources(before, self.root)

    def test_file_and_dangling_symlinks_are_rejected(self):
        folder = self.root / 'rust/crates/mds-bullet/tests'
        before = check.source_hashes(self.root)
        for target in [folder / 'contact_data/inputs.tsv', folder / 'absent.tsv']:
            with self.subTest(target=target):
                link = folder / 'symlink-control.tsv'
                try:
                    try:
                        link.symlink_to(target)
                    except (OSError, NotImplementedError) as error:
                        self.skipTest(f'file symlink unavailable: {error}')
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.source_hashes(self.root)
                    with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                        check.verify_sources(before, self.root)
                finally:
                    link.unlink(missing_ok=True)
        check.verify_sources(before, self.root)

    def test_fifo_is_rejected_without_reading(self):
        if not hasattr(os, 'mkfifo'):
            self.skipTest('FIFO creation unavailable')
        fifo = self.root / 'rust/crates/mds-bullet/tests/fifo-control'
        before = check.source_hashes(self.root)
        try:
            try:
                os.mkfifo(fifo)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f'FIFO creation unavailable: {error}')
            with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                check.source_hashes(self.root)
            with self.assertRaisesRegex(AssertionError, 'compiled source closure'):
                check.verify_sources(before, self.root)
        finally:
            fifo.unlink(missing_ok=True)
        check.verify_sources(before, self.root)

    def test_manifest_keys_are_posix_and_hashes_preserve_bytes(self):
        data = b'first\r\nsecond\n'
        relative = 'rust/crates/mds-crtmath/src/digest.rs'
        for path_type, directory in [(PureWindowsPath, 'C:/repo'), (PurePosixPath, '/repo')]:
            with self.subTest(path_type=path_type):
                root = path_type(directory)
                with patch.object(check, 'source_paths', return_value=[root / relative]), \
                        patch.object(path_type, 'read_bytes', create=True, return_value=data):
                    self.assertEqual(check.source_hashes(root), {
                        relative: hashlib.sha256(data).hexdigest(),
                    })

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
