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
//! All 24 rows open. Ground shadow color (menu 248) is drawn by the View menu (`view.rs`, which
//! owns that window's state), so its action runs `menu:248`.
//!
//! Entry points that other areas have to wire: the English names, toon texture and physics model
//! dialogs belong to menu 259, 261 and 262 (`help.rs`, which lists them as missing: run
//! `dlg:IDD_ENGLISH_NAMES`, `dlg:IDD_TOON_TEXTURE`, `dlg:IDD_PHYSICS_MODEL`); the timeline's
//! button 424 runs `dlg:IDD_FRAME_SCALE`. The physics model dialog tells the viewport which
//! record it has selected ([`viewport::set_record_target`]), so the record drag edits it.
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
//! * [`apply_cpp`] puts the modified flag back after a command whose C++ handler sets no
//!   `SceneModified` where the document's rule (`Document::marks_modified`, which knows an empty
//!   clipboard) differs from the `Editor`'s.
//! * The outside parent dialog shows the readout of the result on a copy of the document; the PMM
//!   holds the Japanese bone names only, so the English names are not shown.
//! * The physics model dialog edits a dense scratch list (`EditState::physics_scratch`): after a
//!   delete and an add the new body is `BODY_<count>`, where the C++ reuses a free slot. The
//!   committed model does not rebuild the live physics world (an `Editor` limitation), and a
//!   changed rigid body or joint name has to be ASCII (there is no Shift-JIS encoder here).
//! * The English names dialog does not select the bone it shows, and keeps no
//!   `FrameRangeStartFrame` for the frame scale dialog.
//! * The window is not modal. Playback still greys out the actions that edit the document.
//!
//! `MDS_APP_DIALOG=<name>` opens a dialog when the window starts, for screenshots.

use super::camera_panel::{atof, atol, in_camera_mode, window_text};
use super::viewport::{self, RecordTarget};
use super::{help, model_panel, timeline, Ctx};
use crate::actions::{self, Action};
use egui::{Align2, Context, Id, Key};
use mds_doc::{Command, EnglishName, GlobalTrack, ModelFile, OutsideParent};
use mds_formats::pmd::{Joint, Rigid};
use mds_formats::text::{decode_sjis, FixedSjis};
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
    opens!("dlg:IDD_FRAME_SCALE", "IDD_FRAME_SCALE", Gate::Model, true),
    opens!(
        "dlg:IDD_ACCESSORY_ORDER",
        "IDD_ACCESSORY_ORDER",
        Gate::Any,
        true
    ),
    opens!(
        "dlg:IDD_MODEL_DRAW_ORDER",
        "IDD_MODEL_DRAW_ORDER",
        Gate::Any,
        true
    ),
    opens!(
        "dlg:IDD_MODEL_CALCULATE_ORDER",
        "IDD_MODEL_CALCULATE_ORDER",
        Gate::Any,
        true
    ),
    Action::run("dlg:IDD_OUTSIDE_PARENT", open_outside_parent, true),
    Action::run("dlg:IDD_ENGLISH_NAMES", open_english_names, true),
    Action::run("dlg:IDD_TOON_TEXTURE", open_toon, true),
    Action::run("dlg:IDD_PHYSICS_MODEL", open_physics_model, true),
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
    if name == PHYSICS_MODEL {
        viewport::set_record_target(egui, None);
    }
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
    /// The list box of the order dialogs: `(slot, text)` rows and the selected row.
    rows: Vec<(u8, String)>,
    sel: Option<usize>,
    /// The outside parent dialog.
    op: Op,
    /// The English names dialog: the cursors of its three combos.
    cursors: [usize; 3],
    /// The physics model dialog.
    ph: Phys,
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
    /// Cancel, Esc and the close button; the English names dialog applies its boxes here too.
    cancel: fn(&mut Ctx, &Form),
    /// Runs after every edit of a box (`EN_UPDATE`) for the dialogs that apply as they go.
    live: fn(&mut Ctx, &mut Form),
    /// Whether the dialog still has what it edits: a dialog of the selected model closes when
    /// the model is deleted or camera mode is entered.
    valid: fn(&Ctx) -> bool,
}

fn accept(_: &mut Ctx, _: &Form) -> Result<(), String> {
    Ok(())
}

