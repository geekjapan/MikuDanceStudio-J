//! The `dialog` area: the 24 `dlg:*` rows of the UI inventory, each an egui window over the
//! central panel (`res/templates/dialog/dialogs.rc`, the procs in `src/window/`).
//!
//! # Contract
//!
//! [`open`] stores the dialog name (`"IDD_FRAME_SHIFT"`) in egui's temp memory under
//! `egui::Id::unique("mds.dialog")`, which is what the deprecated `Id::new("mds.dialog")` hashes
//! to as well. [`show`] draws the open dialog and closes it on OK, Cancel, Esc or the window's
//! close button. Each implemented `dlg:*` action opens its dialog; the menus of other areas that
//! open one call [`open`] or run the action. Enter is OK in the modal dialogs, as the
//! `DEFPUSHBUTTON` is.
//!
//! The edit boxes keep the text the user typed, and OK reads them the way the dialog procs do:
//! `GetWindowTextA` into a 20 byte buffer and `atol` / `atof` ([`field_int`], [`field_float`]).
//! Window `show` and the test seams ([`set_field`], [`submit`]) edit the same form.
//!
//! # Rows
//!
//! Open now: 16 of the 24 rows. Ground shadow color (menu 248) is drawn by the View menu
//! (`view.rs`, which owns that window's state), so its action runs `menu:248`.
//!
//! Missing, for lack of a [`mds_doc::Command`] or a way to build one (the report of the slice
//! names each): `IDD_FRAME_SCALE`, `IDD_ACCESSORY_ORDER`, `IDD_MODEL_DRAW_ORDER`,
//! `IDD_MODEL_CALCULATE_ORDER`, `IDD_OUTSIDE_PARENT`, `IDD_ENGLISH_NAMES`, `IDD_TOON_TEXTURE`,
//! `IDD_PHYSICS_MODEL`.
//!
//! # Where this differs from the C++
//!
//! * The numeric input dialogs (`IDD_BONE_NUMERIC_INPUT`, `IDD_CAMERA_NUMERIC_INPUT`) do what
//!   they were meant to. The C++ procs write the typed values to a scratch array that the menu 300
//!   code never reads back (it writes its own locals), takes the reciprocal of the roll
//!   (`kD2 / (kD3 * t5)`), and reads `m[1][3]` of a 4x4 matrix for the bone's Y angle. Here OK
//!   applies the position and the rotation in degrees, with the signs of the readout edits 544 to
//!   550 (`CommitEditControlTail`), as one command (one undo entry).
//! * The AVI dialog has no codec combo, settings button or 3D Vision check boxes (806, 807): the
//!   operator's decisions of 2026-10-25 are a built-in uncompressed AVI writer or a PNG sequence,
//!   and 3D Vision is dropped. OK stores an [`AviSettings`] for the recorder ([`take_avi_request`])
//!   and rejects a frame rate of 0 or less, which the C++ does not check.
//! * A command that fails keeps its dialog open with the error on the status line (the C++ closes
//!   it and the handler returns with nothing changed).
//! * The window is not modal. Playback still greys out the actions that edit the document.
//!
//! `MDS_APP_DIALOG=<name>` opens a dialog when the window starts, for screenshots.

use super::camera_panel::{atof, atol, in_camera_mode, window_text};
use super::{help, Ctx};
use crate::actions::{self, Action};
use egui::{Align2, Context, Id, Key};
use mds_doc::{Command, GlobalTrack};
use mds_math::{Mat4, Quat};

/// How a dialog's action may be opened.
#[derive(Clone, Copy)]
enum Gate {
    Any,
    /// The C++ handler returns in camera mode (`app->CameraMode() != 0`).
    Model,
    /// The handler returns in model mode (menu 242 and the camera numeric input).
    Camera,
}

fn start(ctx: &mut Ctx, name: &'static str, gate: Gate) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or("no window")?;
    let refused = match gate {
        Gate::Any => false,
        Gate::Model => in_camera_mode(ctx),
        Gate::Camera => !in_camera_mode(ctx),
    };
    if refused {
        return Err(format!("{name}: not in this mode"));
    }
    open_in(&egui, name);
    Ok(())
}

macro_rules! opens {
    ($id:literal, $name:literal, $gate:expr, $doc:literal) => {
        Action::run($id, |c| start(c, $name, $gate), $doc)
    };
}

