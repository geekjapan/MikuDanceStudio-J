//! The physics menus, the floor, the physics check box, and which commands
//! set `SceneModified`. Each expectation is read off the C++ named in the
//! test's comment.

use mds_doc::{Command, Document, Error, SelectAll};
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// swing600.pmm: slot 0 is chain8_ik.pmx; bones 5..7 have rigid bodies.
fn doc() -> Document {
    let data = std::fs::read(dir().join("swing600.pmm")).unwrap();
    Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

#[test]
fn the_physics_menus_set_the_mode_and_modes_1_to_3_settle() {
    // command_view_menu.cpp 1048-1110: 265 -> 1, 269 -> 2, 270 -> 3 with
    // `PhysicsResetPending() = 1`; 272 -> 0 without it.
    let mut d = doc();
    for (mode, settles) in [(1, true), (2, true), (3, true), (0, false)] {
        d.edit.physics_reset_pending = false;
        d.apply(Command::SetPhysicsMode(mode)).unwrap();
        assert_eq!(d.pmm.physics.playback_mode, mode);
        assert_eq!(d.edit.physics_reset_pending, settles, "mode {mode}");
    }
    d.edit.physics_reset_pending = false;
    assert!(d.apply(Command::SetPhysicsMode(4)).is_err());
    assert_eq!(d.pmm.physics.playback_mode, 0);
    assert!(!d.edit.physics_reset_pending);
}

#[test]
fn the_floor_menu_sets_the_saved_flag() {
    // command_view_menu.cpp 1437-1452: `floorVisible` 0 or 1.
    let mut d = doc();
    d.apply(Command::SetFloorVisible(false)).unwrap();
    assert_eq!(d.pmm.appearance.floor_visible, 0);
    d.apply(Command::SetFloorVisible(true)).unwrap();
    assert_eq!(d.pmm.appearance.floor_visible, 1);
}

/// The `physicsDisabled` byte that "register" stores for rigid-body bone 5
/// at frame 7 in physics mode 1.
fn registered_physics_disabled(checkbox: bool) -> u8 {
    let mut d = doc();
    d.pmm.physics.playback_mode = 1;
    for c in [
        Command::SetPhysicsCheckbox(checkbox),
        Command::SetFrame(7),
        Command::SelectBones(vec![5]),
        Command::RegisterBoneKeys,
    ] {
        d.apply(c).unwrap();
    }
    assert_eq!(d.edit.physics_checkbox, checkbox);
    let pool = &d.pmm.models[0].bone_keys;
    let k = pool
        .records()
        .iter()
        .map(|(_, k)| k)
        .find(|k| k.frame == 7 && k.allocated != 0)
        .expect("the key at frame 7");
    k.physics_disabled
}

#[test]
fn register_stores_the_physics_check_box_negated() {
    // model_keyframe_edit.cpp 276-282: a rigid-body bone's key gets
    // physicsDisabled 0 when 499 is checked, else 1.
    assert_eq!(registered_physics_disabled(true), 0);
    assert_eq!(registered_physics_disabled(false), 1);
}

#[test]
fn the_camera_menus_write_position_rotation_and_distance() {
    // command_view_menu.cpp 1764-1770 (300) and 1864-1868 (302): the
    // camera-mode paths write the position, pitch, yaw, roll and distance.
    let mut d = doc();
    let cmd = Command::SetCameraFromMenu {
        position: [1.0, 2.0, 3.0],
        rotation: [0.25, 0.5, 0.75],
        distance: -40.0,
    };
    assert!(matches!(d.apply(cmd.clone()), Err(Error::NotApplicable(_))));
    d.apply(Command::SelectCameraMode).unwrap();
    let (fov, perspective) = (d.pmm.settings.camera_fov, d.pmm.camera_perspective);
    let offset = [d.pmm.camera_state[3], d.pmm.camera_state[4]];
    d.apply(cmd).unwrap();
    let s = d.pmm.camera_state;
    assert_eq!([s[0], s[1], s[2], s[5]], [1.0, 2.0, 3.0, -40.0]);
    assert_eq!([s[6], s[7], s[8]], [0.25, 0.5, 0.75]);
    assert_eq!([s[3], s[4]], offset);
    assert_eq!(
        (d.pmm.settings.camera_fov, d.pmm.camera_perspective),
        (fov, perspective)
    );
}

#[test]
fn the_self_shadow_slider_sets_the_distance_only() {
    // ui_hscroll.cpp 263-266: `(10000 - pos) / 100000.0` in double, stored
    // as float; the mode radio is not touched.
    let mut d = doc();
    let mode = d.edit.self_shadow_mode;
    d.apply(Command::SetSelfShadowSlider(8000)).unwrap();
    assert_eq!(d.pmm.physics_interval, (2000.0f64 / 100000.0) as f32);
    assert_eq!(d.edit.self_shadow_mode, mode);
    d.apply(Command::SetSelfShadowSlider(10000)).unwrap();
    assert_eq!(d.pmm.physics_interval, 0.0);
}

#[test]
fn scene_modified_follows_the_cpp_handlers() {
    let camera = Command::SetCamera {
        position: [0.0; 3],
        rotation: [0.0; 3],
        distance: 45.0,
        fov: 30.0,
        perspective: true,
    };
    let marked = [
        // command_view_menu.cpp 1771 (300), 1870 (302).
        Command::SetCameraFromMenu {
            position: [0.0; 3],
            rotation: [0.0; 3],
            distance: 45.0,
        },
        // ui_hscroll.cpp 270.
        Command::SetSelfShadowSlider(8000),
        // command_frame_edit.cpp 1356.
        Command::CloseOutsideParentDialog,
    ];
    let unmarked = [
        // The camera panel and edit 561 (`CommitEditControl`,
        // ui_edit_commit.cpp, no `SceneModified`).
        camera,
        Command::SetSelfShadow {
            mode: 1,
            distance: 0.02,
        },
        // frame_line_edit.cpp 536 (`SelectFrameGroup`).
        Command::SelectAll(SelectAll::Bone),
        // bone_pose_edit.cpp 25, bone_pose_clipboard.cpp 89, 175.
        Command::ResetBonePose,
        Command::PasteBonePose { mirror: false },
        Command::PasteBonePose { mirror: true },
        // command_view_menu.cpp 1464-1495.
        Command::SetOutlineColor([1, 2, 3]),
        // The 530 check box, the physics check box 499, the physics menus
        // (1048-1110) and the floor (1437-1452).
        Command::SetAutoInterpolation(false),
        Command::SetPhysicsCheckbox(false),
        Command::SetPhysicsMode(1),
        Command::SetFloorVisible(false),
        // oni_skeleton_pump.cpp 510-524.
        Command::RegisterKinectCapture {
            frame: 0,
            samples: 0,
            keys: Vec::new(),
        },
    ];
    let d = doc();
    for c in &marked {
        assert!(c.marks_modified() && d.marks_modified(c), "{c:?}");
    }
    for c in &unmarked {
        assert!(!c.marks_modified() && !d.marks_modified(c), "{c:?}");
    }
}
