from pathlib import Path
import tempfile
import hashlib
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


class RequiredRelationsSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = (Path(__file__).parent / 'patches/c2rust-win64-abi.patch').read_text()
        cls.sections = cls.patch.split('diff --git ')[1:]
        section = next(s for s in cls.sections if s.startswith(
            'a/c2rust-transpile/src/c_ast/closed_variadic.rs '))
        cls.source = '\n'.join(line[1:] for line in section.splitlines()
                               if line.startswith('+') and not line.startswith('+++')) + '\n'

    def test_common_plan_patch_scope_preserves_inventory_contract(self):
        self.assertEqual(len(apply_c2rust_patch.patch_destinations(
            Path(__file__).parent / 'patches/c2rust-win64-abi.patch')), len(self.sections))
        others = ''.join('diff --git ' + s for s in self.sections if not s.startswith(
            'a/c2rust-transpile/src/c_ast/closed_variadic.rs '))
        self.assertEqual(hashlib.sha256(others.encode()).hexdigest(), '94e531fefd4de1a2f0e7fed4bdee16a7e1023995eb7e8f786cf61abfc4935b8b')
        inventory = self.source.split('    pub fn closed_variadic_inventory(', 1)[1].split('#[cfg(test)]', 1)[0]
        self.assertEqual(hashlib.sha256(inventory.encode()).hexdigest(), 'fe98bb97bd17641f186a1c4244571e04474eab1bdfa52182fcfecce141a733cb')

    def test_required_facts_remain_witness_only_and_reached_by_named_unit(self):
        witness = self.source.split('    pub fn cursor_witness(', 1)[1].split(
            '    pub fn closed_variadic_inventory(', 1)[0]
        self.assertIn('"required_relations": self.cursor_required_relations(unit, &owners)', witness)
        relations = self.source.split('    fn cursor_required_relations(', 1)[1].split(
            '    /// A separate raw witness.', 1)[0]
        for table in ('roots', 'types', 'cursors', 'native_records', 'enum_owners',
                      'builtin_declarations', 'builtin_endpoints'):
            self.assertIn('"' + table + '"', relations)
        self.assertIn('"schema": 1, "authorization": "witness_only"', relations)
        unit = self.source.split(
            '    fn closed_variadic_inventory_uses_promoted_ast_types_and_linker_identity() {', 1)[1]
        self.assertTrue(unit.startswith('\n        cursor_required_relations_are_bounded_native_facts();\n'))
        helper = self.source.split('    fn cursor_required_relations_are_bounded_native_facts() {', 1)[1].split('    #[test]', 1)[0]
        for control in ('source_array_elements.remove', 'source_typedef_types.remove',
                        'native_va_list_records.remove', 'variants.push',
                        'BuiltinFnToFnPtr', '"unknown".into()', 'CTypeId(998)',
                        '"restrict"', '"ASTContext.getVaListTagDecl"'):
            self.assertIn(control, helper)
        self.assertNotIn('#[cfg', helper)
        self.assertNotIn('return;', helper)


    def test_retarget_fixture_has_imported_linker_identity(self):
        helper = self.source.split('    fn cursor_required_relations_are_bounded_native_facts() {', 1)[1]
        fixture = 'ast.linker_names.insert(CDeclId(60), "body".into());'
        self.assertIn(fixture, helper)
        self.assertLess(helper.index(fixture), helper.index('*decl = CDeclId(60);'))

    def test_body_collection_prunes_types_and_nonlexical_declarations(self):
        walk = self.source.split('    fn cursor_required_relations(', 1)[1].split('        let mut builtin_ids', 1)[0]
        self.assertNotIn('DFExpr', walk)
        self.assertIn('node.type_().is_some()', walk)
        self.assertIn('Some(CDeclKind::Variable { .. })) { continue; }', walk)
        self.assertIn('filter(|child| child.type_().is_none())', walk)
        helper = self.source.split('    fn cursor_required_relations_are_bounded_native_facts() {', 1)[1]
        for control in ('CTypeKind::Struct(CDeclId(90))', 'CDeclId(91)',
                        'Some(CExprId(810))', 'Some(CExprId(80))',
                        'positive["enum_owners"].as_array().unwrap().len(), 1'):
            self.assertIn(control, helper)

    def test_depth_checks_are_per_root_and_named_unit_covers_renaming(self):
        relation = self.source.split('    fn required_type_relation(', 1)[1].split('    fn required_native_record(', 1)[0]
        self.assertIn('depth > 32 || visiting.contains(&id)', relation)
        self.assertIn('checked.get(&(id, depth))', relation)
        self.assertNotIn('rows.insert', relation)
        roots = self.source.split('        let mut root_facts = vec![];', 1)[1].split('        let mut native_ids', 1)[0]
        self.assertIn('&mut HashSet::new(), &mut HashMap::new(), 0', roots)
        self.assertIn('fact["unproved"]', roots)
        self.assertIn('root_proved.get(&CTypeId(id)) == Some(&true)', self.source)
        unit = self.source.split('    fn closed_variadic_inventory_uses_promoted_ast_types_and_linker_identity() {', 1)[1]
        self.assertIn('cursor_required_relations_depth_is_per_root();', unit)
        helper = self.source.split('    fn cursor_required_relations_depth_is_per_root() {', 1)[1].split('    fn cursor_required_relations_are_bounded_native_facts()', 1)[0]
        for control in ('[0u64, 20, 255]', '[false, true]', 'normalize(&mut facts, mask)',
                        'assert_eq!(&facts, expected)', 'vec![q(1)]', 'CTypeKind::Paren(t(20))'):
            self.assertIn(control, helper)


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


class ToolIdentityRetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.artifacts = self.root / 'logs'
        self.tool = self.root / 'tool'
        self.source.mkdir()
        self.artifacts.mkdir()
        (self.tool / 'bin').mkdir(parents=True)
        for name in ('c2rust', 'c2rust-transpile'):
            (self.tool / 'bin' / name).write_bytes(name.encode())
        (self.tool / 'unrelated-cache').write_bytes(b'must not retain')
        (self.source / 'module.rs').write_bytes(b'mapped source\n')
        saved_patch = self.artifacts / 'c2rust-source.patch'
        saved_patch.write_text('diff --git a/module.rs b/module.rs\nnew file mode 100644\n'
                               '--- /dev/null\n+++ b/module.rs\n@@ -0,0 +1 @@\n+mapped source\n')
        saved_source = self.artifacts / 'c2rust-applied-source'
        saved_source.mkdir()
        (saved_source / 'module.rs').write_bytes((self.source / 'module.rs').read_bytes())
        record = {'original_revision': apply_c2rust_patch.REVISION,
                  'patch_sha256': apply_c2rust_patch.digest(saved_patch),
                  'applied_diff_sha256': apply_c2rust_patch.digest(saved_patch),
                  'modified_source_sha256': {'module.rs': apply_c2rust_patch.digest(self.source / 'module.rs')}}
        (self.artifacts / 'c2rust-patch.json').write_text(json.dumps(record))

    def test_bind_retains_only_verified_identity_before_returning(self):
        apply_c2rust_patch.bind_tool(self.source, self.artifacts, self.tool)
        retained = self.artifacts / 'early-tool-identity'
        apply_c2rust_patch.verify_tool(retained)
        files = json.loads((retained / 'retention.json').read_text())['files']
        self.assertEqual(set(files), {'bin/c2rust', 'bin/c2rust-transpile', 'source-receipt.json',
                                     'source-evidence/c2rust-patch.json', 'source-evidence/c2rust-source.patch',
                                     'source-evidence/c2rust-applied-source/module.rs'})
        self.assertEqual({str(p.relative_to(retained)) for p in retained.rglob('*') if p.is_file()},
                         set(files) | {'retention.json'})
        for name, identity in files.items():
            with self.subTest(name=name):
                original = self.tool / name
                self.assertEqual((retained / name).read_bytes(), original.read_bytes())
                self.assertEqual(identity, {'source': str(original.resolve()),
                                           'sha256': apply_c2rust_patch.digest(original),
                                           'bytes': original.stat().st_size})

    def test_corrupt_copy_fails_before_retention_manifest(self):
        copy = apply_c2rust_patch.shutil.copy2
        def corrupt(source, destination):
            result = copy(source, destination)
            if Path(destination).as_posix().endswith('early-tool-identity/bin/c2rust-transpile'):
                Path(destination).write_bytes(b'corrupt')
            return result
        with patch.object(apply_c2rust_patch.shutil, 'copy2', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'retained tool identity differs'):
                apply_c2rust_patch.bind_tool(self.source, self.artifacts, self.tool)
        self.assertFalse((self.artifacts / 'early-tool-identity/retention.json').exists())

    def test_symlink_binary_is_rejected(self):
        binary = self.tool / 'bin/c2rust-transpile'
        binary.unlink()
        binary.symlink_to(self.source / 'module.rs')
        with self.assertRaisesRegex(ValueError, 'symlink patch destination'):
            apply_c2rust_patch.bind_tool(self.source, self.artifacts, self.tool)
        self.assertFalse((self.artifacts / 'early-tool-identity').exists())


if __name__ == '__main__':
    unittest.main()