fn nothing(_: &mut Ctx, _: &Form) {}

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
    valid: |_| true,
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
        cancel: |c, _| {
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
        name: "IDD_FRAME_SCALE",
        ja: "時間拡大(縮小)率",
        en: "expand/shrink",
        init: scale_init,
        body: scale_body,
        ok: ok_scale,
        ..MODAL
    },
    Spec {
        name: "IDD_ACCESSORY_ORDER",
        ja: "アクセサリ設定",
        en: "accessory",
        init: accessory_init,
        body: accessory_body,
        ok: ok_accessory,
        live: accessory_live,
        ..MODAL
    },
    Spec {
        name: "IDD_MODEL_DRAW_ORDER",
        ja: "モデル描画順設定",
        en: "model disply order",
        init: |c| order_init(c, false),
        body: draw_order_body,
        ok: ok_draw_order,
        ..MODAL
    },
    Spec {
        name: "IDD_MODEL_CALCULATE_ORDER",
        ja: "モデル計算順設定",
        en: "model calculate order",
        init: |c| order_init(c, true),
        body: calc_order_body,
        ok: ok_calc_order,
        ..MODAL
    },
    Spec {
        name: "IDD_OUTSIDE_PARENT",
        ja: "外部親設定",
        en: "outside parent(OP) setting",
        modal: false,
        init: op_init,
        body: op_body,
        cancel: op_close,
        valid: model_bound,
        ..MODAL
    },
    Spec {
        name: "IDD_ENGLISH_NAMES",
        ja: "英語名編集(半角英数字で入力、Enterキーで決定)",
        en: "If name is writen by Japanese Font,Rename it to English Font.",
        modal: false,
        init: names_init,
        body: names_body,
        ok: ok_names,
        cancel: cancel_names,
        valid: model_bound,
        ..MODAL
    },
    Spec {
        name: "IDD_TOON_TEXTURE",
        ja: "トゥーンテクスチャ",
        en: "toon texture",
        init: toon_init,
        body: toon_body,
        ok: ok_toon,
        valid: model_bound,
        ..MODAL
    },
    Spec {
        name: "IDD_PHYSICS_MODEL",
        ja: "物理演算モデル",
        en: "physics model",
        modal: false,
        init: physics_init,
        body: physm_body,
        ok: ok_physics_model,
        cancel: cancel_physics_model,
        valid: model_bound,
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
    if !(spec.valid)(ctx) {
        settle(ctx, &egui, spec, form, Done::Cancel);
        return;
    }
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
        Done::Open => {
            publish_record(egui, spec.name, &form);
            store(egui, spec.name, form);
        }
        Done::Cancel => {
            (spec.cancel)(ctx, &form);
            close(egui, spec.name);
        }
        Done::Ok => match (spec.ok)(ctx, &form) {
            Ok(()) => close(egui, spec.name),
            Err(e) => {
                *ctx.status = e;
                publish_record(egui, spec.name, &form);
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
    if let Ok((egui, spec, form)) = open_form(ctx) {
        (spec.cancel)(ctx, &form);
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

/// Menu 259 (`command_view_menu.cpp:903`): a second call while the dialog is open does nothing,
/// and camera mode returns. A model has to be selected for the dialog to have anything to edit.
fn open_english_names(ctx: &mut Ctx) -> Result<(), String> {
    open_for_model(ctx, "IDD_ENGLISH_NAMES")
}

/// Menu 261.
fn open_toon(ctx: &mut Ctx) -> Result<(), String> {
    open_for_model(ctx, "IDD_TOON_TEXTURE")
}

/// Menu 262.
fn open_physics_model(ctx: &mut Ctx) -> Result<(), String> {
    let open = ctx.egui.as_ref().and_then(current) == Some(PHYSICS_MODEL);
    // `InitPhysicsModelDialog` copies the model's records for the dialog and the viewport; the
    // copy is made only once the dialog really opens.
    let copy = if open {
        None
    } else {
        Some(physics_source(ctx)?)
    };
    open_for_model(ctx, PHYSICS_MODEL)?;
    if copy.is_some() {
        ctx.editor.doc.edit.physics_scratch = copy;
    }
    if let Ok((egui, _, form)) = open_form(ctx) {
        publish_record(&egui, PHYSICS_MODEL, &form);
    }
    Ok(())
}

const PHYSICS_MODEL: &str = "IDD_PHYSICS_MODEL";

/// The record the physics dialog has selected, for the viewport's record drag
/// (`EditModeRecord`, `frame_modes_bone.cpp:158`, edits `selectedRigidIndex` or
/// `selectedJointIndex` by the page): published on open, after every change of the form, and
/// cleared in [`close`].
fn publish_record(egui: &Context, name: &str, f: &Form) {
    if name != PHYSICS_MODEL {
        return;
    }
    let (joint, index) = match f.ph.joint_page {
        true => (true, f.ph.joint),
        false => (false, f.ph.body),
    };
    let target = index.map(|i| RecordTarget {
        joint,
        index: i as u32,
    });
    viewport::set_record_target(egui, target);
}

/// Ctl 442: the outside parent dialog of the selected model.
fn open_outside_parent(ctx: &mut Ctx) -> Result<(), String> {
    open_for_model(ctx, "IDD_OUTSIDE_PARENT")
}

fn open_for_model(ctx: &mut Ctx, name: &'static str) -> Result<(), String> {
    bound_model(ctx).map_err(|e| format!("{name}: {e}"))?;
    start(ctx, name, Gate::Model)
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
/// units of the camera panel's readout; one `SetCameraFromMenu` (`SceneModified`,
/// `command_view_menu.cpp:1771`).
fn ok_camera_numeric(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let p = &ctx.editor.doc.pmm;
    let s = p.camera_state;
    let radians = |i: usize, sign: f64, current: f32| {
        edited(f, i).map_or(current, |d| (sign * d * PI_LIT / 180.0) as f32)
    };
    let at = |i: usize, current: f32| edited(f, i).map_or(current, |v| v as f32);
    let cmd = Command::SetCameraFromMenu {
        position: [at(0, s[0]), at(1, s[1]), at(2, s[2])],
        rotation: [
            radians(3, -1.0, s[6]),
            radians(4, 1.0, s[7]),
            radians(5, 1.0, s[8]),
        ],
        distance: edited(f, 6).map_or(s[5], |v| (-v) as f32),
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

// ---- the document commands as the C++ handlers leave SceneModified --------------------------

/// `Editor::apply`, then the modified flag as the C++ handler leaves it. `Editor` marks the
/// document by `Command::marks_modified`, which does not know that a paste with an empty
/// clipboard changes nothing; where `Document::marks_modified` is false the flag is put back.
pub fn apply_cpp(ctx: &mut Ctx, cmd: Command) -> Result<(), String> {
    let marks = ctx.editor.doc.marks_modified(&cmd);
    let modified = ctx.editor.modified;
    ctx.editor.apply(cmd)?;
    if !marks {
        ctx.editor.modified = modified;
    }
    Ok(())
}

/// `EnglishUI()`.
fn en_ui(ctx: &Ctx) -> bool {
    ctx.egui.as_ref().is_some_and(help::english)
}

/// The dialogs of the selected model close with it: the model mode with a model selected.
fn model_bound(ctx: &Ctx) -> bool {
    !in_camera_mode(ctx) && model_panel::selected_index(&ctx.editor.doc).is_some()
}

fn bound_model(ctx: &Ctx) -> Result<usize, String> {
    if in_camera_mode(ctx) {
        return Err("model mode only".into());
    }
    model_panel::selected_index(&ctx.editor.doc).ok_or_else(|| "no model selected".into())
}

/// The seams of the dialogs that have more than edit boxes: `f` runs on the open dialog `name`
/// and its form is stored again.
fn with_form<R>(
    ctx: &mut Ctx,
    name: &str,
    f: impl FnOnce(&mut Ctx, &mut Form) -> R,
) -> Result<R, String> {
    let (egui, spec, mut form) = open_form(ctx)?;
    if spec.name != name {
        return Err(format!("{name} is not open"));
    }
    let r = f(ctx, &mut form);
    publish_record(&egui, spec.name, &form);
    store(&egui, spec.name, form);
    Ok(r)
}

/// A combo box of `items`; the item picked this pass.
fn combo_box(
    ui: &mut egui::Ui,
    salt: &str,
    items: &[String],
    sel: usize,
    width: f32,
) -> Option<usize> {
    let mut pick = None;
    egui::ComboBox::from_id_salt(salt)
        .width(width)
        .selected_text(items.get(sel).cloned().unwrap_or_default())
        .show_ui(ui, |ui| {
            for (i, text) in items.iter().enumerate() {
                if ui.selectable_label(sel == i, text).clicked() {
                    pick = Some(i);
                }
            }
        });
    pick
}

/// The text of a combo item, for the readers of this file (`""` past the end).
fn names(v: &[(u32, String)]) -> Vec<String> {
    v.iter().map(|(_, t)| t.clone()).collect()
}

// ---- 424: frame range scaling ---------------------------------------------------------------

/// `FrameRangeDlgProc` (`src/window/dialog_procs.cpp:62`): the range boxes of the timeline
/// panel, the rate 1.0 and the three family boxes checked.
fn scale_init(ctx: &Ctx) -> Form {
    let range = timeline::panel(ctx).range;
    Form {
        t: vec![range[0].to_string(), range[1].to_string(), "1.0".into()],
        c: vec![true; 3],
        ..Form::default()
    }
}

fn scale_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    ui.horizontal(|ui| {
        ui.label(tr(en, "フレーム", "frame"));
        edit(ui, &mut f.t[0], 35.0, fresh);
        ui.label("-");
        edit(ui, &mut f.t[1], 35.0, false);
    });
    ui.horizontal(|ui| {
        ui.label(tr(en, "　　倍率", "magnification"));
        edit(ui, &mut f.t[2], 30.0, false);
    });
    ui.horizontal(|ui| {
        ui.checkbox(&mut f.c[0], tr(en, "ボーン", "Bone"));
        ui.checkbox(&mut f.c[1], tr(en, "表情", "Facial"));
        ui.checkbox(&mut f.c[2], tr(en, "表示･IK･外親", "Disp/IK/OP"));
    });
    ok_cancel(ui, en)
}

/// `ApplyFrameRangeScale` (`frame_range_apply.cpp:297`): the boxes are read with
/// `GetWindowTextA(.., 8)`; an empty range or a rate of 1.0 or below 0.00001 returns with
/// nothing changed, and the dialog closes either way. (`FrameRangeStartFrame` is not kept.)
fn ok_scale(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let read = |i: usize| window_text(&f.t[i], 8);
    let (start, end) = (atol(read(0)) as i32, atol(read(1)) as i32);
    let scale = atof(read(2));
    if end.wrapping_sub(start) <= 0 || scale < 0.000_009_999_999_7 || scale == 1.0 {
        return Ok(());
    }
    let p = mds_ops::RangeScale {
        start,
        end,
        scale,
        bones: f.c[0],
        morphs: f.c[1],
        display: f.c[2],
    };
    apply_cpp(ctx, Command::ScaleFrames(p))
}

// ---- 288, 289: model draw and calculation order ---------------------------------------------

/// The list box of the order dialogs, one row per model: by `comboSelIndex` for the draw order
/// (the camera entry is not a row) and by `comboSelIndex2` for the calculation order.
fn order_init(ctx: &Ctx, calc: bool) -> Form {
    let en = en_ui(ctx);
    let mut models: Vec<_> = ctx.editor.doc.pmm.models.iter().collect();
    models.sort_by_key(|m| {
        if calc {
            m.display_order
        } else {
            m.selection.combo_index
        }
    });
    Form {
        rows: models
            .into_iter()
            .map(|m| (m.slot, if en { &m.name_en } else { &m.name }.text.clone()))
            .collect(),
        ..Form::default()
    }
}

/// The list box: one selectable row each. The row clicked this pass.
fn list_box(ui: &mut egui::Ui, f: &Form, salt: &str) -> Option<usize> {
    let mut clicked = None;
    egui::ScrollArea::vertical()
        .id_salt(salt)
        .max_height(180.0)
        .auto_shrink([false, true])
        .show(ui, |ui| {
            ui.set_min_width(140.0);
            for (i, (_, text)) in f.rows.iter().enumerate() {
                if ui.selectable_label(f.sel == Some(i), text).clicked() {
                    clicked = Some(i);
                }
            }
        });
    clicked
}

/// Buttons 630 and 631: the selected row swaps with its neighbour (`LB_DELETESTRING`,
/// `LB_INSERTSTRING` and the swap of the slot array).
fn move_row(f: &mut Form, up: bool) {
    let Some(s) = f.sel else { return };
    let to = if up {
        s.checked_sub(1)
    } else {
        Some(s + 1).filter(|&n| n < f.rows.len())
    };
    if let Some(to) = to {
        f.rows.swap(s, to);
        f.sel = Some(to);
    }
}

fn order_buttons(ui: &mut egui::Ui, f: &mut Form, en: bool, label: &str) {
    ui.label(label);
    ui.horizontal(|ui| {
        if ui.button(tr(en, "上", "up")).clicked() {
            move_row(f, true);
        }
        if ui.button(tr(en, "下", "down")).clicked() {
            move_row(f, false);
        }
    });
}

fn draw_order_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let mut clicked = None;
    ui.horizontal(|ui| {
        clicked = list_box(ui, f, "mds.dialog.draw-order");
        ui.vertical(|ui| order_buttons(ui, f, en, tr(en, "  描画順序", "drawing order")));
    });
    f.sel = clicked.or(f.sel);
    ok_cancel(ui, en)
}

fn calc_order_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let mut clicked = None;
    ui.horizontal(|ui| {
        clicked = list_box(ui, f, "mds.dialog.calc-order");
        ui.vertical(|ui| order_buttons(ui, f, en, tr(en, "  計算順序", "calculate order")));
    });
    f.sel = clicked.or(f.sel);
    ok_cancel(ui, en)
}

fn row_slots(f: &Form) -> Vec<u8> {
    f.rows.iter().map(|(slot, _)| *slot).collect()
}

/// `ApplyModelDisplayOrderDialog` (`model_order_dialog.cpp:85`): row `i` takes combo index
/// `i + 1`, and the camera entry is selected.
fn ok_draw_order(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    apply_cpp(ctx, Command::SetModelDrawOrder(row_slots(f)))
}

/// `ApplyModelCalculateOrderDialog` (`model_order_dialog.cpp:54`): row `i` takes order `i`.
fn ok_calc_order(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    apply_cpp(ctx, Command::SetModelCalcOrder(row_slots(f)))
}

/// Selects row `i` of the open order or accessory dialog.
pub fn select_row(ctx: &mut Ctx, i: usize) -> Result<(), String> {
    let (egui, spec, mut form) = open_form(ctx)?;
    if i >= form.rows.len() {
        return Err("no such row".into());
    }
    choose_row(&mut form, i, spec.name == "IDD_ACCESSORY_ORDER");
    store(&egui, spec.name, form);
    Ok(())
}

/// Presses up (630) or down (631) of the open order or accessory dialog.
pub fn move_selected(ctx: &mut Ctx, up: bool) -> Result<(), String> {
    let (egui, spec, mut form) = open_form(ctx)?;
    move_row(&mut form, up);
    store(&egui, spec.name, form);
    Ok(())
}

/// The rows of the open order or accessory dialog.
pub fn list_rows(ctx: &Ctx) -> Vec<String> {
    open_form(ctx).map_or_else(
        |_| Vec::new(),
        |(_, _, f)| f.rows.into_iter().map(|r| r.1).collect(),
    )
}

// ---- 249: accessories -----------------------------------------------------------------------

/// `AccessorySettingsDlgProc` (`command_file_menu.cpp:741`): the combo of the panel as rows, the
/// split count `accessoryRenderSplitOrder` in the count box, no row selected.
fn accessory_init(ctx: &Ctx) -> Form {
    let p = &ctx.editor.doc.pmm;
    let split = p.physics.accessory_render_order.to_string();
    Form {
        rows: p
            .accessories
            .iter()
            .map(|a| (a.slot, a.list_name.text.clone()))
            .collect(),
        t: vec![String::new(), split.clone()],
        applied: vec![split],
        ..Form::default()
    }
}

/// A click on a row: the name box shows its text (`CBN_SELCHANGE` of the list).
fn choose_row(f: &mut Form, i: usize, show_name: bool) {
    f.sel = Some(i);
    if show_name {
        f.t[0] = f.rows[i].1.clone();
    }
}

/// Button 633 (the hidden default button, Enter in the name box): the name box replaces the
/// selected row, unless it is empty or no row is selected.
fn rename_row(f: &mut Form) {
    let text = window_text(&f.t[0], 256).to_string();
    if let Some(s) = f.sel.filter(|&s| s < f.rows.len()) {
        if !text.is_empty() {
            f.rows[s].1 = text;
        }
    }
}

/// `EN_CHANGE` of the count box: clamped to 0 to the number of rows (the text rewritten when
/// clamped), and the row of that number is the selected one (none from the number of rows on).
fn accessory_live(_: &mut Ctx, f: &mut Form) {
    if f.t[1] == f.applied[0] {
        return;
    }
    let count = f.rows.len() as i64;
    let mut n = atol(window_text(&f.t[1], 256));
    if n > 0 {
        if n > count {
            n = count;
            f.t[1] = count.to_string();
        }
    } else {
        n = 0;
        f.t[1] = "0".into();
    }
    f.applied[0] = f.t[1].clone();
    f.sel = (n < count).then_some(n as usize);
}

fn accessory_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let mut clicked = None;
    let mut enter = false;
    ui.horizontal(|ui| {
        clicked = list_box(ui, f, "mds.dialog.accessory");
        ui.vertical(|ui| {
            ui.label(tr(en, "ｱｸｾｻﾘ名(決定:Enter)", "name(press 'Enter')"));
            let r = ui.add(egui::TextEdit::singleline(&mut f.t[0]).desired_width(65.0));
            enter = r.lost_focus() && ui.input(|i| i.key_pressed(Key::Enter));
            order_buttons(ui, f, en, tr(en, "  描画順序", "drawing order"));
            ui.horizontal(|ui| {
                edit(ui, &mut f.t[1], 25.0, false);
                ui.label(tr(en, "番目より後の", "th"));
            });
            ui.label(tr(
                en,
                "ｱｸｾｻﾘはﾓﾃﾞﾙ描写後に描写する",
                "accessory described after models",
            ));
        });
    });
    if let Some(i) = clicked {
        choose_row(f, i, true);
    }
    if enter {
        rename_row(f);
    }
    accessory_live(ctx, f);
    ok_cancel(ui, en)
}

/// OK (632): `accessoryRenderSplitOrder` from the count box, then `ApplyAccessorySettingsDialog`:
/// each row whose text changed is a rename, the rows give the order and the names follow, and
/// the first row is selected.
fn ok_accessory(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    for (slot, text) in &f.rows {
        let old = ctx
            .editor
            .doc
            .pmm
            .accessories
            .iter()
            .find(|a| a.slot == *slot)
            .map(|a| a.list_name.text.clone());
        if old.as_deref() != Some(text) {
            let cmd = Command::RenameAccessory {
                slot: *slot,
                name: text.clone(),
            };
            apply_cpp(ctx, cmd)?;
        }
    }
    apply_cpp(ctx, Command::SetAccessoryOrder(row_slots(f)))?;
    apply_cpp(ctx, Command::SetAccessoryRenderSplit(field_int(f, 1)))
}

/// The name box of the open accessory dialog and Enter in it (button 633).
pub fn rename_selected(ctx: &mut Ctx) -> Result<(), String> {
    with_form(ctx, "IDD_ACCESSORY_ORDER", |_, f| rename_row(f))
}

// ---- 442: outside parent --------------------------------------------------------------------

/// The state of the outside parent dialog (`SelectNavDlgProc`, `dialog_procs.cpp:109`): the
/// copy of the selector records it edits (`selectNavRecords`) and its three combos.
#[derive(Clone, Debug, Default)]
struct Op {
    /// Combo 669: "root" and the selector bones.
    selectors: Vec<String>,
    /// Combo 673 from its third entry: the models in calculation order.
    models: Vec<(u8, String)>,
    /// Combo 677: the bones a target model offers.
    bones: Vec<(u32, String)>,
    /// One record per selector.
    links: Vec<OutsideParent>,
    /// The cursors: the selector, the target (0 none, 1 ground, 2 and up a model) and its bone.
    selector: usize,
    kind: usize,
    bone: usize,
}

/// `InitSelectNavDialog` (`dialog_select_ops.cpp:113`).
fn op_init(ctx: &Ctx) -> Form {
    let doc = &ctx.editor.doc;
    let Some(i) = model_panel::selected_index(doc) else {
        return Form::default();
    };
    let (m, en) = (&doc.pmm.models[i], en_ui(ctx));
    let mut op = Op::default();
    for (k, &b) in m.selector_bones.iter().enumerate() {
        let name = usize::try_from(b)
            .ok()
            .and_then(|b| m.bone_names.get(b))
            .map_or_else(String::new, |n| n.text.clone());
        op.selectors.push(if k == 0 {
            tr(en, "ルート", "root").into()
        } else {
            name
        });
    }
    op.links = m
        .selector_pose
        .iter()
        .map(|s| match (s[2], s[3]) {
            (-2, _) => OutsideParent::Ground,
            (model, bone) if model >= 0 => OutsideParent::Bone {
                model: model as u8,
                bone: bone.max(0) as u32,
            },
            _ => OutsideParent::None,
        })
        .collect();
    let mut order: Vec<_> = doc.pmm.models.iter().collect();
    order.sort_by_key(|m| m.display_order);
    op.models = order
        .into_iter()
        .map(|o| {
            let name = if en { &o.name_en } else { &o.name }.text.clone();
            let name = if o.slot == m.slot {
                format!("({name})")
            } else {
                name
            };
            (o.slot, name)
        })
        .collect();
    let at = m.selection.selected_bone;
    op.selector = m
        .selector_bones
        .iter()
        .rposition(|&b| b == at)
        .filter(|&k| k > 0)
        .unwrap_or(usize::from(op.selectors.len() > 1));
    let mut f = Form {
        t: vec![String::new(); 6],
        op,
        ..Form::default()
    };
    op_sync(ctx, &mut f);
    f
}

/// The bones the target model offers (`RebuildTargetBoneList`).
fn op_bones(ctx: &Ctx, op: &mut Op) {
    op.bones.clear();
    let Some((slot, _)) = op.kind.checked_sub(2).and_then(|k| op.models.get(k)) else {
        return;
    };
    let doc = &ctx.editor.doc;
    let names = doc
        .pmm
        .models
        .iter()
        .find(|m| m.slot == *slot)
        .map(|m| &m.bone_names);
    op.bones = doc
        .accessory_parent_bones(*slot)
        .into_iter()
        .map(|b| {
            let name = names
                .and_then(|n| n.get(b as usize))
                .map_or_else(String::new, |n| n.text.clone());
            (b, name)
        })
        .collect();
}

/// `SyncSelectAttachCombo`: the combos show the record of the selector, and the readout follows.
fn op_sync(ctx: &Ctx, f: &mut Form) {
    let op = &mut f.op;
    op.bone = 0;
    match op
        .links
        .get(op.selector)
        .copied()
        .unwrap_or(OutsideParent::None)
    {
        OutsideParent::None => op.kind = 0,
        OutsideParent::Ground => op.kind = 1,
        OutsideParent::Bone { model, bone } => {
            op.kind = op
                .models
                .iter()
                .position(|(s, _)| *s == model)
                .map_or(0, |k| k + 2);
            op_bones(ctx, op);
            op.bone = op.bones.iter().position(|(b, _)| *b == bone).unwrap_or(0);
        }
    }
    op_bones(ctx, op);
    op_refresh(ctx, f);
}

/// `RebuildTargetBoneList` after the target combo changed: the record takes the target and
/// bone 0.
fn op_set_kind(ctx: &Ctx, f: &mut Form, kind: usize) {
    let op = &mut f.op;
    op.kind = kind;
    op.bone = 0;
    let record = match kind.checked_sub(2).and_then(|k| op.models.get(k)) {
        None if kind == 0 => OutsideParent::None,
        None => OutsideParent::Ground,
        Some(&(model, _)) => OutsideParent::Bone { model, bone: 0 },
    };
    if let Some(r) = op.links.get_mut(op.selector) {
        *r = record;
    }
    op_bones(ctx, op);
    op_refresh(ctx, f);
}

/// `CommitTargetBonePick`.
fn op_set_bone(ctx: &Ctx, f: &mut Form, pick: usize) {
    let op = &mut f.op;
    op.bone = pick;
    if let (Some(&(model, _)), Some(&(bone, _))) = (
        op.kind.checked_sub(2).and_then(|k| op.models.get(k)),
        op.bones.get(pick),
    ) {
        if let Some(r) = op.links.get_mut(op.selector) {
            *r = OutsideParent::Bone { model, bone };
        }
    }
    op_refresh(ctx, f);
}

fn op_set_selector(ctx: &Ctx, f: &mut Form, selector: usize) {
    f.op.selector = selector;
    op_sync(ctx, f);
}

/// Buttons 671 and 670: the previous and the next selector, not past the ends.
fn op_step(ctx: &Ctx, f: &mut Form, forward: bool) {
    let cur = f.op.selector;
    let to = if forward {
        Some(cur + 1).filter(|&n| n < f.op.selectors.len())
    } else {
        cur.checked_sub(1)
    };
    if let Some(to) = to {
        op_set_selector(ctx, f, to);
    }
}

/// `RefreshSelectNavDisplay` (`dialog_select_ops.cpp:485`): the relative position and rotation
/// of the selector bone under the record, `"%f"`, or `------` for the root. They are the pose
/// that button 630 would give the bone, which the document computes on a copy of itself.
fn op_refresh(ctx: &Ctx, f: &mut Form) {
    let op = &f.op;
    let none = || vec!["------".to_string(); 6];
    f.t = match op.selector {
        0 => none(),
        s => {
            let mut doc = ctx.editor.doc.clone();
            let cmd = Command::ApplyOutsideParent {
                selector: s as u32,
                parent: op.links.get(s).copied().unwrap_or(OutsideParent::None),
            };
            let pose = doc.apply(cmd).ok().and_then(|()| {
                let m = doc.selected_model()?;
                let b = usize::try_from(*m.selector_bones.get(s)?).ok()?;
                m.bone_pose.get(b).cloned()
            });
            match pose {
                None => none(),
                Some(p) => {
                    let r = euler_degrees(p.rotation);
                    [
                        p.translation[0],
                        p.translation[1],
                        p.translation[2],
                        r[0],
                        r[1],
                        r[2],
                    ]
                    .iter()
                    .map(|v| format!("{v:.6}"))
                    .collect()
                }
            }
        }
    };
}

fn op_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let (mut selector, mut step, mut kind, mut bone) = (None, None, None, None);
    let (mut apply, mut register) = (false, false);
    let op = f.op.clone();
    ui.group(|ui| {
        ui.label(tr(en, "外部親設定", "outside parent setting"));
        ui.horizontal(|ui| {
            ui.label(tr(en, "対象ボーン", "subject bone"));
            if ui.button("<").clicked() {
                step = Some(false);
            }
            selector = combo_box(
                ui,
                "mds.dialog.op.selector",
                &op.selectors,
                op.selector,
                120.0,
            );
            if ui.button(">").clicked() {
                step = Some(true);
            }
        });
        ui.horizontal(|ui| {
            ui.vertical(|ui| {
                ui.label(tr(en, "外部親モデル", "target model"));
                let mut items = vec![
                    tr(en, "なし", "non").to_string(),
                    tr(en, "地面", "ground").to_string(),
                ];
                items.extend(op.models.iter().map(|(_, t)| t.clone()));
                kind = combo_box(ui, "mds.dialog.op.kind", &items, op.kind, 120.0);
            });
            ui.vertical(|ui| {
                ui.label(tr(en, "外部親ボーン", "target bone"));
                let mut items = names(&op.bones);
                if items.is_empty() {
                    items.push("------".into());
                }
                bone = combo_box(ui, "mds.dialog.op.bone", &items, op.bone, 120.0);
            });
        });
        register = ui.button(tr(en, "外親登録", "OP register")).clicked();
    });
    ui.group(|ui| {
        ui.label(tr(
            en,
            "対象ボーンの相対位置角度(自動計算)",
            "subject bone relative place(auto calculated)",
        ));
        let labels = [
            tr(en, "位置  X", "place X"),
            "Y",
            "Z",
            tr(en, "回転  X", "rot    X"),
            "Y",
            "Z",
        ];
        egui::Grid::new("mds.dialog.op.readout").show(ui, |ui| {
            for (i, label) in labels.iter().enumerate() {
                ui.label(*label);
                let mut shown = f.t[i].clone();
                ui.add(
                    egui::TextEdit::singleline(&mut shown)
                        .desired_width(70.0)
                        .interactive(false),
                );
                if i % 3 == 2 {
                    ui.end_row();
                }
            }
        });
        let enabled = op.selector != 0;
        apply = ui
            .add_enabled(
                enabled,
                egui::Button::new(tr(en, "ﾌﾚｰﾑ登録", "frame register")),
            )
            .clicked();
    });
    if let Some(s) = selector {
        op_set_selector(ctx, f, s);
    }
    if let Some(forward) = step {
        op_step(ctx, f, forward);
    }
    if let Some(k) = kind {
        op_set_kind(ctx, f, k);
    }
    if let Some(b) = bone {
        op_set_bone(ctx, f, b);
    }
    if apply {
        if let Err(e) = op_apply(ctx, f) {
            *ctx.status = e;
        }
    }
    if register {
        if let Err(e) = op_register(ctx, f) {
            *ctx.status = e;
        }
    }
    Done::Open
}

/// Button 630, `ApplyBoneAttach`: the bone of the selector takes the pose under its record.
fn op_apply(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let s = f.op.selector;
    let parent = *f.op.links.get(s).ok_or("no such selector")?;
    apply_cpp(
        ctx,
        Command::ApplyOutsideParent {
            selector: s as u32,
            parent,
        },
    )
}

/// Button 632, `ResetModelSelection`: the records become a display key.
fn op_register(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    apply_cpp(ctx, Command::RegisterOutsideParents(f.op.links.clone()))
}

/// The dialog ends with Cancel, Esc and the close button alike (`EndDialog(IDOK)`,
/// `dialog_procs.cpp:116`), and the caller marks the scene modified and seeks if 630 or 632 ran.
fn op_close(ctx: &mut Ctx, _: &Form) {
    if let Err(e) = apply_cpp(ctx, Command::CloseOutsideParentDialog) {
        *ctx.status = e;
    }
}

/// Which combo of the outside parent dialog a seam picks in.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpCombo {
    /// 669, the selector bone.
    Selector,
    /// 673, the target: 0 none, 1 ground, 2 and up the models in calculation order.
    Target,
    /// 677, the target bone.
    Bone,
}

/// Picks entry `n` of a combo of the open outside parent dialog.
pub fn op_pick(ctx: &mut Ctx, combo: OpCombo, n: usize) -> Result<(), String> {
    with_form(ctx, "IDD_OUTSIDE_PARENT", |c, f| {
        match combo {
            OpCombo::Selector if n < f.op.selectors.len() => op_set_selector(c, f, n),
            OpCombo::Target if n < f.op.models.len() + 2 => op_set_kind(c, f, n),
            OpCombo::Bone if n < f.op.bones.len() => op_set_bone(c, f, n),
            _ => return Err("no such entry".to_string()),
        }
        Ok(())
    })?
}

/// Buttons 671 and 670.
pub fn op_step_selector(ctx: &mut Ctx, forward: bool) -> Result<(), String> {
    with_form(ctx, "IDD_OUTSIDE_PARENT", |c, f| op_step(c, f, forward))
}

/// Button 630.
pub fn op_apply_pose(ctx: &mut Ctx) -> Result<(), String> {
    let (_, _, f) = open_form(ctx)?;
    op_apply(ctx, &f)
}

/// Button 632.
pub fn op_register_records(ctx: &mut Ctx) -> Result<(), String> {
    let (_, _, f) = open_form(ctx)?;
    op_register(ctx, &f)
}

/// The record of selector `n` in the open outside parent dialog.
pub fn op_record(ctx: &Ctx, n: usize) -> Option<OutsideParent> {
    open_form(ctx).ok()?.2.op.links.get(n).copied()
}

// ---- 259: English names ---------------------------------------------------------------------

/// The English section of the selected PMD (`Pmd::extension`), which holds the names of the bones,
/// morphs and bone groups the dialog edits.
fn english_section<'a>(ctx: &'a Ctx<'_>) -> Option<&'a mds_formats::pmd::English> {
    let i = model_panel::selected_index(&ctx.editor.doc)?;
    match ctx.editor.doc.models.get(i)? {
        ModelFile::Pmd(p) => p.extension.as_ref()?.english.as_ref(),
        _ => None,
    }
}

/// `InitEnglishNameDialog` (`english_name_dialog.cpp:189`): the model name and comment, the
/// first bone, morph and group, the cursors at 0. The comment's line breaks are `\n`.
fn names_init(ctx: &Ctx) -> Form {
    let Some(i) = model_panel::selected_index(&ctx.editor.doc) else {
        return Form::default();
    };
    let name = ctx.editor.doc.pmm.models[i].name_en.text.clone();
    let e = english_section(ctx);
    let text = |v: Option<&FixedSjis<20>>| v.map_or_else(String::new, |n| n.text.clone());
    let comment = e
        .map(|e| e.comment.text.replace("\r\n", "\n").replace('\r', "\n"))
        .unwrap_or_default();
    Form {
        t: vec![
            name,
            comment,
            text(e.and_then(|e| e.bone_names.first())),
            text(e.and_then(|e| e.morph_names.first())),
            e.and_then(|e| e.group_names.first())
                .map_or_else(String::new, |n| n.text.clone()),
        ],
        ..Form::default()
    }
}

/// The names of the three combos: bones, morphs from the second, groups.
fn names_lists(ctx: &Ctx) -> [Vec<String>; 3] {
    let Some(e) = english_section(ctx) else {
        return Default::default();
    };
    [
        e.bone_names.iter().map(|n| n.text.clone()).collect(),
        e.morph_names.iter().map(|n| n.text.clone()).collect(),
        e.group_names.iter().map(|n| n.text.clone()).collect(),
    ]
}

/// `CollectEnglishNameEdit` for one box: 0 the model name, 1 the comment, 2 the bone, 3 the morph
/// and 4 the group at the cursor of its combo. The edits the PMD cannot hold are not sent.
fn names_commit(ctx: &mut Ctx, f: &Form, which: usize) {
    let lists = names_lists(ctx);
    let (name, count) = match which {
        0 => (EnglishName::Model, 1),
        1 => (
            EnglishName::Comment,
            usize::from(english_section(ctx).is_some()),
        ),
        2 => (EnglishName::Bone(f.cursors[0] as u32), lists[0].len()),
        3 => (EnglishName::Morph(f.cursors[1] as u32 + 1), lists[1].len()),
        _ => (EnglishName::Group(f.cursors[2] as u32), lists[2].len()),
    };
    if count == 0 {
        return;
    }
    let cmd = Command::SetEnglishName {
        name,
        text: f.t[which].clone(),
    };
    if let Err(e) = apply_cpp(ctx, cmd) {
        *ctx.status = e;
    }
}

/// `ApplyEnglishNameDialog` (`english_name_dialog.cpp:325`): the comment, then the four names.
fn names_commit_all(ctx: &mut Ctx, f: &Form) {
    for which in [1, 0, 2, 3, 4] {
        names_commit(ctx, f, which);
    }
}

/// The reminder after OK of the dialogs that edit a model for "save enhanced model"
/// (`kMsgEnhanceModelJp` and the English text).
fn preserve_notice(ctx: &Ctx) -> &'static str {
    tr(
        en_ui(ctx),
        "編集結果は'拡張モデル保存'で新しいモデルとして保存して下さい",
        "Please preserve the edit result as a new model by 'save enhanced model'.",
    )
}

