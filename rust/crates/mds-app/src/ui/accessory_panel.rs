//! The `accessory-panel` area: the accessory section of the camera-mode panel, controls 471 to
//! 489. The handlers are in `src/window/command_panel_toggles.cpp` (`HandlePanelControl`,
//! `DeleteSelectedAccessory`), `src/window/command_dispatch.cpp` (the combos) and
//! `src/window/ui_edit_commit.cpp` (the edits); the document side is `mds-doc`
//! (`LoadAccessory`, `SelectAccessory`, `AccessoryEdit`, `SetAccessoryParentModel`,
//! `SetAccessoryParentBone`, `SetAccessory`, `RegisterGlobalKeys`).
//!
//! The combos and edits (471, 474, 475, 478 to 485) are drawn in place and write through
//! [`select`], [`set_parent_model`], [`set_parent_bone`] and [`set_field`], which a test calls
//! too. The buttons and check boxes run through the table.
//!
//! Button 473 asks the C++ confirmation box first (`DeleteSelectedAccessory`,
//! `command_panel_toggles.cpp:222`); a test has no window and no box.

use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::{Command, GlobalTrack};
use mds_formats::pmm::Accessory;
use std::path::Path;

/// The labels of the edits 478 to 485, in order: position X, Y, Z, rotation X, Y, Z (degrees), scale, opacity.
const EDIT_LABELS: [&str; 8] = ["X", "Y", "Z", "X", "Y", "Z", "拡大", "不透明度"];

const ACTIONS: &[Action] = &[
    Action::inline("ctl:471"),
    Action::run("ctl:472", load, true),
    Action::run("ctl:473", delete, true),
    Action::inline("ctl:474"),
    Action::inline("ctl:475"),
    Action::run("ctl:476", toggle_visible, true),
    Action::run("ctl:477", toggle_additive, true),
    Action::inline("ctl:478"),
    Action::inline("ctl:479"),
    Action::inline("ctl:480"),
    Action::inline("ctl:481"),
    Action::inline("ctl:482"),
    Action::inline("ctl:483"),
    Action::inline("ctl:484"),
    Action::inline("ctl:485"),
    Action::run("ctl:486", toggle_shadow, true),
    Action::run("ctl:487", register, true),
    Action::run("ctl:488", collapse, false),
    Action::run("ctl:489", expand, false),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// `PanelExpanded(UiPanel::Accessory)`: UI state of the window, never saved
/// (`src/window/command_panel_toggles.cpp:377`).
fn expanded_id() -> egui::Id {
    egui::Id::unique("accessory-panel-expanded")
}

fn set_expanded(ctx: &mut Ctx, on: bool) -> Result<(), String> {
    if let Some(egui) = &ctx.egui {
        egui.data_mut(|d| d.insert_temp(expanded_id(), on));
    }
    Ok(())
}

fn collapse(ctx: &mut Ctx) -> Result<(), String> {
    set_expanded(ctx, false)
}

fn expand(ctx: &mut Ctx) -> Result<(), String> {
    set_expanded(ctx, true)
}

/// The accessory the combo has selected (`SelectedAccessorySlot`).
fn selected<'a>(ctx: &'a Ctx) -> Option<&'a Accessory> {
    let pmm = &ctx.editor.doc.pmm;
    pmm.accessories
        .iter()
        .find(|a| a.slot == pmm.selected_accessory_slot)
}

fn apply(ctx: &mut Ctx, cmd: Command) -> Result<(), String> {
    if ctx.editor.playing() {
        return Err("not while playing".into());
    }
    ctx.editor.apply(cmd)
}

/// The accessory combo 471 (`command_dispatch.cpp:170`).
pub fn select(ctx: &mut Ctx, slot: u8) -> Result<(), String> {
    apply(ctx, Command::SelectAccessory(slot))
}

