//! The `mme` area: the MMEffect menu (`third_party/mmeffect/res/MMEffect.rc`, dispatched by
//! `MmeMainWindowProc` in `third_party/mmeffect/src/mmeffect/mme_ui.cpp`) and its log window; and
//! in [`dialog`], the `mme-dialog` area: the effect mapping dialog (`mme_dlg.cpp`).

use super::Ctx;
use crate::actions::Action;

const ACTIONS: &[Action] = &[];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

pub fn show(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}

pub mod dialog {
    use super::Ctx;
    use crate::actions::Action;

    const ACTIONS: &[Action] = &[];

    pub fn actions() -> &'static [Action] {
        ACTIONS
    }

    pub fn show(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}

    pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
}
