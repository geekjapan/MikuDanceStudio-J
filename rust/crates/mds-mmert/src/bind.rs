//! Parameter values: the semantic binding of `MmeBindSemanticParameters` (`material_bind.cpp`,
//! `ClassifySemantic` and its switch), the material colors of `MmeBindMaterialParameter`, the
//! name-table booleans of `MmeBindBooleanParameter`, and the constant-register layout the
//! values take in a shader.
//!
//! Values are kept per parameter as D3DX holds them: numbers in declaration order, a matrix
//! as its rows. [`registers`] lays them out as vkd3d packs them: HLSL's default
//! `column_major` gives one register per matrix column, `row_major` one per row.

use mds_math::Mat4;
use mds_mme::fx::{Data, Desc, Item, CLASS_MATRIX_COLUMNS, CLASS_MATRIX_ROWS};

use crate::model::Material;

pub type Mat = [f32; 16];

pub const IDENTITY: Mat = Mat4::IDENTITY.0;

pub fn mul(a: &Mat, b: &Mat) -> Mat {
    Mat4::multiply(&Mat4(*a), &Mat4(*b)).0
}

fn inverse(m: &Mat) -> Mat {
    Mat4(*m).inverse().map_or(*m, |(i, _)| i.0)
}

fn transpose(m: &Mat) -> Mat {
    std::array::from_fn(|i| m[(i % 4) * 4 + i / 4])
}

fn normalize(v: [f32; 3]) -> [f32; 3] {
    let l = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
    if l > 0.0 {
        v.map(|c| c / l)
    } else {
        v
    }
}