const ACTIONS: &[Action] = &[
    opens!(
        "dlg:IDD_CENTER_POSITION_BIAS",
        "IDD_CENTER_POSITION_BIAS",
        Gate::Model,
        true
    ),
    opens!("dlg:IDD_SCREEN_SIZE", "IDD_SCREEN_SIZE", Gate::Any, true),
    opens!("dlg:IDD_AVI_OUTPUT", "IDD_AVI_OUTPUT", Gate::Any, false),
    opens!("dlg:IDD_FRAME_SHIFT", "IDD_FRAME_SHIFT", Gate::Model, true),
    opens!(
        "dlg:IDD_REGISTER_BLINKING",
        "IDD_REGISTER_BLINKING",
        Gate::Model,
        true
    ),
    opens!(
        "dlg:IDD_CAMERA_FRAME_MULTIPLY",
        "IDD_CAMERA_FRAME_MULTIPLY",
        Gate::Camera,
        true
    ),
    Action::run("dlg:IDD_GROUND_SHADOW_COLOR", shadow_color, false),
    opens!(
        "dlg:IDD_BONE_FRAME_MULTIPLY",
        "IDD_BONE_FRAME_MULTIPLY",
        Gate::Model,
        true
    ),
    opens!(
        "dlg:IDD_MORPH_MULTIPLY",
        "IDD_MORPH_MULTIPLY",
        Gate::Model,
        true
    ),
    opens!(
        "dlg:IDD_EDGE_THICKNESS",
        "IDD_EDGE_THICKNESS",
        Gate::Model,
        true
    ),
    Action::run("dlg:IDD_BONE_NUMERIC_INPUT", open_bone_numeric, true),
    opens!(
        "dlg:IDD_CAMERA_NUMERIC_INPUT",
        "IDD_CAMERA_NUMERIC_INPUT",
        Gate::Camera,
        true
    ),
    opens!("dlg:IDD_GRAVITY", "IDD_GRAVITY", Gate::Any, true),
    opens!(
        "dlg:IDD_PHYSICS_FRAME_CONVERSION",
        "IDD_PHYSICS_FRAME_CONVERSION",
        Gate::Any,
        true
    ),
    opens!(
        "dlg:IDD_PMM_MISSING_MODEL",
        "IDD_PMM_MISSING_MODEL",
        Gate::Any,
        false
    ),
    opens!(
        "dlg:IDD_PMM_MODEL_MISMATCH",
        "IDD_PMM_MODEL_MISMATCH",
        Gate::Any,
        false
    ),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

// ---- the open dialog ------------------------------------------------------------------------

fn slot() -> Id {
    Id::unique("mds.dialog")
}

fn form_id(name: &str) -> Id {
    Id::unique(("mds.dialog.form", name))
}

/// Opens the dialog `name` (`"IDD_FRAME_SHIFT"`); a second call for the dialog already open
/// keeps what was typed.
pub fn open(ui: &egui::Ui, name: &'static str) {
    open_in(ui.ctx(), name);
}

fn open_in(egui: &Context, name: &'static str) {
    if current(egui) == Some(name) {
        return;
    }
    egui.data_mut(|d| {
        d.insert_temp(slot(), name);
        d.remove::<Form>(form_id(name));
    });
}

/// The name of the open dialog.
pub fn current(egui: &Context) -> Option<&'static str> {
    egui.data(|d| d.get_temp::<&'static str>(slot()))
}

fn close(egui: &Context, name: &str) {
    egui.data_mut(|d| {
        d.remove::<&'static str>(slot());
        d.remove::<Form>(form_id(name));
    });
}

/// What the controls of a dialog hold. Each dialog uses the fields it needs.
#[derive(Clone, Debug, Default)]
struct Form {
    /// The edit boxes, in the order the dialog's `ok` reads them.
    t: Vec<String>,
    /// The check boxes.
    c: Vec<bool>,
    /// The combo selection.
    pick: usize,
    /// The numbers a dialog opened with, which a box left alone keeps exactly.
    f: Vec<f32>,
    /// The text of the edit boxes last applied (the live dialogs apply on `EN_UPDATE`).
    applied: Vec<String>,
    /// Drawn for the first time: the first edit takes the focus.
    fresh: bool,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Done {
    Open,
    Ok,
    Cancel,
}

struct Spec {
    name: &'static str,
    ja: &'static str,
    en: &'static str,
    /// Enter is OK. The live dialogs (edge thickness, gravity) apply as they go.
    modal: bool,
    init: fn(&Ctx) -> Form,
    body: fn(&mut egui::Ui, &mut Ctx, &mut Form, bool) -> Done,
    ok: fn(&mut Ctx, &Form) -> Result<(), String>,
    cancel: fn(&mut Ctx),
    /// Runs after every edit of a box (`EN_UPDATE`) for the dialogs that apply as they go.
    live: fn(&mut Ctx, &mut Form),
}

fn accept(_: &mut Ctx, _: &Form) -> Result<(), String> {
    Ok(())
}

fn nothing(_: &mut Ctx) {}

const MODAL: Spec = Spec {
    name: "",
    ja: "",
    en: "",
    modal: true,
    init: |_| Form::default(),
    body: |_, _, _, _| Done::Cancel,
    ok: accept,
    cancel: nothing,
    live: |_, _| {},
};

const SPECS: &[Spec] = &[
    Spec {
        name: "IDD_CENTER_POSITION_BIAS",
        ja: "バイアス付加",
        en: "apply center position bias",
        init: |_| texts(&["0.0"; 3]),
        body: bias_body,
        ok: ok_bias,
        ..MODAL
    },
    Spec {
        name: "IDD_SCREEN_SIZE",
        ja: "出力画面サイズ変更",
        en: "screen size",
        init: screen_init,
        body: screen_body,
        ok: ok_screen,
        ..MODAL
    },
    Spec {
        name: "IDD_AVI_OUTPUT",
        ja: "AVI出力設定",
        en: "AVI-out",
        init: avi_init,
        body: avi_body,
        ok: ok_avi,
        ..MODAL
    },
    Spec {
        name: "IDD_FRAME_SHIFT",
        ja: "シフトするﾌﾚｰﾑ数",
        en: "frame number to shift",
        init: |_| texts(&["0"]),
        body: shift_body,
        ok: ok_shift,
        ..MODAL
    },
    Spec {
        name: "IDD_REGISTER_BLINKING",
        ja: "まばたき登録",
        en: "register blinking",
        init: |_| texts(&["", ""]),
        body: blink_body,
        ok: ok_blink,
        ..MODAL
    },
    Spec {
        name: "IDD_CAMERA_FRAME_MULTIPLY",
        ja: "ｶﾒﾗﾌﾚｰﾑ位置角度補正",
        en: "multiply of camera frame position-angle",
        init: |_| scale_add(8),
        body: camera_multiply_body,
        ok: ok_camera_multiply,
        ..MODAL
    },
    Spec {
        name: "IDD_BONE_FRAME_MULTIPLY",
        ja: "ﾎﾞｰﾝﾌﾚｰﾑ位置角度補正",
        en: "multiply of bone position-angle",
        init: |_| scale_add(6),
        body: bone_multiply_body,
        ok: ok_bone_multiply,
        ..MODAL
    },
    Spec {
        name: "IDD_MORPH_MULTIPLY",
        ja: "表情大きさ補正",
        en: "multiply of facial expression ",
        init: |_| scale_add(1),
        body: morph_multiply_body,
        ok: ok_morph_multiply,
        ..MODAL
    },
    Spec {
        name: "IDD_EDGE_THICKNESS",
        ja: "エッジ太さ設定",
        en: "thickness of edge line",
        modal: false,
        init: edge_init,
        body: edge_body,
        ok: ok_edge,
        ..MODAL
    },
    Spec {
        name: "IDD_BONE_NUMERIC_INPUT",
        ja: "数値入力(ボーン)",
        en: "numeric input(bone)",
        init: bone_numeric_init,
        body: bone_numeric_body,
        ok: ok_bone_numeric,
        ..MODAL
    },
    Spec {
        name: "IDD_CAMERA_NUMERIC_INPUT",
        ja: "数値入力(カメラ)",
        en: "numeric input(camera)",
        init: camera_numeric_init,
        body: camera_numeric_body,
        ok: ok_camera_numeric,
        ..MODAL
    },
    Spec {
        name: "IDD_GRAVITY",
        ja: "重力設定",
        en: "gravity setting",
        modal: false,
        init: gravity_init,
        body: gravity_body,
        live: gravity_sync,
        cancel: |c| {
            if let Err(e) = c.editor.apply(Command::CloseGravityDialog) {
                *c.status = e;
            }
        },
        ..MODAL
    },
    Spec {
        name: "IDD_PHYSICS_FRAME_CONVERSION",
        ja: "物理ON/OFFフレーム変換",
        en: "change physics ON/OFF frame",
        init: |_| Form::default(),
        body: physics_body,
        ok: ok_physics,
        ..MODAL
    },
    Spec {
        name: "IDD_PMM_MISSING_MODEL",
        ja: "pmm ver.2.0 ロード",
        en: "pmm ver.2.0 load",
        modal: false,
        body: missing_body,
        cancel: abort_unless_chosen,
        ..MODAL
    },
    Spec {
        name: "IDD_PMM_MODEL_MISMATCH",
        ja: "pmm ver.2.0 ロード",
        en: "pmm ver.2.0 load",
        modal: false,
        body: mismatch_body,
        cancel: abort_unless_chosen,
        ..MODAL
    },
];

fn texts(t: &[&str]) -> Form {
    Form {
        t: t.iter().map(|s| s.to_string()).collect(),
        ..Form::default()
    }
}

/// The (scale, add) edit pairs of the multiply dialogs: "1.0" and "0.0" (`PrefillEdit`).
fn scale_add(pairs: usize) -> Form {
    Form {
        t: (0..pairs)
            .flat_map(|_| ["1.0", "0.0"])
            .map(String::from)
            .collect(),
        ..Form::default()
    }
}

fn form_of(ctx: &Ctx, egui: &Context, spec: &Spec) -> Form {
    egui.data(|d| d.get_temp::<Form>(form_id(spec.name)))
        .unwrap_or_else(|| Form {
            fresh: true,
            ..(spec.init)(ctx)
        })
}

fn store(egui: &Context, name: &str, form: Form) {
    egui.data_mut(|d| d.insert_temp(form_id(name), form));
}

fn spec_of(egui: &Context) -> Option<&'static Spec> {
    let name = current(egui)?;
    SPECS.iter().find(|s| s.name == name)
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let egui = ui.ctx().clone();
    let Some(name) = current(&egui) else {
        return;
    };
    let Some(spec) = SPECS.iter().find(|s| s.name == name) else {
        // A row without a dialog (see the file doc) has nothing to draw.
        close(&egui, name);
        return;
    };
    let en = help::english(&egui);
    let mut form = form_of(ctx, &egui, spec);
    let (mut open, mut done) = (true, Done::Open);
    egui::Window::new(help::pick(&egui, spec.ja, spec.en))
        .id(Id::unique(("mds.dialog.window", name)))
        .collapsible(false)
        .resizable(false)
        .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
        .open(&mut open)
        .show(&egui, |ui| done = (spec.body)(ui, ctx, &mut form, en));
    form.fresh = false;
    let (enter, esc) = egui.input(|i| (i.key_pressed(Key::Enter), i.key_pressed(Key::Escape)));
    if !open || esc {
        done = Done::Cancel;
    } else if enter && spec.modal && done == Done::Open {
        done = Done::Ok;
    }
    settle(ctx, &egui, spec, form, done);
}

/// What the dialog does with `done`; a failing OK keeps it open.
fn settle(ctx: &mut Ctx, egui: &Context, spec: &Spec, form: Form, done: Done) {
    match done {
        Done::Open => store(egui, spec.name, form),
        Done::Cancel => {
            (spec.cancel)(ctx);
            close(egui, spec.name);
        }
        Done::Ok => match (spec.ok)(ctx, &form) {
            Ok(()) => close(egui, spec.name),
            Err(e) => {
                *ctx.status = e;
                store(egui, spec.name, form);
            }
        },
    }
}

pub fn pass(ui: &mut egui::Ui, _ctx: &mut Ctx) {
    static START: std::sync::Once = std::sync::Once::new();
    START.call_once(|| {
        let Ok(want) = std::env::var("MDS_APP_DIALOG") else {
            return;
        };
        if let Some(spec) = SPECS.iter().find(|s| s.name == want) {
            open_in(ui.ctx(), spec.name);
        }
    });
}

// ---- the test seams: the same form the window edits -----------------------------------------

fn open_form(ctx: &Ctx) -> Result<(Context, &'static Spec, Form), String> {
    let egui = ctx.egui.clone().ok_or("no window")?;
    let spec = spec_of(&egui).ok_or("no dialog is open")?;
    let form = form_of(ctx, &egui, spec);
    Ok((egui, spec, form))
}

/// The text of edit box `i` of the open dialog.
pub fn field(ctx: &Ctx, i: usize) -> Option<String> {
    open_form(ctx).ok()?.2.t.get(i).cloned()
}

/// Types `text` into edit box `i` of the open dialog.
pub fn set_field(ctx: &mut Ctx, i: usize, text: &str) {
    if let Ok((egui, spec, mut form)) = open_form(ctx) {
        form.t[i] = text.to_string();
        (spec.live)(ctx, &mut form);
        store(&egui, spec.name, form);
    }
}

pub fn set_check(ctx: &mut Ctx, i: usize, on: bool) {
    if let Ok((egui, spec, mut form)) = open_form(ctx) {
        form.c[i] = on;
        (spec.live)(ctx, &mut form);
        store(&egui, spec.name, form);
    }
}

pub fn set_pick(ctx: &Ctx, pick: usize) {
    if let Ok((egui, spec, mut form)) = open_form(ctx) {
        form.pick = pick;
        store(&egui, spec.name, form);
    }
}

/// Presses Cancel (or Esc, or the close button) of the open dialog.
pub fn cancel(ctx: &mut Ctx) {
    if let Ok((egui, spec, _)) = open_form(ctx) {
        (spec.cancel)(ctx);
        close(&egui, spec.name);
    }
}

/// Presses OK of the open dialog.
pub fn submit(ctx: &mut Ctx) -> Result<(), String> {
    let (egui, spec, form) = open_form(ctx)?;
    (spec.ok)(ctx, &form)?;
    close(&egui, spec.name);
    Ok(())
}

// ---- reading the edit boxes -----------------------------------------------------------------

/// `ReadFloatFromEdit`: `atof` of at most 19 characters, as a float.
fn field_float(f: &Form, i: usize) -> f32 {
    atof(window_text(&f.t[i], 20)) as f32
}

/// `ReadIntFromEdit`: `atol` of at most 19 characters, saturating as the CRT does.
fn field_int(f: &Form, i: usize) -> i32 {
    atol(window_text(&f.t[i], 20)).clamp(i32::MIN.into(), i32::MAX.into()) as i32
}

// ---- drawing --------------------------------------------------------------------------------

/// `ja` or `en` by the interface language.
fn tr(en: bool, ja: &'static str, e: &'static str) -> &'static str {
    if en {
        e
    } else {
        ja
    }
}

