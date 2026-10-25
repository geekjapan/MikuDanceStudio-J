//! Frame-line insert and delete (menus 255 to 258). "Insert" shifts every
//! key at or after the current frame up by one; "delete" unlinks the keys
//! at the current frame and shifts every later key down by one, merging a
//! key that lands on frame 0 into its predecessor record.
//!
//! The bone and facial variants edit the active model, the camera and light
//! variants the global track, by the edit mode (`settings.options[0]`). The
//! bone variants return the records their undo entry holds ([`BoneUndo`]).
//! The automatic-interpolation checkbox is taken as clear, so the
//! interpolation rebuild of the bone delete does not run; the caller refuses
//! a delete that would reach it (`mds-edit` keeps `RebuildBoneInterpolation`
//! private).

use crate::model::active_model;
use crate::pool::{atomic, indices, links, read, record_indices, slot, unlink, Rec};
use crate::Result;
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{BoneKey, CameraKey, LightKey, MorphKey, Pmm};
use std::collections::BTreeMap;

/// The bone records `AppendBoneKeyToUndo` captured, by index, each as it was
/// at its first capture (`None`: never used). `None` instead of a list: no
/// key moved, and the C++ returns before the undo entry and the seek.
pub type BoneUndo = Option<Vec<(u32, Option<BoneKey>)>>;

/// `AppendBoneKeyToUndo`: the first capture of an index wins.
type Touch<'a, K> = &'a mut dyn FnMut(&KeyPool<K>, u32);

fn capture(map: &mut BTreeMap<u32, Option<BoneKey>>) -> impl FnMut(&KeyPool<BoneKey>, u32) + '_ {
    |pool, i| {
        map.entry(i).or_insert_with(|| pool.get(i).cloned());
    }
}

fn camera_mode(pmm: &Pmm) -> bool {
    pmm.settings.options[0] != 0
}

/// The current frame as the C++ reads it: an unsigned copy of the int.
fn current(pmm: &Pmm) -> u32 {
    pmm.timeline.current_frame as u32
}

/// Shifts every key of `which` at or after `frame` up by one. `bump` sees
/// each new frame (the timeline end of the model or of the scene).
fn insert_line<K: Rec>(
    pool: &mut KeyPool<K>,
    which: Vec<u32>,
    frame: u32,
    touch: Touch<K>,
    mut bump: impl FnMut(u32),
) -> Result<()> {
    for i in which {
        let key_frame = links(pool, i)?.0;
        if key_frame != 0 && key_frame >= frame {
            touch(pool, i);
            slot(pool, i)?.set_frame(key_frame.wrapping_add(1));
            bump(key_frame.wrapping_add(1));
        }
    }
    Ok(())
}

/// What differs between the four delete loops: the fields a removed record
/// loses, and the fields a record merged into its predecessor carries over.
struct Delete<K> {
    /// The record at the current frame, after its neighbours are relinked.
    clear: fn(&mut K),
    /// The key that shifted onto frame 0, after its payload moved to `dst`.
    merged: fn(&mut K),
    copy: fn(dst: &mut K, src: &K),
}

/// The automatic curve rebuild of a key's neighbour, `next` when there is
/// one, else `previous` (the bone variant with checkbox 530 on).
type Rebuild<'a, K> = &'a mut dyn FnMut(&mut KeyPool<K>, u32) -> Result<()>;

fn delete_line<K: Rec>(
    pool: &mut KeyPool<K>,
    which: Vec<u32>,
    frame: u32,
    touch: Touch<K>,
    d: &Delete<K>,
    rebuild: Rebuild<K>,
) -> Result<()> {
    for i in which {
        let (key_frame, prev, next) = links(pool, i)?;
        if key_frame != 0 && key_frame == frame {
            for j in [prev, i, next] {
                touch(pool, j);
            }
            unlink(pool, prev, next)?;
            (d.clear)(slot(pool, i)?);
            rebuild(pool, if next != 0 { next } else { prev })?;
            continue;
        }
        if key_frame != 0 && frame < key_frame {
            touch(pool, i);
            let shifted = key_frame - 1;
            slot(pool, i)?.set_frame(shifted);
            if shifted == 0 {
                let src = read(pool, i)?;
                let dst = slot(pool, prev)?;
                dst.set_next(src.next());
                (d.copy)(dst, &src);
                if src.next() != 0 {
                    slot(pool, src.next())?.set_previous(prev);
                }
                rebuild(pool, if src.next() != 0 { src.next() } else { prev })?;
                (d.merged)(slot(pool, i)?);
            }
        }
    }
    Ok(())
}