/// OK closes like Cancel (both apply), then the reminder.
fn ok_names(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    names_commit_all(ctx, f);
    *ctx.status = preserve_notice(ctx).into();
    Ok(())
}

fn cancel_names(ctx: &mut Ctx, f: &Form) {
    if model_bound(ctx) {
        names_commit_all(ctx, f);
    }
}

/// A combo of the dialog moved to entry `to` (`SelectEnglishNameBone`, `Morph`, `Group`): the
/// box of the old entry is committed first, then the box shows the new name.
fn names_pick(ctx: &mut Ctx, f: &mut Form, combo: usize, to: usize) {
    let lists = names_lists(ctx);
    if to >= lists[combo].len() {
        return;
    }
    names_commit(ctx, f, 2 + combo);
    f.cursors[combo] = to;
    f.t[2 + combo] = names_lists(ctx)[combo][to].clone();
}

/// Buttons "<" and ">" of a combo, wrapping around.
fn names_step(ctx: &mut Ctx, f: &mut Form, combo: usize, forward: bool) {
    let count = names_lists(ctx)[combo].len();
    if count == 0 {
        return;
    }
    let cur = f.cursors[combo];
    let to = match forward {
        true if cur + 1 >= count => 0,
        true => cur + 1,
        false if cur == 0 => count - 1,
        false => cur - 1,
    };
    names_pick(ctx, f, combo, to);
}

