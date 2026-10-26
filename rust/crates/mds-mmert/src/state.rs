//! Pass render states and `sampler_state` blocks, read from the effect's syntax tree, as wgpu
//! pipeline and sampler descriptions.
//!
//! The pass states start from what MikuMikuDance sets before an effect draw (depth test and
//! write on, `LESSEQUAL`, counter-clockwise culling, `SRCALPHA`/`INVSRCALPHA` blending), because
//! `ID3DXEffect::Begin(.., 0)` restores the device state after every pass. Read: `ZEnable`,
//! `ZWriteEnable`, `ZFunc`, `CullMode`, `AlphaBlendEnable`, `SrcBlend`, `DestBlend`,
//! `BlendOp`, `SeparateAlphaBlendEnable`, `SrcBlendAlpha`, `DestBlendAlpha`, `BlendOpAlpha`,
//! `ColorWriteEnable`. Not modelled: alpha test, stencil, fill mode, depth bias, point sprites,
//! and the fixed-function states.

use mds_fx::ast::{StateAssignment, StateValue, Value};

/// A state value as a D3D enum number or a boolean.
fn number(v: &StateValue) -> Option<u32> {
    let StateValue::Value(v) = v else {
        return None;
    };
    Some(match v {
        Value::Int(i) => *i as u32,
        Value::Bool(b) => u32::from(*b),
        Value::Float(f) => *f as u32,
        Value::Ident(s) | Value::Expr(s) => {
            let s = s.to_ascii_uppercase();
            let s = s
                .strip_prefix("D3DBLEND_")
                .or_else(|| s.strip_prefix("D3DCMP_"))
                .or_else(|| s.strip_prefix("D3DCULL_"))
                .or_else(|| s.strip_prefix("D3DBLENDOP_"))
                .or_else(|| s.strip_prefix("D3DTEXF_"))
                .or_else(|| s.strip_prefix("D3DTADDRESS_"))
                .unwrap_or(&s)
                .to_string();
            match s.as_str() {
                "TRUE" => 1,
                "FALSE" => 0,
                _ => return s.parse().ok(),
            }
        }
        _ => return None,
    })
}

fn ident(v: &StateValue) -> Option<String> {
    match v {
        StateValue::Value(Value::Ident(s)) => Some(s.to_ascii_uppercase()),
        _ => None,
    }
}

fn blend_factor(v: &StateValue) -> Option<wgpu::BlendFactor> {
    use wgpu::BlendFactor as F;
    let n = match ident(v).as_deref() {
        Some("ZERO") => 1,
        Some("ONE") => 2,
        Some("SRCCOLOR") => 3,
        Some("INVSRCCOLOR") => 4,
        Some("SRCALPHA") => 5,
        Some("INVSRCALPHA") => 6,
        Some("DESTALPHA") => 7,
        Some("INVDESTALPHA") => 8,
        Some("DESTCOLOR") => 9,
        Some("INVDESTCOLOR") => 10,
        Some("SRCALPHASAT") => 11,
        Some("BLENDFACTOR") => 14,
        Some("INVBLENDFACTOR") => 15,
        _ => number(v)?,
    };
    Some(match n {
        1 => F::Zero,
        2 => F::One,
        3 => F::Src,
        4 => F::OneMinusSrc,
        5 | 12 => F::SrcAlpha,
        6 | 13 => F::OneMinusSrcAlpha,
        7 => F::DstAlpha,
        8 => F::OneMinusDstAlpha,
        9 => F::Dst,
        10 => F::OneMinusDst,
        11 => F::SrcAlphaSaturated,
        14 => F::Constant,
        15 => F::OneMinusConstant,
        _ => return None,
    })
}

fn blend_op(v: &StateValue) -> Option<wgpu::BlendOperation> {
    use wgpu::BlendOperation as O;
    let n = match ident(v).as_deref() {
        Some("ADD") => 1,
        Some("SUBTRACT") => 2,
        Some("REVSUBTRACT") => 3,
        Some("MIN") => 4,
        Some("MAX") => 5,
        _ => number(v)?,
    };
    Some(match n {
        1 => O::Add,
        2 => O::Subtract,
        3 => O::ReverseSubtract,
        4 => O::Min,
        5 => O::Max,
        _ => return None,
    })
}

