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

pub struct Action {
    /// The inventory id.
    pub id: &'static str,
    pub handler: Handler,
    /// Edits, replaces or writes the document. [`run`] refuses it while playing, as the C++ greys
    /// these out during playback (`DisablePlaybackMenus`, `src/app/playback_state.cpp:67`, and the
    /// control ranges `StopPlayback` enables again, `playback_state.cpp:345`).
    pub needs_document: bool,
}

impl Action {
    pub const fn run(id: &'static str, run: Run, needs_document: bool) -> Action {
        Action {
            id,
            handler: Handler::Run(run),
            needs_document,
        }
    }

    pub const fn inline(id: &'static str) -> Action {
        Action {
            id,
            handler: Handler::Inline,
            needs_document: false,
        }
    }

    pub const fn dropped(id: &'static str, reason: &'static str) -> Action {
        Action {
            id,
            handler: Handler::Dropped(reason),
            needs_document: false,
        }
    }
}

pub fn all() -> impl Iterator<Item = &'static Action> {
    AREAS.iter().flat_map(|a| (a.actions)())
}

pub fn find(id: &str) -> Option<&'static Action> {
    all().find(|a| a.id == id)
}

/// Whether [`run`] would run `id` now.
pub fn enabled(ctx: &Ctx, id: &str) -> bool {
    find(id).is_some_and(|a| {
        matches!(a.handler, Handler::Run(_)) && !(a.needs_document && ctx.editor.playing())
    })
}

pub fn run(ctx: &mut Ctx, id: &str) -> Result<(), String> {
    let action = find(id).ok_or_else(|| format!("{id}: not implemented"))?;
    match action.handler {
        Handler::Run(_) if action.needs_document && ctx.editor.playing() => {
            Err(format!("{id}: not while playing"))
        }
        Handler::Run(f) => f(ctx),
        Handler::Inline => Err(format!("{id}: a control, not a command")),
        Handler::Dropped(why) => Err(format!("{id}: dropped ({why})")),
    }
}
