//! The eight dialogs of the model panel, the timeline and the View menu that had no command to
//! run: the frame scale, accessory, draw order, calculation order, outside parent, English names,
//! toon texture and physics model dialogs. The expected values are read off the C++ named in the
//! comments, and `mds-doc/tests/dialogs.rs`; the byte-exact oracle is `replay.rs`.

use super::{fixtures, Rig};
use mds_app::editor::Editor;
use mds_app::ui::dialog::{self, OpCombo};
use mds_app::ui::model_panel;
use mds_app::ui::viewport::RecordTarget;
use mds_app::ui::Ctx;
use mds_doc::{Command, Document, ModelFile, OutsideParent};
use mds_formats::pmm::Pmm;

/// A scene with `lips.pmd` (the English names, toon names, 8 bodies and joints of `chain8.pmd`)
/// loaded and selected, saved next to the inputs of `script3`.
fn lips() -> Rig {
    let dir = fixtures().join("script3/inputs");
    let mut rig = Rig::new(Editor::new(Document::startup(), Some(dir.join("scene.pmm"))).unwrap());
    let data = std::fs::read(dir.join("lips.pmd")).unwrap();
    rig.with(|c| model_panel::load(c, ".\\lips.pmd", data))
        .unwrap();
    rig.editor.modified = false;
    rig
}

fn pmd(rig: &Rig) -> &mds_formats::pmd::Pmd {
    let i = rig.editor.doc.pmm.models.len() - 1;
    match &rig.editor.doc.models[i] {
        ModelFile::Pmd(p) => p,
        _ => panic!("not a PMD"),
    }
}

fn reload(rig: &Rig) -> Pmm {
    Pmm::read(&rig.saved()).unwrap()
}

const ALL: [(&str, bool); 8] = [
    ("IDD_FRAME_SCALE", true),
    ("IDD_ACCESSORY_ORDER", false),
    ("IDD_MODEL_DRAW_ORDER", false),
    ("IDD_MODEL_CALCULATE_ORDER", false),
    ("IDD_OUTSIDE_PARENT", true),
    ("IDD_ENGLISH_NAMES", true),
    ("IDD_TOON_TEXTURE", true),
    ("IDD_PHYSICS_MODEL", true),
];

/// Every row has an action. The ones of the selected model are refused in camera mode (the C++
/// handlers return there), and a model has to be selected.
#[test]
fn every_row_opens_and_the_model_ones_need_model_mode() {
    let mut rig = lips();
    for (name, _) in ALL {
        let id = format!("dlg:{name}");
        rig.run(&id).unwrap_or_else(|e| panic!("{id}: {e}"));
        assert_eq!(rig.shown(), Some(name));
        rig.cancel();
        assert_eq!(rig.shown(), None, "{name}");
    }
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    for (name, model_only) in ALL {
        let id = format!("dlg:{name}");
        assert_eq!(rig.run(&id).is_err(), model_only, "{id} in camera mode");
        rig.cancel();
    }
    assert!(
        mds_app::actions::find("dlg:IDD_PHYSICS_MODEL")
            .unwrap()
            .needs_document
    );
}

// ---- 424: frame scale -----------------------------------------------------------------------

/// `FrameRangeDlgProc`: the boxes start at the range of the timeline, a rate of 1.0 or below
/// 0.00001 changes nothing and the dialog closes, anything else scales (`ApplyFrameRangeScale`).
#[test]
fn frame_scale_starts_at_the_range_and_ignores_a_rate_that_changes_nothing() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("dlg:IDD_FRAME_SCALE").unwrap();
    assert_eq!(rig.field(2), "1.0");
    let before = rig.saved();
    for rate in ["1.0", "0", "0.000001", "x"] {
        rig.run("dlg:IDD_FRAME_SCALE").unwrap();
        rig.type_into(0, "0");
        rig.type_into(1, "300");
        rig.type_into(2, rate);
        rig.ok().unwrap();
        assert_eq!(rig.shown(), None);
        assert!(rig.saved() == before, "rate {rate}");
    }
    rig.run("dlg:IDD_FRAME_SCALE").unwrap();
    rig.type_into(0, "300");
    rig.type_into(1, "300");
    rig.type_into(2, "2");
    rig.ok().unwrap();
    assert!(rig.saved() == before, "an empty range");
    rig.fill("dlg:IDD_FRAME_SCALE", &["0", "300", "1.5"]);
    rig.ok().unwrap();
    assert!(rig.saved() != before);
    let mut doc = Rig::open("swing600.pmm").editor.doc;
    doc.apply(Command::ScaleFrames(mds_ops::RangeScale {
        start: 0,
        end: 300,
        scale: 1.5,
        bones: true,
        morphs: true,
        display: true,
    }))
    .unwrap();
    assert!(
        rig.saved() == doc.save().unwrap(),
        "the three boxes start checked"
    );
}

