//! The facial menus: lip frame shift, delete all lip / eye / eyebrow
//! frames, reset all morphs, and register all facial frames (menus 225,
//! 226, 228, 230, 229, 231).

use crate::model::{active_model, check, commit, open, soft};
use crate::pool::{atomic, links, slot, walk_limit};
use crate::{Error, ModelFacts, Result};
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{MorphKey, Pmm};

fn camera_mode(pmm: &Pmm) -> bool {
    pmm.settings.options[0] != 0
}

/// A morph record with no key: the fields every facial clear writes.
fn zero_key(k: &mut MorphKey) {
    k.frame = 0;
    k.next = 0;
    k.previous = 0;
    k.allocated = 0;
    k.value = 0.0;
}

fn typed_morphs(facts: &ModelFacts, kind: u8) -> impl Iterator<Item = u32> + '_ {
    facts
        .morph_type
        .iter()
        .enumerate()
        .filter(move |(_, &t)| t == kind)
        .map(|(m, _)| m as u32)
}

/// The shift loop of menu 225 for the track of morph `m`.
fn shift_track(pool: &mut KeyPool<MorphKey>, m: u32, shift: i32) -> Result<()> {
    let mut cur = links(pool, m)?.2;
    if cur == 0 {
        return Ok(());
    }
    for _ in 0..=walk_limit(pool) {
        let next = links(pool, cur)?.2;
        if next != 0 {
            if cur == m {
                cur = next;
                continue;
            }
            let v = (links(pool, cur)?.0 as i32).wrapping_add(shift);
            slot(pool, cur)?.frame = v as u32;
            if v > 0 {
                cur = next;
                continue;
            }
            // Dropped: the head skips the key, and the key that follows keeps
            // its `previous` pointing at the cleared record.
            slot(pool, m)?.next = next;
            zero_key(slot(pool, cur)?);
            cur = next;
            continue;
        }
        if cur == m {
            return Ok(());
        }
        let v = (links(pool, cur)?.0 as i32).wrapping_add(shift);
        slot(pool, cur)?.frame = v as u32;
        if v > 0 {
            return Ok(());
        }
        slot(pool, m)?.next = next;
        zero_key(slot(pool, cur)?);
        return Ok(());
    }
    Err(Error::Corrupt)
}

/// Menu 225, the shift loop of `CmdFileMenu` (`src/window/command_file_menu.cpp`
/// 1242-1321): for every lip morph (`MorphRecord::type == 3`), every key of
/// its track moves by `shift` frames, and a key whose new frame is not
/// positive is dropped. The dialog supplies `shift` (`MorphFrameShift`).
///
/// A dropped key is skipped by the head only: the next key's `previous` is
/// not rewritten, so after a drop [`KeyPool::validate_tracks`] reports that
/// key's `previous`. The C++ does the same.
pub fn shift_lip_frames(pmm: &mut Pmm, facts: &ModelFacts, shift: i32) -> Result<()> {
    if camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    check(&pmm.models[m], facts)?;
    atomic(&mut pmm.models[m].morph_keys, |p| {
        typed_morphs(facts, 3).try_for_each(|morph| shift_track(p, morph, shift))
    })
}

/// `PurgeMorphFrames` (`command_file_menu.cpp` 372-411). Every key of the
/// track is cleared except the last one, which stays with its frame, its
/// `previous` and its value although no head reaches it any more: the head's
/// `next` is 0 after the first step. A track with one key keeps that key.
/// [`KeyPool::validate_tracks`] reports the survivor as on no track.
fn purge_type(pmm: &mut Pmm, facts: &ModelFacts, kind: u8) -> Result<()> {
    if camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    check(&pmm.models[m], facts)?;
    atomic(&mut pmm.models[m].morph_keys, |p| {
        for morph in typed_morphs(facts, kind) {
            let mut cur = morph;
            if links(p, morph)?.2 != 0 {
                let mut steps = 0;
                loop {
                    let k = slot(p, cur)?;
                    let next = k.next;
                    k.frame = 0;
                    k.previous = 0;
                    k.allocated = 0;
                    k.value = 0.0;
                    slot(p, morph)?.next = 0;
                    cur = next;
                    if links(p, cur)?.2 == 0 {
                        break;
                    }
                    steps += 1;
                    if steps > walk_limit(p) {
                        return Err(Error::Corrupt);
                    }
                }
            }
            let k = slot(p, morph)?;
            k.frame = 0;
            k.previous = 0;
            k.allocated = 0;
            k.value = 0.0;
        }
        Ok(())
    })
}

/// Menu 226, delete all lip frames: `PurgeMorphFrames(app, 3)`
/// (`command_file_menu.cpp` 1323-1347). The confirmation box is the
/// caller's.
pub fn delete_lip_frames(pmm: &mut Pmm, facts: &ModelFacts) -> Result<()> {
    purge_type(pmm, facts, 3)
}

/// Menu 228, delete all eye frames: `PurgeMorphFrames(app, 2)`
/// (`command_file_menu.cpp` 1440-1465).
pub fn delete_eye_frames(pmm: &mut Pmm, facts: &ModelFacts) -> Result<()> {
    purge_type(pmm, facts, 2)
}

/// Menu 231, delete all eyebrow frames: `PurgeMorphFrames(app, 1)`
/// (`command_file_menu.cpp` 1737-1765).
pub fn delete_eyebrow_frames(pmm: &mut Pmm, facts: &ModelFacts) -> Result<()> {
    purge_type(pmm, facts, 1)
}

/// Menu 230, reset all morphs (`command_file_menu.cpp` 1709-1735): every
/// morph weight of the model becomes 0. Only the live weights change; no
/// key does.
pub fn reset_morphs(pmm: &mut Pmm) -> Result<()> {
    if camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    pmm.models[m].morph_pose.fill(0.0);
    Ok(())
}

/// Menu 229, register all facial frames (`command_file_menu.cpp`
/// 1654-1707). Clears every mark of the three pools, then registers the
/// live weight of each morph at the current frame with
/// `RegisterMorphKeyCurrent` and raises `last_registered_frame` to the
/// model's `max_frame` after each one. A full pool does not stop the loop,
/// as in the original; the first error is returned at the end. Morph 0 is
/// registered only on a PMX model.
pub fn register_all_morph_frames(pmm: &mut Pmm, facts: &ModelFacts) -> Result<()> {
    if camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    let frame = pmm.timeline.current_frame as u32;
    let (mut tracks, rig) = open(&pmm.models[m], facts)?;
    tracks.clear_marks();
    let mut last = pmm.timeline.last_registered_frame;
    let mut first = Ok(());
    for morph in 0..rig.morphs.len() as i32 {
        if let Err(e) = tracks.register_morph_current(&rig, morph, frame) {
            soft(&mut first, e)?;
        }
        last = last.max(tracks.max_frame as i32);
    }
    commit(&mut pmm.models[m], tracks, &rig);
    pmm.timeline.last_registered_frame = last;
    first
}
