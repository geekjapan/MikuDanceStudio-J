//! PMD models, in the layout `model_reader.cpp` on `next` reads.
//!
//! The file may end after the bone-frame table, after the toon names, or
//! after the rigid bodies; the C++ reader accepts each of those ends, and the
//! optional parts here are `None` to match.

use crate::io::{Reader, Result, Writer};
use crate::text::FixedSjis;

const MAX_VERTICES: usize = 1_000_000;
const MAX_INDICES: usize = 3_000_000;
const MAX_RECORDS: usize = 100_000;
const MAX_OFFSETS: usize = 1_000_000;

#[derive(Clone, Debug)]
pub struct Pmd {
    pub version: f32,
    pub name: FixedSjis<20>,
    pub comment: FixedSjis<256>,
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u16>,
    pub materials: Vec<Material>,
    pub bones: Vec<Bone>,
    pub ik_chains: Vec<IkChain>,
    pub morphs: Vec<Morph>,
    /// Morph indices shown in the facial panel.
    pub morph_display: Vec<u16>,
    pub bone_groups: Vec<FixedSjis<50>>,
    pub bone_frames: Vec<BoneFrame>,
    /// `None` when the file ends after the bone frames.
    pub extension: Option<Extension>,
    /// Bytes after the joints, ignored by the C++ reader.
    pub trailing: Vec<u8>,
}

#[derive(Clone, Debug, Default)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    pub bones: [u16; 2],
    pub weight: u8,
    pub edge_disabled: u8,
}

#[derive(Clone, Debug)]
pub struct Material {
    pub diffuse: [f32; 4],
    pub specular_power: f32,
    pub specular: [f32; 3],
    pub ambient: [f32; 3],
    pub toon: u8,
    pub edge: u8,
    pub face_vertex_count: u32,
    pub texture: FixedSjis<20>,
}

#[derive(Clone, Debug)]
pub struct Bone {
    pub name: FixedSjis<20>,
    pub parent: i16,
    pub tail: i16,
    pub kind: u8,
    pub ik_parent: i16,
    pub position: [f32; 3],
}

#[derive(Clone, Debug, Default)]
pub struct IkChain {
    pub bone: u16,
    pub target: u16,
    pub iterations: u16,
    pub max_angle: f32,
    /// At most 255 links (u8 count).
    pub links: Vec<u16>,
}

#[derive(Clone, Debug)]
pub struct Morph {
    pub name: FixedSjis<20>,
    pub panel: u8,
    /// `(vertex index, offset)`.
    pub offsets: Vec<(u32, [f32; 3])>,
}

#[derive(Clone, Debug, Default)]
pub struct BoneFrame {
    pub bone: u16,
    pub group: u8,
}

/// Everything after the bone frames.
#[derive(Clone, Debug)]
pub struct Extension {
    /// The English-section flag byte as read.
    pub english_flag: u8,
    /// Present when `english_flag` is not 0.
    pub english: Option<English>,
    pub toon_textures: [FixedSjis<100>; 10],
    /// `None` when the file ends after the toon names.
    pub physics: Option<Physics>,
}

#[derive(Clone, Debug)]
pub struct English {
    pub name: FixedSjis<20>,
    pub comment: FixedSjis<256>,
    /// One per bone.
    pub bone_names: Vec<FixedSjis<20>>,
    /// One per morph after the base morph.
    pub morph_names: Vec<FixedSjis<20>>,
    /// One per bone group.
    pub group_names: Vec<FixedSjis<50>>,
}

#[derive(Clone, Debug)]
pub struct Physics {
    pub rigids: Vec<Rigid>,
    /// `None` when the file ends after the rigid bodies.
    pub joints: Option<Vec<Joint>>,
}

#[derive(Clone, Debug)]
pub struct Rigid {
    pub name: FixedSjis<20>,
    pub bone: i16,
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
    pub name: FixedSjis<20>,
    pub rigid_a: u32,
    pub rigid_b: u32,
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub translation_min: [f32; 3],
    pub translation_max: [f32; 3],
    pub rotation_min: [f32; 3],
    pub rotation_max: [f32; 3],
    pub spring_translation: [f32; 3],
    pub spring_rotation: [f32; 3],
}

/// An optional section count: `None` at the end of the file, `Err` when
/// the file ends inside the count (`ReadPmdOptionalCount`).
fn optional_u32(r: &mut Reader) -> Result<Option<u32>> {
    if r.remaining() == 0 {
        return Ok(None);
    }
    r.u32().map(Some)
}

fn count(r: &mut Reader, limit: usize) -> Result<usize> {
    let n = r.u32()? as usize;
    bounded(r, n, limit)
}

fn bounded(r: &Reader, n: usize, limit: usize) -> Result<usize> {
    r.limit(n, limit, "count over the C++ limit")
}