fn compare(v: &StateValue) -> Option<wgpu::CompareFunction> {
    use wgpu::CompareFunction as C;
    let n = match ident(v).as_deref() {
        Some("NEVER") => 1,
        Some("LESS") => 2,
        Some("EQUAL") => 3,
        Some("LESSEQUAL") => 4,
        Some("GREATER") => 5,
        Some("NOTEQUAL") => 6,
        Some("GREATEREQUAL") => 7,
        Some("ALWAYS") => 8,
        _ => number(v)?,
    };
    Some(match n {
        1 => C::Never,
        2 => C::Less,
        3 => C::Equal,
        4 => C::LessEqual,
        5 => C::Greater,
        6 => C::NotEqual,
        7 => C::GreaterEqual,
        8 => C::Always,
        _ => return None,
    })
}

/// The render states of one pass that the pipeline carries.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct PassStates {
    pub z_enable: bool,
    pub z_write: bool,
    /// `None` keeps the host's: `LESSEQUAL`, or `LESS` in the edge pass.
    pub z_func: Option<wgpu::CompareFunction>,
    /// D3DCULL: 1 none, 2 clockwise, 3 counter-clockwise. `None` keeps the host's: CCW, or CW
    /// in the edge pass.
    pub cull: Option<u32>,
    pub blend: Option<wgpu::BlendState>,
    pub write_mask: [wgpu::ColorWrites; 4],
}

impl PassStates {
    pub fn read(states: &[StateAssignment]) -> PassStates {
        let mut s = PassStates {
            z_enable: true,
            z_write: true,
            z_func: None,
            cull: None,
            blend: None,
            write_mask: [wgpu::ColorWrites::ALL; 4],
        };
        let mut blend_on = true;
        let mut separate = false;
        let mut color = wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::SrcAlpha,
            dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
            operation: wgpu::BlendOperation::Add,
        };
        let mut alpha = color;
        for st in states {
            let v = &st.value;
            match st.name.to_ascii_lowercase().as_str() {
                "zenable" => s.z_enable = number(v).is_none_or(|n| n != 0),
                "zwriteenable" => s.z_write = number(v).is_none_or(|n| n != 0),
                "zfunc" => s.z_func = compare(v).or(s.z_func),
                "cullmode" => {
                    s.cull = Some(match ident(v).as_deref() {
                        Some("NONE") => 1,
                        Some("CW") => 2,
                        Some("CCW") => 3,
                        _ => number(v).unwrap_or(3),
                    })
                }
                "alphablendenable" => blend_on = number(v).is_none_or(|n| n != 0),
                "separatealphablendenable" => separate = number(v).is_some_and(|n| n != 0),
                "srcblend" => color.src_factor = blend_factor(v).unwrap_or(color.src_factor),
                "destblend" => color.dst_factor = blend_factor(v).unwrap_or(color.dst_factor),
                "blendop" => color.operation = blend_op(v).unwrap_or(color.operation),
                "srcblendalpha" => alpha.src_factor = blend_factor(v).unwrap_or(alpha.src_factor),
                "destblendalpha" => alpha.dst_factor = blend_factor(v).unwrap_or(alpha.dst_factor),
                "blendopalpha" => alpha.operation = blend_op(v).unwrap_or(alpha.operation),
                name if name.starts_with("colorwriteenable") => {
                    let slot = name["colorwriteenable".len()..]
                        .parse::<usize>()
                        .unwrap_or(st.index.unwrap_or(0) as usize);
                    if let (Some(m), true) = (number(v), slot < 4) {
                        s.write_mask[slot] = wgpu::ColorWrites::from_bits_truncate(m & 0xF);
                    }
                }
                _ => {}
            }
        }
        if blend_on {
            s.blend = Some(wgpu::BlendState {
                color,
                alpha: if separate { alpha } else { color },
            });
        }
        s
    }
}

