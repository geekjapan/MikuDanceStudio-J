use crate::support::{camera_mode, model_mode, run, saved, with_ctx};
use mds_app::editor::Editor;
use mds_app::ui::camera_panel::{commit_fov, commit_readout, readout_text, set_fov, set_readout};
use mds_doc::Command;

/// `kPiLit` of `ui_edit_commit.cpp`.
const PI_LIT: f64 = 3.141592025756836;

fn state(e: &Editor) -> [f32; 9] {
    e.doc.pmm.camera_state
}

#[test]
fn the_perspective_toggle_flips_the_flag_and_nothing_else() {
    // `case panel::kPerspectiveCheckbox`, command_frame_edit.cpp:1627.
    let mut e = camera_mode();
    let (before, fov) = (state(&e), e.doc.pmm.settings.camera_fov);
    let p0 = e.doc.pmm.camera_perspective;
    run(&mut e, "ctl:446").unwrap();
    assert_eq!(e.doc.pmm.camera_perspective, u8::from(p0 == 0));
    run(&mut e, "ctl:446").unwrap();
    assert_eq!(e.doc.pmm.camera_perspective, p0);
    assert_eq!((state(&e), e.doc.pmm.settings.camera_fov), (before, fov));
}

#[test]
fn the_view_angle_is_an_integer_from_the_first_seven_characters() {
    // ui_hscroll.cpp:232 stores the slider position; ui_edit_commit.cpp:324 `atol` of
    // `GetWindowTextA(edit, text, 8)`.
    let mut e = camera_mode();
    with_ctx(&mut e, |c| set_fov(c, 125)).0.unwrap();
    assert_eq!(e.doc.pmm.settings.camera_fov, 125.0);
    for (text, want) in [
        ("40", 40.0),
        (" 77x", 77.0),
        ("12.9", 12.0),
        ("12345678", 1234567.0),
        ("x", 0.0),
    ] {
        with_ctx(&mut e, |c| commit_fov(c, text)).0.unwrap();
        assert_eq!(e.doc.pmm.settings.camera_fov, want, "{text:?}");
    }
}

#[test]
fn reset_puts_the_camera_back() {
    // command_panel_toggles.cpp:331: X, Z and the angles to 0; Y 10 and the distance -45 when no
    // model carries the camera, else both 0.
    let mut e = camera_mode();
    for field in 0..7 {
        with_ctx(&mut e, |c| set_readout(c, field, 7.0)).0.unwrap();
    }
    run(&mut e, "ctl:451").unwrap();
    let s = state(&e);
    assert_eq!(
        ([s[0], s[1], s[2]], s[5], [s[6], s[7], s[8]]),
        ([0.0, 10.0, 0.0], -45.0, [0.0; 3])
    );
    for field in 0..7 {
        with_ctx(&mut e, |c| set_readout(c, field, 7.0)).0.unwrap();
    }
    e.doc.pmm.appearance.camera_parent_model = 2;
    run(&mut e, "ctl:451").unwrap();
    let s = state(&e);
    assert_eq!(
        ([s[0], s[1], s[2]], s[5], [s[6], s[7], s[8]]),
        ([0.0; 3], 0.0, [0.0; 3])
    );
}

#[test]
fn register_stores_the_camera_at_the_current_frame() {
    // command_panel_toggles.cpp:391 (RegisterCameraState at currentFrame).
    let mut e = camera_mode();
    e.seek(30).unwrap();
    with_ctx(&mut e, |c| set_readout(c, 0, 1.5)).0.unwrap();
    with_ctx(&mut e, |c| set_readout(c, 6, 25.0)).0.unwrap();
    let before = e.doc.pmm.camera.records().len();
    run(&mut e, "ctl:452").unwrap();
    let cam = &e.doc.pmm.camera;
    let key = cam
        .records()
        .iter()
        .map(|(_, k)| k)
        .chain(cam.heads())
        .find(|k| k.frame == 30)
        .unwrap();
    assert_eq!((key.eye[0], key.distance), (1.5, -25.0));
    assert!(cam.records().len() >= before);
    assert!(e.modified);
}

