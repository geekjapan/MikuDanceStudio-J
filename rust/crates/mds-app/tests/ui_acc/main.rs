//! The `accessory-panel` area through its table rows and the functions its combos and edits
//! call. The buttons and check boxes (472, 476, 486, 487, 488, 489) go through `Ctx::run`; the
//! combos and edits (471, 474, 475, 478 to 485) are `Inline` rows, which `Ctx::run` refuses, so
//! they go through the pub functions `show` calls.
//!
//! Expected bytes come from `tests/fixtures/rust/script/expected/accessory/`, the C++ output of
//! `accessory.txt`; the other values are derived from the C++ handlers named at each test.

use mds_app::actions::{self, Handler};
use mds_app::editor::Editor;
use mds_app::ui::accessory_panel as panel;
use mds_app::ui::Ctx;
use mds_doc::save::opacity_visible;
use mds_doc::Command;
use std::path::PathBuf;

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn with_ctx<R>(
    editor: &mut Editor,
    egui: Option<egui::Context>,
    f: impl FnOnce(&mut Ctx) -> R,
) -> R {
    let mut status = String::new();
    f(&mut Ctx {
        editor,
        now_ms: 0,
        egui,
        viewport: None,
        status: &mut status,
    })
}

/// The scene of `accessory.txt` up to `load wav`: `chain8.pmx`, the accessory `.\tri.x`, the wave.
fn scene() -> Editor {
    let mut editor = Editor::empty();
    let read = |p: PathBuf| std::fs::read(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()));
    editor
        .apply(Command::LoadModel {
            path: "chain8.pmx".into(),
            data: read(fixtures().join("chain8.pmx")),
        })
        .unwrap();
    with_ctx(&mut editor, None, |ctx| {
        panel::load_file(ctx, ".\\tri.x", &fixtures().join("script/inputs/tri.x")).unwrap()
    });
    editor
        .apply(Command::LoadWave {
            path: "tone.wav".into(),
            data: read(fixtures().join("script/inputs/tone.wav")),
        })
        .unwrap();
    editor.apply(Command::SelectCameraMode).unwrap();
    editor
}

fn tri(editor: &Editor) -> u8 {
    let a = &editor.doc.pmm.accessories;
    assert_eq!(a.len(), 1);
    assert_eq!(a[0].list_name.text, "tri.x");
    a[0].slot
}

fn state(editor: &Editor) -> mds_formats::pmm::AccessoryState {
    editor.doc.pmm.accessories[0].state.clone()
}

/// `accessory.txt` up to `save pmm registered.pmm`: values, register, parent, register.
#[test]
fn the_edits_the_parent_and_register_save_what_the_cpp_saves() {
    let want = fixtures().join("script/expected/accessory/registered.pmm");
    let Ok(want) = std::fs::read(&want) else {
        println!("SKIP: {} is missing", want.display());
        return;
    };
    let mut editor = scene();
    let slot = tri(&editor);
    with_ctx(&mut editor, None, |ctx| {
        panel::select(ctx, slot).unwrap();
        ctx.editor.apply(Command::SetFrame(0)).unwrap();
        for (field, v) in [
            (0, 1.0),
            (1, 2.0),
            (2, 3.0),
            (3, 10.0),
            (4, 20.0),
            (5, 30.0),
        ] {
            panel::set_field(ctx, field, v).unwrap();
        }
        panel::set_field(ctx, 6, 2.0).unwrap();
        panel::set_field(ctx, 7, 0.5).unwrap();
        ctx.run("ctl:487");
        assert_eq!(ctx.status, "");

        ctx.editor.apply(Command::SetFrame(20)).unwrap();
        let chain = ctx.editor.doc.pmm.models[0].slot;
        let head = ctx.editor.doc.pmm.models[0]
            .bone_names
            .iter()
            .position(|n| n.text == "頭")
            .unwrap();
        panel::set_parent_model(ctx, Some(chain)).unwrap();
        panel::set_parent_bone(ctx, head as u32).unwrap();
        for (field, v) in [(0, 0.0), (1, 1.0), (2, 0.0)] {
            panel::set_field(ctx, field, v).unwrap();
        }
        ctx.run("ctl:487");
        assert_eq!(ctx.status, "");
    });
    let got = editor.doc.save().unwrap();
    let at = got.iter().zip(&want).position(|(a, b)| a != b);
    assert_eq!(
        (at, got.len()),
        (None, want.len()),
        "first differing byte of registered.pmm"
    );
    assert!(editor.modified);
}

