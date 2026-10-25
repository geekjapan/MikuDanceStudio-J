//! The `light-panel` area: the colour sliders 455 to 457 and edits 461 to 463 (0 to 255, stored
//! as value / 256), the direction sliders 458 to 460 (-100 to 100, stored as value / 100) and
//! edits 464 to 466, reset 467 and register 468 (`src/window/ui_hscroll.cpp:168` to `:229`,
//! `src/window/ui_edit_commit.cpp:291` to `:322`, `src/window/command_panel_toggles.cpp:405` and
//! `:459`). The collapse and expand buttons 469 and 470 are the section header of the side panel
//! the shell draws.

use super::camera_panel::{atof, atol, camera_mode_only, edit_box, in_camera_mode, window_text};
use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::{Command, GlobalTrack};

const ACTIONS: &[Action] = &[
    Action::inline("ctl:455"),
    Action::inline("ctl:456"),
    Action::inline("ctl:457"),
    Action::inline("ctl:458"),
    Action::inline("ctl:459"),
    Action::inline("ctl:460"),
    Action::inline("ctl:461"),
    Action::inline("ctl:462"),
    Action::inline("ctl:463"),
    Action::inline("ctl:464"),
    Action::inline("ctl:465"),
    Action::inline("ctl:466"),
    Action::run("ctl:467", reset, true),
    Action::run("ctl:468", register, true),
    Action::inline("ctl:469"),
    Action::inline("ctl:470"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// One edit of the light, the other five values staying (`CommitEditControl`).
fn edit_light(ctx: &mut Ctx, f: impl FnOnce(&mut [f32; 6])) -> Result<(), String> {
    camera_mode_only(ctx)?;
    let mut l = ctx.editor.doc.pmm.light_state;
    f(&mut l);
    ctx.editor.apply(Command::SetLight {
        color: [l[0], l[1], l[2]],
        direction: [l[3], l[4], l[5]],
    })
}

/// Colour channel `channel` (0 to 2) from slider 455 to 457.
pub fn color_slider(ctx: &mut Ctx, channel: usize, pos: i32) -> Result<(), String> {
    edit_light(ctx, |l| l[channel] = (f64::from(pos) * 0.00390625) as f32)
}

/// Colour channel `channel` from edit 461 to 463: `atol` of the first 7 characters.
pub fn color_edit(ctx: &mut Ctx, channel: usize, text: &str) -> Result<(), String> {
    let v = atol(window_text(text, 8)) as f64 * 0.00390625;
    edit_light(ctx, |l| l[channel] = v as f32)
}

/// Direction axis `axis` (0 to 2) from slider 458 to 460.
pub fn direction_slider(ctx: &mut Ctx, axis: usize, pos: i32) -> Result<(), String> {
    edit_light(ctx, |l| l[3 + axis] = (f64::from(pos) / 100.0) as f32)
}

/// Direction axis `axis` from edit 464 to 466: `atof` of the first 7 characters.
pub fn direction_edit(ctx: &mut Ctx, axis: usize, text: &str) -> Result<(), String> {
    let v = atof(window_text(text, 8));
    edit_light(ctx, |l| l[3 + axis] = v as f32)
}

/// Button 467: the direction (-0.5, -1, 0.5) and every channel 0.602 (`0x3F1A1CAC`).
fn reset(ctx: &mut Ctx) -> Result<(), String> {
    camera_mode_only(ctx)?;
    ctx.editor.apply(Command::SetLight {
        color: [0.602; 3],
        direction: [-0.5, -1.0, 0.5],
    })
}

/// Button 468: clear the marks, register the light key.
fn register(ctx: &mut Ctx) -> Result<(), String> {
    camera_mode_only(ctx)?;
    ctx.editor
        .apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Light]))
}

/// A colour channel as the edit shows it: `%3d` of `value * 256`.
fn color_level(v: f32) -> i32 {
    (f64::from(v) * 256.0) as i32
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if !in_camera_mode(ctx) {
        return;
    }
    let l = ctx.editor.doc.pmm.light_state;
    let playing = ctx.editor.playing();
    ui.add_enabled_ui(!playing, |ui| {
        egui::Grid::new("light-panel").show(ui, |ui| {
            for (c, name) in ["R", "G", "B"].into_iter().enumerate() {
                ui.label(name);
                let mut pos = color_level(l[c]).clamp(0, 255);
                if ui
                    .add(egui::Slider::new(&mut pos, 0..=255).show_value(false))
                    .changed()
                {
                    if let Err(e) = color_slider(ctx, c, pos) {
                        *ctx.status = e;
                    }
                }
                let shown = format!("{:3}", color_level(l[c]));
                if let Some(text) = edit_box(ui, &format!("light-color-{c}"), &shown, 44.0) {
                    if let Err(e) = color_edit(ctx, c, &text) {
                        *ctx.status = e;
                    }
                }
                ui.end_row();
            }
            for (a, name) in ["X", "Y", "Z"].into_iter().enumerate() {
                ui.label(name);
                let mut pos = ((f64::from(l[3 + a]) * 100.0) as i32).clamp(-100, 100);
                if ui
                    .add(egui::Slider::new(&mut pos, -100..=100).show_value(false))
                    .changed()
                {
                    if let Err(e) = direction_slider(ctx, a, pos) {
                        *ctx.status = e;
                    }
                }
                let shown = format!("{:+.1}", l[3 + a]);
                if let Some(text) = edit_box(ui, &format!("light-dir-{a}"), &shown, 44.0) {
                    if let Err(e) = direction_edit(ctx, a, &text) {
                        *ctx.status = e;
                    }
                }
                ui.end_row();
            }
        });
        ui.horizontal(|ui| {
            button(ui, ctx, "ctl:467", "reset");
            button(ui, ctx, "ctl:468", "register");
        });
    });
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
