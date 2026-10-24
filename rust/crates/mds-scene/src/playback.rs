//! `StartPmmScenePlayback` and `AdvancePmmScenePlayback`
//! (`src/io/pmm_scene_playback.cpp`): the cursor-based evaluator at a
//! fractional frame. The C++ trace mode cannot reach it, so lanes 7 and 9
//! compare it with a C++ driver that calls the same two functions.

use crate::frame::{
    apply_bone_selector_pose, bone_count, bone_of_key, evaluate_scene_frame,
    evaluate_selector_window, interpolate_bone_playback_segment, interpolate_morph_at,
    select_bone_segment_pose, select_bone_terminal_pose, select_display_key, DisplayCursor,
    DisplayTraversal, ScenePose, SelectionKind,
};
use crate::track::{
    evaluate_accessory, evaluate_camera, evaluate_gravity, evaluate_self_shadow, light_at,
    CameraMode, LightMode, Track,
};
use mds_formats::key_pool::Key;
use mds_formats::pmm::Pmm;

#[derive(Clone, Copy, Debug)]
struct Cursor {
    index: u32,
    active: bool,
}

#[derive(Clone, Debug)]
struct ModelCursors {
    display: Cursor,
    bones: Vec<Cursor>,
    morphs: Vec<Cursor>,
}

/// The playback state: the retained pose and one cursor per track.
#[derive(Clone, Debug)]
pub struct PlaybackState {
    pub frame: f64,
    pub pose: ScenePose,
    models: Vec<ModelCursors>,
    accessories: Vec<Cursor>,
}

/// The frame the Windows playback path reaches after `seconds` of float
/// cursor time: 30 fps, rounded half up to the nearest 1/1000 frame.
pub fn playback_frame(seconds: f32) -> Option<f64> {
    if !seconds.is_finite() || seconds < 0.0 {
        return None;
    }
    let mut frame = f64::from(seconds) * 30.0;
    if frame * 1000.0 >= f64::from(i32::MAX) {
        return None;
    }
    let scaled = frame * 1000.0;
    if scaled - f64::from(scaled as i32) >= 0.5 {
        frame = f64::from(scaled as i32 + 1) / 1000.0;
    }
    Some(frame)
}

/// `StartPmmScenePlayback`: the frame-0 pose and every cursor on its head.
pub fn start_playback(scene: &Pmm) -> Option<PlaybackState> {
    let pose = evaluate_scene_frame(scene, 0)?;
    let mut models = Vec::with_capacity(scene.models.len());
    for source in &scene.models {
        if source.bone_keys.heads().len() != bone_count(source)
            || source.morph_keys.heads().len() != source.morph_names.len()
            || source.display_keys.heads().len() != 1
        {
            return None;
        }
        let cursors = |n: usize| {
            (0..n as u32)
                .map(|index| Cursor {
                    index,
                    active: true,
                })
                .collect()
        };
        models.push(ModelCursors {
            display: Cursor {
                index: 0,
                active: true,
            },
            bones: cursors(bone_count(source)),
            morphs: cursors(source.morph_names.len()),
        });
    }
    Some(PlaybackState {
        frame: 0.0,
        pose,
        models,
        accessories: vec![
            Cursor {
                index: 0,
                active: true
            };
            scene.accessories.len()
        ],
    })
}

/// `AdvanceCursor`: moves `cursor` to the first key at or after `frame`.
/// Returns the key and whether the track ran out (the cursor then goes
/// inactive on the last key).
fn advance_cursor<'a, K: Key>(
    track: &Track<'a, K>,
    frame: f64,
    cursor: &mut Cursor,
) -> Option<(&'a K, bool)> {
    if !cursor.active {
        return None;
    }
    let mut key = track.get(cursor.index)?;
    let mut steps = 0usize;
    while f64::from(key.frame()) < frame {
        if steps >= track.len() {
            return None;
        }
        steps += 1;
        if key.next() == 0 {
            cursor.active = false;
            return Some((key, true));
        }
        let next = track.get(key.next())?;
        if next.previous() != cursor.index || next.frame() <= key.frame() {
            return None;
        }
        cursor.index = key.next();
        key = next;
    }
    Some((key, false))
}

