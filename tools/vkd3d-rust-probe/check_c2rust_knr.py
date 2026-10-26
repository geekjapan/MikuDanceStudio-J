"""Run the patched C2Rust K&R method with AST shims, without building LLVM."""
import argparse
from pathlib import Path
import subprocess


HARNESS = r'''
#![allow(dead_code)]
use std::ops::Index;
#[derive(Clone, Copy, Debug, PartialEq)]
struct CTypeId(usize);
#[derive(Clone, Copy, Debug)]
struct CDeclId(usize);
type CParamId = CDeclId;
#[derive(Clone, Copy, Debug, PartialEq)]
struct CQualTypeId { ctype: CTypeId }
#[derive(Clone, Copy, Debug, PartialEq)]
enum CCallingConvention { C, Win64, SysV64 }
#[derive(Debug)]
enum CTypeKind {
    Function(CQualTypeId, Vec<CQualTypeId>, bool, bool, bool, CCallingConvention),
    Attributed(CQualTypeId, Option<()>),
    Elaborated(CTypeId), Decayed(CTypeId), Paren(CTypeId), TypeOf(CTypeId),
    Typedef(CDeclId), Other,
}
struct CType { kind: CTypeKind }
enum CDeclKind { Variable { typ: CQualTypeId }, Typedef { typ: CQualTypeId } }
struct CDecl { kind: CDeclKind }
struct TypedAstContext { types: Vec<CType>, decls: Vec<CDecl> }
impl Index<CTypeId> for TypedAstContext {
    type Output = CType;
    fn index(&self, id: CTypeId) -> &CType { &self.types[id.0] }
}
impl Index<CDeclId> for TypedAstContext {
    type Output = CDecl;
    fn index(&self, id: CDeclId) -> &CDecl { &self.decls[id.0] }
}
impl TypedAstContext {
    fn get_decl(&self, id: &CDeclId) -> Option<&CDecl> { self.decls.get(id.0) }
}
#[derive(Clone, Debug, PartialEq)]
struct Type { ret: Option<CQualTypeId>, params: Vec<CQualTypeId>, variadic: bool, abi: CCallingConvention }
type TranslationResult<T> = Result<T, ()>;
struct TypeConverter;
impl TypeConverter {
    fn convert_function(&mut self, _: &TypedAstContext, ret: Option<CQualTypeId>,
        params: &[CQualTypeId], variadic: bool, abi: CCallingConvention) -> TranslationResult<Box<Type>> {
        Ok(Box::new(Type { ret, params: params.to_vec(), variadic, abi }))
    }
    // The real pinned source method is inserted here.
    METHOD
}

#[test]
fn attributed_function_signatures_preserve_abi_and_parameters() {
    for abi in [CCallingConvention::C, CCallingConvention::Win64, CCallingConvention::SysV64] {
        for prototype in [false, true] {
            for noreturn in [false, true] {
                for variadic in [false, true] {
                    let ret = CQualTypeId { ctype: CTypeId(99) };
                    let params: Vec<_> = (0..8).map(|i| CQualTypeId { ctype: CTypeId(100 + i % 2) }).collect();
                    let mut ctxt = TypedAstContext {
                        types: vec![CType { kind: CTypeKind::Function(ret, vec![], variadic, noreturn, prototype, abi) }],
                        decls: params.iter().map(|&typ| CDecl { kind: CDeclKind::Variable { typ } }).collect(),
                    };
                    let ids: Vec<_> = (0..8).map(CDeclId).collect();
                    let expected = if prototype { None } else {
                        Some(Box::new(Type { ret: if noreturn { None } else { Some(ret) }, params, variadic, abi }))
                    };
                    let mut converter = TypeConverter;
                    assert_eq!(converter.knr_function_type_with_parameters(&ctxt, CTypeId(0), &ids), Ok(expected.clone()));
                    for wrapper in 0..8 {
                        let inner = CTypeId(ctxt.types.len() - 1);
                        let qual = CQualTypeId { ctype: inner };
                        let kind = match wrapper {
                            0 | 7 => CTypeKind::Attributed(qual, None),
                            1 => CTypeKind::Attributed(qual, Some(())),
                            2 => CTypeKind::Paren(inner),
                            3 => CTypeKind::Elaborated(inner),
                            4 => CTypeKind::Decayed(inner),
                            5 => CTypeKind::TypeOf(inner),
                            _ => {
                                let id = CDeclId(ctxt.decls.len());
                                ctxt.decls.push(CDecl { kind: CDeclKind::Typedef { typ: qual } });
                                CTypeKind::Typedef(id)
                            }
                        };
                        ctxt.types.push(CType { kind });
                        assert_eq!(converter.knr_function_type_with_parameters(&ctxt, CTypeId(ctxt.types.len() - 1), &ids), Ok(expected.clone()));
                    }
                }
            }
        }
    }
}
'''


def check(source, artifacts):
    text = (source / 'c2rust-transpile/src/convert_type.rs').read_text()
    start = text.index('pub fn knr_function_type_with_parameters(')
    body = text.index('{', start)
    depth = 1
    end = body + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    artifacts.mkdir(parents=True, exist_ok=True)
    harness = artifacts / 'knr.rs'
    harness.write_text(HARNESS.replace('METHOD', text[start:end]))
    executable = artifacts / 'knr-test'
    subprocess.run(['rustc', '+1.95.0', '--edition', '2021', '--test', str(harness),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable), '--nocapture'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    check(args.source.resolve(), args.artifacts.resolve())
