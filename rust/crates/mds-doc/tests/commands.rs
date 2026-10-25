//! One test per command. Each expected record or pool state is read off the
//! C++ named in the test's comment.

use mds_doc::history::Entry;
use mds_doc::{Command, Document, Error, GlobalTrack, Track};
use mds_formats::key_pool::{Key, KeyPool, GLOBAL_KEY_CAPACITY};
use mds_formats::pmm::{Accessory, AccessoryKey, AccessoryState, BoneKey};
use mds_formats::text::FixedSjis;
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// swing600.pmm: slot 0 is chain8_ik.pmx with bone keys; bones 5..7 have
/// rigid bodies. Camera has one key (the head), light two, self shadow two.
fn doc() -> Document {
    let data = std::fs::read(dir().join("swing600.pmm")).unwrap();
    Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

fn run(d: &mut Document, cmds: impl IntoIterator<Item = Command>) {
    for c in cmds {
        let what = format!("{c:?}");
        d.apply(c).unwrap_or_else(|e| panic!("{what}: {e}"));
    }
}

/// `(index, frame)` of the keys of a track, head first.
fn track<K: Key>(pool: &KeyPool<K>, head: u32) -> Vec<(u32, u32)> {
    let mut out = vec![(head, pool.get(head).unwrap().frame())];
    let mut i = pool.get(head).unwrap().next();
    while i != 0 {
        out.push((i, pool.get(i).unwrap().frame()));
        i = pool.get(i).unwrap().next();
    }
    out
}

fn validate(d: &Document) {
    for m in &d.pmm.models {
        m.bone_keys.validate_tracks().unwrap();
        m.morph_keys.validate_tracks().unwrap();
        m.display_keys.validate_tracks().unwrap();
    }
    d.pmm.camera.validate_tracks().unwrap();
    d.pmm.light.validate_tracks().unwrap();
    d.pmm.self_shadow.validate_tracks().unwrap();
    d.pmm.gravity.validate_tracks().unwrap();
    for a in &d.pmm.accessories {
        a.keys.validate_tracks().unwrap();
    }
}

fn with_accessory(d: &mut Document) {
    let fixed = |s: &str| {
        let mut raw = [0; 100];
        raw[..s.len()].copy_from_slice(s.as_bytes());
        FixedSjis {
            raw,
            text: s.into(),
        }
    };
    let mut path = [0; 256];
    path[..5].copy_from_slice(b"acc.x");
    let head = AccessoryKey {
        opacity_visible: 1,
        parent_model: -1,
        scale: 1.0,
        ..AccessoryKey::default()
    };
    d.pmm.accessories.push(Accessory {
        list_name: fixed("acc"),
        slot: 0,
        name: fixed("acc"),
        path: FixedSjis {
            raw: path,
            text: "acc.x".into(),
        },
        order: 0,
        keys: KeyPool::new(GLOBAL_KEY_CAPACITY, vec![head]).unwrap(),
        state: AccessoryState {
            opacity_visible: 1,
            parent_model: -1,
            scale: 1.0,
            ..AccessoryState::default()
        },
    });
}

// ---- camera mode ----------------------------------------------------------

#[test]
fn camera_register_appends_after_the_last_key() {
    // InsertGlobalFrame: free record 1, appended with next = 0, selected,
    // lastRegisteredFrame raised; RegisterCameraState takes the panel state.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SetFrame(700),
            Command::SetCamera {
                position: [1.0, 2.0, 3.0],
                rotation: [0.1, 0.2, 0.3],
                distance: -20.0,
                fov: 40.0,
                perspective: true,
            },
            Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]),
        ],
    );
    assert_eq!(track(&d.pmm.camera, 0), [(0, 0), (1, 700)]);
    let k = d.pmm.camera.get(1).unwrap();
    assert_eq!(
        (k.eye, k.target, k.distance, k.fov),
        ([1.0, 2.0, 3.0], [0.1, 0.2, 0.3], -20.0, 40)
    );
    assert_eq!((k.selected, k.perspective, k.parent_model), (1, 1, -1));
    assert_eq!(k.interpolation, [[20; 6], [20; 6], [107; 6], [107; 6]]);
    assert_eq!(d.pmm.timeline.last_registered_frame, 700);
    validate(&d);
}

