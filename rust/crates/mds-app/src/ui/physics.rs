//! The `physics` menu, so far: "initialize bodies position" (268, `MDS_CMD_RESET_PHYSICS_BODIES`,
//! `src/window/command_view_menu.cpp:1154`).

use super::{button, Ctx};
use crate::actions::Action;

const ACTIONS: &[Action] = &[Action::run("menu:268", reset, false)];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn reset(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.reset_physics();
    Ok(())
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    button(ui, ctx, "menu:268", "initialize bodies position");
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
