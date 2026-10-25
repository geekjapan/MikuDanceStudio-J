//! One shader of a pass, compiled through `mds-shader` and rewritten for one wgpu pipeline.
//!
//! vkd3d-shader names its resources by D3D register (`cb0_0`, `s3`, `t3`) and puts every one
//! in group 0, and it numbers SM 3.0 varyings by output and input register, which D3D9 links
//! by semantic instead. This module reads the semantics from [`Vkd3d::scan_hlsl`] on the source
//! of the same compile (`TEXCOORD1` at `o2`) and rewrites the naga module:
//!
//! - group 0 holds the vertex shader's resources and group 1 the pixel shader's; constant
//!   buffer `cbN` binds at N, sampler `sN` at `4 + 2N`, texture `tN` at `5 + 2N`;
//! - SM 3.0 vertex outputs and pixel inputs move to the location of their semantic
//!   ([`varying_location`]); SM 2.x keeps vkd3d's fixed `oTn`/`tn` numbering, which already
//!   matches.
//!
//! The module is read from vkd3d's SPIR-V without naga's Y flip: vkd3d keeps D3D clip space,
//! which is also wgpu's.
//!
//! The constant registers of each parameter come from [`mds_shader::reflect`].

use std::collections::BTreeMap;

use mds_fx::{Effect, Entry};
use mds_shader::ctab::Constant;
use mds_shader::vkd3d::{self, Scan, Vkd3d};
use mds_shader::Options;
use naga::{Binding, Handle, ScalarKind, Type, TypeInner};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Stage {
    Vertex,
    Fragment,
}

impl Stage {
    pub fn group(self) -> u32 {
        match self {
            Stage::Vertex => 0,
            Stage::Fragment => 1,
        }
    }
}

/// One resource the shader binds, in its group.
#[derive(Clone, Debug, PartialEq)]
pub enum Slot {
    /// Constant buffer `cbN` (N 0 float, 1 int, 2 bool registers) of `rows` vec4s.
    Uniform {
        cb: u32,
        rows: u32,
    },
    Sampler {
        reg: u32,
        comparison: bool,
    },
    Texture {
        reg: u32,
        dim: wgpu::TextureViewDimension,
        kind: ScalarKind,
    },
}

impl Slot {
    pub fn binding(&self) -> u32 {
        match self {
            Slot::Uniform { cb, .. } => *cb,
            Slot::Sampler { reg, .. } => 4 + 2 * reg,
            Slot::Texture { reg, .. } => 5 + 2 * reg,
        }
    }
}

/// A `@location` of an entry point: location, scalar kind, components.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Loc {
    pub location: u32,
    pub kind: ScalarKind,
    pub components: u32,
}

pub struct Shader {
    pub stage: Stage,
    pub wgsl: String,
    pub entry: String,
    pub constants: Vec<Constant>,
    pub slots: Vec<Slot>,
    /// Entry inputs after the rewrite (vertex attributes or varyings).
    pub inputs: Vec<Loc>,
    pub outputs: Vec<Loc>,
    pub writes_depth: bool,
    /// The semantic of each vertex-shader input location: usage and index.
    pub input_semantics: BTreeMap<u32, (String, u32)>,
}

/// The location a varying with this D3D usage and index takes in both stages.
pub fn varying_location(usage: &str, index: u32) -> Option<u32> {
    match usage {
        "texcoord" if index < 10 => Some(index),
        "color" if index < 2 => Some(10 + index),
        "normal" if index == 0 => Some(12),
        "tangent" if index == 0 => Some(13),
        "binormal" if index == 0 => Some(14),
        "fog" | "position" | "blendweight" | "blendindices" | "psize" | "depth" if index < 4 => {
            Some(15)
        }
        _ => None,
    }
}

/// The semantic of each register the rewrite looks up, from [`Vkd3d::scan_hlsl`]: register
/// letter and number to usage and index. Vertex inputs (`v`) always; for SM 3.0 also vertex
/// outputs (`o`) and pixel inputs (`v`). The sm3 `VPOS` and `VFACE` pixel inputs are not
/// varyings and stay out.
fn scan_semantics(scan: &Scan, profile: &str) -> BTreeMap<(char, u32), (String, u32)> {
    let vs = profile.starts_with("vs_");
    let sm3 = profile.get(3..4) == Some("3");
    let mut map = BTreeMap::new();
    for (letter, list) in [('v', &scan.inputs), ('o', &scan.outputs)] {
        if !((vs && letter == 'v') || (sm3 && (vs == (letter == 'o')))) {
            continue;
        }
        for e in list {
            if !vs && [vkd3d::SV_POSITION, vkd3d::SV_IS_FRONT_FACE].contains(&e.sysval) {
                continue;
            }
            let name = e.semantic.to_ascii_lowercase();
            let name = name.strip_prefix("sv_").unwrap_or(&name).to_string();
            map.insert((letter, e.register), (name, e.index));
        }
    }
    map
}