fn cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn dot(a: [f32; 3], b: [f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

/// `D3DXMatrixLookAtLH`.
pub fn look_at_lh(eye: [f32; 3], at: [f32; 3], up: [f32; 3]) -> Mat {
    let z = normalize([at[0] - eye[0], at[1] - eye[1], at[2] - eye[2]]);
    let x = normalize(cross(up, z));
    let y = cross(z, x);
    [
        x[0],
        y[0],
        z[0],
        0.0,
        x[1],
        y[1],
        z[1],
        0.0,
        x[2],
        y[2],
        z[2],
        0.0,
        -dot(x, eye),
        -dot(y, eye),
        -dot(z, eye),
        1.0,
    ]
}

/// `D3DXMatrixPerspectiveFovLH`.
pub fn perspective_lh(fov_y: f32, aspect: f32, near: f32, far: f32) -> Mat {
    let h = 1.0 / (fov_y / 2.0).tan();
    let q = far / (far - near);
    [
        h / aspect,
        0.0,
        0.0,
        0.0,
        0.0,
        h,
        0.0,
        0.0,
        0.0,
        0.0,
        q,
        1.0,
        0.0,
        0.0,
        -near * q,
        0.0,
    ]
}

/// `D3DXMatrixOrthoLH`.
pub fn ortho_lh(w: f32, h: f32, near: f32, far: f32) -> Mat {
    let q = 1.0 / (far - near);
    [
        2.0 / w,
        0.0,
        0.0,
        0.0,
        0.0,
        2.0 / h,
        0.0,
        0.0,
        0.0,
        0.0,
        q,
        0.0,
        0.0,
        0.0,
        -near * q,
        1.0,
    ]
}

/// What one frame binds: the camera and light families, the light colors, the clocks.
#[derive(Clone, Debug)]
pub struct Scene {
    pub world: Mat,
    pub view: Mat,
    pub projection: Mat,
    pub light_view: Mat,
    pub light_projection: Mat,
    /// The direction the light travels.
    pub light_direction: [f32; 3],
    pub light_diffuse: [f32; 3],
    pub light_ambient: [f32; 3],
    pub light_specular: [f32; 3],
    pub time: f32,
    pub elapsed: f32,
    /// `GetCurrentFrameTime`: the raw frame clock in seconds, which drives animated textures.
    pub frame_time: f32,
    /// The BeginScene viewport, which `VIEWPORTPIXELSIZE` reports.
    pub viewport: (u32, u32),
    /// The host clear color (ARGB), the start value of `ClearSetColor`.
    pub background: u32,
}

impl Scene {
    /// MikuMikuDance's start-up view: the camera 45 units in front of (0, 10, 0) with a 30 degree
    /// view angle, and the default light (-0.5, -1, 0.5) at 154/255.
    pub fn default_view(width: u32, height: u32) -> Scene {
        let light_direction = [-0.5, -1.0, 0.5];
        let target = [0.0, 10.0, 0.0];
        let ld = normalize(light_direction);
        let light_eye = [0, 1, 2].map(|i| target[i] - ld[i] * 100.0);
        Scene {
            world: IDENTITY,
            view: look_at_lh([0.0, 10.0, -45.0], target, [0.0, 1.0, 0.0]),
            projection: perspective_lh(
                30f32.to_radians(),
                width as f32 / height as f32,
                1.0,
                10000.0,
            ),
            light_view: look_at_lh(light_eye, target, [0.0, 0.0, 1.0]),
            light_projection: ortho_lh(80.0, 80.0, 1.0, 400.0),
            light_direction,
            light_diffuse: [154.0 / 255.0; 3],
            light_ambient: [154.0 / 255.0; 3],
            light_specular: [154.0 / 255.0; 3],
            time: 0.0,
            elapsed: 0.0,
            frame_time: 0.0,
            viewport: (width, height),
            background: 0xFFFF_FFFF,
        }
    }
}

/// Draw type of the snapshot: 2 an effect draw of an object, 3 the ground shadow, 4 the edge.
pub const DRAW_OBJECT: u8 = 2;
pub const DRAW_SHADOW: u8 = 3;
pub const DRAW_EDGE: u8 = 4;

/// The `D3DMATERIAL9` a model material record holds: diffuse, ambient = diffuse (the record's
/// mirror copy), specular, emissive = the PMX ambient, power (`ModelMaterialRecord`).
fn material9(m: &Material) -> [[f32; 4]; 4] {
    [
        m.diffuse,
        m.diffuse,
        [m.specular[0], m.specular[1], m.specular[2], 0.0],
        [m.ambient[0], m.ambient[1], m.ambient[2], 0.0],
    ]
}

pub struct Draw<'a> {
    pub scene: &'a Scene,
    pub material: Option<&'a Material>,
    pub draw_type: u8,
}

fn set(values: &mut [f32], v: &[f32]) {
    for (d, s) in values.iter_mut().zip(v) {
        *d = *s;
    }
}

/// The value of a parameter in D3DX's float view.
pub fn initial(p: &Item) -> Vec<f32> {
    match &p.data {
        Data::Nums(n) => n.iter().map(|x| x.float()).collect(),
        _ => Vec::new(),
    }
}

fn ends_with_ci(s: &str, suffix: &str) -> bool {
    s.len() >= suffix.len() && s[s.len() - suffix.len()..].eq_ignore_ascii_case(suffix)
}

/// `ClassifySemantic` and the per-pass switch, for the numeric semantics.
pub fn bind_semantics(params: &[Item], values: &mut [Vec<f32>], d: &Draw) {
    let s = d.scene;
    for (p, vals) in params.iter().zip(values.iter_mut()) {
        if p.semantic.is_empty() || !p.desc.is_numeric() {
            continue;
        }
        let object = p
            .annotation("Object")
            .and_then(Item::get_string)
            .unwrap_or("");
        let light = object.eq_ignore_ascii_case("Light") || object.eq_ignore_ascii_case("Light0");
        let sem = p.semantic.as_str();
        let (base, invert, trans) = if ends_with_ci(sem, "INVERSETRANSPOSE") {
            (&sem[..sem.len() - 16], true, true)
        } else if ends_with_ci(sem, "TRANSPOSE") {
            (&sem[..sem.len() - 9], false, true)
        } else if ends_with_ci(sem, "INVERSE") {
            (&sem[..sem.len() - 7], true, false)
        } else {
            (sem, false, false)
        };
        let (view, proj) = if light {
            (s.light_view, s.light_projection)
        } else {
            (s.view, s.projection)
        };
        let matrix = match base.to_ascii_uppercase().as_str() {
            "WORLD" => Some(s.world),
            "VIEW" => Some(view),
            "PROJECTION" => Some(proj),
            "WORLDVIEW" => Some(mul(&s.world, &view)),
            "VIEWPROJECTION" => Some(mul(&view, &proj)),
            "WORLDVIEWPROJECTION" => Some(mul(&s.world, &mul(&view, &proj))),
            _ => None,
        };
        if let Some(m) = matrix {
            let m = if invert { inverse(&m) } else { m };
            set(vals, &if trans { transpose(&m) } else { m });
            continue;
        }
        let upper = sem.to_ascii_uppercase();
        let lit = |c: [f32; 3]| [c[0], c[1], c[2], 1.0];
        let v: Option<[f32; 4]> = match upper.as_str() {
            "POSITION" | "DIRECTION" if light => {
                let t = s.light_direction;
                Some(if upper == "POSITION" {
                    [-t[0], -t[1], -t[2], 0.0]
                } else {
                    let n = normalize(t);
                    [n[0], n[1], n[2], 0.0]
                })
            }
            "POSITION" | "DIRECTION" => {
                let inv = inverse(&s.view);
                Some(if upper == "POSITION" {
                    [inv[12], inv[13], inv[14], 1.0]
                } else {
                    let n = normalize([inv[8], inv[9], inv[10]]);
                    [n[0], n[1], n[2], 0.0]
                })
            }
            "DIFFUSE" if light => Some(lit(s.light_diffuse)),
            "AMBIENT" if light => Some(lit(s.light_ambient)),
            "SPECULAR" if light => Some(lit(s.light_specular)),
            "DIFFUSE" | "AMBIENT" | "SPECULAR" | "EMISSIVE" | "SPECULARPOWER" | "TOONCOLOR"
            | "EDGECOLOR" | "GROUNDSHADOWCOLOR" => material_value(&upper, d),
            "TIME" | "TIME2" => Some([s.time; 4]),
            "ELAPSEDTIME" | "ELAPSEDTIME2" => Some([s.elapsed; 4]),
            "VIEWPORTPIXELSIZE" => Some([s.viewport.0 as f32, s.viewport.1 as f32, 0.0, 0.0]),
            "MOUSEPOSITION" | "LEFTMOUSEDOWN" | "RIGHTMOUSEDOWN" | "MIDDLEMOUSEDOWN" => {
                Some([0.0; 4])
            }
            "ADDINGTEXTURE" | "ADDINGSPHERETEXTURE" => Some([0.0; 4]),
            "MULTIPLYINGTEXTURE" | "MULTIPLYINGSPHERETEXTURE" => Some([1.0; 4]),
            _ => None,
        };
        if let Some(v) = v {
            set(vals, &v);
        }
    }
    bind_names(params, values, d);
}

/// `MmeBindMaterialParameter` for an effect draw (`effect_file_used`) of a PMX model.
fn material_value(semantic: &str, d: &Draw) -> Option<[f32; 4]> {
    let m9 = d.material.map(material9);
    let power = d.material.map_or(0.0, |m| m.power);
    match semantic {
        "TOONCOLOR" => Some([1.0; 4]),
        "EDGECOLOR" => {
            (d.draw_type == DRAW_EDGE).then(|| d.material.map_or([0.0; 4], |m| m.edge_color))
        }
        "GROUNDSHADOWCOLOR" => (d.draw_type == DRAW_SHADOW).then(|| {
            let a = m9.map_or([0.0; 4], |m| m[1]);
            let l = d.scene.light_ambient;
            [a[0] * l[0], a[1] * l[1], a[2] * l[2], 0.65]
        }),
        "SPECULARPOWER" => {
            let p = if power == 0.0 { 0.1 } else { power };
            Some([p; 4])
        }
        _ if d.draw_type == DRAW_EDGE => Some(match semantic {
            "DIFFUSE" | "AMBIENT" => [0.0, 0.0, 0.0, 1.0],
            _ => [0.0; 4],
        }),
        _ => {
            let m = m9.unwrap_or_default();
            Some(match semantic {
                "DIFFUSE" => m[0],
                "AMBIENT" => m[1],
                "SPECULAR" => m[2],
                _ => m[3],
            })
        }
    }
}

/// The name-table parameters (`kNameTable`) the standard MMD effects read.
fn bind_names(params: &[Item], values: &mut [Vec<f32>], d: &Draw) {
    let s = d.scene;
    let m = d.material;
    for (p, vals) in params.iter().zip(values.iter_mut()) {
        if !p.semantic.is_empty() {
            continue;
        }
        let b = |x: bool| [f32::from(u8::from(x)); 4];
        let v: Option<[f32; 4]> = match p.name.to_ascii_lowercase().as_str() {
            "matworld" => {
                set(vals, &s.world);
                None
            }
            "matworldviewproj" => {
                set(vals, &mul(&s.world, &mul(&s.view, &s.projection)));
                None
            }
            "matlightviewproj" => {
                set(
                    vals,
                    &mul(&s.world, &mul(&s.light_view, &s.light_projection)),
                );
                None
            }
            "lightdir" => {
                let n = normalize(s.light_direction);
                Some([n[0], n[1], n[2], 0.0])
            }
            "use_texture" => Some(b(m.is_some_and(|m| m.has_texture))),
            "use_spheremap" => Some(b(m.is_some_and(|m| m.sphere_mode > 0))),
            "use_subtexture" => Some(b(m.is_some_and(|m| m.sphere_mode == 3))),
            "use_toon" => Some(b(m.is_some_and(|m| m.toon))),
            "spadd" => Some(b(m.is_some_and(|m| m.sphere_mode == 2))),
            "transp" | "parthf" | "opadd" => Some(b(false)),
            "egcolor" => m.map(|m| m.edge_color),
            "difcolor" => m.map(|m| m.diffuse),
            "spccolor" => m.map(|m| [m.specular[0], m.specular[1], m.specular[2], 1.0]),
            "tooncolor" => Some([1.0; 4]),
            _ => None,
        };
        if let Some(v) = v {
            set(vals, &v);
        }
    }
}

/// Registers one element of `desc` takes and the components of each, in the packing of the
/// global (`row_major` or the HLSL default `column_major`).
fn element_shape(desc: &Desc, row_major: bool) -> (usize, usize) {
    let (r, c) = (desc.rows as usize, desc.columns as usize);
    if desc.class == CLASS_MATRIX_ROWS || desc.class == CLASS_MATRIX_COLUMNS {
        if row_major {
            (r, c)
        } else {
            (c, r)
        }
    } else {
        (1, r * c)
    }
}

/// Writes `count` registers of the parameter into `rows` (vec4 per register).
pub fn registers(desc: &Desc, row_major: bool, values: &[f32], count: usize) -> Vec<[f32; 4]> {
    let (regs, comps) = element_shape(desc, row_major);
    let is_matrix = desc.class == CLASS_MATRIX_ROWS || desc.class == CLASS_MATRIX_COLUMNS;
    let per = (desc.rows * desc.columns) as usize;
    let mut out = Vec::new();
    for e in 0..desc.elements.max(1) as usize {
        let el = values.get(e * per..).unwrap_or(&[]);
        for r in 0..regs {
            let mut v = [0.0; 4];
            for (k, slot) in v.iter_mut().enumerate().take(comps) {
                let idx = if !is_matrix {
                    k
                } else if row_major {
                    r * desc.columns as usize + k
                } else {
                    k * desc.columns as usize + r
                };
                *slot = el.get(idx).copied().unwrap_or(0.0);
            }
            out.push(v);
            if out.len() == count {
                return out;
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matrices_pack_by_column_unless_row_major() {
        let desc = Desc {
            class: CLASS_MATRIX_ROWS,
            ty: 3,
            rows: 4,
            columns: 4,
            elements: 0,
        };
        let m: Vec<f32> = (0..16).map(|i| i as f32).collect();
        let cols = registers(&desc, false, &m, 4);
        assert_eq!(cols[1], [1.0, 5.0, 9.0, 13.0]);
        let rows = registers(&desc, true, &m, 2);
        assert_eq!(rows, [[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0]]);
        let v = Desc {
            class: 1,
            ty: 3,
            rows: 1,
            columns: 2,
            elements: 2,
        };
        assert_eq!(
            registers(&v, false, &[1.0, 2.0, 3.0, 4.0], 2)[1],
            [3.0, 4.0, 0.0, 0.0]
        );
        let t = transpose(&m.clone().try_into().unwrap());
        assert_eq!(t[1], 4.0);
        let p = mul(
            &IDENTITY,
            &look_at_lh([0.0, 0.0, -1.0], [0.0; 3], [0.0, 1.0, 0.0]),
        );
        assert_eq!(p[14], 1.0);
    }
}
