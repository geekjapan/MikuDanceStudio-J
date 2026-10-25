//! The pose and model files of the model menu: `LoadVpdFile` and
//! `SaveVpdFile` (`src/io/vpd_file.cpp`, VA 0x00418A10 and 0x00418750) and
//! `SaveEnhancedModel` (`src/window/enhance_model_io.cpp`, VA 0x0041EC10).

use crate::history::{Entry, History, PoseSnapshot};
use crate::model::{ModelEdit, Skeleton};
use crate::Error;
use mds_formats::pmd::Pmd;
use mds_formats::pmm;
use mds_formats::text::Sjis;
use mds_formats::vpd::{Bone, Vpd};

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
}

/// `LoadVpdFile` onto `m`: an undo entry with one pose snapshot per VPD
/// bone (zeros when no bone has its name; the last bone of that name
/// otherwise), then every bone of that name takes the pose and is selected
/// and marked edited; a fixed-axis bone gets the registrar's twist
/// correction. No seek follows. The file is read with
/// `mds_formats::vpd` (`ReadVpd`), not the `fgets`/`fscanf` sequence of the
/// C++, which agree on well-formed files.
pub fn load_vpd(
    m: &mut pmm::Model,
    s: &Skeleton,
    h: &mut History,
    data: &[u8],
) -> Result<(), Error> {
    let vpd = Vpd::read(data).map_err(|e| Error::Format(e.to_string()))?;
    let matches = |b: &Bone| -> Vec<usize> {
        let want = cstr(&b.name.raw);
        (0..m.bone_names.len())
            .filter(|&i| cstr(&m.bone_names[i].raw) == want)
            .collect()
    };
    let mut snaps = vec![
        PoseSnapshot {
            bone: 0,
            translation: [0.0; 3],
            rotation: [0.0; 4],
            edited: 0,
        };
        vpd.bones.len()
    ];
    for (snap, b) in snaps.iter_mut().zip(&vpd.bones) {
        // The C++ corrects the one quaternion it read in place, so a second
        // bone of the same name gets the corrected value.
        let mut rotation = b.rotation;
        for i in matches(b) {
            if s.bones.get(i).is_some_and(|b| b.1) {
                // `vpd_file.cpp` 231-274: the registrar's twist correction.
                let axis = s.axes[i];
                let axis = if s.pmx {
                    axis
                } else {
                    mds_math::Vec3(axis).normalize().0
                };
                rotation = mds_edit::twist(axis, rotation);
            }
            let p = &mut m.bone_pose[i];
            *snap = PoseSnapshot {
                bone: i as u32,
                translation: p.translation,
                rotation: p.rotation,
                edited: p.flags[1],
            };
            p.flags[2] = 1;
            p.flags[1] = 1;
            p.translation = b.translation;
            p.rotation = rotation;
        }
    }
    h.push(Entry::BonePose(snaps));
    Ok(())
}

/// `SaveVpdFile` of `m`: the selected bones in bone order, each with the
/// physics pose when physics drives it (a rigid body, `physicsDisabled` 0,
/// physics mode 2 or 3), else the saved pose. The file is opened in text
/// mode, so lines end in CRLF.
pub fn save_vpd(
    m: &pmm::Model,
    s: &Skeleton,
    e: &ModelEdit,
    physics_mode: u8,
) -> Result<Vec<u8>, Error> {
    let mut bones = Vec::new();
    for (i, p) in m
        .bone_pose
        .iter()
        .enumerate()
        .filter(|(_, p)| p.flags[2] != 0)
    {
        let (translation, rotation) =
            if s.bones.get(i).is_some_and(|b| b.2) && p.flags[0] == 0 && physics_mode >= 2 {
                let pose = e.physics_pose.as_ref().and_then(|v| v.get(i)).ok_or(
                    mds_edit::Error::Unsupported("the physics pose of a rigid-body bone"),
                )?;
                (pose.1, pose.0)
            } else {
                (p.translation, p.rotation)
            };
        bones.push(Bone {
            name: Sjis::from_raw(cstr(&m.bone_names[i].raw).to_vec()),
            translation,
            rotation,
        });
    }
    if bones.is_empty() {
        return Err(Error::NotApplicable("no bone is selected (a message box)"));
    }
    Ok(Vpd {
        model_name: Sjis::from_raw(cstr(&m.name.raw).to_vec()),
        bones,
        crlf: true,
    }
    .write())
}

/// `SaveEnhancedModel` of a PMD as loaded: the reader's file written back
/// with the writer's quirks. Morph 0's offsets overwrite (not add to) the
/// vertex positions; edge flags become 0 or 1; the index loop reads the
/// loader's buffer, which keeps each index in a 32-bit slot, with a 16-bit
/// stride, so it writes the first half of the indices with a 0 after each;
/// later morphs map their base-morph index back through the vertex it names
/// (the first base entry of that vertex); the English flag is 1; texture
/// names are zero after their NUL; bytes after the joints are dropped.
/// The vertex overwrite stays on `pmd`, as on the C++ model.
pub fn save_pmd(pmd: &mut Pmd) -> Result<Vec<u8>, Error> {
    let unsupported = |what| Error::Edit(mds_edit::Error::Unsupported(what));
    let ext = pmd
        .extension
        .as_ref()
        .ok_or(unsupported("a PMD without the English section"))?;
    if ext.english.is_none() || ext.physics.is_none() {
        return Err(unsupported("a PMD without English names or physics"));
    }
    if let Some(m) = pmd.morphs.first() {
        for &(v, offset) in &m.offsets {
            if let Some(v) = pmd.vertices.get_mut(v as usize) {
                v.position = offset;
            }
        }
    }
    let mut p = pmd.clone();
    if let Some(ext) = &mut p.extension {
        ext.english_flag = 1;
    }
    p.version = 1.0;
    p.trailing.clear();
    let base: Vec<u32> = p
        .morphs
        .first()
        .map_or(Vec::new(), |m| m.offsets.iter().map(|o| o.0).collect());
    for m in p.morphs.iter_mut().skip(1) {
        for o in &mut m.offsets {
            // ponytail: an index past the base morph keeps its value; the C++
            // loader reads past its table there.
            if let Some(&v) = base.get(o.0 as usize) {
                o.0 = base.iter().position(|&b| b == v).unwrap_or(0) as u32;
            }
        }
    }
    for v in &mut p.vertices {
        v.edge_disabled = u8::from(v.edge_disabled != 0);
    }
    p.indices = (0..p.indices.len())
        .map(|i| if i % 2 == 0 { p.indices[i / 2] } else { 0 })
        .collect();
    for mat in &mut p.materials {
        let n = cstr(&mat.texture.raw).len();
        mat.texture.raw[n..].fill(0);
    }
    p.write().map_err(|e| Error::Format(e.to_string()))
}
