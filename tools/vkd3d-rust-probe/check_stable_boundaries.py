"""Check bounded stable atomic/opaque lowering against native C.

--focused compiles the real shared atomic method, type resolver and opaque item
builder with AST shims. --c2rust checks untouched output of the actual translator.
Neither mode enables bootstrap, nightly features or static_mut_refs suppression.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from apply_c2rust_patch import REVISION
from check_enum_constants import method
from full_compiler import stable_env

HARNESS = r'''
#![allow(dead_code)]
use c2rust_ast_builder::mk;
use quote::ToTokens;
use syn::{Expr, Item, Type, BinOp, UnOp};
use std::{cell::{Cell, RefCell}, ops::Index, sync::atomic::Ordering};
type CTypeId = usize;
#[derive(Clone, Copy)] struct CExprId(usize);
#[derive(Clone, Copy)] struct CQualTypeId { ctype: CTypeId }
#[derive(Clone, Copy)] enum CTypeKind {
    UInt, UInt32, ULongLong, UInt64, Int, Int32, Atomic(CQualTypeId), Pointer(CQualTypeId), Attributed(CQualTypeId, ()),
    Elaborated(CTypeId), Decayed(CTypeId), TypeOf(CTypeId), Paren(CTypeId), Typedef(DeclId), Auto(CTypeId),
}
impl CTypeKind { fn is_unsigned_integral_type(&self) -> bool { matches!(self, Self::UInt | Self::UInt32 | Self::ULongLong | Self::UInt64) } }
#[derive(Clone, Copy)] struct DeclId(usize);
enum CDeclKind { Typedef { typ: CQualTypeId }, Other }
struct CType { kind: CTypeKind }
struct Decl { kind: CDeclKind }
struct CExpr { kind: ExprKind }
struct ExprKind(CQualTypeId);
impl ExprKind { fn get_qual_type(&self) -> Option<CQualTypeId> { Some(self.0) } }
struct Ast { types: Vec<CType>, decls: Vec<Decl>, exprs: Vec<CExpr> }
impl Index<CTypeId> for Ast { type Output = CType; fn index(&self, id: CTypeId) -> &CType { &self.types[id] } }
impl Index<CExprId> for Ast { type Output = CExpr; fn index(&self, id: CExprId) -> &CExpr { &self.exprs[id.0] } }
impl Index<DeclId> for Ast { type Output = Decl; fn index(&self, id: DeclId) -> &Decl { &self.decls[id.0] } }
impl Ast { RESOLVER
    fn index<T>(&self, id: T) -> &<Self as Index<T>>::Output where Self: Index<T> { &self[id] }
}
#[derive(Clone, Copy)] struct ExprContext;
struct WithStmts<T> { stmts: Vec<syn::Stmt>, val: T }
impl<T> WithStmts<T> {
    fn new_val(val: T) -> Self { Self { stmts: vec![], val } }
    fn new(stmts: Vec<syn::Stmt>, val: T) -> Self { Self { stmts, val } }
}
type TranslationResult<T> = Result<T, ()>;
struct Names;
struct Namespaces;
impl Namespaces { fn values() {} }
impl Names { fn pick_name(&mut self, name: &str, _: ()) -> String { name.into() } }
struct Translation { ast_context: Ast, renamer: RefCell<Names>, features: Cell<bool> }
impl Translation {
    fn convert_side_effects_expr(&self, _: ExprContext, val: WithStmts<Box<Expr>>, _: &str) -> WithStmts<Box<Expr>> { val }
    fn atomic_intrinsic_expr(&self, _: &str, _: &[Ordering]) -> Box<Expr> {
        self.features.set(true);
        syn::parse_quote!(::core::intrinsics::atomic_xadd::<_, _, {::core::intrinsics::AtomicOrdering::SeqCst}>)
    }
    ATOMIC
}
OPS
OPAQUE
fn main() {
    let t = Translation { ast_context: Ast {
        types: vec![CType { kind: CTypeKind::UInt }, CType { kind: CTypeKind::Typedef(DeclId(0)) },
            CType { kind: CTypeKind::Pointer(CQualTypeId { ctype: 1 }) }, CType { kind: CTypeKind::Int },
            CType { kind: CTypeKind::Pointer(CQualTypeId { ctype: 3 }) },
            CType { kind: CTypeKind::UInt32 }, CType { kind: CTypeKind::Pointer(CQualTypeId { ctype: 5 }) },
            CType { kind: CTypeKind::ULongLong }, CType { kind: CTypeKind::Pointer(CQualTypeId { ctype: 7 }) },
            CType { kind: CTypeKind::UInt64 }, CType { kind: CTypeKind::Pointer(CQualTypeId { ctype: 9 }) },
            CType { kind: CTypeKind::Int32 }, CType { kind: CTypeKind::Pointer(CQualTypeId { ctype: 11 }) }],
        decls: vec![Decl { kind: CDeclKind::Typedef { typ: CQualTypeId { ctype: 0 } } }], exprs: (0..13).map(|ctype| CExpr { kind: ExprKind(CQualTypeId { ctype }) }).collect(),
    }, renamer: RefCell::new(Names), features: Cell::new(false) };
    for name in ["_IO_wide_data", "_IO_codecvt", "_IO_marker", "__locale_data"] {
        println!("{}", opaque_record_item(syn::Ident::new(name, proc_macro2::Span::call_site())).to_token_stream());
    }
    for (name, effect, pointer, value) in [("stable_sync", false, 2, 1), ("stable_atomic", false, 2, 1), ("stable_effects", true, 2, 1),
        ("stable_alias_sync", false, 6, 5), ("stable_alias_atomic", false, 6, 5), ("stable_alias_effects", true, 6, 5)] {
        let dst = if effect { syn::parse_quote!({ *pc += 1; x }) } else { syn::parse_quote!(x) };
        let src = if effect { syn::parse_quote!({ *vc += 1; value }) } else { syn::parse_quote!(value) };
        let ptr_id = CExprId(pointer);
        let result = t.convert_atomic_op(ExprContext, CAtomicBinOp::AddFetch, Ordering::SeqCst, PTR_ID dst, src, CQualTypeId { ctype: value }).unwrap();
        let stmts = result.stmts.iter().map(|s| s.to_token_stream().to_string()).collect::<Vec<_>>().join("\n");
        let params = if effect { ", pc: *mut u32, vc: *mut u32" } else { "" };
        println!("unsafe extern \"C\" fn {name}(x: *mut u32, value: u32{params}) -> u32 {{ {stmts} {} }}", result.val.to_token_stream());
    }
    for pointer in [2, 4, 6, 8, 10, 12] {
        for value in [1, 3, 5, 7, 9, 11] {
            for (op, order) in [(CAtomicBinOp::AddFetch, Ordering::SeqCst), (CAtomicBinOp::AddFetch, Ordering::Relaxed), (CAtomicBinOp::FetchAdd, Ordering::SeqCst)] {
                t.features.set(false);
                let ptr_id = CExprId(pointer);
                let _ = t.convert_atomic_op(ExprContext, op, order, PTR_ID syn::parse_quote!(x), syn::parse_quote!(value), CQualTypeId { ctype: value }).unwrap();
                assert_eq!(t.features.get(), !(matches!(pointer, 2 | 6) && matches!(value, 1 | 5) && op == CAtomicBinOp::AddFetch && order == Ordering::SeqCst));
            }
        }
    }

}
'''

LAYOUT = r'''
#[repr(C)] struct opaque_pointers { tag: u8, wide: *mut _IO_wide_data, codecvt: *mut _IO_codecvt, marker: *mut _IO_marker, locale: *mut __locale_data }
#[repr(C)] struct refcount { tag: u8, count: u32 }
unsafe extern "C" fn stable_layout(which: u32) -> u64 {
    use core::mem::{size_of, align_of, offset_of};
    [size_of::<opaque_pointers>(), align_of::<opaque_pointers>(), offset_of!(opaque_pointers, wide),
     offset_of!(opaque_pointers, codecvt), offset_of!(opaque_pointers, marker), offset_of!(opaque_pointers, locale),
     size_of::<refcount>(), align_of::<refcount>(), offset_of!(refcount, count), size_of::<u32>(), align_of::<u32>()][which as usize] as u64
}
unsafe extern "C" fn stable_opaque_roundtrip(value: *mut core::ffi::c_void) -> *mut core::ffi::c_void {
    let p = opaque_pointers { tag: 0, wide: value.cast(), codecvt: value.cast(), marker: value.cast(), locale: value.cast() };
    p.locale.cast()
}
'''

CALLER = r'''
unsafe extern "C" {
    fn native_stable_sync(x: *mut u32, value: u32) -> u32;
    fn native_stable_atomic(x: *mut u32, value: u32) -> u32;
    fn native_stable_effects(x: *mut u32, value: u32, pc: *mut u32, vc: *mut u32) -> u32;
    fn native_stable_alias_sync(x: *mut u32, value: u32) -> u32;
    fn native_stable_alias_atomic(x: *mut u32, value: u32) -> u32;
    fn native_stable_alias_effects(x: *mut u32, value: u32, pc: *mut u32, vc: *mut u32) -> u32;
    fn native_stable_layout(which: u32) -> u64;
    fn native_stable_opaque_roundtrip(value: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
}
fn main() { unsafe {
    for initial in [0u32, 1, u32::MAX-1, u32::MAX] {
        for delta in [0u32, 1, 2, u32::MAX] {
            for (native, generated) in [(native_stable_sync as unsafe extern "C" fn(*mut u32,u32)->u32, stable_sync as unsafe extern "C" fn(*mut u32,u32)->u32), (native_stable_atomic, stable_atomic)] {
                let (mut n, mut r) = (initial, initial);
                assert_eq!(native(&mut n, delta), initial.wrapping_add(delta));
                assert_eq!(generated(&mut r, delta), initial.wrapping_add(delta));
                assert_eq!(n, r);
            }
            let (mut n, mut r, mut np, mut nv, mut rp, mut rv) = (initial, initial, 0, 0, 0, 0);
            assert_eq!(native_stable_effects(&mut n, delta, &mut np, &mut nv), initial.wrapping_add(delta));
            assert_eq!(stable_effects(&mut r, delta, &mut rp, &mut rv), initial.wrapping_add(delta));
            assert_eq!((n, np, nv), (r, rp, rv));
            assert_eq!((rp, rv), (1, 1));
        }
    }
    for initial in [0u32, 1, u32::MAX-1, u32::MAX] {
        for delta in [0u32, 1, 2, u32::MAX] {
            for (native, generated) in [(native_stable_alias_sync as unsafe extern "C" fn(*mut u32,u32)->u32, stable_alias_sync as unsafe extern "C" fn(*mut u32,u32)->u32), (native_stable_alias_atomic, stable_alias_atomic)] {
                let (mut n, mut r) = (initial, initial);
                assert_eq!(native(&mut n, delta), initial.wrapping_add(delta));
                assert_eq!(generated(&mut r, delta), initial.wrapping_add(delta));
                assert_eq!(n, r);
            }
            let (mut n, mut r, mut np, mut nv, mut rp, mut rv) = (initial, initial, 0, 0, 0, 0);
            assert_eq!(native_stable_alias_effects(&mut n, delta, &mut np, &mut nv), initial.wrapping_add(delta));
            assert_eq!(stable_alias_effects(&mut r, delta, &mut rp, &mut rv), initial.wrapping_add(delta));
            assert_eq!((n, np, nv), (r, rp, rv));
            assert_eq!((rp, rv), (1, 1));
        }
    }
    assert_eq!(core::mem::align_of::<core::sync::atomic::AtomicU32>(), core::mem::align_of::<u32>());
    let native_count = core::sync::atomic::AtomicU32::new(0);
    let generated_count = core::sync::atomic::AtomicU32::new(0);
    std::thread::scope(|scope| {
        for _ in 0..4 {
            let (n, r) = (&native_count, &generated_count);
            scope.spawn(move || { for _ in 0..1024 {
                native_stable_sync(n.as_ptr(), 1);
                stable_sync(r.as_ptr(), 1);
            } });
        }
    });
    assert_eq!(native_count.load(core::sync::atomic::Ordering::SeqCst), 4096);
    assert_eq!(generated_count.load(core::sync::atomic::Ordering::SeqCst), 4096);
    for which in 0..11 { assert_eq!(stable_layout(which), native_stable_layout(which), "layout {which}"); }
    let mut count = 1u32;
    assert_eq!(stable_sync(&mut count, 1), 2);
    assert_eq!(stable_sync(&mut count, u32::MAX), 1);
    assert_eq!(stable_sync(&mut count, u32::MAX), 0);
    let p = core::ptr::addr_of_mut!(count).cast();
    assert_eq!(stable_opaque_roundtrip(p), p);
    assert_eq!(native_stable_opaque_roundtrip(p), p);
    assert!(stable_opaque_roundtrip(core::ptr::null_mut()).is_null());
    println!("Stable boundaries passed 48 explicit unsigned int and 48 stdint uint32_t native atomic cases, 11 layouts, single evaluation, refcounts and opaque pointers.");
} }
'''


def check(source, artifacts, focused=False, c2rust=None, clang='clang', fixture=None):
    source, artifacts = source.resolve(), artifacts.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise ValueError('C2Rust revision differs from pinned official source')
    fixture = fixture or source / 'tests/unit/builtins/src/stable_boundaries.c'
    artifacts.mkdir(parents=True, exist_ok=False)
    translated = artifacts / 'translated.c'
    translated.write_bytes(fixture.read_bytes())
    result = {'official_revision': revision, 'mode': 'focused' if focused else 'actual-translator',
              'status': 'incomplete', 'source_sha256': hashlib.sha256(translated.read_bytes()).hexdigest(), 'stages': {}}
    env = stable_env(artifacts / 'target')

    def run(name, args, expect_failure=False):
        proc = subprocess.run(args, cwd=artifacts, env=env, capture_output=True, text=True, timeout=180)
        (artifacts / (name + '.log')).write_text(proc.stdout + proc.stderr)
        result['stages'][name] = {'command': [str(a) for a in args], 'exit_code': proc.returncode}
        if (proc.returncode == 0) == expect_failure:
            raise RuntimeError(f'{name} unexpected exit {proc.returncode}')
        return proc.stdout

    names = ['stable_sync', 'stable_atomic', 'stable_effects', 'stable_alias_sync', 'stable_alias_atomic', 'stable_alias_effects', 'stable_layout', 'stable_opaque_roundtrip']
    try:
        run('native', [clang, '-std=c11', *['-D' + n + '=native_' + n for n in names], '-c', str(translated), '-o', str(artifacts / 'native.o')])
        if focused:
            atomic = (source / 'c2rust-transpile/src/translator/atomics.rs').read_text()
            mod = (source / 'c2rust-transpile/src/translator/mod.rs').read_text()
            ast = (source / 'c2rust-transpile/src/c_ast/mod.rs').read_text()
            convert = method(atomic, 'pub(crate) fn convert_atomic_op(')
            harness = HARNESS.replace('ATOMIC', convert).replace('OPS', atomic[atomic.index('#[derive(Debug, Clone, Copy, PartialEq, Eq)]'):])
            harness = harness.replace('PTR_ID ', 'ptr_id, ' if 'ptr_id: CExprId' in convert else '')
            resolver = ''.join(method(ast, sig) for sig in ['pub fn resolve_type_id(', 'pub fn resolve_type(', 'pub fn get_pointee_qual_type('])
            harness = harness.replace('RESOLVER', resolver)
            if 'fn opaque_record_item(' in mod:
                opaque = method(mod, 'fn opaque_record_item(')
            else:
                old = mod.split('self.use_feature("extern_types");', 1)[1].split('Ok(ConvertedDecl::ForeignItem(extern_item))', 1)[0]
                old = old[old.index('let extern_item'):]
                opaque = 'fn opaque_record_item(name: syn::Ident) -> Box<Item> { let span = proc_macro2::Span::call_site(); ' + old + ' mk().unsafe_().extern_("C").foreign_items(vec![*extern_item]) }'
            harness = harness.replace('OPAQUE', opaque)
            project = artifacts / 'emitter'
            (project / 'src').mkdir(parents=True)
            (project / 'src/main.rs').write_text(harness)
            (project / 'Cargo.toml').write_text('[package]\nname="stable-boundary-check"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[dependencies]\nc2rust-ast-builder={path=' + json.dumps(str(source / 'c2rust-ast-builder')) + '}\nquote="1"\nproc-macro2="1"\nsyn={version="2.0",features=["full"]}\n')
            (project / 'Cargo.lock').write_bytes((source / 'Cargo.lock').read_bytes())
            body = run('emitter', ['cargo', '+1.95.0', 'run', '--offline', '--quiet', '--manifest-path', str(project / 'Cargo.toml')])
            generated = artifacts / 'focused.rs'
            generated.write_text('#![allow(non_camel_case_types)]\n' + body + LAYOUT)
            prefix = generated.read_text()
        else:
            database = artifacts / 'compile_commands.json'
            database.write_text(json.dumps([{'directory': str(artifacts), 'file': str(translated), 'arguments': [clang, '-std=c11', '-c', str(translated)]}], indent=2))
            run('transpile', [str(c2rust.with_name('c2rust-transpile')), '--fail-on-error', '--disable-rustfmt', '--edition', '2024', '--output-dir', str(artifacts / 'rust'), str(database)])
            matches = list((artifacts / 'rust').rglob('translated.rs'))
            if len(matches) != 1:
                raise RuntimeError('expected one translated.rs')
            generated = matches[0]
            negative = artifacts / 'negative.c'
            negative.write_bytes((source / 'tests/unit/builtins/src/stable_boundaries_negative.c').read_bytes())
            database.write_text(json.dumps([{'directory': str(artifacts), 'file': str(negative), 'arguments': [clang, '-std=c11', '-c', str(negative)]}]))
            run('negative-transpile', [str(c2rust.with_name('c2rust-transpile')), '--fail-on-error', '--disable-rustfmt', '--edition', '2024', '--output-dir', str(artifacts / 'negative-rust'), str(database)])
            negative_output = list((artifacts / 'negative-rust').rglob('negative.rs'))
            if len(negative_output) != 1:
                raise RuntimeError('expected one negative.rs')
            negative_text = negative_output[0].read_text()
            if negative_text.count('::core::intrinsics::atomic_') != 4 or 'AtomicU32::from_ptr' in negative_text:
                raise RuntimeError('nonmatching atomic types, order or operation used stable lowering')
            run('generated-build', ['rustc', '+1.95.0', '--edition', '2024', '--crate-type', 'staticlib', str(generated), '-o', str(artifacts / 'libtranslated.a')])
            prefix = '''unsafe extern "C" {
fn stable_sync(x: *mut u32, value: u32) -> u32;
fn stable_atomic(x: *mut u32, value: u32) -> u32;
fn stable_effects(x: *mut u32, value: u32, pc: *mut u32, vc: *mut u32) -> u32;
fn stable_alias_sync(x: *mut u32, value: u32) -> u32;
fn stable_alias_atomic(x: *mut u32, value: u32) -> u32;
fn stable_alias_effects(x: *mut u32, value: u32, pc: *mut u32, vc: *mut u32) -> u32;
fn stable_layout(which: u32) -> u64;
fn stable_opaque_roundtrip(value: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
}\n'''
        result['generated_sha256'] = hashlib.sha256(generated.read_bytes()).hexdigest()
        caller = artifacts / 'caller.rs'
        caller.write_text(prefix + CALLER)
        flags = [] if focused else ['-C', 'link-arg=' + str(artifacts / 'libtranslated.a')]
        run('rust-build', ['rustc', '+1.95.0', '--edition', '2024', str(caller), '-C', 'link-arg=' + str(artifacts / 'native.o'), *flags, '-o', str(artifacts / 'boundary-check')])
        run('numeric', [str(artifacts / 'boundary-check')])
        if focused:
            for trait in ['Send', 'Sync', 'Unpin']:
                negative = artifacts / ('not-' + trait + '.rs')
                negative.write_text(generated.read_text() + f'\nfn require<T: {trait}>() {{}} fn main() {{ require::<_IO_marker>(); }}\n')
                run('reject-' + trait, ['rustc', '+1.95.0', '--edition', '2024', str(negative), '-o', str(artifacts / ('not-' + trait))], True)
                if 'E0277' not in (artifacts / ('reject-' + trait + '.log')).read_text():
                    raise RuntimeError('negative auto trait check failed for an unrelated reason')
            negative = artifacts / 'construct.rs'
            negative.write_text('mod ffi { ' + body + ' }\nfn main() { let _ = ffi::_IO_marker {}; }\n')
            run('reject-construction', ['rustc', '+1.95.0', '--edition', '2024', str(negative), '-o', str(artifacts / 'construct')], True)
            if 'private fields' not in (artifacts / 'reject-construction.log').read_text():
                raise RuntimeError('construction failed for an unrelated reason')
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
