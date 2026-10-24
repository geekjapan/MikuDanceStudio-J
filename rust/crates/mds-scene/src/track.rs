//! Key track lookup and the camera, light, accessory, self-shadow and gravity
//! track evaluators of `src/io/pmm_scene_evaluation.cpp`.
//!
//! A [`Track`] is the C++ `IndexedTrack`: heads and records are reached by raw
//! pool index. The C++ `valid` flag (negative or duplicate sparse index)
//! cannot be false here, because `KeyPool` only holds distinct in-pool indices.

use crate::curve::camera_ease;
use crate::frame::{Accessory, Camera, Gravity};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{AccessoryKey, CameraKey, GravityKey, LightKey, SelfShadowKey};
use std::ptr;

/// The keys on either side of a frame. `left` and `right` are the same key
/// when the frame is held (before the head, on a key, or after the last key).
pub struct Bracket<'a, K> {
    pub left: &'a K,
    pub right: &'a K,
}

impl<K> Bracket<'_, K> {
    pub fn is_span(&self) -> bool {
        !ptr::eq(self.left, self.right)
    }
}

pub struct Track<'a, K> {
    pool: &'a KeyPool<K>,
    /// Number of keys, heads included: the C++ `keys.size()` loop bound.
    len: usize,
}

impl<'a, K: Key> Track<'a, K> {
    pub fn new(pool: &'a KeyPool<K>) -> Self {
        Track {
            pool,
            len: pool.heads().len() + pool.records().len(),
        }
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn heads(&self) -> &'a [K] {
        self.pool.heads()
    }

    pub fn get(&self, index: u32) -> Option<&'a K> {
        self.pool.get(index)
    }

    /// Every key of the pool, heads first (the C++ `keys` map values).
    pub fn all(&self) -> impl Iterator<Item = &'a K> {
        self.pool
            .heads()
            .iter()
            .chain(self.pool.records().iter().map(|(_, k)| k))
    }

    /// `IndexedTrack::Find`: walks the track from `head` to the keys around
    /// `frame`. `None` when the links are broken.
    pub fn find(&self, head: usize, frame: f64) -> Option<Bracket<'a, K>> {
        let mut current = self.pool.heads().get(head)?;
        let mut index = head as u32;
        if frame <= f64::from(current.frame()) {
            return Some(Bracket {
                left: current,
                right: current,
            });
        }
        for _ in 0..self.len {
            if current.next() == 0 {
                return Some(Bracket {
                    left: current,
                    right: current,
                });
            }
            let following = self.pool.get(current.next())?;
            if following.previous() != index || following.frame() <= current.frame() {
                return None;
            }
            if frame <= f64::from(following.frame()) {
                return Some(if frame == f64::from(following.frame()) {
                    Bracket {
                        left: following,
                        right: following,
                    }
                } else {
                    Bracket {
                        left: current,
                        right: following,
                    }
                });
            }
            index = current.next();
            current = following;
        }
        None
    }
}

/// How the camera interpolates between keys: `Seek` blends in `f64` (the
/// frame-seek path), `Playback` in `f32`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum CameraMode {
    Seek,
    Playback,
}

fn camera_key_pose(key: &CameraKey) -> Camera {
    Camera {
        position: key.eye,
        rotation: key.target,
        distance: key.distance,
        fov: key.fov as f32,
        perspective: u8::from(key.perspective == 1),
        parent_model: key.parent_model,
        parent_bone: key.parent_bone,
    }
}

/// `EvaluatePmmCameraTrack`.
pub fn evaluate_camera(pool: &KeyPool<CameraKey>, frame: f64, mode: CameraMode) -> Option<Camera> {
    if !frame.is_finite() || frame < 0.0 {
        return None;
    }
    let track = Track::new(pool);
    if track.heads().len() != 1 {
        return None;
    }
    let mut current = &track.heads()[0];
    let mut index = 0u32;
    let mut steps = 0usize;
    while f64::from(current.frame) < frame {
        if steps >= track.len() {
            return None;
        }
        steps += 1;
        if current.next == 0 {
            break;
        }
        let found = track.get(current.next)?;
        if found.previous != index || found.frame <= current.frame {
            return None;
        }
        index = current.next;
        current = found;
    }
    if f64::from(current.frame) <= frame {
        return Some(camera_key_pose(current));
    }
    let left = track.get(current.previous)?;
    if left.next != index || left.frame >= current.frame {
        return None;
    }
    if mode == CameraMode::Playback && current.frame.wrapping_sub(1) == left.frame {
        return Some(camera_key_pose(left));
    }
    let t = match mode {
        CameraMode::Playback => {
            (frame as f32 - left.frame as f32) / (current.frame.wrapping_sub(left.frame)) as f32
        }
        CameraMode::Seek => {
            ((frame - f64::from(left.frame)) / f64::from(current.frame.wrapping_sub(left.frame)))
                as f32
        }
    };
    // Seek: double(eased) * (double(b) - double(a)) + double(a), rounded once.
    let blend = |eased: f32, a: f32, b: f32| -> f32 {
        match mode {
            CameraMode::Seek => {
                (f64::from(eased) * (f64::from(b) - f64::from(a)) + f64::from(a)) as f32
            }
            CameraMode::Playback => eased * (b - a) + a,
        }
    };
    let mut result = Camera {
        perspective: u8::from(left.perspective == 1),
        parent_model: left.parent_model,
        parent_bone: left.parent_bone,
        ..Camera::default()
    };
    for axis in 0..3 {
        let eased = camera_ease(&current.interpolation, axis, t);
        result.position[axis] = blend(eased, left.eye[axis], current.eye[axis]);
    }
    let rotation_ease = camera_ease(&current.interpolation, 3, t);
    for axis in 0..3 {
        result.rotation[axis] = blend(rotation_ease, left.target[axis], current.target[axis]);
    }
    let distance_ease = camera_ease(&current.interpolation, 4, t);
    let fov_ease = camera_ease(&current.interpolation, 5, t);
    result.distance = blend(distance_ease, left.distance, current.distance);
    result.fov = match mode {
        CameraMode::Seek => {
            (f64::from(fov_ease) * f64::from(current.fov.wrapping_sub(left.fov))
                + f64::from(left.fov)) as f32
        }
        CameraMode::Playback => {
            fov_ease * (current.fov.wrapping_sub(left.fov)) as f32 + left.fov as f32
        }
    };
    Some(result)
}

