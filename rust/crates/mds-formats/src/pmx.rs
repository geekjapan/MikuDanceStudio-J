//! PMX 2.0 and 2.1 models, in the layout `model_reader.cpp` and
//! `model_sections.cpp` on `next` read.
//!
//! Index fields are stored as `i32` and written back at the header's index
//! width. The C++ reader stops after the joints (or after the rigid bodies
//! when there are none) and ignores the rest, so the rest, including PMX 2.1
//! soft bodies, is kept in `trailing`.

use crate::io::{Reader, Result, Writer};
use crate::text::{PmxEncoding, PmxText};

const MAX_VERTICES: usize = 1_000_000;
const MAX_INDICES: usize = 3_000_000;
const MAX_RECORDS: usize = 100_000;
const MAX_OFFSETS: usize = 1_000_000;

#[derive(Clone, Debug)]
pub struct Pmx {
    /// 2.0 or 2.1, bits as read.
    pub version: f32,
    /// The 8 header globals: encoding, additional UVs, then the vertex,
    /// texture, material, bone, morph and rigid index widths.
    pub globals: [u8; 8],
    pub name: PmxText,
    pub name_en: PmxText,
    pub comment: PmxText,
    pub comment_en: PmxText,
    pub vertices: Vec<Vertex>,
    pub indices: Vec<i32>,
    pub textures: Vec<PmxText>,
    pub materials: Vec<Material>,
    pub bones: Vec<Bone>,
    pub morphs: Vec<Morph>,
    pub frames: Vec<DisplayFrame>,
    pub rigids: Vec<Rigid>,
    /// `None` when there are no rigid bodies: the C++ reader then stops.
    pub joints: Option<Vec<Joint>>,
    pub trailing: Vec<u8>,
}

#[derive(Clone, Debug, Default)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    /// One entry per additional UV in the header.
    pub extra_uv: Vec<[f32; 4]>,
    /// 0 BDEF1, 1 BDEF2, 2 BDEF4, 3 SDEF, 4 QDEF (2.1).
    pub weight_kind: u8,
    /// BDEF1 uses 1 bone, BDEF2 and SDEF 2, BDEF4 and QDEF 4.
    pub bones: [i32; 4],
    /// BDEF2 and SDEF use 1 weight, BDEF4 and QDEF 4.
    pub weights: [f32; 4],
    /// SDEF only: C, R0, R1.
    pub sdef: [[f32; 3]; 3],
    pub edge_scale: f32,
}

#[derive(Clone, Debug)]
pub struct Material {
    pub name: PmxText,
    pub name_en: PmxText,
    pub diffuse: [f32; 4],
    pub specular: [f32; 3],
    pub specular_power: f32,
    pub ambient: [f32; 3],
    pub flags: u8,
    pub edge_color: [f32; 4],
    pub edge_size: f32,
    pub texture: i32,
    pub sphere: i32,
    pub sphere_mode: u8,
    /// Not 0: `toon` is a shared toon number (one byte). 0: a texture index.
    pub shared_toon: u8,
    pub toon: i32,
    pub memo: PmxText,
    pub face_vertex_count: i32,
}

#[derive(Clone, Debug)]
pub struct Bone {
    pub name: PmxText,
    pub name_en: PmxText,
    pub position: [f32; 3],
    pub parent: i32,
    pub layer: i32,
    pub flags: u16,
    /// Flag 0x0001: tail bone index, otherwise `tail_offset`.
    pub tail_bone: i32,
    pub tail_offset: [f32; 3],
    /// Flags 0x0100 or 0x0200.
    pub inherit_parent: i32,
    pub inherit_ratio: f32,
    /// Flag 0x0400.
    pub fixed_axis: [f32; 3],
    /// Flag 0x0800: X axis, then Z axis.
    pub local_axes: [[f32; 3]; 2],
    /// Flag 0x2000.
    pub external_parent: i32,
    /// Flag 0x0020.
    pub ik: Ik,
}

