//! The `edit` area: the Edit menu, the keys I, K, U, J, F, D and R, and the dialog window the
//! bulk menus of this area, `expression` and `view` open ([`Form`]).
//!
//! Every row of the area has an action: the select-all menus (217, 218, 220, 237 to 241;
//! `SelectFrameGroup`, `src/window/frame_line_edit.cpp:540`, and
//! `src/window/command_file_menu.cpp:1964` to `:2029`), the frame-line menus and keys (255 to 258;
//! `command_view_menu.cpp:861`, `src/app/key_ladder.cpp:127` to `:141`), the rotation reset (302,
//! `command_view_menu.cpp:1864`), delete unused frames (222, `command_file_menu.cpp:1118`), the
//! center position bias (219 and D, `:1042`), the multiply menus (242 `:1940`, 251 and R, 252;
//! `command_view_menu.cpp:796` and `:814`), paste to another bone (250 and F, `:1471`) and the
//! numeric input dialog (300, `command_view_menu.cpp:1740`).
//!
//! The menus are gated by mode as the C++ grays them (`RestorePlaybackMenus`,
//! `src/app/playback_state.cpp:83`; `src/app/reset_app_state.cpp:489`): the model-mode ones in
//! camera mode, the camera-mode ones in model mode. During playback they are all grayed
//! (`DisablePlaybackMenus`, `playback_state.cpp:67`), which `needs_document` covers. The letter
//! keys D, R and (in `expression`) H do nothing in the mode their menu is grayed in, as the key
//! ladder does (`key_ladder.cpp:122`, `:304`, `:318`).
//!
//! # Dialogs
//!
//! The C++ opens a modal dialog or a message box from these menus. Here that is a [`Form`], one
//! at a time, kept in egui's memory and drawn by [`pass`]: a message, edit boxes prefilled as the
//! C++ prefills them, and OK / cancel. OK reads each edit box as the C++ does (`atof` or `atol` of
//! at most 19 characters, `GetWindowTextA` into a 20 byte buffer) and runs the area's commit
//! function, which applies the document [`Command`]. A test opens the form with the menu's
//! action, sets the boxes with [`set_text`] and presses OK with [`submit`]. The info boxes the C++
//! shows after a command (menus 222 and 227) go to the status line.
//!
//! # Menu 300
//!
//! `case MDS_CMD_NUMERIC_INPUT` fills the dialog from, and reads it back into, the temp floats
//! `RotationDialogTemp(i)`, but the C++ port keeps its own copies in locals `t0` to `t5` and writes
//! those back, so the dialog neither shows the pose nor changes it, and its roll conversions
//! (`kD2 / (kD3 * t5)`) are not the inverse of the display ones. Here the dialog is the readout
//! boxes 544 to 550 in a window (the text [`camera_panel::readout_text`] shows). In camera mode OK
//! is one [`Command::SetCameraFromMenu`] with the conversions of the readout edits (a box left
//! alone keeps the camera's exact value), and the scene is modified whatever was typed
//! (`command_view_menu.cpp:1771`). In bone mode OK commits each box that was edited through
//! [`camera_panel::set_readout`], one undo entry per edited box.

use super::camera_panel::{atof, atol, readout_text, set_readout, window_text};
use super::{button, help, Ctx};
use crate::actions::Action;
use egui::Id;
use mds_doc::{Command, SelectAll};