fn edit(ui: &mut egui::Ui, text: &mut String, width: f32, focus: bool) {
    let r = ui.add(egui::TextEdit::singleline(text).desired_width(width));
    if focus {
        r.request_focus();
    }
}

fn ok_cancel(ui: &mut egui::Ui, en: bool) -> Done {
    ui.horizontal(|ui| {
        let ok = ui.button("OK").clicked();
        let cancel = ui.button(tr(en, "ｷｬﾝｾﾙ", "cancel")).clicked();
        match (ok, cancel) {
            (true, _) => Done::Ok,
            (_, true) => Done::Cancel,
            _ => Done::Open,
        }
    })
    .inner
}

/// A column of `label: edit` rows over the texts from `first`.
fn rows(ui: &mut egui::Ui, f: &mut Form, first: usize, labels: &[&str], fresh_first: bool) {
    egui::Grid::new(("mds.dialog.rows", first)).show(ui, |ui| {
        for (i, label) in labels.iter().enumerate() {
            ui.label(*label);
            edit(ui, &mut f.t[first + i], 70.0, fresh_first && i == 0);
            ui.end_row();
        }
    });
}

/// Rows of `label * [scale] + [add]` over the pairs from text `first`.
fn pair_rows(ui: &mut egui::Ui, f: &mut Form, first: usize, labels: &[&str], focus: bool) {
    egui::Grid::new(("mds.dialog.pairs", first)).show(ui, |ui| {
        for (i, label) in labels.iter().enumerate() {
            ui.label(*label);
            edit(ui, &mut f.t[first + 2 * i], 50.0, focus && i == 0);
            ui.label("+");
            edit(ui, &mut f.t[first + 2 * i + 1], 50.0, false);
            ui.end_row();
        }
    });
}

