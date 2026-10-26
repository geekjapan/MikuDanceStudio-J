//! The UI, one file per area of `tools/ui_inventory/inventory.tsv`. Read this first if you own
//! a UI slice.
//!
//! # Contract
//!
//! Each area file `src/ui/<area>.rs` (the inventory area with `-` as `_`) exposes exactly:
//!
//! * `pub fn actions() -> &'static [Action]`: the area's rows of the action table
//!   ([`crate::actions`]), one per inventory id the area implements or drops. Only ids of the
//!   area's own inventory rows go here (`tests/ui_coverage.rs` fails otherwise).
//! * `pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx)`: draws the area where [`AREAS`] places it
//!   ([`Place`]). A menu area draws the items inside its menu; a panel area draws its controls.
//! * `pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx)`: runs once every window pass, before the
//!   panels and whether or not the area is visible, for input that belongs to no widget (held
//!   keys, dropped files, the close request).
//!
//! Buttons and menu items run their action through [`button`] / [`Ctx::run`], never the handler
//! directly, so every function goes through the table. One-shot key chords need no code in the
//! area: [`keys`] maps each key press to `key:<chord>` (then `key:<chord>@camera-mode` or
//! `@model-mode`) and runs the action with that id. The arrow keys are left to `timeline`,
//! which repeats them while held.
//!
//! A UI slice owns its area file and its tests, nothing else. Its area is done when every
//! inventory row of the area has an action; it then adds the area to [`COMPLETE`] (the one
//! shared line it touches), and `tests/ui_coverage.rs` keeps it complete.
//!
//! Per-area state that must outlive a pass goes into egui's memory under an id of the area
//! (`ui.data_mut(|d| d.get_temp_mut_or_default::<T>(egui::Id::unique(..)))`), not into shared structs.
//! Document state is changed only through [`Editor`] (`ctx.editor.apply(Command)` and the
//! playback and physics calls), which keeps the derived pose, physics and view in step.

use crate::actions::{self, Action};
use crate::editor::Editor;
use crate::viewport::WindowViewport;
use egui::{Event, Key};

pub mod accessory_panel;
pub mod background;
pub mod bone_panel;
pub mod camera_panel;
pub mod dialog;
pub mod edit;
pub mod expression;
pub mod file;
pub mod help;
pub mod light_panel;
pub mod mme;
pub mod mocap;
pub mod model_panel;
pub mod morph_panel;
pub mod physics;
pub mod play;
pub mod shadow_panel;
pub mod timeline;
pub mod view;
pub mod viewport;
// The mapping dialog lives in `mme.rs`, the one area file of the `mme` slice.
pub use mme::dialog as mme_dialog;

/// What an area's code gets each call.
pub struct Ctx<'a> {
    pub editor: &'a mut Editor,
    /// The wall clock of this pass, in milliseconds.
    pub now_ms: u64,
    /// egui's context in the window; `None` in tests.
    pub egui: Option<egui::Context>,
    /// The window's viewport; `None` in tests.
    pub viewport: Option<&'a mut WindowViewport>,
    /// The status line: the last error or notice.
    pub status: &'a mut String,
}

impl Ctx<'_> {
    /// Runs the action `id`; an error goes to the status line.
    pub fn run(&mut self, id: &str) {
        if let Err(e) = actions::run(self, id) {
            *self.status = e;
        }
    }

    pub fn enabled(&self, id: &str) -> bool {
        actions::enabled(self, id)
    }
}

/// A button (or menu item) for action `id`, greyed out when the action cannot run.
pub fn button(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, label: &str) {
    if ui
        .add_enabled(ctx.enabled(id), egui::Button::new(label))
        .clicked()
    {
        ctx.run(id);
    }
}

/// Where the shell draws an area's `show`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Place {
    /// A top-level menu with this title.
    Menu(&'static str),
    /// A row of the bottom panel.
    Bottom,
    /// A section of the right-hand panel, shown once the area has actions.
    Side,
    /// The central panel.
    Viewport,
    /// Windows over the central panel (`show` is called once per pass, after the viewport).
    Dialog,
}

