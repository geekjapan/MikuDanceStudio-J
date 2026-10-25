//! The `timeline` area, so far: undo and redo (400, 401, Ctrl+Z, Ctrl+X), the frame step
//! buttons 418 and 419 and the arrows (`StepFrame`, `src/window/ui_frame_step.cpp`; the hold
//! repeat of `ConsumeArrowKeyNavigation`, `src/app/pump_navigation.cpp:238`), and the current
//! frame edit 417.

use super::{button, Ctx};
use crate::actions::Action;
use crate::navigation::{KeyState, Repeat};
use egui::Key;
use mds_doc::Command;

const ACTIONS: &[Action] = &[
    Action::run("ctl:400", undo, true),
    Action::run("ctl:401", redo, true),
    Action::run("key:Ctrl+Z", undo, true),
    Action::run("key:Ctrl+X", redo, true),
    Action::run("ctl:418", previous, true),
    Action::run("ctl:419", next, true),
    Action::run("key:Left", previous, true),
    Action::run("key:Right", next, true),
    Action::inline("ctl:417"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn undo(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::Undo)
}

fn redo(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::Redo)
}

fn previous(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.step_frame(false)
}

fn next(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.step_frame(true)
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    button(ui, ctx, "ctl:400", "undo");
    button(ui, ctx, "ctl:401", "redo");
    ui.separator();
    button(ui, ctx, "ctl:418", "<");
    let playing = ctx.editor.playing();
    let mut frame = ctx.editor.current_frame();
    let t = &ctx.editor.doc.pmm.timeline;
    let last = (t.last_registered_frame.max(t.play_stop_frame).max(0) as u32).max(frame);
    let changed = ui
        .add_enabled_ui(!playing, |ui| {
            ui.add(egui::DragValue::new(&mut frame).range(0..=99_999))
                .changed()
                | ui.add(egui::Slider::new(&mut frame, 0..=last).show_value(false))
                    .changed()
        })
        .inner;
    if changed {
        if let Err(e) = ctx.editor.seek(frame) {
            *ctx.status = e;
        }
    }
    button(ui, ctx, "ctl:419", ">");
    ui.label(format!("frame {}", ctx.editor.shown_frame()));
}

/// The arrows' hold state between passes.
#[derive(Clone, Copy, Default)]
struct Arrows {
    repeat: Repeat,
    down: [bool; 2],
}

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let id = egui::Id::unique("timeline-arrows");
    let mut s: Arrows = ui.data(|d| d.get_temp(id)).unwrap_or_default();
    let free = !ui.ctx().egui_wants_keyboard_input() && !ctx.editor.playing();
    let (dt, ctrl, keys) = ui.input(|i| {
        let ctrl = i.modifiers.command || i.modifiers.ctrl;
        let keys = [Key::ArrowLeft, Key::ArrowRight].map(|k| free && i.key_down(k));
        (i.unstable_dt, ctrl, keys)
    });
    for (k, action) in ["key:Left", "key:Right"].into_iter().enumerate() {
        if s.repeat.step(KeyState::of(s.down[k], keys[k]), ctrl, dt) {
            ctx.run(action);
        }
        s.down[k] = keys[k];
    }
    ui.data_mut(|d| d.insert_temp(id, s));
}