// ---- 288, 289: the order dialogs ------------------------------------------------------------

/// `ApplyModelDisplayOrderDialog` and `ApplyModelCalculateOrderDialog`: the list box as rows,
/// up (630) and down (631) move the selected row, OK writes the order of the rows. The expected
/// bytes are those of `the_order_dialogs_write_the_order_bytes` (mds-doc).
#[test]
fn the_order_dialogs_move_rows_and_write_the_order_bytes() {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectModel(0)).unwrap();
    rig.run("dlg:IDD_MODEL_DRAW_ORDER").unwrap();
    let rows = rig.with(|c| dialog::list_rows(c));
    assert_eq!(rows.len(), 4);
    // The rows 0, 1, 2, 3 -> 2, 0, 3, 1.
    rig.with(|c| {
        dialog::select_row(c, 2).unwrap();
        dialog::move_selected(c, true).unwrap();
        dialog::move_selected(c, true).unwrap();
        dialog::select_row(c, 3).unwrap();
        dialog::move_selected(c, true).unwrap();
    });
    let moved = rig.with(|c| dialog::list_rows(c));
    assert_eq!(
        moved,
        [&rows[2], &rows[0], &rows[3], &rows[1]].map(|r| r.clone())
    );
    // Past the first and last rows nothing moves.
    rig.with(|c| {
        dialog::select_row(c, 0).unwrap();
        dialog::move_selected(c, true).unwrap();
    });
    assert_eq!(rig.with(|c| dialog::list_rows(c)), moved);
    rig.ok().unwrap();
    assert_eq!(rig.shown(), None);
    assert_eq!(rig.editor.doc.pmm.settings.options[0], 1);
    assert_eq!(rig.editor.doc.pmm.timeline.edit_mode, 2);
    // Calculation order: the rows are the slots by `display_order`; swap the first two.
    let mut by_order: Vec<(u8, u8)> = reload(&rig)
        .models
        .iter()
        .map(|m| (m.display_order, m.slot))
        .collect();
    by_order.sort();
    let mut calc: Vec<u8> = by_order.into_iter().map(|(_, s)| s).collect();
    rig.run("dlg:IDD_MODEL_CALCULATE_ORDER").unwrap();
    rig.with(|c| {
        dialog::select_row(c, 1).unwrap();
        dialog::move_selected(c, true).unwrap();
    });
    rig.ok().unwrap();
    calc.swap(0, 1);
    let mut oracle = Rig::open("swing600.pmm");
    oracle.editor.apply(Command::SelectModel(0)).unwrap();
    oracle
        .editor
        .apply(Command::SetModelDrawOrder(vec![2, 0, 3, 1]))
        .unwrap();
    oracle
        .editor
        .apply(Command::SetModelCalcOrder(calc))
        .unwrap();
    assert!(rig.saved() == oracle.saved());
    let p = reload(&rig);
    let combo: Vec<u8> = p.models.iter().map(|m| m.selection.combo_index).collect();
    assert_eq!(combo, [2, 4, 1, 3]);
}

#[test]
fn cancelling_an_order_dialog_changes_nothing() {
    let mut rig = Rig::open("swing600.pmm");
    let before = rig.saved();
    for id in ["dlg:IDD_MODEL_DRAW_ORDER", "dlg:IDD_MODEL_CALCULATE_ORDER"] {
        rig.run(id).unwrap();
        rig.with(|c| {
            dialog::select_row(c, 1).unwrap();
            dialog::move_selected(c, false).unwrap();
        });
        rig.cancel();
    }
    assert!(rig.saved() == before && !rig.editor.modified);
    assert_eq!(rig.status, "");
}

