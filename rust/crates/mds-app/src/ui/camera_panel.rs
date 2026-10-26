//! The `camera-panel` area: the camera panel (perspective 446, view angle 447 and 448, reset
//! 451, register 452) and the readout beside the viewport (reset buttons 537 to 543, edits 544 to
//! 550). `show` also hosts the helpers the light and shadow panels share: the C++ edit box rule
//! and the `atof` / `atol` reads of an edit's text.
//!
//! The readout edits act on the camera in camera mode and on the selected bone in model mode
//! (`CommitEditControlTail`, `src/window/ui_edit_commit.cpp:116`; `BonePosEdit` and `BoneRotEdit`,
//! `src/window/command_frame_register.cpp:281` and `:307`). The collapse and expand buttons 453
//! and 454 are the section header of the side panel the shell draws.
//!
//! The three panels label their controls with the English captions (`label_en`): egui's default
//! fonts have no Japanese glyphs, so `label_ja` would draw as boxes until the shell loads a CJK
//! font.
//!
//! The follow check box 535 (`command_frame_register.cpp:594`) is drawn in both modes.
//!
//! The camera reference check boxes 412 and 531 (`command_frame_edit.cpp:1448`,
//! `command_frame_register.cpp:560`) are two views of one value, `camera_reference_mode`
//! (`Command::SetCameraReference`): checking one sets its mode, which unchecks the other, and
//! unchecking sets 0. Neither handler sets `SceneModified`, so [`Editor::modified`] stays.

use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::{Command, GlobalTrack};
use mds_math::{Mat4, Quat};

