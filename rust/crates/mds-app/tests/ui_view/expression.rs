use crate::labels;
use crate::rig::{fixtures, Rig};
use mds_app::actions::{self, Handler};
use mds_app::ui::{edit, expression, file};
use mds_doc::Command;
use std::path::{Path, PathBuf};

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("expression", expression::LABELS);
}

/// Every row has an action.
#[test]
fn every_row_has_an_action() {
    for (id, _, _) in expression::LABELS {
        let found = actions::find(id).map(|a| a.handler);
        assert!(matches!(found, Some(Handler::Run(_))), "{id}");
    }
    assert!(matches!(
        actions::find("key:H").map(|a| a.handler),
        Some(Handler::Run(_))
    ));
}

fn scene(model: &str) -> Rig {
    let mut rig = Rig::new();
    let path = fixtures().join(model);
    rig.editor
        .apply(Command::LoadModel {
            path: model.into(),
            data: std::fs::read(path).unwrap(),
        })
        .unwrap();
    rig
}

fn form(rig: &Rig) -> Option<edit::Form> {
    edit::current(rig.egui.as_ref().unwrap())
}

/// The three deletes ask first (`MessageBoxA` with `MB_OKCANCEL`), with the captions the C++ has
/// (the eye and eyebrow menus reuse "delete lip frame" and 新規作成); cancel changes nothing.
#[test]
fn the_deletes_ask_before_they_delete() {
    for (id, ja, en) in [
        ("menu:226", "リップフレーム削除", "delete lip frame"),
        ("menu:228", "新規作成", "delete lip frame"),
        ("menu:231", "新規作成", "delete lip frame"),
    ] {
        let mut rig = scene("morph4.pmx");
        let before = rig.editor.doc.save().unwrap();
        rig.run(id).unwrap();
        let f = form(&rig).unwrap_or_else(|| panic!("{id}: no question"));
        assert_eq!(f.title, (ja, en), "{id}");
        assert!(f.fields.is_empty() && f.message.is_some(), "{id}");
        edit::close(rig.egui.as_ref().unwrap());
        assert!(rig.editor.doc.save().unwrap() == before, "{id}");
        rig.answer(id, &[]).unwrap_or_else(|e| panic!("{id}: {e}"));
    }
}

/// `FrameShiftDlgProc` opens with "0"; `BlinkRegisterDlgProc` with empty boxes.
#[test]
fn the_dialogs_open_with_the_boxes_the_cpp_fills() {
    let mut rig = scene("morph4.pmx");
    rig.run("menu:225").unwrap();
    assert_eq!(form(&rig).unwrap().fields[0].text, "0");
    rig.run("menu:227").unwrap();
    let f = form(&rig).unwrap();
    assert_eq!(f.fields.len(), 2);
    assert!(f.fields.iter().all(|b| b.text.is_empty()));
}

/// Menu 227 says so before it opens the dialog when the model has no まばたき morph.
#[test]
fn blinks_need_a_blink_morph() {
    let mut rig = scene("chain8.pmx");
    let err = rig.run("menu:227").unwrap_err();
    assert_eq!(
        err,
        "このモデルの表情に”まばたき”がない為\n自動リップシンクはできません"
    );
    assert!(form(&rig).is_none());
    rig.run("menu:260").unwrap();
    let err = rig.run("menu:227").unwrap_err();
    assert!(err.starts_with("You cannot register blinking"), "{err}");
}

/// The info box of menu 227 (`messages.tsv` of `script2/expected/blink`), in both languages.
#[test]
fn the_blink_count_is_reported() {
    let mut rig = scene("morph4.pmx");
    rig.editor.apply(Command::SetFrame(0)).unwrap();
    rig.answer("menu:227", &["0", "300"]).unwrap();
    assert_eq!(rig.status, "3回のまばたきを追加しました");
    rig.run("menu:260").unwrap();
    rig.answer("menu:227", &["300", "600"]).unwrap();
    let n = rig.editor.doc.edit.reported.unwrap();
    assert_eq!(rig.status, format!("{n} blinking is registerd"));
}

/// All the menus are model-mode ones: gray in camera mode, and H does nothing there.
#[test]
fn the_menus_keep_to_the_model_mode() {
    let mut rig = Rig::open("camera3.pmm");
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    for id in [
        "menu:225", "menu:226", "menu:227", "menu:228", "menu:229", "menu:230", "menu:231",
    ] {
        assert_eq!(rig.run(id), Err(format!("{id}: not in this mode")), "{id}");
    }
    assert!(form(&rig).is_none());
    rig.run("key:H").unwrap();
}

#[test]
fn the_menu_draws_in_both_languages() {
    let mut rig = scene("morph4.pmx");
    rig.frame(vec![], expression::show);
    rig.run("menu:260").unwrap();
    rig.frame(vec![], expression::show);
}

/// `script3/lipsync.txt` line 3, `load model lips.pmd`, in an editor.
fn lips() -> Rig {
    Rig::replay("script3", "lipsync", 3)
}

/// `tests/fixtures/rust/vsq/<name>` copied into a folder of its own: the load writes its `.txt`
/// beside it.
fn vsq(test: &str, name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-appfix2-{test}-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join(name);
    std::fs::copy(fixtures().join("vsq").join(name), &path).unwrap();
    path
}

