//! "Save motion" (menu 210): `SaveVmdFile` (`src/io/vmd_save.cpp`, VA
//! 0x00419370). The marked keys of the selected model, or in camera mode of
//! the camera, light and self-shadow tracks, every frame less the smallest
//! marked frame, in pool index order.

use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{self, Pmm};

/// `カメラ・照明`, the model name of a camera-mode motion.
const CAMERA_LIGHT: &[u8] = b"\x83\x4a\x83\x81\x83\x89\x81\x45\x8f\xc6\x96\xbe";

/// Every record of a pool, heads first, by index.
fn all<K: Key>(pool: &KeyPool<K>) -> impl Iterator<Item = (u32, &K)> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    heads.chain(pool.records().iter().map(|(i, k)| (*i, k)))
}

/// A name in a fixed field: its bytes, zeros after.
fn fixed(out: &mut Vec<u8>, name: &[u8], width: usize) {
    let n = name.len().min(width);
    out.extend_from_slice(&name[..n]);
    out.resize(out.len() + width - n, 0);
}

fn floats(out: &mut Vec<u8>, v: &[f32]) {
    v.iter()
        .for_each(|f| out.extend_from_slice(&f.to_le_bytes()));
}

fn head_of<K: Key>(pool: &KeyPool<K>, mut i: u32) -> u32 {
    let heads = pool.heads().len() as u32;
    for _ in 0..=pool.capacity() {
        if i < heads {
            return i;
        }
        i = pool.get(i).map_or(0, |k| k.previous());
    }
    0
}

/// The VMD bytes. `model` is the selected model in model mode.
pub fn save(p: &Pmm, model: Option<&pmm::Model>) -> Vec<u8> {
    let camera_mode = p.settings.options[0] != 0;
    let model = model.filter(|_| !camera_mode);
    let mut min = u32::MAX;
    let mut low = |f: u32| min = min.min(f);
    if let Some(m) = model {
        all(&m.bone_keys)
            .filter(|k| k.1.allocated != 0)
            .for_each(|k| low(k.1.frame));
        all(&m.morph_keys)
            .filter(|k| k.1.allocated != 0)
            .for_each(|k| low(k.1.frame));
        all(&m.display_keys)
            .filter(|k| k.1.allocated != 0)
            .for_each(|k| low(k.1.frame));
    } else if camera_mode {
        all(&p.camera)
            .filter(|k| k.1.selected != 0)
            .for_each(|k| low(k.1.frame));
        all(&p.light)
            .filter(|k| k.1.selected != 0)
            .for_each(|k| low(k.1.frame));
        all(&p.self_shadow)
            .filter(|k| k.1.selected != 0)
            .for_each(|k| low(k.1.frame));
    }
    let rel = |f: u32| f.wrapping_sub(min).to_le_bytes();

    let mut out = Vec::new();
    fixed(&mut out, b"Vocaloid Motion Data 0002", 30);
    match model {
        Some(m) => fixed(&mut out, &m.name.raw, 20),
        None => {
            // `strcpy_s` into the buffer that still holds the header text.
            let mut buf = [0; 20];
            buf.copy_from_slice(&out[..20]);
            buf[..CAMERA_LIGHT.len()].copy_from_slice(CAMERA_LIGHT);
            buf[CAMERA_LIGHT.len()] = 0;
            out.extend_from_slice(&buf);
        }
    }
    let count = |out: &mut Vec<u8>, n: usize| out.extend_from_slice(&(n as u32).to_le_bytes());

    let bones: Vec<_> = model.map_or(Vec::new(), |m| {
        all(&m.bone_keys).filter(|k| k.1.allocated != 0).collect()
    });
    count(&mut out, bones.len());
    if let Some(m) = model {
        for (i, k) in &bones {
            let b = head_of(&m.bone_keys, *i) as usize;
            fixed(&mut out, &m.bone_names[b].raw, 15);
            out.extend_from_slice(&rel(k.frame));
            floats(&mut out, &k.position);
            floats(&mut out, &k.rotation);
            // The transposed curve table, one 4-byte read per row, which
            // overlaps the next channels' bytes; channel 0 carries the
            // physics marker.
            let mut raw = k.interpolation.to_vec();
            raw.extend_from_slice(&k.position[0].to_le_bytes()[..3]);
            for ch in 0..4 {
                if ch == 0 {
                    out.extend_from_slice(&raw[..2]);
                    let marker: u16 = if k.physics_disabled != 0 { 0x0F63 } else { 0 };
                    out.extend_from_slice(&marker.to_le_bytes());
                } else {
                    out.extend_from_slice(&raw[ch..ch + 4]);
                }
                for row in 1..4 {
                    out.extend_from_slice(&raw[4 * row + ch..4 * row + ch + 4]);
                }
            }
        }
    }

    let morphs: Vec<_> = model.map_or(Vec::new(), |m| {
        all(&m.morph_keys).filter(|k| k.1.allocated != 0).collect()
    });
    count(&mut out, morphs.len());
    if let Some(m) = model {
        for (i, k) in &morphs {
            let n = head_of(&m.morph_keys, *i) as usize;
            fixed(&mut out, &m.morph_names[n].raw, 15);
            out.extend_from_slice(&rel(k.frame));
            floats(&mut out, &[k.value]);
        }
    }

    let cams: Vec<_> = all(&p.camera)
        .filter(|k| camera_mode && k.1.selected != 0)
        .collect();
    count(&mut out, cams.len());
    for (_, k) in cams {
        out.extend_from_slice(&rel(k.frame));
        floats(&mut out, &[k.distance]);
        floats(&mut out, &k.eye);
        floats(&mut out, &k.target);
        for j in 0..6 {
            for row in [0, 2, 1, 3] {
                out.push(k.interpolation[row][j]);
            }
        }
        out.extend_from_slice(&k.fov.to_le_bytes());
        out.push(u8::from(k.perspective != 0));
    }
    let lights: Vec<_> = all(&p.light)
        .filter(|k| camera_mode && k.1.selected != 0)
        .collect();
    count(&mut out, lights.len());
    for (_, k) in lights {
        out.extend_from_slice(&rel(k.frame));
        floats(&mut out, &k.color);
        floats(&mut out, &k.direction);
    }
    let shadows: Vec<_> = all(&p.self_shadow)
        .filter(|k| camera_mode && k.1.selected != 0)
        .collect();
    count(&mut out, shadows.len());
    for (_, k) in shadows {
        out.extend_from_slice(&rel(k.frame));
        out.push(k.mode);
        floats(&mut out, &[k.distance]);
    }

    let displays: Vec<_> = model.map_or(Vec::new(), |m| {
        all(&m.display_keys)
            .filter(|k| k.1.allocated != 0)
            .collect()
    });
    count(&mut out, displays.len());
    if let Some(m) = model {
        for (_, k) in displays {
            out.extend_from_slice(&rel(k.frame));
            out.push(u8::from(k.visible != 0));
            count(&mut out, m.ik_bones.len());
            for (j, &b) in m.ik_bones.iter().enumerate() {
                fixed(&mut out, &m.bone_names[b as usize].raw, 20);
                out.push(u8::from(k.ik_enabled.get(j).is_some_and(|&on| on != 0)));
            }
        }
    }
    out
}
