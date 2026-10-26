use super::common::*;
use mds_app::editor::Editor;
use mds_app::ui::{bone_panel, Ctx};
use mds_doc::{Command, ModelFile};

/// `bones.txt` up to its first save: load, frame 10, the centre bone's pose, register (button
/// 500), frame 20, the upper body's rotation, register (Enter), frame 15, register display (438).
/// `src/app/pump_edit_keys.cpp:358` sends Enter as the button 500.
#[test]
fn bone_keys_register_like_the_script() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    frame(&mut e, 10);
    select_bone(&mut e, "センター");
    for (axis, v) in [
        (0, 1.0),
        (1, 2.0),
        (2, 3.0),
        (3, 10.0),
        (4, 20.0),
        (5, 30.0),
    ] {
        e.apply(Command::BoneReadoutEdit { axis, value: v })
            .unwrap();
    }
    run(&mut e, "ctl:500").unwrap();
    frame(&mut e, 20);
    select_bone(&mut e, "上半身");
    for (axis, v) in [(3, 0.0), (4, 45.0), (5, 0.0)] {
        e.apply(Command::BoneReadoutEdit { axis, value: v })
            .unwrap();
    }
    run(&mut e, "key:Enter@model-mode").unwrap();
    frame(&mut e, 15);
    run(&mut e, "ctl:438").unwrap();
    assert_saved(&e, "bones", "registered.pmm");
    assert!(e.modified);
}