const ACTIONS: &[Action] = &[
    Action::run("menu:217", select_bone, true),
    Action::run("menu:218", select_display, true),
    Action::run("menu:220", select_morph, true),
    Action::run("menu:237", select_camera, true),
    Action::run("menu:238", select_light, true),
    Action::run("menu:239", select_self_shadow, true),
    Action::run("menu:240", select_gravity, true),
    Action::run("menu:241", select_accessory, true),
    Action::run("menu:255", insert_bone_camera, true),
    Action::run("menu:256", delete_bone_camera, true),
    Action::run("menu:257", insert_morph_light, true),
    Action::run("menu:258", delete_morph_light, true),
    Action::run("key:I", insert_bone_camera, true),
    Action::run("key:K", delete_bone_camera, true),
    Action::run("key:U", insert_morph_light, true),
    Action::run("key:J", delete_morph_light, true),
    Action::run("menu:302", reset_rotation, true),
    Action::run("menu:300", numeric_input, true),
    Action::run("menu:222", remove_unused, true),
    Action::run("menu:219", center_bias, true),
    Action::run("key:D", key_center_bias, true),
    Action::run("menu:242", multiply_camera, true),
    Action::run("menu:251", multiply_bone, true),
    Action::run("key:R", key_multiply_bone, true),
    Action::run("menu:252", multiply_morph, true),
    Action::run("menu:250", paste_different, true),
    Action::run("key:F", paste_different, true),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn camera_mode(ctx: &Ctx) -> bool {
    ctx.editor.doc.pmm.settings.options[0] != 0
}

/// Which edit mode a menu item is enabled in.
#[derive(Clone, Copy, PartialEq)]
pub enum Mode {
    Any,
    Model,
    Camera,
}

impl Mode {
    pub fn allows(self, camera: bool) -> bool {
        match self {
            Mode::Any => true,
            Mode::Model => !camera,
            Mode::Camera => camera,
        }
    }
}

/// The gate of a menu item: `Err` in the mode the C++ grays it in.
pub fn gated(ctx: &Ctx, mode: Mode, id: &str) -> Result<(), String> {
    match mode.allows(camera_mode(ctx)) {
        true => Ok(()),
        false => Err(format!("{id}: not in this mode")),
    }
}

/// `ja` or `en` by the interface language.
pub fn localized(ctx: &Ctx, ja: String, en: String) -> String {
    match ctx.egui.as_ref().is_some_and(help::english) {
        true => en,
        false => ja,
    }
}

/// Puts the text on the status line: the info boxes of the C++.
pub fn say(ctx: &mut Ctx, ja: String, en: String) {
    *ctx.status = localized(ctx, ja, en);
}

/// `(ja, en)`.
pub type Text = (&'static str, &'static str);

/// One edit box of a [`Form`].
#[derive(Clone, Debug)]
pub struct Field {
    pub label: Text,
    pub text: String,
    /// What the box held when the form opened.
    pub initial: String,
}

impl Field {
    /// `atof` of the box (`GetWindowTextA` into 20 bytes).
    pub fn number(&self) -> f64 {
        atof(window_text(&self.text, 20))
    }

    pub fn float(&self) -> f32 {
        self.number() as f32
    }

    /// `atol` of the box.
    pub fn integer(&self) -> i32 {
        atol(window_text(&self.text, 20)) as i32
    }

    pub fn edited(&self) -> bool {
        self.text != self.initial
    }
}

/// The commit of a form: runs when OK is pressed.
pub type Commit = fn(&mut Ctx, &[Field]) -> Result<(), String>;

/// A dialog or a message box of the C++, open in the window.
#[derive(Clone)]
pub struct Form {
    pub title: Text,
    pub message: Option<Text>,
    pub fields: Vec<Field>,
    pub ok: Commit,
    /// The dialog stays open when OK fails (`ScreenSizeDlgProc` ends only on success).
    pub sticky: bool,
}

impl Form {
    pub fn new(title: Text, ok: Commit) -> Form {
        Form {
            title,
            message: None,
            fields: Vec::new(),
            ok,
            sticky: false,
        }
    }

    pub fn message(mut self, text: Text) -> Form {
        self.message = Some(text);
        self
    }

    pub fn field(mut self, label: Text, text: impl Into<String>) -> Form {
        let text = text.into();
        self.fields.push(Field {
            label,
            initial: text.clone(),
            text,
        });
        self
    }

    pub fn sticky(mut self) -> Form {
        self.sticky = true;
        self
    }
}

fn form_id() -> Id {
    Id::unique("uimenus2-form")
}

/// Opens `form`, replacing the one that is open.
pub fn open(ctx: &Ctx, form: Form) -> Result<(), String> {
    let egui = ctx.egui.as_ref().ok_or("no window")?;
    egui.data_mut(|d| d.insert_temp(form_id(), Some(form)));
    Ok(())
}

/// The form that is open.
pub fn current(egui: &egui::Context) -> Option<Form> {
    egui.data(|d| d.get_temp::<Option<Form>>(form_id()).flatten())
}

pub fn close(egui: &egui::Context) {
    egui.data_mut(|d| d.insert_temp(form_id(), None::<Form>));
}

/// Types `text` into edit box `index` of the open form.
pub fn set_text(egui: &egui::Context, index: usize, text: &str) {
    if let Some(mut form) = current(egui) {
        if let Some(f) = form.fields.get_mut(index) {
            f.text = text.to_owned();
        }
        egui.data_mut(|d| d.insert_temp(form_id(), Some(form)));
    }
}

/// OK: the commit runs and the form closes, unless the form is [`Form::sticky`] and the commit
/// failed. A form never outlives playback (the menus are grayed then).
pub fn submit(ctx: &mut Ctx) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or("no window")?;
    let form = current(&egui).ok_or("no dialog is open")?;
    close(&egui);
    if ctx.editor.playing() {
        return Err("not while playing".into());
    }
    let r = (form.ok)(ctx, &form.fields);
    if r.is_err() && form.sticky {
        egui.data_mut(|d| d.insert_temp(form_id(), Some(form)));
    }
    r
}

