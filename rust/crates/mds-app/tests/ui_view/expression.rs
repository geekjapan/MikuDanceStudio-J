use crate::labels;
use crate::rig::{fixtures, Rig};
use mds_app::actions::{self, Handler};
use mds_app::ui::{edit, expression};
use mds_doc::Command;

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("expression", expression::LABELS);
}

/// Every row has an action but the VSQ lip sync (224), for which `mds-doc` has no command.
#[test]
fn every_row_but_the_vsq_lip_sync_has_an_action() {
    for (id, _, _) in expression::LABELS {
        let found = actions::find(id).map(|a| a.handler);
        match *id {
            "menu:224" => assert!(found.is_none(), "{id}"),
            _ => assert!(matches!(found, Some(Handler::Run(_))), "{id}"),
        }
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
