//! The action table: every function of the UI, keyed by its stable id in
//! `tools/ui_inventory/inventory.tsv` (`menu:207`, `ctl:452`, `key:Ctrl+S`,
//! `mouse:rmb-drag`, ...). Menus, buttons and keys dispatch through [`run`].
//!
//! The rows live with the UI area that owns them (`actions()` of each `src/ui/<area>.rs`, see
//! [`crate::ui`]); [`all`] is their concatenation in [`crate::ui::AREAS`] order, so a UI slice
//! adds rows without editing a shared file. `tests/ui_coverage.rs` checks the table against the
//! inventory.

use crate::ui::{Ctx, AREAS};

/// A one-shot function: what a menu item, a button or a key chord does.
pub type Run = fn(&mut Ctx) -> Result<(), String>;

#[derive(Clone, Copy)]
pub enum Handler {
    Run(Run),
    /// A control that the area's `show` or `pass` edits in place (an edit box, a check box bound
    /// to a value, a viewport drag, a file drop). Implemented, with nothing to dispatch.
    Inline,
    /// A function the operator dropped, with the reason.
    Dropped(&'static str),
}

/// The edit mode an action runs in: the C++ greys out the controls and menus of the other mode
/// (`RestorePlaybackMenus`, `src/app/playback_state.cpp:94`, and the panels of each mode).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Any,
    /// Camera mode (`settings.options[0] != 0`).
    Camera,
    /// Model mode (`settings.options[0] == 0`).
    Model,
}

impl Mode {
    /// The mode the document is in now (never [`Mode::Any`]).
    pub fn of(ctx: &Ctx) -> Mode {
        match ctx.editor.doc.pmm.settings.options[0] {
            0 => Mode::Model,
            _ => Mode::Camera,
        }
    }
}

pub struct Action {
    /// The inventory id.
    pub id: &'static str,
    pub handler: Handler,
    /// Edits, replaces or writes the document. [`run`] refuses it while playing, as the C++ greys
    /// these out during playback (`DisablePlaybackMenus`, `src/app/playback_state.cpp:67`, and the
    /// control ranges `StopPlayback` enables again, `playback_state.cpp:345`).
    pub needs_document: bool,
    /// Set by [`Action::in_mode`]; ids ending in `@camera-mode` or `@model-mode` take the mode of
    /// the suffix ([`Action::mode`]).
    pub only: Mode,
}

impl Action {
    pub const fn run(id: &'static str, run: Run, needs_document: bool) -> Action {
        Action {
            id,
            handler: Handler::Run(run),
            needs_document,
            only: Mode::Any,
        }
    }

    pub const fn inline(id: &'static str) -> Action {
        Action {
            id,
            handler: Handler::Inline,
            needs_document: false,
            only: Mode::Any,
        }
    }

    pub const fn dropped(id: &'static str, reason: &'static str) -> Action {
        Action {
            id,
            handler: Handler::Dropped(reason),
            needs_document: false,
            only: Mode::Any,
        }
    }

    /// The action, run only in `mode` ([`enabled`] and [`run`] refuse it in the other).
    pub const fn in_mode(self, mode: Mode) -> Action {
        Action { only: mode, ..self }
    }

    /// The mode the action runs in.
    pub fn mode(&self) -> Mode {
        match self.only {
            Mode::Any if self.id.ends_with("@camera-mode") => Mode::Camera,
            Mode::Any if self.id.ends_with("@model-mode") => Mode::Model,
            m => m,
        }
    }

    fn refusal(&self, ctx: &Ctx) -> Option<&'static str> {
        if self.needs_document && ctx.editor.playing() {
            return Some("not while playing");
        }
        match (self.mode(), Mode::of(ctx)) {
            (Mode::Camera, Mode::Model) => Some("camera mode only"),
            (Mode::Model, Mode::Camera) => Some("model mode only"),
            _ => None,
        }
    }
}

pub fn all() -> impl Iterator<Item = &'static Action> {
    AREAS.iter().flat_map(|a| (a.actions)())
}

pub fn find(id: &str) -> Option<&'static Action> {
    all().find(|a| a.id == id)
}

/// Whether [`run`] would run `id` now: implemented, not refused while playing, and in its mode
/// ([`Action::mode`]).
pub fn enabled(ctx: &Ctx, id: &str) -> bool {
    find(id).is_some_and(|a| matches!(a.handler, Handler::Run(_)) && a.refusal(ctx).is_none())
}

pub fn run(ctx: &mut Ctx, id: &str) -> Result<(), String> {
    let action = find(id).ok_or_else(|| format!("{id}: not implemented"))?;
    match action.handler {
        Handler::Run(_) if action.refusal(ctx).is_some() => {
            Err(format!("{id}: {}", action.refusal(ctx).unwrap_or_default()))
        }
        Handler::Run(f) => f(ctx),
        Handler::Inline => Err(format!("{id}: a control, not a command")),
        Handler::Dropped(why) => Err(format!("{id}: dropped ({why})")),
    }
}
