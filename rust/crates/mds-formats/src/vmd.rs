//! VMD motions, version 1 ("Vocaloid Motion Data file") and 2 ("... 0002"),
//! in the layout `vmd_format.cpp` on `next` reads and `vmd_save.cpp` writes.
//!
//! A file may end before the camera, light, self-shadow or IK count; the
//! C++ reader accepts each of those ends, so those sections are `Option`s.
//! A later section is present only when every earlier one is.

use crate::io::{Reader, Result, Writer};
use crate::text::{FixedSjis, Sjis};

const MAX_BONE_KEYS: usize = 600_000;
const MAX_MORPH_KEYS: usize = 20_000;
const MAX_TRACK_KEYS: usize = 10_000;
const MAX_IK_KEYS: usize = 1_000;
const MAX_IK_ENTRIES: usize = 10_000;

#[derive(Clone, Debug)]
pub struct Vmd {
    /// The 30-byte header, kept as read (version string and padding).
    pub header: [u8; 30],
    /// 20 bytes in version 2, 10 in version 1.
    pub model_name: Sjis,
    pub bones: Vec<BoneKey>,
    pub morphs: Vec<MorphKey>,
    pub cameras: Option<Vec<CameraKey>>,
    pub lights: Option<Vec<LightKey>>,
    /// Version 2 only, like `ik`.
    pub shadows: Option<Vec<ShadowKey>>,
    pub ik: Option<Vec<IkKey>>,
    /// Bytes after the last section, ignored by the C++ reader.
    pub trailing: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct BoneKey {
    pub name: FixedSjis<15>,
    pub frame: u32,
    pub position: [f32; 3],
    pub rotation: [f32; 4],
    /// The 64-byte curve block as stored.
    pub interpolation: [u8; 64],
}

#[derive(Clone, Debug)]
pub struct MorphKey {
    pub name: FixedSjis<15>,
    pub frame: u32,
    pub value: f32,
}

#[derive(Clone, Debug, Default)]
pub struct CameraKey {
    pub frame: u32,
    pub distance: f32,
    pub eye: [f32; 3],
    pub target: [f32; 3],
    /// 24 bytes in version 2; version 1 stores only the first 4.
    pub interpolation: [u8; 24],
    /// Version 2 only.
    pub fov: u32,
    pub perspective: u8,
}

#[derive(Clone, Debug, Default)]
pub struct LightKey {
    pub frame: u32,
    pub color: [f32; 3],
    pub direction: [f32; 3],
}

#[derive(Clone, Debug, Default)]
pub struct ShadowKey {
    pub frame: u32,
    pub mode: u8,
    pub distance: f32,
}

#[derive(Clone, Debug)]
pub struct IkKey {
    pub frame: u32,
    pub visible: u8,
    pub entries: Vec<IkEntry>,
}

#[derive(Clone, Debug)]
pub struct IkEntry {
    pub name: FixedSjis<20>,
    pub enabled: u8,
}

/// A section count that may be missing at the end of the file. Returns
/// `None` at the end, `Err` when the file ends inside the count.
fn optional_count(r: &mut Reader, limit: usize) -> Result<Option<usize>> {
    if r.remaining() == 0 {
        return Ok(None);
    }
    let n = r.u32()? as usize;
    r.limit(n, limit, "count over the C++ limit").map(Some)
}

impl Vmd {
    pub fn is_v2(&self) -> bool {
        self.header.starts_with(b"Vocaloid Motion Data 0002")
    }

    pub fn read(data: &[u8]) -> Result<Self> {
        let r = &mut Reader::new(data);
        let header = r.array::<30>()?;
        let v2 = if header.starts_with(b"Vocaloid Motion Data 0002") {
            true
        } else if header.starts_with(b"Vocaloid Motion Data file") {
            false
        } else {
            return Err(r.invalid("not a VMD file"));
        };
        let model_name = Sjis::from_raw(r.bytes(if v2 { 20 } else { 10 })?.to_vec());
        let n = r.u32()? as usize;
        r.limit(n, MAX_BONE_KEYS, "too many bone keys")?;
        let bones = r.vec(n, 111, |r| {
            Ok(BoneKey {
                name: FixedSjis::read(r)?,
                frame: r.u32()?,
                position: r.f32s()?,
                rotation: r.f32s()?,
                interpolation: r.array()?,
            })
        })?;
        let n = r.u32()? as usize;
        r.limit(n, MAX_MORPH_KEYS, "too many morph keys")?;
        let morphs = r.vec(n, 23, |r| {
            Ok(MorphKey {
                name: FixedSjis::read(r)?,
                frame: r.u32()?,
                value: r.f32()?,
            })
        })?;
        let mut vmd = Vmd {
            header,
            model_name,
            bones,
            morphs,
            cameras: None,
            lights: None,
            shadows: None,
            ik: None,
            trailing: Vec::new(),
        };
        vmd.read_optional(r, v2)?;
        vmd.trailing = r.rest();
        Ok(vmd)
    }