#[derive(Clone, Debug, Default)]
pub struct Ik {
    pub target: i32,
    pub loops: i32,
    pub angle: f32,
    pub links: Vec<IkLink>,
}

#[derive(Clone, Debug, Default)]
pub struct IkLink {
    pub bone: i32,
    /// 1: `limits` follow (minimum, maximum).
    pub has_limits: u8,
    pub limits: [[f32; 3]; 2],
}

#[derive(Clone, Debug)]
pub struct Morph {
    pub name: PmxText,
    pub name_en: PmxText,
    pub panel: u8,
    pub kind: u8,
    pub offsets: Offsets,
}

/// Morph offsets by kind. Kinds above 10 are accepted only with no
/// offsets, as the C++ reader does for kinds above 8.
#[derive(Clone, Debug)]
pub enum Offsets {
    /// Kind 0 (group) and 9 (flip): morph index and weight.
    Group(Vec<(i32, f32)>),
    /// Kind 1: vertex index and position offset.
    Vertex(Vec<(i32, [f32; 3])>),
    /// Kind 2: bone index, translation, rotation.
    Bone(Vec<(i32, [f32; 3], [f32; 4])>),
    /// Kinds 3 to 7: vertex index and UV offset.
    Uv(Vec<(i32, [f32; 4])>),
    /// Kind 8.
    Material(Vec<MaterialOffset>),
    /// Kind 10: rigid index, local flag, velocity, torque.
    Impulse(Vec<(i32, u8, [f32; 3], [f32; 3])>),
    /// Any other kind, with no offsets.
    None,
}

#[derive(Clone, Debug)]
pub struct MaterialOffset {
    pub material: i32,
    pub operation: u8,
    /// Diffuse 4, specular 3, power 1, ambient 3, edge color 4, edge size 1,
    /// texture, sphere and toon factors 4 each.
    pub values: [f32; 28],
}

#[derive(Clone, Debug)]
pub struct DisplayFrame {
    pub name: PmxText,
    pub name_en: PmxText,
    pub special: u8,
    /// `(kind, index)`: kind 0 is a bone, any other kind a morph.
    pub entries: Vec<(u8, i32)>,
}

#[derive(Clone, Debug)]
pub struct Rigid {
    pub name: PmxText,
    pub name_en: PmxText,
    pub bone: i32,
    pub group: u8,
    pub mask: u16,
    pub shape: u8,
    pub size: [f32; 3],
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub mass: f32,
    pub linear_damping: f32,
    pub angular_damping: f32,
    pub restitution: f32,
    pub friction: f32,
    pub mode: u8,
}

#[derive(Clone, Debug)]
pub struct Joint {
    pub name: PmxText,
    pub name_en: PmxText,
    pub kind: u8,
    pub rigid_a: i32,
    pub rigid_b: i32,
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub translation_min: [f32; 3],
    pub translation_max: [f32; 3],
    pub rotation_min: [f32; 3],
    pub rotation_max: [f32; 3],
    pub spring_translation: [f32; 3],
    pub spring_rotation: [f32; 3],
}

/// Index widths and text encoding from the header.
#[derive(Clone, Copy)]
struct Sizes {
    enc: PmxEncoding,
    extra_uv: usize,
    vertex: u8,
    texture: u8,
    material: u8,
    bone: u8,
    morph: u8,
    rigid: u8,
    v21: bool,
}

impl Pmx {
    fn sizes(&self) -> Sizes {
        let g = self.globals;
        Sizes {
            enc: if g[0] == 1 {
                PmxEncoding::Utf8
            } else {
                PmxEncoding::Utf16Le
            },
            extra_uv: g[1].into(),
            vertex: g[2],
            texture: g[3],
            material: g[4],
            bone: g[5],
            morph: g[6],
            rigid: g[7],
            v21: self.version != 2.0,
        }
    }
}

