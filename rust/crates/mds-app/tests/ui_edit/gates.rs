//! Mode gates, playback and the rotation reset (menu 302).

use super::{open, run};
use mds_doc::{Command, SelectAll};

/// A quarter turn about Y.
const TURNED: [f32; 4] = [0.0, 0.6, 0.0, 0.8];

#[test]
fn select_all_follows_the_mode_of_the_menu() {
    let mut e = open("swing600.pmm");
    let before = e.doc.save().unwrap();
    // RestorePlaybackMenus grays 237..241 in model mode (playback_state.cpp:94 to :113).
    for id in ["menu:237", "menu:238", "menu:239", "menu:240", "menu:241"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not in this mode")));
    }
    assert!(e.doc.save().unwrap() == before && !e.modified);
    run(&mut e, "menu:217").unwrap();
    // `SelectFrameGroup` (`frame_line_edit.cpp:536` to the end of its cases) never sets
    // `SceneModified`. `Editor` still marks it (editor.rs, slice appfix2), so the rule is read
    // from the document.
    for what in [SelectAll::Bone, SelectAll::Display, SelectAll::Morph] {
        assert!(!Command::SelectAll(what).marks_modified(), "{what:?}");
    }

    // and 217, 218, 220 in camera mode.
    e.apply(Command::SelectCameraMode).unwrap();
    let before = e.doc.save().unwrap();
    for id in ["menu:217", "menu:218", "menu:220"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not in this mode")));
    }
    assert!(e.doc.save().unwrap() == before);
    run(&mut e, "menu:237").unwrap();
}

#[test]
fn nothing_runs_while_playing() {
    let mut e = open("swing600.pmm");
    run(&mut e, "ctl:408").unwrap();
    for id in [
        "menu:217", "menu:255", "key:J", "menu:302", "menu:300", "menu:222", "menu:219", "key:D",
        "menu:242", "menu:251", "key:R", "menu:252", "menu:250", "key:F",
    ] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}

#[test]
fn the_frame_line_menu_and_its_key_do_the_same() {
    for (menu, key) in [
        ("menu:255", "key:I"),
        ("menu:256", "key:K"),
        ("menu:257", "key:U"),
        ("menu:258", "key:J"),
    ] {
        let (mut a, mut b) = (open("swing600.pmm"), open("swing600.pmm"));
        for e in [&mut a, &mut b] {
            e.apply(Command::SetFrame(30)).unwrap();
        }
        run(&mut a, menu).unwrap();
        run(&mut b, key).unwrap();
        assert!(a.doc.save().unwrap() == b.doc.save().unwrap(), "{menu}");
    }
}

/// `case MDS_CMD_RESET_BONE_CAMERA_ROTATION` (`src/window/command_view_menu.cpp:1864`), camera
/// path: pitch, yaw and roll to 0, the rest of the camera untouched.
#[test]
fn reset_rotation_in_camera_mode() {
    let mut e = open("camera3.pmm");
    e.apply(Command::SelectCameraMode).unwrap();
    let s = e.doc.pmm.camera_state;
    e.apply(Command::SetCamera {
        position: [s[0], s[1], s[2]],
        rotation: [0.1, -0.2, 0.3],
        distance: s[5],
        fov: 40.0,
        perspective: true,
    })
    .unwrap();
    e.modified = false;
    run(&mut e, "menu:302").unwrap();
    let after = e.doc.pmm.camera_state;
    assert_eq!(&after[6..], &[0.0; 3]);
    assert_eq!(&after[..6], &s[..6]);
    assert_eq!(e.doc.pmm.settings.camera_fov, 40.0);
    assert!(e.modified, "SceneModified = 1 (command_view_menu.cpp:1870)");
}

/// The bone path: `PushBoneEditUndo`, identity rotation (`D3DXQuaternionRotationMatrix` of the
/// identity is (0, 0, 0, 1)), the translation as it was, the bone flagged edited; no selected
/// bone (`selectedBone == -1`) returns first.
#[test]
fn reset_rotation_of_the_selected_bone() {
    let mut e = open("swing600.pmm");
    e.apply(Command::SelectBones(vec![])).unwrap();
    assert_eq!(e.doc.pmm.models[0].selection.selected_bone, -1);
    e.modified = false;
    run(&mut e, "menu:302").unwrap();
    assert!(!e.modified, "no bone is selected");

    e.apply(Command::SelectBones(vec![1])).unwrap();
    let pose = |e: &mut mds_app::editor::Editor| e.doc.pmm.models[0].bone_pose[1].clone();
    e.apply(Command::SetBonePose {
        bone: 1,
        translation: [1.0, 2.0, 3.0],
        rotation: TURNED,
    })
    .unwrap();
    run(&mut e, "menu:302").unwrap();
    let p = pose(&mut e);
    assert_eq!(p.rotation, [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(p.translation, [1.0, 2.0, 3.0]);
    assert_eq!(p.flags[1], 1);

    run(&mut e, "ctl:400").unwrap();
    assert_eq!(pose(&mut e).rotation, TURNED, "the reset is one undo entry");
}
