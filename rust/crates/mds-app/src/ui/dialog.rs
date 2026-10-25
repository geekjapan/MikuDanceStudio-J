//! The `dialog` area of the UI inventory. Not ported yet: see [`crate::ui`] for the contract.

use super::Ctx;
use crate::actions::Action;

pub fn actions() -> &'static [Action] {
    &[]
}

pub fn show(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
