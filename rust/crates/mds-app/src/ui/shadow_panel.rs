//! The `shadow-panel` area: the mode buttons 562 to 564 (off, mode 1, mode 2), the range slider
//! 560 and edit 561 (0 to 9999, stored as `(10000 - value) / 100000`), register 565
//! (`src/window/command_frame_register.cpp:773` to `:882`, `src/window/ui_hscroll.cpp:262`,
//! `src/window/ui_edit_commit.cpp:332`), and Ctrl+G, which only says that the fine-shadow mode
//! moved to a button (`FineShadowModeNotice`, `src/window/command_view_menu.cpp:777`). The
//! collapse and expand buttons 566 and 567 are the section header of the side panel the shell
//! draws.
//!
//! Not yet: the Fshadow check box 556 (the shadow map's size, 0x800 or 0x1000) and Shift+G (the
//! shadow map shown over the viewport). Both are renderer state; `mds-render` has no
//! self-shadow map to size or show.

use super::camera_panel::{atof, camera_mode_only, edit_box, in_camera_mode, toggle, window_text};
use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::{Command, GlobalTrack};

const ACTIONS: &[Action] = &[
    Action::inline("ctl:560"),
    Action::inline("ctl:561"),
    Action::run("ctl:562", mode_off, false),
    Action::run("ctl:563", mode_1, false),
    Action::run("ctl:564", mode_2, false),
    Action::run("ctl:565", register, false),
    Action::inline("ctl:566"),
    Action::inline("ctl:567"),
    Action::run("key:Ctrl+G", fine_shadow_notice, false),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn mode(ctx: &Ctx) -> u8 {
    ctx.editor.doc.edit.self_shadow_mode
}

/// The shadow range as the slider and edit hold it: `10000 - distance * 100000`, rounded
/// (`src/window/ui_init.cpp:700`).
fn range(ctx: &Ctx) -> i32 {
    let d = f64::from(ctx.editor.doc.pmm.physics_interval);
    (10000.0 - d * 100000.0 + 0.5) as i32
}

fn set_mode(ctx: &mut Ctx, mode: u8) -> Result<(), String> {
    camera_mode_only(ctx)?;
    let distance = ctx.editor.doc.pmm.physics_interval;
    ctx.editor.apply(Command::SetSelfShadow { mode, distance })
}

fn mode_off(ctx: &mut Ctx) -> Result<(), String> {
    set_mode(ctx, 0)
}

fn mode_1(ctx: &mut Ctx) -> Result<(), String> {
    set_mode(ctx, 1)
}

fn mode_2(ctx: &mut Ctx) -> Result<(), String> {
    set_mode(ctx, 2)
}

/// The range `value` from slider 560 or edit 561: the distance is `(10000 - value) / 100000`.
pub fn set_range(ctx: &mut Ctx, value: f64) -> Result<(), String> {
    camera_mode_only(ctx)?;
    let mode = mode(ctx);
    let distance = ((10000.0 - value) / 100000.0) as f32;
    ctx.editor.apply(Command::SetSelfShadow { mode, distance })
}

pub fn commit_range(ctx: &mut Ctx, text: &str) -> Result<(), String> {
    set_range(ctx, atof(window_text(text, 8)))
}

/// Button 565: clear the marks, register the self-shadow key. The C++ reads the range edit
/// again first; the edit has committed on losing focus by then.
fn register(ctx: &mut Ctx) -> Result<(), String> {
    camera_mode_only(ctx)?;
    ctx.editor
        .apply(Command::RegisterGlobalKeys(vec![GlobalTrack::SelfShadow]))
}

const NOTICE_CAPTION: &str = "美影モード";
const NOTICE: &str = "この隠しコマンドは画面右上の「美　影」ボタンに取って変わりました";

/// Ctrl+G: the notice box. Without a window it goes to the status line.
fn fine_shadow_notice(ctx: &mut Ctx) -> Result<(), String> {
    if ctx.egui.is_none() {
        *ctx.status = NOTICE.into();
        return Ok(());
    }
    rfd::MessageDialog::new()
        .set_title(NOTICE_CAPTION)
        .set_description(NOTICE)
        .show();
    Ok(())
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if !in_camera_mode(ctx) {
        return;
    }
    let current = mode(ctx);
    ui.horizontal(|ui| {
        toggle(ui, ctx, "ctl:562", "off", current == 0);
        toggle(ui, ctx, "ctl:563", "mode1", current == 1);
        toggle(ui, ctx, "ctl:564", "mode2", current == 2);
    });
    let shown = range(ctx);
    ui.horizontal(|ui| {
        let mut pos = shown.clamp(0, 9999);
        if ui
            .add(egui::Slider::new(&mut pos, 0..=9999).show_value(false))
            .changed()
        {
            if let Err(e) = set_range(ctx, pos.into()) {
                *ctx.status = e;
            }
        }
        if let Some(text) = edit_box(ui, "shadow-range", &shown.to_string(), 48.0) {
            if let Err(e) = commit_range(ctx, &text) {
                *ctx.status = e;
            }
        }
        button(ui, ctx, "ctl:565", "register");
    });
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
