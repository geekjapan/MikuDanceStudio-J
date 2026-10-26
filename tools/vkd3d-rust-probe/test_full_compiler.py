import contextlib
import io
import json
import os
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
    def test_exact_parser_patch_preserves_other_bytes_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'parser.rs'
            path.write_text(PARSER)
            report = full.patch_parser(path)
            self.assertEqual(path.read_text(), PARSER[:PARSER.index('offset_of!')] + full.GOOD_OFFSET + ';\n')
            self.assertNotEqual(report['original_sha256'], report['patched_sha256'])
            self.assertEqual(report['patched_occurrences'], 1)
            # Reapplying or a changed generator shape must stop, never guess.
            patched = path.read_bytes()
            with self.assertRaises(ValueError):
                full.patch_parser(path)
            self.assertEqual(path.read_bytes(), patched)

    def test_unexpected_parser_shapes_are_rejected_without_writes(self):
        candidates = [PARSER.replace('[hlsl_src; 0]', '[*mut hlsl_src; 0]'),
                      PARSER.replace('= usize;', '= u32;'), PARSER + PARSER,
                      PARSER.replace('offset(- 2isize)', 'offset(- 3isize)')]
        for text in candidates:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'parser.rs'
                path.write_text(text)
                with self.assertRaises(ValueError):
                    full.patch_parser(path)
                self.assertEqual(path.read_text(), text)

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
                  'bootstrap_build': {'exit_code': 0}, 'link': {'status': 'success'},
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