#[test]
fn camera_register_on_a_key_keeps_its_curve_unless_reset() {
    // RegisterCameraState: an existing key's curve is kept unless the 530
    // checkbox is on; an exact hit does not raise lastRegisteredFrame.
    let mut d = doc();
    d.pmm.timeline.last_registered_frame = 0;
    d.pmm.camera.heads_mut()[0].interpolation[0][0] = 77;
    run(
        &mut d,
        [Command::RegisterGlobalKeys(vec![GlobalTrack::Camera])],
    );
    let head = &d.pmm.camera.heads()[0];
    assert_eq!(head.interpolation[0][0], 77);
    assert_eq!(head.selected, 1);
    assert_eq!(d.pmm.timeline.last_registered_frame, 0);
    run(
        &mut d,
        [
            Command::SetAutoInterpolation(true),
            Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]),
        ],
    );
    assert_eq!(d.pmm.camera.heads()[0].interpolation[0][0], 20);
}

#[test]
fn global_register_clears_the_selection_once() {
    // PumpGlobalEnterRegister: the marks of all tracks cleared, then every
    // listed track registered, so all new keys stay selected.
    let mut d = doc();
    let light_keys = track(&d.pmm.light, 0);
    run(
        &mut d,
        [
            Command::SelectKeys {
                track: Track::Global(GlobalTrack::Light),
                from: 0,
                to: 1000,
            },
            Command::SetFrame(50),
            Command::RegisterGlobalKeys(vec![GlobalTrack::Gravity, GlobalTrack::Light]),
        ],
    );
    let light = &d.pmm.light;
    assert_eq!(track(light, 0)[..2], [light_keys[0], (2, 50)]);
    let selected: Vec<u32> = track(light, 0)
        .iter()
        .filter(|(i, _)| light.get(*i).unwrap().selected != 0)
        .map(|k| k.1)
        .collect();
    assert_eq!(selected, [50]);
    let g = d.pmm.gravity.get(1).unwrap();
    assert_eq!(
        (g.frame, g.selected, g.noise, g.acceleration),
        (50, 1, 10, 9.8)
    );
    validate(&d);
}

#[test]
fn light_and_gravity_register_take_the_panel_state() {
    // RegisterLightState copies lightState (color, direction);
    // RegisterGravityState the gravity dialog values into the key.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SetFrame(700),
            Command::SetLight {
                color: [0.1, 0.2, 0.3],
                direction: [1.0, 0.0, -1.0],
            },
            Command::SetGravity {
                acceleration: 4.5,
                noise: 3,
                direction: [0.0, 0.0, 1.0],
                noise_enabled: true,
            },
            Command::RegisterGlobalKeys(vec![GlobalTrack::Light, GlobalTrack::Gravity]),
        ],
    );
    assert_eq!(d.pmm.light_state, [0.1, 0.2, 0.3, 1.0, 0.0, -1.0]);
    let (i, frame) = *track(&d.pmm.light, 0).last().unwrap();
    let l = d.pmm.light.get(i).unwrap();
    assert_eq!(
        (frame, l.color, l.direction, l.selected),
        (700, [0.1, 0.2, 0.3], [1.0, 0.0, -1.0], 1)
    );
    let g = d.pmm.gravity.get(1).unwrap();
    assert_eq!(
        (
            g.frame,
            g.acceleration,
            g.noise,
            g.direction,
            g.noise_enabled
        ),
        (700, 4.5, 3, [0.0, 0.0, 1.0], 1)
    );
    validate(&d);
}