// ---- 249: accessories -----------------------------------------------------------------------

/// `AccessorySettingsDlgProc`: the rows are the accessory combo, the name box renames the
/// selected row (633, an empty box is ignored), the count box is clamped to the rows, OK renames,
/// reorders and splits. The expected values are those of
/// `the_accessory_order_dialog_reorders_renames_and_selects` (mds-doc).
#[test]
fn the_accessory_dialog_reorders_renames_and_clamps_the_split() {
    let mut rig = Rig::new(Editor::new(Document::startup(), None).unwrap());
    for name in ["a", "b", "c"] {
        let cmd = Command::LoadAccessory {
            path: format!("C:\\acc\\{name}.x"),
            data: std::fs::read(fixtures().join("accessory/cube.x")).unwrap(),
        };
        rig.editor.apply(cmd).unwrap();
    }
    rig.run("dlg:IDD_ACCESSORY_ORDER").unwrap();
    assert_eq!(rig.with(|c| dialog::list_rows(c)), ["a.x", "b.x", "c.x"]);
    rig.with(|c| dialog::select_row(c, 0)).unwrap();
    assert_eq!(rig.field(0), "a.x", "the box shows the selected row");
    rig.type_into(0, "first");
    rig.with(dialog::rename_selected).unwrap();
    rig.with(|c| dialog::select_row(c, 1)).unwrap();
    rig.type_into(0, "");
    rig.with(dialog::rename_selected).unwrap();
    rig.with(|c| {
        dialog::select_row(c, 2).unwrap();
        dialog::move_selected(c, true).unwrap();
        dialog::move_selected(c, true).unwrap();
    });
    assert_eq!(rig.with(|c| dialog::list_rows(c)), ["c.x", "first", "b.x"]);
    rig.type_into(1, "7");
    assert_eq!(rig.field(1), "3", "clamped to the number of rows");
    rig.ok().unwrap();
    assert_eq!(rig.editor.doc.pmm.selected_accessory_slot, 2);
    assert_eq!(rig.editor.doc.pmm.physics.accessory_render_order, 3);
    let rows: Vec<String> = reload(&rig)
        .accessories
        .iter()
        .map(|a| a.list_name.text.clone())
        .collect();
    assert_eq!(rows, ["c.x", "first", "b.x"]);
    let slots: Vec<(u8, u8, String)> = reload(&rig)
        .accessories
        .iter()
        .map(|a| (a.slot, a.order, a.name.text.clone()))
        .collect();
    assert_eq!(
        slots,
        [
            (0, 1, "first".to_string()),
            (1, 2, "b.x".to_string()),
            (2, 0, "c.x".to_string())
        ]
    );
}

// ---- 442: outside parent --------------------------------------------------------------------

/// The result of the dialog equals the commands it stands for: 630 bakes the pose of the selector
/// bone for the chosen parent, 632 registers the records, and the close seeks.
#[test]
fn the_outside_parent_dialog_applies_and_registers_the_records() {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectModel(0)).unwrap();
    rig.editor.apply(Command::SetFrame(10)).unwrap();
    rig.run("ctl:442").unwrap();
    assert_eq!(rig.shown(), Some("IDD_OUTSIDE_PARENT"));
    rig.with(|c| dialog::op_pick(c, OpCombo::Selector, 2))
        .unwrap();
    rig.with(|c| dialog::op_pick(c, OpCombo::Target, 1))
        .unwrap();
    assert_eq!(
        rig.with(|c| dialog::op_record(c, 2)),
        Some(OutsideParent::Ground)
    );
    rig.with(dialog::op_apply_pose).unwrap();
    rig.with(dialog::op_register_records).unwrap();
    rig.cancel();
    assert_eq!(rig.shown(), None);

    let mut oracle = Rig::open("swing600.pmm");
    for cmd in [
        Command::SelectModel(0),
        Command::SetFrame(10),
        Command::ApplyOutsideParent {
            selector: 2,
            parent: OutsideParent::Ground,
        },
        Command::RegisterOutsideParents(vec![
            OutsideParent::None,
            OutsideParent::None,
            OutsideParent::Ground,
            OutsideParent::None,
        ]),
        Command::CloseOutsideParentDialog,
    ] {
        oracle.editor.apply(cmd).unwrap();
    }
    assert!(rig.saved() == oracle.saved());
}