fn numeric(module: &naga::Module, ty: Handle<Type>) -> Option<(ScalarKind, u32)> {
    match module.types[ty].inner {
        TypeInner::Scalar(s) => Some((s.kind, 1)),
        TypeInner::Vector { size, scalar } => Some((scalar.kind, size as u32)),
        _ => None,
    }
}

/// Rewrites the `@location`s of one argument or result with `map` (old location to new, or
/// `None` to keep it) and collects them. A struct gets a new type with the moved bindings.
fn relocate(
    module: &mut naga::Module,
    ty: Handle<Type>,
    binding: &mut Option<Binding>,
    map: &dyn Fn(u32) -> Result<Option<u32>, String>,
    out: &mut Vec<Loc>,
    depth: &mut bool,
) -> Result<Option<Handle<Type>>, String> {
    match binding {
        Some(Binding::Location { location, .. }) => {
            if let Some(n) = map(*location)? {
                *location = n;
            }
            let (kind, components) =
                numeric(module, ty).ok_or("a location is not a scalar or vector")?;
            out.push(Loc {
                location: *location,
                kind,
                components,
            });
            Ok(None)
        }
        Some(Binding::BuiltIn(naga::BuiltIn::FragDepth)) => {
            *depth = true;
            Ok(None)
        }
        Some(_) => Ok(None),
        None => {
            let t = module.types[ty].clone();
            let TypeInner::Struct { mut members, span } = t.inner else {
                return Ok(None);
            };
            for m in &mut members {
                let mut b = m.binding.clone();
                relocate(module, m.ty, &mut b, map, out, depth)?;
                m.binding = b;
            }
            let new = module.types.insert(
                Type {
                    name: t.name.clone(),
                    inner: TypeInner::Struct { members, span },
                },
                Default::default(),
            );
            Ok((new != ty).then_some(new))
        }
    }
}

fn narrow_float(module: &naga::Module, ty: Handle<Type>) -> Option<u32> {
    match numeric(module, ty)? {
        (ScalarKind::Float, n) if n < 4 => Some(n),
        _ => None,
    }
}

/// `c` (a float scalar or vector of `n` components) as a vec4, filled with 0 and a final 1.
fn widened(
    f: &mut naga::Function,
    v4: Handle<Type>,
    c: Handle<naga::Expression>,
    n: u32,
    zero: Handle<naga::Expression>,
    one: Handle<naga::Expression>,
) -> Handle<naga::Expression> {
    let mut components = vec![c];
    components.extend(std::iter::repeat_n(zero, 3 - n as usize));
    components.push(one);
    f.expressions.append(
        naga::Expression::Compose { ty: v4, components },
        Default::default(),
    )
}

