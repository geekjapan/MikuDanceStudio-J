"""Compare enum constant arrays with native C using the pinned translator.

--focused compiles the real ConstantExpr branch, type resolver, constant emitter,
and enum constructor with AST shims and the pinned AST builder. It does not run
the exporter or complete translator. --c2rust exercises the complete translator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from apply_c2rust_patch import REVISION
from full_compiler import stable_env


def method(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


EXPECTED = [40, 0, 3, 0x80000000, -7, 0, 13, -3, 40, 0, -7, 13, 4, 4, 4, 4, 16, 16]
HARNESS = r'''
#![allow(dead_code)]
use c2rust_ast_builder::mk;
use quote::ToTokens;
use std::{cell::RefCell, ops::Index};
use syn::Expr;
type CTypeId = usize;
type CEnumId = usize;
#[derive(Clone, Copy)] struct CQualTypeId { ctype: CTypeId }
#[derive(Clone, Copy)] enum CTypeKind {
    Enum(CEnumId), Int, Attributed(CQualTypeId, ()), Elaborated(CTypeId),
    Decayed(CTypeId), TypeOf(CTypeId), Paren(CTypeId), Typedef(DeclId), Auto(CTypeId),
}
#[derive(Clone, Copy)] struct DeclId(usize);
enum CDeclKind { Typedef { typ: CQualTypeId }, Other }
struct CType { kind: CTypeKind }
struct Decl { kind: CDeclKind }
struct Ast { types: Vec<CType>, decls: Vec<Decl> }
impl Index<CTypeId> for Ast { type Output = CType; fn index(&self, id: CTypeId) -> &CType { &self.types[id] } }
impl Index<DeclId> for Ast { type Output = Decl; fn index(&self, id: DeclId) -> &Decl { &self.decls[id.0] } }
impl Ast { RESOLVER }
#[derive(Clone, Copy)] enum ConstIntExpr { I(i64), U(u64) }
#[derive(Clone, Copy)] struct ExprContext { is_pattern: bool }
struct WithStmts<T> { val: T }
impl<T> WithStmts<T> {
    fn new_val(val: T) -> Self { Self { val } }
    fn map<U>(self, f: impl FnOnce(T) -> U) -> WithStmts<U> { WithStmts::new_val(f(self.val)) }
}
type TranslationResult<T> = Result<T, ()>;
struct Names;
impl Names { fn resolve_decl_name(&self, id: CEnumId) -> Option<String> { Some(if id == 0 { "Operand" } else { "Signed" }.into()) } }
struct Translation { ast_context: Ast, type_converter: RefCell<Names> }
fn neg_expr(value: Box<Expr>) -> Box<Expr> { mk().unary_expr(syn::UnOp::Neg(Default::default()), value) }
impl Translation {
    fn add_import(&self, _: CEnumId, _: &str) {}
    fn convert_expr(&self, _: ExprContext, _: usize, _: Option<CQualTypeId>) -> TranslationResult<WithStmts<Box<Expr>>> {
        Ok(WithStmts::new_val(mk().lit_expr(mk().int_unsuffixed_lit(77))))
    }
    CONSTANT
    CONSTRUCTOR
    fn constant_expr(&self, ctx: ExprContext, ty: CQualTypeId, override_ty: Option<CQualTypeId>, value: Option<ConstIntExpr>) -> TranslationResult<WithStmts<Box<Expr>>> {
        let child = 0;
        BRANCH
    }
}
fn main() {
    let t = Translation { ast_context: Ast {
        types: vec![CType { kind: CTypeKind::Enum(0) }, CType { kind: CTypeKind::Enum(1) }, CType { kind: CTypeKind::Int }, CType { kind: CTypeKind::Typedef(DeclId(0)) }],
        decls: vec![Decl { kind: CDeclKind::Typedef { typ: CQualTypeId { ctype: 1 } } }],
    }, type_converter: RefCell::new(Names) };
    let ctx = ExprContext { is_pattern: false };
    let emit = |ty, override_ty: Option<CTypeId>, value| t.constant_expr(ctx, CQualTypeId { ctype: ty }, override_ty.map(|ctype| CQualTypeId { ctype }), Some(value)).unwrap().val.to_token_stream().to_string();
    println!("static OPERANDS: [Operand; 4] = [{}];", [40, 0, 3, 0x80000000].map(|v| emit(2, Some(0), ConstIntExpr::U(v))).join(","));
    println!("static SIGNED: [SignedAlias; 4] = [{}];", [-7, 0, 13, -3].map(|v| emit(3, None, ConstIntExpr::I(v))).join(","));
    println!("static INTEGERS: [i32; 4] = [{}];", [40, 0, -7, 13].map(|v| emit(1, Some(2), ConstIntExpr::I(v))).join(","));
    let pattern = t.constant_expr(ExprContext { is_pattern: true }, CQualTypeId { ctype: 0 }, Some(CQualTypeId { ctype: 0 }), Some(ConstIntExpr::U(40))).unwrap().val;
    assert_eq!(pattern.to_token_stream().to_string(), "77");
    assert_eq!(t.constant_expr(ctx, CQualTypeId { ctype: 0 }, None, None).unwrap().val.to_token_stream().to_string(), "77");
}
'''


def check(source, artifacts, focused=False, c2rust=None, fixture=None, clang='clang'):
    source, artifacts = source.resolve(), artifacts.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise ValueError('C2Rust revision differs from pinned official source')
    fixture = fixture or source / 'tests/unit/enums/src/constant_array.c'
    artifacts.mkdir(parents=True, exist_ok=False)
    translated = artifacts / 'translated.c'
    translated.write_bytes(fixture.read_bytes())
    result = {'official_revision': revision, 'mode': 'focused' if focused else 'actual-translator',
              'status': 'incomplete', 'source_sha256': hashlib.sha256(translated.read_bytes()).hexdigest(),
              'stages': {}}
    env = stable_env(artifacts / 'target')

    def run(name, args):
        process = subprocess.run(args, cwd=artifacts, env=env, capture_output=True, text=True, timeout=180)
        (artifacts / (name + '.log')).write_text(process.stdout + process.stderr)
        result['stages'][name] = {'command': [str(arg) for arg in args], 'exit_code': process.returncode}
        if process.returncode:
            raise RuntimeError(f'{name} exited {process.returncode}')
        return process.stdout

    try:
        run('native', [clang, '-std=c99', '-Denum_array_probe=native_enum_array_probe', '-c', str(translated), '-o', str(artifacts / 'native.o')])
        if focused:
            mod = (source / 'c2rust-transpile/src/translator/mod.rs').read_text()
            enums = (source / 'c2rust-transpile/src/translator/enums.rs').read_text()
            ast = (source / 'c2rust-transpile/src/c_ast/mod.rs').read_text()
            branch = mod.split('ConstantExpr(ty, child, value) => {', 1)[1].split('\n            DeclRef(', 1)[0].rsplit('}', 1)[0]
            harness = HARNESS.replace('BRANCH', branch).replace('CONSTANT', method(mod, 'pub fn convert_constant('))
            harness = harness.replace('CONSTRUCTOR', method(enums, 'pub(crate) fn enum_constructor_expr('))
            harness = harness.replace('RESOLVER', method(ast, 'pub fn resolve_type_id(') + method(ast, 'pub fn resolve_type('))
            project = artifacts / 'emitter'
            (project / 'src').mkdir(parents=True)
            (project / 'src/main.rs').write_text(harness)
            (project / 'Cargo.toml').write_text('[package]\nname="enum-constant-check"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[dependencies]\nc2rust-ast-builder={path=' + json.dumps(str(source / 'c2rust-ast-builder')) + '}\nquote="1"\nsyn={version="2.0",features=["full"]}\n')
            (project / 'Cargo.lock').write_bytes((source / 'Cargo.lock').read_bytes())
            body = run('emitter', ['cargo', '+1.95.0', 'run', '--offline', '--quiet', '--manifest-path', str(project / 'Cargo.toml')])
            generated = artifacts / 'focused.rs'
            generated.write_text('''#[repr(transparent)] struct Operand(u32);
#[repr(transparent)] struct Signed(i32);
type SignedAlias = Signed;
BODY
fn generated(which: u32) -> i64 {
    match which { 0..=3 => OPERANDS[which as usize].0 as i64,
        4..=7 => SIGNED[(which-4) as usize].0 as i64,
        8..=11 => INTEGERS[(which-8) as usize] as i64,
        12 => size_of::<Operand>() as i64, 13 => align_of::<Operand>() as i64,
        14 => size_of::<SignedAlias>() as i64, 15 => align_of::<SignedAlias>() as i64,
        16 => size_of::<[Operand; 4]>() as i64, 17 => size_of::<[SignedAlias; 4]>() as i64,
        _ => -999 }
}
'''.replace('BODY', body))
            prefix = generated.read_text()
        else:
            database = artifacts / 'compile_commands.json'
            database.write_text(json.dumps([{'directory': str(artifacts), 'file': str(translated), 'arguments': [clang, '-std=c99', '-c', str(translated)]}], indent=2))
            run('transpile', [str(c2rust.with_name('c2rust-transpile')), '--fail-on-error', '--disable-rustfmt', '--edition', '2024', '--output-dir', str(artifacts / 'rust'), str(database)])
            matches = list((artifacts / 'rust').rglob('translated.rs'))
            if len(matches) != 1:
                raise RuntimeError('expected one translated.rs')
            generated = matches[0]
            result['generated_sha256'] = hashlib.sha256(generated.read_bytes()).hexdigest()
            run('generated-build', ['rustc', '+1.95.0', '--edition', '2024', '--crate-type', 'staticlib', str(generated), '-o', str(artifacts / 'libtranslated.a')])
            prefix = 'unsafe extern "C" { #[link_name="enum_array_probe"] fn generated(which: u32) -> i64; }\n'
        result['generated_sha256'] = hashlib.sha256(generated.read_bytes()).hexdigest()
        caller = artifacts / 'caller.rs'
        caller.write_text(prefix + '''
unsafe extern "C" { fn native_enum_array_probe(which: u32) -> i64; }
fn main() {
    let expected: [i64; 18] = EXPECTED;
    for (which, value) in expected.into_iter().enumerate() {
        unsafe {
            assert_eq!(native_enum_array_probe(which as u32), value, "native case {which}");
            assert_eq!(generated(which as u32), value, "generated case {which}");
        }
    }
    println!("Enum constant arrays passed 12 value and 6 layout comparisons against native C.");
}
'''.replace('EXPECTED', repr(EXPECTED)))
        flags = [] if focused else ['-C', 'link-arg=' + str(artifacts / 'libtranslated.a')]
        run('rust-build', ['rustc', '+1.95.0', '--edition', '2024', str(caller), '-C', 'link-arg=' + str(artifacts / 'native.o'), *flags, '-o', str(artifacts / 'enum-check')])
        run('numeric', [str(artifacts / 'enum-check')])
        result['status'] = 'success'
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        result.update(status='failure', error=str(error))
    finally:
        (artifacts / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--clang', default='clang')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--focused', action='store_true')
    mode.add_argument('--c2rust', type=Path)
    args = parser.parse_args()
    result = check(args.source, args.artifacts, args.focused, args.c2rust.resolve() if args.c2rust else None, args.fixture, args.clang)
    print(json.dumps(result, indent=2))
    raise SystemExit(result['status'] != 'success')
