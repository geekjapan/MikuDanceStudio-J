//! The `bone-panel` area: the register button 500 and Enter in model mode
//! (`src/window/command_frame_register.cpp:375`; `PumpModelEnterRegister`,
//! `src/app/pump_edit_keys.cpp:358`), the edit mode radios 490 to 493 with the keys C, X and Z
//! (`command_panel_toggles.cpp:612` to `:650`; `key_ladder.cpp:99`, `:259`, `:290`), select all
//! 494 and A (`command_panel_toggles.cpp:658`), select unregistered 501 and S
//! (`command_frame_register.cpp:399`), reset 495, copy 496, paste 497 and reverse paste 498
//! (`command_panel_toggles.cpp:696` to `:730`), and the collapse and expand buttons 502 and 503
//! (`command_frame_register.cpp:402`; kept in the window, although `Command::SetPanelExpanded`
//! could now store it in `options[4]`).
//!
//! The camera parent combos 449 and 450 (`command_dispatch.cpp:203` to `:293`) are filed under
//! this area by their id; they exist in camera mode only, so `show` draws them there. The bone
//! combo lists every bone of the parent: the C++ lists the fixed-axis bones and those of type 0
//! to 6 (`RepopulateBoneCombo`), a type the PMM does not carry.
//!
//! The keys do nothing in camera mode, as the C++ gates them on `modelMode()`.
//!
//! The edit mode, the selection and the copy are no scene edit in the C++ (none sets
//! `SceneModified`), so [`view_command`] keeps [`Editor::modified`] as it was.

use super::camera_panel::camera_mode_only;
use super::model_panel::{combo_len, combo_text, selected_index};
use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::Command;

/// `ViewportEditMode` (`include/mikudancestudio/mmd_app.hpp:67`).
const BONE: i32 = 0;
const BOX: i32 = 1;
const NONE: i32 = 2;
const ROTATE: i32 = 3;
const MOVE: i32 = 4;

