//! Key application of the x64 app: `SeekModelFrame`
//! (`src/model/model_frame_seek.cpp`), `InitModelTrackCursors` and
//! `AdvanceModelKeyframes` (`src/model/model_keyframe_advance.cpp`), with the
//! shared selector refresh of `src/model/keyframe_common.hpp`.
//!
//! The transcendentals are the UCRT `acosf` and `sinf` (`mds_crtmath`); the
//! arithmetic is single precision, as in the x64 build. Physics modes 2 and
//! 3 (the rigid-body arming branches) are not ported; `Scene` rejects them.

use crate::model::{kind, Bone, Model, Selector};
use mds_crtmath::{acosf, sinf};
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{BoneKey, DisplayKey};

const QUAT_CLAMP: f32 = 0.999_999;
/// `0x3FC90FD8`, pi/2 from the truncated float pi.
const HALF_PI: f32 = f32::from_bits(0x3fc9_0fd8);
/// `0x3CC182ED`, 3/127 as stored.
const CP_SCALE: f32 = f32::from_bits(0x3cc1_82ed);

pub(crate) fn key<K: mds_formats::key_pool::Key>(pool: &KeyPool<K>, index: u32) -> &K {
    pool.get(index)
        .unwrap_or_else(|| panic!("key record {index} is not in the pool"))
}

/// `BoneEase` (x64 `sub_7FF7CB4EDB00`): the VMD curve of `channel` at `t`.
pub fn bone_ease(rec: &BoneKey, channel: usize, t: f32) -> f32 {
    let ip = &rec.interpolation;
    let (x1, y1, x2, y2) = (
        ip[channel],
        ip[channel + 4],
        ip[channel + 8],
        ip[channel + 12],
    );
    if x2 == y2 && x1 == y1 {
        return t;
    }
    let x1c = f32::from(x1 as i8) * CP_SCALE;
    let x2c = f32::from(x2 as i8) * CP_SCALE;
    let y1b = f32::from(y1 as i8);
    let y2b = f32::from(y2 as i8);
    let mut u = 0.5f32;
    let mut step = 0.5f32;
    for _ in 0..12 {
        let om = 1.0 - u;
        let gx = (om * om * u) * x1c + (om * u * u) * x2c + u * u * u;
        if gx == t {
            break;
        }
        step *= 0.5;
        u = if gx >= t { u - step } else { u + step };
    }
    let om = 1.0 - u;
    (om * om * u) * y1b * CP_SCALE + (om * u * u) * y2b * CP_SCALE + u * u * u
}

fn same(s: &Selector, pair: [i32; 2]) -> bool {
    s.linked_bone == pair[1] && s.linked_model == pair[0]
}

/// `kfa::RefreshIkSelectors`.
fn refresh_selectors(
    selectors: &mut [Selector],
    keys: &KeyPool<DisplayKey>,
    pair_idx: u32,
    back_start: u32,
    with_forward: bool,
    fwd_start: u32,
    fwd_pair_idx: u32,
) {
    for (i, selector) in selectors.iter_mut().enumerate() {
        let pair = key(keys, pair_idx).selectors[i];
        selector.linked_model = pair[0];
        selector.linked_bone = pair[1];
        let mut walk = back_start;
        loop {
            let wrec = key(keys, walk);
            if wrec.frame == 0 {
                selector.window_start = 0;
                break;
            }
            let prev = wrec.previous;
            if same(selector, key(keys, prev).selectors[i]) {
                walk = prev;
                continue;
            }
            selector.window_start = key(keys, key(keys, prev).next).frame;
            break;
        }
        if !with_forward {
            selector.window_end = 0;
            continue;
        }
        if same(selector, key(keys, fwd_pair_idx).selectors[i]) {
            let mut f = fwd_start;
            let mut to_end = false;
            loop {
                let next = key(keys, f).next;
                if next == 0 {
                    to_end = true;
                    break;
                }
                f = next;
                if !same(selector, key(keys, f).selectors[i]) {
                    break;
                }
            }
            selector.window_end = if to_end { 0 } else { key(keys, f).frame };
        } else {
            selector.window_end = key(keys, fwd_start).frame;
        }
    }
}

/// `CopyIkDisplayFlags` then `RefreshIkSelectors`.
fn apply_display(model: &mut Model, flags_idx: u32, refresh: [u32; 4], with_forward: bool) {
    let flags = &key(&model.display_keys, flags_idx).ik_enabled;
    for (ik, &on) in model.iks.iter_mut().zip(flags) {
        ik.enabled = u8::from(on == 1);
    }
    refresh_selectors(
        &mut model.selectors,
        &model.display_keys,
        refresh[0],
        refresh[1],
        with_forward,
        refresh[2],
        refresh[3],
    );
}