#[test]
fn the_outside_parent_dialog_cancelled_marks_the_scene_modified_as_the_c_plus_plus_does() {
    // The cancel returns IDOK (`dialog_procs.cpp:116`), so the caller always marks SceneModified.
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectModel(0)).unwrap();
    rig.editor.modified = false;
    rig.run("dlg:IDD_OUTSIDE_PARENT").unwrap();
    rig.cancel();
    assert!(rig.editor.modified);
}

#[test]
fn the_outside_parent_dialog_closes_when_camera_mode_is_entered() {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectModel(0)).unwrap();
    rig.run("ctl:442").unwrap();
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    rig.draw(Vec::new());
    assert_eq!(
        rig.shown(),
        None,
        "camera mode ends the dialog of the selected model"
    );
}

// ---- 259: English names ---------------------------------------------------------------------

/// `EnglishNameDlgProc`: the boxes start with the model's name and the first bone, morph and
/// group; a combo step commits the box it leaves; OK and Cancel both apply, OK adds the reminder.
#[test]
fn the_english_names_dialog_edits_the_names_of_the_model() {
    let mut rig = lips();
    rig.run("dlg:IDD_ENGLISH_NAMES").unwrap();
    let (bone0, morph0, group0) = {
        let e = pmd(&rig)
            .extension
            .as_ref()
            .unwrap()
            .english
            .as_ref()
            .unwrap();
        (
            e.bone_names[0].text.clone(),
            e.morph_names[0].text.clone(),
            e.group_names[0].text.clone(),
        )
    };
    assert_eq!(
        (rig.field(2), rig.field(3), rig.field(4)),
        (bone0, morph0, group0)
    );
    rig.type_into(0, "Lips");
    rig.type_into(2, "Center2");
    rig.with(|c| dialog::names_move(c, 0, true)).unwrap();
    let bone1 = pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .english
        .as_ref()
        .unwrap()
        .bone_names[1]
        .text
        .clone();
    assert_eq!(rig.field(2), bone1, "the box shows the next bone");
    let e = pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .english
        .as_ref()
        .unwrap();
    assert_eq!(e.bone_names[0].text, "Center2", "the old box was committed");
    rig.type_into(2, "Second");
    rig.type_into(3, "Smile");
    rig.ok().unwrap();
    assert_eq!(rig.shown(), None);
    assert!(rig.status.contains("拡張モデル保存"));
    let e = pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .english
        .as_ref()
        .unwrap();
    assert_eq!(
        (
            e.bone_names[1].text.as_str(),
            e.morph_names[0].text.as_str()
        ),
        ("Second", "Smile")
    );
    assert_eq!(rig.editor.doc.pmm.models[0].name_en.text, "Lips");
}

/// Opening the dialog sets edit mode 0 and selects bone 0 (`english_name_dialog.cpp:291-304`);
/// the bone combo selects its bone alone, or none for kinds 6, 7 and 9
/// (`SelectEnglishNameBone`, `:383-391`). Neither is an edit of the scene.
#[test]
fn the_english_bone_combo_selects_the_bone() {
    let mut rig = lips();
    rig.editor
        .apply(mds_doc::Command::SelectBones(vec![1, 2]))
        .unwrap();
    rig.editor.apply(mds_doc::Command::SetEditMode(1)).unwrap();
    rig.editor.modified = false;
    rig.run("dlg:IDD_ENGLISH_NAMES").unwrap();
    let selection = |rig: &Rig| {
        let m = rig.editor.doc.selected_model().unwrap();
        let marked: Vec<usize> = (0..m.bone_pose.len())
            .filter(|&b| m.bone_pose[b].flags[2] != 0)
            .collect();
        (m.selection.selected_bone, marked)
    };
    assert_eq!(rig.editor.doc.pmm.timeline.edit_mode, 0);
    assert_eq!(selection(&rig), (0, vec![0]));
    assert!(pmd(&rig).bones[..2]
        .iter()
        .all(|b| ![6, 7, 9].contains(&b.kind)));
    rig.with(|c| dialog::names_select(c, 0, 1)).unwrap();
    assert_eq!(selection(&rig), (1, vec![1]));
    // lips.pmd has no tip bone: bone 2 becomes one of each kind.
    for kind in [6, 7, 9] {
        let ModelFile::Pmd(p) = &mut rig.editor.doc.models[0] else {
            panic!("not a PMD")
        };
        p.bones[2].kind = kind;
        rig.with(|c| dialog::names_select(c, 0, 2)).unwrap();
        assert_eq!(selection(&rig), (-1, vec![]), "kind {kind}");
        rig.with(|c| dialog::names_select(c, 0, 1)).unwrap();
    }
    assert!(!rig.editor.modified);
}

