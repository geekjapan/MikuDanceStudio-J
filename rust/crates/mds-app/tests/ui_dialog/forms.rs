//! The dialogs without a script oracle: the value each OK reads, what Cancel leaves, and the
//! gates of the actions.

use super::Rig;
use mds_app::ui::dialog::{self, AviFormat, AviSettings};
use mds_doc::Command;

#[test]
fn cancel_changes_nothing() {
    let mut rig = Rig::open("swing600.pmm");
    let before = rig.saved();
    rig.fill("dlg:IDD_CENTER_POSITION_BIAS", &["5", "5", "5"]);
    rig.cancel();
    assert_eq!(rig.shown(), None);
    assert!(rig.saved() == before && !rig.editor.modified);
}

#[test]
fn a_dialog_opens_again_with_the_document_not_with_the_last_text() {
    let mut rig = Rig::open("swing600.pmm");
    rig.fill("dlg:IDD_REGISTER_BLINKING", &["12", "34"]);
    rig.cancel();
    rig.run("dlg:IDD_REGISTER_BLINKING").unwrap();
    assert_eq!(rig.field(0), "");
}

/// `ScreenSizeDlgProc` (`src/window/command_file_menu.cpp:436`): the edits start at the render
/// size, and a size over the device's largest texture keeps the dialog.
#[test]
fn screen_size() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("dlg:IDD_SCREEN_SIZE").unwrap();
    let s = &rig.editor.doc.pmm.settings;
    let (w, h) = (s.render_width, s.render_height);
    assert_eq!(
        (rig.field(0), rig.field(1)),
        (format!("{w:3}"), format!("{h:3}"))
    );
    rig.editor.doc.edit.max_texture_size = Some([1024, 1024]);
    rig.type_into(0, "2000");
    assert!(rig.ok().is_err());
    assert_eq!(rig.shown(), Some("IDD_SCREEN_SIZE"));
    assert_eq!(rig.editor.doc.pmm.settings.render_width, w);
    rig.type_into(0, "640");
    rig.type_into(1, "360abc");
    rig.ok().unwrap();
    let s = &rig.editor.doc.pmm.settings;
    assert_eq!((s.render_width, s.render_height), (640, 360));
    assert_eq!(rig.shown(), None);
}

/// `AviOutDlgProc` (`command_file_menu.cpp:556`): an end frame below the start frame is refused.
#[test]
fn avi_output_hands_the_recorder_its_settings() {
    let mut rig = Rig::open("swing600.pmm");
    rig.fill("dlg:IDD_AVI_OUTPUT", &["10", "5", "30"]);
    assert!(rig.ok().is_err());
    assert_eq!(dialog::take_avi_request(&rig.egui), None);
    rig.type_into(1, "90");
    rig.type_into(2, "0");
    assert!(rig.ok().is_err(), "the frame rate must be above 0");
    rig.type_into(2, "29.97");
    rig.with(|c| dialog::set_pick(c, 1));
    rig.ok().unwrap();
    let s = &rig.editor.doc.pmm.settings;
    let want = AviSettings {
        start_frame: 10,
        end_frame: 90,
        fps: 29.97,
        width: s.render_width,
        height: s.render_height,
        include_wave: false,
        format: AviFormat::PngSequence,
    };
    assert_eq!(dialog::take_avi_request(&rig.egui), Some(want));
    assert_eq!(dialog::take_avi_request(&rig.egui), None, "once");
}

/// `EdgeThicknessEditSubclassProc` reads 7 characters of the edit at Enter.
#[test]
fn edge_thickness() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("dlg:IDD_EDGE_THICKNESS").unwrap();
    let before = rig.editor.doc.selected_model().unwrap().edge_scale;
    assert_eq!(rig.field(0), format!("{before:3.2}"));
    rig.type_into(0, "1.2345678");
    rig.ok().unwrap();
    assert_eq!(
        rig.editor.doc.selected_model().unwrap().edge_scale,
        1.23456f32
    );
}

fn camera_rig() -> Rig {
    let mut rig = Rig::open("camera3.pmm");
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    rig
}

/// Typing into the camera numeric dialog equals typing into the camera panel's boxes, which the
/// `camera.txt` oracle covers: pitch is the negated X, the stored distance the negated box.
#[test]
fn camera_numeric_input() {
    let mut rig = camera_rig();
    rig.fill(
        "dlg:IDD_CAMERA_NUMERIC_INPUT",
        &["1", "2", "3", "10", "-20", "5", "25"],
    );
    rig.ok().unwrap();
    let pi = 3.141592025756836f64;
    let s = rig.editor.doc.pmm.camera_state;
    assert_eq!(&s[..3], &[1.0, 2.0, 3.0]);
    assert_eq!(s[5], -25.0);
    assert_eq!(s[6], (-10.0 * pi / 180.0) as f32);
    assert_eq!(s[7], (-20.0 * pi / 180.0) as f32);
    assert_eq!(s[8], (5.0 * pi / 180.0) as f32);
    // Reopened, the dialog shows what was entered.
    rig.run("dlg:IDD_CAMERA_NUMERIC_INPUT").unwrap();
    let shown: Vec<String> = (0..7).map(|i| rig.field(i)).collect();
    assert_eq!(
        shown
            .iter()
            .map(|t| t.trim().parse::<f32>().unwrap())
            .collect::<Vec<_>>(),
        [1.0, 2.0, 3.0, 10.0, -20.0, 5.0, 25.0]
    );
}