fn copy_key(bone: &mut Bone, rec: &BoneKey) {
    bone.rot_quat = rec.rotation;
    bone.trans = rec.position;
}

/// The seek slerp (`InterpolateSeekRotation`, x64): weights `sin / s`.
fn seek_slerp(pq: [f32; 4], cq: [f32; 4], t: f32) -> [f32; 4] {
    let dot = pq[0] * cq[0] + pq[1] * cq[1] + pq[2] * cq[2] + pq[3] * cq[3];
    if 1.0 - dot * dot == 0.0 {
        return pq;
    }
    let dc = clamp_dot(dot);
    let angle = acosf(dc);
    if angle > HALF_PI && dc < 0.0 {
        let short = acosf(-dc);
        let s = sinf(short);
        let w0 = sinf((1.0 - t) * short) / s;
        let w1 = sinf(t * short) / s;
        std::array::from_fn(|c| pq[c] * w0 - w1 * cq[c])
    } else {
        let s = sinf(angle);
        let w0 = sinf((1.0 - t) * angle) / s;
        let w1 = sinf(t * angle) / s;
        std::array::from_fn(|c| pq[c] * w0 + w1 * cq[c])
    }
}

/// The advance slerp (x64 `0x7FF7CB4F1D91`): weights `sin * (1 / s)`.
fn advance_slerp(pq: [f32; 4], cq: [f32; 4], t: f32) -> [f32; 4] {
    let dot = pq[0] * cq[0] + pq[1] * cq[1] + pq[2] * cq[2] + pq[3] * cq[3];
    if 1.0 - dot * dot == 0.0 {
        return pq;
    }
    let dc = clamp_dot(dot);
    let th = acosf(dc);
    if th > HALF_PI && dc < 0.0 {
        let th2 = acosf(-dc);
        let inv = 1.0 / sinf(th2);
        let w0 = sinf((1.0 - t) * th2) * inv;
        let w1 = sinf(t * th2) * inv;
        std::array::from_fn(|c| pq[c] * w0 - w1 * cq[c])
    } else {
        let inv = 1.0 / sinf(th);
        let w0 = sinf((1.0 - t) * th) * inv;
        let w1 = sinf(t * th) * inv;
        std::array::from_fn(|c| pq[c] * w0 + w1 * cq[c])
    }
}

fn clamp_dot(dot: f32) -> f32 {
    if dot > 1.0 {
        QUAT_CLAMP
    } else if dot < -1.0 {
        -QUAT_CLAMP
    } else {
        dot
    }
}

/// The signed type test of the seek and the position easing: types up to
/// 6 and 8.
fn keyed_type(bone: &Bone) -> bool {
    (bone.kind as i8) <= kind::EFFECTOR as i8 || bone.kind == kind::FIXED_AXIS
}

