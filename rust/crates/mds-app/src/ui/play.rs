//! The `play` area: the play button 408 and P, and the play panel's edits and check boxes
//! (409, 410, 411, 413, 414; `src/window/command_frame_edit.cpp:1423` to `:1438`). The edits
//! are greyed out while playing, as `StopPlayback` enables them again.

use super::Ctx;
use crate::actions::Action;

const ACTIONS: &[Action] = &[
    Action::run("ctl:408", toggle_play, false),
    Action::run("key:P", toggle_play, false),
    Action::inline("ctl:409"),
    Action::inline("ctl:410"),
    Action::inline("ctl:411"),
    Action::inline("ctl:413"),
    Action::inline("ctl:414"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn toggle_play(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.toggle_play(ctx.now_ms)
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let playing = ctx.editor.playing();
    super::button(ui, ctx, "ctl:408", if playing { "stop" } else { "play" });
    let o = &mut ctx.editor.options;
    ui.add_enabled_ui(!playing, |ui| {
        ui.label("play");
        ui.add(egui::DragValue::new(&mut o.start_frame).range(0..=99_999));
        ui.label("to");
        ui.add(egui::DragValue::new(&mut o.stop_frame).range(0..=99_999));
        ui.checkbox(&mut o.from_current, "from current");
        ui.checkbox(&mut o.stop_at_playhead, "stop at playhead");
    });
    ui.checkbox(&mut o.looped, "loop");
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