fn names_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let lists = names_lists(ctx);
    let (mut commit, mut pick, mut step) = (Vec::new(), None, None);
    let fresh = f.fresh;
    ui.horizontal(|ui| {
        ui.label(tr(en, "モデル名", "Model Name"));
        let r = ui.add(
            egui::TextEdit::singleline(&mut f.t[0])
                .desired_width(120.0)
                .hint_text(""),
        );
        if fresh {
            r.request_focus();
        }
        if r.lost_focus() && ui.input(|i| i.key_pressed(Key::Enter)) {
            commit.push(0);
        }
    });
    ui.horizontal(|ui| {
        ui.label(tr(en, "モデル情報", "Model Info"));
        ui.add(
            egui::TextEdit::multiline(&mut f.t[1])
                .desired_width(240.0)
                .desired_rows(4),
        );
    });
    let groups = [
        (tr(en, "ボーン名", "Bone Name"), 2usize),
        (tr(en, "表情名", "Facial Name"), 3),
        (tr(en, "区分名", "Division Name"), 4),
    ];
    for (combo, (title, text)) in groups.into_iter().enumerate() {
        ui.group(|ui| {
            ui.label(title);
            ui.horizontal(|ui| {
                let enabled = !lists[combo].is_empty();
                ui.add_enabled_ui(enabled, |ui| {
                    if let Some(n) = combo_box(
                        ui,
                        &format!("mds.dialog.names.{combo}"),
                        &lists[combo],
                        f.cursors[combo],
                        110.0,
                    ) {
                        pick = Some((combo, n));
                    }
                    if ui.button("<").clicked() {
                        step = Some((combo, false));
                    }
                    if ui.button(">").clicked() {
                        step = Some((combo, true));
                    }
                    let r = ui.add(egui::TextEdit::singleline(&mut f.t[text]).desired_width(120.0));
                    if r.lost_focus() && ui.input(|i| i.key_pressed(Key::Enter)) {
                        commit.push(text);
                    }
                });
            });
        });
    }
    for which in commit {
        names_commit(ctx, f, which);
    }
    if let Some((combo, n)) = pick {
        names_pick(ctx, f, combo, n);
    }
    if let Some((combo, forward)) = step {
        names_step(ctx, f, combo, forward);
    }
    if ui.button("OK").clicked() {
        return Done::Ok;
    }
    Done::Open
}