const XYZ: [&str; 3] = ["X *", "Y *", "Z *"];

// ---- 219: center position bias --------------------------------------------------------------

fn bias_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    rows(ui, f, 0, &["X:", "Y:", "Z:"], fresh);
    ok_cancel(ui, en)
}

/// `ModelOffsetDlgProc` (`src/window/command_file_menu.cpp:474`): three `atof`, then the offset
/// of `CmdFileMenu` case 219.
fn ok_bias(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    ctx.editor.apply(Command::CenterPositionBias([
        field_float(f, 0),
        field_float(f, 1),
        field_float(f, 2),
    ]))
}

// ---- 212: screen size -----------------------------------------------------------------------

fn screen_init(ctx: &Ctx) -> Form {
    let s = &ctx.editor.doc.pmm.settings;
    texts(&[
        &format!("{:3}", s.render_width),
        &format!("{:3}", s.render_height),
    ])
}

fn screen_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    rows(
        ui,
        f,
        0,
        &[tr(en, "幅", "width"), tr(en, "高さ", "height")],
        fresh,
    );
    ok_cancel(ui, en)
}

/// `ScreenSizeDlgProc` (`command_file_menu.cpp:436`): both sizes must fit the device's largest
/// texture, else a message box and the dialog stays.
fn ok_screen(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let (width, height) = (field_int(f, 0), field_int(f, 1));
    if let Some([w, h]) = ctx.editor.doc.edit.max_texture_size {
        if width > w || height > h {
            let en = ctx.egui.as_ref().is_some_and(help::english);
            return Err(tr(
                en,
                "このPCで処理できる大きさを超えています",
                "too big for your PC!",
            )
            .into());
        }
    }
    ctx.editor.apply(Command::SetRenderSize { width, height })
}

// ---- 223: AVI output ------------------------------------------------------------------------

/// What the recorder needs to start a recording: the settings of `AviOutDlgProc`
/// (`command_file_menu.cpp:556`) without the codec choice.
#[derive(Clone, Debug, PartialEq)]
pub struct AviSettings {
    /// `AviRecordStartFrame()` and `AviRecordEndFrame()`.
    pub start_frame: i32,
    pub end_frame: i32,
    /// `AviRecordFps()`.
    pub fps: f32,
    /// The render size at OK; the C++ shows it greyed out.
    pub width: i32,
    pub height: i32,
    /// `AviIncludeWave()`: offered only when a WAVE is loaded.
    pub include_wave: bool,
    pub format: AviFormat,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AviFormat {
    /// The built-in uncompressed AVI writer.
    UncompressedAvi,
    PngSequence,
}

fn take<T: Clone + Send + Sync + 'static>(egui: &Context, id: Id) -> Option<T> {
    egui.data_mut(|d| {
        let value = d.get_temp::<T>(id);
        d.remove::<T>(id);
        value
    })
}

fn avi_key() -> Id {
    Id::unique("mds.dialog.avi")
}

/// The settings of the last OK of the AVI dialog, once: the recorder polls this each pass.
pub fn take_avi_request(egui: &Context) -> Option<AviSettings> {
    take(egui, avi_key())
}

fn avi_init(ctx: &Ctx) -> Form {
    let o = &ctx.editor.options;
    Form {
        t: vec![
            o.start_frame.to_string(),
            o.stop_frame.to_string(),
            "30".into(),
        ],
        c: vec![ctx.editor.doc.pmm.wave.enabled != 0],
        ..Form::default()
    }
}

fn avi_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let s = &ctx.editor.doc.pmm.settings;
    ui.label(format!(
        "{} {} x {} Pixel",
        tr(en, "録画サイズ", "AVI size"),
        s.render_width,
        s.render_height
    ));
    let fresh = f.fresh;
    rows(
        ui,
        f,
        0,
        &[
            tr(en, "録画ﾌﾚｰﾑ 開始", "recording frame from"),
            tr(en, "録画ﾌﾚｰﾑ 終了", "recording frame to"),
            tr(en, "フレームレート fps", "frame rate fps"),
        ],
        fresh,
    );
    let wave = ctx.editor.doc.pmm.wave.enabled != 0;
    ui.add_enabled(
        wave,
        egui::Checkbox::new(&mut f.c[0], tr(en, "WAVEも出力する", "output WAVE")),
    );
    ui.horizontal(|ui| {
        ui.radio_value(&mut f.pick, 0, tr(en, "無圧縮AVI", "uncompressed AVI"));
        ui.radio_value(&mut f.pick, 1, tr(en, "連番PNG", "PNG sequence"));
    });
    ok_cancel(ui, en)
}