/// A signed index of width 1, 2 or 4.
fn index(r: &mut Reader, size: u8) -> Result<i32> {
    Ok(match size {
        1 => (r.u8()? as i8).into(),
        2 => r.i16()?.into(),
        _ => r.i32()?,
    })
}
fn write_index(w: &mut Writer, size: u8, v: i32) {
    match size {
        1 => w.u8(v as i8 as u8),
        2 => w.i16(v as i16),
        _ => w.i32(v),
    }
}
/// A vertex index: unsigned at width 1 and 2.
fn vertex_index(r: &mut Reader, size: u8) -> Result<i32> {
    Ok(match size {
        1 => r.u8()?.into(),
        2 => r.u16()?.into(),
        _ => r.i32()?,
    })
}
fn write_vertex_index(w: &mut Writer, size: u8, v: i32) {
    match size {
        1 => w.u8(v as u8),
        2 => w.u16(v as u16),
        _ => w.i32(v),
    }
}

fn count(r: &mut Reader, limit: usize) -> Result<usize> {
    let n = r.u32()? as usize;
    r.limit(n, limit, "count over the C++ limit")
}

fn texts(r: &mut Reader, s: Sizes) -> Result<(PmxText, PmxText)> {
    Ok((PmxText::read(r, s.enc)?, PmxText::read(r, s.enc)?))
}

impl Pmx {
    pub fn read(data: &[u8]) -> Result<Self> {
        let r = &mut Reader::new(data);
        if r.bytes(4)? != b"PMX " {
            return Err(r.invalid("not a PMX file"));
        }
        let version = r.f32()?;
        if version != 2.0 && version != 2.1 {
            return Err(r.invalid("PMX version is not 2.0 or 2.1"));
        }
        if r.u8()? != 8 {
            return Err(r.invalid("PMX header does not have 8 globals"));
        }
        let globals = r.array::<8>()?;
        let width_ok = |w: u8| matches!(w, 1 | 2 | 4);
        if globals[0] > 1 || globals[1] > 4 || !globals[2..].iter().all(|&w| width_ok(w)) {
            return Err(r.invalid("bad PMX globals"));
        }
        let mut pmx = Pmx {
            version,
            globals,
            name: blank(),
            name_en: blank(),
            comment: blank(),
            comment_en: blank(),
            vertices: Vec::new(),
            indices: Vec::new(),
            textures: Vec::new(),
            materials: Vec::new(),
            bones: Vec::new(),
            morphs: Vec::new(),
            frames: Vec::new(),
            rigids: Vec::new(),
            joints: None,
            trailing: Vec::new(),
        };
        let s = pmx.sizes();
        (pmx.name, pmx.name_en) = texts(r, s)?;
        (pmx.comment, pmx.comment_en) = texts(r, s)?;
        let n = count(r, MAX_VERTICES)?;
        pmx.vertices = r.vec(n, 37 + 16 * s.extra_uv, |r| read_vertex(r, s))?;
        let n = count(r, MAX_INDICES)?;
        pmx.indices = r.vec(n, s.vertex.into(), |r| vertex_index(r, s.vertex))?;
        let n = count(r, MAX_RECORDS)?;
        pmx.textures = r.vec(n, 4, |r| PmxText::read(r, s.enc))?;
        let n = count(r, MAX_RECORDS)?;
        pmx.materials = r.vec(n, 86, |r| read_material(r, s))?;
        let n = count(r, MAX_RECORDS)?;
        pmx.bones = r.vec(n, 28, |r| read_bone(r, s))?;
        let n = count(r, MAX_RECORDS)?;
        let mut total = 0;
        pmx.morphs = r.vec(n, 14, |r| read_morph(r, s, &mut total))?;
        let n = count(r, MAX_RECORDS)?;
        let mut total = 0;
        pmx.frames = r.vec(n, 13, |r| {
            let (name, name_en) = texts(r, s)?;
            let special = r.u8()?;
            let n = usize::try_from(r.i32()?).map_err(|_| r.invalid("negative entry count"))?;
            total += n;
            r.limit(total, MAX_OFFSETS, "too many display entries")?;
            let entries = r.vec(n, 2, |r| {
                let kind = r.u8()?;
                Ok((kind, index(r, if kind != 0 { s.morph } else { s.bone })?))
            })?;
            Ok(DisplayFrame {
                name,
                name_en,
                special,
                entries,
            })
        })?;
        let n = count(r, MAX_RECORDS)?;
        pmx.rigids = r.vec(n, 70, |r| read_rigid(r, s))?;
        if !pmx.rigids.is_empty() {
            let n = count(r, MAX_RECORDS)?;
            pmx.joints = Some(r.vec(n, 107, |r| read_joint(r, s))?);
        }
        pmx.trailing = r.rest();
        Ok(pmx)
    }