#[test]
fn the_readout_edits_set_the_camera_as_the_c_code_stores_them() {
    // `CommitEditControlTail`, ui_edit_commit.cpp:116 to :330: pitch is the negated X, the
    // distance is stored negated, and Z is mirrored when a model carries the camera.
    let mut e = camera_mode();
    for (field, text) in [
        (0, "1.25"),
        (1, "-2"),
        (2, "3"),
        (3, "10"),
        (4, "-20"),
        (5, "5"),
        (6, "25"),
    ] {
        with_ctx(&mut e, |c| commit_readout(c, field, text))
            .0
            .unwrap();
    }
    let s = state(&e);
    assert_eq!([s[0], s[1], s[2]], [1.25, -2.0, 3.0]);
    assert_eq!(s[5], -25.0);
    let rad = |deg: f64| (deg * PI_LIT / 180.0) as f32;
    assert_eq!(
        [s[6], s[7], s[8]],
        [(-10.0 * PI_LIT / 180.0) as f32, rad(-20.0), rad(5.0)]
    );
    e.doc.pmm.appearance.camera_parent_model = 1;
    with_ctx(&mut e, |c| commit_readout(c, 2, "3")).0.unwrap();
    assert_eq!(state(&e)[2], -3.0);
    with_ctx(&mut e, |c| commit_readout(c, 0, "junk"))
        .0
        .unwrap();
    assert_eq!(state(&e)[0], 0.0, "atof of text without a number");
}

#[test]
fn the_readout_shows_what_post_view_refresh_prints() {
    // ui_view_refresh.cpp:128 to :176: %1.2f, %1.1f of the degrees, the distance negated.
    let mut e = camera_mode();
    e.apply(Command::SetCamera {
        position: [1.234, -5.678, 9.0],
        rotation: [
            (-30.0 * PI_LIT / 180.0) as f32,
            (45.0 * PI_LIT / 180.0) as f32,
            0.0,
        ],
        distance: -45.0,
        fov: 30.0,
        perspective: true,
    })
    .unwrap();
    let shown = |e: &mut Editor| -> Vec<String> { (0..7).map(|f| readout_text_of(e, f)).collect() };
    assert_eq!(
        shown(&mut e),
        ["1.23", "-5.68", "9.00", "30.0", "45.0", "0.0", "45.00"]
    );
    e.doc.pmm.appearance.camera_parent_model = 0;
    assert_eq!(shown(&mut e)[2], "-9.00");
    assert_eq!(
        shown(&mut e)[6],
        "0.00",
        "a parented camera shows 0 for the distance"
    );
}

fn readout_text_of(e: &mut Editor, field: usize) -> String {
    with_ctx(e, |c| readout_text(c, field)).0
}

#[test]
fn the_reset_buttons_zero_one_value() {
    // BonePosEdit and BoneRotEdit in display mode (command_frame_register.cpp:281, :307) and
    // button 543 (:677).
    for (id, field) in [
        ("ctl:537", 0),
        ("ctl:538", 1),
        ("ctl:539", 2),
        ("ctl:540", 3),
        ("ctl:541", 4),
        ("ctl:542", 5),
        ("ctl:543", 6),
    ] {
        let mut e = camera_mode();
        for f in 0..7 {
            with_ctx(&mut e, |c| set_readout(c, f, 3.0)).0.unwrap();
        }
        let before = state(&e);
        run(&mut e, id).unwrap();
        let after = state(&e);
        let slot = [0, 1, 2, 6, 7, 8, 5][field];
        for i in 0..9 {
            match i == slot {
                true => assert_eq!(after[i], 0.0, "{id}"),
                false => assert_eq!(after[i], before[i], "{id} moved {i}"),
            }
        }
    }
}

#[test]
fn the_readout_edits_a_bone_in_model_mode() {
    // `CommitEditControlTail` for a bone: ui_edit_commit.cpp:122 to :245. The edit goes through
    // `Command::BoneReadoutEdit`, so the document equals one that took the command directly.
    let mut e = model_mode();
    e.apply(Command::SelectBones(vec![1])).unwrap();
    let mut reference = model_mode();
    reference.apply(Command::SelectBones(vec![1])).unwrap();
    for (field, text) in [(0, "1.5"), (1, "-2"), (3, "30"), (4, "-40"), (5, "10")] {
        with_ctx(&mut e, |c| commit_readout(c, field, text))
            .0
            .unwrap();
        reference
            .apply(Command::BoneReadoutEdit {
                axis: field as u8,
                value: text.parse().unwrap(),
            })
            .unwrap();
    }
    assert_eq!(saved(&e), saved(&reference));
    let pose = &e.doc.pmm.models[0].bone_pose[1];
    assert_eq!(&pose.translation[..2], &[1.5, -2.0]);
    let shown: Vec<_> = [0, 1, 2, 3, 4, 5]
        .iter()
        .map(|&f| readout_text_of(&mut e, f))
        .collect();
    assert_eq!(&shown[..2], ["1.50", "-2.00"]);
    for (text, want) in shown[3..].iter().zip([30.0, -40.0, 10.0]) {
        assert!(
            (text.parse::<f64>().unwrap() - want).abs() <= 0.1,
            "{shown:?}"
        );
    }
    // The distance edit exists in camera mode only (`&& cameraMode`, :561).
    let before = saved(&e);
    with_ctx(&mut e, |c| commit_readout(c, 6, "9")).0.unwrap();
    run(&mut e, "ctl:543").unwrap();
    assert_eq!(saved(&e), before);
}