/// Draws the open form: a window with the message, one row per edit box, and OK and cancel.
pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let Some(egui) = ctx.egui.clone() else {
        return;
    };
    let Some(mut form) = current(&egui) else {
        return;
    };
    let pick = |t: Text| help::pick(&egui, t.0, t.1);
    let (mut ok, mut cancel) = (false, false);
    egui::Window::new(pick(form.title))
        .collapsible(false)
        .resizable(false)
        .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
        .show(ui.ctx(), |ui| {
            if let Some(m) = form.message {
                ui.label(pick(m));
            }
            egui::Grid::new("uimenus2-form-fields").show(ui, |ui| {
                for f in &mut form.fields {
                    ui.label(pick(f.label));
                    ui.add(egui::TextEdit::singleline(&mut f.text).desired_width(64.0));
                    ui.end_row();
                }
            });
            ui.horizontal(|ui| {
                ok = ui.button("OK").clicked();
                cancel = ui.button(help::pick(&egui, "ｷｬﾝｾﾙ", "cancel")).clicked();
            });
        });
    if cancel {
        close(&egui);
        return;
    }
    egui.data_mut(|d| d.insert_temp(form_id(), Some(form)));
    if ok {
        if let Err(e) = submit(ctx) {
            *ctx.status = e;
        }
    }
}

fn select(ctx: &mut Ctx, id: &str, what: SelectAll) -> Result<(), String> {
    let mode = match what {
        SelectAll::Bone | SelectAll::Display | SelectAll::Morph => Mode::Model,
        _ => Mode::Camera,
    };
    gated(ctx, mode, id)?;
    ctx.editor.apply(Command::SelectAll(what))
}

fn select_bone(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:217", SelectAll::Bone)
}

fn select_display(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:218", SelectAll::Display)
}

fn select_morph(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:220", SelectAll::Morph)
}

fn select_camera(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:237", SelectAll::Camera)
}

fn select_light(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:238", SelectAll::Light)
}

fn select_self_shadow(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:239", SelectAll::SelfShadow)
}

fn select_gravity(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:240", SelectAll::Gravity)
}

fn select_accessory(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:241", SelectAll::Accessory)
}

fn frame_line(ctx: &mut Ctx, morph: bool, insert: bool) -> Result<(), String> {
    ctx.editor.apply(Command::FrameLine { morph, insert })
}

fn insert_bone_camera(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, false, true)
}

fn delete_bone_camera(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, false, false)
}

fn insert_morph_light(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, true, true)
}

fn delete_morph_light(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, true, false)
}

