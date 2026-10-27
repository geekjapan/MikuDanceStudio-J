"""Check function-pointer value reads against C on stable Rust 2024.

--focused compiles the real null-conversion method and pinned AST builder with
expression/type/context shims. --c2rust compiles untouched actual translation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from apply_c2rust_patch import REVISION
from check_enum_constants import method
from full_compiler import stable_env

HARNESS = r'''
#![allow(dead_code)]
use c2rust_ast_builder::mk;
use quote::ToTokens;
use syn::{Expr, UnOp};
macro_rules! format_err { ($($x:tt)*) => { format!($($x)*) } }
macro_rules! format_translation_err { ($where:expr, $($x:tt)*) => { format!($($x)*) } }
#[derive(Clone, Copy)] struct ExprContext { is_const: bool }
impl ExprContext { fn decay_ref(self) -> Self { self } }
struct QualType { ctype: bool }
struct IdOrExpr(Box<Expr>);
impl IdOrExpr { fn type_id(&self, _: &Ast) -> Option<QualType> { Some(QualType { ctype: true }) } }
struct Ast;
impl Ast { fn is_function_pointer(&self, yes: bool) -> bool { yes } }
struct WithStmts<T> { val: T, stmts: Vec<syn::Stmt>, is_unsafe: bool }
impl<T> WithStmts<T> { MAP }
type TranslationResult<T> = Result<T, String>;
struct Translation { ast_context: Ast }
impl Translation {
    fn convert_expr(&self, _: ExprContext, expr: IdOrExpr, _: Option<()>) -> TranslationResult<WithStmts<Box<Expr>>> {
        Ok(WithStmts { val: expr.0, stmts: vec![syn::parse_quote!(let _preserved = ();)], is_unsafe: true })
    }
    CONVERT
}
fn main() {
    let t = Translation { ast_context: Ast };
    let emit = |expr: &str, is_null| {
        let result = t.convert_pointer_is_null(ExprContext { is_const: false }, IdOrExpr(syn::parse_str(expr).unwrap()), is_null).unwrap();
        assert!(result.is_unsafe);
        assert_eq!(result.stmts.len(), 1);
        result.val.to_token_stream().to_string()
    };
    println!("type Callback = Option<unsafe extern \"C\" fn() -> i32>; unsafe extern \"C\" fn yes() -> i32 {{ 7 }}");
    println!("static mut FILE: Callback = None; static IMMUTABLE: Callback = Some(yes); static IMMUTABLE_NULL: Callback = None; static mut VOLATILE: Callback = None;");
    println!("static mut CALLS: i32 = 0; unsafe fn next(p: Callback) -> Callback {{ CALLS += 1; p }}");
    println!("struct Holder {{ fp: Callback }} unsafe fn next_holder(h: *mut Holder) -> *mut Holder {{ CALLS += 1; h }}");
    for (name, init, expr) in [
        ("fp_volatile_local", "let p = if n != 0 { Some(yes as unsafe extern \"C\" fn() -> i32) } else { None };", "core::ptr::read_volatile(&raw const p)"),
        ("fp_volatile_static", "let _ = n;", "core::ptr::read_volatile(&raw const VOLATILE)"),
        ("fp_const_volatile", "let p = if n != 0 { Some(yes as unsafe extern \"C\" fn() -> i32) } else { None };", "core::ptr::read_volatile(&raw const p)"),
    ] { println!("unsafe fn {name}(n: i32) -> i32 {{ {init} ({}) as i32 }}", emit(expr, false)); }
    println!("unsafe fn function_pointer_nulls(n: i32, out: *mut i32) -> i32 {{ let p: Callback = if n != 0 {{ Some(yes) }} else {{ None }}; let local = p; static mut BLOCK: Callback = None; let mut h = Holder {{ fp: p }}; let array = [p]; FILE = p; BLOCK = p; VOLATILE = p; let mut i = 0; macro_rules! put {{ ($v:expr) => {{{{ *out.add(i) = $v; i += 1; }}}} }}");
    for expr in ["p", "local", "FILE", "BLOCK", "IMMUTABLE", "IMMUTABLE_NULL", "h.fp", "array[0]"] {
        for null in [false, true, false, true, true, false, false] { println!("put!(({}) as i32);", emit(expr, null)); }
        for null in [false, true, false, true, true, false, false] { println!("put!(if {} {{ 1 }} else {{ 0 }});", emit(expr, null)); }
    }
    println!("put!(fp_volatile_local(n)); put!(fp_volatile_static(n)); put!(fp_const_volatile(n));");
    for (setup, expr, count) in [("CALLS = 0;", "next(p)", "CALLS"), ("CALLS = 0;", "(*next_holder(&raw mut h)).fp", "CALLS"), ("let mut index = 0;", "array[{ let old = index; index += 1; old }]", "index")] {
        println!("{setup} put!(({}) as i32); put!({count} as i32);", emit(expr, false));
    }
    for (null, op) in [(false, "&&"), (false, "||"), (true, "&&"), (true, "||")] {
        println!("CALLS = 0; put!(({} {op} {}) as i32); put!(CALLS);", emit("next(p)", null), emit("next(p)", false));
    }
    println!("CALLS = 0; put!((if {} {{ {} }} else {{ {} }}) as i32); put!(CALLS);", emit("p", false), emit("next(p)", false), emit("next(p)", false));
    println!("let mut result = 0; while {} {{ result = 1; break; }} put!(result);", emit("p", false));
    println!("let mut result = 0; while {} {{ result = 1; break; }} put!(result);", emit("p", false));
    println!("put!(if {} {{ 1 }} else {{ 0 }}); i as i32 }}", emit("p", false));
}
'''

CALLER = r'''
unsafe extern "C" { fn native_function_pointer_nulls(n: i32, out: *mut i32) -> i32; }
fn main() { unsafe {
    for n in [0, 1] {
        let (mut native, mut generated) = ([0; 160], [0; 160]);
        assert_eq!(native_function_pointer_nulls(n, native.as_mut_ptr()), 134);
        assert_eq!(function_pointer_nulls(n, generated.as_mut_ptr()), 134);
        let mut expected = Vec::new();
        for v in [n, n, n, n, 1, 0, n, n] {
            let row = [v, 1-v, v, 1-v, 1-v, v, v];
            expected.extend(row); expected.extend(row);
        }
        expected.extend([n, n, n, n, 1, n, 1, n, 1]);
        expected.extend([n, 1+n, n, 2-n, 0, 2-n, 1, 1+n]);
        expected.extend([n, 1, n, n, n]);
        assert_eq!(&native[..134], expected, "native n={n}");
        assert_eq!(&generated[..134], expected, "generated n={n}");
        assert_eq!(native, generated);
    }
    println!("Function pointer nulls passed 268 native comparisons, value reads, single evaluation and short circuiting.");
} }
'''


def inspect_volatile(text):
    """Require one volatile read and raw address per isolated actual C read."""
    for name in ['fp_volatile_local', 'fp_volatile_static', 'fp_const_volatile']:
        body = method(text, 'fn ' + name + '(')
        if len(re.findall(r'\bread_volatile\b', body)) != 1:
            raise RuntimeError(name + ' must retain exactly one volatile read')
        if len(re.findall(r'&\s*raw\s+(?:const|mut)\b', body)) != 1:
            raise RuntimeError(name + ' must use exactly one raw address')


def check(source, artifacts, focused=False, c2rust=None, clang='clang', fixture=None):
    source, artifacts = source.resolve(), artifacts.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise ValueError('C2Rust revision differs from pinned official source')
    fixture = fixture or source / 'tests/unit/pointers/src/function_pointer_nulls.c'
    artifacts.mkdir(parents=True, exist_ok=False)
    translated = artifacts / 'translated.c'
    translated.write_bytes(fixture.read_bytes())
    result = dict(official_revision=revision, mode='focused' if focused else 'actual-translator', status='incomplete',
                  source_sha256=hashlib.sha256(translated.read_bytes()).hexdigest(), stages={})
    env = stable_env(artifacts / 'target')

    def run(name, args):
        proc = subprocess.run(args, cwd=artifacts, env=env, capture_output=True, text=True, timeout=180)
        (artifacts / (name + '.log')).write_text(proc.stdout + proc.stderr)
        result['stages'][name] = dict(command=[str(a) for a in args], exit_code=proc.returncode)
        if proc.returncode:
            raise RuntimeError(f'{name} exited {proc.returncode}')
        return proc.stdout

    try:
        names = ['function_pointer_nulls', 'fp_volatile_local', 'fp_volatile_static', 'fp_const_volatile']
        run('native', [clang, '-std=c11', *['-D' + n + '=native_' + n for n in names], '-c', str(translated), '-o', str(artifacts / 'native.o')])
        if focused:
            convert = method((source / 'c2rust-transpile/src/translator/pointers.rs').read_text(), 'pub(crate) fn convert_pointer_is_null(')
            mapping = method((source / 'c2rust-transpile/src/with_stmts.rs').read_text(), 'pub fn map<U, F>')
            harness = HARNESS.replace('CONVERT', convert).replace('MAP', mapping)
            project = artifacts / 'emitter'
            (project / 'src').mkdir(parents=True)
            (project / 'src/main.rs').write_text(harness)
            (project / 'Cargo.toml').write_text('[package]\nname="function-pointer-null-check"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[dependencies]\nc2rust-ast-builder={path=' + json.dumps(str(source / 'c2rust-ast-builder')) + '}\nquote="1"\nsyn={version="2.0",features=["full"]}\n')
            (project / 'Cargo.lock').write_bytes((source / 'Cargo.lock').read_bytes())
            body = run('emitter', ['cargo', '+1.95.0', 'run', '--offline', '--quiet', '--manifest-path', str(project / 'Cargo.toml')])
            generated = artifacts / 'focused.rs'
            generated.write_text(body)
            prefix = body
        else:
            database = artifacts / 'compile_commands.json'
            database.write_text(json.dumps([dict(directory=str(artifacts), file=str(translated), arguments=[clang, '-std=c11', '-c', str(translated)])], indent=2))
            run('transpile', [str(c2rust.with_name('c2rust-transpile')), '--fail-on-error', '--disable-rustfmt', '--edition', '2024', '--output-dir', str(artifacts / 'rust'), str(database)])
            matches = list((artifacts / 'rust').rglob('translated.rs'))
            if len(matches) != 1:
                raise RuntimeError('expected one translated.rs')
            generated = matches[0]
            run('generated-build', ['rustc', '+1.95.0', '--edition', '2024', '--crate-type', 'staticlib', str(generated), '-o', str(artifacts / 'libtranslated.a')])
            prefix = 'unsafe extern "C" { fn function_pointer_nulls(n: i32, out: *mut i32) -> i32; }\n'
        result['generated_sha256'] = hashlib.sha256(generated.read_bytes()).hexdigest()
        inspect_volatile(generated.read_text())
        result['volatile_reads'] = dict(fp_volatile_local=1, fp_volatile_static=1, fp_const_volatile=1)
        caller = artifacts / 'caller.rs'
        caller.write_text(prefix + CALLER)
        flags = [] if focused else ['-C', 'link-arg=' + str(artifacts / 'libtranslated.a')]
        run('rust-build', ['rustc', '+1.95.0', '--edition', '2024', str(caller), '-C', 'link-arg=' + str(artifacts / 'native.o'), *flags, '-o', str(artifacts / 'null-check')])
        run('numeric', [str(artifacts / 'null-check')])
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
    result = check(args.source, args.artifacts, args.focused, args.c2rust.resolve() if args.c2rust else None, args.clang, args.fixture)
    print(json.dumps(result, indent=2))
    raise SystemExit(result['status'] != 'success')
