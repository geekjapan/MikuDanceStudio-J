//! `LoadAccessoryObject` after the D3DX call, and the defaults of the accessory record.

use crate::mesh::{self, AttributeRange, Vertex, XMesh};
use crate::Error;
use mds_formats::text::Sjis;
use mds_math::Vec3;

/// `D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1`, the vertex format the renderer draws.
pub const FVF_274: u32 = 274;

/// `AccessoryRecord::textureTypes`. The numbers are the C++ values.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum TextureKind {
    Plain = 0,
    /// `.sph` as the only texture: sphere map, modulate.
    SphereMultiply = 1,
    /// `.spa` as the only texture: sphere map, add.
    SphereAdd = 2,
    /// `screen.bmp`: the captured screen, no file.
    Screen = 3,
    /// `name*map.sph`: main texture and a sphere map, modulate.
    SubMultiply = 4,
    /// `name*map.spa`: main texture and a sphere map, add.
    SubAdd = 5,
}

/// `texturePaths[i]` and `textureTypes[i]`. A name is a path relative to the
/// accessory's directory; empty means none.
#[derive(Clone, Debug, PartialEq)]
pub struct TextureSlot {
    pub kind: TextureKind,
    pub primary: Sjis,
    pub sphere: Sjis,
}

impl TextureSlot {
    /// `strchr(texture, '*')` splits main texture from sphere map; `strstr` finds
    /// `.sph` and `.spa` (case-sensitive, anywhere in the name).
    pub fn parse(texture: Option<&[u8]>) -> TextureSlot {
        let none = || Sjis::from_raw(Vec::new());
        let Some(name) = texture.filter(|t| !t.is_empty()) else {
            return TextureSlot {
                kind: TextureKind::Plain,
                primary: none(),
                sphere: none(),
            };
        };
        let has = |s: &[u8], pat: &[u8]| s.windows(pat.len()).any(|w| w == pat);
        if let Some(star) = name.iter().position(|&b| b == b'*') {
            let (first, sphere) = (&name[..star], &name[star + 1..]);
            let kind = if has(sphere, b".sph") {
                TextureKind::SubMultiply
            } else if has(sphere, b".spa") {
                TextureKind::SubAdd
            } else {
                TextureKind::Plain
            };
            return TextureSlot {
                kind,
                primary: Sjis::from_raw(first.to_vec()),
                sphere: Sjis::from_raw(sphere.to_vec()),
            };
        }
        let kind = if has(name, b"screen.bmp") {
            TextureKind::Screen
        } else if has(name, b".sph") {
            TextureKind::SphereMultiply
        } else if has(name, b".spa") {
            TextureKind::SphereAdd
        } else {
            TextureKind::Plain
        };
        // `screen.bmp` is never loaded as a file, so no name is kept.
        let primary = if kind == TextureKind::Screen {
            none()
        } else {
            Sjis::from_raw(name.to_vec())
        };
        TextureSlot {
            kind,
            primary,
            sphere: none(),
        }
    }
}

/// A `D3DMATERIAL9` after `LoadAccessoryObject` changed it.
#[derive(Clone, Debug, PartialEq)]
pub struct AccessoryMaterial {
    pub diffuse: [f32; 4],
    pub ambient: [f32; 4],
    pub specular: [f32; 4],
    pub emissive: [f32; 4],
    pub power: f32,
    pub texture: TextureSlot,
}

/// The editable fields of `AccessoryRecord`, with the values `InitAccessoryRecord`
/// and `LoadAccessoryFile` give a new accessory.
#[derive(Clone, Debug, PartialEq)]
pub struct AccessoryState {
    pub visible: bool,
    pub position: [f32; 3],
    /// Radians, as the record and the PMM store it.
    pub rotation: [f32; 3],
    pub scale: f32,
    /// Slot of the model the accessory follows, or `-1`.
    pub parent_model: i32,
    pub parent_bone: i32,
    pub shadow_enabled: bool,
    pub additive_blend: bool,
    pub opacity: f32,
}

