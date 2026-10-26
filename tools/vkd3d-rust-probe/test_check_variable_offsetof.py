from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from check_variable_offsetof import DECLARATIONS, EXPRESSIONS, fixture


class VariableOffsetofTests(unittest.TestCase):
    def test_actual_expression_inventory_and_declarations_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            shader = source / 'libs/vkd3d-shader'
            shader.mkdir(parents=True)
            for filename in set(DECLARATIONS) | {name for name, _ in EXPRESSIONS}:
                declarations = '\n'.join(name + '\n{ int field;\n};' for name in DECLARATIONS.get(filename, []))
                expressions = '\n'.join('offsetof(' + expr + ')' for name, expr in EXPRESSIONS if name == filename)
                (shader / filename).write_text(declarations + '\n' + expressions)
            text = fixture(source)
            self.assertNotIn('ACTUAL_CASES', text)
            for number, (_, expression) in enumerate(EXPRESSIONS):
                self.assertIn(f'case {number}: return offsetof({expression});', text)
            self.assertIn('allocator->count = (size_t)index', text)
            (shader / 'ir.c').write_text('')
            with self.assertRaisesRegex(ValueError, 'missing actual shader expression'):
                fixture(source)

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