#[test]
fn self_shadow_register_takes_the_radio_and_the_distance() {
    // RegisterSelfShadowState: mode from SelfShadowMode, distance from
    // selfShadowDistance; insert before the frame-300 key.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SetFrame(100),
            Command::SetSelfShadow {
                mode: 2,
                distance: 0.5,
            },
            Command::RegisterGlobalKeys(vec![GlobalTrack::SelfShadow]),
        ],
    );
    let frames: Vec<u32> = track(&d.pmm.self_shadow, 0).iter().map(|k| k.1).collect();
    assert_eq!(frames, [0, 100, 300]);
    let k = d.pmm.self_shadow.get(2).unwrap();
    assert_eq!((k.mode, k.distance, k.selected), (2, 0.5, 1));
    validate(&d);
}

#[test]
fn accessory_register_and_paste() {
    // RegisterAccessoryKey copies the accessory state; PasteAccessoryKeyRecord
    // puts the copy at the current frame plus its offset.
    let mut d = doc();
    with_accessory(&mut d);
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SetFrame(10),
            Command::SetAccessory {
                slot: 0,
                visible: true,
                opacity: 0.5,
                shadow: true,
                parent_model: 0,
                parent_bone: 2,
                position: [1.0, 0.0, 0.0],
                rotation: [0.0; 3],
                scale: 2.0,
            },
            Command::RegisterGlobalKeys(vec![GlobalTrack::Accessory(0)]),
            Command::Copy,
            Command::SetFrame(30),
            Command::Paste,
        ],
    );
    let keys = &d.pmm.accessories[0].keys;
    assert_eq!(track(keys, 0), [(0, 0), (1, 10), (2, 30)]);
    let k = keys.get(2).unwrap();
    // (100 - 50) * 2 + 1
    assert_eq!(
        (k.opacity_visible, k.shadow, k.parent_bone, k.scale),
        (101, 1, 2, 2.0)
    );
    assert_eq!(
        keys.get(1).unwrap().selected,
        0,
        "paste clears the selection"
    );
    validate(&d);
    assert!(matches!(
        d.apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Accessory(9)])),
        Err(Error::NotApplicable(_))
    ));
}

#[test]
fn camera_copy_and_paste_is_relative_to_the_first_key() {
    // CopySelectedKeyframes: frames minus the earliest selected key over all
    // tracks; PasteSelectedKeyframes adds the current frame.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SelectKeys {
                track: Track::Global(GlobalTrack::Light),
                from: 1,
                to: 1000,
            },
            Command::SelectKeys {
                track: Track::Global(GlobalTrack::SelfShadow),
                from: 1,
                to: 1000,
            },
            Command::Copy,
        ],
    );
    assert_eq!(d.edit.global_clipboard.lights[0].frame, 0);
    assert_eq!(d.edit.global_clipboard.shadows[0].frame, 0);
    run(&mut d, [Command::SetFrame(1000), Command::Paste]);
    let frames: Vec<u32> = track(&d.pmm.light, 0).iter().map(|k| k.1).collect();
    assert_eq!(frames, [0, 300, 1000]);
    assert_eq!(d.pmm.timeline.last_registered_frame, 1000);
    validate(&d);
}

#[test]
fn camera_delete_unlinks_through_link_0() {
    // DeleteMarkedKeyframes: UnlinkGlobalKey of the last key writes
    // previous of record 0; the freed record is reset.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SelectKeys {
                track: Track::Global(GlobalTrack::Light),
                from: 300,
                to: 300,
            },
            Command::DeleteSelectedKeys,
        ],
    );
    let head = &d.pmm.light.heads()[0];
    assert_eq!((head.next, head.previous), (0, 0));
    let freed = d.pmm.light.get(1).unwrap();
    assert_eq!((freed.frame, freed.color, freed.selected), (0, [0.0; 3], 0));
    validate(&d);
}