/// Picks entry `n` of the bone (0), morph (1) or group (2) combo of the open dialog.
pub fn names_select(ctx: &mut Ctx, combo: usize, n: usize) -> Result<(), String> {
    with_form(ctx, "IDD_ENGLISH_NAMES", |c, f| names_pick(c, f, combo, n))
}

/// The "<" (`forward` false) and ">" buttons of a combo.
pub fn names_move(ctx: &mut Ctx, combo: usize, forward: bool) -> Result<(), String> {
    with_form(ctx, "IDD_ENGLISH_NAMES", |c, f| {
        names_step(c, f, combo, forward)
    })
}

/// Enter in box `which` (0 model name, 2 bone, 3 morph, 4 group) of the open dialog.
pub fn names_enter(ctx: &mut Ctx, which: usize) -> Result<(), String> {
    with_form(ctx, "IDD_ENGLISH_NAMES", |c, f| names_commit(c, f, which))
}

// ---- 261: toon textures ---------------------------------------------------------------------

/// The ten toon file names of the selected model (`FillToonTextureEdits`): those of a PMD, else the
/// defaults `toon01.bmp` to `toon10.bmp`.
fn toon_names(ctx: &Ctx) -> Vec<String> {
    let model =
        model_panel::selected_index(&ctx.editor.doc).and_then(|i| ctx.editor.doc.models.get(i));
    let pmd = match model {
        Some(ModelFile::Pmd(p)) => p.extension.as_ref(),
        _ => None,
    };
    (0..10)
        .map(|i| match pmd {
            Some(x) => x.toon_textures[i].text.clone(),
            None => format!("toon{:02}.bmp", i + 1),
        })
        .collect()
}

fn toon_init(ctx: &Ctx) -> Form {
    Form {
        t: toon_names(ctx),
        ..Form::default()
    }
}

fn toon_body(ui: &mut egui::Ui, _: &mut Ctx, f: &mut Form, en: bool) -> Done {
    let fresh = f.fresh;
    ui.horizontal(|ui| {
        for column in 0..2 {
            ui.vertical(|ui| {
                for row in 0..5 {
                    let i = column * 5 + row;
                    ui.horizontal(|ui| {
                        ui.label(format!("{}{:02}", tr(en, "ﾄｩｰﾝ", "tex"), i + 1));
                        edit(ui, &mut f.t[i], 90.0, fresh && i == 0);
                    });
                }
            });
        }
    });
    ok_cancel(ui, en)
}

/// The folder of the selected model's file: toon files are looked for there.
fn model_folder(ctx: &Ctx) -> std::path::PathBuf {
    let dir = ctx
        .editor
        .path
        .as_deref()
        .and_then(std::path::Path::parent)
        .map_or_else(
            || std::path::PathBuf::from("."),
            std::path::Path::to_path_buf,
        );
    let stored = model_panel::selected_index(&ctx.editor.doc)
        .map(|i| ctx.editor.doc.pmm.models[i].path.text.clone())
        .unwrap_or_default();
    crate::scene::resolve(&dir, &stored)
        .parent()
        .map_or(dir, std::path::Path::to_path_buf)
}

/// `CollectToonFileNames` (`enhance_model_io.cpp:57`): a name equal to its default is taken as
/// it is, another must name a file beside the model, or a box says so, the name is not stored
/// and the dialog closes without the reminder (`EndDialog(IDCANCEL)`). The names that were
/// found are stored.
fn ok_toon(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let (folder, old, en) = (model_folder(ctx), toon_names(ctx), en_ui(ctx));
    let mut missing = Vec::new();
    let mut names = Vec::new();
    for (i, typed) in f.t.iter().enumerate() {
        let name = window_text(typed, 256).to_string();
        let default = format!("toon{:02}.bmp", i + 1);
        if name == default || (!name.is_empty() && folder.join(name.replace('\\', "/")).is_file()) {
            names.push(name);
        } else {
            names.push(old[i].clone());
            missing.push(name);
        }
    }
    apply_cpp(ctx, Command::SetToonFileNames(names))?;
    *ctx.status = match missing.last() {
        None => preserve_notice(ctx).into(),
        Some(name) if en => format!(
            "Cannot find '{name}'.\n\nPlease put '{name}' in the same folder as model file (*.pmd)."
        ),
        Some(name) => format!(
            "トゥーンテクスチャ:{name}が見つかりません。\n\n{name}をモデルファイル(*.pmd)と同じフォルダ内に置いてください。"
        ),
    };
    Ok(())
}

// ---- 262: the physics model -----------------------------------------------------------------

/// `kPiF` and the truncated pi (`3.141592f`) the edits show degrees with.
const PI_F: f32 = std::f32::consts::PI;
#[allow(clippy::approx_constant)]
const PI_SHORT: f32 = 3.141592;

// The edit boxes of `Form::t`, in the order of the C++ records: the body page, then the joint page.
const B_NAME: usize = 0;
const B_SIZE: usize = 1;
const B_POS: usize = 4;
const B_ROT: usize = 7;
const B_MASS: usize = 10;
const B_GROUPS: usize = 11;
const B_LIN: usize = 12;
const B_ANG: usize = 13;
const B_REST: usize = 14;
const B_FRIC: usize = 15;
const J_NAME: usize = 16;
const J_POS: usize = 17;
const J_ROT: usize = 20;
const J_LIN_UP: usize = 23;
const J_LIN_LO: usize = 26;
const J_ANG_UP: usize = 29;
const J_ANG_LO: usize = 32;
const J_SPR_LIN: usize = 35;
const J_SPR_ANG: usize = 38;
const PH_TEXTS: usize = 41;

/// The state of the physics model dialog (`PhysicsModelDlgProc`, `physics_model_dialog.cpp:1259`)
/// beside its boxes: the selected body and joint, the page, and the records the boxes were last
/// filled from or read into (a drag in the viewport changes the record behind them), and the
/// copy buffers.
#[derive(Clone, Debug, Default)]
struct Phys {
    body: Option<usize>,
    joint: Option<usize>,
    joint_page: bool,
    shown: (Option<Rigid>, Option<Joint>),
    copied: (Option<Rigid>, Option<Joint>),
}

type Scratch = (Vec<Rigid>, Vec<Joint>);

fn scratch<'a>(ctx: &'a mut Ctx<'_>) -> Result<&'a mut Scratch, String> {
    ctx.editor
        .doc
        .edit
        .physics_scratch
        .as_mut()
        .ok_or_else(|| "the physics model dialog is closed".into())
}

/// The rigid bodies and joints of the selected PMD; a PMX model has none to edit.
fn physics_source(ctx: &Ctx) -> Result<Scratch, String> {
    let i = bound_model(ctx)?;
    match ctx.editor.doc.models.get(i) {
        Some(ModelFile::Pmd(p)) => Ok(p
            .extension
            .as_ref()
            .and_then(|x| x.physics.as_ref())
            .map(|p| (p.rigids.clone(), p.joints.clone().unwrap_or_default()))
            .unwrap_or_default()),
        _ => Err("the physics model needs a PMD model".into()),
    }
}

/// `InitPhysicsModelDialog`: the scratch copy of the model's records, which the dialog and the
/// viewport edit (`EditState::physics_scratch`). A dialog opened without it makes it here.
fn physics_ensure(ctx: &mut Ctx) -> Result<(), String> {
    if ctx.editor.doc.edit.physics_scratch.is_none() {
        ctx.editor.doc.edit.physics_scratch = Some(physics_source(ctx)?);
    }
    Ok(())
}

fn physics_init(ctx: &Ctx) -> Form {
    let (rigids, joints) = physics_source(ctx).unwrap_or_default();
    let mut f = Form {
        t: vec![String::new(); PH_TEXTS],
        c: vec![false],
        ..Form::default()
    };
    f.ph.body = (!rigids.is_empty()).then_some(0);
    f.ph.joint = (!joints.is_empty()).then_some(0);
    match rigids.first() {
        Some(r) => show_body(&mut f, r),
        None => clear_body(&mut f),
    }
    match joints.first() {
        Some(j) => show_joint(&mut f, j),
        None => clear_joint(&mut f),
    }
    f
}

fn fmt(v: f32, width: usize, precision: usize) -> String {
    format!("{v:width$.precision$}")
}

/// `UpdateShapeControls`: the size boxes of the shape (radius; width, height, depth; radius,
/// height) from the record; the others keep their text.
fn show_size(f: &mut Form, r: &Rigid) {
    for a in 0..[1, 3, 2][usize::from(r.shape).min(2)] {
        f.t[B_SIZE + a] = fmt(r.size[a], 3, 2);
    }
}

/// `ApplyBodyRecordToEdits`.
fn show_body(f: &mut Form, r: &Rigid) {
    f.t[B_NAME] = r.name.text.clone();
    show_size(f, r);
    for a in 0..3 {
        f.t[B_POS + a] = fmt(r.position[a], 3, 2);
        f.t[B_ROT + a] = fmt(r.rotation[a] / PI_SHORT * 180.0, 3, 2);
    }
    f.t[B_MASS] = fmt(r.mass, 4, 3);
    f.t[B_LIN] = fmt(r.linear_damping, 4, 3);
    f.t[B_ANG] = fmt(r.angular_damping, 4, 3);
    f.t[B_REST] = fmt(r.restitution, 4, 3);
    f.t[B_FRIC] = fmt(r.friction, 4, 3);
    // The group list shows the groups the body collides with: the bits the mask does not set.
    f.t[B_GROUPS] = (0..16)
        .filter(|bit| !r.mask & (1 << bit) != 0)
        .map(|bit| format!("{} ", bit + 1))
        .collect();
    f.c[0] = r.mode == 2;
    f.ph.shown.0 = Some(r.clone());
}

/// `ApplyBodyRecordToEdits(-1)`: the boxes are emptied.
fn clear_body(f: &mut Form) {
    f.t[B_NAME].clear();
    f.t[B_SIZE].clear();
    for i in B_POS..=B_FRIC {
        f.t[i].clear();
    }
    f.c[0] = false;
    f.ph.shown.0 = None;
}

/// `ApplyJointRecordToEdits`.
fn show_joint(f: &mut Form, j: &Joint) {
    f.t[J_NAME] = j.name.text.clone();
    let deg = |v: f32| fmt(v / PI_SHORT * 180.0, 3, 2);
    for a in 0..3 {
        f.t[J_POS + a] = fmt(j.position[a], 5, 4);
        f.t[J_ROT + a] = deg(j.rotation[a]);
        f.t[J_LIN_UP + a] = fmt(j.translation_max[a], 3, 2);
        f.t[J_LIN_LO + a] = fmt(j.translation_min[a], 3, 2);
        f.t[J_ANG_UP + a] = deg(j.rotation_max[a]);
        f.t[J_ANG_LO + a] = deg(j.rotation_min[a]);
        f.t[J_SPR_LIN + a] = fmt(j.spring_translation[a], 3, 2);
        f.t[J_SPR_ANG + a] = fmt(j.spring_rotation[a], 3, 2);
    }
    f.ph.shown.1 = Some(j.clone());
}