/// An edit of the selected accessory; the C++ handlers return at once without one
/// (`command_dispatch.cpp:303`, `ui_edit_commit.cpp:359`) and the scene stays unmodified.
fn apply_to_selected(ctx: &mut Ctx, cmd: Command) -> Result<(), String> {
    if selected(ctx).is_none() {
        return Ok(());
    }
    apply(ctx, cmd)
}

/// The parent model combo 474: a model slot, or `None` for the ground.
pub fn set_parent_model(ctx: &mut Ctx, model: Option<u8>) -> Result<(), String> {
    apply_to_selected(ctx, Command::SetAccessoryParentModel(model))
}

/// The parent bone combo 475: a bone index of the parent model.
pub fn set_parent_bone(ctx: &mut Ctx, bone: u32) -> Result<(), String> {
    apply_to_selected(ctx, Command::SetAccessoryParentBone(bone))
}

/// The edit `field` (0 to 7 for 478 to 485) set to `value`: position, rotation in degrees,
/// scale, opacity (clamped to 0 to 1 by the document).
pub fn set_field(ctx: &mut Ctx, field: u8, value: f64) -> Result<(), String> {
    apply_to_selected(ctx, Command::AccessoryEdit { field, value })
}

/// The whole percent of opacity the byte holds (`(100 - (b >> 1))`, the inverse of
/// `ScaleQuirkByte`, as `mds-doc` `refresh.rs` reads it).
fn percent(opacity_visible: u8) -> i32 {
    100 - i32::from(opacity_visible >> 1)
}

/// The opacity the panel shows.
fn opacity_of(opacity_visible: u8) -> f32 {
    percent(opacity_visible) as f32 / 100.0
}

/// An opacity that `ScaleQuirkByte` (`(int)(opacity * 100.0)`) turns back into the same percent,
/// whatever float rounding the division leaves, so that a flag toggle keeps the byte's other bits.
fn same_percent(opacity_visible: u8) -> f32 {
    let p = percent(opacity_visible) as f32;
    (p + 0.5_f32.copysign(p)) / 100.0
}

/// Button 472: the file dialog, then [`load_file`].
fn load(ctx: &mut Ctx) -> Result<(), String> {
    // ponytail: `.x` only; the document's LoadAccessory takes the bytes of a `.x` file and does
    // not read the `.vac` wrapper, so the C++ filter `*.x;*.vac` is cut to `*.x`.
    let Some(path) = rfd::FileDialog::new()
        .set_title("open file")
        .add_filter("accessory files(*.x)", &["x"])
        .pick_file()
    else {
        return Ok(());
    };
    // The loader takes the name after the last backslash, and the C++ stores the dialog's
    // Windows path; a path of another system gets the same separator.
    let pmm_path = path.to_string_lossy().replace('/', "\\");
    load_file(ctx, &pmm_path, &path)
}

/// `LoadAccessoryFile` of the file `path`, recorded in the scene as `pmm_path`.
pub fn load_file(ctx: &mut Ctx, pmm_path: &str, path: &Path) -> Result<(), String> {
    let data = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    apply(
        ctx,
        Command::LoadAccessory {
            path: pmm_path.to_string(),
            data,
        },
    )?;
    *ctx.status = format!("loaded {}", path.display());
    Ok(())
}

/// Check boxes 476 (visible) and 486 (shadow) flip one flag of the selected accessory and keep the
/// rest of its record (`SetAccessory` writes the whole record).
fn toggle(ctx: &mut Ctx, flip_visible: bool, flip_shadow: bool) -> Result<(), String> {
    let a = selected(ctx).ok_or("no accessory selected")?;
    let s = &a.state;
    let cmd = Command::SetAccessory {
        slot: a.slot,
        visible: (s.opacity_visible & 1 != 0) ^ flip_visible,
        opacity: same_percent(s.opacity_visible),
        shadow: (s.shadow != 0) ^ flip_shadow,
        parent_model: s.parent_model,
        parent_bone: s.parent_bone,
        position: s.position,
        rotation: s.rotation,
        scale: s.scale,
    };
    apply(ctx, cmd)
}