fn advance_model(
    source: &mds_formats::pmm::Model,
    frame: f64,
    cursors: &mut ModelCursors,
    pose: &mut crate::frame::ModelPose,
) -> Option<()> {
    let bones = bone_count(source);
    if source.slot != pose.slot
        || bones != pose.bones.len()
        || source.morph_names.len() != pose.morph_values.len()
        || source.ik_bones.len() != pose.ik_enabled.len()
        || source.selector_bones.len() != pose.selectors.len()
        || cursors.bones.len() != pose.bones.len()
        || cursors.morphs.len() != pose.morph_values.len()
    {
        return None;
    }
    let display = Track::new(&source.display_keys);
    // AdvanceDisplay
    if cursors.display.active {
        let mut display_cursor = DisplayCursor {
            index: cursors.display.index,
            active: cursors.display.active,
        };
        let selected = select_display_key(
            &display,
            frame,
            DisplayTraversal::AdvancePlayback,
            &mut display_cursor,
        )?;
        cursors.display = Cursor {
            index: display_cursor.index,
            active: display_cursor.active,
        };
        if selected.kind != SelectionKind::None {
            let held = display.get(selected.held_index)?;
            if held.ik_enabled.len() != source.ik_bones.len() {
                return None;
            }
            pose.visible = selected.visible;
            pose.ik_enabled = held.ik_enabled.iter().map(|&v| u8::from(v == 1)).collect();
            pose.selectors.clear();
            for i in 0..source.selector_bones.len() as u32 {
                pose.selectors
                    .push(evaluate_selector_window(&display, &selected, i)?);
            }
        }
    }
    let mut selector_for_bone = vec![-1i32; bones];
    for (i, &bone) in source.selector_bones.iter().enumerate() {
        if bone < 0 {
            continue;
        }
        let slot = selector_for_bone.get_mut(bone as usize)?;
        if *slot >= 0 {
            return None;
        }
        *slot = i as i32;
    }
    let morphs = Track::new(&source.morph_keys);
    for (i, cursor) in cursors.morphs.iter_mut().enumerate() {
        if !cursor.active {
            continue;
        }
        let (key, exhausted) = advance_cursor(&morphs, frame, cursor)?;
        if exhausted || frame == f64::from(key.frame) {
            pose.morph_values[i] = key.value;
            continue;
        }
        let previous = morphs.get(key.previous)?;
        if previous.next != cursor.index || previous.frame >= key.frame {
            return None;
        }
        pose.morph_values[i] =
            interpolate_morph_at(previous.value, key.value, previous.frame, key.frame, frame);
    }
    let bone_track = Track::new(&source.bone_keys);
    for (i, cursor) in cursors.bones.iter_mut().enumerate() {
        if !cursor.active {
            continue;
        }
        let (key, exhausted) = advance_cursor(&bone_track, frame, cursor)?;
        let selector = usize::try_from(selector_for_bone[i]).ok();
        if exhausted {
            pose.bones[i] = bone_of_key(key);
            if let Some(s) = selector {
                let decision = select_bone_terminal_pose(key.frame, frame, &pose.selectors[s]);
                apply_bone_selector_pose(decision, key, key, true, &mut pose.bones[i]);
            }
            continue;
        }
        if frame == f64::from(key.frame) {
            pose.bones[i] = bone_of_key(key);
            continue;
        }
        let previous = bone_track.get(key.previous)?;
        if previous.next != cursor.index || previous.frame >= key.frame {
            return None;
        }
        if let Some(s) = selector {
            let decision =
                select_bone_segment_pose(previous.frame, key.frame, frame, &pose.selectors[s]);
            if apply_bone_selector_pose(decision, previous, key, true, &mut pose.bones[i]) {
                continue;
            }
        }
        pose.bones[i] = interpolate_bone_playback_segment(previous, key, frame)?;
    }
    Some(())
}

/// `AdvancePmmScenePlayback`: moves the state to `cursor_seconds`. The
/// state is unchanged on `None`.
pub fn advance_playback(scene: &Pmm, cursor_seconds: f32, state: &mut PlaybackState) -> Option<()> {
    if state.models.len() != scene.models.len()
        || state.pose.models.len() != scene.models.len()
        || state.accessories.len() != scene.accessories.len()
        || state.pose.accessories.len() != scene.accessories.len()
    {
        return None;
    }
    let frame = playback_frame(cursor_seconds)?;
    if frame < state.frame {
        return None;
    }
    let mut next = state.clone();
    next.pose.camera = evaluate_camera(&scene.camera, frame, CameraMode::Playback)?;
    let lights = Track::new(&scene.light);
    next.pose.light_state = light_at(&lights.find(0, frame)?, frame, LightMode::Playback)?;
    if !scene.self_shadow.heads().is_empty() {
        (next.pose.self_shadow_mode, next.pose.self_shadow_distance) =
            evaluate_self_shadow(&scene.self_shadow, frame)?;
    }
    if !scene.gravity.heads().is_empty() {
        next.pose.gravity = evaluate_gravity(&scene.gravity, frame, false)?;
    }
    for (i, model) in scene.models.iter().enumerate() {
        advance_model(model, frame, &mut next.models[i], &mut next.pose.models[i])?;
    }
    for (i, accessory) in scene.accessories.iter().enumerate() {
        let cursor = &mut next.accessories[i];
        if !cursor.active {
            continue;
        }
        let track = Track::new(&accessory.keys);
        advance_cursor(&track, frame, cursor)?;
        next.pose.accessories[i] = evaluate_accessory(&accessory.keys, accessory.slot, frame)?;
    }
    next.frame = frame;
    next.pose.frame = frame as u32;
    *state = next;
    Some(())
}