/// OK of `AviOutDlgProc`: the end frame may not be below the start frame (a "WARNING" box).
fn ok_avi(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let en = ctx.egui.as_ref().is_some_and(help::english);
    let (start, end, fps) = (field_int(f, 0), field_int(f, 1), field_float(f, 2));
    if end < start {
        return Err(tr(
            en,
            "終了フレームが開始フレームより小さいです",
            "End frame is less than start frame!",
        )
        .into());
    }
    if fps <= 0.0 || fps.is_nan() {
        return Err(tr(
            en,
            "フレームレートは0より大きくしてください",
            "The frame rate must be above 0",
        )
        .into());
    }
    let s = &ctx.editor.doc.pmm.settings;
    let request = AviSettings {
        start_frame: start,
        end_frame: end,
        fps,
        width: s.render_width,
        height: s.render_height,
        include_wave: f.c[0] && ctx.editor.doc.pmm.wave.enabled != 0,
        format: if f.pick == 0 {
            AviFormat::UncompressedAvi
        } else {
            AviFormat::PngSequence
        },
    };
    let egui = ctx.egui.as_ref().ok_or("no window")?;
    egui.data_mut(|d| d.insert_temp(avi_key(), request));
    Ok(())
}

// ---- 225: frame shift, 227: blinking --------------------------------------------------------

fn shift_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    rows(ui, f, 0, &[""], fresh);
    ok_cancel(ui, en)
}

fn ok_shift(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    ctx.editor.apply(Command::ShiftLipFrames(field_int(f, 0)))
}

fn blink_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    rows(
        ui,
        f,
        0,
        &[
            tr(en, "開始ﾌﾚｰﾑ", "frame from"),
            tr(en, "終了ﾌﾚｰﾑ", "frame to"),
        ],
        fresh,
    );
    ok_cancel(ui, en)
}

/// `BlinkRegisterDlgProc`, then the loop of case 227 and its info box with the count.
fn ok_blink(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let (start, end) = (field_int(f, 0), field_int(f, 1));
    ctx.editor.apply(Command::RegisterBlinks { start, end })?;
    if let Some(n) = ctx.editor.doc.edit.reported {
        let en = ctx.egui.as_ref().is_some_and(help::english);
        *ctx.status = match en {
            true => format!("{n} blinking is registered"),
            false => format!("{n}回のまばたきを追加しました"),
        };
    }
    Ok(())
}

// ---- 242, 251, 252: scale and add -----------------------------------------------------------

fn camera_multiply_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    ui.label(tr(en, "カメラ中心", "camera"));
    let fresh = f.fresh;
    pair_rows(ui, f, 0, &XYZ, fresh);
    ui.label(tr(en, "角度", "angle"));
    pair_rows(ui, f, 6, &XYZ, false);
    pair_rows(
        ui,
        f,
        12,
        &[tr(en, "距離 *", "dist *"), tr(en, "視野角 *", "v-angle *")],
        false,
    );
    ok_cancel(ui, en)
}

// `Command::Multiply*` carries `mds_ops` types that `mds-app` cannot name (it has no dependency
// on `mds-ops`), so the command starts from their defaults and the pairs are written into it.
fn ok_camera_multiply(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let mut cmd = Command::MultiplyCamera(Default::default());
    if let Command::MultiplyCamera(p) = &mut cmd {
        for (i, (s, a)) in p.scale.iter_mut().zip(p.add.iter_mut()).enumerate() {
            (*s, *a) = (field_float(f, 2 * i), field_float(f, 2 * i + 1));
        }
    }
    ctx.editor.apply(cmd)
}

fn bone_multiply_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    ui.label(tr(en, "ボーン位置", "bone place"));
    let fresh = f.fresh;
    pair_rows(ui, f, 0, &XYZ, fresh);
    ui.label(tr(en, "角度", "angle"));
    pair_rows(ui, f, 6, &XYZ, false);
    ok_cancel(ui, en)
}

fn ok_bone_multiply(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let mut cmd = Command::MultiplyBone(Default::default());
    if let Command::MultiplyBone(p) = &mut cmd {
        for (i, (s, a)) in p.scale.iter_mut().zip(p.add.iter_mut()).enumerate() {
            (*s, *a) = (field_float(f, 2 * i), field_float(f, 2 * i + 1));
        }
    }
    ctx.editor.apply(cmd)
}

fn morph_multiply_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    pair_rows(ui, f, 0, &[tr(en, "大きさ *", "degree *")], fresh);
    ok_cancel(ui, en)
}

fn ok_morph_multiply(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    ctx.editor.apply(Command::MultiplyMorph {
        scale: field_float(f, 0),
        add: field_float(f, 1),
    })
}

// ---- 253: edge thickness --------------------------------------------------------------------

fn edge_init(ctx: &Ctx) -> Form {
    let v = ctx
        .editor
        .doc
        .selected_model()
        .map_or(1.0, |m| m.edge_scale);
    Form {
        t: vec![format!("{v:3.2}")],
        f: vec![v],
        ..Form::default()
    }
}

/// `EdgeThicknessDlgProc` (`command_view_menu.cpp:550`): the slider (0 to 200 over 100) and Enter in
/// the edit box (7 characters, `EdgeThicknessEditSubclassProc`) set the thickness at once.
fn edge_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    ui.label(tr(en, "太さ", "thickness"));
    let mut pos = (f64::from(f.f[0]) * 100.0).clamp(0.0, 200.0) as i32;
    let mut set = None;
    ui.horizontal(|ui| {
        if ui
            .add(egui::Slider::new(&mut pos, 0..=200).show_value(false))
            .changed()
        {
            let v = pos as f32 / 100.0;
            f.t[0] = format!("{v:3.2}");
            set = Some(v);
        }
        let r = ui.add(egui::TextEdit::singleline(&mut f.t[0]).desired_width(40.0));
        if r.lost_focus() && ui.input(|i| i.key_pressed(Key::Enter)) {
            set = Some(edge_text(&f.t[0]));
        }
    });
    ui.label("0                     1                    2");
    if let Some(v) = set {
        f.f[0] = v;
        edge_commit(ctx, v);
    }
    Done::Open
}

