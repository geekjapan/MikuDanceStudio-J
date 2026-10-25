//! The `model-panel` area: load model 435 (`OpenModelFile`, `src/window/command_frame_edit.cpp:1135`),
//! the model combo 436 with Tab, Shift+Tab and the extra key left of Z (`ApplyModelComboSelection`,
//! `src/window/ui_model_reload.cpp:386`; `PumpTabCycle`, `src/app/pump_edit_keys.cpp:266`), the
//! model-mode register button 438 (`command_frame_edit.cpp:1548`), the IK chain combo 443 and the
//! model/camera toggle 536 (`src/window/command_frame_register.cpp:636`).
//!
//! Every action here goes through `Editor::apply`, which seeks the physics world, so the table
//! refuses them while playing, as the Tab handler does (`!playing()`).
//!
//! The check boxes 439 to 441 (`command_frame_edit.cpp:1566` to `:1592`) and the IK radios 444 and
//! 445 (`:1598` to `:1617`, on the chain the combo 443 has selected).
//!
//! Not here, for lack of a [`mds_doc::Command`]: 437 (delete model, `DeleteSelectedModel`) and 442
//! (the outside parent dialog, `EditAccessoryAttachments`).

use super::{button, Ctx};
use crate::actions::Action;
use crate::editor::Editor;
use mds_doc::{Command, Document, ModelFlag};
use rfd::FileDialog;

const ACTIONS: &[Action] = &[
    Action::run("ctl:435", load_dialog, true),
    Action::inline("ctl:436"),
    Action::run("ctl:438", register_display, true),
    Action::run("ctl:439", |c| flip(c, ModelFlag::Visible), true),
    Action::run("ctl:440", |c| flip(c, ModelFlag::Shadow), true),
    Action::run("ctl:441", |c| flip(c, ModelFlag::AddBlend), true),
    Action::inline("ctl:443"),
    Action::run("ctl:444", |c| ik(c, true), true),
    Action::run("ctl:445", |c| ik(c, false), true),
    Action::run("ctl:536", mode_toggle, true),
    Action::run("key:Tab", |c| cycle(c, true), true),
    Action::run("key:Shift+Tab", |c| cycle(c, false), true),
    Action::run("key:VK226", |c| cycle(c, true), true),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// The selected model's index in `pmm.models`, in model mode.
pub fn selected_index(doc: &Document) -> Option<usize> {
    doc.selected_model()?;
    let slot = doc.pmm.selected_model_slot;
    doc.pmm.models.iter().position(|m| m.slot == slot)
}

/// Entries of the model combo: the camera entry and one for each model.
pub fn combo_len(doc: &Document) -> u8 {
    doc.pmm.models.len() as u8 + 1
}

/// The combo's cursor: 0 in camera mode, else the selected model's `comboSelIndex`.
pub fn combo_cursor(doc: &Document) -> u8 {
    selected_index(doc).map_or(0, |i| doc.pmm.models[i].selection.combo_index)
}

/// The text of combo entry `entry`.
pub fn combo_text(doc: &Document, entry: u8) -> String {
    if entry == 0 {
        return "camera / light / accessory".into();
    }
    doc.pmm
        .models
        .iter()
        .find(|m| m.selection.combo_index == entry)
        .map_or_else(String::new, |m| m.name.text.clone())
}

/// `ApplyModelComboSelection` for the combo cursor `entry`: 0 is camera mode, else the model whose
/// `comboSelIndex` it is.
pub fn select_combo(ctx: &mut Ctx, entry: u8) -> Result<(), String> {
    let cmd = match entry {
        0 => Command::SelectCameraMode,
        n => {
            let m = ctx
                .editor
                .doc
                .pmm
                .models
                .iter()
                .find(|m| m.selection.combo_index == n)
                .ok_or("no model at that combo entry")?;
            Command::SelectModel(m.slot)
        }
    };
    ctx.editor.apply(cmd)
}

/// One step of the Tab handler: forward wraps to entry 0, backward wraps to the last entry.
fn cycle(ctx: &mut Ctx, forward: bool) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let (cursor, len) = (combo_cursor(doc), combo_len(doc));
    let entry = match (forward, cursor) {
        (true, c) if c + 1 >= len => 0,
        (true, c) => c + 1,
        (false, 0) => len - 1,
        (false, c) => c - 1,
    };
    select_combo(ctx, entry)
}