fn toggle_visible(ctx: &mut Ctx) -> Result<(), String> {
    toggle(ctx, true, false)
}

fn toggle_shadow(ctx: &mut Ctx) -> Result<(), String> {
    toggle(ctx, false, true)
}

/// Check box 477 (`command_panel_toggles.cpp:554`): the additive flag of the selected accessory.
fn toggle_additive(ctx: &mut Ctx) -> Result<(), String> {
    let on = selected(ctx).ok_or("no accessory selected")?.state.additive == 0;
    apply(ctx, Command::SetAccessoryAdditive(on))
}

/// Button 473 (`command_panel_toggles.cpp:222`): after the OK / Cancel box, the selected
/// accessory and its keys go. Nothing without a selected accessory.
fn delete(ctx: &mut Ctx) -> Result<(), String> {
    let Some(a) = selected(ctx) else {
        return Ok(());
    };
    let slot = a.slot;
    if ctx.egui.is_some() && !confirm_delete(&a.name.text) {
        return Ok(());
    }
    apply(ctx, Command::DeleteAccessory(slot))
}

/// `kMsgDelAccessoryJp` and `kCaptionDelAccessoryJp`.
fn confirm_delete(name: &str) -> bool {
    rfd::MessageDialog::new()
        .set_title("アクセサリ削除")
        .set_description(format!(
            "アクセサリ：{name}を削除します\nアクセサリのフレームデータも全て削除されます\n(この操作は元に戻す事はできません)\n\n削除してもよろしいですか？"
        ))
        .set_buttons(rfd::MessageButtons::OkCancel)
        .show()
        == rfd::MessageDialogResult::Ok
}

/// Button 487: the selected accessory's state as a key at the current frame
/// (`RegisterAccessoryKey`, `command_panel_toggles.cpp:590`). The edits commit as they change,
/// so the `CommitEditControl` loop of the C++ has nothing left to do.
fn register(ctx: &mut Ctx) -> Result<(), String> {
    let slot = selected(ctx).ok_or("no accessory selected")?.slot;
    ctx.editor
        .apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Accessory(
            slot,
        )]))
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let expanded = ui.data(|d| d.get_temp(expanded_id())).unwrap_or(true);
    ui.horizontal(|ui| {
        if expanded {
            button(ui, ctx, "ctl:488", "-");
        } else {
            button(ui, ctx, "ctl:489", "+");
        }
        ui.label("アクセサリ");
    });
    if !expanded {
        return;
    }
    let mut accessories: Vec<(u8, u8, String)> = ctx
        .editor
        .doc
        .pmm
        .accessories
        .iter()
        .map(|a| (a.order, a.slot, a.list_name.text.clone()))
        .collect();
    accessories.sort();
    let current = selected(ctx).map(|a| a.slot);
    let mut errors = Vec::new();
    ui.horizontal(|ui| {
        let text = accessories
            .iter()
            .find(|(_, s, _)| Some(*s) == current)
            .map_or("", |(_, _, n)| n.as_str());
        egui::ComboBox::from_id_salt("accessory-panel-list")
            .selected_text(text)
            .show_ui(ui, |ui| {
                for (_, slot, name) in &accessories {
                    if ui.selectable_label(Some(*slot) == current, name).clicked() {
                        errors.extend(select(ctx, *slot).err());
                    }
                }
            });
        button(ui, ctx, "ctl:472", "読込");
        button(ui, ctx, "ctl:473", "削除");
    });
    let playing = ctx.editor.playing();
    // The C++ does nothing without a selected accessory, and the edits are greyed out in playback.
    ui.add_enabled_ui(current.is_some() && !playing, |ui| {
        let Some(state) = selected(ctx).map(|a| a.state.clone()) else {
            return;
        };
        parent_row(ui, ctx, state.parent_model, state.parent_bone, &mut errors);
        let values: [f64; 8] = [
            state.position[0].into(),
            state.position[1].into(),
            state.position[2].into(),
            f64::from(state.rotation[0]).to_degrees(),
            f64::from(state.rotation[1]).to_degrees(),
            f64::from(state.rotation[2]).to_degrees(),
            state.scale.into(),
            opacity_of(state.opacity_visible).into(),
        ];
        egui::Grid::new("accessory-panel-edits").show(ui, |ui| {
            for (i, (label, value)) in EDIT_LABELS.iter().zip(values).enumerate() {
                if i == 0 {
                    ui.label("位置");
                } else if i == 3 {
                    ui.end_row();
                    ui.label("回転");
                } else if i == 6 {
                    ui.end_row();
                    ui.label("");
                }
                ui.horizontal(|ui| {
                    ui.label(*label);
                    let mut v = value;
                    let drag = egui::DragValue::new(&mut v).speed(if i == 7 { 0.01 } else { 0.1 });
                    let drag = if i == 7 { drag.range(0.0..=1.0) } else { drag };
                    if ui.add(drag).changed() {
                        errors.extend(set_field(ctx, i as u8, v).err());
                    }
                });
            }
        });
        ui.horizontal(|ui| {
            for (id, label, on) in [
                ("ctl:476", "表示", state.opacity_visible & 1 != 0),
                ("ctl:486", "影", state.shadow != 0),
            ] {
                let mut checked = on;
                if ui.checkbox(&mut checked, label).changed() {
                    ctx.run(id);
                }
            }
            let mut additive = state.additive != 0;
            if ui.checkbox(&mut additive, "加算").changed() {
                ctx.run("ctl:477");
            }
            button(ui, ctx, "ctl:487", "登録");
        });
    });
    if let Some(e) = errors.into_iter().next() {
        *ctx.status = e;
    }
}