fn edge_text(text: &str) -> f32 {
    atof(window_text(text, 8)) as f32
}

fn edge_commit(ctx: &mut Ctx, v: f32) {
    if let Err(e) = ctx.editor.apply(Command::SetEdgeScale(v)) {
        *ctx.status = e;
    }
}

/// Enter in the edit box, for the seam.
fn ok_edge(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    ctx.editor.apply(Command::SetEdgeScale(edge_text(&f.t[0])))
}

// ---- 300: numeric input ---------------------------------------------------------------------

/// `kPiLit`, the float pi of the edit handlers.
const PI_LIT: f64 = 3.141592025756836;

/// Menu 300 opens the dialog of the mode.
pub fn numeric_input(ctx: &mut Ctx) -> Result<(), String> {
    match in_camera_mode(ctx) {
        true => start(ctx, "IDD_CAMERA_NUMERIC_INPUT", Gate::Camera),
        false => open_bone_numeric(ctx),
    }
}

/// The bone dialog needs a selected bone (`selectedBone == -1` returns before it opens).
fn open_bone_numeric(ctx: &mut Ctx) -> Result<(), String> {
    match ctx.editor.doc.selected_model() {
        Some(m) if m.selection.selected_bone >= 0 => {
            start(ctx, "IDD_BONE_NUMERIC_INPUT", Gate::Model)
        }
        _ => Err("IDD_BONE_NUMERIC_INPUT: no bone is selected".into()),
    }
}

/// `"%7.3f"`.
fn shown(v: f32) -> String {
    format!("{v:7.3}")
}

fn numeric_form(values: &[f32]) -> Form {
    Form {
        t: values.iter().map(|&v| shown(v)).collect(),
        f: values.to_vec(),
        ..Form::default()
    }
}

/// The box `i` as the user left it: `None` while it still shows what the dialog opened with, so
/// that OK keeps the exact stored value rather than its rounding to three decimals.
fn edited(f: &Form, i: usize) -> Option<f64> {
    (f.t[i] != shown(f.f[i])).then(|| atof(window_text(&f.t[i], 20)))
}

fn degrees_of(rad: f32) -> f32 {
    (f64::from(rad) / PI_LIT * 180.0) as f32
}

/// The readout degrees `(x, y, z)` of a bone rotation: `PostViewRefresh`
/// (`src/window/ui_view_refresh.cpp:200` to `:260`), the same as the camera panel's readout.
fn euler_degrees(q: [f32; 4]) -> [f32; 3] {
    let m = Mat4::rotation_quaternion(Quat(q)).0;
    let d = f64::from;
    let mut rz = d(m[1]).atan2(d(m[5])) as f32;
    let mut rx = (-d(m[9])).asin() as f32;
    let mut ry = d(m[8]).atan2(d(m[10])) as f32;
    if d(d(rx).cos() as f32).abs() < d(1e-6f32) {
        rz = (d(rz) + if m[1] > 0.0 { PI_LIT } else { -PI_LIT }) as f32;
        ry = (d(ry) + if m[8] > 0.0 { PI_LIT } else { -PI_LIT }) as f32;
    }
    for a in [&mut rx, &mut ry, &mut rz] {
        if d(*a).abs() < d(1e-6f32) {
            *a = 0.0;
        }
    }
    let snap = |v: f32| if d(v).abs() < d(1e-7f32) { 0.0 } else { v };
    [
        snap((d(rx) / PI_LIT * 180.0) as f32),
        snap((-d(ry) / PI_LIT * 180.0) as f32),
        snap((180.0 * (-d(rz) / PI_LIT)) as f32),
    ]
}

/// `ComposeEulerToBone`: `Rz * Rx * Ry` with the readout's signs.
fn quaternion_of(deg: [f64; 3]) -> [f32; 4] {
    let ex = (deg[0] * PI_LIT / 180.0) as f32;
    let ey = (-deg[1] * PI_LIT / 180.0) as f32;
    let ez = (PI_LIT * -deg[2] / 180.0) as f32;
    let r = Mat4::multiply(&Mat4::rotation_z(ez), &Mat4::rotation_x(ex));
    Quat::from_matrix(&Mat4::multiply(&r, &Mat4::rotation_y(ey))).0
}

fn bone_numeric_init(ctx: &Ctx) -> Form {
    let Some(m) = ctx.editor.doc.selected_model() else {
        return Form::default();
    };
    let bone = usize::try_from(m.selection.selected_bone).unwrap_or(0);
    let Some(p) = m.bone_pose.get(bone) else {
        return Form::default();
    };
    let [x, y, z] = euler_degrees(p.rotation);
    let [px, py, pz] = p.translation;
    let mut f = numeric_form(&[px, py, pz, x, y, z]);
    f.f.push(bone as f32);
    f
}

fn numeric_rows(ui: &mut egui::Ui, f: &mut Form, en: bool, camera: bool) {
    let fresh = f.fresh;
    let pos = tr(en, "位置", "pos");
    let axes = [
        format!("{pos}X"),
        format!("{pos}Y"),
        format!("{pos}Z"),
        tr(en, "X軸", "axis X").to_string(),
        tr(en, "Y軸", "axis Y").to_string(),
        tr(en, "Z軸", "axis Z").to_string(),
        tr(en, "距離", "distance").to_string(),
    ];
    let count = if camera { 7 } else { 6 };
    ui.label(match camera {
        true => tr(en, "中心位置", "center position"),
        false => tr(en, "位置", "position"),
    });
    egui::Grid::new("mds.dialog.numeric").show(ui, |ui| {
        for (i, label) in axes.iter().enumerate().take(count) {
            if i == 3 {
                ui.label(tr(en, "角度(°)", "degree"));
                ui.end_row();
            }
            ui.label(label);
            edit(ui, &mut f.t[i], 70.0, fresh && i == 0);
            ui.end_row();
        }
    });
}

fn bone_numeric_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    numeric_rows(ui, f, en, false);
    ok_cancel(ui, en)
}