const ACTIONS: &[Action] = &[
    Action::run("ctl:446", toggle_perspective, true),
    Action::inline("ctl:447"),
    Action::inline("ctl:448"),
    Action::run("ctl:451", reset, true),
    Action::run("ctl:452", register, true),
    Action::inline("ctl:453"),
    Action::inline("ctl:454"),
    Action::run("ctl:537", reset_x, true),
    Action::run("ctl:538", reset_y, true),
    Action::run("ctl:539", reset_z, true),
    Action::run("ctl:540", reset_rx, true),
    Action::run("ctl:541", reset_ry, true),
    Action::run("ctl:542", reset_rz, true),
    Action::run("ctl:543", reset_distance, true),
    Action::inline("ctl:544"),
    Action::inline("ctl:545"),
    Action::inline("ctl:546"),
    Action::inline("ctl:547"),
    Action::inline("ctl:548"),
    Action::inline("ctl:549"),
    Action::inline("ctl:550"),
    Action::run("ctl:535", toggle_follow, false),
    Action::run("ctl:412", |c| toggle_reference(c, 1), false),
    Action::run("ctl:531", |c| toggle_reference(c, 2), false),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// `kPiLit`, the float pi of the edit handlers.
const PI_LIT: f64 = 3.141592025756836;

/// `3.141592f` (0x40490FD8) of the readout, as a double (`dbl_52B768`).
const PI_READOUT: f64 = f32::from_bits(0x4049_0fd8) as f64;

/// `atof`: the longest numeric prefix of `text`, else 0.
pub(super) fn atof(text: &str) -> f64 {
    let t = text.trim_start();
    let b = t.as_bytes();
    let digits = |mut i: usize| {
        while b.get(i).is_some_and(u8::is_ascii_digit) {
            i += 1;
        }
        i
    };
    let mut end = usize::from(matches!(b.first(), Some(b'+' | b'-')));
    let int_end = digits(end);
    let mut seen = int_end > end;
    end = int_end;
    if b.get(end) == Some(&b'.') {
        let frac_end = digits(end + 1);
        seen |= frac_end > end + 1;
        end = frac_end;
    }
    if !seen {
        return 0.0;
    }
    if matches!(b.get(end), Some(b'e' | b'E')) {
        let sign = usize::from(matches!(b.get(end + 1), Some(b'+' | b'-')));
        let exp_end = digits(end + 1 + sign);
        if exp_end > end + 1 + sign {
            end = exp_end;
        }
    }
    t[..end].parse().unwrap_or(0.0)
}

/// `atol`: the integer prefix of `text`, else 0.
pub(super) fn atol(text: &str) -> i64 {
    let t = text.trim_start();
    let sign = usize::from(matches!(t.as_bytes().first(), Some(b'+' | b'-')));
    let digits = t[sign..].bytes().take_while(u8::is_ascii_digit).count();
    t[..sign + digits].parse().unwrap_or(0)
}

/// What `GetWindowTextA(edit, buf, size)` reads: at most `size - 1` characters.
pub(super) fn window_text(text: &str, size: usize) -> &str {
    match text.char_indices().nth(size - 1) {
        Some((end, _)) => &text[..end],
        None => text,
    }
}

/// An edit box, committed as the C++ edit subclass commits (`EditSubclassProc`,
/// `src/window/ui_edit_commit.cpp:459`): on Enter or when the box loses focus. Shows `shown`
/// until it is edited; returns the text when an edit is committed.
pub(super) fn edit_box(ui: &mut egui::Ui, key: &str, shown: &str, width: f32) -> Option<String> {
    let id = egui::Id::unique(("mds-edit-box", key));
    let mut text = ui
        .data(|d| d.get_temp::<String>(id))
        .unwrap_or_else(|| shown.to_owned());
    let r = ui.add(
        egui::TextEdit::singleline(&mut text)
            .id(id.with("text"))
            .desired_width(width),
    );
    if r.has_focus() {
        ui.data_mut(|d| d.insert_temp(id, text));
        return None;
    }
    ui.data_mut(|d| d.remove::<String>(id));
    (r.lost_focus() && text != shown).then_some(text)
}

/// A push-like check box (`toggle` in the inventory) for the action `id`.
pub(super) fn toggle(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, label: &str, on: bool) {
    let b = egui::Button::new(label).selected(on);
    if ui.add_enabled(ctx.enabled(id), b).clicked() {
        ctx.run(id);
    }
}

pub(super) fn in_camera_mode(ctx: &Ctx) -> bool {
    ctx.editor.doc.pmm.settings.options[0] != 0
}

/// The camera, light and shadow panels exist in camera mode only (`PostModelReload2`,
/// `src/window/ui_model_reload.cpp:212`).
pub(super) fn camera_mode_only(ctx: &Ctx) -> Result<(), String> {
    match in_camera_mode(ctx) {
        true => Ok(()),
        false => Err("camera mode only".into()),
    }
}

fn camera(ctx: &Ctx) -> mds_doc::CameraControls {
    ctx.editor.doc.camera_controls()
}

fn edit_camera(ctx: &mut Ctx, f: impl FnOnce(&mut mds_doc::CameraControls)) -> Result<(), String> {
    ctx.editor.edit_camera_controls(f)
}

/// Whether the camera follows a model (`CameraParentModel() >= 0`).
fn parented(ctx: &Ctx) -> bool {
    ctx.editor.doc.pmm.appearance.camera_parent_model >= 0
}

/// Check box 446 (`src/window/command_frame_edit.cpp:1627`).
fn toggle_perspective(ctx: &mut Ctx) -> Result<(), String> {
    camera_mode_only(ctx)?;
    edit_camera(ctx, |c| c.orthographic = !c.orthographic)
}

/// Check box 535: camera and lighting tracking, as menu 247 flips it. The C++ sets no
/// `SceneModified` for either. Playback does not grey it (`StartPlayback` greys 536 and on).
fn toggle_follow(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.pmm.appearance.follow_camera == 0;
    ctx.editor.apply(Command::SetFollowCamera(on))
}

/// Check box 412 (`mode` 1, the model) or 531 (`mode` 2, the selected bone): checking sets the
/// mode and unchecks the other box, unchecking the box that is checked sets 0. The C++ sets the
/// mode in either edit mode and moves the view only in model mode (the document does the same).
fn toggle_reference(ctx: &mut Ctx, mode: u8) -> Result<(), String> {
    let now = ctx.editor.doc.pmm.timeline.camera_reference_mode;
    ctx.editor
        .apply(Command::SetCameraReference(if now == mode {
            0
        } else {
            mode
        }))
}

/// The view angle, from slider 447 (`src/window/ui_hscroll.cpp:232`) or edit 448 (`atol`,
/// `ui_edit_commit.cpp:324`).
pub fn set_fov(ctx: &mut Ctx, degrees: i64) -> Result<(), String> {
    camera_mode_only(ctx)?;
    edit_camera(ctx, |c| c.fov_deg = degrees as f32)
}

pub fn commit_fov(ctx: &mut Ctx, text: &str) -> Result<(), String> {
    set_fov(ctx, atol(window_text(text, 8)))
}

/// Button 451 (`src/window/command_panel_toggles.cpp:331`).
fn reset(ctx: &mut Ctx) -> Result<(), String> {
    camera_mode_only(ctx)?;
    let free = !parented(ctx);
    edit_camera(ctx, |c| {
        c.target = [0.0, if free { 10.0 } else { 0.0 }, 0.0];
        c.rotation = [0.0; 3];
        c.distance = if free { -45.0 } else { 0.0 };
    })
}

/// Button 452 (`command_panel_toggles.cpp:391`): clear the marks, register the camera key.
fn register(ctx: &mut Ctx) -> Result<(), String> {
    camera_mode_only(ctx)?;
    ctx.editor
        .apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]))
}

