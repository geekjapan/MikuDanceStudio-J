"""Compile the pinned translator's offsetof token construction without rebuilding LLVM.

This focused check adapts the record predicate to a boolean input. It exercises
actual AST-builder and syn APIs, not the exporter or full translator pipeline.
"""
import argparse
import json
from pathlib import Path
import subprocess

from apply_c2rust_patch import REVISION
from full_compiler import stable_env


def check(source, artifacts):
    source = source.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise ValueError('C2Rust revision differs from pinned official source')
    artifacts.mkdir(parents=True, exist_ok=True)
    text = (source / 'c2rust-transpile/src/translator/mod.rs').read_text()
    branch = text.split('OffsetOfKind::Variable(qty, field_id, expr_id) => {', 1)[1]
    field = branch.split('let field_ident = mk().ident(field_name);', 1)[1].split('let field_ty =', 1)[0]
    if 'let field_path:' in field:
        assert 'let record_id = self.ast_context.parents[field_id];' in field
        field = field.replace('let record_id = self.ast_context.parents[field_id];', '')
        field = field.replace('self.ast_context.has_inner_struct_decl(record_id)', 'aligned')
    else:
        field = ''
    expression = branch.split('syn::parse_quote! {', 1)[1].split('\n                        }', 1)[0]
    assert expression.count('#index') == 1
    project = artifacts / 'emitter'
    (project / 'src').mkdir(parents=True, exist_ok=True)
    manifest = '''[package]
name = "offsetof-token-check"
version = "0.0.0"
edition = "2021"
[workspace]
[dependencies]
c2rust-ast-builder = { path = BUILDER }
proc-macro2 = "1.0"
syn = { version = "2.0", features = ["full", "extra-traits", "parsing", "printing"] }
quote = "1"
'''.replace('BUILDER', json.dumps(str(source / 'c2rust-ast-builder')))
    (project / 'Cargo.toml').write_text(manifest)
    (project / 'Cargo.lock').write_bytes((source / 'Cargo.lock').read_bytes())
    emitter = '''use c2rust_ast_builder::mk;
use proc_macro2::TokenStream;
use quote::ToTokens;
fn expression(aligned: bool, name: &str, ty: &str, element: &str) -> String {
    let field_name = name;
    let field_ident = mk().ident(field_name);
    FIELD
    let struct_ty: syn::Type = syn::parse_str(ty).unwrap();
    let element_ty: syn::Type = syn::parse_str(element).unwrap();
    let size_ty: syn::Type = syn::parse_quote!(u64);
    let cast_ty: syn::Type = syn::parse_quote!(u64);
    let index: syn::Expr = syn::parse_quote!({ calls += 1; index });
    let result: syn::Expr = syn::parse_quote! { EXPRESSION };
    result.to_token_stream().to_string()
}
fn main() {
    for (aligned, name, ty, element, case) in [
        (false, "mod_0", "matrix", "[u16; 3]", 0),
        (false, "mod_0", "packed", "i32", 1),
        (true, "mod_0", "aligned", "i32", 2),
        (false, "mod_0", "flexible", "i32", 3),
        (true, "mod_0", "aligned_alias", "i32", 13),
    ] {
        println!("{{ let mut calls = 0; let actual = {}; assert_eq!(actual, unsafe {{ offset_case({}, index) }}); assert_eq!(calls, 1); }}", expression(aligned, name, ty, element), case);
    }
}
'''.replace('FIELD', field).replace('EXPRESSION', expression)
    (project / 'src/main.rs').write_text(emitter)

    def run(name, args):
        result = subprocess.run(args, capture_output=True, text=True,
                                env=stable_env(artifacts / 'target'))
        (artifacts / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}; see {artifacts / (name + ".log")}')
        return result.stdout

    body = run('emitter', ['cargo', '+1.95.0', 'run', '--offline', '--quiet', '--manifest-path', str(project / 'Cargo.toml')])
    rust = '''#![allow(non_camel_case_types)]
#[repr(C)] struct matrix { head: i8, mod_0: [[u16; 3]; 4] }
#[repr(C, packed)] struct packed { head: i8, mod_0: [i32; 4] }
#[repr(C, align(32))] struct aligned(aligned_inner);
#[repr(C)] struct aligned_inner { head: i8, mod_0: [i32; 4] }
type aligned_alias = aligned;
#[repr(C)] struct flexible { head: [u64; 2], mod_0: [i32; 0] }
unsafe extern "C" { fn offset_case(which: u32, index: i64) -> u64; }
fn main() {
    for index in [0i64, 1, 3, -1, -5, u32::MAX as i64, i64::MAX, 1i64 << 62] {
        BODY
    }
    assert_eq!(core::mem::size_of::<aligned>(), 32);
    assert_eq!(core::mem::align_of::<aligned>(), 32);
    println!("Focused token API check passed 40 native C comparisons and single-evaluation assertions.");
}
'''.replace('BODY', body)
    (artifacts / 'focused.rs').write_text(rust)
    run('native', ['clang', '-std=c99', '-c', str(source / 'tests/unit/structs/src/variable_offsetof.c'), '-o', str(artifacts / 'native.o')])
    run('rust-build', ['rustc', '+1.95.0', '--edition', '2024', str(artifacts / 'focused.rs'), '-C', 'link-arg=' + str(artifacts / 'native.o'), '-o', str(artifacts / 'focused')])
    return run('numeric', [str(artifacts / 'focused')])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    print(check(args.source, args.artifacts.resolve()), end='')
