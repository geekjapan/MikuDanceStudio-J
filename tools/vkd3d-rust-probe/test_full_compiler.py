import contextlib
import io
import json
import os
import shutil
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import full_compiler as full
import probe
import shader_matrix
import validate

PARSER = '''pub type size_t = usize;
pub struct parse_initializer {
    pub args_count: ::core::ffi::c_uint,
}
pub struct hlsl_attribute {
    pub args_count: ::core::ffi::c_uint,
    pub args: [hlsl_src; 0],
}
let size = offset_of!(
    hlsl_attribute, args[(* yyvsp.offset(- 2isize)).initializer
    .args_count as usize]
) as size_t;
'''


class FullCompilerTests(unittest.TestCase):
    def collect_fixture(self, root, invalid=None, valid_new=False, working_success=False):
        artifacts = root / 'artifacts'
        artifacts.mkdir()
        output = artifacts / 'rust'
        shutil.copytree(Path(__file__).parent / 'full-compiler-fixtures/generated', output)
        parser = output / 'src/vkd3d_shader/hlsl_tab.rs'
        if invalid == 'missing':
            parser.unlink()
        elif invalid == 'ambiguous':
            shutil.copy2(parser, output / 'src/hlsl_tab.rs')
        elif invalid in ('outside', 'inside'):
            target = root / 'hlsl_tab.rs' if invalid == 'outside' else output / 'src/parser-target.rs'
            parser.rename(target)
            parser.symlink_to(target)
        if valid_new:
            parser.write_text('pub unsafe extern "C" fn new_generator_output() {}\n')
        before = {p.relative_to(output): full.digest(p) for p in output.rglob('*') if p.is_file()}
        calls = []

        def execute(command, log, **kwargs):
            calls.append(log.stem)
            log.write_text('')
            if log.stem in ('cargo-stable', 'cargo-working-stable'):
                self.assertNotIn('RUSTC_BOOTSTRAP', kwargs['env'])
                self.assertNotIn('RUSTFLAGS', kwargs['env'])
            if working_success and log.stem == 'cargo-working-stable':
                return {'exit_code': 0}
            return {'exit_code': 101 if log.stem.startswith('cargo-') else 0}

        result = {}
        full.collect(result, SimpleNamespace(rust_toolchain='1.95.0', build_timeout=5),
                     root, output, [{'arguments': ['clang', '-c', 'fixture.c']}], artifacts,
                     execute, lambda: None)
        self.assertEqual(before, {p.relative_to(output): full.digest(p)
                                  for p in output.rglob('*') if p.is_file()})
        return result, calls, artifacts

    def test_new_generator_output_reaches_working_build_without_source_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, artifacts = self.collect_fixture(Path(directory), valid_new=True)
            self.assertNotIn('working_copy_failure', result)
            self.assertTrue(result['working_source_identity']['equal'])
            self.assertEqual(full.source_manifest(artifacts / 'rust'),
                             full.source_manifest(artifacts / 'rust-working'))
            self.assertIn('cargo-working-stable', calls)
            self.assertEqual(result['stable_build']['exit_code'], 101)
            self.assertEqual(result['working_stable_build']['exit_code'], 101)
            self.assertEqual(result['bootstrap_build']['exit_code'], 101)
            self.assertEqual(result['prototype_build']['exit_code'], 101)
            self.assertEqual(probe.outcome(dict(result, complete_translation=True,
                             transpile={'exit_code': 0})), 'compiler_failure')

    def test_working_stable_success_skips_bootstrap_and_preserves_raw_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.collect_fixture(Path(directory), working_success=True)
            self.assertEqual(result['stable_build']['exit_code'], 101)
            self.assertEqual(result['working_stable_build']['exit_code'], 0)
            self.assertNotIn('cargo-bootstrap', calls)
            self.assertNotIn('cargo-prototype', calls)
            self.assertEqual(probe.outcome(dict(result, complete_translation=True,
                             transpile={'exit_code': 0})), 'linker_failure')

    def test_changed_working_copy_is_rejected_before_build(self):
        copytree = shutil.copytree
        def corrupt(source, target, *args, **kwargs):
            result = copytree(source, target, *args, **kwargs)
            if Path(target).name == 'rust-working':
                (Path(target) / 'lib.rs').write_text('changed source')
            return result
        with tempfile.TemporaryDirectory() as directory, patch.object(full.shutil, 'copytree', corrupt):
            result, calls, _ = self.collect_fixture(Path(directory))
            self.assertFalse(result['working_source_identity']['equal'])
            self.assertIn('manifest differs', result['working_copy_failure'])
            self.assertEqual(calls, ['cargo-stable'])

    def test_missing_or_ambiguous_nested_parser_stops_before_working_build(self):
        for invalid in ('missing', 'ambiguous'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                result, calls, artifacts = self.collect_fixture(Path(directory), invalid)
                self.assertIn('missing, ambiguous, or outside-owned generated parser', result['working_copy_failure'])
                self.assertEqual(calls, ['cargo-stable'])
                self.assertNotIn('working_stable_build', result)

    def test_collect_rejects_outside_parser_before_copy_and_working_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, calls, artifacts = self.collect_fixture(root, 'outside')
            self.assertIn('outside-owned generated parser', result['working_copy_failure'])
            self.assertEqual(calls, ['cargo-stable'])
            self.assertNotIn('working_stable_build', result)
            self.assertFalse((artifacts / 'rust-working').exists())
            parser = artifacts / 'rust/src/vkd3d_shader/hlsl_tab.rs'
            self.assertTrue(parser.is_symlink())
            fixture = Path(__file__).parent / 'full-compiler-fixtures/generated/src/vkd3d_shader/hlsl_tab.rs'
            self.assertEqual((root / 'hlsl_tab.rs').read_bytes(), fixture.read_bytes())

    def test_collect_accepts_parser_symlink_inside_owned_output(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.collect_fixture(Path(directory), 'inside')
            self.assertNotIn('working_copy_failure', result)
            self.assertTrue(result['working_source_identity']['equal'])
            self.assertIn('cargo-working-stable', calls)

    def test_outside_generated_parser_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            working = root / 'working'
            (working / 'src').mkdir(parents=True)
            outside = root / 'hlsl_tab.rs'
            outside.write_text(PARSER)
            (working / 'src/hlsl_tab.rs').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'outside-owned'):
                full.generated_parser(working)
            self.assertEqual(outside.read_text(), PARSER)

    def test_stable_environment_clears_inherited_experimental_flags(self):
        with patch.dict(os.environ, {key: 'injected' for key in (
            'RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER',
            'RUSTC_WORKSPACE_WRAPPER', 'RUSTDOCFLAGS')}):
            env = full.stable_env(Path('/tmp/probe-target'))
        for key in ('RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER'):
            self.assertNotIn(key, env)

    def test_all_unit_outcomes_require_link_and_real_comparison(self):
        result = {'all_unit_prototype': True, 'complete_translation': True,
                  'transpile': {'exit_code': 0}, 'stable_build': {'exit_code': 101},
                  'bootstrap_build': {'exit_code': 0}}
        self.assertEqual(probe.outcome(result), 'linker_failure')
        result['link'] = {'status': 'success'}
        self.assertEqual(probe.outcome(result), 'runtime_unverified')
        result['runtime_comparison'] = {'status': 'success'}
        self.assertEqual(probe.outcome(result), 'prototype_success')

    def test_validator_checks_exact_inventory_not_count_and_rejects_prototype(self):
        result = {'all_unit_prototype': True, 'status': 'prototype_success', 'complete_translation': True,
                  'transpile': {'exit_code': 0}, 'stable_build': {'exit_code': 101},
                  'working_stable_build': {'exit_code': 0}, 'link': {'status': 'success'},
                  'runtime_comparison': {'status': 'success'},
                  'input_sha256': {unit: 'hash' for unit in full.UNITS},
                  'translated_sources': list(full.UNITS), 'syntax': [{'exit_code': 0}] * 24}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            for wrong_inventory in (False, True):
                if wrong_inventory:
                    result['input_sha256']['libs/vkd3d-shader/imposter.c'] = result['input_sha256'].pop(full.UNITS[0])
                path.write_text(json.dumps(result))
                with patch('sys.argv', ['validate.py', str(path), '--all-units']), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(validate.main(), 1)
                self.assertIn('incomplete' if wrong_inventory else 'prototype_success', output.getvalue())

    def test_matching_native_rejections_are_not_runtime_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'native.so'
            library.touch()
            def reject(command, log, **kwargs):
                output = Path(command[4])
                output.write_bytes(b'')
                Path(str(output) + '.status').write_text('-4')
                Path(str(output) + '.diagnostics').write_text('rejected')
                return {'exit_code': 0}
            result = shader_matrix.compare(root / 'driver', library, root, reject)
            self.assertEqual(len(result['cases']), 48)
            self.assertEqual(result['status'], 'comparison_failure')
            self.assertTrue(all(case['status'] == 'compile_failure' for case in result['cases']))


if __name__ == '__main__':
    unittest.main()