/// `EvaluatePmmAccessoryTrack`. The key stores `visible | (100 - opacity%) << 1`.
pub fn evaluate_accessory(pool: &KeyPool<AccessoryKey>, slot: u8, frame: f64) -> Option<Accessory> {
    if !frame.is_finite() || frame < 0.0 || pool.heads().len() != 1 {
        return None;
    }
    let track = Track::new(pool);
    let head = &track.heads()[0];
    let (mut left, mut right) = (head, head);
    let mut index = 0u32;
    let mut steps = 0usize;
    while f64::from(right.frame) < frame && right.next != 0 {
        if steps >= track.len() {
            return None;
        }
        steps += 1;
        let next = track.get(right.next)?;
        if next.previous != index || next.frame <= right.frame {
            return None;
        }
        left = right;
        index = right.next;
        right = next;
    }
    if f64::from(right.frame) <= frame || ptr::eq(right, head) || f64::from(right.frame) == frame {
        left = right;
    }
    let opacity =
        |key: &AccessoryKey| (100 - i32::from(key.opacity_visible >> 1)) as f32 / 100.0f32;
    let mut pose = Accessory {
        slot,
        visible: left.opacity_visible & 1,
        shadow_enabled: u8::from(left.shadow == 1),
        parent_model: left.parent_model,
        parent_bone: left.parent_bone,
        position: left.position,
        rotation: left.rotation,
        scale: left.scale,
        opacity: opacity(left),
    };
    if !ptr::eq(left, right) {
        let t = ((frame - f64::from(left.frame)) / f64::from(right.frame.wrapping_sub(left.frame)))
            as f32;
        pose.scale = left.scale + t * (right.scale - left.scale);
        pose.opacity = opacity(left) + t * (opacity(right) - opacity(left));
    }
    Some(pose)
}

/// `EvaluatePmmSelfShadowTrack`: the held mode and distance.
pub fn evaluate_self_shadow(pool: &KeyPool<SelfShadowKey>, frame: f64) -> Option<(u8, f32)> {
    if !frame.is_finite() || frame < 0.0 || pool.heads().len() != 1 {
        return None;
    }
    let track = Track::new(pool);
    let mut held = &track.heads()[0];
    let mut index = 0u32;
    let mut steps = 0usize;
    while held.next != 0 && f64::from(held.frame) < frame {
        if steps >= track.len() {
            return None;
        }
        steps += 1;
        let next = track.get(held.next)?;
        if next.previous != index || next.frame <= held.frame {
            return None;
        }
        if f64::from(next.frame) > frame {
            break;
        }
        index = held.next;
        held = next;
    }
    Some((held.mode, held.distance))
}

/// `EvaluatePmmGravityTrack`. `frame_seek` also takes the noise flag of the
/// right key inside a span.
pub fn evaluate_gravity(
    pool: &KeyPool<GravityKey>,
    frame: f64,
    frame_seek: bool,
) -> Option<Gravity> {
    if !frame.is_finite() || frame < 0.0 || pool.heads().len() != 1 {
        return None;
    }
    let track = Track::new(pool);
    let mut left = &track.heads()[0];
    let mut right = left;
    let mut index = 0u32;
    let mut steps = 0usize;
    while f64::from(right.frame) < frame && right.next != 0 {
        if steps >= track.len() {
            return None;
        }
        steps += 1;
        let found = track.get(right.next)?;
        if found.previous != index || found.frame <= right.frame {
            return None;
        }
        left = right;
        index = right.next;
        right = found;
    }
    if f64::from(right.frame) <= frame {
        left = right;
    }
    let mut result = Gravity {
        noise_enabled: u8::from(left.noise_enabled == 1),
        noise: left.noise,
        acceleration: left.acceleration,
        direction: left.direction,
    };
    if !ptr::eq(left, right) {
        if frame_seek {
            result.noise_enabled = u8::from(right.noise_enabled == 1);
        }
        let fraction =
            (frame as f32 - left.frame as f32) / (right.frame.wrapping_sub(left.frame)) as f32;
        result.noise = result
            .noise
            .wrapping_add((right.noise.wrapping_sub(left.noise) as f32 * fraction) as i32);
        result.acceleration =
            (right.acceleration - left.acceleration) * fraction + left.acceleration;
        for axis in 0..3 {
            result.direction[axis] =
                (right.direction[axis] - left.direction[axis]) * fraction + left.direction[axis];
        }
    }
    Some(result)
}