#[test]
fn the_reset_buttons_zero_a_bone_axis_in_model_mode() {
    let mut e = model_mode();
    e.apply(Command::SelectBones(vec![1])).unwrap();
    for f in 0..6 {
        with_ctx(&mut e, |c| commit_readout(c, f, "20")).0.unwrap();
    }
    let before = e.doc.pmm.models[0].bone_pose[1].translation;
    run(&mut e, "ctl:538").unwrap();
    let t = e.doc.pmm.models[0].bone_pose[1].translation;
    assert_eq!((t[0], t[1], t[2]), (before[0], 0.0, before[2]));
    // BoneRotEdit composes Rz * Rx * Ry with the edited axis 0 and the others from the readout.
    let (rx, rz) = (readout_text_of(&mut e, 3), readout_text_of(&mut e, 5));
    run(&mut e, "ctl:541").unwrap();
    assert_eq!(readout_text_of(&mut e, 4), "0.0");
    for (axis, was) in [(3, rx), (5, rz)] {
        let now: f64 = readout_text_of(&mut e, axis).parse().unwrap();
        assert!(
            (now - was.parse::<f64>().unwrap()).abs() <= 0.15,
            "axis {axis}: {was} -> {now}"
        );
    }
}

#[test]
fn a_bone_edit_without_a_selected_bone_does_nothing() {
    let mut e = model_mode();
    e.apply(Command::SelectBones(vec![])).unwrap();
    let before = saved(&e);
    run(&mut e, "ctl:537").unwrap();
    with_ctx(&mut e, |c| commit_readout(c, 0, "4")).0.unwrap();
    assert_eq!(saved(&e), before);
    assert_eq!(readout_text_of(&mut e, 0), "-----");
}

#[test]
fn the_buttons_are_refused_while_playing_and_the_camera_ones_outside_camera_mode() {
    // StartPlayback greys 415..=468 and 536..=550 (playback_state.cpp:331 to :340).
    let mut e = model_mode();
    run(&mut e, "ctl:408").unwrap();
    for id in [
        "ctl:446", "ctl:451", "ctl:452", "ctl:537", "ctl:541", "ctl:543",
    ] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:446", "ctl:451", "ctl:452"] {
        assert_eq!(run(&mut e, id), Err("camera mode only".into()), "{id}");
    }
}

/// Check box 535 flips `followCameraEnabled` as menu 247 does (`command_frame_register.cpp:594`
/// to `:629`): on zeroes the view offset (camera_state 3 and 4); the scene stays unmodified.
#[test]
fn the_follow_box_flips_camera_tracking() {
    let mut e = model_mode();
    e.apply(Command::SetCamera {
        position: [0.0; 3],
        rotation: [0.0; 3],
        distance: -45.0,
        fov: 30.0,
        perspective: true,
    })
    .unwrap();
    e.doc.pmm.camera_state[3] = 5.0;
    e.doc.pmm.camera_state[4] = 6.0;
    e.modified = false;
    let follow = |e: &Editor| e.doc.pmm.appearance.follow_camera;
    assert_eq!(follow(&e), 0);
    run(&mut e, "ctl:535").unwrap();
    assert_eq!(follow(&e), 1);
    assert_eq!(state(&e)[3..5], [0.0, 0.0]);
    assert!(!e.modified);
    run(&mut e, "ctl:535").unwrap();
    assert_eq!(follow(&e), 0);
    let bytes = saved(&e);
    assert_eq!(
        mds_doc::Document::load(&bytes, |_| None)
            .unwrap()
            .pmm
            .appearance
            .follow_camera,
        0
    );
}