/// Menu 302: the camera's pitch, yaw and roll to 0, or the selected bone's rotation to identity
/// (a bone-edit undo entry first; nothing when no bone is selected).
fn reset_rotation(ctx: &mut Ctx) -> Result<(), String> {
    let pmm = &ctx.editor.doc.pmm;
    if camera_mode(ctx) {
        let s = pmm.camera_state;
        return ctx.editor.apply(Command::SetCameraFromMenu {
            position: [s[0], s[1], s[2]],
            rotation: [0.0; 3],
            distance: s[5],
        });
    }
    let model = pmm
        .models
        .iter()
        .find(|m| m.slot == pmm.selected_model_slot)
        .ok_or("no model")?;
    let Ok(bone) = u32::try_from(model.selection.selected_bone) else {
        return Ok(());
    };
    let translation = model
        .bone_pose
        .get(bone as usize)
        .ok_or("no such bone")?
        .translation;
    ctx.editor.apply(Command::SetBonePose {
        bone,
        translation,
        rotation: [0.0, 0.0, 0.0, 1.0],
    })
}

/// The dialog's rows for menu 300: position, the three angles, and in camera mode the distance
/// (`IDD_CAMERA_NUMERIC_INPUT`, `IDD_BONE_NUMERIC_INPUT`).
const NUMERIC: [Text; 7] = [
    ("位置X", "pos X"),
    ("位置Y", "pos Y"),
    ("位置Z", "pos Z"),
    ("X軸(°)", "axis X (degree)"),
    ("Y軸(°)", "axis Y (degree)"),
    ("Z軸(°)", "axis Z (degree)"),
    ("距離", "distance"),
];

/// Menu 300 (`command_view_menu.cpp:1740`): the camera path always opens the dialog, the bone
/// path only with a selected bone (`selectedBone == -1` returns first).
fn numeric_input(ctx: &mut Ctx) -> Result<(), String> {
    let camera = camera_mode(ctx);
    if !camera {
        let selected = ctx
            .editor
            .doc
            .selected_model()
            .is_some_and(|m| m.selection.selected_bone >= 0);
        if !selected {
            return Ok(());
        }
    }
    let (title, rows) = match camera {
        true => (("数値入力(カメラ)", "numeric input(camera)"), 7),
        false => (("数値入力(ボーン)", "numeric input(bone)"), 6),
    };
    let mut form = Form::new(title, commit_numeric_input);
    for (i, label) in NUMERIC.iter().take(rows).enumerate() {
        form = form.field(*label, readout_text(ctx, i));
    }
    open(ctx, form)
}

/// `kPiLit`, the float pi of the camera edit handlers.
const PI_LIT: f64 = 3.141592025756836;

fn commit_numeric_input(ctx: &mut Ctx, fields: &[Field]) -> Result<(), String> {
    if camera_mode(ctx) {
        let s = ctx.editor.doc.pmm.camera_state;
        let flip = ctx.editor.doc.pmm.appearance.camera_parent_model >= 0;
        let pick = |i: usize, current: f32, convert: &dyn Fn(f64) -> f32| match fields.get(i) {
            Some(f) if f.edited() => convert(f.number()),
            _ => current,
        };
        let z = |v: f64| if flip { -v } else { v } as f32;
        return ctx.editor.apply(Command::SetCameraFromMenu {
            position: [
                pick(0, s[0], &|v| v as f32),
                pick(1, s[1], &|v| v as f32),
                pick(2, s[2], &z),
            ],
            rotation: [
                pick(3, s[6], &|v| (-v * PI_LIT / 180.0) as f32),
                pick(4, s[7], &|v| (v * PI_LIT / 180.0) as f32),
                pick(5, s[8], &|v| (v * PI_LIT / 180.0) as f32),
            ],
            distance: pick(6, s[5], &|v| (-v) as f32),
        });
    }
    for (i, f) in fields.iter().enumerate().filter(|(_, f)| f.edited()) {
        set_readout(ctx, i, f.number())?;
    }
    Ok(())
}