    pub fn write(&self) -> Result<Vec<u8>> {
        let s = self.sizes();
        let w = &mut Writer::default();
        w.bytes(b"PMX ");
        w.f32(self.version);
        w.u8(8);
        w.bytes(&self.globals);
        for t in [&self.name, &self.name_en, &self.comment, &self.comment_en] {
            t.write(w)?;
        }
        w.count32(self.vertices.len())?;
        for v in &self.vertices {
            write_vertex(w, s, v)?;
        }
        w.count32(self.indices.len())?;
        for &i in &self.indices {
            write_vertex_index(w, s.vertex, i);
        }
        w.count32(self.textures.len())?;
        for t in &self.textures {
            t.write(w)?;
        }
        w.count32(self.materials.len())?;
        for m in &self.materials {
            write_material(w, s, m)?;
        }
        w.count32(self.bones.len())?;
        for b in &self.bones {
            write_bone(w, s, b)?;
        }
        w.count32(self.morphs.len())?;
        for m in &self.morphs {
            write_morph(w, s, m)?;
        }
        w.count32(self.frames.len())?;
        for f in &self.frames {
            f.name.write(w)?;
            f.name_en.write(w)?;
            w.u8(f.special);
            w.count32(f.entries.len())?;
            for &(kind, i) in &f.entries {
                w.u8(kind);
                write_index(w, if kind != 0 { s.morph } else { s.bone }, i);
            }
        }
        w.count32(self.rigids.len())?;
        for b in &self.rigids {
            b.name.write(w)?;
            b.name_en.write(w)?;
            write_index(w, s.bone, b.bone);
            w.u8(b.group);
            w.u16(b.mask);
            w.u8(b.shape);
            w.f32s(&b.size);
            w.f32s(&b.position);
            w.f32s(&b.rotation);
            w.f32s(&[
                b.mass,
                b.linear_damping,
                b.angular_damping,
                b.restitution,
                b.friction,
            ]);
            w.u8(b.mode);
        }
        if let Some(joints) = &self.joints {
            w.count32(joints.len())?;
            for j in joints {
                j.name.write(w)?;
                j.name_en.write(w)?;
                w.u8(j.kind);
                write_index(w, s.rigid, j.rigid_a);
                write_index(w, s.rigid, j.rigid_b);
                for v in [
                    &j.position,
                    &j.rotation,
                    &j.translation_min,
                    &j.translation_max,
                    &j.rotation_min,
                    &j.rotation_max,
                    &j.spring_translation,
                    &j.spring_rotation,
                ] {
                    w.f32s(v);
                }
            }
        }
        w.bytes(&self.trailing);
        Ok(std::mem::take(&mut w.out))
    }
}

fn blank() -> PmxText {
    PmxText {
        raw: Vec::new(),
        text: String::new(),
    }
}

/// Bones and weights used by a weight kind.
fn weight_shape(kind: u8, v21: bool) -> Option<(usize, usize)> {
    match kind {
        0 => Some((1, 0)),
        1 | 3 => Some((2, 1)),
        2 => Some((4, 4)),
        4 if v21 => Some((4, 4)),
        _ => None,
    }
}