/// `kAccessoryVisibleCheckbox` and `kAccessoryShadowCheckbox` flip `visible` and `shadowEnabled`
/// (`command_panel_toggles.cpp:532`, `:568`) and leave the rest of the record as it was.
#[test]
fn the_check_boxes_flip_one_flag_and_keep_the_record() {
    let mut editor = scene();
    let slot = tri(&editor);
    with_ctx(&mut editor, None, |ctx| {
        panel::select(ctx, slot).unwrap();
        for (field, v) in [(0, 1.5), (4, 45.0), (6, 3.0), (7, 0.37)] {
            panel::set_field(ctx, field, v).unwrap();
        }
    });
    let before = state(&editor);
    assert_eq!((before.opacity_visible & 1, before.shadow), (1, 0));

    with_ctx(&mut editor, None, |ctx| ctx.run("ctl:476"));
    let hidden = state(&editor);
    assert_eq!((hidden.opacity_visible & 1, hidden.shadow), (0, 0));
    assert_eq!(hidden.opacity_visible, before.opacity_visible & !1);
    assert_eq!(
        (hidden.position, hidden.rotation, hidden.scale),
        (before.position, before.rotation, before.scale)
    );

    with_ctx(&mut editor, None, |ctx| ctx.run("ctl:486"));
    let shadowed = state(&editor);
    assert_eq!((shadowed.opacity_visible & 1, shadowed.shadow), (0, 1));
    assert_eq!(shadowed.opacity_visible, hidden.opacity_visible);

    with_ctx(&mut editor, None, |ctx| {
        ctx.run("ctl:476");
        ctx.run("ctl:486");
    });
    let back = state(&editor);
    assert_eq!((back.opacity_visible & 1, back.shadow), (1, 0));
    assert_eq!(back.opacity_visible, before.opacity_visible);
    let saved = editor.doc.save().unwrap();
    assert!(mds_formats::pmm::Pmm::read(&saved).is_ok());
}

/// A toggle changes the visible bit and nothing else of the byte, whatever byte a file left.
#[test]
fn a_toggle_keeps_every_other_bit_of_the_opacity_byte() {
    let mut editor = scene();
    for b in 0..=255u8 {
        editor.doc.pmm.accessories[0].state.opacity_visible = b;
        with_ctx(&mut editor, None, |ctx| {
            ctx.run("ctl:476");
            assert_eq!(ctx.status, "");
        });
        assert_eq!(state(&editor).opacity_visible, b ^ 1, "byte {b}");
        with_ctx(&mut editor, None, |ctx| ctx.run("ctl:486"));
        assert_eq!(state(&editor).opacity_visible, b ^ 1, "byte {b} after 486");
    }
}

/// `CommitEditControl` for 485 clamps the opacity to 0 to 1 (`AccessoryEdit`).
#[test]
fn the_opacity_edit_is_clamped() {
    let mut editor = scene();
    with_ctx(&mut editor, None, |ctx| {
        panel::set_field(ctx, 7, 1.7).unwrap();
        assert_eq!(state(ctx.editor).opacity_visible, opacity_visible(1.0, 1));
        panel::set_field(ctx, 7, -0.2).unwrap();
        assert_eq!(state(ctx.editor).opacity_visible, opacity_visible(0.0, 1));
        assert!(panel::set_field(ctx, 8, 1.0).is_err());
    });
}

/// 474 with the ground entry detaches; 475 only counts under a parent
/// (`command_dispatch.cpp:300`, `:307`).
#[test]
fn the_parent_combos_follow_the_cpp() {
    let mut editor = scene();
    with_ctx(&mut editor, None, |ctx| {
        let chain = ctx.editor.doc.pmm.models[0].slot;
        panel::set_parent_bone(ctx, 2).unwrap();
        assert_eq!(state(ctx.editor).parent_bone, 0, "no parent model: ignored");
        panel::set_parent_model(ctx, Some(chain)).unwrap();
        panel::set_parent_bone(ctx, 2).unwrap();
        let s = state(ctx.editor);
        assert_eq!((s.parent_model, s.parent_bone), (i32::from(chain), 2));
        panel::set_parent_model(ctx, Some(chain.wrapping_add(1))).unwrap();
        assert_eq!(
            state(ctx.editor).parent_model,
            i32::from(chain),
            "no such model"
        );
        panel::set_parent_model(ctx, Some(chain)).unwrap();
        assert_eq!(
            state(ctx.editor).parent_bone,
            0,
            "a new parent starts at bone 0"
        );
        panel::set_parent_model(ctx, None).unwrap();
        assert_eq!(state(ctx.editor).parent_model, -1);
    });
}

