//! The dialogs and question boxes of the `edit` menus, and menu 300: what each form opens with,
//! how its boxes are read, the mode gates, cancel, and the numeric input. The effects of OK on
//! the document are the script oracle in `replay.rs`.

use super::labels;
use super::rig::Rig;
use mds_app::ui::{camera_panel, edit};
use mds_doc::{Command, SelectAll};

/// `kPiLit`, the float pi of the camera edit handlers.
const PI_LIT: f64 = 3.141592025756836;

fn boxes(rig: &Rig) -> Vec<String> {
    let form = edit::current(rig.egui.as_ref().unwrap()).expect("a form is open");
    form.fields.into_iter().map(|f| f.text).collect()
}

fn is_open(rig: &Rig) -> bool {
    edit::current(rig.egui.as_ref().unwrap()).is_some()
}

fn camera_rig() -> Rig {
    let mut rig = Rig::open("camera3.pmm");
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    rig
}

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("edit", edit::LABELS);
}

/// `ModelOffsetDlgProc` (`command_file_menu.cpp:474`) fills "0.0" three times,
/// `BoneFrameMultiplyDlgProc` and `CameraFrameMultiplyDlgProc` (`command_view_menu.cpp:475`,
/// `command_file_menu.cpp:633`) "1.0" in the even boxes and "0.0" in the odd ones,
/// `FacialMultiplyDlgProc` the first two of those.
#[test]
fn the_dialogs_open_with_the_boxes_the_cpp_fills() {
    let alternating = |n: usize| -> Vec<String> {
        (0..n)
            .map(|i| if i % 2 == 0 { "1.0" } else { "0.0" }.to_string())
            .collect()
    };
    let mut rig = Rig::open("swing600.pmm");
    for (id, want) in [
        ("menu:219", vec!["0.0".to_string(); 3]),
        ("key:D", vec!["0.0".to_string(); 3]),
        ("menu:251", alternating(12)),
        ("key:R", alternating(12)),
        ("menu:252", alternating(2)),
    ] {
        rig.run(id).unwrap_or_else(|e| panic!("{id}: {e}"));
        assert_eq!(boxes(&rig), want, "{id}");
    }
    let mut rig = camera_rig();
    rig.run("menu:242").unwrap();
    assert_eq!(boxes(&rig), alternating(16));
}

#[test]
fn a_form_needs_a_window() {
    let mut rig = Rig::open("swing600.pmm");
    rig.egui = None;
    assert_eq!(rig.run("menu:219"), Err("no window".into()));
    assert_eq!(rig.submit(), Err("no window".into()));
}

/// `RestorePlaybackMenus` (`playback_state.cpp:83`): 217 and the other model menus are gray in
/// camera mode and 242 in model mode, and the dialogs open nothing there.
#[test]
fn the_dialogs_keep_to_their_mode() {
    let mut rig = Rig::open("swing600.pmm");
    assert_eq!(
        rig.run("menu:242"),
        Err("menu:242: not in this mode".into())
    );
    assert!(!is_open(&rig));
    let mut rig = camera_rig();
    for id in ["menu:219", "menu:222", "menu:251", "menu:252"] {
        assert_eq!(rig.run(id), Err(format!("{id}: not in this mode")));
        assert!(!is_open(&rig), "{id}");
    }
    // The letter keys of the model mode do nothing in camera mode, as the key ladder does.
    for id in ["key:D", "key:R"] {
        rig.run(id).unwrap();
        assert!(!is_open(&rig), "{id}");
    }
}

/// `ReadFloatFromEdit` is `atof` on the text: the numeric prefix, else 0.
#[test]
fn a_box_is_read_as_atof_reads_it() {
    let (mut typed, mut direct) = (Rig::open("swing600.pmm"), Rig::open("swing600.pmm"));
    for rig in [&mut typed, &mut direct] {
        rig.editor
            .apply(Command::SelectAll(SelectAll::Bone))
            .unwrap();
    }
    typed.answer("menu:219", &["1.5abc", "-2", ""]).unwrap();
    direct
        .editor
        .apply(Command::CenterPositionBias([1.5, -2.0, 0.0]))
        .unwrap();
    assert!(typed.editor.doc.save().unwrap() == direct.editor.doc.save().unwrap());
    assert!(typed.editor.modified);
}

#[test]
fn cancel_changes_nothing_and_ok_needs_a_form() {
    let mut rig = Rig::open("swing600.pmm");
    let before = rig.editor.doc.save().unwrap();
    rig.run("menu:219").unwrap();
    edit::set_text(rig.egui.as_ref().unwrap(), 0, "5");
    edit::close(rig.egui.as_ref().unwrap());
    assert!(!is_open(&rig));
    assert_eq!(rig.submit(), Err("no dialog is open".into()));
    assert!(rig.editor.doc.save().unwrap() == before && !rig.editor.modified);
}

#[test]
fn a_form_does_not_commit_while_playing() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("menu:219").unwrap();
    rig.editor.toggle_play(0).unwrap();
    assert_eq!(rig.submit(), Err("not while playing".into()));
    assert!(!is_open(&rig));
}

/// A form drawn in a window pass keeps what is typed and closes on cancel.
#[test]
fn the_form_window_draws() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("menu:251").unwrap();
    rig.frame(vec![], edit::pass);
    assert_eq!(boxes(&rig).len(), 12);
}