#[test]
fn the_english_names_dialog_applies_on_cancel_too() {
    let mut rig = lips();
    rig.run("dlg:IDD_ENGLISH_NAMES").unwrap();
    rig.type_into(2, "Cancelled");
    rig.cancel();
    let e = pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .english
        .as_ref()
        .unwrap();
    assert_eq!(e.bone_names[0].text, "Cancelled");
    assert_eq!(rig.status, "");
}

// ---- 261: toon textures ---------------------------------------------------------------------

/// `CollectToonFileNames`: a name equal to the default or naming a file beside the model is
/// stored; another is not, and a box names it and closes without the reminder.
#[test]
fn the_toon_dialog_stores_the_names_that_exist_beside_the_model() {
    let mut rig = lips();
    rig.run("dlg:IDD_TOON_TEXTURE").unwrap();
    assert_eq!(
        rig.field(0),
        pmd(&rig).extension.as_ref().unwrap().toon_textures[0].text
    );
    rig.type_into(2, "toonx.bmp");
    rig.ok().unwrap();
    assert_eq!(
        pmd(&rig).extension.as_ref().unwrap().toon_textures[2].text,
        "toonx.bmp"
    );
    assert!(rig.status.contains("拡張モデル保存"));

    rig.status.clear();
    rig.run("dlg:IDD_TOON_TEXTURE").unwrap();
    rig.type_into(3, "nothing-here.bmp");
    rig.ok().unwrap();
    assert_eq!(rig.shown(), None);
    let toon = |rig: &Rig, i: usize| {
        pmd(rig).extension.as_ref().unwrap().toon_textures[i]
            .text
            .clone()
    };
    assert_ne!(toon(&rig, 3), "nothing-here.bmp");
    assert_eq!(
        toon(&rig, 2),
        "toonx.bmp",
        "the names that were found are kept"
    );
    assert!(rig.status.contains("nothing-here.bmp"), "{}", rig.status);
    assert!(!rig.status.contains("拡張モデル保存"));
}

// ---- 262: the physics model -----------------------------------------------------------------

fn bodies(rig: &Rig) -> usize {
    pmd(rig)
        .extension
        .as_ref()
        .unwrap()
        .physics
        .as_ref()
        .unwrap()
        .rigids
        .len()
}

fn joints(rig: &Rig) -> usize {
    pmd(rig)
        .extension
        .as_ref()
        .unwrap()
        .physics
        .as_ref()
        .unwrap()
        .joints
        .as_ref()
        .map_or(0, Vec::len)
}