#[test]
fn register_does_nothing_without_a_model_and_not_while_playing() {
    let mut e = editor();
    let before = e.doc.save().unwrap();
    run(&mut e, "ctl:500").unwrap();
    assert_eq!(e.doc.save().unwrap(), before, "no model: no-op");
    assert!(!e.modified);
    assert_eq!(
        run(&mut e, "ctl:438"),
        Err("no model selected".into()),
        "camera mode has no model to register"
    );
    load_model(&mut e, "chain8.pmx");
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:500", "key:Enter@model-mode", "ctl:438"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}

fn with_ctx<R>(e: &mut Editor, f: impl FnOnce(&mut Ctx) -> R) -> R {
    let mut status = String::new();
    f(&mut ctx(e, &mut status))
}

fn edit_mode(e: &Editor) -> i32 {
    e.doc.pmm.timeline.edit_mode
}

fn chain8() -> Editor {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    e.modified = false;
    e
}

fn selected_bones(e: &Editor) -> Vec<usize> {
    let m = e.doc.selected_model().unwrap();
    (0..m.bone_pose.len())
        .filter(|&i| m.bone_pose[i].flags[2] != 0)
        .collect()
}

/// Radios 490 to 493 store 0, 1, 4, 3 in `timeline.edit_mode` (`command_panel_toggles.cpp:612` to
/// `:650`: bone, box, move, rotate); the keys C, X and Z set bone-or-none, rotate (3) and move
/// (4) (`key_ladder.cpp:99`, `:259`, `:290`). None of them marks the scene modified.
#[test]
fn the_edit_mode_radios_and_keys() {
    let mut e = chain8();
    assert_eq!(edit_mode(&e), 0);
    for (id, mode) in [
        ("ctl:491", 1),
        ("ctl:492", 4),
        ("ctl:493", 3),
        ("ctl:490", 0),
        ("key:C", 2),
        ("key:C", 0),
        ("key:X", 3),
        ("key:Z", 4),
        ("key:C", 0),
    ] {
        run(&mut e, id).unwrap();
        assert_eq!(edit_mode(&e), mode, "{id}");
    }
    assert!(!e.modified);
    let saved = Document::load(&e.doc.save().unwrap(), |p| {
        std::fs::read(fixtures().join(p)).ok()
    })
    .unwrap();
    assert_eq!(saved.pmm.timeline.edit_mode, 0, "the PMM keeps it");
}

use mds_doc::Document;

/// The keys are gated on model mode in the C++ (`modelMode()`, `key_ladder.cpp`) and do nothing in
/// camera mode; the buttons of the hidden panel refuse.
#[test]
fn in_camera_mode_the_keys_do_nothing_and_the_buttons_refuse() {
    let mut e = chain8();
    e.apply(Command::SelectCameraMode).unwrap();
    let before = e.doc.save().unwrap();
    for id in ["key:C", "key:X", "key:Z", "key:A", "key:S"] {
        run(&mut e, id).unwrap();
    }
    for id in [
        "ctl:490", "ctl:494", "ctl:495", "ctl:496", "ctl:497", "ctl:501",
    ] {
        assert_eq!(run(&mut e, id), Err("model mode only".into()), "{id}");
    }
    assert_eq!(e.doc.save().unwrap(), before);
}

#[test]
fn the_edit_mode_actions_refuse_while_playing() {
    let mut e = chain8();
    run(&mut e, "ctl:408").unwrap();
    for id in [
        "ctl:490", "ctl:491", "ctl:492", "ctl:493", "ctl:494", "ctl:495", "ctl:496", "ctl:497",
        "ctl:498", "ctl:501", "key:C", "key:X", "key:Z", "key:A", "key:S",
    ] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}

/// Button 494 and key A (`command_panel_toggles.cpp:658`) select every bone of type 0 to 6 or
/// fixed axis, which is all of `chain8.pmx`, and check the bone radio. Button 501 and key S
/// (`command_frame_register.cpp:399`) keep the edited bones only and clear `selectedBone`.
#[test]
fn select_all_and_select_unregistered() {
    let mut e = chain8();
    let n = e.doc.selected_model().unwrap().bone_pose.len();
    for id in ["ctl:494", "key:A"] {
        e.apply(Command::SelectBones(vec![1])).unwrap();
        run(&mut e, "ctl:493").unwrap();
        e.modified = false;
        run(&mut e, id).unwrap();
        assert_eq!(selected_bones(&e), (0..n).collect::<Vec<_>>(), "{id}");
        assert_eq!(edit_mode(&e), 0, "{id}: the bone radio is checked");
        assert!(!e.modified, "{id}: selection is no edit");
    }

    let bone = (n - 1) as u32;
    e.apply(Command::SelectBones(vec![bone])).unwrap();
    e.apply(Command::SetBonePose {
        bone,
        translation: [0.0, 1.0, 0.0],
        rotation: [0.0, 0.0, 0.0, 1.0],
    })
    .unwrap();
    for id in ["ctl:501", "key:S"] {
        run(&mut e, "ctl:494").unwrap();
        run(&mut e, "ctl:492").unwrap();
        e.modified = false;
        run(&mut e, id).unwrap();
        assert_eq!(selected_bones(&e), [bone as usize], "{id}");
        assert_eq!(e.doc.selected_model().unwrap().selection.selected_bone, -1);
        assert_eq!(edit_mode(&e), 0, "{id}");
        assert!(!e.modified, "{id}");
    }
}

/// Button 495 (`bone_pose_edit.cpp:25` to `:143`): bone 0 loses its Y and its rotation, a bone
/// with a parent becomes the identity and is marked edited.
#[test]
fn reset_clears_the_selected_poses() {
    let mut e = chain8();
    let q = [0.0, 0.247_403_96, 0.0, 0.968_912_4];
    for (bone, t) in [(0, [1.0, 2.0, 3.0]), (3, [0.5, 0.0, 0.0])] {
        e.apply(Command::SetBonePose {
            bone,
            translation: t,
            rotation: q,
        })
        .unwrap();
    }
    e.apply(Command::SelectBones(vec![0, 3])).unwrap();
    run(&mut e, "ctl:495").unwrap();
    let b = &e.doc.selected_model().unwrap().bone_pose;
    assert_eq!(b[0].translation, [1.0, 0.0, 3.0]);
    assert_eq!(b[0].rotation, [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(
        (b[3].translation, b[3].rotation),
        ([0.0; 3], [0.0, 0.0, 0.0, 1.0])
    );
    assert_eq!(b[3].flags[1], 1);
    assert!(e.modified);
    e.apply(Command::Undo).unwrap();
    let b = &e.doc.selected_model().unwrap().bone_pose;
    assert_eq!(
        (b[0].translation, b[3].translation),
        ([1.0, 2.0, 3.0], [0.5, 0.0, 0.0])
    );
}

/// Buttons 496 to 498 (`bone_pose_clipboard.cpp:34` to `:292`): copy keeps the selected poses,
/// paste puts each on the bone of its name and selects it; reverse paste negates x of the
/// translation and y and z of the rotation, on the bone itself when its name has no 左 or 右.
#[test]
fn copy_paste_and_reverse_paste() {
    let mut e = chain8();
    let q = [0.1, 0.2, 0.3, 0.927_361_8];
    e.apply(Command::SetBonePose {
        bone: 2,
        translation: [1.0, 2.0, 3.0],
        rotation: q,
    })
    .unwrap();
    e.apply(Command::SelectBones(vec![2])).unwrap();
    e.modified = false;
    run(&mut e, "ctl:496").unwrap();
    assert!(!e.modified, "copy is no edit");
    e.apply(Command::SetBonePose {
        bone: 2,
        translation: [0.0; 3],
        rotation: [0.0, 0.0, 0.0, 1.0],
    })
    .unwrap();
    e.apply(Command::SelectBones(vec![5])).unwrap();
    run(&mut e, "ctl:497").unwrap();
    let m = e.doc.selected_model().unwrap();
    assert_eq!(
        (m.bone_pose[2].translation, m.bone_pose[2].rotation),
        ([1.0, 2.0, 3.0], q)
    );
    assert_eq!(selected_bones(&e), [2]);
    assert_eq!(e.doc.selected_model().unwrap().selection.selected_bone, 2);
    run(&mut e, "ctl:498").unwrap();
    let p = &e.doc.selected_model().unwrap().bone_pose[2];
    assert_eq!(p.translation, [-1.0, 2.0, 3.0]);
    assert_eq!(p.rotation, [0.1, -0.2, -0.3, 0.927_361_8]);
    assert!(e.modified);
}

/// With nothing copied, paste does nothing (`bone_pose_clipboard.cpp:90`).
#[test]
fn paste_without_a_copy_changes_nothing() {
    let mut e = chain8();
    e.modified = false;
    let before = e.doc.save().unwrap();
    run(&mut e, "ctl:497").unwrap();
    run(&mut e, "ctl:498").unwrap();
    assert_eq!(e.doc.save().unwrap(), before);
}

/// Combos 449 and 450 (`command_dispatch.cpp:203` to `:293`): entry 0 is "non", entry n the model
/// whose `comboSelIndex` is n. Attaching with no parent before clears the camera position and
/// rotation and takes bone 0; detaching puts the camera on the parent bone, distance -20, no
/// rotation.
#[test]
fn the_camera_parent_combos() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    e.apply(Command::SelectCameraMode).unwrap();
    e.apply(Command::SetCamera {
        position: [1.0, 2.0, 3.0],
        rotation: [0.1, 0.2, 0.3],
        distance: -45.0,
        fov: 30.0,
        perspective: true,
    })
    .unwrap();
    assert_eq!(with_ctx(&mut e, |c| bone_panel::camera_parent_entry(c)), 0);
    with_ctx(&mut e, |c| bone_panel::set_camera_parent_model(c, 1)).unwrap();
    let p = &e.doc.pmm;
    assert_eq!(
        (
            p.appearance.camera_parent_model,
            p.appearance.camera_parent_bone
        ),
        (0, 0)
    );
    assert_eq!(p.camera_state[..3], [0.0; 3]);
    assert_eq!(p.camera_state[6..], [0.0; 3]);
    assert_eq!(with_ctx(&mut e, |c| bone_panel::camera_parent_entry(c)), 1);

    with_ctx(&mut e, |c| bone_panel::set_camera_parent_bone(c, 3)).unwrap();
    assert_eq!(e.doc.pmm.appearance.camera_parent_bone, 3);
    assert!(with_ctx(&mut e, |c| bone_panel::set_camera_parent_bone(c, 99)).is_err());
    assert!(with_ctx(&mut e, |c| bone_panel::set_camera_parent_model(c, 9)).is_err());

    with_ctx(&mut e, |c| bone_panel::set_camera_parent_model(c, 0)).unwrap();
    let p = &e.doc.pmm;
    let ModelFile::Pmx(pmx) = &e.doc.models[0] else {
        panic!()
    };
    assert_eq!(p.appearance.camera_parent_model, -1);
    assert_eq!(p.camera_state[5], -20.0);
    assert_eq!(p.camera_state[6..], [0.0; 3]);
    assert_eq!(p.camera_state[..3], pmx.bones[3].position);
}

#[test]
fn the_camera_parent_combos_are_for_camera_mode_and_a_stopped_scene() {
    let mut e = chain8();
    assert_eq!(
        with_ctx(&mut e, |c| bone_panel::set_camera_parent_model(c, 1)),
        Err("camera mode only".into())
    );
    e.apply(Command::SelectCameraMode).unwrap();
    run(&mut e, "ctl:408").unwrap();
    assert_eq!(
        with_ctx(&mut e, |c| bone_panel::set_camera_parent_model(c, 1)),
        Err("not while playing".into())
    );
}