fn clear_joint(f: &mut Form) {
    for i in J_POS..PH_TEXTS {
        f.t[i].clear();
    }
    f.ph.shown.1 = None;
}

/// `ReadEditFloat`, `ReadEditFloatClamped` (a value under 0.1 is written back as `0.1`) and
/// `ReadEditDegrees` (`float / 180.0f * kPiF`).
fn read_float(text: &str) -> f32 {
    atof(window_text(text, 256)) as f32
}

fn read_clamped(text: &mut String) -> f32 {
    if atof(window_text(text, 256)) < 0.1 {
        *text = "0.1".into();
    }
    read_float(text)
}

fn read_degrees(text: &str) -> f32 {
    read_float(text) / 180.0 * PI_F
}

/// `CheckYAngleLimit`: the y angle limits stay inside -90 to 90, else a box says so and the value
/// becomes 80 or -80. The value in radians (`/ 180.0f * 3.141592f`) and the message.
fn read_y_limit(text: &mut String, size: usize, en: bool) -> (f32, Option<&'static str>) {
    let mut value = atof(window_text(text, size)) as f32;
    let mut message = None;
    if value <= -90.0 || value >= 90.0 {
        message = Some(tr(
            en,
            "Bulletの仕様上、y軸の角度制限は-90<y<90の間しか設定できません",
            "y-axis limit must between -90 to 90",
        ));
        (value, *text) = if value > -90.0 {
            (80.0, "80.00".into())
        } else {
            (-80.0, "-80.00".into())
        };
    }
    (value / 180.0 * PI_SHORT, message)
}

/// A name box into a `FixedSjis`: `sprintf_s` / `strcpy_s` of the typed text, cut to the buffer
/// (the rest of the buffer keeps its bytes). There is no Shift-JIS encoder in this crate, so a
/// changed name has to be ASCII.
fn set_name<const N: usize>(name: &mut FixedSjis<N>, typed: &str) -> Result<(), String> {
    let typed = window_text(typed, 100);
    if name.text == typed {
        return Ok(());
    }
    if !typed.is_ascii() {
        return Err(
            "a name that is not ASCII needs a Shift-JIS encoder (not available here)".into(),
        );
    }
    let bytes = &typed.as_bytes()[..typed.len().min(N - 1)];
    name.raw[..bytes.len()].copy_from_slice(bytes);
    name.raw[bytes.len()] = 0;
    name.text = decode_sjis(&name.raw);
    Ok(())
}

/// One body box read into the record, as `CollectBodyEdits` (all of them, in order) and the
/// edit subclass on Enter (`enter`: the mass is clamped too) do.
fn read_body_box(r: &mut Rigid, f: &mut Form, i: usize, enter: bool) -> Result<(), String> {
    let a = |base: usize| i - base;
    match i {
        B_NAME => return set_name(&mut r.name, &f.t[i].clone()),
        i if (B_SIZE..B_POS).contains(&i) => r.size[a(B_SIZE)] = read_clamped(&mut f.t[i]),
        i if (B_POS..B_ROT).contains(&i) => r.position[a(B_POS)] = read_float(&f.t[i]),
        i if (B_ROT..B_MASS).contains(&i) => r.rotation[a(B_ROT)] = read_degrees(&f.t[i]),
        B_MASS if enter => r.mass = read_clamped(&mut f.t[i]),
        B_MASS => r.mass = read_float(&f.t[i]),
        B_GROUPS => r.mask = !mask_of(&f.t[i]),
        B_LIN => r.linear_damping = read_float(&f.t[i]),
        B_ANG => r.angular_damping = read_float(&f.t[i]),
        B_REST => r.restitution = read_float(&f.t[i]),
        B_FRIC => r.friction = read_float(&f.t[i]),
        _ => {}
    }
    Ok(())
}

/// The group list ("1 5 9 ") as the collision mask, bit `N - 1` for group `N`.
fn mask_of(text: &str) -> u16 {
    window_text(text, 100)
        .split(' ')
        .map(|t| atol(t) - 1)
        .filter(|bit| (0..=15).contains(bit))
        .fold(0, |mask, bit| mask | 1 << bit)
}

/// `CollectBodyEdits`.
fn collect_body(f: &mut Form, r: &mut Rigid) -> Result<(), String> {
    let mut result = Ok(());
    for i in B_NAME..=B_FRIC {
        let one = read_body_box(r, f, i, false);
        result = result.and(one);
    }
    result
}

/// One joint box read into the record (`CollectJointEdits`, and Enter in the box). The y angle
/// limits are checked; the message goes to `notes`.
fn read_joint_box(
    j: &mut Joint,
    f: &mut Form,
    i: usize,
    enter: bool,
    en: bool,
    notes: &mut Vec<&'static str>,
) -> Result<(), String> {
    let (a, size) = (|base: usize| i - base, if enter { 256 } else { 10 });
    let mut y = |slot: &mut f32, text: &mut String| {
        let (v, note) = read_y_limit(text, size, en);
        *slot = v;
        notes.extend(note);
    };
    match i {
        J_NAME => return set_name(&mut j.name, &f.t[i].clone()),
        i if (J_POS..J_ROT).contains(&i) => j.position[a(J_POS)] = read_float(&f.t[i]),
        i if (J_ROT..J_LIN_UP).contains(&i) => j.rotation[a(J_ROT)] = read_degrees(&f.t[i]),
        i if (J_LIN_UP..J_LIN_LO).contains(&i) => {
            j.translation_max[a(J_LIN_UP)] = read_float(&f.t[i])
        }
        i if (J_LIN_LO..J_ANG_UP).contains(&i) => {
            j.translation_min[a(J_LIN_LO)] = read_float(&f.t[i])
        }
        J_ANG_UP | 31 => j.rotation_max[a(J_ANG_UP)] = read_degrees(&f.t[i]),
        30 => y(&mut j.rotation_max[1], &mut f.t[i]),
        J_ANG_LO | 34 => j.rotation_min[a(J_ANG_LO)] = read_degrees(&f.t[i]),
        33 => y(&mut j.rotation_min[1], &mut f.t[i]),
        i if (J_SPR_LIN..J_SPR_ANG).contains(&i) => {
            j.spring_translation[a(J_SPR_LIN)] = read_float(&f.t[i])
        }
        i if (J_SPR_ANG..PH_TEXTS).contains(&i) => {
            j.spring_rotation[a(J_SPR_ANG)] = read_float(&f.t[i])
        }
        _ => {}
    }
    Ok(())
}

/// `CollectJointEdits`.
fn collect_joint(f: &mut Form, j: &mut Joint, en: bool) -> Result<Vec<&'static str>, String> {
    let mut notes = Vec::new();
    let mut result = Ok(());
    for i in J_NAME..PH_TEXTS {
        let one = read_joint_box(j, f, i, false, en, &mut notes);
        result = result.and(one);
    }
    result.map(|()| notes)
}

/// Reads the boxes of the selected body into its record.
fn physics_collect_body(ctx: &mut Ctx, f: &mut Form) -> Result<(), String> {
    let Some(i) = f.ph.body else { return Ok(()) };
    let r = scratch(ctx)?.0.get_mut(i).ok_or("no such rigid body")?;
    let result = collect_body(f, r);
    f.ph.shown.0 = Some(r.clone());
    result
}

fn physics_collect_joint(ctx: &mut Ctx, f: &mut Form) -> Result<(), String> {
    let (Some(i), en) = (f.ph.joint, en_ui(ctx)) else {
        return Ok(());
    };
    let j = scratch(ctx)?.1.get_mut(i).ok_or("no such joint")?;
    let result = collect_joint(f, j, en);
    f.ph.shown.1 = Some(j.clone());
    let notes = result?;
    if let Some(note) = notes.last() {
        *ctx.status = (*note).into();
    }
    Ok(())
}

/// Enter in a box (`PhysicsEditSubclassProc`): that box alone is read into the record.
fn physics_enter(ctx: &mut Ctx, f: &mut Form, i: usize) -> Result<(), String> {
    let en = en_ui(ctx);
    if i < J_NAME {
        let Some(b) = f.ph.body else { return Ok(()) };
        let r = scratch(ctx)?.0.get_mut(b).ok_or("no such rigid body")?;
        let result = read_body_box(r, f, i, true);
        f.ph.shown.0 = Some(r.clone());
        return result;
    }
    let Some(b) = f.ph.joint else { return Ok(()) };
    let j = scratch(ctx)?.1.get_mut(b).ok_or("no such joint")?;
    let mut notes = Vec::new();
    let result = read_joint_box(j, f, i, true, en, &mut notes);
    f.ph.shown.1 = Some(j.clone());
    if let Some(note) = notes.last() {
        *ctx.status = (*note).into();
    }
    result
}

/// A drag in the viewport (`Command::EditPhysicsRecord`) changed the record behind the boxes:
/// they show it (the C++ echoes the value into the box).
fn physics_pull(ctx: &mut Ctx, f: &mut Form) {
    let Ok((rigids, joints)) = scratch(ctx) else {
        return;
    };
    if let Some(r) = f.ph.body.and_then(|i| rigids.get(i)) {
        if f.ph.shown.0.as_ref() != Some(r) {
            show_body(f, r);
        }
    }
    if let Some(j) = f.ph.joint.and_then(|i| joints.get(i)) {
        if f.ph.shown.1.as_ref() != Some(j) {
            show_joint(f, j);
        }
    }
}

fn body_name(r: &Rigid) -> String {
    r.name.text.clone()
}

/// The new body of `AddRigidBody`: a sphere of size 2 and mass 1 that follows bone 0, in no group
/// (`mask` is the PMD no-collapse mask, so all bits set).
fn new_body(n: usize) -> Rigid {
    let mut raw = [0u8; 20];
    let text = format!("BODY_{n}");
    raw[..text.len()].copy_from_slice(text.as_bytes());
    Rigid {
        name: FixedSjis { raw, text },
        bone: 0,
        group: 0,
        mask: 0xFFFF,
        shape: 0,
        size: [2.0; 3],
        position: [0.0; 3],
        rotation: [0.0; 3],
        mass: 1.0,
        linear_damping: 0.5,
        angular_damping: 0.5,
        restitution: 0.0,
        friction: 0.5,
        mode: 0,
    }
}

fn new_joint(n: usize) -> Joint {
    let mut raw = [0u8; 20];
    let text = format!("JOINT_{n}");
    raw[..text.len()].copy_from_slice(text.as_bytes());
    Joint {
        name: FixedSjis { raw, text },
        rigid_a: 0,
        rigid_b: 0,
        position: [0.0; 3],
        rotation: [0.0; 3],
        translation_min: [0.0; 3],
        translation_max: [0.0; 3],
        rotation_min: [0.0; 3],
        rotation_max: [0.0; 3],
        spring_translation: [0.0; 3],
        spring_rotation: [0.0; 3],
    }
}