/// `SeekModelFrame` at integer `frame`.
pub fn seek_model_frame(model: &mut Model, frame: u32) {
    // SeekDisplayTrack
    let keys = &model.display_keys;
    let mut found = 0u32;
    let mut resolved = true;
    if key(keys, 0).frame < frame {
        resolved = false;
        loop {
            let next = key(keys, found).next;
            if next == 0 {
                break;
            }
            found = next;
            if key(keys, found).frame >= frame {
                resolved = true;
                break;
            }
        }
        if !resolved {
            apply_display(model, found, [found, found, 0, 0], false);
        }
    }
    if resolved {
        if key(&model.display_keys, found).frame == frame {
            apply_display(model, found, [found, found, found, found], true);
        } else {
            let prev = key(&model.display_keys, found).previous;
            apply_display(model, prev, [prev, prev, found, found], true);
        }
    }

    // SeekMorphTracks
    let keys = &model.morph_keys;
    for (k, morph) in model.morphs.iter_mut().enumerate() {
        let mut found = k as u32;
        if key(keys, found).frame < frame {
            let mut resolved = false;
            loop {
                let next = key(keys, found).next;
                if next == 0 {
                    break;
                }
                found = next;
                if key(keys, found).frame >= frame {
                    resolved = true;
                    break;
                }
            }
            if !resolved {
                morph.value = key(keys, found).value;
                continue;
            }
        }
        let rec = key(keys, found);
        morph.value = if rec.frame == frame {
            rec.value
        } else {
            let prev = key(keys, rec.previous);
            let t = (frame - prev.frame) as f32 / (rec.frame as i32 - prev.frame as i32) as f32;
            t * (rec.value - prev.value) + prev.value
        };
    }

    // SeekBoneFrame per keyed bone
    let keys = &model.bone_keys;
    for (b, bone) in model.bones.iter_mut().enumerate() {
        if !keyed_type(bone) {
            continue;
        }
        let mut found = b as u32;
        if key(keys, found).frame < frame {
            let mut resolved = false;
            loop {
                let next = key(keys, found).next;
                if next == 0 {
                    break;
                }
                found = next;
                if key(keys, found).frame >= frame {
                    resolved = true;
                    break;
                }
            }
            if !resolved {
                let rec = key(keys, found);
                copy_key(bone, rec);
                if let Ok(s) = usize::try_from(bone.slot_index) {
                    let start = model.selectors[s].window_start;
                    if rec.frame < start && start <= frame {
                        bone.trans = [0.0; 3];
                        bone.rot_quat = [0.0, 0.0, 0.0, 1.0];
                    }
                }
                continue;
            }
        }
        let rec = key(keys, found);
        let cur_frame = rec.frame;
        if cur_frame == frame {
            copy_key(bone, rec);
            continue;
        }
        let prev = key(keys, rec.previous);
        let prev_frame = prev.frame;
        if let Ok(s) = usize::try_from(bone.slot_index) {
            let w = &model.selectors[s];
            let snap = if w.window_start < cur_frame && prev_frame < w.window_start {
                Some(w.window_start)
            } else if !(cur_frame < w.window_end || prev_frame >= w.window_end) {
                Some(w.window_end)
            } else {
                None
            };
            if let Some(at) = snap {
                copy_key(bone, if frame >= at { rec } else { prev });
                continue;
            }
        }
        let t = (frame - prev_frame) as f32 / (cur_frame as i32 - prev_frame as i32) as f32;
        bone.rot_quat = seek_slerp(prev.rotation, rec.rotation, bone_ease(rec, 3, t));
        for axis in 0..3 {
            let delta = rec.position[axis] - prev.position[axis];
            bone.trans[axis] = if delta == 0.0 {
                prev.position[axis]
            } else {
                bone_ease(rec, axis, t) * delta + prev.position[axis]
            };
        }
    }
}

/// `InitModelTrackCursors` at `cursor` seconds.
pub fn init_track_cursors(model: &mut Model, cursor: f32) {
    let frame = f64::from(cursor) * 30.0;
    model.display_active = true;
    model.display_cursor = 0;
    if f64::from(key(&model.display_keys, 0).frame) < frame {
        loop {
            let cur = model.display_cursor;
            let next = key(&model.display_keys, cur).next;
            if next == 0 {
                model.display_active = false;
                apply_display(model, cur, [cur, cur, 0, 0], false);
                break;
            }
            model.display_cursor = next;
            if f64::from(key(&model.display_keys, next).frame) >= frame {
                break;
            }
        }
    }

    let keys = &model.morph_keys;
    for (k, morph) in model.morphs.iter_mut().enumerate() {
        let c = &mut model.morph_cursors;
        c.active[k] = true;
        c.index[k] = k as u32;
        loop {
            let rec = key(keys, c.index[k]);
            if f64::from(rec.frame) >= frame {
                break;
            }
            if rec.next != 0 {
                c.index[k] = rec.next;
                continue;
            }
            c.active[k] = false;
            morph.value = rec.value;
            break;
        }
    }

    let keys = &model.bone_keys;
    for (b, bone) in model.bones.iter_mut().enumerate() {
        let c = &mut model.bone_cursors;
        c.active[b] = true;
        if bone.kind == kind::INERT_TIP {
            c.active[b] = false;
            continue;
        }
        c.index[b] = b as u32;
        loop {
            let rec = key(keys, c.index[b]);
            if f64::from(rec.frame) >= frame {
                break;
            }
            if rec.next != 0 {
                c.index[b] = rec.next;
                continue;
            }
            c.active[b] = false;
            copy_key(bone, rec);
            break;
        }
        if bone.has_rigid_body != 0 {
            bone.physics_disabled = key(keys, c.index[b]).physics_disabled;
        }
    }
}

/// The frame of `cursor` seconds: `cursor * 30` rounded up to 1/1000 when
/// the thousandths fraction is at least one half.
pub fn cursor_frame(cursor: f32) -> f64 {
    let frame = f64::from(cursor) * 30.0;
    let scaled = frame * 1000.0;
    if scaled - f64::from(scaled as i32) >= 0.5 {
        f64::from(scaled as i32 + 1) / 1000.0
    } else {
        frame
    }
}