pub struct Area {
    /// The inventory area.
    pub name: &'static str,
    pub place: Place,
    pub actions: fn() -> &'static [Action],
    pub show: fn(&mut egui::Ui, &mut Ctx),
    pub pass: fn(&mut egui::Ui, &mut Ctx),
}

macro_rules! area {
    ($name:literal, $module:ident, $place:expr) => {
        Area {
            name: $name,
            place: $place,
            actions: $module::actions,
            show: $module::show,
            pass: $module::pass,
        }
    };
}

/// Every area, in menu-bar and panel order.
pub const AREAS: [Area; 21] = [
    area!("file", file, Place::Menu("File")),
    area!("edit", edit, Place::Menu("Edit")),
    area!("view", view, Place::Menu("View")),
    area!("background", background, Place::Menu("Background")),
    area!("expression", expression, Place::Menu("Expression")),
    area!("physics", physics, Place::Menu("Physics")),
    area!("mocap", mocap, Place::Menu("MoCap")),
    area!("help", help, Place::Menu("Help")),
    area!("mme", mme, Place::Menu("MMEffect")),
    area!("play", play, Place::Bottom),
    area!("timeline", timeline, Place::Bottom),
    area!("model-panel", model_panel, Place::Side),
    area!("camera-panel", camera_panel, Place::Side),
    area!("light-panel", light_panel, Place::Side),
    area!("accessory-panel", accessory_panel, Place::Side),
    area!("bone-panel", bone_panel, Place::Side),
    area!("morph-panel", morph_panel, Place::Side),
    area!("shadow-panel", shadow_panel, Place::Side),
    area!("viewport", viewport, Place::Viewport),
    area!("dialog", dialog, Place::Dialog),
    area!("mme-dialog", mme_dialog, Place::Dialog),
];

/// Areas whose every inventory row has an action.
pub const COMPLETE: &[&str] = &[
    "accessory-panel",
    "bone-panel",
    "edit",
    "light-panel",
    "morph-panel",
    "play",
    "view",
];

/// The inventory name of a key with its modifiers (`Ctrl+S`, `Numpad2`, `Enter`, `]`), or
/// `None` for keys the inventory does not name and for the arrows.
pub fn chord(key: Key, m: egui::Modifiers) -> Option<String> {
    let name = match key {
        Key::Num0
        | Key::Num1
        | Key::Num2
        | Key::Num3
        | Key::Num4
        | Key::Num5
        | Key::Num6
        | Key::Num7
        | Key::Num8
        | Key::Num9 => format!("Numpad{}", key.name()),
        Key::Enter | Key::Delete | Key::Tab => key.name().to_string(),
        Key::Escape => "Esc".into(),
        Key::CloseBracket => "]".into(),
        k if k.name().len() == 1 && k.name().as_bytes()[0].is_ascii_uppercase() => {
            k.name().to_string()
        }
        _ => return None,
    };
    let mut out = String::new();
    // Command is Ctrl on Windows and Linux and Cmd on macOS.
    if m.command || m.ctrl {
        out.push_str("Ctrl+");
    }
    if m.shift {
        out.push_str("Shift+");
    }
    if m.alt {
        out.push_str("Alt+");
    }
    out.push_str(&name);
    Some(out)
}

/// Runs the action of every key press of this pass (see the module doc).
pub fn keys(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if ui.ctx().egui_wants_keyboard_input() {
        return;
    }
    let presses: Vec<_> = ui.input(|i| {
        i.events
            .iter()
            .filter_map(|e| match e {
                Event::Key {
                    key,
                    pressed: true,
                    repeat: false,
                    modifiers,
                    ..
                } => chord(*key, *modifiers),
                _ => None,
            })
            .collect()
    });
    let mode = match ctx.editor.doc.pmm.settings.options[0] {
        0 => "model-mode",
        _ => "camera-mode",
    };
    for chord in presses {
        let plain = format!("key:{chord}");
        let moded = format!("{plain}@{mode}");
        if let Some(a) = [plain, moded].iter().find_map(|id| actions::find(id)) {
            ctx.run(a.id);
        }
    }
}