/// Makes every float varying a vec4: D3D9 links a `float2` output to a `float4` input, Metal
/// requires the types to match. Vertex outputs get `(x, y, 0, 1)` style fills; pixel inputs
/// read the components they declared.
fn widen_varyings(module: &mut naga::Module, epi: usize, stage: Stage) -> Result<(), String> {
    let v4 = module.types.insert(
        Type {
            name: None,
            inner: TypeInner::Vector {
                size: naga::VectorSize::Quad,
                scalar: naga::Scalar::F32,
            },
        },
        Default::default(),
    );
    match stage {
        Stage::Fragment => {
            let narrow: Vec<(usize, u32)> = module.entry_points[epi]
                .function
                .arguments
                .iter()
                .enumerate()
                .filter(|(_, a)| matches!(a.binding, Some(Binding::Location { .. })))
                .filter_map(|(i, a)| narrow_float(module, a.ty).map(|n| (i, n)))
                .collect();
            if narrow.is_empty() {
                return Ok(());
            }
            let f = &mut module.entry_points[epi].function;
            for &(i, _) in &narrow {
                f.arguments[i].ty = v4;
            }
            let arg_of: BTreeMap<Handle<naga::Expression>, u32> = f
                .expressions
                .iter()
                .filter_map(|(h, e)| match e {
                    naga::Expression::FunctionArgument(i) => narrow
                        .iter()
                        .find(|(a, _)| *a == *i as usize)
                        .map(|&(_, n)| (h, n)),
                    _ => None,
                })
                .collect();
            let body = std::mem::take(&mut f.body);
            let mut out = naga::Block::new();
            for (st, span) in body.span_into_iter() {
                match st {
                    naga::Statement::Store { pointer, value } if arg_of.contains_key(&value) => {
                        let n = arg_of[&value];
                        let e = if n == 1 {
                            naga::Expression::AccessIndex {
                                base: value,
                                index: 0,
                            }
                        } else {
                            use naga::SwizzleComponent as C;
                            naga::Expression::Swizzle {
                                size: if n == 2 {
                                    naga::VectorSize::Bi
                                } else {
                                    naga::VectorSize::Tri
                                },
                                vector: value,
                                pattern: [C::X, C::Y, C::Z, C::W],
                            }
                        };
                        let h = f.expressions.append(e, span);
                        out.push(
                            naga::Statement::Emit(naga::Range::new_from_bounds(h, h)),
                            span,
                        );
                        out.push(naga::Statement::Store { pointer, value: h }, span);
                    }
                    st => out.push(st, span),
                }
            }
            f.body = out;
        }
        Stage::Vertex => {
            let Some(result) = &module.entry_points[epi].function.result else {
                return Ok(());
            };
            let rty = result.ty;
            let TypeInner::Struct { members, .. } = module.types[rty].inner.clone() else {
                return Ok(());
            };
            let narrow: Vec<Option<u32>> = members
                .iter()
                .map(|m| match m.binding {
                    Some(Binding::Location { .. }) => narrow_float(module, m.ty),
                    _ => None,
                })
                .collect();
            if narrow.iter().all(Option::is_none) {
                return Ok(());
            }
            let mut new_members = members.clone();
            for (m, n) in new_members.iter_mut().zip(&narrow) {
                if n.is_some() {
                    m.ty = v4;
                }
            }
            let mut layouter = naga::proc::Layouter::default();
            layouter
                .update(module.to_ctx())
                .map_err(|e| format!("layout: {e}"))?;
            let mut offset = 0;
            for m in &mut new_members {
                let l = layouter[m.ty];
                offset = l.alignment.round_up(offset);
                m.offset = offset;
                offset += l.size;
            }
            let align = new_members
                .iter()
                .map(|m| layouter[m.ty].alignment)
                .max()
                .unwrap_or(naga::proc::Alignment::ONE);
            let new_ty = module.types.insert(
                Type {
                    name: module.types[rty].name.clone(),
                    inner: TypeInner::Struct {
                        members: new_members,
                        span: align.round_up(offset),
                    },
                },
                Default::default(),
            );
            let f = &mut module.entry_points[epi].function;
            f.result.as_mut().unwrap().ty = new_ty;
            let body = std::mem::take(&mut f.body);
            let mut out = naga::Block::new();
            for (st, span) in body.span_into_iter() {
                let naga::Statement::Return { value: Some(v) } = st else {
                    out.push(st, span);
                    continue;
                };
                let naga::Expression::Compose { components, .. } = f.expressions[v].clone() else {
                    return Err("vertex result is not a composed struct".into());
                };
                let zero = f
                    .expressions
                    .append(naga::Expression::Literal(naga::Literal::F32(0.0)), span);
                let one = f
                    .expressions
                    .append(naga::Expression::Literal(naga::Literal::F32(1.0)), span);
                let mut first = None;
                let mut parts = Vec::new();
                for (c, n) in components.iter().zip(&narrow) {
                    parts.push(match n {
                        Some(n) => {
                            let h = widened(f, v4, *c, *n, zero, one);
                            first.get_or_insert(h);
                            h
                        }
                        None => *c,
                    });
                }
                let whole = f.expressions.append(
                    naga::Expression::Compose {
                        ty: new_ty,
                        components: parts,
                    },
                    span,
                );
                out.push(
                    naga::Statement::Emit(naga::Range::new_from_bounds(
                        first.unwrap_or(whole),
                        whole,
                    )),
                    span,
                );
                out.push(naga::Statement::Return { value: Some(whole) }, span);
            }
            f.body = out;
        }
    }
    Ok(())
}

/// The register a vkd3d resource name stands for: `cb0_0` is (`c`, 0), `s3` and `t3` are
/// (`s`, 3) and (`t`, 3).
fn register_of(name: &str) -> Option<(char, u32)> {
    if let Some(rest) = name.strip_prefix("cb") {
        let n: String = rest.chars().take_while(char::is_ascii_digit).collect();
        return n.parse().ok().map(|n| ('c', n));
    }
    let letter = name.chars().next()?;
    let n: String = name[1..].chars().take_while(char::is_ascii_digit).collect();
    matches!(letter, 's' | 't')
        .then(|| n.parse().ok().map(|n| (letter, n)))
        .flatten()
}