#[test]
fn deleting_the_light_head_cuts_its_track() {
    // ResetLightRecord(head) then light[0].next = 0: an unselected key is
    // left on no track. The camera head keeps its track.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SelectKeys {
                track: Track::Global(GlobalTrack::Light),
                from: 0,
                to: 0,
            },
            Command::DeleteSelectedKeys,
        ],
    );
    let head = &d.pmm.light.heads()[0];
    assert_eq!(
        (head.next, head.color, head.direction),
        (0, [0.602; 3], [-0.5, -1.0, 0.5])
    );
    assert!(d
        .pmm
        .light
        .validate_tracks()
        .unwrap_err()
        .contains("no track"));
}

// ---- model mode -----------------------------------------------------------

fn bone_records(d: &Document) -> Vec<(u32, BoneKey)> {
    let pool = &d.pmm.models[0].bone_keys;
    let heads = pool
        .heads()
        .iter()
        .enumerate()
        .map(|(i, k)| (i as u32, k.clone()));
    heads.chain(pool.records().iter().cloned()).collect()
}

#[test]
fn register_bones_stores_the_pose_and_an_undo_entry() {
    // RegisterSelectedBoneKeys: an undo entry with every bone's pose and the
    // records RegisterBonePoseAtFrame touches ({prev, cur, fresh} for an
    // insert), the edited mark cleared, lastRegisteredFrame raised to
    // maxFrame.
    let mut d = doc();
    d.pmm.timeline.last_registered_frame = 0;
    run(
        &mut d,
        [
            Command::SetFrame(150),
            Command::SelectBones(vec![1]),
            Command::SetBonePose {
                bone: 1,
                translation: [1.0, 2.0, 3.0],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
            Command::RegisterBoneKeys,
        ],
    );
    let m = &d.pmm.models[0];
    let t = track(&m.bone_keys, 1);
    let frames: Vec<u32> = t.iter().map(|k| k.1).collect();
    assert_eq!(frames, [0, 100, 150, 200, 300, 400, 500, 599]);
    let fresh = t[2].0;
    let k = m.bone_keys.get(fresh).unwrap();
    assert_eq!((k.position, k.allocated), ([1.0, 2.0, 3.0], 1));
    assert_eq!(m.bone_pose[1].flags[1], 0);
    assert_eq!(d.pmm.timeline.last_registered_frame, 599);
    let h = &d.edit.models[0].history;
    let Entry::BoneKeys { frame, pose, keys } = &h.undo[h.cursor] else {
        panic!("{:?}", h.undo[h.cursor]);
    };
    assert_eq!((*frame, pose.len()), (150, 9));
    let touched: Vec<u32> = keys.iter().map(|k| k.0).collect();
    let mut expect = vec![t[1].0, t[3].0, fresh];
    expect.sort();
    assert_eq!(touched, expect);
    assert!(
        keys.iter().find(|k| k.0 == fresh).unwrap().1.is_none(),
        "fresh was free"
    );
    assert!(
        keys.iter().flat_map(|k| &k.1).all(|k| k.allocated == 0),
        "captured after the marks are cleared"
    );
    validate(&d);
}

#[test]
fn undo_and_redo_of_a_register() {
    // UndoModelEdit restores the records, the pose and the frame;
    // RedoModelEdit restores the records only.
    let mut d = doc();
    let before = bone_records(&d);
    run(
        &mut d,
        [
            Command::SetFrame(150),
            Command::SelectBones(vec![1, 2]),
            Command::RegisterBoneKeys,
        ],
    );
    // The frame change seeks the saved pose, so only the records are
    // compared after the redo.
    let after = format!("{:?}", bone_records(&d));
    run(&mut d, [Command::SetFrame(5), Command::Undo]);
    assert_eq!(d.pmm.timeline.current_frame, 150);
    let undone = bone_records(&d);
    assert_eq!(undone.len(), before.len());
    for ((i, a), (j, b)) in undone.iter().zip(&before) {
        assert_eq!(
            (i, a.frame, a.previous, a.next),
            (j, b.frame, b.previous, b.next)
        );
    }
    assert!(!d.edit.models[0].history.undo_dirty);
    assert_eq!(
        d.apply(Command::Undo),
        Err(Error::NotApplicable("nothing to undo"))
    );
    run(&mut d, [Command::Redo]);
    assert_eq!(format!("{:?}", bone_records(&d)), after);
    assert!(!d.edit.models[0].history.redo_dirty);
}

#[test]
fn a_rigid_body_bone_registers_the_zeroed_physics_pose_before_any_physics_step() {
    // RegisterBonePoseAtFrame (model_keyframe_edit.cpp 262-275) stores
    // ikBackup for a bone that physics drives; the loaders zero the bone
    // records, so before the first physics step that is all zeros. Then
    // physicsDisabled = !checkbox (499, checked at start-up).
    let mut d = doc();
    d.pmm.physics.playback_mode = 1;
    d.edit.physics_checkbox = true;
    run(
        &mut d,
        [
            Command::SetFrame(7),
            Command::SelectBones(vec![5]),
            Command::RegisterBoneKeys,
        ],
    );
    let m = &d.pmm.models[0];
    let k = bone_records(&d)
        .into_iter()
        .map(|(_, k)| k)
        .find(|k| k.frame == 7 && k.allocated != 0)
        .expect("the key at frame 7");
    assert_eq!((k.rotation, k.position), ([0.0; 4], [0.0; 3]));
    assert_eq!(k.physics_disabled, 0);
    assert_eq!(m.bone_pose[5].rotation, [0.0; 4]);
    assert_eq!(m.bone_pose[5].flags[0], 0);
}

#[test]
fn delete_captures_i_previous_and_next() {
    // DeleteMarkedModelKeys: AppendBoneKeyToUndo(i, prev, next) for every
    // marked bone key; deleting the head captures its next and record 0.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::ClearKeySelection,
            Command::SelectKeys {
                track: Track::Bone(1),
                from: 0,
                to: 100,
            },
            Command::DeleteSelectedKeys,
        ],
    );
    let t = track(&d.pmm.models[0].bone_keys, 1);
    let frames: Vec<u32> = t.iter().map(|k| k.1).collect();
    assert_eq!(frames, [0, 200, 300, 400, 500, 599]);
    let h = &d.edit.models[0].history;
    let Entry::BoneKeys { keys, .. } = &h.undo[h.cursor] else {
        panic!();
    };
    let touched: Vec<u32> = keys.iter().map(|k| k.0).collect();
    // Head 1 (previous 0, next the frame-100 key), then the frame-100 key
    // (previous 1, next the frame-200 key).
    let mut expect = vec![0, 1, t[1].0];
    let k100 = keys
        .iter()
        .find(|k| k.1.as_ref().is_some_and(|k| k.frame == 100))
        .unwrap();
    expect.push(k100.0);
    expect.sort();
    assert_eq!(touched, expect);
    run(&mut d, [Command::Undo]);
    let frames: Vec<u32> = track(&d.pmm.models[0].bone_keys, 1)
        .iter()
        .map(|k| k.1)
        .collect();
    assert_eq!(frames, [0, 100, 200, 300, 400, 500, 599]);
    validate(&d);
}