#[test]
fn a_failed_open_leaves_no_scratch_copy() {
    // Without a window the action cannot open the dialog; nothing may stay behind.
    let mut rig = lips();
    let mut status = String::new();
    let mut ctx = mds_app::ui::Ctx {
        editor: &mut rig.editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    assert!(mds_app::actions::run(&mut ctx, "dlg:IDD_PHYSICS_MODEL").is_err());
    assert!(ctx.editor.doc.edit.physics_scratch.is_none());
}

#[test]
fn the_physics_dialog_needs_a_pmd_model() {
    let mut rig = Rig::open("swing600.pmm");
    rig.editor.apply(Command::SelectModel(0)).unwrap();
    let e = rig.run("dlg:IDD_PHYSICS_MODEL").unwrap_err();
    assert!(e.contains("PMD"), "{e}");
    assert_eq!(rig.shown(), None);
}

/// Add and delete bodies and joints on the scratch copy; the model keeps its records until OK,
/// and Cancel leaves them. The joints of a deleted body go with it.
#[test]
fn the_physics_dialog_edits_a_copy_and_ok_commits_it() {
    let mut rig = lips();
    let (b0, j0) = (bodies(&rig), joints(&rig));
    assert!(b0 > 0 && j0 > 0);
    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    rig.with(|c| dialog::physics_press(c, 685)).unwrap();
    rig.with(|c| dialog::physics_press(c, 735)).unwrap();
    assert_eq!(
        rig.with(|c| dialog::physics_records(c)),
        Some((b0 + 1, j0 + 1))
    );
    assert_eq!(bodies(&rig), b0, "the model is untouched until OK");
    rig.cancel();
    assert_eq!(rig.with(|c| dialog::physics_records(c)), None);
    assert_eq!((bodies(&rig), joints(&rig)), (b0, j0));
    assert!(!rig.editor.modified);

    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    rig.with(|c| dialog::physics_press(c, 685)).unwrap();
    rig.with(|c| dialog::physics_text(c, 718, "2.5")).unwrap();
    rig.ok().unwrap();
    assert_eq!((bodies(&rig), joints(&rig)), (b0 + 1, j0));
    let added = &pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .physics
        .as_ref()
        .unwrap()
        .rigids[b0];
    assert_eq!(
        (added.name.text.as_str(), added.mass),
        (format!("BODY_{b0}").as_str(), 2.5)
    );
    assert!(rig.status.contains("拡張モデル保存"));
    // The PMD edits set `EnhancedModelDirty`, not `SceneModified`.
    assert!(!rig.editor.modified);

    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    rig.with(|c| dialog::physics_pick(c, 704, 0)).unwrap();
    rig.with(|c| dialog::physics_press(c, 706)).unwrap();
    let (b, j) = rig.with(|c| dialog::physics_records(c)).unwrap();
    assert_eq!(b, b0);
    assert!(j < j0, "the joints of the deleted body go with it");
}

#[test]
fn the_physics_dialog_reads_the_boxes_as_the_cpp_does() {
    let mut rig = lips();
    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    // A size below 0.1 is written back as 0.1; the y limit of a joint stays inside -90..90.
    rig.with(|c| dialog::physics_text(c, 709, "0.01")).unwrap();
    rig.with(|c| dialog::physics_commit(c, 709)).unwrap();
    rig.with(|c| dialog::physics_press(c, 801)).unwrap();
    rig.with(|c| dialog::physics_text(c, 765, "120")).unwrap();
    rig.with(|c| dialog::physics_commit(c, 765)).unwrap();
    assert!(rig.status.contains("-90"), "{}", rig.status);
    rig.ok().unwrap();
    let p = pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .physics
        .as_ref()
        .unwrap();
    assert_eq!(p.rigids[0].size[0], 0.1);
    let upper_y = p.joints.as_ref().unwrap()[0].rotation_max[1];
    assert!((upper_y - 80.0_f32.to_radians()).abs() < 1e-5, "{upper_y}");
}

fn record_target(rig: &Rig) -> Option<RecordTarget> {
    let id = egui::Id::unique("viewport-record-target");
    rig.egui
        .data(|d| d.get_temp::<Option<RecordTarget>>(id))
        .flatten()
}

/// The viewport's record drag edits the record the dialog has selected (`EditModeRecord`,
/// `frame_modes_bone.cpp:158`, by `selectedRigidIndex`, `selectedJointIndex` and the page): the
/// dialog publishes it on open, on a new selection or page, and withdraws it on close.
#[test]
fn the_physics_dialog_tells_the_viewport_which_record_it_has_selected() {
    let at = |joint, index| Some(RecordTarget { joint, index });
    let mut rig = lips();
    assert_eq!(record_target(&rig), None);
    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    assert_eq!(record_target(&rig), at(false, 0));
    rig.with(|c| dialog::physics_pick(c, 704, 1)).unwrap();
    assert_eq!(record_target(&rig), at(false, 1));
    rig.with(|c| dialog::physics_press(c, 801)).unwrap();
    assert_eq!(record_target(&rig), at(true, 0));
    rig.with(|c| dialog::physics_pick(c, 736, 1)).unwrap();
    assert_eq!(record_target(&rig), at(true, 1));
    rig.with(|c| dialog::physics_press(c, 800)).unwrap();
    assert_eq!(record_target(&rig), at(false, 1));
    // A drawn pass keeps it, and Esc withdraws it.
    let pass = |rig: &mut Rig, events: Vec<egui::Event>| {
        let egui = rig.egui.clone();
        let mut ctx = Ctx {
            editor: &mut rig.editor,
            now_ms: 0,
            egui: Some(egui.clone()),
            viewport: None,
            status: &mut rig.status,
        };
        let input = egui::RawInput {
            events,
            ..Default::default()
        };
        egui.run_ui(input, |ui| dialog::show(ui, &mut ctx))
            .drop_without_applying_deltas();
    };
    pass(&mut rig, vec![]);
    assert_eq!(record_target(&rig), at(false, 1));
    let esc = egui::Event::Key {
        key: egui::Key::Escape,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: egui::Modifiers::NONE,
    };
    pass(&mut rig, vec![esc]);
    assert_eq!(rig.shown(), None);
    assert_eq!(record_target(&rig), None);

    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    assert_eq!(record_target(&rig), at(false, 0));
    rig.ok().unwrap();
    assert_eq!(record_target(&rig), None);
}

/// A record drag echoes the dragged value into its box only (`EchoRecord`,
/// `frame_modes_bone.cpp:161-224`): what was typed in another box and not entered stays. The
/// rotation is the widened value over the double truncated pi, as a float (`:176`): the record
/// 0.104807 rad shows 6.00 where the float division would show 6.01.
#[test]
fn a_record_drag_echoes_only_the_dragged_box() {
    let mut rig = lips();
    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    rig.with(|c| dialog::physics_text(c, 718, "9.99")).unwrap();
    rig.with(|c| dialog::physics_text(c, 712, "7.77")).unwrap();
    let scratch = rig.editor.doc.edit.physics_scratch.as_mut().unwrap();
    scratch.0[0].rotation[0] = f32::from_bits(0x3dc2_2a2c);
    let drag = |rig: &mut Rig, field, axis, dy| {
        rig.editor
            .apply(mds_doc::Command::EditPhysicsRecord {
                joint: false,
                index: 0,
                field,
                axis,
                dy,
            })
            .unwrap();
        rig.draw(vec![]);
    };
    drag(&mut rig, mds_doc::PhysicsField::Rotation, 0, -1);
    assert_eq!(rig.field(7), "6.00");
    assert_eq!(
        (rig.field(10), rig.field(4)),
        ("9.99".into(), "7.77".into())
    );
    let y = rig.editor.doc.edit.physics_scratch.as_ref().unwrap().0[0].position[1];
    drag(&mut rig, mds_doc::PhysicsField::Position, 1, 2);
    assert_eq!(
        rig.field(5),
        format!("{:3.2}", (f64::from(y) - 0.1f32 as f64) as f32)
    );
    assert_eq!(
        (rig.field(10), rig.field(4)),
        ("9.99".into(), "7.77".into())
    );
}

/// The name boxes 705 and 740 are ANSI edit boxes: `CollectBodyEdits` and `CollectJointEdits`
/// copy their Shift-JIS bytes into the 20-byte names (`physics_model_dialog.cpp:1129` on). A
/// character cp932 has no code for reads back as `?`.
#[test]
fn the_physics_dialog_writes_the_names_in_shift_jis() {
    let mut rig = lips();
    rig.run("dlg:IDD_PHYSICS_MODEL").unwrap();
    rig.with(|c| dialog::physics_text(c, 705, "剛体")).unwrap();
    rig.with(|c| dialog::physics_text(c, 740, "関節😀"))
        .unwrap();
    rig.ok().unwrap();
    let p = pmd(&rig)
        .extension
        .as_ref()
        .unwrap()
        .physics
        .as_ref()
        .unwrap();
    let body = &p.rigids[0].name;
    assert_eq!(body.raw[..5], [0x8d, 0x84, 0x91, 0xcc, 0]);
    assert_eq!(body.text, "剛体");
    let joint = &p.joints.as_ref().unwrap()[0].name;
    assert_eq!(joint.raw[..6], [0x8a, 0xd6, 0x90, 0xdf, b'?', 0]);
}