fn address(v: &StateValue) -> Option<wgpu::AddressMode> {
    use wgpu::AddressMode as A;
    let n = match ident(v).as_deref() {
        Some("WRAP") => 1,
        Some("MIRROR") => 2,
        Some("CLAMP") => 3,
        Some("BORDER") => 4,
        Some("MIRRORONCE") => 5,
        _ => number(v)?,
    };
    Some(match n {
        1 => A::Repeat,
        2 | 5 => A::MirrorRepeat,
        3 => A::ClampToEdge,
        4 => A::ClampToBorder,
        _ => return None,
    })
}

/// D3DTEXF: 0 none, 1 point, 2 linear, 3 anisotropic, others linear.
fn filter(v: &StateValue) -> Option<u32> {
    match ident(v).as_deref() {
        Some("NONE") => Some(0),
        Some("POINT") => Some(1),
        Some("LINEAR") => Some(2),
        Some("ANISOTROPIC") => Some(3),
        Some("PYRAMIDALQUAD" | "GAUSSIANQUAD") => Some(2),
        _ => number(v),
    }
}

/// The texture a `sampler_state` names and its sampler. D3D9 defaults: point filtering, no
/// mip filter, wrap addressing.
pub fn sampler(
    states: &[StateAssignment],
    border: bool,
    comparison: bool,
) -> (Option<String>, wgpu::SamplerDescriptor<'static>) {
    let mut texture = None;
    let (mut min, mut mag, mut mip) = (1, 1, 0);
    let mut addr = [wgpu::AddressMode::Repeat; 3];
    let mut aniso = 1u16;
    for st in states {
        let v = &st.value;
        match st.name.to_ascii_lowercase().as_str() {
            "texture" => {
                texture = match v {
                    StateValue::Texture(t) => Some(t.clone()),
                    StateValue::Value(Value::Ident(t)) => Some(t.clone()),
                    _ => texture,
                }
            }
            "minfilter" => min = filter(v).unwrap_or(min),
            "magfilter" => mag = filter(v).unwrap_or(mag),
            "mipfilter" => mip = filter(v).unwrap_or(mip),
            "addressu" => addr[0] = address(v).unwrap_or(addr[0]),
            "addressv" => addr[1] = address(v).unwrap_or(addr[1]),
            "addressw" => addr[2] = address(v).unwrap_or(addr[2]),
            "maxanisotropy" => aniso = number(v).map_or(1, |n| n.clamp(1, 16) as u16),
            _ => {}
        }
    }
    let f = |n: u32| {
        if n >= 2 {
            wgpu::FilterMode::Linear
        } else {
            wgpu::FilterMode::Nearest
        }
    };
    let mip_filter = if mip >= 2 {
        wgpu::MipmapFilterMode::Linear
    } else {
        wgpu::MipmapFilterMode::Nearest
    };
    for a in &mut addr {
        if *a == wgpu::AddressMode::ClampToBorder && !border {
            *a = wgpu::AddressMode::ClampToEdge;
        }
    }
    let all_linear = min >= 2 && mag >= 2 && mip >= 2;
    let desc = wgpu::SamplerDescriptor {
        label: None,
        address_mode_u: addr[0],
        address_mode_v: addr[1],
        address_mode_w: addr[2],
        mag_filter: f(mag),
        min_filter: f(min),
        mipmap_filter: mip_filter,
        lod_min_clamp: 0.0,
        // D3DTEXF_NONE as the mip filter samples level 0 only.
        lod_max_clamp: if mip == 0 { 0.0 } else { 32.0 },
        compare: comparison.then_some(wgpu::CompareFunction::LessEqual),
        anisotropy_clamp: if all_linear && (min == 3 || mag == 3) {
            aniso
        } else {
            1
        },
        border_color: (addr.contains(&wgpu::AddressMode::ClampToBorder))
            .then_some(wgpu::SamplerBorderColor::TransparentBlack),
    };
    (texture, desc)
}