fn read_vertex(r: &mut Reader, s: Sizes) -> Result<Vertex> {
    let mut v = Vertex {
        position: r.f32s()?,
        normal: r.f32s()?,
        uv: r.f32s()?,
        extra_uv: r.vec(s.extra_uv, 16, |r| r.f32s())?,
        weight_kind: r.u8()?,
        ..Vertex::default()
    };
    let (bones, weights) =
        weight_shape(v.weight_kind, s.v21).ok_or(r.invalid("bad weight type"))?;
    for b in &mut v.bones[..bones] {
        *b = index(r, s.bone)?;
    }
    for x in &mut v.weights[..weights] {
        *x = r.f32()?;
    }
    if v.weight_kind == 3 {
        v.sdef = [r.f32s()?, r.f32s()?, r.f32s()?];
    }
    v.edge_scale = r.f32()?;
    Ok(v)
}

fn write_vertex(w: &mut Writer, s: Sizes, v: &Vertex) -> Result<()> {
    if v.extra_uv.len() != s.extra_uv {
        return Err(w.invalid("additional UV count differs from the header"));
    }
    let (bones, weights) =
        weight_shape(v.weight_kind, s.v21).ok_or(w.invalid("bad weight type"))?;
    w.f32s(&v.position);
    w.f32s(&v.normal);
    w.f32s(&v.uv);
    for uv in &v.extra_uv {
        w.f32s(uv);
    }
    w.u8(v.weight_kind);
    for &b in &v.bones[..bones] {
        write_index(w, s.bone, b);
    }
    w.f32s(&v.weights[..weights]);
    if v.weight_kind == 3 {
        for p in &v.sdef {
            w.f32s(p);
        }
    }
    w.f32(v.edge_scale);
    Ok(())
}

fn read_material(r: &mut Reader, s: Sizes) -> Result<Material> {
    let (name, name_en) = texts(r, s)?;
    let diffuse = r.f32s()?;
    let specular = r.f32s()?;
    let specular_power = r.f32()?;
    let ambient = r.f32s()?;
    let flags = r.u8()?;
    let edge_color = r.f32s()?;
    let edge_size = r.f32()?;
    let texture = index(r, s.texture)?;
    let sphere = index(r, s.texture)?;
    let sphere_mode = r.u8()?;
    let shared_toon = r.u8()?;
    let toon = if shared_toon != 0 {
        r.u8()?.into()
    } else {
        index(r, s.texture)?
    };
    Ok(Material {
        name,
        name_en,
        diffuse,
        specular,
        specular_power,
        ambient,
        flags,
        edge_color,
        edge_size,
        texture,
        sphere,
        sphere_mode,
        shared_toon,
        toon,
        memo: PmxText::read(r, s.enc)?,
        face_vertex_count: r.i32()?,
    })
}

fn write_material(w: &mut Writer, s: Sizes, m: &Material) -> Result<()> {
    m.name.write(w)?;
    m.name_en.write(w)?;
    w.f32s(&m.diffuse);
    w.f32s(&m.specular);
    w.f32(m.specular_power);
    w.f32s(&m.ambient);
    w.u8(m.flags);
    w.f32s(&m.edge_color);
    w.f32(m.edge_size);
    write_index(w, s.texture, m.texture);
    write_index(w, s.texture, m.sphere);
    w.u8(m.sphere_mode);
    w.u8(m.shared_toon);
    if m.shared_toon != 0 {
        w.u8(m.toon as u8);
    } else {
        write_index(w, s.texture, m.toon);
    }
    m.memo.write(w)?;
    w.i32(m.face_vertex_count);
    Ok(())
}