impl Pmd {
    pub fn read(data: &[u8]) -> Result<Self> {
        let r = &mut Reader::new(data);
        if r.bytes(3)? != b"Pmd" {
            return Err(r.invalid("not a PMD file"));
        }
        let version = r.f32()?;
        let name = FixedSjis::read(r)?;
        let comment = FixedSjis::read(r)?;
        let n = count(r, MAX_VERTICES)?;
        let vertices = r.vec(n, 38, |r| {
            Ok(Vertex {
                position: r.f32s()?,
                normal: r.f32s()?,
                uv: r.f32s()?,
                bones: [r.u16()?, r.u16()?],
                weight: r.u8()?,
                edge_disabled: r.u8()?,
            })
        })?;
        let n = count(r, MAX_INDICES)?;
        let indices = r.vec(n, 2, |r| r.u16())?;
        let n = count(r, MAX_RECORDS)?;
        let materials = r.vec(n, 70, |r| {
            Ok(Material {
                diffuse: r.f32s()?,
                specular_power: r.f32()?,
                specular: r.f32s()?,
                ambient: r.f32s()?,
                toon: r.u8()?,
                edge: r.u8()?,
                face_vertex_count: r.u32()?,
                texture: FixedSjis::read(r)?,
            })
        })?;
        let n = r.u16()?.into();
        let bones = r.vec(n, 39, |r| {
            Ok(Bone {
                name: FixedSjis::read(r)?,
                parent: r.i16()?,
                tail: r.i16()?,
                kind: r.u8()?,
                ik_parent: r.i16()?,
                position: r.f32s()?,
            })
        })?;
        let n = r.u16()?.into();
        let ik_chains = r.vec(n, 11, |r| {
            let bone = r.u16()?;
            let target = r.u16()?;
            let links = r.u8()?.into();
            Ok(IkChain {
                bone,
                target,
                iterations: r.u16()?,
                max_angle: r.f32()?,
                links: r.vec(links, 2, |r| r.u16())?,
            })
        })?;
        let n = r.u16()?.into();
        let mut total = 0usize;
        let morphs = r.vec(n, 25, |r| {
            let name = FixedSjis::read(r)?;
            let count = r.i32()?;
            let count = usize::try_from(count).map_err(|_| r.invalid("negative morph count"))?;
            total += count;
            bounded(r, total, MAX_OFFSETS)?;
            Ok(Morph {
                name,
                panel: r.u8()?,
                offsets: r.vec(count, 16, |r| Ok((r.u32()?, r.f32s()?)))?,
            })
        })?;
        let n = r.u8()?.into();
        let morph_display = r.vec(n, 2, |r| r.u16())?;
        let n = r.u8()?.into();
        let bone_groups = r.vec(n, 50, FixedSjis::read)?;
        let n = count(r, MAX_RECORDS)?;
        let bone_frames = r.vec(n, 3, |r| {
            Ok(BoneFrame {
                bone: r.u16()?,
                group: r.u8()?,
            })
        })?;
        let extension = if r.remaining() == 0 {
            None
        } else {
            Some(Extension::read(r, &bones, &morphs, &bone_groups)?)
        };
        let trailing = r.rest();
        Ok(Pmd {
            version,
            name,
            comment,
            vertices,
            indices,
            materials,
            bones,
            ik_chains,
            morphs,
            morph_display,
            bone_groups,
            bone_frames,
            extension,
            trailing,
        })
    }

    pub fn write(&self) -> Result<Vec<u8>> {
        let w = &mut Writer::default();
        w.bytes(b"Pmd");
        w.f32(self.version);
        self.name.write(w);
        self.comment.write(w);
        w.count32(self.vertices.len())?;
        for v in &self.vertices {
            w.f32s(&v.position);
            w.f32s(&v.normal);
            w.f32s(&v.uv);
            w.u16(v.bones[0]);
            w.u16(v.bones[1]);
            w.u8(v.weight);
            w.u8(v.edge_disabled);
        }
        w.count32(self.indices.len())?;
        for &i in &self.indices {
            w.u16(i);
        }
        w.count32(self.materials.len())?;
        for m in &self.materials {
            w.f32s(&m.diffuse);
            w.f32(m.specular_power);
            w.f32s(&m.specular);
            w.f32s(&m.ambient);
            w.u8(m.toon);
            w.u8(m.edge);
            w.u32(m.face_vertex_count);
            m.texture.write(w);
        }
        count16(w, self.bones.len())?;
        for b in &self.bones {
            b.name.write(w);
            w.i16(b.parent);
            w.i16(b.tail);
            w.u8(b.kind);
            w.i16(b.ik_parent);
            w.f32s(&b.position);
        }
        count16(w, self.ik_chains.len())?;
        for k in &self.ik_chains {
            w.u16(k.bone);
            w.u16(k.target);
            count8(w, k.links.len())?;
            w.u16(k.iterations);
            w.f32(k.max_angle);
            for &l in &k.links {
                w.u16(l);
            }
        }
        count16(w, self.morphs.len())?;
        for m in &self.morphs {
            m.name.write(w);
            w.count32(m.offsets.len())?;
            w.u8(m.panel);
            for (v, d) in &m.offsets {
                w.u32(*v);
                w.f32s(d);
            }
        }
        count8(w, self.morph_display.len())?;
        for &d in &self.morph_display {
            w.u16(d);
        }
        count8(w, self.bone_groups.len())?;
        for g in &self.bone_groups {
            g.write(w);
        }
        w.count32(self.bone_frames.len())?;
        for f in &self.bone_frames {
            w.u16(f.bone);
            w.u8(f.group);
        }
        if let Some(e) = &self.extension {
            e.write(w, self)?;
        }
        w.bytes(&self.trailing);
        Ok(std::mem::take(&mut w.out))
    }
}

