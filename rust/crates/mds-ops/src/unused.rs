//! Unused-key removal (menu 222).

use crate::model::{active_model, commit, open};
use crate::pool::{links, read, slot, walk_limit, Rec};
use crate::{Error, ModelFacts, Result};
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{BoneKey, DisplayKey, Pmm};

/// `SamePose` (`src/model/model_key_reduction.cpp` 5-11): position and
/// rotation compare as floats, so `-0.0 == 0.0` and a NaN equals nothing.
fn same_pose(a: &BoneKey, b: &BoneKey) -> bool {
    a.position == b.position && a.rotation == b.rotation
}

/// The IK flags and outside-parent selectors of two display keys, over the
/// first `iks` and `selectors` entries.
fn same_display(a: &DisplayKey, b: &DisplayKey, iks: usize, selectors: usize) -> bool {
    let ik = |k: &DisplayKey, i: usize| k.ik_enabled.get(i).copied().unwrap_or(1);
    let sel = |k: &DisplayKey, i: usize| k.selectors.get(i).copied().unwrap_or([-1, 0]);
    a.visible == b.visible
        && (0..iks).all(|i| ik(a, i) == ik(b, i))
        && (0..selectors).all(|i| sel(a, i) == sel(b, i))
}

/// The walk of `MarkRedundantModelKeys` along one track: every key that has
/// a successor and equals both neighbours is marked. The first key is
/// compared with the head, the last key is never a candidate.
fn mark_track<K: Rec>(
    pool: &mut KeyPool<K>,
    head: u32,
    same: impl Fn(&K, &K) -> bool,
) -> Result<u32> {
    let mut current = links(pool, head)?.2;
    if current == 0 {
        return Ok(0);
    }
    let mut marked = 0;
    let mut next = links(pool, current)?.2;
    for _ in 0..=walk_limit(pool) {
        if next == 0 {
            return Ok(marked);
        }
        let previous = links(pool, current)?.1;
        let key = read(pool, current)?;
        if same(&key, &read(pool, previous)?) && same(&key, &read(pool, next)?) {
            marked += 1;
            slot(pool, current)?.set_mark(1);
        }
        current = links(pool, current)?.2;
        next = links(pool, current)?.2;
    }
    Err(Error::Corrupt)
}

/// Menu 222, delete unused frames (`src/window/command_file_menu.cpp`
/// 1118-1145 and `MarkRedundantModelKeys`, `model_key_reduction.cpp`
/// 15-103): clears every mark of the model's three pools, marks each
/// interior key whose pose, weight or display state equals both of its
/// neighbours' (bones of type 6 and 7 are skipped), and deletes the marked
/// keys with [`mds_edit::Tracks::delete_marked`]. Returns the number of
/// keys marked, which the message box reports. Marking finishes before any
/// deletion, so neighbours are compared as they were.
pub fn remove_unused_keys(pmm: &mut Pmm, facts: &ModelFacts) -> Result<u32> {
    if pmm.settings.options[0] != 0 {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    let (mut tracks, rig) = open(&pmm.models[m], facts)?;
    tracks.clear_marks();
    let mut deleted = 0;
    for (bone, f) in facts.bones.iter().enumerate() {
        if f.kind != 6 && f.kind != 7 {
            deleted += mark_track(&mut tracks.bone, bone as u32, same_pose)?;
        }
    }
    for morph in 0..rig.morphs.len() as u32 {
        deleted += mark_track(&mut tracks.morph, morph, |a, b| a.value == b.value)?;
    }
    let (iks, selectors) = (rig.ik_chains.len(), rig.selectors.len());
    deleted += mark_track(&mut tracks.display, 0, |a, b| {
        same_display(a, b, iks, selectors)
    })?;
    tracks.delete_marked(&rig)?;
    commit(&mut pmm.models[m], tracks, &rig);
    Ok(deleted)
}