/// Menu 222 (`command_file_menu.cpp:1118`): the redundant keys of the selected model go, and the
/// box with the count is the status line.
fn remove_unused(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:222")?;
    ctx.editor.apply(Command::RemoveUnusedKeys)?;
    if let Some(n) = ctx.editor.doc.edit.reported {
        say(
            ctx,
            format!("{n}個のポイントを削除しました"),
            format!("{n} point was deleted."),
        );
    }
    Ok(())
}

/// Menu 219 (`ModelOffsetDlgProc`, `command_file_menu.cpp:474`): X, Y and Z boxes holding "0.0".
fn center_bias(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:219")?;
    let form = Form::new(
        ("バイアス付加", "apply center position bias"),
        commit_center_bias,
    )
    .field(("X:", "X:"), "0.0")
    .field(("Y:", "Y:"), "0.0")
    .field(("Z:", "Z:"), "0.0");
    open(ctx, form)
}

fn commit_center_bias(ctx: &mut Ctx, f: &[Field]) -> Result<(), String> {
    ctx.editor.apply(Command::CenterPositionBias([
        f[0].float(),
        f[1].float(),
        f[2].float(),
    ]))
}

/// Key D (`PumpModelShortcuts`, `key_ladder.cpp:304`): menu 219 in model mode, nothing in camera
/// mode.
fn key_center_bias(ctx: &mut Ctx) -> Result<(), String> {
    match camera_mode(ctx) {
        true => Ok(()),
        false => center_bias(ctx),
    }
}

/// The edit boxes of the (scale, add) dialogs: a "scale *" box prefilled "1.0" and a "+" box
/// prefilled "0.0" for each of `names`.
fn pairs(mut form: Form, names: &[Text]) -> Form {
    for &(ja, en) in names {
        form = form.field((ja, en), "1.0").field(("+", "+"), "0.0");
    }
    form
}

/// `(scale, add)` of pair `i` of a dialog built by [`pairs`], as `ApplyCameraFrameScaleAdd` and
/// `ApplyBoneFrameScaleAdd` read them.
fn pair(f: &[Field], i: usize) -> (f32, f32) {
    (f[2 * i].float(), f[2 * i + 1].float())
}

/// The scale and add arrays of `n` pairs, filled into the struct of a `Command` by `put`.
fn pair_arrays<const N: usize>(f: &[Field]) -> ([f32; N], [f32; N]) {
    let (mut scale, mut add) = ([1.0; N], [0.0; N]);
    for i in 0..N {
        (scale[i], add[i]) = pair(f, i);
    }
    (scale, add)
}

const CAMERA_PAIRS: [Text; 8] = [
    ("カメラ中心 X *", "camera X *"),
    ("カメラ中心 Y *", "camera Y *"),
    ("カメラ中心 Z *", "camera Z *"),
    ("角度 X *", "angle X *"),
    ("角度 Y *", "angle Y *"),
    ("角度 Z *", "angle Z *"),
    ("距離 *", "dist *"),
    ("視野角 *", "v-angle *"),
];

/// Menu 242 (`command_file_menu.cpp:1940`): camera mode only, the gate is the inverse of the
/// other dialogs. Edit boxes 686 to 701 hold "1.0" and "0.0" alternately.
fn multiply_camera(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Camera, "menu:242")?;
    let form = Form::new(
        (
            "ｶﾒﾗﾌﾚｰﾑ位置角度補正",
            "multiply of camera frame position-angle",
        ),
        commit_multiply_camera,
    );
    open(ctx, pairs(form, &CAMERA_PAIRS))
}

fn commit_multiply_camera(ctx: &mut Ctx, f: &[Field]) -> Result<(), String> {
    let (scale, add) = pair_arrays::<8>(f);
    let cmd = fill(Command::MultiplyCamera, |p| {
        p.scale = scale;
        p.add = add;
    });
    ctx.editor.apply(cmd)
}