fn count16(w: &mut Writer, n: usize) -> Result<()> {
    w.u16(u16::try_from(n).map_err(|_| w.invalid("over 65535 records"))?);
    Ok(())
}
fn count8(w: &mut Writer, n: usize) -> Result<()> {
    w.u8(u8::try_from(n).map_err(|_| w.invalid("over 255 records"))?);
    Ok(())
}

impl Extension {
    fn read(
        r: &mut Reader,
        bones: &[Bone],
        morphs: &[Morph],
        groups: &[FixedSjis<50>],
    ) -> Result<Self> {
        let english_flag = r.u8()?;
        let english = if english_flag == 0 {
            None
        } else {
            Some(English {
                name: FixedSjis::read(r)?,
                comment: FixedSjis::read(r)?,
                bone_names: r.vec(bones.len(), 20, FixedSjis::read)?,
                morph_names: r.vec(morphs.len().saturating_sub(1), 20, FixedSjis::read)?,
                group_names: r.vec(groups.len(), 50, FixedSjis::read)?,
            })
        };
        let toons = r.vec(10, 100, FixedSjis::read)?;
        let toon_textures = toons.try_into().map_err(|_| r.invalid("toon table"))?;
        let physics = match optional_u32(r)? {
            None => None,
            Some(n) => {
                let n = bounded(r, n as usize, MAX_RECORDS)?;
                let rigids = r.vec(n, 83, |r| {
                    Ok(Rigid {
                        name: FixedSjis::read(r)?,
                        bone: r.i16()?,
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
                })?;
                let joints = match optional_u32(r)? {
                    None => None,
                    Some(n) => {
                        let n = bounded(r, n as usize, MAX_RECORDS)?;
                        Some(r.vec(n, 124, |r| {
                            Ok(Joint {
                                name: FixedSjis::read(r)?,
                                rigid_a: r.u32()?,
                                rigid_b: r.u32()?,
                                position: r.f32s()?,
                                rotation: r.f32s()?,
                                translation_min: r.f32s()?,
                                translation_max: r.f32s()?,
                                rotation_min: r.f32s()?,
                                rotation_max: r.f32s()?,
                                spring_translation: r.f32s()?,
                                spring_rotation: r.f32s()?,
                            })
                        })?)
                    }
                };
                Some(Physics { rigids, joints })
            }
        };
        Ok(Extension {
            english_flag,
            english,
            toon_textures,
            physics,
        })
    }

    fn write(&self, w: &mut Writer, pmd: &Pmd) -> Result<()> {
        w.u8(self.english_flag);
        match (&self.english, self.english_flag) {
            (None, 0) => {}
            (Some(e), f) if f != 0 => {
                if e.bone_names.len() != pmd.bones.len()
                    || e.morph_names.len() != pmd.morphs.len().saturating_sub(1)
                    || e.group_names.len() != pmd.bone_groups.len()
                {
                    return Err(w.invalid("English tables differ from the model"));
                }
                e.name.write(w);
                e.comment.write(w);
                for n in &e.bone_names {
                    n.write(w);
                }
                for n in &e.morph_names {
                    n.write(w);
                }
                for n in &e.group_names {
                    n.write(w);
                }
            }
            _ => return Err(w.invalid("English flag and section disagree")),
        }
        for t in &self.toon_textures {
            t.write(w);
        }
        let Some(p) = &self.physics else {
            return Ok(());
        };
        w.count32(p.rigids.len())?;
        for b in &p.rigids {
            b.name.write(w);
            w.i16(b.bone);
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
        let Some(joints) = &p.joints else {
            return Ok(());
        };
        w.count32(joints.len())?;
        for j in joints {
            j.name.write(w);
            w.u32(j.rigid_a);
            w.u32(j.rigid_b);
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
        Ok(())
    }
}
