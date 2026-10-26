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
    assert_eq!(
        model_panel::combo_text(&e.doc, 0),
        "camera / light / accessory"
    );
    assert_eq!(model_panel::combo_text(&e.doc, 1), "chain8");
    assert_eq!(
        doc(&e),
        (2, 1, 0, 0),
        "the second model is selected after two loads"
    );

    run(&mut e, "key:Tab").unwrap();
    assert_eq!(
        doc(&e),
        (0, 1, 1, 2),
        "Tab past the last entry wraps to the camera entry"
    );
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
    assert_eq!(
        e.doc.pmm.selected_model_slot, 1,
        "back on the model that was selected"
    );

    let mut status = String::new();
    model_panel::select_combo(&mut ctx(&mut e, &mut status), 1).unwrap();
    assert_eq!(
        (
            model_panel::combo_cursor(&e.doc),
            e.doc.pmm.selected_model_slot
        ),
        (1, 0)
    );
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
    assert_eq!(
        (
            model_panel::combo_len(&e.doc),
            model_panel::combo_cursor(&e.doc)
        ),
        (1, 0)
    );
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
    assert_eq!(
        (p.models.len(), p.selected_model_slot, p.settings.options[0]),
        (1, 0, 0)
    );
    assert_eq!(p.models[0].path.text, "chain8.pmx");
    assert!(e.modified);
    assert!(
        e.options.looped && e.options.start_frame == 7,
        "the play panel survives"
    );
    assert_eq!(e.physics_opens, opens + 1);
    e.with_frame([64, 64], &[[0.0, 0.0]], |_| ())
        .expect("the new model draws");
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
    for id in [
        "ctl:435",
        "ctl:536",
        "key:Tab",
        "key:Shift+Tab",
        "key:VK226",
    ] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}

/// Check boxes 439 to 441 write `loadComplete`, `toonFlag` and `postLoadFlag2` of the selected
/// model (`command_frame_edit.cpp:1566` to `:1592`: the first from the box, the others toggled)
/// and leave every other field.
#[test]
fn the_check_boxes_write_their_flag() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    let flags = |e: &mds_app::editor::Editor| {
        let m = e.doc.selected_model().unwrap();
        [m.selection.load_complete, m.toon, m.post_load]
    };
    let start = flags(&e);
    let saved = e.doc.save().unwrap();
    for (n, id) in ["ctl:439", "ctl:440", "ctl:441"].into_iter().enumerate() {
        run(&mut e, id).unwrap();
        let mut want = start;
        want[n] = u8::from(start[n] == 0);
        assert_eq!(flags(&e), want, "{id}");
        assert_ne!(e.doc.save().unwrap(), saved, "{id}: the PMM keeps it");
        run(&mut e, id).unwrap();
        assert_eq!(flags(&e), start, "{id} again");
        assert_eq!(e.doc.save().unwrap(), saved);
    }
}

/// 444 and 445 write the switch of the chain the combo has selected (`ikChains[sel].enabled`,
/// `command_frame_edit.cpp:1598` to `:1617`); without a window that is chain 0, and a chain the
/// model lacks is refused.
#[test]
fn the_ik_radios_switch_a_chain() {
    let mut e = editor();
    load_model(&mut e, "chain8_ik.pmx");
    let chains = e.doc.selected_model().unwrap().ik_pose.len();
    assert!(chains > 0);
    let ik = |e: &mds_app::editor::Editor| e.doc.selected_model().unwrap().ik_pose.clone();
    run(&mut e, "ctl:445").unwrap();
    assert_eq!(ik(&e)[0], 0);
    let off = e.doc.save().unwrap();
    run(&mut e, "ctl:444").unwrap();
    assert_eq!(ik(&e)[0], 1);
    run(&mut e, "ctl:445").unwrap();
    assert_eq!(e.doc.save().unwrap(), off, "off again is the same file");

    let mut status = String::new();
    assert!(model_panel::set_ik(&mut ctx(&mut e, &mut status), chains as u32, true).is_err());
    model_panel::set_ik(&mut ctx(&mut e, &mut status), (chains - 1) as u32, true).unwrap();
    assert_eq!(ik(&e)[chains - 1], 1);
}

#[test]
fn the_selected_chain_comes_from_the_window() {
    let mut e = editor();
    load_model(&mut e, "chain8_ik.pmx");
    let egui = egui::Context::default();
    egui.data_mut(|d| d.insert_temp(egui::Id::unique("model-panel-ik"), 3usize));
    let mut status = String::new();
    let mut c = ctx(&mut e, &mut status);
    assert_eq!(model_panel::ik_chain(&c), 0);
    c.egui = Some(egui);
    assert_eq!(model_panel::ik_chain(&c), 3);
}

#[test]
fn the_model_flags_need_a_model_and_a_stopped_scene() {
    let mut e = editor();
    for id in ["ctl:439", "ctl:440", "ctl:441", "ctl:444", "ctl:445"] {
        assert_eq!(run(&mut e, id), Err("no model selected".into()), "{id}");
    }
    load_model(&mut e, "chain8_ik.pmx");
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:439", "ctl:440", "ctl:441", "ctl:444", "ctl:445"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}