/// The body list of the combos and the bodies a joint can name.
fn physics_names(ctx: &mut Ctx) -> (Vec<String>, Vec<String>) {
    scratch(ctx).map_or_else(
        |_| (Vec::new(), Vec::new()),
        |(r, j)| {
            (
                r.iter().map(body_name).collect(),
                j.iter().map(|j| j.name.text.clone()).collect(),
            )
        },
    )
}

/// The bones of the model, "none" first for the body's bone combo.
fn physics_bones(ctx: &Ctx) -> Vec<String> {
    let Some(i) = model_panel::selected_index(&ctx.editor.doc) else {
        return Vec::new();
    };
    match ctx.editor.doc.models.get(i) {
        Some(ModelFile::Pmd(p)) => p.bones.iter().map(|b| b.name.text.clone()).collect(),
        _ => Vec::new(),
    }
}

/// A button of the dialog, by its control id (`physics_model_dialog.cpp`): 685 and 735 add a
/// body and a joint, 706 and 737 delete them, 724, 725, 738 and 739 copy and paste, 726 to 728
/// the shape, 729 and 730 the mode radios, 731 the bone alignment box, 800 and 801 the pages.
fn physics_click(ctx: &mut Ctx, f: &mut Form, id: u32) -> Result<(), String> {
    physics_ensure(ctx)?;
    let (en, selected_body) = (en_ui(ctx), f.ph.body);
    match id {
        685 => {
            physics_collect_body(ctx, f)?;
            let rigids = &mut scratch(ctx)?.0;
            rigids.push(new_body(rigids.len()));
            f.ph.body = Some(rigids.len() - 1);
            let r = rigids.last().unwrap().clone();
            show_body(f, &r);
        }
        735 => {
            physics_collect_joint(ctx, f)?;
            let (rigids, joints) = scratch(ctx)?;
            if rigids.is_empty() {
                return Err(tr(
                    en,
                    "剛体が一つもありません\n先に剛体を追加して下さい",
                    "There is no Body.\nPlease add body first.",
                )
                .into());
            }
            joints.push(new_joint(joints.len()));
            f.ph.joint = Some(joints.len() - 1);
            let j = joints.last().unwrap().clone();
            show_joint(f, &j);
        }
        706 => {
            let (rigids, joints) = scratch(ctx)?;
            let Some(b) = selected_body.filter(|&b| b < rigids.len()) else {
                return Ok(());
            };
            rigids.remove(b);
            // The joints of the body go with it; the others name the bodies as they are now.
            joints.retain(|j| j.rigid_a as usize != b && j.rigid_b as usize != b);
            for j in joints.iter_mut() {
                for r in [&mut j.rigid_a, &mut j.rigid_b] {
                    *r -= u32::from(*r as usize > b);
                }
            }
            f.ph.body = (!rigids.is_empty()).then_some(0);
            f.ph.joint = (!joints.is_empty()).then_some(0);
            let (r, j) = (rigids.first().cloned(), joints.first().cloned());
            match r {
                Some(r) => show_body(f, &r),
                None => clear_body(f),
            }
            match j {
                Some(j) => show_joint(f, &j),
                None => clear_joint(f),
            }
        }
        737 => {
            let joints = &mut scratch(ctx)?.1;
            let Some(s) = f.ph.joint.filter(|&s| s < joints.len()) else {
                return Ok(());
            };
            joints.remove(s);
            f.ph.joint = (!joints.is_empty()).then_some(0);
            let j = joints.first().cloned();
            match j {
                Some(j) => show_joint(f, &j),
                None => clear_joint(f),
            }
        }
        724 => {
            physics_collect_body(ctx, f)?;
            f.ph.copied.0 = f.ph.body.and_then(|b| scratch(ctx).ok()?.0.get(b).cloned());
        }
        725 => {
            // The restitution, friction, name and group stay.
            let (Some(src), Some(b)) = (f.ph.copied.0.clone(), f.ph.body) else {
                return Ok(());
            };
            let r = scratch(ctx)?.0.get_mut(b).ok_or("no such rigid body")?;
            (r.bone, r.mode, r.mass) = (src.bone, src.mode, src.mass);
            (r.linear_damping, r.angular_damping) = (src.linear_damping, src.angular_damping);
            (r.position, r.rotation, r.size, r.shape) =
                (src.position, src.rotation, src.size, src.shape);
            let r = r.clone();
            show_body(f, &r);
        }
        738 => {
            physics_collect_joint(ctx, f)?;
            f.ph.copied.1 =
                f.ph.joint
                    .and_then(|s| scratch(ctx).ok()?.1.get(s).cloned());
        }
        739 => {
            let (Some(src), Some(s)) = (f.ph.copied.1.clone(), f.ph.joint) else {
                return Ok(());
            };
            let j = scratch(ctx)?.1.get_mut(s).ok_or("no such joint")?;
            (j.rigid_a, j.rigid_b, j.position, j.rotation) =
                (src.rigid_a, src.rigid_b, src.position, src.rotation);
            (j.translation_min, j.translation_max) = (src.translation_min, src.translation_max);
            (j.rotation_min, j.rotation_max) = (src.rotation_min, src.rotation_max);
            (j.spring_translation, j.spring_rotation) =
                (src.spring_translation, src.spring_rotation);
            let j = j.clone();
            show_joint(f, &j);
        }
        726..=728 => {
            let Some(b) = selected_body else {
                return Ok(());
            };
            let r = scratch(ctx)?.0.get_mut(b).ok_or("no such rigid body")?;
            r.shape = (id - 726) as u8;
            let r = r.clone();
            show_size(f, &r);
            f.ph.shown.0 = Some(r);
        }
        729..=731 => {
            let Some(b) = selected_body else {
                return Ok(());
            };
            let r = scratch(ctx)?.0.get_mut(b).ok_or("no such rigid body")?;
            r.mode = match (id, r.mode) {
                (729, _) => 1 + u8::from(f.c[0]),
                (730, _) => 0,
                (_, 2) => 1,
                (_, 1) => 2,
                (_, m) => m,
            };
            f.c[0] = r.mode == 2;
            f.ph.shown.0 = Some(r.clone());
        }
        800 => {
            physics_collect_joint(ctx, f)?;
            f.ph.joint_page = false;
        }
        801 => {
            physics_collect_body(ctx, f)?;
            f.ph.joint_page = true;
        }
        _ => return Err(format!("no button {id}")),
    }
    Ok(())
}

/// A combo of the dialog by its control id: 704 and 736 the body and joint lists (the old record
/// is read first), 741 and 742 the bodies of the joint, 707 the related bone (0 is none), 708 the
/// group and 743 the pivot bone (the joint takes its position).
fn physics_select(ctx: &mut Ctx, f: &mut Form, id: u32, n: usize) -> Result<(), String> {
    physics_ensure(ctx)?;
    match id {
        704 => {
            physics_collect_body(ctx, f)?;
            let r = scratch(ctx)?
                .0
                .get(n)
                .cloned()
                .ok_or("no such rigid body")?;
            f.ph.body = Some(n);
            show_body(f, &r);
        }
        736 => {
            physics_collect_joint(ctx, f)?;
            let j = scratch(ctx)?.1.get(n).cloned().ok_or("no such joint")?;
            f.ph.joint = Some(n);
            show_joint(f, &j);
        }
        741 | 742 => {
            let j = f.ph.joint.ok_or("no joint")?;
            let (rigids, joints) = scratch(ctx)?;
            if n >= rigids.len() {
                return Err("no such rigid body".into());
            }
            let j = joints.get_mut(j).ok_or("no such joint")?;
            *if id == 741 {
                &mut j.rigid_a
            } else {
                &mut j.rigid_b
            } = n as u32;
            f.ph.shown.1 = Some(j.clone());
        }
        707 | 708 => {
            let b = f.ph.body.ok_or("no body")?;
            let r = scratch(ctx)?.0.get_mut(b).ok_or("no such rigid body")?;
            match id {
                707 => r.bone = n as i16 - 1,
                _ => r.group = n as u8,
            }
            f.ph.shown.0 = Some(r.clone());
        }
        743 => {
            let s = f.ph.joint.ok_or("no joint")?;
            let at = match ctx.editor.doc.models.get(bound_model(ctx)?) {
                Some(ModelFile::Pmd(p)) => {
                    p.bones.get(n).map(|b| b.position).ok_or("no such bone")?
                }
                _ => return Err("no PMD model".into()),
            };
            let j = scratch(ctx)?.1.get_mut(s).ok_or("no such joint")?;
            j.position = at;
            for (a, v) in at.into_iter().enumerate() {
                f.t[J_POS + a] = fmt(v, 5, 4);
            }
            f.ph.shown.1 = Some(j.clone());
        }
        _ => return Err(format!("no combo {id}")),
    }
    Ok(())
}

/// The text index of the edit box with control id `id` (`physics_model_dialog.cpp:54`).
fn physics_box(id: u32) -> Option<usize> {
    Some(match id {
        705 => B_NAME,
        709..=711 => B_SIZE + (id - 709) as usize,
        712..=714 => B_POS + (id - 712) as usize,
        715..=717 => B_ROT + (id - 715) as usize,
        718 => B_MASS,
        719 => B_GROUPS,
        720 => B_LIN,
        721 => B_ANG,
        722 => B_REST,
        723 => B_FRIC,
        740 => J_NAME,
        744..=746 => J_POS + (id - 744) as usize,
        754..=756 => J_ROT + (id - 754) as usize,
        757 => J_LIN_UP,
        759 => J_LIN_UP + 1,
        761 => J_LIN_UP + 2,
        747 => J_LIN_LO,
        758 => J_LIN_LO + 1,
        760 => J_LIN_LO + 2,
        763 => J_ANG_UP,
        765 => J_ANG_UP + 1,
        767 => J_ANG_UP + 2,
        762 => J_ANG_LO,
        764 => J_ANG_LO + 1,
        766 => J_ANG_LO + 2,
        748..=750 => J_SPR_LIN + (id - 748) as usize,
        751..=753 => J_SPR_ANG + (id - 751) as usize,
        _ => return None,
    })
}

/// Types `text` into the edit box with control id `id` of the open physics dialog.
pub fn physics_text(ctx: &mut Ctx, id: u32, text: &str) -> Result<(), String> {
    let i = physics_box(id).ok_or_else(|| format!("no edit box {id}"))?;
    with_form(ctx, "IDD_PHYSICS_MODEL", |_, f| f.t[i] = text.to_string())
}

/// Presses the button with control id `id`; see [`physics_click`].
pub fn physics_press(ctx: &mut Ctx, id: u32) -> Result<(), String> {
    with_form(ctx, "IDD_PHYSICS_MODEL", |c, f| physics_click(c, f, id))?
}

