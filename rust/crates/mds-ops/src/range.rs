//! Frame-range scale (menu 424, the 拡大縮小 button of the timeline).

use crate::model::{active_model, commit, extra, open, soft};
use crate::multiply::truncate;
use crate::pool::{indices, links, read, set_marks, walk_limit, Rec};
use crate::{Error, ModelFacts, Result};
use mds_edit::{BoneClip, BoneTarget, DisplayClip, Extra, MorphClip, Rig, Tracks};
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::Pmm;

/// The fields of the frame-range dialog (`FrameRangeDlgProc`,
/// `src/window/dialog_procs.cpp` 62-108).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RangeScale {
    /// The first frame of the range, from the edit box (`atol`).
    pub start: i32,
    /// The last frame of the range.
    pub end: i32,
    /// The scale (`atof`). Frames in the range stretch by it; frames after
    /// the range move by the change in the range's length.
    pub scale: f64,
    /// The three family check boxes (bone, morph, display/IK/outside parent).
    pub bones: bool,
    pub morphs: bool,
    pub display: bool,
}

/// `ScaledRelativeFrame` (`src/window/frame_range_apply.cpp` 68-76): the
/// product and its truncation stay in single precision, as the x64 SSE code
/// does. Returns the frame relative to `start`, which the registrar adds
/// `start` to.
fn scaled_relative(frame: u32, start: u32, end: u32, scale: f64) -> u32 {
    let f = scale as f32;
    if frame <= end {
        let m = (frame.wrapping_sub(start) as i32 as f32) * f;
        return truncate(m) as u32;
    }
    let m = (end.wrapping_sub(start) as i32 as f32) * f;
    frame.wrapping_add(truncate(m) as u32).wrapping_sub(end)
}

/// The bone or morph whose track holds record `index` (`TrackOwner`): follow
/// `previous` until the index is a head.
fn owner<K: Rec>(pool: &KeyPool<K>, mut index: u32) -> Result<u32> {
    let heads = pool.heads().len() as u32;
    for _ in 0..=walk_limit(pool) {
        if index < heads {
            return Ok(index);
        }
        index = links(pool, index)?.1;
    }
    Err(Error::Corrupt)
}

/// Marks the keys `pred` accepts, clears every other mark of the pool, and
/// returns the marked indices in index order.
fn gather<K: Rec>(pool: &mut KeyPool<K>, pred: impl Fn(u32, &K) -> bool) -> Vec<u32> {
    set_marks(pool, pred);
    indices(pool, |_, k| k.mark() != 0)
}

fn unmark<K: Rec>(pool: &mut KeyPool<K>) {
    set_marks(pool, |_, _| false);
}

#[derive(Clone, Copy)]
enum Family {
    Bone,
    Morph,
    Display,
}