const ACTIONS: &[Action] = &[
    Action::inline("ctl:449"),
    Action::inline("ctl:450"),
    Action::run("ctl:490", |c| edit_mode(c, BONE), true),
    Action::run("ctl:491", |c| edit_mode(c, BOX), true),
    Action::run("ctl:492", |c| edit_mode(c, MOVE), true),
    Action::run("ctl:493", |c| edit_mode(c, ROTATE), true),
    Action::run("ctl:494", select_all, true),
    Action::run("ctl:495", reset, true),
    Action::run("ctl:496", copy, true),
    Action::run("ctl:497", |c| paste(c, false), true),
    Action::run("ctl:498", |c| paste(c, true), true),
    Action::run("ctl:500", register, true),
    Action::run("ctl:501", select_unregistered, true),
    Action::inline("ctl:502"),
    Action::inline("ctl:503"),
    Action::run("key:C", |c| model_key(c, toggle_bone_mode), true),
    Action::run("key:X", |c| model_key(c, |c| edit_mode(c, ROTATE)), true),
    Action::run("key:Z", |c| model_key(c, |c| edit_mode(c, MOVE)), true),
    Action::run("key:A", |c| model_key(c, select_all), true),
    Action::run("key:S", |c| model_key(c, select_unregistered), true),
    Action::run("key:Enter@model-mode", register, true),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn camera_mode(ctx: &Ctx) -> bool {
    ctx.editor.doc.pmm.settings.options[0] != 0
}

fn model_mode_only(ctx: &Ctx) -> Result<(), String> {
    match camera_mode(ctx) {
        true => Err("model mode only".into()),
        false => Ok(()),
    }
}

/// A key of the model ladder: nothing in camera mode.
fn model_key(ctx: &mut Ctx, run: fn(&mut Ctx) -> Result<(), String>) -> Result<(), String> {
    match camera_mode(ctx) {
        true => Ok(()),
        false => run(ctx),
    }
}

/// `cmd` for a view or selection function: the scene stays unmodified.
fn view_command(ctx: &mut Ctx, cmd: Command) -> Result<(), String> {
    let modified = ctx.editor.modified;
    ctx.editor.apply(cmd)?;
    ctx.editor.modified = modified;
    Ok(())
}

/// The radios 490 to 493 and the keys X and Z: `timeline.edit_mode`.
fn edit_mode(ctx: &mut Ctx, mode: i32) -> Result<(), String> {
    model_mode_only(ctx)?;
    view_command(ctx, Command::SetEditMode(mode))
}

/// Key C: the bone mode radio, off when it was on.
fn toggle_bone_mode(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.pmm.timeline.edit_mode == BONE;
    edit_mode(ctx, if on { NONE } else { BONE })
}

/// Button 494 and key A, which also checks the bone mode radio.
fn select_all(ctx: &mut Ctx) -> Result<(), String> {
    model_mode_only(ctx)?;
    view_command(ctx, Command::SelectAllBones)
}

/// Button 501 and key S.
fn select_unregistered(ctx: &mut Ctx) -> Result<(), String> {
    model_mode_only(ctx)?;
    view_command(ctx, Command::SelectUnregisteredBones)
}

fn reset(ctx: &mut Ctx) -> Result<(), String> {
    model_mode_only(ctx)?;
    ctx.editor.apply(Command::ResetBonePose)
}

fn copy(ctx: &mut Ctx) -> Result<(), String> {
    model_mode_only(ctx)?;
    view_command(ctx, Command::CopyBonePose)
}

/// Button 497, or 498 with `mirror`.
fn paste(ctx: &mut Ctx, mirror: bool) -> Result<(), String> {
    model_mode_only(ctx)?;
    ctx.editor.apply(Command::PasteBonePose { mirror })
}

/// The selected bones' keys at the current frame. Without a model in the selected slot the C++
/// does nothing (`command_frame_register.cpp:384`).
fn register(ctx: &mut Ctx) -> Result<(), String> {
    if selected_index(&ctx.editor.doc).is_none() {
        return Ok(());
    }
    ctx.editor.apply(Command::RegisterBoneKeys)
}

fn stopped(ctx: &Ctx) -> Result<(), String> {
    match ctx.editor.playing() {
        true => Err("not while playing".into()),
        false => Ok(()),
    }
}

/// The combo 449's cursor: 0 for no parent, else the parent model's `comboSelIndex`.
pub fn camera_parent_entry(ctx: &Ctx) -> u8 {
    let pmm = &ctx.editor.doc.pmm;
    let parent = pmm.appearance.camera_parent_model;
    pmm.models
        .iter()
        .find(|m| i32::from(m.slot) == parent)
        .map_or(0, |m| m.selection.combo_index)
}

/// The combo 449 at `entry`: 0 detaches the camera, else the model whose `comboSelIndex` it is
/// becomes the parent.
pub fn set_camera_parent_model(ctx: &mut Ctx, entry: u8) -> Result<(), String> {
    camera_mode_only(ctx)?;
    stopped(ctx)?;
    let slot = match entry {
        0 => None,
        n => Some(
            ctx.editor
                .doc
                .pmm
                .models
                .iter()
                .find(|m| m.selection.combo_index == n)
                .ok_or("no model at that combo entry")?
                .slot,
        ),
    };
    ctx.editor.apply(Command::SetCameraParentModel(slot))
}

/// The combo 450: bone `bone` of the parent model. Without a parent the C++ finds no bone to
/// store.
pub fn set_camera_parent_bone(ctx: &mut Ctx, bone: u32) -> Result<(), String> {
    camera_mode_only(ctx)?;
    stopped(ctx)?;
    ctx.editor.apply(Command::SetCameraParentBone(bone))
}

fn camera_parent_row(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let (entry, len) = (camera_parent_entry(ctx), combo_len(&ctx.editor.doc));
    let bones: Vec<String> = {
        let pmm = &ctx.editor.doc.pmm;
        let parent = pmm.appearance.camera_parent_model;
        pmm.models
            .iter()
            .find(|m| i32::from(m.slot) == parent)
            .map(|m| m.bone_names.iter().map(|n| n.text.clone()).collect())
            .unwrap_or_default()
    };
    let bone = ctx.editor.doc.pmm.appearance.camera_parent_bone.max(0) as usize;
    let text = |entry| match entry {
        0 => "non".to_owned(),
        n => combo_text(&ctx.editor.doc, n),
    };
    let mut model = None;
    let mut parent_bone = None;
    ui.add_enabled_ui(!ctx.editor.playing(), |ui| {
        ui.horizontal(|ui| {
            egui::ComboBox::from_id_salt("camera-parent-model")
                .selected_text(text(entry))
                .show_ui(ui, |ui| {
                    for n in 0..len {
                        if ui.selectable_label(n == entry, text(n)).clicked() && n != entry {
                            model = Some(n);
                        }
                    }
                });
            egui::ComboBox::from_id_salt("camera-parent-bone")
                .selected_text(bones.get(bone).map_or("", String::as_str))
                .show_ui(ui, |ui| {
                    for (i, name) in bones.iter().enumerate() {
                        if ui.selectable_label(i == bone, name).clicked() {
                            parent_bone = Some(i as u32);
                        }
                    }
                });
        });
    });
    let result = match (model, parent_bone) {
        (Some(n), _) => set_camera_parent_model(ctx, n),
        (None, Some(b)) => set_camera_parent_bone(ctx, b),
        _ => Ok(()),
    };
    if let Err(e) = result {
        *ctx.status = e;
    }
}

fn radio(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, label: &str, on: bool) {
    if ui
        .add_enabled(ctx.enabled(id), egui::RadioButton::new(on, label))
        .clicked()
    {
        ctx.run(id);
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if camera_mode(ctx) {
        camera_parent_row(ui, ctx);
        return;
    }
    if selected_index(&ctx.editor.doc).is_none() {
        ui.label("no model selected");
        return;
    }
    let id = egui::Id::unique("bone-panel-expanded");
    let initial = ctx.editor.doc.pmm.settings.options[4] != 0;
    let expanded: bool = ui.data(|d| d.get_temp(id)).unwrap_or(initial);
    // 502 collapses and 503 expands; each shows while the other state holds.
    if expanded && ui.small_button("-").clicked() {
        ui.data_mut(|d| d.insert_temp(id, false));
    } else if !expanded && ui.small_button("+").clicked() {
        ui.data_mut(|d| d.insert_temp(id, true));
    }
    if !expanded {
        return;
    }
    let mode = ctx.editor.doc.pmm.timeline.edit_mode;
    ui.horizontal_wrapped(|ui| {
        radio(ui, ctx, "ctl:490", "select", mode == BONE);
        radio(ui, ctx, "ctl:491", "BOX-sel", mode == BOX);
        radio(ui, ctx, "ctl:492", "move", mode == MOVE);
        radio(ui, ctx, "ctl:493", "rotate", mode == ROTATE);
    });
    ui.horizontal_wrapped(|ui| {
        button(ui, ctx, "ctl:494", "select all");
        button(ui, ctx, "ctl:501", "unregisted");
        button(ui, ctx, "ctl:500", "register");
    });
    ui.horizontal_wrapped(|ui| {
        button(ui, ctx, "ctl:495", "reset");
        button(ui, ctx, "ctl:496", "copy");
        button(ui, ctx, "ctl:497", "paste");
        button(ui, ctx, "ctl:498", "revers");
    });
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