fn read_bone(r: &mut Reader, s: Sizes) -> Result<Bone> {
    let (name, name_en) = texts(r, s)?;
    let mut b = Bone {
        name,
        name_en,
        position: r.f32s()?,
        parent: index(r, s.bone)?,
        layer: r.i32()?,
        flags: r.u16()?,
        tail_bone: 0,
        tail_offset: [0.0; 3],
        inherit_parent: 0,
        inherit_ratio: 0.0,
        fixed_axis: [0.0; 3],
        local_axes: [[0.0; 3]; 2],
        external_parent: 0,
        ik: Ik::default(),
    };
    if b.flags & 0x0001 != 0 {
        b.tail_bone = index(r, s.bone)?;
    } else {
        b.tail_offset = r.f32s()?;
    }
    if b.flags & 0x0300 != 0 {
        b.inherit_parent = index(r, s.bone)?;
        b.inherit_ratio = r.f32()?;
    }
    if b.flags & 0x0400 != 0 {
        b.fixed_axis = r.f32s()?;
    }
    if b.flags & 0x0800 != 0 {
        b.local_axes = [r.f32s()?, r.f32s()?];
    }
    if b.flags & 0x2000 != 0 {
        b.external_parent = r.i32()?;
    }
    if b.flags & 0x0020 != 0 {
        b.ik.target = index(r, s.bone)?;
        b.ik.loops = r.i32()?;
        b.ik.angle = r.f32()?;
        let n = r.i32()?;
        if !(0..=65535).contains(&n) {
            return Err(r.invalid("bad IK link count"));
        }
        b.ik.links = r.vec(n as usize, 2, |r| {
            let mut l = IkLink {
                bone: index(r, s.bone)?,
                has_limits: r.u8()?,
                ..IkLink::default()
            };
            if l.has_limits == 1 {
                l.limits = [r.f32s()?, r.f32s()?];
            }
            Ok(l)
        })?;
    }
    Ok(b)
}

fn write_bone(w: &mut Writer, s: Sizes, b: &Bone) -> Result<()> {
    b.name.write(w)?;
    b.name_en.write(w)?;
    w.f32s(&b.position);
    write_index(w, s.bone, b.parent);
    w.i32(b.layer);
    w.u16(b.flags);
    if b.flags & 0x0001 != 0 {
        write_index(w, s.bone, b.tail_bone);
    } else {
        w.f32s(&b.tail_offset);
    }
    if b.flags & 0x0300 != 0 {
        write_index(w, s.bone, b.inherit_parent);
        w.f32(b.inherit_ratio);
    }
    if b.flags & 0x0400 != 0 {
        w.f32s(&b.fixed_axis);
    }
    if b.flags & 0x0800 != 0 {
        w.f32s(&b.local_axes[0]);
        w.f32s(&b.local_axes[1]);
    }
    if b.flags & 0x2000 != 0 {
        w.i32(b.external_parent);
    }
    if b.flags & 0x0020 != 0 {
        write_index(w, s.bone, b.ik.target);
        w.i32(b.ik.loops);
        w.f32(b.ik.angle);
        if b.ik.links.len() > 65535 {
            return Err(w.invalid("over 65535 IK links"));
        }
        w.count32(b.ik.links.len())?;
        for l in &b.ik.links {
            write_index(w, s.bone, l.bone);
            w.u8(l.has_limits);
            if l.has_limits == 1 {
                w.f32s(&l.limits[0]);
                w.f32s(&l.limits[1]);
            }
        }
    }
    Ok(())
}

fn read_morph(r: &mut Reader, s: Sizes, total: &mut usize) -> Result<Morph> {
    let (name, name_en) = texts(r, s)?;
    let panel = r.u8()?;
    let kind = r.u8()?;
    let n = usize::try_from(r.i32()?).map_err(|_| r.invalid("negative offset count"))?;
    *total += n;
    r.limit(*total, MAX_OFFSETS, "too many morph offsets")?;
    let offsets = match kind {
        0 | 9 => Offsets::Group(r.vec(n, 5, |r| Ok((index(r, s.morph)?, r.f32()?)))?),
        1 => Offsets::Vertex(r.vec(n, 13, |r| Ok((vertex_index(r, s.vertex)?, r.f32s()?)))?),
        2 => Offsets::Bone(r.vec(n, 29, |r| Ok((index(r, s.bone)?, r.f32s()?, r.f32s()?)))?),
        3..=7 => Offsets::Uv(r.vec(n, 17, |r| Ok((vertex_index(r, s.vertex)?, r.f32s()?)))?),
        8 => Offsets::Material(r.vec(n, 114, |r| {
            Ok(MaterialOffset {
                material: index(r, s.material)?,
                operation: r.u8()?,
                values: r.f32s()?,
            })
        })?),
        10 => Offsets::Impulse(r.vec(n, 26, |r| {
            Ok((index(r, s.rigid)?, r.u8()?, r.f32s()?, r.f32s()?))
        })?),
        _ if n == 0 => Offsets::None,
        _ => return Err(r.invalid("offsets of an unknown morph kind")),
    };
    if kind > 8 && !s.v21 && n != 0 {
        return Err(r.invalid("PMX 2.1 morph in a 2.0 file"));
    }
    Ok(Morph {
        name,
        name_en,
        panel,
        kind,
        offsets,
    })
}