#[test]
fn camera_numeric_input_left_alone_keeps_the_camera() {
    let mut rig = camera_rig();
    let before = rig.saved();
    rig.run("dlg:IDD_CAMERA_NUMERIC_INPUT").unwrap();
    rig.ok().unwrap();
    assert!(rig.saved() == before);
}

fn bone_rig() -> Rig {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectBones(vec![0])).unwrap();
    rig
}

#[test]
fn bone_numeric_input_needs_a_selected_bone() {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectBones(Vec::new())).unwrap();
    assert!(rig.run("dlg:IDD_BONE_NUMERIC_INPUT").is_err());
    assert!(rig.with(dialog::numeric_input).is_err());
    assert_eq!(rig.shown(), None);
}

/// Position as typed; the angles round-trip through the readout of the same bone.
#[test]
fn bone_numeric_input() {
    let mut rig = bone_rig();
    rig.fill(
        "dlg:IDD_BONE_NUMERIC_INPUT",
        &["1.5", "-2", "0.25", "30", "-45", "60"],
    );
    rig.ok().unwrap();
    let pose = rig.editor.doc.selected_model().unwrap().bone_pose[0].clone();
    assert_eq!(pose.translation, [1.5, -2.0, 0.25]);
    rig.cancel();
    rig.with(dialog::numeric_input).unwrap();
    assert_eq!(rig.shown(), Some("IDD_BONE_NUMERIC_INPUT"));
    for (i, want) in [1.5, -2.0, 0.25, 30.0, -45.0, 60.0].into_iter().enumerate() {
        let got: f32 = rig.field(i).trim().parse().unwrap();
        assert!((got - want).abs() < 0.002, "box {i}: {got} for {want}");
    }
}

#[test]
fn bone_numeric_input_left_alone_keeps_the_pose() {
    let mut rig = bone_rig();
    rig.editor
        .apply(Command::SetBonePose {
            bone: 0,
            translation: [0.123456, 0.0, 0.0],
            rotation: [0.1, 0.2, 0.3, 0.927_361_85],
        })
        .unwrap();
    let before = rig.saved();
    rig.run("dlg:IDD_BONE_NUMERIC_INPUT").unwrap();
    rig.ok().unwrap();
    assert!(rig.saved() == before);
}

/// The gravity dialog applies as it goes and leaves the document as the oracle does.
#[test]
fn gravity_noise_and_close() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("dlg:IDD_GRAVITY").unwrap();
    rig.with(|c| dialog::set_check(c, 0, true));
    assert_eq!(rig.editor.doc.pmm.physics.gravity_noise_enabled, 1);
    rig.type_into(4, "77");
    assert_eq!(rig.editor.doc.pmm.physics.gravity_noise, 77);
    rig.cancel();
    assert_eq!(rig.shown(), None);
}

// ---- gates ----------------------------------------------------------------------------------

const MODEL_ONLY: [&str; 6] = [
    "dlg:IDD_CENTER_POSITION_BIAS",
    "dlg:IDD_FRAME_SHIFT",
    "dlg:IDD_REGISTER_BLINKING",
    "dlg:IDD_BONE_FRAME_MULTIPLY",
    "dlg:IDD_MORPH_MULTIPLY",
    "dlg:IDD_EDGE_THICKNESS",
];

#[test]
fn model_dialogs_refuse_camera_mode_and_camera_dialogs_model_mode() {
    let mut rig = camera_rig();
    for id in MODEL_ONLY {
        assert_eq!(
            rig.run(id),
            Err(format!("{}: not in this mode", &id[4..])),
            "{id}"
        );
    }
    assert_eq!(rig.shown(), None);
    for id in [
        "dlg:IDD_CAMERA_FRAME_MULTIPLY",
        "dlg:IDD_CAMERA_NUMERIC_INPUT",
    ] {
        rig.run(id).unwrap();
        rig.cancel();
    }
    let mut rig = Rig::open("swing600.pmm");
    for id in [
        "dlg:IDD_CAMERA_FRAME_MULTIPLY",
        "dlg:IDD_CAMERA_NUMERIC_INPUT",
    ] {
        assert!(rig.run(id).is_err(), "{id}");
    }
}

#[test]
fn editing_dialogs_do_not_open_while_playing() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("ctl:408").unwrap();
    for id in MODEL_ONLY {
        assert_eq!(rig.run(id), Err(format!("{id}: not while playing")), "{id}");
    }
    // The AVI and prompt dialogs do not edit the document.
    for id in ["dlg:IDD_AVI_OUTPUT", "dlg:IDD_PMM_MISSING_MODEL"] {
        rig.run(id).unwrap();
        rig.cancel();
    }
}

#[test]
fn rows_without_a_command_are_not_runnable() {
    let mut rig = Rig::open("swing600.pmm");
    for id in [
        "IDD_FRAME_SCALE",
        "IDD_ACCESSORY_ORDER",
        "IDD_MODEL_DRAW_ORDER",
        "IDD_MODEL_CALCULATE_ORDER",
        "IDD_OUTSIDE_PARENT",
        "IDD_ENGLISH_NAMES",
        "IDD_TOON_TEXTURE",
        "IDD_PHYSICS_MODEL",
    ] {
        let id = format!("dlg:{id}");
        assert_eq!(rig.run(&id), Err(format!("{id}: not implemented")));
    }
}