/// `AdvanceModelKeyframes` at `cursor` seconds, physics mode 0 or 1.
pub fn advance_model_keyframes(model: &mut Model, cursor: f32) {
    let frame = cursor_frame(cursor);
    let frame_f = frame as f32;

    // Section 1: the IK and outside-parent track.
    if model.display_active {
        while f64::from(key(&model.display_keys, model.display_cursor).frame) < frame
            && model.display_active
        {
            let cur = model.display_cursor;
            let next = key(&model.display_keys, cur).next;
            if next != 0 {
                model.display_cursor = next;
                continue;
            }
            model.display_active = false;
            apply_display(model, cur, [cur, cur, 0, 0], false);
        }
        if model.display_active {
            let cur = model.display_cursor;
            let rec = key(&model.display_keys, cur);
            if frame == f64::from(rec.frame) {
                apply_display(model, cur, [cur, cur, cur, cur], true);
            } else {
                let prev = rec.previous;
                apply_display(model, prev, [prev, prev, cur, cur], true);
            }
        }
    }

    // Section 2: morph tracks.
    let keys = &model.morph_keys;
    let c = &mut model.morph_cursors;
    for (k, morph) in model.morphs.iter_mut().enumerate() {
        if !c.active[k] {
            continue;
        }
        while f64::from(key(keys, c.index[k]).frame) < frame && c.active[k] {
            let rec = key(keys, c.index[k]);
            if rec.next != 0 {
                c.index[k] = rec.next;
            } else {
                c.active[k] = false;
                morph.value = rec.value;
            }
        }
        if !c.active[k] {
            continue;
        }
        let rec = key(keys, c.index[k]);
        morph.value = if frame == f64::from(rec.frame) {
            rec.value
        } else {
            let prev = key(keys, rec.previous);
            let t = (frame_f - prev.frame as f32) / (rec.frame as i32 - prev.frame as i32) as f32;
            t * (rec.value - prev.value) + prev.value
        };
    }

    // Section 3: bone tracks.
    let keys = &model.bone_keys;
    let c = &mut model.bone_cursors;
    for (b, bone) in model.bones.iter_mut().enumerate() {
        if !c.active[b] {
            continue;
        }
        while f64::from(key(keys, c.index[b]).frame) < frame && c.active[b] {
            let rec = key(keys, c.index[b]);
            if rec.next != 0 {
                c.index[b] = rec.next;
                continue;
            }
            // Terminal key.
            c.active[b] = false;
            copy_key(bone, rec);
            if let Ok(s) = usize::try_from(bone.slot_index) {
                let w = &model.selectors[s];
                if rec.frame < w.window_start && f64::from(w.window_start) <= frame {
                    // Position and quaternion xyz; w is kept.
                    bone.trans = [0.0; 3];
                    bone.rot_quat[..3].fill(0.0);
                }
                if w.window_end == 0 {
                    c.active[b] = false;
                }
            }
            break;
        }
        if !c.active[b] {
            continue;
        }
        let rec = key(keys, c.index[b]);
        let cur_frame = rec.frame;
        if frame == f64::from(cur_frame) {
            copy_key(bone, rec);
            continue;
        }
        let prev = key(keys, rec.previous);
        let prev_frame = prev.frame;
        if let Ok(s) = usize::try_from(bone.slot_index) {
            let w = &model.selectors[s];
            if w.window_start < cur_frame && prev_frame < w.window_start {
                copy_key(
                    bone,
                    if f64::from(w.window_start) <= frame {
                        rec
                    } else {
                        prev
                    },
                );
                continue;
            }
            if !(cur_frame < w.window_end || prev_frame >= w.window_end) {
                copy_key(
                    bone,
                    if f64::from(w.window_end) <= frame {
                        rec
                    } else {
                        prev
                    },
                );
                continue;
            }
        }
        let t = (frame_f - prev_frame as f32) / (cur_frame as i32 - prev_frame as i32) as f32;
        bone.rot_quat = advance_slerp(prev.rotation, rec.rotation, bone_ease(rec, 3, t));
        if keyed_type(bone) {
            for axis in 0..3 {
                let delta = rec.position[axis] - prev.position[axis];
                bone.trans[axis] = if delta == 0.0 {
                    prev.position[axis]
                } else {
                    bone_ease(rec, axis, t) * delta + prev.position[axis]
                };
            }
        }
    }
}