/// Edit `field` of the readout (0..=2 position, 3..=5 rotation in degrees, 6 distance) set to
/// `value` as the C++ stores it: camera mode edits the camera (`CommitEditControlTail`), model
/// mode the selected bone. The distance edit has no effect in model mode (`:561`).
pub fn set_readout(ctx: &mut Ctx, field: usize, value: f64) -> Result<(), String> {
    if !in_camera_mode(ctx) {
        return match field {
            0..=5 => ctx.editor.apply(Command::BoneReadoutEdit {
                axis: field as u8,
                value,
            }),
            _ => Ok(()),
        };
    }
    let flip = parented(ctx);
    edit_camera(ctx, |c| match field {
        0 | 1 => c.target[field] = value as f32,
        2 => c.target[2] = if flip { -value } else { value } as f32,
        3 => c.rotation[0] = (-value * PI_LIT / 180.0) as f32,
        4 | 5 => c.rotation[field - 3] = (value * PI_LIT / 180.0) as f32,
        _ => c.distance = (-value) as f32,
    })
}

pub fn commit_readout(ctx: &mut Ctx, field: usize, text: &str) -> Result<(), String> {
    set_readout(ctx, field, atof(window_text(text, 100)))
}

/// Buttons 537 to 542: one position or rotation axis back to 0. Camera mode zeroes the camera
/// value (`BonePosEdit`, `BoneRotEdit`); model mode the selected bone's axis.
fn reset_axis(ctx: &mut Ctx, field: usize) -> Result<(), String> {
    if !in_camera_mode(ctx) {
        return set_readout(ctx, field, 0.0);
    }
    edit_camera(ctx, |c| match field {
        0..=2 => c.target[field] = 0.0,
        _ => c.rotation[field - 3] = 0.0,
    })
}

macro_rules! resets {
    ($($name:ident = $field:literal),*) => {
        $(fn $name(ctx: &mut Ctx) -> Result<(), String> {
            reset_axis(ctx, $field)
        })*
    };
}
resets!(
    reset_x = 0,
    reset_y = 1,
    reset_z = 2,
    reset_rx = 3,
    reset_ry = 4,
    reset_rz = 5
);

/// Button 543 (`command_frame_register.cpp:677`): the camera distance to 0, in camera mode.
fn reset_distance(ctx: &mut Ctx) -> Result<(), String> {
    if !in_camera_mode(ctx) {
        return Ok(());
    }
    edit_camera(ctx, |c| c.distance = 0.0)
}

/// The text of readout edit `field` (`PostViewRefresh`, `src/window/ui_view_refresh.cpp:128`).
pub fn readout_text(ctx: &Ctx, field: usize) -> String {
    let doc = &ctx.editor.doc;
    if in_camera_mode(ctx) {
        let (c, pi) = (camera(ctx), PI_READOUT);
        let degrees = |r: f32| f64::from(r) / pi * 180.0;
        let zero = |v: f64| if v.abs() < f64::from(1e-7f32) { 0.0 } else { v };
        return match field {
            0 | 1 => format!("{:.2}", c.target[field]),
            2 => format!(
                "{:.2}",
                if parented(ctx) {
                    -c.target[2]
                } else {
                    c.target[2]
                }
            ),
            3 => format!("{:.1}", zero(-degrees(c.rotation[0]))),
            4 | 5 => format!("{:.1}", degrees(c.rotation[field - 3])),
            _ if parented(ctx) => "0.00".into(),
            _ => format!("{:.2}", zero(-f64::from(c.distance))),
        };
    }
    match (doc.selected_bone_readout(), field) {
        (Some((_, translation)), 0..=2) => format!("{:.2}", translation[field]),
        (Some((rotation, _)), 3..=5) => format!("{:.1}", euler_degrees(rotation)[field - 3]),
        _ => "-----".into(),
    }
}