#[test]
fn morph_and_display_registers_push_no_undo() {
    // The morph buttons and button 438 clear the marks and register; only
    // bone edits are undoable.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SelectModel(1),
            Command::SetFrame(20),
            Command::SetMorph {
                morph: 2,
                value: 0.25,
            },
            Command::RegisterMorphKey(2),
        ],
    );
    let m = &d.pmm.models[1];
    let frames: Vec<u32> = track(&m.morph_keys, 2).iter().map(|k| k.1).collect();
    assert_eq!(frames, [0, 20, 200, 260]);
    let k = m.morph_keys.get(track(&m.morph_keys, 2)[1].0).unwrap();
    assert_eq!((k.value, k.allocated), (0.25, 1));
    assert!(!d.edit.models[1].history.undo_dirty);
    run(
        &mut d,
        [Command::SelectModel(0), Command::RegisterDisplayKey],
    );
    let m = &d.pmm.models[0];
    let frames: Vec<u32> = track(&m.display_keys, 0).iter().map(|k| k.1).collect();
    assert_eq!(frames, [0, 20, 200, 300, 450]);
    validate(&d);
}

#[test]
fn model_copy_and_paste() {
    // CopySelectedKeyframes then PasteSelectedKeyframes at another frame:
    // the bone keys land there by name and the undo entry covers them.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::ClearKeySelection,
            Command::SelectKeys {
                track: Track::Bone(1),
                from: 100,
                to: 200,
            },
            Command::Copy,
        ],
    );
    let clip = &d.edit.model_clipboard;
    assert_eq!(clip.bones.len(), 2);
    assert_eq!((clip.bones[0].frame, clip.bones[1].frame), (0, 100));
    run(&mut d, [Command::SetFrame(1000), Command::Paste]);
    let frames: Vec<u32> = track(&d.pmm.models[0].bone_keys, 1)
        .iter()
        .map(|k| k.1)
        .collect();
    assert_eq!(frames, [0, 100, 200, 300, 400, 500, 599, 1000, 1100]);
    assert!(d.edit.models[0].history.undo_dirty);
    run(&mut d, [Command::Undo]);
    let frames: Vec<u32> = track(&d.pmm.models[0].bone_keys, 1)
        .iter()
        .map(|k| k.1)
        .collect();
    assert_eq!(frames, [0, 100, 200, 300, 400, 500, 599]);
    validate(&d);
}