fn clear_bone(k: &mut BoneKey) {
    k.frame = 0;
    k.allocated = 0;
    k.position = [0.0; 3];
    k.rotation = [0.0, 0.0, 0.0, 1.0];
}

/// Menu 255, `InsertBoneCameraFrameLine` (`src/window/frame_line_edit.cpp`
/// 184-249). Bone mode shifts the non-head bone keys (`i >= boneCount`) and
/// raises the model's `max_frame` to the largest new frame; camera mode
/// shifts the camera track and raises `last_registered_frame` (and has no
/// undo: `Ok(None)`).
pub fn insert_bone_camera_frame_line(pmm: &mut Pmm) -> Result<BoneUndo> {
    let frame = current(pmm);
    if !camera_mode(pmm) {
        let m = active_model(pmm)?;
        let model = &mut pmm.models[m];
        let mut max = model.selection.max_frame;
        let which = record_indices(&model.bone_keys, |_| true);
        let mut undo = BTreeMap::new();
        atomic(&mut model.bone_keys, |p| {
            insert_line(p, which, frame, &mut capture(&mut undo), |new| {
                if (max as i32) < new as i32 {
                    max = new;
                }
            })
        })?;
        model.selection.max_frame = max;
        return Ok((!undo.is_empty()).then(|| undo.into_iter().collect()));
    }
    let mut last = pmm.timeline.last_registered_frame;
    let which = indices(&pmm.camera, |_, _| true);
    atomic(&mut pmm.camera, |p| {
        insert_line(p, which, frame, &mut |_, _| {}, |new| {
            if last < new as i32 {
                last = new as i32;
            }
        })
    })?;
    pmm.timeline.last_registered_frame = last;
    Ok(None)
}

/// Menu 257, `InsertFacialLightFrameLine` (`frame_line_edit.cpp` 392-432).
/// Edit mode 0 shifts the non-head morph keys of the model; the other mode
/// shifts the light track and raises `last_registered_frame`.
pub fn insert_morph_light_frame_line(pmm: &mut Pmm) -> Result<()> {
    let frame = current(pmm);
    if camera_mode(pmm) {
        let mut last = pmm.timeline.last_registered_frame;
        let which = indices(&pmm.light, |_, _| true);
        atomic(&mut pmm.light, |p| {
            insert_line(p, which, frame, &mut |_, _| {}, |new| {
                if last < new as i32 {
                    last = new as i32;
                }
            })
        })?;
        pmm.timeline.last_registered_frame = last;
        return Ok(());
    }
    let m = active_model(pmm)?;
    let model = &mut pmm.models[m];
    let mut max = model.selection.max_frame;
    let which = record_indices(&model.morph_keys, |_| true);
    atomic(&mut model.morph_keys, |p| {
        insert_line(p, which, frame, &mut |_, _| {}, |new| {
            if (max as i32) < new as i32 {
                max = new;
            }
        })
    })?;
    model.selection.max_frame = max;
    Ok(())
}