impl Default for AccessoryState {
    fn default() -> Self {
        AccessoryState {
            visible: true,
            position: [0.0; 3],
            rotation: [0.0; 3],
            scale: 1.0,
            parent_model: -1,
            parent_bone: 0,
            shadow_enabled: false,
            additive_blend: false,
            opacity: 1.0,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Accessory {
    /// The vertex format is always [`FVF_274`].
    pub vertices: Vec<Vertex>,
    /// Three indices per face, into `vertices`.
    pub indices: Vec<u32>,
    /// The material of each face, grouped by material within one source mesh.
    pub face_material: Vec<u32>,
    /// The mesh's attribute table, which `DrawSubset` follows; `CloneMeshFVF` keeps it.
    pub attribute_table: Vec<AttributeRange>,
    pub materials: Vec<AccessoryMaterial>,
    /// The loaded mesh lacked normals or texture coordinates (or had vertex colors),
    /// so `D3DXComputeNormals` replaced every normal.
    pub normals_computed: bool,
    pub state: AccessoryState,
}

impl Accessory {
    /// Faces drawn by `DrawSubset(material)`, as face numbers.
    pub fn subset_faces(&self, material: usize) -> impl Iterator<Item = usize> + '_ {
        self.face_material
            .iter()
            .enumerate()
            .filter(move |(_, m)| **m as usize == material)
            .map(|(i, _)| i)
    }
}

/// `LoadAccessoryObject` on the bytes of a `.x` file.
pub fn load_x(data: &[u8]) -> Result<Accessory, Error> {
    from_mesh(mesh::load(data)?)
}

pub(crate) fn from_mesh(x: XMesh) -> Result<Accessory, Error> {
    let materials = x
        .materials
        .iter()
        .map(|m| {
            // `material->Ambient = Diffuse`, then 0.1 on the RGB of Diffuse and Specular.
            let tenth = |c: [f32; 4]| [c[0] * 0.1, c[1] * 0.1, c[2] * 0.1, c[3]];
            AccessoryMaterial {
                ambient: m.diffuse,
                diffuse: tenth(m.diffuse),
                specular: tenth(m.specular),
                emissive: m.emissive,
                power: m.power,
                texture: TextureSlot::parse(m.texture.as_deref()),
            }
        })
        .collect();
    let normals_computed = !(x.has_normals && x.has_texcoords && !x.has_colors);
    let mut vertices = x.vertices;
    if normals_computed {
        compute_normals(&mut vertices, &x.indices);
    }
    Ok(Accessory {
        vertices,
        indices: x.indices,
        face_material: x.face_material,
        attribute_table: x.attribute_table,
        materials,
        normals_computed,
        state: AccessoryState::default(),
    })
}

/// `D3DXComputeNormals(mesh, NULL)`: no adjacency, so vertices at one position are
/// not welded. Each face adds its unit normal to its three vertices, weighted by
/// the face's angle at that vertex (the `D3DXTANGENT_WEIGHT_BY_ANGLE` default): the
/// `acos`, in `f64`, of the dot product of the two unit edges. Every unit vector is
/// `D3DXVec3Normalize`. The Windows dump fixes this order of operations.
pub fn compute_normals(vertices: &mut [Vertex], indices: &[u32]) {
    let mut sum = vec![[0.0f32; 3]; vertices.len()];
    let sub = |a: [f32; 3], b: [f32; 3]| [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    let dot = |a: [f32; 3], b: [f32; 3]| (a[0] * b[0] + a[1] * b[1]) + a[2] * b[2];
    let unit = |a: [f32; 3]| Vec3(a).normalize().0;
    let angle = |a: [f32; 3], b: [f32; 3]| {
        // Rounding can push the dot product of two unit edges past 1 (`degenerate_face.x`).
        libm::acos(f64::from(dot(unit(a), unit(b)).clamp(-1.0, 1.0))) as f32
    };
    for f in indices.chunks_exact(3) {
        let [i0, i1, i2] = [f[0] as usize, f[1] as usize, f[2] as usize];
        let [v0, v1, v2] = [
            vertices[i0].position,
            vertices[i1].position,
            vertices[i2].position,
        ];
        let (a, b) = (sub(v0, v1), sub(v0, v2));
        let cross = [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ];
        let w = [
            angle(a, b),
            angle(sub(v1, v0), sub(v1, v2)),
            angle(sub(v2, v0), sub(v2, v1)),
        ];
        let n = Vec3(cross).normalize().0;
        for (i, w) in [i0, i1, i2].into_iter().zip(w) {
            for k in 0..3 {
                sum[i][k] += n[k] * w;
            }
        }
    }
    for (v, s) in vertices.iter_mut().zip(sum) {
        v.normal = Vec3(s).normalize().0;
    }
}