#[test]
fn pose_edits_and_frame_changes_are_undoable() {
    // PushBoneEditUndo snapshots the selected bones; SnapshotPoseBeforeFrameChange
    // all bones, once a bone is edited, before the seek. The frame edit (417)
    // sets the frame first, so the entry holds the new frame
    // (`RefreshAfterFrameApply`).
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SetFrame(0),
            Command::SetFrame(10),
            Command::SelectBones(vec![3]),
            Command::SetBonePose {
                bone: 3,
                translation: [0.0; 3],
                rotation: [0.0, 1.0, 0.0, 0.0],
            },
            Command::SetFrame(40),
        ],
    );
    assert_eq!(
        d.edit.models[0].history.cursor, 2,
        "no entry before the edit"
    );
    run(&mut d, [Command::Undo]);
    assert_eq!(d.pmm.timeline.current_frame, 40);
    assert_eq!(d.pmm.models[0].bone_pose[3].rotation, [0.0, 1.0, 0.0, 0.0]);
    // The pose before the edit is the one the seek to frame 10 left.
    let mut seeked = doc();
    run(&mut seeked, [Command::SetFrame(10)]);
    run(&mut d, [Command::Undo]);
    assert_eq!(
        d.pmm.models[0].bone_pose[3].rotation,
        seeked.pmm.models[0].bone_pose[3].rotation
    );
    assert_eq!(d.pmm.models[0].bone_pose[3].flags[1], 0);
    run(&mut d, [Command::Redo]);
    assert_eq!(d.pmm.models[0].bone_pose[3].rotation, [0.0, 1.0, 0.0, 0.0]);
    assert_eq!(d.pmm.models[0].bone_pose[3].flags[1], 1);
}

#[test]
fn the_ring_keeps_30_entries() {
    // AdvanceUndo wraps at 30; after 30 undos the cursor is back at the
    // latest entry and undo is disabled.
    let mut d = doc();
    run(&mut d, [Command::SelectBones(vec![0])]);
    for i in 0..31 {
        run(
            &mut d,
            [Command::SetBonePose {
                bone: 0,
                translation: [i as f32, 0.0, 0.0],
                rotation: [0.0, 0.0, 0.0, 1.0],
            }],
        );
    }
    for _ in 0..30 {
        run(&mut d, [Command::Undo]);
    }
    assert!(!d.edit.models[0].history.undo_dirty);
    // The 30 entries kept are the pushes before edits 1..30.
    assert_eq!(d.pmm.models[0].bone_pose[0].translation[0], 0.0);
}