/// The command `make` builds from a default parameter changed by `f`. `mds-app` does not depend
/// on `mds-ops`, whose `CameraScale` and `BoneScale` the two multiply commands take, so their
/// type comes from the command.
fn fill<T: Default>(make: fn(T) -> Command, f: impl FnOnce(&mut T)) -> Command {
    let mut v = T::default();
    f(&mut v);
    make(v)
}

const BONE_PAIRS: [Text; 6] = [
    ("ボーン位置 X *", "bone place X *"),
    ("ボーン位置 Y *", "bone place Y *"),
    ("ボーン位置 Z *", "bone place Z *"),
    ("角度 X *", "angle X *"),
    ("角度 Y *", "angle Y *"),
    ("角度 Z *", "angle Z *"),
];

/// Menu 251 (`command_view_menu.cpp:796`): edit boxes 686 to 697.
fn multiply_bone(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:251")?;
    let form = Form::new(
        ("ﾎﾞｰﾝﾌﾚｰﾑ位置角度補正", "multiply of bone position-angle"),
        commit_multiply_bone,
    );
    open(ctx, pairs(form, &BONE_PAIRS))
}

fn commit_multiply_bone(ctx: &mut Ctx, f: &[Field]) -> Result<(), String> {
    let (scale, add) = pair_arrays::<6>(f);
    let cmd = fill(Command::MultiplyBone, |p| {
        p.scale = scale;
        p.add = add;
    });
    ctx.editor.apply(cmd)
}

/// Key R (`PumpFrameDialogShortcut`, `key_ladder.cpp:318`): menu 251 in model mode.
fn key_multiply_bone(ctx: &mut Ctx) -> Result<(), String> {
    match camera_mode(ctx) {
        true => Ok(()),
        false => multiply_bone(ctx),
    }
}

/// Menu 252 (`command_view_menu.cpp:814`): edit boxes 686 and 687.
fn multiply_morph(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:252")?;
    let form = Form::new(
        ("表情大きさ補正", "multiply of facial expression"),
        commit_multiply_morph,
    );
    open(ctx, pairs(form, &[("大きさ *", "degree *")]))
}

fn commit_multiply_morph(ctx: &mut Ctx, f: &[Field]) -> Result<(), String> {
    let (scale, add) = pair(f, 0);
    ctx.editor.apply(Command::MultiplyMorph { scale, add })
}

/// Menu 250 and key F (`command_file_menu.cpp:1471`): with copied bone keys, the question, then
/// the keys on the selected bone. The accessory path of camera mode has no document command: the
/// command refuses it, and the question is not asked.
fn paste_different(ctx: &mut Ctx) -> Result<(), String> {
    if camera_mode(ctx) {
        return ctx.editor.apply(Command::PasteToSelectedBone);
    }
    if ctx.editor.doc.edit.model_clipboard.bones.is_empty() {
        return Ok(());
    }
    let form = Form::new(
        ("別ﾌﾚｰﾑへﾍﾟｰｽﾄ", "paste to difference flame"),
        |ctx, _| ctx.editor.apply(Command::PasteToSelectedBone),
    )
    .message((
        "現在コピー領域に格納されているフレームデータをボーン名を無視して\n操作対象ボーン(画面左上に表示)を選択して\n削除します\n\nよろしいですか？",
        "Trying to paste flame data to difference bone\nwhich is selected for manipulate.\n\nAre you ok?",
    ));
    open(ctx, form)
}

/// The Edit menu in the order of `res/templates/menu/menus.rc`; `None` is a separator.
const MENU: &[Option<(&str, Mode)>] = &[
    Some(("menu:300", Mode::Any)),
    Some(("menu:302", Mode::Any)),
    None,
    Some(("menu:222", Mode::Model)),
    None,
    Some(("menu:237", Mode::Camera)),
    Some(("menu:238", Mode::Camera)),
    Some(("menu:239", Mode::Camera)),
    Some(("menu:240", Mode::Camera)),
    Some(("menu:241", Mode::Camera)),
    None,
    Some(("menu:242", Mode::Camera)),
    None,
    Some(("menu:217", Mode::Model)),
    Some(("menu:220", Mode::Model)),
    Some(("menu:218", Mode::Model)),
    None,
    Some(("menu:250", Mode::Any)),
    None,
    Some(("menu:255", Mode::Any)),
    Some(("menu:256", Mode::Any)),
    Some(("menu:257", Mode::Any)),
    Some(("menu:258", Mode::Any)),
    None,
    Some(("menu:251", Mode::Model)),
    Some(("menu:252", Mode::Model)),
    None,
    Some(("menu:219", Mode::Model)),
];