/// Menu 256, `DeleteBoneCameraFrameLine` (`frame_line_edit.cpp` 252-389).
///
/// A removed bone key loses its frame, mark, position and rotation (the
/// physics byte stays) and then both links; a key shifted onto frame 0 gives
/// its curves, position, rotation and mark to the head, and keeps its links.
/// A removed camera key loses its links, frame, perspective, distance, fov,
/// the x and y of eye and target, the first four bytes of each curve row,
/// and its mark; its eye z, target z and parent stay. A camera key shifted
/// onto frame 0 gives the head its distance, eye, target, curves,
/// perspective and fov. The camera variant has no undo (`Ok(None)`).
///
/// With `auto_interpolation` (checkbox 530, `frame_line_edit.cpp` 288-290)
/// the curves of the neighbour of each removed or merged bone key are rebuilt
/// with `RebuildBoneInterpolation` ([`mds_edit::rebuild_interpolation`]),
/// all four lanes, as the key is processed; the rig names the model's bones.
pub fn delete_bone_camera_frame_line(
    pmm: &mut Pmm,
    auto_interpolation: Option<&mds_edit::Rig>,
) -> Result<BoneUndo> {
    let frame = current(pmm);
    if !camera_mode(pmm) {
        let m = active_model(pmm)?;
        let pool = &mut pmm.models[m].bone_keys;
        let which = record_indices(pool, |_| true);
        let mut undo = BTreeMap::new();
        atomic(pool, |p| {
            delete_line(
                p,
                which,
                frame,
                &mut capture(&mut undo),
                &Delete {
                    clear: |k: &mut BoneKey| {
                        clear_bone(k);
                        k.next = 0;
                        k.previous = 0;
                    },
                    merged: clear_bone,
                    copy: |dst, src| {
                        dst.interpolation = src.interpolation;
                        dst.position = src.position;
                        dst.rotation = src.rotation;
                        dst.allocated = src.allocated;
                    },
                },
                &mut |p, at| {
                    if let Some(rig) = auto_interpolation {
                        for lane in 0..4 {
                            mds_edit::rebuild_interpolation(p, rig, at, lane)?;
                        }
                    }
                    Ok(())
                },
            )
        })?;
        return Ok((!undo.is_empty()).then(|| undo.into_iter().collect()));
    }
    let which = indices(&pmm.camera, |_, _| true);
    atomic(&mut pmm.camera, |p| {
        delete_line(
            p,
            which,
            frame,
            &mut |_, _| {},
            &Delete {
                clear: |k: &mut CameraKey| {
                    k.next = 0;
                    k.previous = 0;
                    k.frame = 0;
                    k.perspective = 0;
                    k.distance = 0.0;
                    k.fov = 0;
                    k.eye[..2].fill(0.0);
                    k.target[..2].fill(0.0);
                    k.interpolation.iter_mut().for_each(|row| row[..4].fill(0));
                    k.selected = 0;
                },
                merged: |_| {},
                copy: |dst, src| {
                    dst.distance = src.distance;
                    dst.eye = src.eye;
                    dst.target = src.target;
                    for (d, s) in dst.interpolation.iter_mut().zip(&src.interpolation) {
                        d[..4].copy_from_slice(&s[..4]);
                    }
                    dst.perspective = src.perspective;
                    dst.fov = src.fov;
                },
            },
            &mut |_, _| Ok(()),
        )
    })?;
    Ok(None)
}

/// Menu 258, `DeleteFacialLightFrameLine` (`frame_line_edit.cpp` 435-526).
///
/// A removed morph key loses frame, mark, value and links; a morph key
/// shifted onto frame 0 gives its mark and value to the head and keeps its
/// links. A removed light key loses links, frame and mark but keeps its
/// color and direction; a light key shifted onto frame 0 gives the head its
/// direction and color.
pub fn delete_morph_light_frame_line(pmm: &mut Pmm) -> Result<()> {
    let frame = current(pmm);
    if camera_mode(pmm) {
        let which = indices(&pmm.light, |_, _| true);
        return atomic(&mut pmm.light, |p| {
            delete_line(
                p,
                which,
                frame,
                &mut |_, _| {},
                &Delete {
                    clear: |k: &mut LightKey| {
                        k.next = 0;
                        k.previous = 0;
                        k.frame = 0;
                        k.selected = 0;
                    },
                    merged: |_| {},
                    copy: |dst, src| {
                        dst.direction = src.direction;
                        dst.color = src.color;
                    },
                },
                &mut |_, _| Ok(()),
            )
        });
    }
    let m = active_model(pmm)?;
    let pool = &mut pmm.models[m].morph_keys;
    let which = record_indices(pool, |_| true);
    atomic(pool, |p| {
        delete_line(
            p,
            which,
            frame,
            &mut |_, _| {},
            &Delete {
                clear: |k: &mut MorphKey| {
                    k.frame = 0;
                    k.allocated = 0;
                    k.value = 0.0;
                    k.next = 0;
                    k.previous = 0;
                },
                merged: |_| {},
                copy: |dst, src| {
                    dst.allocated = src.allocated;
                    dst.value = src.value;
                },
            },
            &mut |_, _| Ok(()),
        )
    })
}