#[test]
fn undo_is_model_mode_only() {
    let mut d = doc();
    run(&mut d, [Command::SelectCameraMode]);
    assert!(matches!(
        d.apply(Command::Undo),
        Err(Error::NotApplicable(_))
    ));
}

#[test]
fn new_scene_is_the_reset_state() {
    // ResetAppState over InitDefaults: no models, the default heads, frame 0.
    let mut d = doc();
    run(&mut d, [Command::NewScene]);
    let p = &d.pmm;
    assert!(p.models.is_empty() && d.models.is_empty());
    assert_eq!(p.settings.options, [1; 7]);
    // 45, then the refresh tail's `ReloadModels` copies the head key's 30
    // (the script oracle's camera/new.pmm).
    assert_eq!(p.settings.camera_fov, 30.0);
    let cam = &p.camera.heads()[0];
    assert_eq!(
        (cam.distance, cam.eye, cam.fov, cam.parent_model),
        (-45.0, [0.0, 10.0, 0.0], 30, -1)
    );
    assert_eq!(p.camera_state[5], -45.0);
    assert_eq!(p.light.heads()[0].color, [0.602; 3]);
    let s = &p.self_shadow.heads()[0];
    assert_eq!((s.mode, s.distance), (1, 0.01125));
    assert_eq!(p.gravity.heads()[0].acceleration, 9.8);
    assert_eq!(p.timeline.last_registered_frame, 0);
    assert_eq!(p.appearance.max_frame, 0);
    let saved = d.save().unwrap();
    let again = Document::load(&saved, |_| None).unwrap();
    assert_eq!(again.save().unwrap(), saved);
}

#[test]
fn a_vpd_pose_on_a_fixed_axis_bone_gets_the_twist_correction() {
    // LoadVpdFile (vpd_file.cpp 231-274): the VPD quaternion keeps its own
    // axis and takes the sign of its angle with the bone axis, then is
    // normalized. A quarter turn about -X, (-√½, 0, 0, √½), on a bone with
    // axis +X: sin(θ/2) = √(1 - ½) = √½ is negated (the axes oppose), x
    // becomes -√½ · -√½ = ½, and (½, 0, 0, √½) normalized is
    // (1/√3, 0, 0, √(2/3)).
    use mds_formats::text::Sjis;
    use mds_formats::vpd::{Bone, Vpd};
    let mut d = doc();
    let m = &mut d.pmm.models[0];
    let n = m.bone_names.len();
    let mut axes = vec![[0.0; 3]; n];
    axes[3] = [1.0, 0.0, 0.0];
    let mut bones = vec![(true, false, false); n];
    bones[3].1 = true;
    let s = mds_doc::model::Skeleton {
        pmx: true,
        bones,
        axes,
    };
    let h = 0.5f32.sqrt();
    let vpd = Vpd {
        model_name: Sjis::from_raw(m.name.raw.clone()),
        bones: vec![Bone {
            name: Sjis::from_raw(m.bone_names[3].raw.clone()),
            translation: [0.0; 3],
            rotation: [-h, 0.0, 0.0, h],
        }],
        crlf: true,
    }
    .write();
    let mut history = mds_doc::history::History::default();
    mds_doc::pose_file::load_vpd(m, &s, &mut history, &vpd).unwrap();
    let q = m.bone_pose[3].rotation;
    let want = [1.0 / 3f32.sqrt(), 0.0, 0.0, (2.0f32 / 3.0).sqrt()];
    for (a, b) in q.iter().zip(want) {
        assert!((a - b).abs() < 1e-6, "{q:?}");
    }
}