/// One family of `ScaleBoneKeys`, `ScaleMorphKeys` or `ScaleDisplayKeys`.
fn run(
    t: &mut Tracks,
    rig: &Rig,
    extra: &Extra,
    p: &RangeScale,
    first: &mut Result<()>,
    family: Family,
) -> Result<()> {
    let (start, end) = (p.start as u32, p.end as u32);
    let at = start as i32;
    match family {
        Family::Bone => {
            let heads = t.bone.heads().len() as u32;
            let marks = gather(&mut t.bone, |i, k| {
                (k.frame != 0 || i < heads) && k.frame >= start
            });
            if marks.is_empty() {
                return Ok(());
            }
            unmark(&mut t.morph);
            unmark(&mut t.display);
            let clips = marks
                .iter()
                .map(|&i| {
                    let k = read(&t.bone, i)?;
                    Ok(BoneClip {
                        name: rig.bones[owner(&t.bone, i)? as usize].name.clone(),
                        frame: scaled_relative(k.frame, start, end, p.scale),
                        rotation: k.rotation,
                        position: k.position,
                        physics_disabled: k.physics_disabled,
                        interpolation: k.interpolation,
                    })
                })
                .collect::<Result<Vec<_>>>()?;
            t.delete_marked(rig)?;
            t.reset_bone_cursor(rig);
            for clip in &clips {
                if let Err(e) = t.register_bone_key_with(rig, extra, clip, at, BoneTarget::Named) {
                    return soft(first, e);
                }
            }
        }
        Family::Morph => {
            let heads = t.morph.heads().len() as u32;
            let marks = gather(&mut t.morph, |i, k| {
                (k.frame != 0 || i < heads) && k.frame >= start
            });
            if marks.is_empty() {
                return Ok(());
            }
            unmark(&mut t.bone);
            unmark(&mut t.display);
            let clips = marks
                .iter()
                .map(|&i| {
                    let k = read(&t.morph, i)?;
                    Ok(MorphClip {
                        name: rig.morphs[owner(&t.morph, i)? as usize].name.clone(),
                        frame: scaled_relative(k.frame, start, end, p.scale),
                        value: k.value,
                    })
                })
                .collect::<Result<Vec<_>>>()?;
            t.delete_marked(rig)?;
            t.reset_morph_cursor(rig);
            for clip in &clips {
                if let Err(e) = t.register_morph_key(rig, clip, at) {
                    return soft(first, e);
                }
            }
        }
        Family::Display => {
            let marks = gather(&mut t.display, |_, k| k.frame >= start && k.frame != 0);
            if marks.is_empty() {
                return Ok(());
            }
            unmark(&mut t.bone);
            unmark(&mut t.morph);
            let bone_name = |b: u32| -> Result<Vec<u8>> {
                Ok(rig
                    .bones
                    .get(b as usize)
                    .ok_or(Error::Corrupt)?
                    .name
                    .clone())
            };
            let clips = marks
                .iter()
                .map(|&i| {
                    let k = read(&t.display, i)?;
                    let ik = (rig.ik_chains.iter().enumerate())
                        .map(|(n, c)| {
                            Ok((
                                bone_name(c.bone)?,
                                k.ik_enabled.get(n).copied().unwrap_or(1),
                            ))
                        })
                        .collect::<Result<_>>()?;
                    // Selector 0 has no name in the C++ buffer, so it never
                    // matches a selector of the model again.
                    let selectors = (rig.selectors.iter().enumerate())
                        .map(|(n, s)| {
                            let name = if n == 0 {
                                Vec::new()
                            } else {
                                bone_name(s.bone)?
                            };
                            let [model, bone] = k.selectors.get(n).copied().unwrap_or([-1, 0]);
                            Ok((name, model, bone))
                        })
                        .collect::<Result<_>>()?;
                    Ok(DisplayClip {
                        frame: scaled_relative(k.frame, start, end, p.scale) as i32,
                        visible: k.visible,
                        ik,
                        selectors,
                    })
                })
                .collect::<Result<Vec<_>>>()?;
            t.delete_marked(rig)?;
            t.reset_display_cursor();
            for clip in &clips {
                if let Err(e) = t.register_display_key(rig, clip, at) {
                    return soft(first, e);
                }
            }
        }
    }
    Ok(())
}

/// Menu 424, `ApplyFrameRangeScale` (`src/window/frame_range_apply.cpp`
/// 297-340). Rebuilds the selected families of the active model through the
/// registrars: each key at or after `start` is copied, the marked originals
/// are deleted with [`Tracks::delete_marked`], and the copies are registered
/// again with their frames mapped by `ScaledRelativeFrame`. Afterwards
/// `last_registered_frame` rises to the model's `max_frame` (an unsigned
/// comparison, as in the C++).
///
/// The marks are the operation's own: each family clears the other families'
/// marks first, and the bone, morph and display marks are left as the last
/// run family leaves them. A family with no key at or after `start` is
/// skipped. A full pool ends that family only and the first such error is
/// returned at the end; any other error leaves the scene unchanged.
///
/// A fixed-axis bone gets the registrar's twist correction about
/// [`BoneFacts::axis`](crate::BoneFacts::axis).
pub fn scale_frame_range(pmm: &mut Pmm, facts: &ModelFacts, p: &RangeScale) -> Result<()> {
    let m = active_model(pmm)?;
    if p.end.wrapping_sub(p.start) <= 0 {
        return Err(Error::EmptyRange);
    }
    if p.scale < 0.000_009_999_999_7 || p.scale == 1.0 {
        return Err(Error::ScaleOutOfRange);
    }
    let (mut tracks, rig) = open(&pmm.models[m], facts)?;
    let extra = extra(facts);
    let mut first = Ok(());
    for (on, family) in [
        (p.bones, Family::Bone),
        (p.morphs, Family::Morph),
        (p.display, Family::Display),
    ] {
        if on {
            run(&mut tracks, &rig, &extra, p, &mut first, family)?;
        }
    }
    let max = tracks.max_frame;
    commit(&mut pmm.models[m], tracks, &rig);
    if (pmm.timeline.last_registered_frame as u32) < max {
        pmm.timeline.last_registered_frame = max as i32;
    }
    first
}
