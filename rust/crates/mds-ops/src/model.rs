//! The active model of a scene as `mds-edit` reads it, and the facts about
//! it that a PMM file does not hold.

use crate::{Error, Result};
use mds_edit::{BoneInfo, IkChain, MorphInfo, Rig, Selector, Tracks};
use mds_formats::pmm::{Model, Pmm};

/// What the model file says about one bone and the PMM does not.
#[derive(Clone, Debug)]
pub struct BoneFacts {
    /// `BoneRecord::parent`: the parent bone, `-1` for a root.
    pub parent: i32,
    /// `BoneRecord::type` (`bone_layout.hpp`): 0 rotate+move, 1 move, 2 IK,
    /// 4 under IK, 6 effector, 7 inert tip, 8 fixed axis.
    pub kind: u8,
    /// `BoneRecord::flags`; bit 0x400 is the fixed-axis flag of an under-IK
    /// bone.
    pub flags: u16,
    /// `BoneRecord::hasRigidBody`.
    pub rigid_body: bool,
}

/// The model-file side of the active model, one entry per bone and morph
/// of the PMM's tables.
#[derive(Clone, Debug)]
pub struct ModelFacts {
    pub bones: Vec<BoneFacts>,
    /// `MorphRecord::type` of each morph: the byte that menus 225, 226, 228
    /// and 231 compare with 3 (lip), 2 (eye) and 1 (eyebrow).
    ///
    /// The C++ reads the field at offset 89, which the PMX loader fills with
    /// the morph kind (0 group, 1 vertex, 2 bone, 3 to 7 UV, 8 material) and
    /// the PMD loader leaves 0. Its comments name offset 0x58 = 88, the
    /// `panel` byte (1 eyebrow, 2 eye, 3 mouth, 4 other), which is what the
    /// menu texts promise. This crate compares whatever bytes it is given;
    /// pass the `type` bytes for the behavior of this C++ port and the `panel`
    /// bytes for the behavior the menus describe.
    pub morph_type: Vec<u8>,
    /// PMX model (`physicsMode == 2`).
    pub pmx: bool,
}

/// The model in the selected slot (`selected_model_slot`), the one every
/// menu command edits.
pub fn active_model(pmm: &Pmm) -> Result<usize> {
    pmm.models
        .iter()
        .position(|m| m.slot == pmm.selected_model_slot)
        .ok_or(Error::NoModel)
}

/// The model's tables must agree with its pools, as the loader makes them.
pub(crate) fn check(m: &Model, facts: &ModelFacts) -> Result<()> {
    let bones = m.bone_keys.heads().len();
    let morphs = m.morph_keys.heads().len();
    let ok = m.bone_names.len() == bones
        && facts.bones.len() == bones
        && m.morph_names.len() == morphs
        && facts.morph_type.len() == morphs
        && m.morph_pose.len() == morphs
        && m.ik_pose.len() == m.ik_bones.len()
        && m.selector_pose.len() == m.selector_bones.len();
    ok.then_some(()).ok_or(Error::Corrupt)
}

fn bone_index(i: i32, bones: usize) -> Result<u32> {
    usize::try_from(i)
        .ok()
        .filter(|&b| b < bones)
        .map(|b| b as u32)
        .ok_or(Error::Corrupt)
}

/// The pools and the rig of one model, for the `mds-edit` operations. The
/// search cursor starts at 0, as every operation resets it before use.
pub(crate) fn open(m: &Model, facts: &ModelFacts) -> Result<(Tracks, Rig)> {
    check(m, facts)?;
    let bones = m.bone_names.len();
    let rig = Rig {
        bones: (0..bones)
            .map(|i| {
                let f = &facts.bones[i];
                let pose = m.bone_pose.get(i);
                BoneInfo {
                    name: m.bone_names[i].raw.clone(),
                    writes_position: f.kind <= 2,
                    twist: f.kind == 8 || (f.kind == 4 && f.flags & 0x400 != 0),
                    rigid_body: f.rigid_body,
                    rotation: pose.map_or([0.0, 0.0, 0.0, 1.0], |p| p.rotation),
                    translation: pose.map_or([0.0; 3], |p| p.translation),
                }
            })
            .collect(),
        morphs: m
            .morph_names
            .iter()
            .zip(&m.morph_pose)
            .map(|(n, &value)| MorphInfo {
                name: n.raw.clone(),
                value,
            })
            .collect(),
        ik_chains: m
            .ik_bones
            .iter()
            .zip(&m.ik_pose)
            .map(|(&b, &enabled)| {
                Ok(IkChain {
                    bone: bone_index(b, bones)?,
                    enabled,
                })
            })
            .collect::<Result<_>>()?,
        selectors: m
            .selector_bones
            .iter()
            .zip(&m.selector_pose)
            .map(|(&b, p)| {
                Ok(Selector {
                    // The root selector (-1) has no bone; mds-edit matches
                    // it against no entry, as the C++ does in practice.
                    bone: if b < 0 {
                        u32::MAX
                    } else {
                        bone_index(b, bones)?
                    },
                    linked_model: p[2],
                    linked_bone: p[3],
                })
            })
            .collect::<Result<_>>()?,
        pmx: facts.pmx,
        load_complete: m.selection.load_complete,
        auto_interpolation: false,
    };
    let tracks = Tracks {
        bone: m.bone_keys.clone(),
        morph: m.morph_keys.clone(),
        display: m.display_keys.clone(),
        search_cursor: 0,
        max_frame: m.selection.max_frame,
    };
    Ok((tracks, rig))
}

/// Writes the pools, the timeline end and the morph weights back.
pub(crate) fn commit(m: &mut Model, tracks: Tracks, rig: &Rig) {
    m.bone_keys = tracks.bone;
    m.morph_keys = tracks.morph;
    m.display_keys = tracks.display;
    m.selection.max_frame = tracks.max_frame;
    for (w, morph) in m.morph_pose.iter_mut().zip(&rig.morphs) {
        *w = morph.value;
    }
}

/// A registrar's error in a loop that goes on after a full pool, as the C++
/// loops do: a full pool is remembered (the first one is returned at the
/// end), any other error ends the operation.
pub(crate) fn soft(first: &mut Result<()>, e: mds_edit::Error) -> Result<()> {
    match e {
        e @ mds_edit::Error::Full { .. } => {
            if first.is_ok() {
                *first = Err(Error::Edit(e));
            }
            Ok(())
        }
        e => Err(Error::Edit(e)),
    }
}
