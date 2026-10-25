use super::common::*;
use mds_app::ui::model_panel;

/// The combo is the camera entry, then the models by `comboSelIndex`; Tab steps it forward with a
/// wrap to the camera entry, Shift+Tab back with a wrap to the last model
/// (`src/app/pump_edit_keys.cpp:266` to `:286`), and ApplyModelComboSelection
/// (`src/window/ui_model_reload.cpp:386`) leaves or enters camera mode.
#[test]
fn tab_cycles_the_model_combo() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    load_model(&mut e, "morph4.pmx");
    let doc = |e: &mds_app::editor::Editor| {
        let p = &e.doc.pmm;
        (
            model_panel::combo_cursor(&e.doc),
            p.selected_model_slot,
            p.settings.options[0],
            p.timeline.edit_mode,
        )
    };
    assert_eq!(model_panel::combo_len(&e.doc), 3);
    assert_eq!(model_panel::combo_text(&e.doc, 0), "camera / light / accessory");
    assert_eq!(model_panel::combo_text(&e.doc, 1), "chain8");
    assert_eq!(doc(&e), (2, 1, 0, 0), "the second model is selected after two loads");

    run(&mut e, "key:Tab").unwrap();
    assert_eq!(doc(&e), (0, 1, 1, 2), "Tab past the last entry wraps to the camera entry");
    run(&mut e, "key:Tab").unwrap();
    assert_eq!(doc(&e), (1, 0, 0, 0), "and on to the first model");
    run(&mut e, "key:Shift+Tab").unwrap();
    assert_eq!(doc(&e).0, 0, "Shift+Tab back to the camera entry");
    run(&mut e, "key:Shift+Tab").unwrap();
    assert_eq!(doc(&e), (2, 1, 0, 0), "and from there to the last model");
    run(&mut e, "key:VK226").unwrap();
    assert_eq!(doc(&e).0, 0, "the key left of Z cycles forward like Tab");
}

/// Button 536 (`command_frame_register.cpp:636`): from camera mode to the selected model, from
/// model mode to the camera entry. The combo entry 436 does the same by cursor.
#[test]
fn the_mode_toggle_and_the_combo() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    load_model(&mut e, "morph4.pmx");
    run(&mut e, "ctl:536").unwrap();
    assert_eq!(e.doc.pmm.settings.options[0], 1);
    run(&mut e, "ctl:536").unwrap();
    assert_eq!(e.doc.pmm.settings.options[0], 0);
    assert_eq!(e.doc.pmm.selected_model_slot, 1, "back on the model that was selected");

    let mut status = String::new();
    model_panel::select_combo(&mut ctx(&mut e, &mut status), 1).unwrap();
    assert_eq!((model_panel::combo_cursor(&e.doc), e.doc.pmm.selected_model_slot), (1, 0));
    assert!(model_panel::select_combo(&mut ctx(&mut e, &mut status), 9).is_err());
    let modified = e.modified;
    run(&mut e, "key:Tab").unwrap();
    assert_eq!(e.modified, modified, "selecting is not an edit");
}

/// A scene with no model has only the camera entry, and 536 in camera mode opens the load dialog
/// when there is no model; here the entry count and the cursor are what can be checked.
#[test]
fn an_empty_scene_has_the_camera_entry_only() {
    let mut e = editor();
    assert_eq!((model_panel::combo_len(&e.doc), model_panel::combo_cursor(&e.doc)), (1, 0));
    run(&mut e, "key:Tab").unwrap();
    assert_eq!(e.doc.pmm.settings.options[0], 1);
    assert!(!e.modified);
}

/// Load model 435 (`LoadModelFile`) adds the model, selects it, leaves camera mode and makes the
/// viewport edit mode bone (0); the editor is built again, so the window can draw it.
#[test]
fn load_selects_the_new_model_and_keeps_the_play_panel() {
    let mut e = editor();
    e.options.looped = true;
    e.options.start_frame = 7;
    let opens = e.physics_opens;
    load_model(&mut e, "chain8.pmx");
    let p = &e.doc.pmm;
    assert_eq!((p.models.len(), p.selected_model_slot, p.settings.options[0]), (1, 0, 0));
    assert_eq!(p.models[0].path.text, "chain8.pmx");
    assert!(e.modified);
    assert!(e.options.looped && e.options.start_frame == 7, "the play panel survives");
    assert_eq!(e.physics_opens, opens + 1);
    e.with_frame([64, 64], &[[0.0, 0.0]], |_| ()).expect("the new model draws");
}

#[test]
fn a_model_that_does_not_parse_changes_nothing() {
    let mut e = editor();
    let before = e.doc.save().unwrap();
    let mut status = String::new();
    let r = model_panel::load(&mut ctx(&mut e, &mut status), "bad.pmx", vec![1, 2, 3]);
    assert!(r.is_err());
    assert_eq!(e.doc.save().unwrap(), before);
    assert!(!e.modified);
}

#[test]
fn model_actions_refuse_while_playing() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:435", "ctl:536", "key:Tab", "key:Shift+Tab", "key:VK226"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}