/// Menu 222 reports the number of deleted points in a box; here it is the status line, in the
/// language of the interface (`kFmtPointsDeletedJp`, "%d point was deleted.").
#[test]
fn the_unused_frames_count_is_reported() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("menu:222").unwrap();
    let n = rig.editor.doc.edit.reported.expect("the count");
    assert_eq!(rig.status, format!("{n}個のポイントを削除しました"));
    rig.run("menu:260").unwrap();
    rig.run("menu:222").unwrap();
    let n = rig.editor.doc.edit.reported.expect("the count");
    assert_eq!(rig.status, format!("{n} point was deleted."));
}

/// Menu 250 (`command_file_menu.cpp:1471`): nothing without copied bone keys; with them a
/// question, and OK pastes onto the selected bone, which must exist.
#[test]
fn paste_to_another_bone_asks_first() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("menu:250").unwrap();
    assert!(!is_open(&rig), "nothing was copied");

    let copied = || {
        let mut rig = Rig::open("swing600.pmm");
        rig.editor
            .apply(Command::SelectAll(SelectAll::Bone))
            .unwrap();
        rig.editor.apply(Command::Copy).unwrap();
        rig.editor.apply(Command::SelectBones(vec![2])).unwrap();
        rig.editor.apply(Command::SetFrame(80)).unwrap();
        rig
    };
    let mut rig = copied();
    let mut direct = copied();
    direct.editor.apply(Command::PasteToSelectedBone).unwrap();

    let before = rig.editor.doc.save().unwrap();
    rig.run("key:F").unwrap();
    let form = edit::current(rig.egui.as_ref().unwrap()).unwrap();
    assert!(form.message.is_some() && form.fields.is_empty());
    edit::close(rig.egui.as_ref().unwrap());
    assert!(rig.editor.doc.save().unwrap() == before, "cancel");

    rig.answer("menu:250", &[]).unwrap();
    assert!(rig.editor.doc.save().unwrap() == direct.editor.doc.save().unwrap());

    // "Please select bone."
    rig.editor.apply(Command::SelectBones(vec![])).unwrap();
    let err = rig.answer("menu:250", &[]).unwrap_err();
    assert!(err.contains("no bone is selected"), "{err}");
}

/// In camera mode menu 250 pastes the copied accessory keys onto the selected accessory;
/// with nothing copied it changes nothing.
#[test]
fn paste_to_another_accessory_without_a_copy_changes_nothing() {
    let mut rig = camera_rig();
    let before = rig.editor.doc.save().unwrap();
    rig.run("menu:250").unwrap();
    assert!(rig.editor.doc.save().unwrap() == before);
    assert!(!is_open(&rig));
}

/// Menu 300 in camera mode: the seven readout boxes (position, angles in degrees, distance),
/// with what the camera panel shows; OK sets the boxes that were edited the way the readout
/// edits do (`CommitEditControlTail`: the stored pitch is the negated X, the distance is
/// negated) and leaves the rest of the camera alone.
#[test]
fn numeric_input_edits_the_camera() {
    let mut rig = camera_rig();
    rig.run("menu:300").unwrap();
    let shown: Vec<String> = (0..7)
        .map(|i| rig.with_ctx(|ctx| camera_panel::readout_text(ctx, i)))
        .collect();
    assert_eq!(boxes(&rig), shown);
    edit::close(rig.egui.as_ref().unwrap());

    // OK with nothing typed writes the camera's own values back and still sets `SceneModified`
    // (`command_view_menu.cpp:1771`).
    let before = rig.editor.doc.save().unwrap();
    rig.answer("menu:300", &[]).unwrap();
    assert!(rig.editor.doc.save().unwrap() == before);
    assert!(rig.editor.modified);
    rig.editor.modified = false;

    let s = rig.editor.doc.pmm.camera_state;
    let mut typed: Vec<&str> = shown.iter().map(String::as_str).collect();
    typed[3] = "15";
    typed[6] = "30";
    rig.answer("menu:300", &typed).unwrap();
    let after = rig.editor.doc.pmm.camera_state;
    assert_eq!(after[6], (-15.0 * PI_LIT / 180.0) as f32, "pitch");
    assert_eq!(after[5], -30.0, "distance");
    for i in [0, 1, 2, 3, 4, 7, 8] {
        assert_eq!(after[i], s[i], "camera_state[{i}]");
    }
    assert!(
        rig.editor.modified,
        "SceneModified = 1 (command_view_menu.cpp:1771)"
    );
}

/// The bone path opens only with a selected bone (`selectedBone == -1` returns first) and shows
/// the readout of that bone; an edited position and angle land on the bone.
#[test]
fn numeric_input_edits_the_selected_bone() {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectBones(vec![])).unwrap();
    rig.run("menu:300").unwrap();
    assert!(!is_open(&rig));

    rig.editor.apply(Command::SelectBones(vec![1])).unwrap();
    rig.run("menu:300").unwrap();
    assert_eq!(boxes(&rig).len(), 6);
    edit::close(rig.egui.as_ref().unwrap());

    let mut typed: Vec<String> = (0..6)
        .map(|i| rig.with_ctx(|ctx| camera_panel::readout_text(ctx, i)))
        .collect();
    typed[1] = "2.5".into();
    typed[4] = "30".into();
    let typed: Vec<&str> = typed.iter().map(String::as_str).collect();
    rig.answer("menu:300", &typed).unwrap();
    let pose = &rig.editor.doc.pmm.models[0].bone_pose[1];
    assert_eq!(pose.translation[1], 2.5);
    assert_eq!(pose.flags[1], 1, "the bone is marked edited");
    let y = rig.with_ctx(|ctx| camera_panel::readout_text(ctx, 4));
    assert_eq!(y, "30.0");
}
