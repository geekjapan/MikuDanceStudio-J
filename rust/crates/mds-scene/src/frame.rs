//! `EvaluatePmmSceneFrame`: the stateless evaluation of a PMM scene at an
//! integer frame, and the bone, morph, display and selector kernels it and
//! the playback evaluator share. Port of `src/io/pmm_scene_evaluation.cpp`.
//!
//! Operation order, `f32`/`f64` types and conversions follow the C++ line by
//! line. A `None` result is the C++ `false`: broken key links or an invalid
//! frame order.

use crate::curve::bone_ease;
use crate::mds_math;
use crate::track::{
    evaluate_accessory, evaluate_camera, evaluate_gravity, evaluate_self_shadow, light_at,
    CameraMode, LightMode, Track,
};
use mds_formats::pmm::{BoneKey, DisplayKey, Model, Pmm};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Bone {
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
    pub physics_disabled: u8,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Selector {
    pub linked_model: i32,
    pub linked_bone: i32,
    pub window_start: u32,
    pub window_end: u32,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelPose {
    pub slot: u8,
    pub visible: u8,
    pub morph_values: Vec<f32>,
    pub bones: Vec<Bone>,
    pub ik_enabled: Vec<u8>,
    pub selectors: Vec<Selector>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Camera {
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub distance: f32,
    pub fov: f32,
    pub perspective: u8,
    pub parent_model: i32,
    pub parent_bone: i32,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Accessory {
    pub slot: u8,
    pub visible: u8,
    pub shadow_enabled: u8,
    pub opacity: f32,
    pub scale: f32,
    pub parent_model: i32,
    pub parent_bone: i32,
    pub position: [f32; 3],
    pub rotation: [f32; 3],
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Gravity {
    pub noise_enabled: u8,
    pub noise: i32,
    pub acceleration: f32,
    pub direction: [f32; 3],
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScenePose {
    pub frame: u32,
    pub camera: Camera,
    /// Color RGB, direction XYZ.
    pub light_state: [f32; 6],
    pub self_shadow_mode: u8,
    pub self_shadow_distance: f32,
    pub gravity: Gravity,
    pub models: Vec<ModelPose>,
    pub accessories: Vec<Accessory>,
}

pub(crate) fn bone_of_key(key: &BoneKey) -> Bone {
    Bone {
        translation: key.position,
        rotation: key.rotation,
        physics_disabled: key.physics_disabled,
    }
}

/// The C++ literal `1.570796012878418f`, which is one step below
/// `f32::consts::FRAC_PI_2`.
const HALF_PI: f32 = f32::from_bits(0x3fc9_0fd8);

/// `int(b) - int(a)` of two frames, as `f32`: the C++ casts both to `int`.
fn span(a: u32, b: u32) -> f32 {
    (b as i32).wrapping_sub(a as i32) as f32
}

/// `InterpolatePmmMorphValue`, integer frame (the scene-frame overload).
pub fn interpolate_morph(
    previous_value: f32,
    next_value: f32,
    previous_frame: u32,
    next_frame: u32,
    frame: u32,
) -> f32 {
    let fraction = frame.wrapping_sub(previous_frame) as f32 / span(previous_frame, next_frame);
    fraction * (next_value - previous_value) + previous_value
}

/// `InterpolatePmmMorphValue`, floating frame (the playback overload).
pub fn interpolate_morph_at(
    previous_value: f32,
    next_value: f32,
    previous_frame: u32,
    next_frame: u32,
    frame: f64,
) -> f32 {
    let fraction = (frame as f32 - previous_frame as f32) / span(previous_frame, next_frame);
    fraction * (next_value - previous_value) + previous_value
}

fn dot4(left: &[f32; 4], right: &[f32; 4]) -> f32 {
    left[0] * right[0] + left[1] * right[1] + left[2] * right[2] + left[3] * right[3]
}

/// `InterpolatePmmBoneSegment`: direct seek at an integer frame, `f64` blend
/// of the translation and a divided slerp.
pub fn interpolate_bone_segment(left: &BoneKey, right: &BoneKey, frame: u32) -> Option<Bone> {
    if right.frame <= left.frame || frame <= left.frame || frame >= right.frame {
        return None;
    }
    let mut result = Bone {
        physics_disabled: left.physics_disabled,
        ..Bone::default()
    };
    let t = frame.wrapping_sub(left.frame) as f32 / span(left.frame, right.frame);
    for axis in 0..3 {
        let difference = right.position[axis] - left.position[axis];
        result.translation[axis] = if difference == 0.0 {
            left.position[axis]
        } else {
            (f64::from(bone_ease(&right.interpolation, axis, t)) * f64::from(difference)
                + f64::from(left.position[axis])) as f32
        };
    }
    let fraction = bone_ease(&right.interpolation, 3, t);
    let dot = dot4(&left.rotation, &right.rotation);
    if 1.0f32 - dot * dot == 0.0 {
        result.rotation = left.rotation;
        return Some(result);
    }
    let mut clamped = dot;
    if clamped > 1.0 {
        clamped = 0.999_999;
    } else if clamped < -1.0 {
        clamped = -0.999_999;
    }
    let angle = mds_math::acos(clamped);
    if angle > HALF_PI && clamped < 0.0 {
        let shortest = mds_math::acos(-clamped);
        let divisor = mds_math::sin(shortest);
        let w0 = mds_math::sin((1.0f32 - fraction) * shortest) / divisor;
        let w1 = mds_math::sin(fraction * shortest) / divisor;
        result.rotation = std::array::from_fn(|i| left.rotation[i] * w0 - right.rotation[i] * w1);
    } else {
        let divisor = mds_math::sin(angle);
        let w0 = mds_math::sin((1.0f32 - fraction) * angle) / divisor;
        let w1 = mds_math::sin(fraction * angle) / divisor;
        result.rotation = std::array::from_fn(|i| left.rotation[i] * w0 + right.rotation[i] * w1);
    }
    Some(result)
}

/// `InterpolatePmmBonePlaybackSegment`: floating frame, `f32` translation
/// and reciprocal-multiply slerp weights.
pub fn interpolate_bone_playback_segment(
    left: &BoneKey,
    right: &BoneKey,
    frame: f64,
) -> Option<Bone> {
    if right.frame <= left.frame
        || frame <= f64::from(left.frame)
        || frame >= f64::from(right.frame)
    {
        return None;
    }
    let mut result = Bone {
        physics_disabled: left.physics_disabled,
        ..Bone::default()
    };
    let t = (frame as f32 - left.frame as f32) / span(left.frame, right.frame);
    let fraction = bone_ease(&right.interpolation, 3, t);
    let dot = dot4(&left.rotation, &right.rotation);
    if 1.0f32 - dot * dot == 0.0 {
        result.rotation = left.rotation;
    } else {
        let mut clamped = dot;
        if clamped > 1.0 {
            clamped = 0.999_999;
        } else if clamped < -1.0 {
            clamped = -0.999_999;
        }
        let angle = mds_math::acos(clamped);
        if angle > HALF_PI && clamped < 0.0 {
            let shortest = mds_math::acos(-clamped);
            let reciprocal = 1.0f32 / mds_math::sin(shortest);
            let w0 = mds_math::sin((1.0f32 - fraction) * shortest) * reciprocal;
            let w1 = mds_math::sin(fraction * shortest) * reciprocal;
            result.rotation =
                std::array::from_fn(|i| left.rotation[i] * w0 - w1 * right.rotation[i]);
        } else {
            let reciprocal = 1.0f32 / mds_math::sin(angle);
            let w0 = mds_math::sin((1.0f32 - fraction) * angle) * reciprocal;
            let w1 = mds_math::sin(fraction * angle) * reciprocal;
            result.rotation =
                std::array::from_fn(|i| left.rotation[i] * w0 + w1 * right.rotation[i]);
        }
    }
    for axis in 0..3 {
        let difference = right.position[axis] - left.position[axis];
        result.translation[axis] = if difference == 0.0 {
            left.position[axis]
        } else {
            bone_ease(&right.interpolation, axis, t) * difference + left.position[axis]
        };
    }
    Some(result)
}

// ---- display key and selector windows -------------------------------------

/// The links of a display key, with the visible flag read as `flag == 1`.
#[derive(Clone, Copy)]
pub(crate) struct DisplayLink {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub visible: u8,
}

pub(crate) fn display_link(track: &Track<'_, DisplayKey>, index: u32) -> Option<DisplayLink> {
    let key = track.get(index)?;
    Some(DisplayLink {
        frame: key.frame,
        previous: key.previous,
        next: key.next,
        visible: u8::from(key.visible == 1),
    })
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum DisplayTraversal {
    Seek,
    InitializePlayback,
    AdvancePlayback,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub(crate) enum SelectionKind {
    #[default]
    None,
    Terminal,
    Exact,
    Between,
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct DisplaySelection {
    pub kind: SelectionKind,
    pub held_index: u32,
    pub cursor_index: u32,
    pub visible: u8,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct DisplayCursor {
    pub index: u32,
    pub active: bool,
}

impl Default for DisplayCursor {
    fn default() -> Self {
        DisplayCursor {
            index: 0,
            active: true,
        }
    }
}

const WALK_LIMIT: u32 = 1_000_000;

/// `SelectPmmDisplayKey`.
pub(crate) fn select_display_key(
    track: &Track<'_, DisplayKey>,
    frame: f64,
    traversal: DisplayTraversal,
    cursor: &mut DisplayCursor,
) -> Option<DisplaySelection> {
    if !frame.is_finite() || frame < 0.0 {
        return None;
    }
    let mut next_cursor = *cursor;
    let mut result = DisplaySelection::default();
    if traversal != DisplayTraversal::AdvancePlayback {
        next_cursor = DisplayCursor::default();
    } else if !next_cursor.active {
        return Some(result);
    }
    let mut key = display_link(track, next_cursor.index)?;
    let mut steps = 0u32;
    while f64::from(key.frame) < frame {
        if steps >= WALK_LIMIT {
            return None;
        }
        steps += 1;
        if key.next == 0 {
            result.kind = SelectionKind::Terminal;
            result.held_index = next_cursor.index;
            result.cursor_index = next_cursor.index;
            result.visible = key.visible;
            next_cursor.active = false;
            *cursor = next_cursor;
            return Some(result);
        }
        let following = display_link(track, key.next)?;
        if following.previous != next_cursor.index || following.frame <= key.frame {
            return None;
        }
        next_cursor.index = key.next;
        key = following;
    }
    if traversal == DisplayTraversal::InitializePlayback {
        *cursor = next_cursor;
        return Some(result);
    }
    result.cursor_index = next_cursor.index;
    if f64::from(key.frame) == frame {
        result.kind = SelectionKind::Exact;
        result.held_index = next_cursor.index;
        result.visible = key.visible;
    } else {
        let previous = display_link(track, key.previous)?;
        result.kind = SelectionKind::Between;
        result.held_index = key.previous;
        result.visible = previous.visible;
    }
    *cursor = next_cursor;
    Some(result)
}

/// The `(model, bone)` pair of selector `selector` on display key `key_index`.
fn rigid_pair(track: &Track<'_, DisplayKey>, key_index: u32, selector: u32) -> Option<[i32; 2]> {
    track
        .get(key_index)?
        .selectors
        .get(selector as usize)
        .copied()
}

/// `EvaluatePmmSelectorWindow`.
pub(crate) fn evaluate_selector_window(
    track: &Track<'_, DisplayKey>,
    selection: &DisplaySelection,
    selector: u32,
) -> Option<Selector> {
    if selection.kind == SelectionKind::None {
        return None;
    }
    display_link(track, selection.held_index)?;
    let held = rigid_pair(track, selection.held_index, selector)?;
    let mut result = Selector {
        linked_model: held[0],
        linked_bone: held[1],
        ..Selector::default()
    };
    let same_pair =
        |key_index: u32| -> Option<bool> { Some(rigid_pair(track, key_index, selector)? == held) };
    let mut walk = selection.held_index;
    for steps in 0..WALK_LIMIT {
        let key = display_link(track, walk)?;
        if key.frame == 0 {
            result.window_start = 0;
            break;
        }
        let previous = display_link(track, key.previous)?;
        if previous.next != walk || previous.frame >= key.frame {
            return None;
        }
        if !same_pair(key.previous)? {
            result.window_start = key.frame;
            break;
        }
        walk = key.previous;
        if steps == WALK_LIMIT - 1 {
            return None;
        }
    }
    if selection.kind == SelectionKind::Terminal {
        return Some(result);
    }
    let mut forward = selection.cursor_index;
    if !same_pair(forward)? {
        result.window_end = display_link(track, forward)?.frame;
        return Some(result);
    }
    for _ in 0..WALK_LIMIT {
        let key = display_link(track, forward)?;
        if key.next == 0 {
            result.window_end = 0;
            return Some(result);
        }
        let next = display_link(track, key.next)?;
        if next.previous != forward || next.frame <= key.frame {
            return None;
        }
        forward = key.next;
        if !same_pair(forward)? {
            result.window_end = next.frame;
            return Some(result);
        }
    }
    None
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum BoneSelectorResult {
    Unchanged,
    PreviousKey,
    NextKey,
    Reset,
}

/// `SelectPmmBoneSegmentPose`.
pub(crate) fn select_bone_segment_pose(
    previous_frame: u32,
    next_frame: u32,
    frame: f64,
    selector: &Selector,
) -> BoneSelectorResult {
    if previous_frame >= next_frame
        || frame <= f64::from(previous_frame)
        || frame >= f64::from(next_frame)
    {
        return BoneSelectorResult::Unchanged;
    }
    let boundary = |value: u32| value > previous_frame && value < next_frame;
    let crossing = if boundary(selector.window_start) {
        selector.window_start
    } else if boundary(selector.window_end) {
        selector.window_end
    } else {
        0
    };
    if crossing == 0 {
        return BoneSelectorResult::Unchanged;
    }
    if frame >= f64::from(crossing) {
        BoneSelectorResult::NextKey
    } else {
        BoneSelectorResult::PreviousKey
    }
}

/// `SelectPmmBoneTerminalPose`.
pub(crate) fn select_bone_terminal_pose(
    terminal_frame: u32,
    frame: f64,
    selector: &Selector,
) -> BoneSelectorResult {
    if terminal_frame < selector.window_start && frame >= f64::from(selector.window_start) {
        BoneSelectorResult::Reset
    } else {
        BoneSelectorResult::Unchanged
    }
}

/// `ApplyPmmBoneSelectorPose`: `true` and `pose` replaced unless `Unchanged`.
pub(crate) fn apply_bone_selector_pose(
    decision: BoneSelectorResult,
    previous: &BoneKey,
    next: &BoneKey,
    playback: bool,
    pose: &mut Bone,
) -> bool {
    let result = match decision {
        BoneSelectorResult::PreviousKey => bone_of_key(previous),
        BoneSelectorResult::NextKey => bone_of_key(next),
        BoneSelectorResult::Reset => {
            let mut bone = bone_of_key(next);
            bone.translation = [0.0; 3];
            bone.rotation[0] = 0.0;
            bone.rotation[1] = 0.0;
            bone.rotation[2] = 0.0;
            if !playback {
                bone.rotation[3] = 1.0;
            }
            bone
        }
        BoneSelectorResult::Unchanged => return false,
    };
    *pose = result;
    true
}

// ---- the scene --------------------------------------------------------------

/// Counts of a model's tracks: the C++ `PmmModelLayout`.
pub(crate) fn bone_count(model: &Model) -> usize {
    model.bone_names.len()
}

/// `EvaluatePmmSceneFrame`.
pub fn evaluate_scene_frame(scene: &Pmm, frame: u32) -> Option<ScenePose> {
    let frame_f = f64::from(frame);
    let mut result = ScenePose {
        frame,
        camera: evaluate_camera(&scene.camera, frame_f, CameraMode::Seek)?,
        ..ScenePose::default()
    };
    let light_track = Track::new(&scene.light);
    let light = light_track.find(0, frame_f)?;
    result.light_state = light_at(&light, frame_f, LightMode::Playback)?;
    result.self_shadow_mode = scene.self_shadow_mode;
    result.self_shadow_distance = scene.physics_interval;
    result.gravity = Gravity {
        noise_enabled: scene.physics.gravity_noise_enabled,
        noise: scene.physics.gravity_noise,
        acceleration: scene.physics.gravity_magnitude,
        direction: scene.physics.gravity_direction,
    };
    if !scene.gravity.heads().is_empty() {
        result.gravity = evaluate_gravity(&scene.gravity, frame_f, true)?;
    }
    if !scene.self_shadow.heads().is_empty() {
        (result.self_shadow_mode, result.self_shadow_distance) =
            evaluate_self_shadow(&scene.self_shadow, frame_f)?;
    }
    result.models.reserve(scene.models.len());
    for model in &scene.models {
        result.models.push(evaluate_model(model, frame)?);
    }
    result.accessories.reserve(scene.accessories.len());
    for accessory in &scene.accessories {
        result.accessories.push(evaluate_accessory(
            &accessory.keys,
            accessory.slot,
            frame_f,
        )?);
    }
    Some(result)
}

fn evaluate_model(model: &Model, frame: u32) -> Option<ModelPose> {
    let frame_f = f64::from(frame);
    let bone_track = Track::new(&model.bone_keys);
    let bones = bone_count(model);
    let mut output = ModelPose {
        slot: model.slot,
        ..ModelPose::default()
    };
    output.bones.reserve(bones);
    for i in 0..bones {
        let bone = bone_track.find(i, frame_f)?;
        output.bones.push(if bone.is_span() {
            interpolate_bone_segment(bone.left, bone.right, frame)?
        } else {
            bone_of_key(bone.right)
        });
    }
    let morph_track = Track::new(&model.morph_keys);
    output.morph_values.reserve(model.morph_names.len());
    for i in 0..model.morph_names.len() {
        let morph = morph_track.find(i, frame_f)?;
        output.morph_values.push(if morph.is_span() {
            interpolate_morph(
                morph.left.value,
                morph.right.value,
                morph.left.frame,
                morph.right.frame,
                frame,
            )
        } else {
            morph.right.value
        });
    }
    let display_track = Track::new(&model.display_keys);
    if display_track.heads().is_empty() {
        return None;
    }
    let mut cursor = DisplayCursor::default();
    let selection =
        select_display_key(&display_track, frame_f, DisplayTraversal::Seek, &mut cursor)?;
    let held = display_track.get(selection.held_index)?;
    output.visible = selection.visible;
    if held.ik_enabled.len() != model.ik_bones.len() {
        return None;
    }
    output.ik_enabled = held.ik_enabled.iter().map(|&v| u8::from(v == 1)).collect();
    let rigid_count = model.selector_bones.len() as u32;
    output.selectors.reserve(rigid_count as usize);
    for i in 0..rigid_count {
        output
            .selectors
            .push(evaluate_selector_window(&display_track, &selection, i)?);
    }
    for (i, &source_bone) in model.selector_bones.iter().enumerate() {
        if source_bone < 0 {
            continue; // the root selector has no bone pose
        }
        let source_bone = source_bone as usize;
        if source_bone >= bones {
            return None;
        }
        let bone = bone_track.find(source_bone, frame_f)?;
        let decision = if bone.is_span() {
            select_bone_segment_pose(
                bone.left.frame,
                bone.right.frame,
                frame_f,
                &output.selectors[i],
            )
        } else if frame > bone.right.frame {
            select_bone_terminal_pose(bone.right.frame, frame_f, &output.selectors[i])
        } else {
            BoneSelectorResult::Unchanged
        };
        apply_bone_selector_pose(
            decision,
            bone.left,
            bone.right,
            false,
            &mut output.bones[source_bone],
        );
    }
    Some(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    const LINEAR: [u8; 16] = [
        20, 20, 20, 20, 20, 20, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107,
    ];

    fn key(frame: u32, x: f32, rotation: [f32; 4]) -> BoneKey {
        BoneKey {
            frame,
            interpolation: LINEAR,
            position: [x, 0.0, -x],
            rotation,
            ..BoneKey::default()
        }
    }

    #[test]
    fn half_pi_is_the_cpp_float_literal() {
        assert_eq!(HALF_PI, 1.570_796_012_878_418f64 as f32);
    }

    #[test]
    fn bone_segment_at_the_linear_midpoint() {
        let identity = [0.0, 0.0, 0.0, 1.0];
        let (left, right) = (key(0, 2.0, identity), key(10, 6.0, identity));
        let pose = interpolate_bone_segment(&left, &right, 5).unwrap();
        assert_eq!(pose.translation, [4.0, 0.0, -4.0]);
        // Equal quaternions: 1 - dot^2 == 0 keeps the left rotation.
        assert_eq!(pose.rotation, identity);
        let pose = interpolate_bone_playback_segment(&left, &right, 5.0).unwrap();
        assert_eq!(pose.translation, [4.0, 0.0, -4.0]);
    }

    #[test]
    fn bone_segment_rejects_the_end_frames() {
        let identity = [0.0, 0.0, 0.0, 1.0];
        let (left, right) = (key(0, 2.0, identity), key(10, 6.0, identity));
        // The caller copies the key at 0 and at 10; the kernel is open.
        assert!(interpolate_bone_segment(&left, &right, 0).is_none());
        assert!(interpolate_bone_segment(&left, &right, 10).is_none());
        assert!(interpolate_bone_playback_segment(&left, &right, 0.0).is_none());
        assert!(interpolate_bone_playback_segment(&left, &right, 10.0).is_none());
    }

    #[test]
    fn slerp_takes_the_short_way_round() {
        // q and -q are the same rotation. Halfway between them the result
        // must stay on the unit sphere and not collapse to zero.
        let a = [0.0, 0.0, 0.0, 1.0];
        let b = [0.0, 0.6, 0.0, -0.8];
        let pose = interpolate_bone_segment(&key(0, 0.0, a), &key(10, 0.0, b), 5).unwrap();
        let norm: f32 = pose.rotation.iter().map(|v| v * v).sum();
        assert!((norm - 1.0).abs() < 1e-5, "{pose:?}");
    }

    #[test]
    fn morph_halfway() {
        assert_eq!(interpolate_morph(0.0, 1.0, 10, 20, 15), 0.5);
        assert_eq!(interpolate_morph_at(0.0, 1.0, 10, 20, 12.5), 0.25);
    }
}