    fn read_optional(&mut self, r: &mut Reader, v2: bool) -> Result<()> {
        let Some(n) = optional_count(r, MAX_TRACK_KEYS)? else {
            return Ok(());
        };
        self.cameras = Some(r.vec(n, if v2 { 61 } else { 36 }, |r| {
            let mut k = CameraKey {
                frame: r.u32()?,
                distance: r.f32()?,
                eye: r.f32s()?,
                target: r.f32s()?,
                ..CameraKey::default()
            };
            if v2 {
                k.interpolation = r.array()?;
                k.fov = r.u32()?;
                k.perspective = r.u8()?;
            } else {
                k.interpolation[..4].copy_from_slice(r.bytes(4)?);
            }
            Ok(k)
        })?);
        let Some(n) = optional_count(r, MAX_TRACK_KEYS)? else {
            return Ok(());
        };
        self.lights = Some(r.vec(n, 28, |r| {
            Ok(LightKey {
                frame: r.u32()?,
                color: r.f32s()?,
                direction: r.f32s()?,
            })
        })?);
        if !v2 {
            return Ok(());
        }
        let Some(n) = optional_count(r, MAX_TRACK_KEYS)? else {
            return Ok(());
        };
        self.shadows = Some(r.vec(n, 9, |r| {
            Ok(ShadowKey {
                frame: r.u32()?,
                mode: r.u8()?,
                distance: r.f32()?,
            })
        })?);
        let Some(n) = optional_count(r, MAX_IK_KEYS)? else {
            return Ok(());
        };
        self.ik = Some(r.vec(n, 9, |r| {
            let frame = r.u32()?;
            let visible = r.u8()?;
            let n = r.u32()? as usize;
            r.limit(n, MAX_IK_ENTRIES, "too many IK entries")?;
            Ok(IkKey {
                frame,
                visible,
                entries: r.vec(n, 21, |r| {
                    Ok(IkEntry {
                        name: FixedSjis::read(r)?,
                        enabled: r.u8()?,
                    })
                })?,
            })
        })?);
        Ok(())
    }

    pub fn write(&self) -> Result<Vec<u8>> {
        let v2 = self.is_v2();
        let w = &mut Writer::default();
        if !v2 && !self.header.starts_with(b"Vocaloid Motion Data file") {
            return Err(w.invalid("not a VMD header"));
        }
        if self.model_name.raw.len() != if v2 { 20 } else { 10 } {
            return Err(w.invalid("model name width differs from the version"));
        }
        let sections = [
            self.cameras.is_some(),
            self.lights.is_some(),
            v2 && self.shadows.is_some(),
            v2 && self.ik.is_some(),
        ];
        if sections.windows(2).any(|p| !p[0] && p[1])
            || (!v2 && (self.shadows.is_some() || self.ik.is_some()))
        {
            return Err(w.invalid("a VMD section follows a missing one"));
        }
        w.bytes(&self.header);
        w.bytes(&self.model_name.raw);
        w.count32(self.bones.len())?;
        for k in &self.bones {
            k.name.write(w);
            w.u32(k.frame);
            w.f32s(&k.position);
            w.f32s(&k.rotation);
            w.bytes(&k.interpolation);
        }
        w.count32(self.morphs.len())?;
        for k in &self.morphs {
            k.name.write(w);
            w.u32(k.frame);
            w.f32(k.value);
        }
        if let Some(cameras) = &self.cameras {
            w.count32(cameras.len())?;
            for k in cameras {
                w.u32(k.frame);
                w.f32(k.distance);
                w.f32s(&k.eye);
                w.f32s(&k.target);
                if v2 {
                    w.bytes(&k.interpolation);
                    w.u32(k.fov);
                    w.u8(k.perspective);
                } else {
                    w.bytes(&k.interpolation[..4]);
                }
            }
        }
        if let Some(lights) = &self.lights {
            w.count32(lights.len())?;
            for k in lights {
                w.u32(k.frame);
                w.f32s(&k.color);
                w.f32s(&k.direction);
            }
        }
        if let Some(shadows) = &self.shadows {
            w.count32(shadows.len())?;
            for k in shadows {
                w.u32(k.frame);
                w.u8(k.mode);
                w.f32(k.distance);
            }
        }
        if let Some(ik) = &self.ik {
            w.count32(ik.len())?;
            for k in ik {
                w.u32(k.frame);
                w.u8(k.visible);
                w.count32(k.entries.len())?;
                for e in &k.entries {
                    e.name.write(w);
                    w.u8(e.enabled);
                }
            }
        }
        w.bytes(&self.trailing);
        Ok(std::mem::take(&mut w.out))
    }
}