/// How a light span blends: `FrameSeek` in `f64`, `Playback` in `f32`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum LightMode {
    FrameSeek,
    Playback,
}

/// `InterpolatePmmLightSegment`: color then direction.
pub fn interpolate_light(
    left: &LightKey,
    right: &LightKey,
    frame: f64,
    mode: LightMode,
) -> Option<[f32; 6]> {
    if right.frame <= left.frame
        || frame <= f64::from(left.frame)
        || frame >= f64::from(right.frame)
    {
        return None;
    }
    let mut result = [0.0f32; 6];
    let fraction =
        (frame as f32 - left.frame as f32) / (right.frame.wrapping_sub(left.frame)) as f32;
    let precise = (frame - f64::from(left.frame)) / f64::from(right.frame.wrapping_sub(left.frame));
    for i in 0..3 {
        match mode {
            LightMode::FrameSeek => {
                result[i] = ((f64::from(right.color[i] - left.color[i])) * precise
                    + f64::from(left.color[i])) as f32;
                result[i + 3] = (f64::from(right.direction[i] - left.direction[i]) * precise
                    + f64::from(left.direction[i])) as f32;
            }
            LightMode::Playback => {
                result[i] = fraction * (right.color[i] - left.color[i]) + left.color[i];
                result[i + 3] =
                    fraction * (right.direction[i] - left.direction[i]) + left.direction[i];
            }
        }
    }
    Some(result)
}

/// The light at a bracket: the key itself when held, else the span blend.
pub fn light_at(bracket: &Bracket<'_, LightKey>, frame: f64, mode: LightMode) -> Option<[f32; 6]> {
    if bracket.is_span() {
        return interpolate_light(bracket.left, bracket.right, frame, mode);
    }
    let key = bracket.right;
    Some([
        key.color[0],
        key.color[1],
        key.color[2],
        key.direction[0],
        key.direction[1],
        key.direction[2],
    ])
}

/// `EvaluatePmmLightTrack`: the checked entry point (finite keys, a walkable
/// chain, `frame <= u32::MAX`).
pub fn evaluate_light(pool: &KeyPool<LightKey>, frame: f64, mode: LightMode) -> Option<[f32; 6]> {
    if !(0.0..=f64::from(u32::MAX)).contains(&frame) || pool.heads().len() != 1 {
        return None;
    }
    let track = Track::new(pool);
    if !track
        .all()
        .all(|k| k.color.iter().chain(&k.direction).all(|v| v.is_finite()))
    {
        return None;
    }
    track.find(0, 4_294_967_295.0)?;
    light_at(&track.find(0, frame)?, frame, mode)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Camera keys at frame 0 and frame 10 (pool index 1), linear curves.
    fn camera_pool(last_x: f32) -> KeyPool<CameraKey> {
        let curve = [[20; 6], [20; 6], [107; 6], [107; 6]];
        let head = CameraKey {
            next: 1,
            interpolation: curve,
            fov: 30,
            ..CameraKey::default()
        };
        let mut pool = KeyPool::new(16, vec![head]).unwrap();
        let last = CameraKey {
            frame: 10,
            previous: 0,
            eye: [last_x, 0.0, 0.0],
            interpolation: curve,
            fov: 50,
            ..CameraKey::default()
        };
        pool.insert(1, last);
        pool
    }

    #[test]
    fn camera_at_the_ends_and_the_linear_midpoint() {
        let pool = camera_pool(8.0);
        for mode in [CameraMode::Seek, CameraMode::Playback] {
            let at = |f: f64| evaluate_camera(&pool, f, mode).unwrap();
            assert_eq!(at(0.0).position[0], 0.0);
            assert_eq!(at(0.0).fov, 30.0);
            assert_eq!(at(5.0).position[0], 4.0, "{mode:?}");
            assert_eq!(at(5.0).fov, 40.0, "{mode:?}");
            assert_eq!(at(10.0).position[0], 8.0);
            assert_eq!(at(99.0).position[0], 8.0, "held after the last key");
        }
    }

    #[test]
    fn camera_rejects_a_bad_frame_and_bad_links() {
        let pool = camera_pool(8.0);
        for frame in [-1.0, f64::NAN, f64::INFINITY] {
            assert!(evaluate_camera(&pool, frame, CameraMode::Seek).is_none());
        }
        let mut broken = camera_pool(8.0);
        broken.get_mut(1).unwrap().previous = 5;
        assert!(evaluate_camera(&broken, 5.0, CameraMode::Seek).is_none());
    }
}