/// The degrees `(x, y, z)` that `PostViewRefresh` derives from a bone's rotation quaternion
/// (`ui_view_refresh.cpp:200` to `:260`).
fn euler_degrees(q: [f32; 4]) -> [f32; 3] {
    let m = Mat4::rotation_quaternion(Quat(q)).0;
    let d = f64::from;
    let pi = PI_READOUT;
    let mut rz = d(m[1]).atan2(d(m[5])) as f32;
    let mut rx = (-d(m[9])).asin() as f32;
    let mut ry = d(m[8]).atan2(d(m[10])) as f32;
    if d(d(rx).cos() as f32).abs() < d(1e-6f32) {
        rz = (d(rz) + if m[1] > 0.0 { pi } else { -pi }) as f32;
        ry = (d(ry) + if m[8] > 0.0 { pi } else { -pi }) as f32;
    }
    for a in [&mut rx, &mut ry, &mut rz] {
        if d(*a).abs() < d(1e-6f32) {
            *a = 0.0;
        }
    }
    let snap = |v: f32| if d(v).abs() < d(1e-7f32) { 0.0 } else { v };
    [
        snap((d(rx) / pi * 180.0) as f32),
        snap((-d(ry) / pi * 180.0) as f32),
        snap((180.0 * (-d(rz) / pi)) as f32),
    ]
}

/// A text edit of the readout that commits through `commit`.
fn readout_edit(ui: &mut egui::Ui, ctx: &mut Ctx, field: usize) {
    let shown = readout_text(ctx, field);
    if let Some(text) = edit_box(ui, &format!("readout-{field}"), &shown, 56.0) {
        if let Err(e) = commit_readout(ctx, field, &text) {
            *ctx.status = e;
        }
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let playing = ctx.editor.playing();
    let follow = ctx.editor.doc.pmm.appearance.follow_camera != 0;
    toggle(ui, ctx, "ctl:535", "track", follow);
    let reference = ctx.editor.doc.pmm.timeline.camera_reference_mode;
    ui.horizontal(|ui| {
        toggle(ui, ctx, "ctl:412", "ref model", reference == 1);
        toggle(ui, ctx, "ctl:531", "ref bone", reference == 2);
    });
    if in_camera_mode(ctx) {
        let on = ctx.editor.doc.pmm.camera_perspective != 0;
        ui.horizontal(|ui| {
            toggle(ui, ctx, "ctl:446", "perspect", on);
            button(ui, ctx, "ctl:451", "reset");
            button(ui, ctx, "ctl:452", "register");
        });
        let fov = ctx.editor.doc.pmm.settings.camera_fov;
        ui.add_enabled_ui(!playing, |ui| {
            ui.horizontal(|ui| {
                let mut pos = (fov as i64).clamp(1, 125) as i32;
                if ui
                    .add(egui::Slider::new(&mut pos, 1..=125).show_value(false))
                    .changed()
                {
                    if let Err(e) = set_fov(ctx, pos.into()) {
                        *ctx.status = e;
                    }
                }
                if let Some(text) = edit_box(ui, "fov", &format!("{:3}", fov as i32), 36.0) {
                    if let Err(e) = commit_fov(ctx, &text) {
                        *ctx.status = e;
                    }
                }
            });
        });
        ui.separator();
    }
    let camera = in_camera_mode(ctx);
    ui.add_enabled_ui(!playing, |ui| {
        egui::Grid::new("camera-readout").show(ui, |ui| {
            for (axis, name) in ["X", "Y", "Z"].into_iter().enumerate() {
                button(ui, ctx, &format!("ctl:{}", 537 + axis), name);
                readout_edit(ui, ctx, axis);
                button(ui, ctx, &format!("ctl:{}", 540 + axis), name);
                readout_edit(ui, ctx, 3 + axis);
                ui.end_row();
            }
            if camera {
                button(ui, ctx, "ctl:543", "dist");
                readout_edit(ui, ctx, 6);
                ui.end_row();
            }
        });
    });
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
