//! Parameter reflection: the constant register of each effect parameter.
//!
//! The first source is the `CTAB` block of a d3dbc compile of the same source, profile, and
//! entry point ([`Source::Ctab`]). vkd3d-shader builds that table before it writes the
//! instructions, and drops it when the d3dbc writer fails. That happens for 36 corpus shaders,
//! whose temporaries exceed the shader model 3 limit of 32 (`E9015`) although their SPIR-V
//! compiles. For those, [`Source::Probe`] rebuilds the table:
//!
//! 1. Compile the source to SPIR-V once more, with every uniform given an explicit
//!    `register(cN)` or `register(sN)` at a distinct, high base. A reservation changes only
//!    where vkd3d places a variable, not the code it generates, so the constant buffer rows
//!    and sampler registers the probe reads give each variable's `bind_count`: how many
//!    registers vkd3d needs for it.
//! 2. Replay vkd3d's allocator (`allocate_const_registers` and `allocate_objects` in
//!    `hlsl_codegen.c` of vkd3d-shader 2.1) on those counts: sort the uniforms by
//!    `bind_count`, largest first and stable, then give each the first free range around the
//!    reservations the source itself makes. Samplers follow in the same way.
//!
//! [`verify_probe`] runs the probe on shaders whose `CTAB` exists; `mds-shader corpus
//! --reflect-verify` checks that both agree on every such shader.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use mds_fx::ast::{EffectAst, RegisterClass};
use mds_fx::lex::{self, Kind};
use rspirv::dr::{self, Operand};
use rspirv::spirv::{Op, StorageClass};

use crate::ctab::{self, Constant, RegisterSet};
use crate::spirv_fix;
use crate::vkd3d::{Target, Vkd3d};

/// Where a reflection came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    /// The `CTAB` block of a d3dbc compile of the same source and profile.
    Ctab,
    /// A SPIR-V compile with probe reservations and a replay of vkd3d's allocator.
    Probe,
}

impl Source {
    pub fn as_str(self) -> &'static str {
        match self {
            Source::Ctab => "ctab",
            Source::Probe => "probe",
        }
    }
}

pub struct Reflection {
    pub source: Source,
    /// Sorted by name, as vkd3d writes the `CTAB`.
    pub constants: Vec<Constant>,
}

/// Reflects the parameters of `entry_point` in `source`, the vkd3d input built from `ast`.
pub fn reflect(
    vk: &Vkd3d,
    ast: &EffectAst,
    source: &str,
    name: &str,
    profile: &str,
    entry_point: &str,
) -> Result<Reflection, String> {
    match vk.compile_hlsl(source, name, profile, entry_point, Target::D3dBytecode) {
        Ok(d3dbc) => {
            let mut constants = ctab::parse(&d3dbc)?;
            constants.sort();
            Ok(Reflection {
                source: Source::Ctab,
                constants,
            })
        }
        // Only the d3dbc writer's register limit is a known gap; other errors are real.
        Err(e) if e.summary().starts_with("E9015:") => Ok(Reflection {
            source: Source::Probe,
            constants: probe(vk, ast, source, name, profile, entry_point)?,
        }),
        Err(e) => Err(e.summary()),
    }
}

/// Runs the probe even when a `CTAB` exists, for checking it.
pub fn verify_probe(
    vk: &Vkd3d,
    ast: &EffectAst,
    source: &str,
    name: &str,
    profile: &str,
    entry_point: &str,
) -> Result<Vec<Constant>, String> {
    probe(vk, ast, source, name, profile, entry_point)
}