/// Picks entry `n` of the combo with control id `id`; see [`physics_select`].
pub fn physics_pick(ctx: &mut Ctx, id: u32, n: usize) -> Result<(), String> {
    with_form(ctx, "IDD_PHYSICS_MODEL", |c, f| physics_select(c, f, id, n))?
}

/// Enter in the edit box with control id `id`.
pub fn physics_commit(ctx: &mut Ctx, id: u32) -> Result<(), String> {
    let i = physics_box(id).ok_or_else(|| format!("no edit box {id}"))?;
    with_form(ctx, "IDD_PHYSICS_MODEL", |c, f| physics_enter(c, f, i))?
}

/// The boxes of the physics dialog and what it edits, for the seams of the tests.
pub fn physics_records(ctx: &Ctx) -> Option<(usize, usize)> {
    let s = ctx.editor.doc.edit.physics_scratch.as_ref()?;
    Some((s.0.len(), s.1.len()))
}

/// OK: the records of both pages are read, the model takes the records (`CommitPhysicsEdits`),
/// the scratch copy goes, and the reminder follows. Cancel only drops the copy.
fn ok_physics_model(ctx: &mut Ctx, f: &Form) -> Result<(), String> {
    let mut f = f.clone();
    physics_ensure(ctx)?;
    physics_collect_body(ctx, &mut f)?;
    physics_collect_joint(ctx, &mut f)?;
    let (rigids, joints) = scratch(ctx)?.clone();
    apply_cpp(ctx, Command::SetPhysicsModel { rigids, joints })?;
    ctx.editor.doc.edit.physics_scratch = None;
    *ctx.status = preserve_notice(ctx).into();
    Ok(())
}

fn cancel_physics_model(ctx: &mut Ctx, _: &Form) {
    ctx.editor.doc.edit.physics_scratch = None;
}

fn physm_body(ui: &mut egui::Ui, ctx: &mut Ctx, f: &mut Form, en: bool) -> Done {
    if let Err(e) = physics_ensure(ctx) {
        ui.label(&e);
        return ok_cancel(ui, en);
    }
    physics_pull(ctx, f);
    let (bodies, joints) = physics_names(ctx);
    let bones = {
        let mut v = vec![tr(en, "なし", "none").to_string()];
        v.extend(physics_bones(ctx));
        v
    };
    let (mut clicks, mut picks, mut commits) = (Vec::new(), Vec::new(), Vec::new());
    ui.horizontal(|ui| {
        let (mut body_page, mut joint_page) = (!f.ph.joint_page, f.ph.joint_page);
        if ui.radio(body_page, tr(en, "剛体", "rigid body")).clicked() && !body_page {
            clicks.push(800);
            body_page = true;
            joint_page = false;
        }
        if ui
            .radio(joint_page, tr(en, "ジョイント", "joint"))
            .clicked()
            && !joint_page
        {
            clicks.push(801);
        }
        let _ = (body_page, joint_page);
    });
    let edit_box = |ui: &mut egui::Ui, f: &mut Form, i: usize, w: f32, commits: &mut Vec<usize>| {
        let r = ui.add(egui::TextEdit::singleline(&mut f.t[i]).desired_width(w));
        if r.lost_focus() && ui.input(|k| k.key_pressed(Key::Enter)) {
            commits.push(i);
        }
    };
    if !f.ph.joint_page {
        ui.horizontal(|ui| {
            if let Some(n) = combo_box(
                ui,
                "mds.dialog.physics.body",
                &bodies,
                f.ph.body.unwrap_or(usize::MAX),
                110.0,
            ) {
                picks.push((704, n));
            }
            for (id, label) in [
                (685, tr(en, "追加", "add")),
                (706, tr(en, "削除", "delete")),
                (724, tr(en, "コピー", "copy")),
                (725, tr(en, "ﾍﾟｰｽﾄ", "paste")),
            ] {
                if ui.button(label).clicked() {
                    clicks.push(id);
                }
            }
        });
        let Some(b) = f.ph.body else {
            return ok_cancel(ui, en);
        };
        let shape = scratch(ctx)
            .ok()
            .and_then(|s| s.0.get(b))
            .map(|r| (r.shape, r.bone, r.group));
        let (shape, bone, group) = shape.unwrap_or((0, 0, 0));
        ui.horizontal(|ui| {
            ui.label(tr(en, "名称", "name"));
            edit_box(ui, f, B_NAME, 90.0, &mut commits);
        });
        ui.horizontal(|ui| {
            ui.label(tr(en, "関連Bone", "bone"));
            if let Some(n) = combo_box(
                ui,
                "mds.dialog.physics.bone",
                &bones,
                (bone + 1).max(0) as usize,
                110.0,
            ) {
                picks.push((707, n));
            }
            let groups: Vec<String> = (1..=15)
                .map(|n| n.to_string())
                .chain(["16(F)".to_string()])
                .collect();
            ui.label(tr(en, "ｸﾞﾙｰﾌﾟ", "group"));
            if let Some(n) = combo_box(
                ui,
                "mds.dialog.physics.group",
                &groups,
                usize::from(group),
                50.0,
            ) {
                picks.push((708, n));
            }
            edit_box(ui, f, B_GROUPS, 80.0, &mut commits);
        });
        ui.horizontal(|ui| {
            for (id, label, n) in [
                (726, tr(en, "球", "sphere"), 0),
                (727, tr(en, "箱", "box"), 1),
                (728, tr(en, "カプセル", "capsule"), 2),
            ] {
                if ui.radio(shape == n, label).clicked() && shape != n {
                    clicks.push(id);
                }
            }
        });
        ui.horizontal(|ui| {
            let labels: [&str; 3] = match shape {
                0 => [tr(en, "半径", "radius"), "", ""],
                1 => [
                    tr(en, "　幅", "width"),
                    tr(en, "高さ", "height"),
                    tr(en, "奥行", "depth"),
                ],
                _ => [tr(en, "半径", "radius"), tr(en, "高さ", "height"), ""],
            };
            for (a, label) in labels.iter().enumerate().filter(|(_, l)| !l.is_empty()) {
                ui.label(*label);
                edit_box(ui, f, B_SIZE + a, 40.0, &mut commits);
            }
        });
        for (title, first) in [
            (tr(en, "位置", "position"), B_POS),
            (tr(en, "回転", "rotation"), B_ROT),
        ] {
            ui.horizontal(|ui| {
                ui.label(title);
                for a in 0..3 {
                    edit_box(ui, f, first + a, 50.0, &mut commits);
                }
            });
        }
        let mode = scratch(ctx)
            .ok()
            .and_then(|s| s.0.get(b))
            .map_or(0, |r| r.mode);
        ui.horizontal(|ui| {
            if ui.radio(mode == 0, tr(en, "Bone追従", "bone")).clicked() && mode != 0 {
                clicks.push(730);
            }
            if ui.radio(mode != 0, tr(en, "物理演算", "physics")).clicked() && mode == 0 {
                clicks.push(729);
            }
            let mut on = f.c[0];
            if ui
                .add_enabled(
                    mode != 0,
                    egui::Checkbox::new(&mut on, tr(en, "Bone位置合せ", "bone alignment")),
                )
                .clicked()
            {
                clicks.push(731);
            }
        });
        egui::Grid::new("mds.dialog.physics.params").show(ui, |ui| {
            for (label, i) in [
                (tr(en, "質量", "mass"), B_MASS),
                (tr(en, "移動減衰", "move damp"), B_LIN),
                (tr(en, "回転減衰", "rot damp"), B_ANG),
                (tr(en, "反発力", "restitution"), B_REST),
                (tr(en, "摩擦力", "friction"), B_FRIC),
            ] {
                ui.label(label);
                edit_box(ui, f, i, 60.0, &mut commits);
                ui.end_row();
            }
        });
    } else {
        ui.horizontal(|ui| {
            if let Some(n) = combo_box(
                ui,
                "mds.dialog.physics.joint",
                &joints,
                f.ph.joint.unwrap_or(usize::MAX),
                110.0,
            ) {
                picks.push((736, n));
            }
            for (id, label) in [
                (735, tr(en, "追加", "add")),
                (737, tr(en, "削除", "delete")),
                (738, tr(en, "コピー", "copy")),
                (739, tr(en, "ﾍﾟｰｽﾄ", "paste")),
            ] {
                if ui.button(label).clicked() {
                    clicks.push(id);
                }
            }
        });
        let Some(s) = f.ph.joint else {
            return ok_cancel(ui, en);
        };
        let ends = scratch(ctx)
            .ok()
            .and_then(|x| x.1.get(s))
            .map(|j| (j.rigid_a as usize, j.rigid_b as usize));
        let (a, b) = ends.unwrap_or((0, 0));
        ui.horizontal(|ui| {
            ui.label(tr(en, "名称", "name"));
            edit_box(ui, f, J_NAME, 90.0, &mut commits);
        });
        ui.horizontal(|ui| {
            ui.label(tr(en, "剛体A", "body A"));
            if let Some(n) = combo_box(ui, "mds.dialog.physics.a", &bodies, a, 90.0) {
                picks.push((741, n));
            }
            ui.label(tr(en, "剛体B", "body B"));
            if let Some(n) = combo_box(ui, "mds.dialog.physics.b", &bodies, b, 90.0) {
                picks.push((742, n));
            }
        });
        ui.horizontal(|ui| {
            ui.label(tr(en, "Boneに位置合せ", "place at bone"));
            let names: Vec<String> = bones.iter().skip(1).cloned().collect();
            if let Some(n) = combo_box(ui, "mds.dialog.physics.pivot", &names, usize::MAX, 110.0) {
                picks.push((743, n));
            }
        });
        egui::Grid::new("mds.dialog.physics.joint").show(ui, |ui| {
            for (label, first) in [
                (tr(en, "位置", "place"), J_POS),
                (tr(en, "回転", "rot"), J_ROT),
                (tr(en, "移動制限 下", "linear lower"), J_LIN_LO),
                (tr(en, "移動制限 上", "linear upper"), J_LIN_UP),
                (tr(en, "回転制限 下", "angle lower"), J_ANG_LO),
                (tr(en, "回転制限 上", "angle upper"), J_ANG_UP),
                (tr(en, "ばね移動", "spring move"), J_SPR_LIN),
                (tr(en, "ばね回転", "spring rot"), J_SPR_ANG),
            ] {
                ui.label(label);
                for k in 0..3 {
                    edit_box(ui, f, first + k, 50.0, &mut commits);
                }
                ui.end_row();
            }
        });
    }
    let mut results = Vec::new();
    for i in commits {
        results.push(physics_enter(ctx, f, i));
    }
    for (id, n) in picks {
        results.push(physics_select(ctx, f, id, n));
    }
    for id in clicks {
        results.push(physics_click(ctx, f, id));
    }
    if let Some(e) = results.into_iter().find_map(Result::err) {
        *ctx.status = e;
    }
    ok_cancel(ui, en)
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

fn abort_unless_chosen(ctx: &mut Ctx, _: &Form) {
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