/// The combos 474 (ground, then the models in combo order) and 475 (the bones of the parent).
fn parent_row(ui: &mut egui::Ui, ctx: &mut Ctx, model: i32, bone: i32, errors: &mut Vec<String>) {
    let mut models: Vec<(u8, u8, String)> = ctx
        .editor
        .doc
        .pmm
        .models
        .iter()
        .map(|m| (m.selection.combo_index, m.slot, m.name.text.clone()))
        .collect();
    models.sort();
    let bones: Vec<String> = ctx
        .editor
        .doc
        .pmm
        .models
        .iter()
        .find(|m| i32::from(m.slot) == model)
        .map(|m| m.bone_names.iter().map(|n| n.text.clone()).collect())
        .unwrap_or_default();
    ui.horizontal(|ui| {
        ui.label("親");
        let text = models
            .iter()
            .find(|(_, s, _)| i32::from(*s) == model)
            .map_or("地面", |(_, _, n)| n.as_str());
        egui::ComboBox::from_id_salt("accessory-panel-parent")
            .selected_text(text)
            .show_ui(ui, |ui| {
                if ui.selectable_label(model < 0, "地面").clicked() {
                    errors.extend(set_parent_model(ctx, None).err());
                }
                for (_, slot, name) in &models {
                    if ui
                        .selectable_label(i32::from(*slot) == model, name)
                        .clicked()
                    {
                        errors.extend(set_parent_model(ctx, Some(*slot)).err());
                    }
                }
            });
        egui::ComboBox::from_id_salt("accessory-panel-bone")
            .selected_text(bones.get(bone.max(0) as usize).map_or("", String::as_str))
            .show_ui(ui, |ui| {
                for (i, name) in bones.iter().enumerate() {
                    if ui.selectable_label(i as i32 == bone, name).clicked() {
                        errors.extend(set_parent_bone(ctx, i as u32).err());
                    }
                }
            });
    });
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
