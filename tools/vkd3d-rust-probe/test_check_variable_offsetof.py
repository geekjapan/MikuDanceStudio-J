from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from check_variable_offsetof import DECLARATIONS, EXPRESSIONS, POINTER_LEAVES, fixture, fixture_bundle


class VariableOffsetofTests(unittest.TestCase):
    def source_fixture(self, source):
        for filename in {filename for filename, _ in DECLARATIONS} | {
                'libs/vkd3d-shader/' + filename for filename, _ in EXPRESSIONS}:
            path = source / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            declarations = '\n'.join(name + '\n{ int field;\n};' for file, name in DECLARATIONS if file == filename)
            expressions = '\n'.join('offsetof(' + expr + ')' for file, expr in EXPRESSIONS
                                    if 'libs/vkd3d-shader/' + file == filename)
            path.write_text(declarations + '\n' + expressions)

    def test_exact_closure_provenance_scalar_types_and_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            self.source_fixture(source)
            bundle = fixture_bundle(source)
            text = bundle['translated']
            self.assertNotIn('ACTUAL_CASES', text)
            self.assertNotIn('#include "hlsl.h"', text)
            self.assertIn('#include "hlsl.h"', bundle['original'])
            self.assertEqual(len(bundle['provenance']), 19)
            self.assertTrue(all(item['kind'] == 'exact-source' for item in bundle['provenance']))
            self.assertEqual(len(bundle['pointer_substitutes']), 6)
            for leaf in POINTER_LEAVES:
                self.assertIn('struct ' + leaf + ' { unsigned char fixture_unused; };', text)
                self.assertFalse(any(leaf + ')' in metric for metric in bundle['metrics']))
            for number, (_, expression) in enumerate(EXPRESSIONS):
                self.assertIn(f'case {number}: return offsetof({expression});', text)
            self.assertIn('unsigned int word_count = (unsigned int)index;', text)
            self.assertIn('allocator->count = (size_t)index', text)
            for filename, name in DECLARATIONS:
                self.assertIn(name + '\n{ int field;\n};', text)
                if filename.endswith('.c'):
                    self.assertIn(name + '\n{ int field;\n};', bundle['original'])
                self.assertIn('sizeof(' + name + ')', bundle['metrics'])
                self.assertIn('__alignof__(' + name + ')', bundle['metrics'])
                if name.startswith('struct '):
                    self.assertIn('offsetof(' + name + ', field)', bundle['metrics'])
            (source / 'libs/vkd3d-shader/ir.c').write_text('')
            with self.assertRaisesRegex(ValueError, 'missing actual shader expression'):
                fixture(source)

    def test_missing_and_duplicate_declarations_fail_closed(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                self.source_fixture(source)
                path = source / DECLARATIONS[0][0]
                path.write_text(path.read_text() * 2 if duplicate else '')
                with self.assertRaisesRegex(ValueError, 'exactly one actual declaration struct list'):
                    fixture(source)

    def test_caller_rejects_layout_mismatch_and_runs_exact_vectors(self):
        caller = Path(__file__).parent / 'offset-fixtures/caller.c'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Native forwarding is only a caller control, never translated success.
            source = root / 'control.c'
            template = (caller.parent / 'translated.c').read_text().replace(
                'ACTUAL_CASES', 'case 8: return 32 + (size_t)(unsigned int)index * sizeof(uint32_t);')
            source.write_text(template + '''\nsize_t native_offset_probe(unsigned int w, long long i) { return offset_probe(w, i); }
size_t extracted_offset_probe(unsigned int w, long long i) { return offset_probe(w, i); }
size_t native_layout_probe(unsigned int w) { return 8; }
size_t extracted_layout_probe(unsigned int w) { return 8; }
size_t layout_probe(unsigned int w) { return METRIC; }
''')
            for mismatch in (False, True):
                control = root / 'run.c'
                control.write_text(source.read_text().replace('METRIC', '9' if mismatch else '8'))
                binary = root / 'control'
                subprocess.run(['clang', '-std=c99', '-DLAYOUT_METRIC_COUNT=1', str(caller),
                                str(control), '-o', str(binary)], check=True, capture_output=True)
                result = subprocess.run([str(binary)], capture_output=True, text=True,
                                        cwd=root)
                if mismatch:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, 'Original/extracted/generated layout metrics 1\n'
                                     'Variable offsetof C/Rust numeric comparisons 200; actual shader expressions 10\n')

    def test_patched_expression_wraps_before_result_cast_and_evaluates_once(self):
        patch = (Path(__file__).parent / 'patches/c2rust-win64-abi.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        self.assertIn('self.convert_expr(ctx, *expr_id, None)?.map(|index|', added)
        self.assertNotIn('to_pure_expr', added)
        start = added.index('((::core::mem::offset_of!')
        end = added.index('\n                        }', start)
        expression = added[start:end].strip()
        self.assertEqual(expression.count('#index'), 1)
        self.assertIn('CTypeKind::ConstantArray(element, _)', added)
        self.assertIn('| CTypeKind::IncompleteArray(element) => element', added)
        self.assertIn('self.convert_type(ty.ctype)?', added)
        if not shutil.which('rustc'):
            self.fail('rustc is required for the focused numeric regression')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expression = (expression.replace('#struct_ty', 'Layout').replace('#field_ident', 'data')
                          .replace('#element_ty', 'u32').replace('#size_ty', 'u64')
                          .replace('#cast_ty', 'u8').replace('#index', '{ calls += 1; index }'))
            harness = '''
#[repr(C)] struct Layout { head: [u64; 2], data: [u32; 0] }
fn main() {
    for index in [0i64, 3, -1, -5, i64::MAX, 1i64 << 62] {
        let mut calls = 0;
        let actual: u8 = EXPRESSION;
        assert_eq!(actual, 16u64.wrapping_add((index as u64).wrapping_mul(4)) as u8);
        assert_eq!(calls, 1);
    }
}
'''.replace('EXPRESSION', expression)
            path = root / 'check.rs'
            path.write_text(harness)
            built = subprocess.run(['rustc', '+1.95.0', '--edition', '2024', str(path), '-o', str(root / 'check')],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            subprocess.run([str(root / 'check')], check=True)


if __name__ == '__main__':
    unittest.main()