/// The position and the angles of the selected bone as typed: `PushBoneEditUndo`, the pose, the
/// edited mark (`SetBonePose`). A rotation box left alone keeps the stored quaternion.
fn ok_bone_numeric(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let bone = f.f[6] as usize;
    let pose = ctx
        .editor
        .doc
        .selected_model()
        .and_then(|m| m.bone_pose.get(bone))
        .ok_or("no such bone")?;
    let at = |i: usize| edited(f, i).map_or(f.f[i], |v| v as f32);
    let rotation = match (3..6).any(|i| edited(f, i).is_some()) {
        false => pose.rotation,
        true => quaternion_of([0, 1, 2].map(|i| edited(f, 3 + i).unwrap_or(f64::from(f.f[3 + i])))),
    };
    ctx.editor.apply(Command::SetBonePose {
        bone: bone as u32,
        translation: [at(0), at(1), at(2)],
        rotation,
    })
}

fn camera_numeric_init(ctx: &Ctx) -> Form {
    let s = &ctx.editor.doc.pmm.camera_state;
    numeric_form(&[
        s[0],
        s[1],
        s[2],
        degrees_of(-s[6]),
        degrees_of(s[7]),
        degrees_of(s[8]),
        -s[5],
    ])
}

fn camera_numeric_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    numeric_rows(ui, f, en, true);
    ok_cancel(ui, en)
}

/// Position, pitch (shown negated), yaw, roll and distance (shown negated) of the camera, in the
/// units of the camera panel's readout; one `SetCamera`.
fn ok_camera_numeric(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let p = &ctx.editor.doc.pmm;
    let s = p.camera_state;
    let radians = |i: usize, sign: f64, current: f32| {
        edited(f, i).map_or(current, |d| (sign * d * PI_LIT / 180.0) as f32)
    };
    let at = |i: usize, current: f32| edited(f, i).map_or(current, |v| v as f32);
    let cmd = Command::SetCamera {
        position: [at(0, s[0]), at(1, s[1]), at(2, s[2])],
        rotation: [
            radians(3, -1.0, s[6]),
            radians(4, 1.0, s[7]),
            radians(5, 1.0, s[8]),
        ],
        distance: edited(f, 6).map_or(s[5], |v| (-v) as f32),
        fov: p.settings.camera_fov,
        perspective: p.camera_perspective != 0,
    };
    ctx.editor.apply(cmd)
}

// ---- 266: gravity ---------------------------------------------------------------------------

fn gravity_init(ctx: &Ctx) -> Form {
    let p = &ctx.editor.doc.pmm.physics;
    let [x, y, z] = p.gravity_direction;
    let mut f = texts(&[
        &format!("{:3.2}", p.gravity_magnitude),
        &format!("{x:3.2}"),
        &format!("{y:3.2}"),
        &format!("{z:3.2}"),
        &p.gravity_noise.to_string(),
    ]);
    f.c = vec![p.gravity_noise_enabled != 0];
    f.applied = f.t.clone();
    f
}

/// `GravitySettingDlgProc` (`src/window/gravity_setting_dialog.cpp:186`): every edit and slider
/// change goes to the document at once (`EN_UPDATE`, `WM_HSCROLL`: `SetGravityChannel`);
/// "register" registers the gravity key at the current frame and the dialog stays; "close"
/// ends it (`ApplyGravityTrack`).
fn gravity_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let (mut done, fresh) = (Done::Open, f.fresh);
    ui.horizontal(|ui| {
        ui.label(tr(en, "加速度", "acceleration"));
        edit(ui, &mut f.t[0], 40.0, fresh);
        ui.checkbox(&mut f.c[0], tr(en, "ﾉｲｽﾞ付加", "noize"));
        ui.add_enabled_ui(f.c[0], |ui| edit(ui, &mut f.t[4], 40.0, false));
    });
    for (axis, name) in ["x", "y", "z"].into_iter().enumerate() {
        ui.horizontal(|ui| {
            ui.label(format!("{} {name}", tr(en, "向き", "dir")));
            let mut pos =
                (atof(window_text(&f.t[1 + axis], 256)) * 100.0).clamp(-100.0, 100.0) as i32;
            if ui
                .add(egui::Slider::new(&mut pos, -100..=100).show_value(false))
                .changed()
            {
                f.t[1 + axis] = format!("{:3.2}", f64::from(pos) / 100.0);
            }
            edit(ui, &mut f.t[1 + axis], 40.0, false);
        });
    }
    ui.label("-1                    0                    1");
    gravity_sync(ctx, f);
    ui.horizontal(|ui| {
        if ui.button(tr(en, "登録", "register")).clicked() {
            register_gravity(ctx);
        }
        if ui.button(tr(en, "閉じる", "close")).clicked() {
            done = Done::Cancel;
        }
    });
    done
}

/// Sends what changed since the last call to the document: the noise check, then each edit box.
fn gravity_sync(ctx: &mut Ctx, f: &mut Form) {
    let p = &ctx.editor.doc.pmm.physics;
    if f.c[0] != (p.gravity_noise_enabled != 0) {
        let cmd = Command::SetGravity {
            acceleration: p.gravity_magnitude,
            noise: p.gravity_noise,
            direction: p.gravity_direction,
            noise_enabled: f.c[0],
        };
        if let Err(e) = ctx.editor.apply(cmd) {
            *ctx.status = e;
        }
    }
    for i in 0..f.t.len() {
        if f.t[i] != f.applied[i] {
            f.applied[i] = f.t[i].clone();
            let v = atof(window_text(&f.t[i], 256)) as f32;
            if let Err(e) = ctx.editor.apply(Command::SetGravityChannel(i as u8, v)) {
                *ctx.status = e;
            }
        }
    }
}

/// The "register" button: registers the gravity key at the current frame. The dialog stays.
pub fn register_gravity(ctx: &mut Ctx) {
    let register = Command::RegisterGlobalKeys(vec![GlobalTrack::Gravity]);
    if let Err(e) = ctx.editor.apply(register) {
        *ctx.status = e;
    }
}

// ---- 275: physics ON/OFF --------------------------------------------------------------------

fn physics_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    ui.label(tr(
        en,
        "選択されたフレームポイントのうち、物理影響ボーンの",
        "Change all selected frame point(under physics)",
    ));
    ui.horizontal(|ui| {
        ui.label(tr(en, "フレームを全て物理", "to physics"));
        egui::ComboBox::from_id_salt("mds.dialog.physics")
            .selected_text(["ON (X印)", "OFF"][f.pick.min(1)])
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut f.pick, 0, tr(en, "ON (X印)", "ON (X mark)"));
                ui.selectable_value(&mut f.pick, 1, "OFF");
            });
        ui.label(tr(en, "の状態にします", "."));
    });
    ok_cancel(ui, en)
}