/// Button 536: from camera mode to the selected model, or to the load dialog when there is none;
/// from model mode to the camera entry.
fn mode_toggle(ctx: &mut Ctx) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    if doc.pmm.settings.options[0] == 0 {
        return select_combo(ctx, 0);
    }
    let slot = doc.pmm.selected_model_slot;
    match doc.pmm.models.iter().find(|m| m.slot == slot) {
        Some(m) => select_combo(ctx, m.selection.combo_index),
        None => load_dialog(ctx),
    }
}

fn flag_of(m: &mds_formats::pmm::Model, flag: ModelFlag) -> bool {
    let v = match flag {
        ModelFlag::Visible => m.selection.load_complete,
        ModelFlag::Shadow => m.toon,
        ModelFlag::AddBlend => m.post_load,
    };
    v != 0
}

/// Check boxes 439 to 441 on the selected model.
fn flip(ctx: &mut Ctx, flag: ModelFlag) -> Result<(), String> {
    let i = selected_index(&ctx.editor.doc).ok_or("no model selected")?;
    let on = !flag_of(&ctx.editor.doc.pmm.models[i], flag);
    ctx.editor.apply(Command::SetModelFlag { flag, on })
}

fn ik_chain_id() -> egui::Id {
    egui::Id::unique("model-panel-ik")
}

/// The chain the combo 443 has selected: the window keeps the cursor, a test has chain 0.
pub fn ik_chain(ctx: &Ctx) -> usize {
    ctx.egui
        .as_ref()
        .and_then(|e| e.data(|d| d.get_temp(ik_chain_id())))
        .unwrap_or(0)
}

/// Radios 444 (on) and 445 (off): the switch of the selected chain.
fn ik(ctx: &mut Ctx, on: bool) -> Result<(), String> {
    let chain = ik_chain(ctx) as u32;
    set_ik(ctx, chain, on)
}

pub fn set_ik(ctx: &mut Ctx, chain: u32, on: bool) -> Result<(), String> {
    selected_index(&ctx.editor.doc).ok_or("no model selected")?;
    ctx.editor.apply(Command::SetIkEnabled { chain, on })
}

fn register_display(ctx: &mut Ctx) -> Result<(), String> {
    if selected_index(&ctx.editor.doc).is_none() {
        return Err("no model selected".into());
    }
    ctx.editor.apply(Command::RegisterDisplayKey)
}

fn load_dialog(ctx: &mut Ctx) -> Result<(), String> {
    let Some(path) = FileDialog::new()
        .set_title("load model")
        .add_filter("All Model files(*.pmd,*.pmx)", &["pmd", "pmx"])
        .pick_file()
    else {
        return Ok(());
    };
    let data = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    load(ctx, &path.to_string_lossy(), data)
}