fn write_morph(w: &mut Writer, s: Sizes, m: &Morph) -> Result<()> {
    let ok = matches!(
        (&m.offsets, m.kind),
        (Offsets::Group(_), 0 | 9)
            | (Offsets::Vertex(_), 1)
            | (Offsets::Bone(_), 2)
            | (Offsets::Uv(_), 3..=7)
            | (Offsets::Material(_), 8)
            | (Offsets::Impulse(_), 10)
            | (Offsets::None, 11..)
    );
    if !ok {
        return Err(w.invalid("morph offsets do not match the morph kind"));
    }
    m.name.write(w)?;
    m.name_en.write(w)?;
    w.u8(m.panel);
    w.u8(m.kind);
    match &m.offsets {
        Offsets::Group(v) => {
            w.count32(v.len())?;
            for &(i, x) in v {
                write_index(w, s.morph, i);
                w.f32(x);
            }
        }
        Offsets::Vertex(v) => {
            w.count32(v.len())?;
            for (i, d) in v {
                write_vertex_index(w, s.vertex, *i);
                w.f32s(d);
            }
        }
        Offsets::Bone(v) => {
            w.count32(v.len())?;
            for (i, t, q) in v {
                write_index(w, s.bone, *i);
                w.f32s(t);
                w.f32s(q);
            }
        }
        Offsets::Uv(v) => {
            w.count32(v.len())?;
            for (i, d) in v {
                write_vertex_index(w, s.vertex, *i);
                w.f32s(d);
            }
        }
        Offsets::Material(v) => {
            w.count32(v.len())?;
            for o in v {
                write_index(w, s.material, o.material);
                w.u8(o.operation);
                w.f32s(&o.values);
            }
        }
        Offsets::Impulse(v) => {
            w.count32(v.len())?;
            for (i, local, vel, torque) in v {
                write_index(w, s.rigid, *i);
                w.u8(*local);
                w.f32s(vel);
                w.f32s(torque);
            }
        }
        Offsets::None => w.i32(0),
    }
    Ok(())
}

fn read_rigid(r: &mut Reader, s: Sizes) -> Result<Rigid> {
    let (name, name_en) = texts(r, s)?;
    Ok(Rigid {
        name,
        name_en,
        bone: index(r, s.bone)?,
        group: r.u8()?,
        mask: r.u16()?,
        shape: r.u8()?,
        size: r.f32s()?,
        position: r.f32s()?,
        rotation: r.f32s()?,
        mass: r.f32()?,
        linear_damping: r.f32()?,
        angular_damping: r.f32()?,
        restitution: r.f32()?,
        friction: r.f32()?,
        mode: r.u8()?,
    })
}

fn read_joint(r: &mut Reader, s: Sizes) -> Result<Joint> {
    let (name, name_en) = texts(r, s)?;
    Ok(Joint {
        name,
        name_en,
        kind: r.u8()?,
        rigid_a: index(r, s.rigid)?,
        rigid_b: index(r, s.rigid)?,
        position: r.f32s()?,
        rotation: r.f32s()?,
        translation_min: r.f32s()?,
        translation_max: r.f32s()?,
        rotation_min: r.f32s()?,
        rotation_max: r.f32s()?,
        spring_translation: r.f32s()?,
        spring_rotation: r.f32s()?,
    })
}