/// `PhysicsOnOffFrameDlgProc`: combo item 0 is on (`physicsDisabled` false), item 1 off. Cancel
/// returns the same code as OK and changes nothing.
fn ok_physics(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    ctx.editor.apply(Command::SetKeyPhysics {
        disabled: f.pick != 0,
    })
}

// ---- 248: ground shadow color ---------------------------------------------------------------

/// The View menu draws this window and keeps its value (`ViewOptions::ground_shadow_gray`), so
/// the action is menu 248.
fn shadow_color(ctx: &mut Ctx) -> Result<(), String> {
    actions::run(ctx, "menu:248")
}

// ---- the pmm 2.0 load prompts ---------------------------------------------------------------

/// What the user chose in a pmm load prompt. The loader (`LoadSceneV2_ModelBlock`,
/// `src/io/pmm_load_v2.cpp:1056` and `:1289`) takes the `DialogBoxParamA` result: the buttons
/// 687 to 690 return 1, 3, 4 and 5 (`DialogFuncStub`, `src/app/late_ports.cpp:314`), the close
/// button 2.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LoadChoice {
    /// Missing model, button 687: pick the model file and load it.
    Locate,
    /// Mismatch, button 687: fit the pmm's model data to this model and go on.
    Fit,
    /// Mismatch, button 688: pick another model file.
    AnotherFile,
    /// Missing model 688, mismatch 689: drop the model and read the next data.
    Skip,
    /// Missing model 689, mismatch 690, or the close button: stop loading the project.
    Abort,
}

/// The prompt to show.
#[derive(Clone, Copy, Debug)]
pub enum Prompt<'a> {
    /// `ModelLoadPMD` failed on the path stored in the pmm.
    MissingModel {
        model_name: &'a str,
        source_name: &'a str,
    },
    /// The model's morph or display counts differ from the pmm's. `again` is the re-test after
    /// the user picked another file.
    ModelMismatch {
        model_name: &'a str,
        source_name: &'a str,
        again: bool,
    },
}

fn message_key() -> Id {
    Id::unique("mds.dialog.message")
}

fn choice_key() -> Id {
    Id::unique("mds.dialog.choice")
}

/// Opens a load prompt with the text of `statusText` in the C++ (`kJpQuoted`, `kJpStructFmt` and
/// the English formats of `pmm_load_v2.cpp`).
pub fn ask(egui: &Context, prompt: Prompt) {
    let en = help::english(egui);
    let (name, text) = match prompt {
        Prompt::MissingModel {
            model_name,
            source_name,
        } => (
            "IDD_PMM_MISSING_MODEL",
            match en {
                true => format!("Cannot open the model file:{source_name}"),
                false => format!("\"{model_name}\""),
            },
        ),
        Prompt::ModelMismatch {
            model_name,
            source_name,
            again,
        } => (
            "IDD_PMM_MODEL_MISMATCH",
            match (en, again) {
                (true, true) => {
                    format!("This model structure is different from pmm too. file:{source_name}")
                }
                (true, false) => {
                    format!("Model structure is different from pmm. file:{source_name}")
                }
                (false, true) => {
                    format!("このモデルの構造もpmm保存時の\"{model_name}\"のものと異なります")
                }
                (false, false) => format!("\"{model_name}\""),
            },
        ),
    };
    egui.data_mut(|d| {
        d.insert_temp(message_key(), text);
        d.remove::<LoadChoice>(choice_key());
    });
    open_in(egui, name);
}

/// The text of the last prompt.
pub fn prompt_message(egui: &Context) -> Option<String> {
    egui.data(|d| d.get_temp(message_key()))
}

/// The choice of the last prompt, once.
pub fn take_choice(egui: &Context) -> Option<LoadChoice> {
    take(egui, choice_key())
}

fn abort_unless_chosen(ctx: &mut Ctx) {
    if let Some(egui) = &ctx.egui {
        egui.data_mut(|d| {
            if d.get_temp::<LoadChoice>(choice_key()).is_none() {
                d.insert_temp(choice_key(), LoadChoice::Abort);
            }
        });
    }
}

/// The wide buttons of a prompt; the first is the default button.
fn choices(ui: &mut egui::Ui, ctx: &Ctx, labels: &[(&str, LoadChoice)]) -> Done {
    let message: String = ui
        .ctx()
        .data(|d| d.get_temp(message_key()))
        .unwrap_or_default();
    ui.label(message);
    let mut done = Done::Open;
    for &(label, choice) in labels {
        if ui
            .add_sized([360.0, 22.0], egui::Button::new(label))
            .clicked()
        {
            if let Some(egui) = &ctx.egui {
                egui.data_mut(|d| d.insert_temp(choice_key(), choice));
            }
            done = Done::Cancel;
        }
    }
    done
}

fn missing_body(ui: &mut egui::Ui, ctx: &mut Ctx, _: &mut Form, en: bool) -> Done {
    choices(
        ui,
        ctx,
        &[
            (
                tr(
                    en,
                    "モデルファイルの場所を指定して読み込む",
                    "Specify the place of model file and load",
                ),
                LoadChoice::Locate,
            ),
            (
                tr(
                    en,
                    "このモデルを飛ばして次のデータを読み込む",
                    "Skip this model and continue",
                ),
                LoadChoice::Skip,
            ),
            (
                tr(
                    en,
                    "プロジェクト全体の読み込みを中止する",
                    "Cancel to load this project",
                ),
                LoadChoice::Abort,
            ),
        ],
    )
}

fn mismatch_body(ui: &mut egui::Ui, ctx: &mut Ctx, _: &mut Form, en: bool) -> Done {
    choices(
        ui,
        ctx,
        &[
            (
                tr(
                    en,
                    "このモデルにpmmファイルのモデル情報を適応させて続行",
                    "Fit pmm model data to this model and continue",
                ),
                LoadChoice::Fit,
            ),
            (
                tr(
                    en,
                    "別のモデルファイルを指定して読み込む",
                    "Specify the place of another model file",
                ),
                LoadChoice::AnotherFile,
            ),
            (
                tr(
                    en,
                    "このモデルを飛ばして次のデータを読み込む",
                    "Skip this model and continue",
                ),
                LoadChoice::Skip,
            ),
            (
                tr(
                    en,
                    "プロジェクト全体の読み込みを中止する",
                    "Cancel to load this project",
                ),
                LoadChoice::Abort,
            ),
        ],
    )
}