fn expected(name: &str) -> Vec<u8> {
    std::fs::read(fixtures().join("script3/expected/lipsync").join(name)).unwrap()
}

/// The `.txt` beside `vsq`, with the CRLF lines the C++ text-mode write gives on Windows.
fn dump(vsq: &Path) -> Vec<u8> {
    let bytes = std::fs::read(vsq.with_extension("txt")).unwrap();
    let mut out = Vec::new();
    for b in bytes {
        if b == b'\n' && !cfg!(windows) {
            out.push(b'\r');
        }
        out.push(b);
    }
    out
}

/// `script3/lipsync.txt` lines 3 to 5: `load lip sync basic.vsq` (menu 224) on `lips.pmd` saves
/// `menu.pmm` and writes `basic.txt` beside the VSQ (`vsq_load.cpp`, the step 4 file of
/// `manifest.tsv`); the menu handler sets `SceneModified` (`command_file_menu.cpp:1169`).
#[test]
fn the_lip_sync_saves_what_the_cpp_saved() {
    let mut rig = lips();
    rig.editor.modified = false;
    let path = vsq("menu", "basic.vsq");
    rig.with_ctx(|ctx| expression::lip_sync(ctx, &path, false))
        .unwrap();
    assert!(rig.editor.doc.save().unwrap() == expected("menu.pmm"));
    assert!(dump(&path) == expected("basic.txt"));
    assert!(rig.editor.modified);
}

/// The live models hold the keys the load registered, and the physics world is at the frame the
/// load moved to.
#[test]
fn the_live_models_see_the_lip_sync() {
    let mut rig = lips();
    let path = vsq("live", "basic.vsq");
    rig.with_ctx(|ctx| expression::lip_sync(ctx, &path, false))
        .unwrap();
    let keys = rig.editor.doc.pmm.models[0].morph_keys.records().len();
    assert!(keys > 4, "the load registered morph keys");
    let live = &rig.editor.physics.scene.models[0];
    assert_eq!(live.morph_keys.records().len(), keys);
}

/// `lipsync.txt` lines 9 to 11: `drop vowels.vsq` at frame 0 saves `drop.pmm` and writes
/// `vowels.txt` (`ui_dropfiles.cpp:251` to `:262`).
#[test]
fn a_dropped_vsq_saves_what_the_cpp_saved() {
    let mut rig = Rig::replay("script3", "lipsync", 9);
    rig.egui = None;
    rig.editor.modified = false;
    let path = vsq("drop", "vowels.vsq");
    rig.with_ctx(|ctx| file::drop_files(ctx, std::slice::from_ref(&path)));
    assert_eq!(rig.status, "");
    assert!(rig.editor.doc.save().unwrap() == expected("drop.pmm"));
    assert!(dump(&path) == expected("vowels.txt"));
    assert!(rig.editor.modified, "ui_dropfiles.cpp:261");
}

/// `lipsync.txt` lines 13 to 15: in camera mode the drop shows its box (`messages.tsv` step 14)
/// and changes nothing (`refused.pmm`).
#[test]
fn a_dropped_vsq_is_refused_in_camera_mode() {
    let mut rig = Rig::replay("script3", "lipsync", 13);
    rig.egui = None;
    rig.editor.modified = false;
    let path = vsq("refused", "rests.vsq");
    rig.with_ctx(|ctx| file::drop_files(ctx, std::slice::from_ref(&path)));
    assert_eq!(
        rig.status,
        "vsq: カメラ・照明モードではvsqデータは読めません"
    );
    assert!(rig.editor.doc.save().unwrap() == expected("refused.pmm"));
    assert!(!path.with_extension("txt").exists());
    assert!(!rig.editor.modified);
}

/// A rejected file (the model has no あ morph) changes nothing in the document; its message box
/// (`vsq_load.cpp`, `mds_vsq::Reject::message`) is the error, and the menu still sets
/// `SceneModified`.
#[test]
fn a_rejected_vsq_is_reported() {
    let mut rig = scene("morph4.pmx");
    rig.editor.modified = false;
    let before = rig.editor.doc.save().unwrap();
    let path = vsq("rejected", "basic.vsq");
    let err = rig
        .with_ctx(|ctx| expression::lip_sync(ctx, &path, false))
        .unwrap_err();
    assert!(err.ends_with("自動リップシンクはできません"), "{err}");
    assert!(rig.editor.doc.save().unwrap() == before);
    assert!(rig.editor.modified);
}

/// Menu 224 is a model-mode menu (`ApplyModelComboSelection` greys it in camera mode), and it
/// needs its window for the file dialog.
#[test]
fn the_lip_sync_menu_keeps_to_the_model_mode() {
    let mut rig = lips();
    rig.egui = None;
    assert_eq!(rig.run("menu:224"), Err("no window".into()));
    rig.egui = Some(egui::Context::default());
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    assert_eq!(
        rig.run("menu:224"),
        Err("menu:224: not in this mode".into())
    );
    let path = vsq("gate", "basic.vsq");
    assert!(rig
        .with_ctx(|ctx| expression::lip_sync(ctx, &path, false))
        .is_err());
}