/// `DisablePlaybackMenus`: the buttons, check boxes and edits are refused while playing.
#[test]
fn nothing_edits_during_playback() {
    let mut editor = scene();
    let slot = tri(&editor);
    editor.toggle_play(0).unwrap();
    assert!(editor.playing());
    let saved = editor.doc.save().unwrap();
    with_ctx(&mut editor, None, |ctx| {
        for id in ["ctl:472", "ctl:476", "ctl:486", "ctl:487"] {
            assert_eq!(
                actions::run(ctx, id),
                Err(format!("{id}: not while playing"))
            );
            assert!(!ctx.enabled(id), "{id}");
        }
        assert!(panel::set_field(ctx, 0, 5.0).is_err());
        assert!(panel::select(ctx, slot).is_err());
        assert!(panel::set_parent_model(ctx, None).is_err());
        assert!(panel::set_parent_bone(ctx, 1).is_err());
        assert!(ctx.enabled("ctl:488") && ctx.enabled("ctl:489"));
    });
    assert_eq!(editor.doc.save().unwrap(), saved);
}

/// Without an accessory the C++ handlers return before they touch anything
/// (`command_panel_toggles.cpp:536`, `:572`, `:597`).
#[test]
fn the_buttons_need_an_accessory() {
    let mut editor = Editor::empty();
    with_ctx(&mut editor, None, |ctx| {
        for id in ["ctl:476", "ctl:486", "ctl:487"] {
            assert_eq!(
                actions::run(ctx, id),
                Err("no accessory selected".to_string()),
                "{id}"
            );
        }
        assert_eq!(panel::set_field(ctx, 0, 1.0), Ok(()));
    });
    assert_eq!(editor.doc.pmm.accessories.len(), 0);
    assert!(!editor.modified);
}

/// A file that is not an accessory adds none; a missing file names itself in the error.
#[test]
fn loading_a_bad_file_adds_nothing() {
    let mut editor = Editor::empty();
    let saved = editor.doc.save().unwrap();
    with_ctx(&mut editor, None, |ctx| {
        let e = panel::load_file(ctx, ".\\chain8.pmx", &fixtures().join("chain8.pmx")).unwrap_err();
        assert!(e.contains("chain8.pmx"), "{e}");
        let missing = fixtures().join("no-such.x");
        let e = panel::load_file(ctx, ".\\no-such.x", &missing).unwrap_err();
        assert!(e.contains("no-such.x"), "{e}");
    });
    assert_eq!(editor.doc.save().unwrap(), saved);
}

/// Loading names the accessory after the last backslash and selects it (`LoadAccessoryFile`);
/// a second one gets the next combo order.
#[test]
fn loading_selects_the_accessory() {
    let mut editor = Editor::empty();
    with_ctx(&mut editor, None, |ctx| {
        let tri = fixtures().join("script/inputs/tri.x");
        panel::load_file(ctx, "C:\\x\\tri.x", &tri).unwrap();
        panel::load_file(ctx, "C:\\x\\again.x", &tri).unwrap();
    });
    let a = &editor.doc.pmm.accessories;
    let names: Vec<_> = a
        .iter()
        .map(|a| (a.list_name.text.as_str(), a.order))
        .collect();
    assert_eq!(names, [("tri.x", 0), ("again.x", 1)]);
    assert_eq!(editor.doc.pmm.selected_accessory_slot, a[1].slot);
    assert!(editor.modified);
}

/// 488 and 489 set the panel's open state, which lives in the window and not in the scene.
#[test]
fn the_panel_buttons_keep_the_state_outside_the_scene() {
    let mut editor = scene();
    let saved = editor.doc.save().unwrap();
    let egui = egui::Context::default();
    let open = |egui: &egui::Context| {
        egui.data(|d| d.get_temp::<bool>(egui::Id::unique("accessory-panel-expanded")))
    };
    with_ctx(&mut editor, Some(egui.clone()), |ctx| {
        ctx.run("ctl:488");
        assert_eq!(open(&egui), Some(false));
        ctx.run("ctl:489");
        assert_eq!(open(&egui), Some(true));
    });
    assert_eq!(editor.doc.save().unwrap(), saved);
}

