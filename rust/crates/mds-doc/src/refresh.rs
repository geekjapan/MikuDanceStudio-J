//! The state a frame change re-evaluates from the keys:
//! `RefreshAfterFrameApply` (`src/window/ui_frame_step.cpp`, VA 0x00432FA0)
//! and the camera-mode refreshes of `RefreshFrameContext`.

use crate::{ModelFile, Pmm};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{self, CameraKey};
use mds_pose::model::Model as PoseModel;

fn key<K: Key>(pool: &KeyPool<K>, i: u32) -> Option<&K> {
    pool.get(i)
}

/// From the head along `next` to the first key at or after `frame`; `true`
/// when the walk ended on the last key before `frame`.
fn seek<K: Key>(pool: &KeyPool<K>, frame: u32) -> (u32, bool) {
    let mut i = 0;
    let Some(k) = key(pool, 0) else {
        return (0, true);
    };
    if k.frame() >= frame {
        return (0, false);
    }
    for _ in 0..pool.capacity() {
        let next = key(pool, i).map_or(0, |k| k.next());
        if next == 0 {
            return (i, true);
        }
        i = next;
        if key(pool, i).map_or(true, |k| k.frame() >= frame) {
            return (i, false);
        }
    }
    (i, true)
}

/// `SeekModelFrame` of one model, through `mds_pose`, written back into the
/// saved pose: bone translation and rotation, the physics flag, morph
/// weights, IK switches, and the outside-parent windows.
pub(crate) fn seek_model(m: &mut pmm::Model, file: &ModelFile, frame: u32, physics_mode: u8) {
    let pose = match file {
        ModelFile::Pmx(p) => PoseModel::from_pmx(m.slot, p),
        ModelFile::Pmd(p) => PoseModel::from_pmd(m.slot, p),
        ModelFile::Missing => return,
    };
    let Ok(mut pose) = pose else { return };
    if pose.apply_pmm(m).is_err() {
        return;
    }
    mds_pose::keys::seek_model_frame(&mut pose, frame, i32::from(physics_mode));
    for (p, b) in m.bone_pose.iter_mut().zip(&pose.bones) {
        p.translation = b.trans;
        p.rotation = b.rot_quat;
        if p.flags[0] != b.physics_disabled {
            p.flags[0] = b.physics_disabled;
        }
    }
    for (v, morph) in m.morph_pose.iter_mut().zip(&pose.morphs) {
        *v = morph.value;
    }
    for (v, ik) in m.ik_pose.iter_mut().zip(&pose.iks) {
        *v = ik.enabled;
    }
    for (v, s) in m.selector_pose.iter_mut().zip(&pose.selectors) {
        *v = [
            s.window_start as i32,
            s.window_end as i32,
            s.linked_model,
            s.linked_bone,
        ];
    }
}

/// `CopyCameraKey` (`src/app/timeline_advance.cpp`).
fn copy_camera(p: &mut Pmm, k: &CameraKey) {
    let s = &mut p.camera_state;
    s[..3].copy_from_slice(&k.eye);
    s[6..].copy_from_slice(&k.target);
    s[5] = k.distance;
    p.camera_perspective = k.perspective;
    p.settings.camera_fov = k.fov as f32;
}

/// `ReloadModels` (`src/app/timeline_advance.cpp`, VA 0x0042E640): the
/// camera at the current frame.
pub(crate) fn camera(p: &mut Pmm) {
    let frame = p.timeline.current_frame as u32;
    let (i, _) = seek(&p.camera, frame);
    let Some(cur) = key(&p.camera, i).cloned() else {
        return;
    };
    let src = if cur.frame <= frame {
        copy_camera(p, &cur);
        cur
    } else {
        let Some(prev) = key(&p.camera, cur.previous).cloned() else {
            return;
        };
        let t = (f64::from(frame - prev.frame) / f64::from(cur.frame - prev.frame)) as f32;
        p.camera_perspective = prev.perspective;
        let ease = |c| mds_scene::curve::camera_ease(&cur.interpolation, c, t);
        let lerp = |e: f32, a: f64, b: f64| (f64::from(e) * (b - a) + a) as f32;
        for c in 0..3 {
            p.camera_state[c] = lerp(ease(c), prev.eye[c].into(), cur.eye[c].into());
        }
        p.camera_state[6] = lerp(ease(3), prev.target[0].into(), cur.target[0].into());
        p.camera_state[5] = lerp(ease(4), prev.distance.into(), cur.distance.into());
        p.settings.camera_fov = lerp(ease(5), f64::from(prev.fov), f64::from(cur.fov));
        let r = ease(3);
        for a in 0..3 {
            p.camera_state[6 + a] = lerp(r, prev.target[a].into(), cur.target[a].into());
        }
        prev
    };
    p.camera_state[3] = 0.0;
    p.camera_state[4] = 0.0;
    p.appearance.camera_parent_model = src.parent_model;
    p.appearance.camera_parent_bone = src.parent_bone;
}