/// `(id, label_ja, label_en)` of the menu rows, mnemonics dropped.
pub const LABELS: &[(&str, &str, &str)] = &[
    (
        "menu:300",
        "ボーン・カメラ数値入力",
        "bone camera numeric input",
    ),
    (
        "menu:302",
        "ボーン・カメラ角度0化",
        "bone camera angle initialize",
    ),
    ("menu:222", "不要ﾌﾚｰﾑ削除", "delete unused frame"),
    ("menu:237", "ｶﾒﾗﾌﾚｰﾑすべて選択", "select all camera frame"),
    ("menu:238", "照明ﾌﾚｰﾑすべて選択", "select all light frame"),
    (
        "menu:239",
        "ｾﾙﾌ影ﾌﾚｰﾑすべて選択",
        "select all self shadow frame",
    ),
    ("menu:240", "重力ﾌﾚｰﾑすべて選択", "select all gravity frame"),
    (
        "menu:241",
        "ｱｸｾｻﾘﾌﾚｰﾑすべて選択",
        "select all accessory frame",
    ),
    (
        "menu:242",
        "ｶﾒﾗﾌﾚｰﾑ位置角度補正",
        "multiply of camera frame position-angle",
    ),
    ("menu:217", "ﾎﾞｰﾝﾌﾚｰﾑすべて選択", "select all bone frame"),
    ("menu:220", "表情ﾌﾚｰﾑすべて選択", "select all facial frame"),
    (
        "menu:218",
        "表示･IK･外親ﾌﾚｰﾑすべて選択",
        "select all disp/IK/OP frame",
    ),
    (
        "menu:250",
        "別ﾌﾚｰﾑへﾍﾟｰｽﾄ(Fｷｰ)",
        "paste to different flame(F_key)",
    ),
    (
        "menu:255",
        "空ﾌﾚｰﾑ挿入(ﾎﾞｰﾝorｶﾒﾗ)(Iｷｰ)",
        "insert frame line(bone or camera)(I_key)",
    ),
    (
        "menu:256",
        "列ﾌﾚｰﾑ削除(ﾎﾞｰﾝorｶﾒﾗ)(Kｷｰ)",
        "delete frame line(bone or camera)(K_key)",
    ),
    (
        "menu:257",
        "空ﾌﾚｰﾑ挿入(表情or照明)(Uｷｰ)",
        "insert frame line(facial or light)(U_key)",
    ),
    (
        "menu:258",
        "列ﾌﾚｰﾑ削除(表情or照明)(Jｷｰ)",
        "delete frame line(facial or light)(J_key)",
    ),
    (
        "menu:251",
        "ﾎﾞｰﾝﾌﾚｰﾑ位置角度補正(Rｷｰ)",
        "multiply of bone frame position-angle(R_key)",
    ),
    (
        "menu:252",
        "表情大きさ補正",
        "multiply of facial expression",
    ),
    ("menu:219", "ｾﾝﾀｰ位置ﾊﾞｲｱｽ付加", "apply center position bias"),
];

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let camera = camera_mode(ctx);
    for item in MENU {
        let Some((id, mode)) = *item else {
            ui.separator();
            continue;
        };
        let &(_, ja, en) = LABELS
            .iter()
            .find(|l| l.0 == id)
            .unwrap_or_else(|| panic!("{id}: no label"));
        ui.add_enabled_ui(mode.allows(camera), |ui| {
            button(ui, ctx, id, help::pick(ui.ctx(), ja, en))
        });
    }
}
