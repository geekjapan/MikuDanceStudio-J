from pathlib import Path
import tempfile
import json
import subprocess
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


class AppliedSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.artifacts = self.root / 'evidence'
        self.tool = self.root / 'tool'
        (self.tool / 'bin').mkdir(parents=True)
        for name in ('c2rust', 'c2rust-transpile'):
            (self.tool / 'bin' / name).write_bytes(name.encode())
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True)
        (self.source / 'existing.rs').write_text('old\n')
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', '-c', 'core.hooksPath=/dev/null',
                        'commit', '-qm', 'fixture'], check=True)
        revision = subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip()
        helper = self.root / 'helper.py'
        patches = self.root / 'patches'
        patches.mkdir()
        self.patch = patches / 'c2rust-win64-abi.patch'
        self.patch.write_text('diff --git a/existing.rs b/existing.rs\n--- a/existing.rs\n+++ b/existing.rs\n'
                              '@@ -1 +1 @@\n-old\n+new\n'
                              'diff --git a/closed_variadic.rs b/closed_variadic.rs\nnew file mode 100644\n'
                              '--- /dev/null\n+++ b/closed_variadic.rs\n@@ -0,0 +1 @@\n+new module\n')
        for name, value in [('REVISION', revision), ('__file__', str(helper))]:
            mocking = patch.object(apply_c2rust_patch, name, value)
            mocking.start()
            self.addCleanup(mocking.stop)

    def test_new_source_is_saved_hashed_and_reconstructible(self):
        record = apply_c2rust_patch.apply(self.source, self.artifacts)
        self.assertEqual(set(record['modified_source_sha256']), {'existing.rs', 'closed_variadic.rs'})
        retained = self.artifacts / 'c2rust-applied-source/closed_variadic.rs'
        self.assertEqual(retained.read_bytes(), b'new module\n')
        reconstructed = self.root / 'reconstructed'
        subprocess.run(['git', 'clone', '-q', str(self.source), str(reconstructed)], check=True)
        subprocess.run(['git', '-C', str(reconstructed), 'apply',
                        str(self.artifacts / 'c2rust-source.patch')], check=True)
        for name, expected in record['modified_source_sha256'].items():
            self.assertEqual(apply_c2rust_patch.digest(reconstructed / name), expected)

    def test_incomplete_new_source_evidence_fails(self):
        apply_c2rust_patch.apply(self.source, self.artifacts)
        (self.artifacts / 'c2rust-applied-source/closed_variadic.rs').unlink()
        with self.assertRaisesRegex(ValueError, 'missing patch destination'):
            apply_c2rust_patch.bind_tool(self.source, self.artifacts, self.tool)
        self.assertFalse((self.tool / 'source-receipt.json').exists())

    def test_tool_receipt_binds_new_module_and_binaries(self):
        apply_c2rust_patch.apply(self.source, self.artifacts)
        apply_c2rust_patch.bind_tool(self.source, self.artifacts, self.tool)
        apply_c2rust_patch.verify_tool(self.tool)
        binary = self.tool / 'bin/c2rust-transpile'
        original_binary = binary.read_bytes()
        binary.write_bytes(b'changed binary')
        with self.assertRaisesRegex(ValueError, 'tool binary'):
            apply_c2rust_patch.verify_tool(self.tool)
        binary.write_bytes(original_binary)
        (self.tool / 'source-evidence/c2rust-applied-source/closed_variadic.rs').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            apply_c2rust_patch.verify_tool(self.tool)

    def test_incomplete_hash_manifest_fails(self):
        apply_c2rust_patch.apply(self.source, self.artifacts)
        receipt = self.artifacts / 'c2rust-patch.json'
        record = json.loads(receipt.read_text())
        del record['modified_source_sha256']['closed_variadic.rs']
        receipt.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            apply_c2rust_patch.verify_evidence(self.artifacts)

    def test_unsafe_duplicate_missing_and_symlink_destinations_fail(self):
        original = self.patch.read_text()
        for text in [original + original, original.replace('closed_variadic.rs', '../outside.rs'),
                     original.replace('closed_variadic.rs', './module.rs'),
                     original.replace('closed_variadic.rs', 'dir//module.rs'),
                     original.replace('closed_variadic.rs', '/absolute.rs'),
                     original.replace('closed_variadic.rs', 'C:/module.rs'),
                     original.replace('+++ b/closed_variadic.rs', '+++ /dev/null'),
                     original.replace('new file mode 100644', 'new file mode 120000')]:
            with self.subTest(text=text):
                self.patch.write_text(text)
                with self.assertRaises(ValueError):
                    apply_c2rust_patch.apply(self.source, self.artifacts)
                self.assertEqual((self.source / 'existing.rs').read_text(), 'old\n')
        self.patch.write_text(original)
        (self.source / 'closed_variadic.rs').symlink_to(self.root / 'outside.rs')
        with self.assertRaisesRegex(ValueError, 'symlink patch destination'):
            apply_c2rust_patch.source_file(self.source, 'closed_variadic.rs', required=False)


if __name__ == '__main__':
    unittest.main()