/// `RefreshLightPanel` (`src/window/ui_frame_refresh.cpp`, VA 0x00411070).
pub(crate) fn light(p: &mut Pmm) {
    let frame = p.timeline.current_frame as u32;
    let (i, _) = seek(&p.light, frame);
    let Some(r) = key(&p.light, i).cloned() else {
        return;
    };
    if r.frame <= frame {
        p.light_state[..3].copy_from_slice(&r.color);
        p.light_state[3..].copy_from_slice(&r.direction);
        return;
    }
    let Some(l) = key(&p.light, r.previous).cloned() else {
        return;
    };
    let amount = f64::from(frame - l.frame) / f64::from(r.frame - l.frame);
    for c in 0..3 {
        p.light_state[3 + c] = (f64::from(r.direction[c] - l.direction[c]) * amount
            + f64::from(l.direction[c])) as f32;
        p.light_state[c] =
            (f64::from(r.color[c] - l.color[c]) * amount + f64::from(l.color[c])) as f32;
    }
}

/// `RefreshSelfShadowPanel` (VA 0x00411B90): the mode and distance of the
/// key at the current frame, else of the key before it.
pub(crate) fn self_shadow(p: &mut Pmm, mode: &mut u8) {
    let frame = p.timeline.current_frame as u32;
    let (i, _) = seek(&p.self_shadow, frame);
    let Some(mut k) = key(&p.self_shadow, i) else {
        return;
    };
    if k.frame != frame {
        match key(&p.self_shadow, k.previous) {
            Some(prev) => k = prev,
            None => return,
        }
    }
    *mode = k.mode;
    p.physics_interval = k.distance;
}

/// `ApplyGravityTrack` (`src/model/track_apply.cpp`, VA 0x00412330).
pub(crate) fn gravity(p: &mut Pmm) {
    let frame = p.timeline.current_frame as u32;
    let (i, end) = seek(&p.gravity, frame);
    let Some(rec) = key(&p.gravity, i).cloned() else {
        return;
    };
    let g = &mut p.physics;
    if end || rec.frame == frame {
        g.gravity_noise_enabled = rec.noise_enabled;
        g.gravity_noise = rec.noise;
        g.gravity_magnitude = rec.acceleration;
        g.gravity_direction = rec.direction;
        return;
    }
    let Some(prev) = key(&p.gravity, rec.previous).cloned() else {
        return;
    };
    let wrap = |v: i32| {
        let f = v as f32;
        if f < 0.0 {
            f + 4294967296.0
        } else {
            f
        }
    };
    let t = wrap(frame.wrapping_sub(prev.frame) as i32)
        / wrap(rec.frame.wrapping_sub(prev.frame) as i32);
    let g = &mut p.physics;
    g.gravity_noise = (t * (rec.noise - prev.noise) as f32) as i32 + prev.noise;
    g.gravity_magnitude = (rec.acceleration - prev.acceleration) * t + prev.acceleration;
    for a in 0..3 {
        g.gravity_direction[a] = (rec.direction[a] - prev.direction[a]) * t + prev.direction[a];
    }
    g.gravity_noise_enabled = rec.noise_enabled;
}

/// `ApplyAccessoryTrack` (`src/window/accessory_paste.cpp`, VA 0x00413120).
pub(crate) fn accessory(a: &mut pmm::Accessory, frame: u32) {
    let (i, end) = seek(&a.keys, frame);
    let Some(rec) = key(&a.keys, i).cloned() else {
        return;
    };
    let opacity = |b: u8| (100 - i32::from(b >> 1)) as f32 / 100.0;
    let s = &mut a.state;
    let push = |s: &mut pmm::AccessoryState, k: &pmm::AccessoryKey, opacity: Option<f32>| {
        let o = opacity.unwrap_or((100 - i32::from(s.opacity_visible >> 1)) as f32 / 100.0);
        s.opacity_visible = crate::save::opacity_visible(o, k.opacity_visible & 1);
        s.shadow = k.shadow;
        s.parent_model = k.parent_model;
        s.parent_bone = k.parent_bone;
        s.rotation = k.rotation;
        s.position = k.position;
    };
    if end || rec.frame == frame {
        s.scale = rec.scale;
        push(s, &rec, Some(opacity(rec.opacity_visible)));
        return;
    }
    let Some(prev) = key(&a.keys, rec.previous).cloned() else {
        return;
    };
    let delta = |a: u32, b: u32| a.wrapping_sub(b) as f32;
    let t = delta(frame, prev.frame) / delta(rec.frame, prev.frame);
    s.scale = prev.scale + t * (rec.scale - prev.scale);
    let (po, ro) = (opacity(prev.opacity_visible), opacity(rec.opacity_visible));
    push(s, &prev, Some(po + t * (ro - po)));
}
