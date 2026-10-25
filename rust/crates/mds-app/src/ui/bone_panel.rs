//! The `bone-panel` area, so far: the register button 500 and Enter in model mode
//! (`src/window/command_frame_register.cpp:375`; `PumpModelEnterRegister`,
//! `src/app/pump_edit_keys.cpp:358`), and the collapse and expand buttons 502 and 503
//! (`command_frame_register.cpp:402`; the C++ keeps the state in `options[4]` of the PMM, which no
//! command sets, so here it only lives in the window).
//!
//! Missing, for lack of a [`mds_doc::Command`] (see the slice report): the mode radios 490 to 493
//! and the keys C, X and Z (the viewport edit mode, `timeline.edit_mode`), select all 494 and A,
//! select unregistered 501 and S, reset 495, copy 496, paste 497 and reverse paste 498, and the
//! camera parent combos 449 and 450 (which the inventory files under this area by id).

use super::model_panel::selected_index;
use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::Command;

const ACTIONS: &[Action] = &[
    Action::run("ctl:500", register, true),
    Action::run("key:Enter@model-mode", register, true),
    Action::inline("ctl:502"),
    Action::inline("ctl:503"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// The selected bones' keys at the current frame. Without a model in the selected slot the C++
/// does nothing (`command_frame_register.cpp:384`).
fn register(ctx: &mut Ctx) -> Result<(), String> {
    if selected_index(&ctx.editor.doc).is_none() {
        return Ok(());
    }
    ctx.editor.apply(Command::RegisterBoneKeys)
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
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
    if expanded {
        button(ui, ctx, "ctl:500", "register");
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