/// Drawing the panel changes nothing in the scene.
#[test]
fn drawing_the_panel_leaves_the_scene_alone() {
    let mut editor = scene();
    let slot = tri(&editor);
    with_ctx(&mut editor, None, |ctx| {
        panel::select(ctx, slot).unwrap();
        for (field, v) in [(3, 33.0), (4, -170.0), (5, 12.5), (7, 0.3)] {
            panel::set_field(ctx, field, v).unwrap();
        }
        panel::set_parent_model(ctx, Some(ctx.editor.doc.pmm.models[0].slot)).unwrap();
    });
    let saved = editor.doc.save().unwrap();
    editor.modified = false;
    let egui = egui::Context::default();
    for open in [true, false, true] {
        with_ctx(&mut editor, Some(egui.clone()), |ctx| {
            ctx.run(if open { "ctl:489" } else { "ctl:488" });
            let mut out = egui.run_ui(egui::RawInput::default(), |ui| {
                panel::show(ui, ctx);
            });
            out.textures_delta.clear();
        });
    }
    assert_eq!(editor.doc.save().unwrap(), saved);
    assert!(!editor.modified);
    assert!(matches!(
        actions::find("ctl:478").unwrap().handler,
        Handler::Inline
    ));
}

/// Check box 477 toggles `additiveBlend` of the selected accessory and no other field
/// (`command_panel_toggles.cpp:554`).
#[test]
fn the_additive_box_toggles_one_flag() {
    let mut editor = scene();
    let slot = tri(&editor);
    with_ctx(&mut editor, None, |ctx| panel::select(ctx, slot).unwrap());
    let before = state(&editor);
    assert_eq!(before.additive, 0);
    let saved = editor.doc.save().unwrap();
    with_ctx(&mut editor, None, |ctx| ctx.run("ctl:477"));
    let on = state(&editor);
    assert_eq!(on.additive, 1);
    assert_eq!(
        (
            on.opacity_visible,
            on.shadow,
            on.scale,
            on.position,
            on.rotation
        ),
        (
            before.opacity_visible,
            before.shadow,
            before.scale,
            before.position,
            before.rotation
        )
    );
    assert_ne!(editor.doc.save().unwrap(), saved);
    with_ctx(&mut editor, None, |ctx| ctx.run("ctl:477"));
    assert_eq!(editor.doc.save().unwrap(), saved);
}

/// Button 473 (`DeleteSelectedAccessory`, `command_panel_toggles.cpp:222` to `:321`): the selected
/// accessory and its keys go, the orders above close up, and the accessory of order 0 becomes the
/// selected one.
#[test]
fn delete_removes_the_accessory_and_its_keys() {
    let mut editor = scene();
    with_ctx(&mut editor, None, |ctx| {
        panel::load_file(ctx, ".\\tri2.x", &fixtures().join("script/inputs/tri.x")).unwrap()
    });
    let slots: Vec<u8> = editor.doc.pmm.accessories.iter().map(|a| a.slot).collect();
    assert_eq!(slots.len(), 2);
    with_ctx(&mut editor, None, |ctx| {
        panel::select(ctx, slots[0]).unwrap();
        ctx.run("ctl:487");
        assert_eq!(ctx.status, "");
        panel::select(ctx, slots[1]).unwrap();
    });
    let before = editor.doc.pmm.accessories[1].clone();
    assert_eq!(before.order, 1);
    with_ctx(&mut editor, None, |ctx| {
        panel::select(ctx, slots[0]).unwrap();
        ctx.run("ctl:473");
        assert_eq!(ctx.status, "");
    });
    let left = &editor.doc.pmm.accessories;
    assert_eq!(left.len(), 1);
    assert_eq!((left[0].slot, left[0].order), (slots[1], 0));
    assert_eq!(editor.doc.pmm.selected_accessory_slot, slots[1]);
    assert!(editor.modified);
    let reloaded = mds_doc::Document::load(&editor.doc.save().unwrap(), |_| None).unwrap();
    assert_eq!(reloaded.pmm.accessories.len(), 1);
    assert_eq!(reloaded.pmm.accessories[0].slot, slots[1]);

    with_ctx(&mut editor, None, |ctx| ctx.run("ctl:473"));
    assert!(editor.doc.pmm.accessories.is_empty());
    let saved = editor.doc.save().unwrap();
    with_ctx(&mut editor, None, |ctx| {
        ctx.run("ctl:473");
        ctx.run("ctl:477");
        assert!(ctx.status.contains("no accessory selected"));
    });
    assert_eq!(editor.doc.save().unwrap(), saved, "nothing to delete");
}

#[test]
fn delete_and_additive_refuse_while_playing() {
    let mut editor = scene();
    editor.toggle_play(0).unwrap();
    for id in ["ctl:473", "ctl:477"] {
        let mut status = String::new();
        let r = mds_app::actions::run(
            &mut Ctx {
                editor: &mut editor,
                now_ms: 0,
                egui: None,
                viewport: None,
                status: &mut status,
            },
            id,
        );
        assert_eq!(r, Err(format!("{id}: not while playing")));
    }
}