fn view_dim(dim: naga::ImageDimension, arrayed: bool) -> wgpu::TextureViewDimension {
    use naga::ImageDimension as D;
    use wgpu::TextureViewDimension as V;
    match (dim, arrayed) {
        (D::D1, _) => V::D1,
        (D::D2, false) => V::D2,
        (D::D2, true) => V::D2Array,
        (D::D3, _) => V::D3,
        (D::Cube, false) => V::Cube,
        (D::Cube, true) => V::CubeArray,
    }
}

/// Compiles `entry` of `fx` for `stage` and rewrites it as the module doc says.
pub fn compile(vk: &Vkd3d, fx: &Effect, entry: &Entry, stage: Stage) -> Result<Shader, String> {
    let name = format!("{}_{}", entry.profile, entry.function);
    // vkd3d writes D3D clip space, which wgpu shares; the default options flip Y like naga-cli.
    let compiled = mds_shader::compile_with(vk, fx, entry, &name, &Options { flip_y: false });
    if compiled.status != mds_shader::Status::Ok {
        return Err(compiled.error.unwrap_or_else(|| "no WGSL".into()));
    }
    let source = compiled.source;
    let ep = compiled.entry_point;
    let mut module = compiled.outputs.ok_or("no naga module")?.module;
    let scan = vk
        .scan_hlsl(&source, &name, &entry.profile, &ep)
        .map_err(|e| format!("scan: {}", e.summary()))?;
    let semantics = scan_semantics(&scan, &entry.profile);
    let reflection = mds_shader::reflect::reflect(vk, &fx.ast, &source, &name, &entry.profile, &ep)
        .map_err(|e| format!("reflect: {e}"))?;
    let sm3 = entry.profile.get(3..4) == Some("3");

    let mut slots = Vec::new();
    let handles: Vec<_> = module.global_variables.iter().map(|(h, _)| h).collect();
    for h in handles {
        let g = &module.global_variables[h];
        if g.binding.is_none() {
            continue;
        }
        let (letter, reg) = g
            .name
            .as_deref()
            .and_then(register_of)
            .ok_or_else(|| format!("resource {:?} has no register name", g.name))?;
        let slot = match (&module.types[g.ty].inner, letter) {
            (TypeInner::Struct { span, .. }, 'c') => Slot::Uniform {
                cb: reg,
                rows: span / 16,
            },
            (TypeInner::Sampler { comparison }, 's') => Slot::Sampler {
                reg,
                comparison: *comparison,
            },
            (
                TypeInner::Image {
                    dim,
                    arrayed,
                    class,
                },
                't',
            ) => Slot::Texture {
                reg,
                dim: view_dim(*dim, *arrayed),
                kind: match class {
                    naga::ImageClass::Sampled { kind, .. } => *kind,
                    _ => ScalarKind::Float,
                },
            },
            (t, _) => return Err(format!("unexpected resource {:?}: {t:?}", g.name)),
        };
        module.global_variables[h].binding = Some(naga::ResourceBinding {
            group: stage.group(),
            binding: slot.binding(),
        });
        slots.push(slot);
    }

    let naga_stage = match stage {
        Stage::Vertex => naga::ShaderStage::Vertex,
        Stage::Fragment => naga::ShaderStage::Fragment,
    };
    let epi = module
        .entry_points
        .iter()
        .position(|e| e.stage == naga_stage)
        .ok_or("no entry point for the stage")?;

    // Locations are register numbers in vkd3d's SPIR-V.
    let semantic = |letter: char, reg: u32| semantics.get(&(letter, reg)).cloned();
    let move_by_semantic = |letter: char| {
        move |reg: u32| -> Result<Option<u32>, String> {
            if !sm3 {
                return Ok(None);
            }
            let (usage, index) =
                semantic(letter, reg).ok_or_else(|| format!("no dcl for {letter}{reg}"))?;
            varying_location(&usage, index)
                .map(Some)
                .ok_or_else(|| format!("no varying location for {usage}{index}"))
        }
    };
    let keep = |_: u32| Ok(None);
    let in_map: Box<dyn Fn(u32) -> Result<Option<u32>, String>> = match stage {
        Stage::Vertex => Box::new(keep),
        Stage::Fragment => Box::new(move_by_semantic('v')),
    };
    let out_map: Box<dyn Fn(u32) -> Result<Option<u32>, String>> = match stage {
        Stage::Vertex => Box::new(move_by_semantic('o')),
        Stage::Fragment => Box::new(keep),
    };

    let mut inputs = Vec::new();
    let mut outputs = Vec::new();
    let mut writes_depth = false;
    let mut unused = false;
    let mut retyped = Vec::new();
    let mut args = std::mem::take(&mut module.entry_points[epi].function.arguments);
    for a in &mut args {
        if let Some(new) = relocate(
            &mut module,
            a.ty,
            &mut a.binding,
            &*in_map,
            &mut inputs,
            &mut unused,
        )? {
            retyped.push((a.ty, new));
            a.ty = new;
        }
    }
    module.entry_points[epi].function.arguments = args;
    if let Some(mut r) = module.entry_points[epi].function.result.take() {
        if let Some(new) = relocate(
            &mut module,
            r.ty,
            &mut r.binding,
            &*out_map,
            &mut outputs,
            &mut writes_depth,
        )? {
            retyped.push((r.ty, new));
            r.ty = new;
        }
        module.entry_points[epi].function.result = Some(r);
    }
    for (old, new) in retyped {
        for (_, e) in module.entry_points[epi].function.expressions.iter_mut() {
            if let naga::Expression::Compose { ty, .. } = e {
                if *ty == old {
                    *ty = new;
                }
            }
        }
    }
    for list in [&inputs, &outputs] {
        let mut seen = std::collections::BTreeSet::new();
        if let Some(l) = list.iter().find(|l| !seen.insert(l.location)) {
            return Err(format!("two varyings at location {}", l.location));
        }
    }

    widen_varyings(&mut module, epi, stage)?;
    if stage == Stage::Fragment {
        for l in &mut inputs {
            l.components = 4;
        }
    } else {
        for l in &mut outputs {
            l.components = 4;
        }
    }

    let input_semantics = match stage {
        Stage::Vertex => inputs
            .iter()
            .filter_map(|l| semantic('v', l.location).map(|s| (l.location, s)))
            .collect(),
        Stage::Fragment => BTreeMap::new(),
    };

    let info = naga::valid::Validator::new(
        naga::valid::ValidationFlags::all(),
        naga::valid::Capabilities::all() & naga::back::wgsl::supported_capabilities(),
    )
    .validate(&module)
    .map_err(|e| format!("rebound module: {}", e.emit_to_string("")))?;
    let wgsl =
        naga::back::wgsl::write_string(&module, &info, naga::back::wgsl::WriterFlags::empty())
            .map_err(|e| format!("rebound module wgsl-out: {e}"))?;
    Ok(Shader {
        stage,
        wgsl,
        entry: ep,
        constants: reflection.constants,
        slots,
        inputs,
        outputs,
        writes_depth,
        input_semantics,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn element(semantic: &str, index: u32, register: u32, sysval: u32) -> vkd3d::Element {
        vkd3d::Element {
            semantic: semantic.into(),
            index,
            register,
            sysval,
            mask: 0xf,
        }
    }

    #[test]
    fn semantics_of_an_sm3_scan() {
        let scan = Scan {
            inputs: vec![element("POSITION", 0, 0, 0), element("TEXCOORD", 1, 1, 0)],
            outputs: vec![element("SV_Position", 0, 0, vkd3d::SV_POSITION)],
            ..Scan::default()
        };
        let d = scan_semantics(&scan, "vs_3_0");
        assert_eq!(d[&('v', 1)], ("texcoord".to_string(), 1));
        assert_eq!(d[&('o', 0)], ("position".to_string(), 0));

        let ps = Scan {
            inputs: vec![
                element("TEXCOORD", 0, 0, 0),
                element("VPOS", 0, 0, vkd3d::SV_POSITION),
            ],
            ..Scan::default()
        };
        let d = scan_semantics(&ps, "ps_3_0");
        assert_eq!(d.len(), 1);
        assert_eq!(d[&('v', 0)], ("texcoord".to_string(), 0));
        assert!(scan_semantics(&ps, "ps_2_0").is_empty());

        assert_eq!(varying_location("texcoord", 1), Some(1));
        assert_eq!(varying_location("color", 1), Some(11));
        assert_eq!(register_of("cb0_0"), Some(('c', 0)));
        assert_eq!(register_of("t12"), Some(('t', 12)));
        assert_eq!(register_of("r0"), None);
    }
}