/// Checks `constants` against the SPIR-V the shader ships with: every constant row and
/// sampler register the module reads lies in exactly one parameter, and every parameter has
/// a register the module reads.
pub fn check_coverage(spirv: &[u32], constants: &[Constant]) -> Result<(), String> {
    let (rows, samplers) = usage(spirv)?;
    let mut errs = Vec::new();
    let reads = |set: RegisterSet| -> Vec<u32> {
        let s = if set == RegisterSet::Sampler {
            &samplers
        } else {
            &rows
        };
        s.iter().map(|r| r & !DYNAMIC).collect()
    };
    for set in [RegisterSet::Float4, RegisterSet::Sampler] {
        for r in reads(set) {
            let n = constants
                .iter()
                .filter(|c| {
                    c.set == set && (c.index as u32..(c.index + c.count) as u32).contains(&r)
                })
                .count();
            if n != 1 {
                errs.push(format!(
                    "{}{r} is read and lies in {n} parameters",
                    set.prefix()
                ));
            }
        }
    }
    for c in constants {
        let range = c.index as u32..(c.index + c.count) as u32;
        if !reads(c.set).iter().any(|r| range.contains(r)) {
            errs.push(format!("{c} is not read"));
        }
    }
    if errs.is_empty() {
        Ok(())
    } else {
        Err(errs.join("; "))
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Class {
    Numeric,
    Sampler,
}

/// A uniform global and where the probe put it.
struct Var {
    name: String,
    class: Class,
    /// An upper bound of the registers it can take, used to space the probe bases.
    span: u32,
    /// `register(xN)` written in the source.
    reserved: Option<u32>,
    base: u32,
    bind_count: u32,
}

fn class_of(ty: &str) -> Option<Class> {
    let last = ty.rsplit(' ').next().unwrap_or(ty);
    let l = last.to_ascii_lowercase();
    if l.starts_with("sampler") {
        Some(Class::Sampler)
    } else if l.starts_with("texture") || l == "string" || l == "void" {
        None
    } else {
        Some(Class::Numeric)
    }
}

/// Registers one element of a numeric type can take: a matrix takes up to its larger
/// dimension, anything else not known (a struct) gets a wide bound.
fn element_span(ty: &str) -> u32 {
    let last = ty.rsplit(' ').next().unwrap_or(ty).to_ascii_lowercase();
    if last == "matrix" {
        return 4;
    }
    let digits: Vec<u32> = last
        .trim_start_matches(|c: char| c.is_ascii_alphabetic())
        .split('x')
        .filter_map(|d| d.parse().ok())
        .collect();
    let scalar = [
        "float",
        "half",
        "double",
        "int",
        "uint",
        "bool",
        "dword",
        "vector",
        "min16float",
        "min10float",
        "min16int",
        "min16uint",
    ]
    .iter()
    .any(|p| last.starts_with(p));
    match (scalar, digits.as_slice()) {
        (true, [r, c]) => (*r).max(*c),
        (true, _) => 1,
        (false, _) => 64,
    }
}

fn span_of(ty: &str, array: &[String]) -> u32 {
    let mut n = element_span(ty);
    for d in array {
        n = n.saturating_mul(d.trim().parse::<u32>().unwrap_or(1024));
    }
    n.max(1)
}

/// Finds each uniform's declarator in `source` and returns the edited probe source.
fn probe_source(ast: &EffectAst, source: &str, vars: &mut [Var]) -> Result<String, String> {
    let toks = lex::lex(source)
        .map_err(|e| format!("probe: cannot lex line {}: {}", e.line, e.message))?;
    let text = |i: usize| toks.get(i).map_or("", |t| t.text(source));
    // Brace and paren depth at each token; declarators sit at depth 0.
    let mut depth = Vec::with_capacity(toks.len());
    let mut d = 0i32;
    for t in &toks {
        let punct = |p: &[&str]| t.kind == Kind::Punct && p.contains(&t.text(source));
        if punct(&["}", ")", "]"]) {
            d -= 1;
        }
        depth.push(d);
        if punct(&["{", "(", "["]) {
            d += 1;
        }
    }
    let globals: Vec<_> = ast
        .globals
        .iter()
        .filter(|g| !g.modifiers.iter().any(|m| m == "static") && class_of(&g.ty).is_some())
        .collect();
    let mut claimed = BTreeSet::new();
    let mut inserts: Vec<(usize, String)> = Vec::new();
    let mut next_base = [1024u32, 64u32];
    for (g, v) in globals.iter().zip(vars.iter_mut()) {
        let start = toks.partition_point(|t| t.line < g.line);
        let at = (start..toks.len())
            .find(|&i| {
                depth[i] == 0
                    && toks[i].kind == Kind::Ident
                    && text(i) == g.name
                    && !claimed.contains(&i)
                    && matches!(text(i + 1), ":" | "[" | "=" | ";" | "," | "<")
            })
            .ok_or_else(|| format!("probe: cannot find the declaration of {}", g.name))?;
        claimed.insert(at);
        let mut j = at + 1;
        while text(j) == "[" {
            while j < toks.len() && !(text(j) == "]" && depth[j] == 0) {
                j += 1;
            }
            j += 1;
        }
        let insert_at = toks.get(j - 1).map_or(source.len(), |t| t.end);
        let slot = if v.class == Class::Numeric { 0 } else { 1 };
        v.base = match v.reserved {
            Some(r) => r,
            None => {
                let b = next_base[slot];
                next_base[slot] = b + v.span + 1;
                let letter = if v.class == Class::Numeric { 'c' } else { 's' };
                inserts.push((insert_at, format!(" : register({letter}{b})")));
                b
            }
        };
    }
    let mut out = String::with_capacity(source.len() + inserts.len() * 24);
    let mut pos = 0;
    for (at, s) in inserts {
        out.push_str(&source[pos..at]);
        out.push_str(&s);
        pos = at;
    }
    out.push_str(&source[pos..]);
    Ok(out)
}

/// The constant-buffer rows and sampler registers a vkd3d SPIR-V module reads.
fn usage(words: &[u32]) -> Result<(BTreeSet<u32>, BTreeSet<u32>), String> {
    let m = dr::load_words(words).map_err(|e| format!("probe: cannot read SPIR-V: {e}"))?;
    let mut consts: HashMap<u32, u32> = HashMap::new();
    let mut uniform_vars = BTreeSet::new();
    for i in &m.types_global_values {
        match (i.class.opcode, i.result_id, i.operands.first()) {
            (Op::Constant, Some(id), Some(Operand::LiteralBit32(v))) => {
                consts.insert(id, *v);
            }
            (Op::Variable, Some(id), Some(Operand::StorageClass(StorageClass::Uniform))) => {
                uniform_vars.insert(id);
            }
            _ => {}
        }
    }
    let mut samplers = BTreeSet::new();
    for n in &m.debug_names {
        if let (Some(Operand::IdRef(_)), Some(Operand::LiteralString(s))) =
            (n.operands.first(), n.operands.get(1))
        {
            if let Some(idx) = s.strip_prefix('s').and_then(|d| d.parse::<u32>().ok()) {
                samplers.insert(idx);
            }
        }
    }
    // Values defined in functions, for following an index back to its constant part.
    let mut defs: HashMap<u32, &dr::Instruction> = HashMap::new();
    for f in &m.functions {
        for b in &f.blocks {
            for i in &b.instructions {
                if let Some(id) = i.result_id {
                    defs.insert(id, i);
                }
            }
        }
    }
    let mut rows = BTreeSet::new();
    for f in &m.functions {
        for b in &f.blocks {
            for i in &b.instructions {
                if i.class.opcode != Op::AccessChain {
                    continue;
                }
                let (Some(Operand::IdRef(base)), Some(Operand::IdRef(idx))) =
                    (i.operands.first(), i.operands.get(2))
                else {
                    continue;
                };
                if !uniform_vars.contains(base) {
                    continue;
                }
                let row = match consts.get(idx) {
                    Some(r) => *r,
                    None => {
                        // A relative address `c[a0.x + N]` is an add with a constant term.
                        let d = defs
                            .get(idx)
                            .ok_or("probe: an index is neither a constant nor computed")?;
                        let c = if d.class.opcode == Op::IAdd {
                            d.operands.iter().find_map(|o| match o {
                                Operand::IdRef(x) => consts.get(x).copied(),
                                _ => None,
                            })
                        } else {
                            None
                        };
                        c.ok_or_else(|| {
                            format!("probe: dynamic constant index from {:?}", d.class.opcode)
                        })? | DYNAMIC
                    }
                };
                rows.insert(row);
            }
        }
    }
    Ok((rows, samplers))
}

/// Marks a row read through a relative address.
const DYNAMIC: u32 = 1 << 31;

fn probe(
    vk: &Vkd3d,
    ast: &EffectAst,
    source: &str,
    name: &str,
    profile: &str,
    entry_point: &str,
) -> Result<Vec<Constant>, String> {
    let mut vars: Vec<Var> = ast
        .globals
        .iter()
        .filter(|g| !g.modifiers.iter().any(|m| m == "static"))
        .filter_map(|g| {
            class_of(&g.ty).map(|class| Var {
                name: g.name.clone(),
                class,
                reserved: g.register.and_then(|r| {
                    let want = match class {
                        Class::Numeric => RegisterClass::Float,
                        Class::Sampler => RegisterClass::Sampler,
                    };
                    (r.class == want).then_some(r.index)
                }),
                span: if class == Class::Numeric {
                    span_of(&g.ty, &g.array)
                } else {
                    span_of("int", &g.array)
                },
                base: 0,
                bind_count: 0,
            })
        })
        .collect();
    let src = probe_source(ast, source, &mut vars)?;
    let spv = vk
        .compile_hlsl(&src, name, profile, entry_point, Target::SpirvBinary)
        .map_err(|e| format!("probe compile: {}", e.summary()))?;
    let (rows, samplers) = usage(&spirv_fix::words(&spv)?)?;
    for v in &mut vars {
        let set = if v.class == Class::Numeric {
            &rows
        } else {
            &samplers
        };
        for &r in set {
            let (dynamic, r) = (r & DYNAMIC != 0, r & !DYNAMIC);
            if r >= v.base && r < v.base + v.span {
                // A relative read can reach every element.
                let n = if dynamic { v.span } else { r - v.base + 1 };
                v.bind_count = v.bind_count.max(n);
            }
        }
    }
    Ok(replay(&vars))
}

/// vkd3d-shader 2.1's allocation of numeric registers, then of sampler registers.
fn replay(vars: &[Var]) -> Vec<Constant> {
    let mut out = Vec::new();
    // `sort_uniforms_by_bind_count` for the numeric set reorders the whole list; the sampler
    // pass sorts that order again by sampler counts.
    let mut order: Vec<usize> = (0..vars.len()).collect();
    let numeric_count = |i: usize| {
        if vars[i].class == Class::Numeric {
            vars[i].bind_count
        } else {
            0
        }
    };
    let sampler_count = |i: usize| {
        if vars[i].class == Class::Sampler {
            vars[i].bind_count
        } else {
            0
        }
    };
    order.sort_by_key(|&i| std::cmp::Reverse(numeric_count(i)));
    for (class, set) in [
        (Class::Numeric, RegisterSet::Float4),
        (Class::Sampler, RegisterSet::Sampler),
    ] {
        if class == Class::Sampler {
            order.sort_by_key(|&i| std::cmp::Reverse(sampler_count(i)));
        }
        let mut used: BTreeMap<u32, ()> = BTreeMap::new();
        for &i in &order {
            let v = &vars[i];
            if v.class == class {
                if let Some(r) = v.reserved {
                    // A source reservation holds the whole variable for numerics, the used part
                    // for samplers.
                    let n = if class == Class::Numeric {
                        v.span
                    } else {
                        v.bind_count
                    };
                    for k in r..r + n {
                        used.insert(k, ());
                    }
                }
            }
        }
        for &i in &order {
            let v = &vars[i];
            if v.class != class || v.bind_count == 0 {
                continue;
            }
            let index = match v.reserved {
                Some(r) => r,
                None => {
                    let mut start = 0;
                    while (start..start + v.bind_count).any(|k| used.contains_key(&k)) {
                        start += 1;
                    }
                    for k in start..start + v.bind_count {
                        used.insert(k, ());
                    }
                    start
                }
            };
            out.push(Constant {
                name: v.name.clone(),
                set,
                index: index as u16,
                count: v.bind_count as u16,
            });
        }
    }
    out.sort();
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn var(name: &str, class: Class, bind_count: u32, reserved: Option<u32>) -> Var {
        Var {
            name: name.into(),
            class,
            span: 4,
            reserved,
            base: 0,
            bind_count,
        }
    }

    #[test]
    fn replay_sorts_by_count_and_fills_around_reservations() {
        let vars = [
            var("a", Class::Numeric, 1, None),
            var("m", Class::Numeric, 4, None),
            var("r", Class::Numeric, 1, Some(5)),
            var("b", Class::Numeric, 1, None),
            var("unused", Class::Numeric, 0, None),
            var("s", Class::Sampler, 1, None),
            var("t", Class::Sampler, 1, Some(0)),
        ];
        let got: Vec<String> = replay(&vars).iter().map(|c| c.to_string()).collect();
        // m takes c0-c3 first; r holds c5-c8 (its whole span); a and b fill c4 and c9.
        assert_eq!(got, ["a=c4", "b=c9", "m=c0+4", "r=c5", "s=s1", "t=s0"]);
    }

    #[test]
    fn spans() {
        assert_eq!(span_of("float4x3", &[]), 4);
        assert_eq!(span_of("float3", &["8".into()]), 8);
        assert_eq!(span_of("bool", &[]), 1);
        assert_eq!(span_of("MyStruct", &[]), 64);
        assert_eq!(class_of("uniform sampler2D"), Some(Class::Sampler));
        assert_eq!(class_of("texture2D"), None);
    }
}
