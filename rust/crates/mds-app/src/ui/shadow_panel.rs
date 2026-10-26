//! The `shadow-panel` area: the mode buttons 562 to 564 (off, mode 1, mode 2), the range slider
//! 560 and edit 561 (0 to 9999, stored as `(10000 - value) / 100000`), register 565
//! (`src/window/command_frame_register.cpp:773` to `:882`, `src/window/ui_hscroll.cpp:262`,
//! `src/window/ui_edit_commit.cpp:332`), and Ctrl+G, which only says that the fine-shadow mode
//! moved to a button (`FineShadowModeNotice`, `src/window/command_view_menu.cpp:777`). The
//! collapse and expand buttons 566 and 567 are the section header of the side panel the shell
//! draws.
//!
//! The Fshadow check box 556 (`command_frame_register.cpp:722`) sets the shadow map's size, 0x800
//! or 0x1000: renderer state, so it lives in the window ([`map_size`]) until `mds-render` has a
//! self-shadow map to size.
//!
//! Not yet: Shift+G, the shadow map shown over the viewport (`key_ladder.cpp:158`); `mds-render`
//! has no self-shadow map to show.

use super::camera_panel::{atof, camera_mode_only, edit_box, in_camera_mode, toggle, window_text};
use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::{Command, GlobalTrack};

const ACTIONS: &[Action] = &[
    Action::run("ctl:556", fine_shadow, false),
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

fn fine_id() -> egui::Id {
    egui::Id::unique("shadow-panel-fine")
}

/// The side of the square shadow map: 0x1000 with Fshadow checked, else 0x800.
pub fn map_size(egui: &egui::Context) -> u32 {
    match egui.data(|d| d.get_temp::<bool>(fine_id())) {
        Some(true) => 0x1000,
        _ => 0x800,
    }
}

/// Check box 556: flips the size. Without a window there is no renderer to tell.
fn fine_shadow(ctx: &mut Ctx) -> Result<(), String> {
    if let Some(egui) = &ctx.egui {
        let fine = map_size(egui) == 0x800;
        egui.data_mut(|d| d.insert_temp(fine_id(), fine));
    }
    Ok(())
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

/// The slider 560 at `position` (`ui_hscroll.cpp:262`): the distance is `(10000 - position) /
/// 100000`, the mode stays, and the scene is modified.
pub fn set_slider(ctx: &mut Ctx, position: i32) -> Result<(), String> {
    camera_mode_only(ctx)?;
    ctx.editor.apply(Command::SetSelfShadowSlider(position))
}

/// The range `value` from edit 561: the distance is `(10000 - value) / 100000`.
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
    let fine = map_size(ui.ctx()) == 0x1000;
    toggle(ui, ctx, "ctl:556", "Fshadow", fine);
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
            if let Err(e) = set_slider(ctx, pos) {
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