/// `LoadModelFile` with the path as the dialog returns it (the PMM stores it as given). The
/// editor is built again from the new document, because `Editor::apply` only rebuilds the meshes
/// and the physics world for a new scene; the view camera and the play panel carry over.
pub fn load(ctx: &mut Ctx, path: &str, data: Vec<u8>) -> Result<(), String> {
    let old = &mut *ctx.editor;
    let mut doc = old.doc.clone();
    doc.apply(Command::LoadModel {
        path: path.into(),
        data,
    })
    .map_err(|e| e.to_string())?;
    let mut fresh = Editor::new(doc, old.path.clone())?;
    fresh.modified = true;
    fresh.camera = old.camera;
    fresh.options = old.options;
    fresh.physics_opens += old.physics_opens;
    *old = fresh;
    Ok(())
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let playing = ctx.editor.playing();
    ui.horizontal(|ui| {
        button(ui, ctx, "ctl:435", "load");
        let camera = ctx.editor.doc.pmm.settings.options[0] != 0;
        button(
            ui,
            ctx,
            "ctl:536",
            if camera { "to model" } else { "to camera" },
        );
    });
    let (cursor, len) = (combo_cursor(&ctx.editor.doc), combo_len(&ctx.editor.doc));
    let mut picked = None;
    ui.add_enabled_ui(!playing, |ui| {
        egui::ComboBox::from_id_salt("model-combo")
            .selected_text(combo_text(&ctx.editor.doc, cursor))
            .show_ui(ui, |ui| {
                for entry in 0..len {
                    let text = combo_text(&ctx.editor.doc, entry);
                    if ui.selectable_label(entry == cursor, text).clicked() && entry != cursor {
                        picked = Some(entry);
                    }
                }
            });
    });
    if let Some(entry) = picked {
        if let Err(e) = select_combo(ctx, entry) {
            *ctx.status = e;
        }
    }
    let Some(i) = selected_index(&ctx.editor.doc) else {
        return;
    };
    button(ui, ctx, "ctl:438", "register");
    let m = &ctx.editor.doc.pmm.models[i];
    let flags = [
        ("ctl:439", "visible", flag_of(m, ModelFlag::Visible)),
        ("ctl:440", "shadow", flag_of(m, ModelFlag::Shadow)),
        ("ctl:441", "add blend", flag_of(m, ModelFlag::AddBlend)),
    ];
    for (id, label, on) in flags {
        let enabled = ctx.enabled(id);
        if ui
            .add_enabled(enabled, egui::Checkbox::new(&mut { on }, label))
            .clicked()
        {
            ctx.run(id);
        }
    }
    let m = &ctx.editor.doc.pmm.models[i];
    if m.ik_bones.is_empty() {
        return;
    }
    let mut chain: usize = ik_chain(ctx);
    chain = chain.min(m.ik_bones.len() - 1);
    let name = |c: usize| {
        usize::try_from(m.ik_bones[c])
            .ok()
            .and_then(|b| m.bone_names.get(b))
            .map_or_else(|| format!("ik {c}"), |n| n.text.clone())
    };
    egui::ComboBox::from_id_salt("model-ik-combo")
        .selected_text(name(chain))
        .show_ui(ui, |ui| {
            for c in 0..m.ik_bones.len() {
                ui.selectable_value(&mut chain, c, name(c));
            }
        });
    let on = m.ik_pose.get(chain).is_some_and(|&b| b != 0);
    ui.data_mut(|d| d.insert_temp(ik_chain_id(), chain));
    ui.horizontal(|ui| {
        for (id, label, shown) in [("ctl:444", "IK on", on), ("ctl:445", "IK off", !on)] {
            let enabled = ctx.enabled(id);
            if ui
                .add_enabled(enabled, egui::RadioButton::new(shown, label))
                .clicked()
            {
                ctx.run(id);
            }
        }
    });
}

/// Tab and Shift+Tab are one-shot chords ([`super::keys`]); the extra key left of Z, VK 226, is
/// egui's `IntlBackslash` and has no chord name, so it is read here as the C++ reads it.
pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if ui.ctx().egui_wants_keyboard_input() {
        return;
    }
    let shift = ui.input(|i| {
        i.events.iter().find_map(|e| match e {
            egui::Event::Key {
                key: egui::Key::IntlBackslash,
                pressed: true,
                repeat: false,
                modifiers,
                ..
            } => Some(modifiers.shift),
            _ => None,
        })
    });
    match shift {
        Some(false) => ctx.run("key:VK226"),
        Some(true) => ctx.run("key:Shift+Tab"),
        None => {}
    }
}
