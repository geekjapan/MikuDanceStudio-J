//! The `file` area: the File menu, Ctrl+S, dropped files, and the prompt when the window closes.
//! The scene side is [`crate::file`]; this file has the handlers of `src/window/command_impl.cpp`
//! (`CmdResetState`, `CmdOpenScene`, `CmdSaveScene`, `CmdLoadPose`, `CmdSavePose`,
//! `CmdLoadMotion`, `CmdSaveMotion`, `CmdOpenWave`), the dispatch of
//! `src/window/command_dispatch.cpp`, menu 276, 284, 297 and 301
//! (`src/window/command_view_menu.cpp`), menu 223 (`src/window/command_file_menu.cpp:1183`) and
//! its Esc (`PumpEscStop`, `src/app/pump_edit_keys.cpp:368`), `HandleDropFiles`
//! (`src/window/ui_dropfiles.cpp`) and `WM_CLOSE` (`src/window/wndproc.cpp`).
//!
//! Menu 223 asks for the file, then opens the AVI dialog (`dialog`, `IDD_AVI_OUTPUT`); the
//! recording ([`crate::record`]) starts in [`pass`] once the dialog's OK left its settings
//! ([`super::dialog::take_avi_request`]), and the status line shows the recording window's
//! title while it runs. Menus 284 and 297 are the WAV switches of [`crate::audio`].
//!
//! Dialogs are native (`rfd`). A run without a window (`Ctx::egui` is `None`) opens none, as the
//! C++ `--mds-script` runner replaces them: a file dialog takes the next path of [`answer`] (or
//! is cancelled), a question is answered OK, and a message goes to the status line.
//!
//! The area's state (the folders of menu 301 and the scripted answers) is kept per thread
//! ([`STATE`]), because the functions run without a window too.
//!
//! The drops of `.avi`, `.bmp` and `.jpg` load the background through the background area's
//! loads, a `.vsq` runs the lip sync of the expression area, and an `.oni` runs the MoCap menu's
//! load (296), which has no sensor session to open it yet. The C++ main window takes no MMEffect
//! files; here an `.emm` loads as on the mapping dialog, and an `.fx`, `.fxm` or `.fxsub` is
//! assigned to the selected model (the selected accessory in camera mode).

use super::dialog::AviSettings;
use super::{button, Ctx};
use crate::actions::{Action, Mode};
use crate::editor::Editor;
use crate::file::Prompt;
use mds_doc::Command;
use rfd::{FileDialog, MessageButtons, MessageDialog, MessageDialogResult};
use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};

const ACTIONS: &[Action] = &[
    Action::run("menu:204", new_scene, true),
    Action::run("menu:205", open, true),
    Action::run("menu:207", save, true),
    Action::run("menu:208", save_as, true),
    // `RestorePlaybackMenus` greys out 202 and 203 in camera mode.
    Action::run("menu:202", load_pose, true).in_mode(Mode::Model),
    Action::run("menu:203", save_pose, true).in_mode(Mode::Model),
    Action::run("menu:209", load_motion, true),
    Action::run("menu:210", save_motion, true),
    Action::run("menu:206", load_wave, true),
    Action::run("menu:223", record, true),
    Action::run("menu:276", render_picture, true),
    Action::run("menu:284", toggle_wave_on_frame, false),
    Action::run("menu:297", toggle_wave_muted, false),
    Action::run("key:Esc@recording", stop_recording, false),
    Action::run("menu:301", toggle_previous_folder, false),
    Action::run("menu:200", exit, false),
    Action::run("key:Ctrl+S", save, true),
    Action::inline("drop:pmm"),
    Action::inline("drop:pmd"),
    Action::inline("drop:pmx"),
    Action::inline("drop:vpd"),
    Action::inline("drop:vmd"),
    Action::inline("drop:x"),
    Action::inline("drop:wav"),
    Action::inline("drop:vac"),
    Action::inline("drop:avi"),
    Action::inline("drop:bmp"),
    Action::inline("drop:jpg"),
    Action::inline("drop:vsq"),
    Action::inline("drop:oni"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    for (id, label) in [
        ("menu:204", "新規"),
        ("menu:205", "開く"),
        ("menu:207", "上書き保存"),
        ("menu:208", "名前を付けて保存"),
    ] {
        button(ui, ctx, id, label);
    }
    ui.separator();
    for (id, label) in [
        ("menu:223", "AVIファイルに出力"),
        ("menu:276", "画像ファイルに出力"),
    ] {
        button(ui, ctx, id, label);
    }
    ui.separator();
    for (id, label) in [
        ("menu:202", "ポーズデータ読込"),
        ("menu:203", "ポーズデータ保存"),
        ("menu:209", "モーションデータ読込"),
        ("menu:210", "モーションデータ保存"),
        ("menu:206", "WAVファイル読込"),
    ] {
        button(ui, ctx, id, label);
    }
    for (id, on, label) in [
        (
            "menu:284",
            crate::audio::on_frame_move(),
            "ﾌﾚｰﾑ移動時WAVを鳴らす",
        ),
        ("menu:297", crate::audio::muted(), "WAVファイルを鳴らさない"),
    ] {
        button(ui, ctx, id, &checked(on, label));
    }
    ui.separator();
    button(
        ui,
        ctx,
        "menu:301",
        &checked(remembers(), "ﾃﾞﾌｫﾙﾄﾌｫﾙﾀﾞを前回位置とする"),
    );
    ui.separator();
    button(ui, ctx, "menu:200", "終了");
}

fn checked(on: bool, label: &str) -> String {
    format!("{}{label}", if on { "✔ " } else { "" })
}

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if let Some(settings) = super::dialog::take_avi_request(ui.ctx()) {
        let path = STATE
            .with_borrow_mut(|s| s.avi_path.take())
            .or_else(|| pick(ctx, &SAVE_AVI));
        if let Some(path) = path {
            if let Err(e) = record_path(ctx, &path, &settings) {
                *ctx.status = e;
            }
        }
    }
    if let Some(r) = &ctx.editor.recording {
        *ctx.status = crate::record::title(r.n, &r.settings, english(ctx));
        let esc = !ui.ctx().egui_wants_keyboard_input()
            && ui.input(|i| i.key_pressed(egui::Key::Escape) && i.modifiers.is_none());
        if esc {
            ctx.run("key:Esc@recording");
        }
    }
    if ui.input(|i| i.viewport().close_requested()) && !confirm(ctx, Prompt::Quit) {
        ui.ctx()
            .send_viewport_cmd(egui::ViewportCommand::CancelClose);
    }
    let dropped: Vec<PathBuf> = ui.input(|i| {
        i.raw
            .dropped_files
            .iter()
            .map(|f| f.path().to_path_buf())
            .collect()
    });
    if !dropped.is_empty() && !ctx.editor.playing() {
        drop_files(ctx, &dropped);
    }
}

// ---- dialogs ----

#[derive(Default)]
struct State {
    /// Menu 301 (`MDS_CMD_TOGGLE_PREVIOUS_FOLDER`): each dialog starts in the folder of its kind
    /// that was used last.
    remember: bool,
    folders: HashMap<&'static str, PathBuf>,
    /// The paths the next file dialogs of a run without a window return; `None` cancels.
    answers: VecDeque<Option<PathBuf>>,
    /// The settings the next AVI dialog of a run without a window returns; none cancels.
    avi_answers: VecDeque<AviSettings>,
    /// `AviOutputPath`: the file menu 223 chose, until the AVI dialog's OK.
    avi_path: Option<PathBuf>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::default();
}

/// Queues the path the next file dialog of a run without a window returns (`None`: cancel).
pub fn answer(path: Option<PathBuf>) {
    STATE.with_borrow_mut(|s| s.answers.push_back(path));
}

/// Queues the settings the next AVI dialog of a run without a window returns (its OK).
pub fn answer_avi(settings: AviSettings) {
    STATE.with_borrow_mut(|s| s.avi_answers.push_back(settings));
}

/// Whether menu 301 is checked.
pub fn remembers() -> bool {
    STATE.with_borrow(|s| s.remember)
}

/// A file dialog of the C++: its title, filter, default extension and folder kind
/// (`DirUser`, `DirPose`, ...).
struct Dialog {
    title: &'static str,
    title_en: &'static str,
    filter: &'static str,
    ext: &'static [&'static str],
    folder: &'static str,
    save: bool,
}

const OPEN_PMM: Dialog = Dialog {
    title: "ファイルを読込",
    title_en: "open file data",
    filter: "PolygonMovieMaker files(*.pmm)",
    ext: &["pmm"],
    folder: "user",
    save: false,
};
const SAVE_PMM: Dialog = Dialog {
    title: "ファイルを保存する",
    title_en: "save file",
    save: true,
    ..OPEN_PMM
};
const LOAD_VPD: Dialog = Dialog {
    title: "ポーズデータ読込",
    title_en: "load pose data",
    filter: "Vocaloid Pose Data files(*.vpd)",
    ext: &["vpd"],
    folder: "pose",
    save: false,
};
const SAVE_VPD: Dialog = Dialog {
    title: "ポーズデータ保存",
    title_en: "save pose data",
    save: true,
    ..LOAD_VPD
};
const LOAD_VMD: Dialog = Dialog {
    title: "モーションデータ読込",
    title_en: "load motion data",
    filter: "Vocaloid Motion Data files(*.vmd)",
    ext: &["vmd"],
    folder: "motion",
    save: false,
};
const SAVE_VMD: Dialog = Dialog {
    title: "モーションデータ保存",
    title_en: "save motion data",
    save: true,
    ..LOAD_VMD
};
const LOAD_WAV: Dialog = Dialog {
    title: "WAVE File",
    title_en: "open WAVE File",
    filter: "Wave files(*.wav)",
    ext: &["wav"],
    folder: "wave",
    save: false,
};
/// Menu 223's dialog. A PNG sequence goes beside the chosen file ([`crate::record::png_path`]).
const SAVE_AVI: Dialog = Dialog {
    title: "AVI出力",
    title_en: "output AVI file",
    filter: "AVI files(*.avi)",
    ext: &["avi"],
    folder: "user",
    save: true,
};
/// The C++ writes any D3DX picture format; this port writes PNG.
const SAVE_PICTURE: Dialog = Dialog {
    title: "画像ファイルに出力",
    title_en: "render to picture file",
    filter: "PNG files(*.png)",
    ext: &["png"],
    folder: "user",
    save: true,
};

fn english(ctx: &Ctx) -> bool {
    ctx.egui.as_ref().is_some_and(super::help::english)
}

/// The path the dialog returns, or `None` when it was cancelled. A saved path without an
/// extension gets the default one (`lpstrDefExt`).
fn pick(ctx: &Ctx, d: &Dialog) -> Option<PathBuf> {
    let mut path = if ctx.egui.is_none() {
        STATE.with_borrow_mut(|s| s.answers.pop_front().flatten())?
    } else {
        let mut f = FileDialog::new()
            .set_title(if english(ctx) { d.title_en } else { d.title })
            .add_filter(d.filter, d.ext);
        if let Some(dir) = STATE.with_borrow(|s| {
            s.remember
                .then(|| s.folders.get(d.folder).cloned())
                .flatten()
        }) {
            f = f.set_directory(dir);
        }
        if d.save {
            f.save_file()?
        } else {
            f.pick_file()?
        }
    };
    if d.save && path.extension().is_none() {
        path.set_extension(d.ext[0]);
    }
    remember_folder(d.folder, &path);
    Some(path)
}

/// `CopyDirPathW` into the folder of `kind`, when menu 301 is checked.
fn remember_folder(kind: &'static str, path: &Path) {
    STATE.with_borrow_mut(|s| {
        if let (true, Some(dir)) = (s.remember, path.parent()) {
            s.folders.insert(kind, dir.to_path_buf());
        }
    });
}

/// The OK/Cancel box of `prompt`; `true` when there is none or OK was chosen.
fn confirm(ctx: &Ctx, prompt: Prompt) -> bool {
    match prompt.text_in(ctx.editor.modified, english(ctx)) {
        Some((caption, text)) => ask(ctx, caption, text),
        None => true,
    }
}

fn ask(ctx: &Ctx, caption: &str, text: &str) -> bool {
    ctx.egui.is_none()
        || MessageDialog::new()
            .set_title(caption)
            .set_description(text)
            .set_buttons(MessageButtons::OkCancel)
            .show()
            == MessageDialogResult::Ok
}

/// An OK box; without a window, the status line.
fn tell(ctx: &mut Ctx, caption: &str, text: &str) {
    if ctx.egui.is_some() {
        MessageDialog::new()
            .set_title(caption)
            .set_description(text)
            .set_buttons(MessageButtons::Ok)
            .show();
    }
    *ctx.status = format!("{caption}: {text}");
}

fn read(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))
}

fn write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    std::fs::write(path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}

// ---- the scene ----

fn new_scene(ctx: &mut Ctx) -> Result<(), String> {
    if confirm(ctx, Prompt::New) {
        ctx.editor.apply(Command::NewScene)?;
    }
    Ok(())
}

fn open(ctx: &mut Ctx) -> Result<(), String> {
    if !confirm(ctx, Prompt::Open) {
        return Ok(());
    }
    match pick(ctx, &OPEN_PMM) {
        Some(path) => open_path(ctx, &path),
        None => Ok(()),
    }
}

/// `LoadSceneFile` of `path`; what the C++ keeps across the load carries over ([`Editor::adopt`]). A scene whose model files do not all load is refused (the
/// cancel of `IDD_PMM_MISSING_MODEL`, `src/io/pmm_load_v2.cpp:1056`): the editor cannot draw
/// or simulate a model without its file, and the document has no call that replaces or drops a
/// model record, which the dialog's locate and skip need.
pub fn open_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    ctx.editor.adopt(Editor::open(path)?)?;
    *ctx.status = path.display().to_string();
    Ok(())
}

/// Save (menu 207, Ctrl+S): to the scene's file, else Save As.
fn save(ctx: &mut Ctx) -> Result<(), String> {
    if ctx.editor.save()? {
        *ctx.status = format!("saved {}", ctx.editor.path.as_ref().unwrap().display());
        return Ok(());
    }
    save_as(ctx)
}

fn save_as(ctx: &mut Ctx) -> Result<(), String> {
    let Some(path) = pick(ctx, &SAVE_PMM) else {
        return Ok(());
    };
    ctx.editor.save_as(&path)?;
    *ctx.status = format!("saved {}", path.display());
    Ok(())
}

/// Exit (menu 200): closing the window, which asks [`Prompt::Quit`] in [`pass`].
fn exit(ctx: &mut Ctx) -> Result<(), String> {
    if let Some(egui) = &ctx.egui {
        egui.send_viewport_cmd(egui::ViewportCommand::Close);
    }
    Ok(())
}

// ---- pose, motion, wave ----

fn load_pose(ctx: &mut Ctx) -> Result<(), String> {
    match pick(ctx, &LOAD_VPD) {
        Some(path) => load_pose_path(ctx, &path),
        None => Ok(()),
    }
}

/// `LoadVpdFile` onto the selected model. It leaves the scene unmodified (`CmdLoadPose` and
/// the `.vpd` drop set no `SceneModified`).
pub fn load_pose_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    ctx.editor.apply(Command::LoadPose(read(path)?))
}

fn save_pose(ctx: &mut Ctx) -> Result<(), String> {
    let selected = ctx
        .editor
        .doc
        .selected_model()
        .is_some_and(|m| m.bone_pose.iter().any(|p| p.flags[2] != 0));
    if !selected {
        let (caption, text) = match english(ctx) {
            true => (
                "save pose data",
                "Pose data will be saved only selected bone.\nPlease select bone.",
            ),
            false => (
                "ポーズデータ保存",
                "ポーズデータは選択されたボーンのみがセーブされます\nボーンの一部、もしくは全てを選択してください",
            ),
        };
        tell(ctx, caption, text);
        return Ok(());
    }
    match pick(ctx, &SAVE_VPD) {
        Some(path) => save_pose_path(ctx, &path),
        None => Ok(()),
    }
}

/// `SaveVpdFile`: the selected bones' pose.
pub fn save_pose_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let bytes = ctx.editor.doc.save_pose().map_err(|e| e.to_string())?;
    write(path, &bytes)
}

fn load_motion(ctx: &mut Ctx) -> Result<(), String> {
    match pick(ctx, &LOAD_VMD) {
        Some(path) => load_motion_path(ctx, &path),
        None => Ok(()),
    }
}

/// `LoadVmdFile` (`src/model/vmd_load.cpp`): in model mode, motion data of another model asks
/// first (OK loads), camera data is refused; then `SceneModified`.
pub fn load_motion_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let data = read(path)?;
    let doc = &ctx.editor.doc;
    if doc.pmm.settings.options[0] == 0 && doc.selected_model().is_some() {
        // The model name follows the 30-byte magic.
        let name = data.get(30..50).ok_or("not a VMD file")?;
        if doc
            .motion_needs_confirmation(name)
            .map_err(|e| e.to_string())?
        {
            let shown = mds_formats::text::decode_sjis(name);
            let (caption, text) = match english(ctx) {
                true => (
                    "load motion data".to_string(),
                    format!("This motion file is the data for '{shown}'.\nYou can regist the motion only same bone name.\nAre you OK?"),
                ),
                false => (
                    "モーションデータ読込".to_string(),
                    format!("このファイルは {shown}用のモーションデータです\n同じボーン名のモーションのみを取り込む事になります\n続行しますか？"),
                ),
            };
            if !ask(ctx, &caption, &text) {
                return Ok(());
            }
        }
    }
    ctx.editor.apply(Command::LoadMotion(data))
}

/// `CmdSaveMotion`: the marked keys of the selected model, or in camera mode those of the
/// camera, light and self-shadow; none marked shows a box.
fn save_motion(ctx: &mut Ctx) -> Result<(), String> {
    if !motion_marked(&ctx.editor.doc) {
        let (caption, text) = match english(ctx) {
            true => (
                "save motion data",
                "Motion data will be saved only selected frame point.\nPlease select frame point.",
            ),
            false => (
                "モーションデータ保存",
                "モーションデータは選択されたフレームポイントがセーブされます\nフレームの一部、もしくは全てを選択してください",
            ),
        };
        tell(ctx, caption, text);
        return Ok(());
    }
    match pick(ctx, &SAVE_VMD) {
        Some(path) => save_motion_path(ctx, &path),
        None => Ok(()),
    }
}

/// The scan of `CmdSaveMotion` (`AnyAllocatedKey` of the three model pools, the selected bytes
/// of the camera, light and self-shadow tracks).
fn motion_marked(doc: &mds_doc::Document) -> bool {
    use mds_formats::key_pool::{Key, KeyPool};
    fn any<K: Key>(pool: &KeyPool<K>, marked: impl Fn(&K) -> bool) -> bool {
        pool.heads().iter().any(&marked) || pool.records().iter().any(|(_, k)| marked(k))
    }
    let p = &doc.pmm;
    if p.settings.options[0] != 0 {
        return any(&p.camera, |k| k.selected != 0)
            || any(&p.light, |k| k.selected != 0)
            || any(&p.self_shadow, |k| k.selected != 0);
    }
    doc.selected_model().is_some_and(|m| {
        any(&m.bone_keys, |k| k.allocated != 0)
            || any(&m.morph_keys, |k| k.allocated != 0)
            || any(&m.display_keys, |k| k.allocated != 0)
    })
}

/// `SaveVmdFile`.
pub fn save_motion_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    write(
        path,
        &mds_doc::vmd_save::save(&doc.pmm, doc.selected_model()),
    )
}

fn load_wave(ctx: &mut Ctx) -> Result<(), String> {
    match pick(ctx, &LOAD_WAV) {
        Some(path) => load_wave_path(ctx, &path),
        None => Ok(()),
    }
}

/// `LoadWaveFile`, then `SceneModified`; the editor plays it from then on ([`crate::audio`]).
pub fn load_wave_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    ctx.editor.apply(Command::LoadWave {
        path: path.to_string_lossy().into_owned(),
        data: read(path)?,
    })
}

// ---- picture output, folders ----

fn render_picture(ctx: &mut Ctx) -> Result<(), String> {
    match pick(ctx, &SAVE_PICTURE) {
        Some(path) => render_picture_path(ctx, &path),
        None => Ok(()),
    }
}

/// Menu 276: the frame on screen at the render size (menu 212, `settings.render_width` and
/// `render_height`) with the frame dump's 8x pattern, as a PNG. The C++ opens a recording window
/// at that size and writes the back buffer through D3DX.
pub fn render_picture_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let s = &ctx.editor.doc.pmm.settings;
    let size = [s.render_width, s.render_height].map(|n| n.max(1) as u32);
    let gpu = mds_render::Gpu::new()?.ok_or("no wgpu adapter")?;
    let px = ctx
        .editor
        .with_stage(size, &mds_render::SAMPLES_8X, |f, st| {
            mds_render::render_frame_with(&gpu, f, st)
        })??;
    write(path, &mds_render::encode_png(size[0], size[1], &px))
}

// ---- recording, WAV switches ----

/// Menu 223: the file, then the AVI dialog; without a window its queued answer
/// ([`answer_avi`]) starts the recording at once.
fn record(ctx: &mut Ctx) -> Result<(), String> {
    let Some(path) = pick(ctx, &SAVE_AVI) else {
        return Ok(());
    };
    if ctx.egui.is_some() {
        STATE.with_borrow_mut(|s| s.avi_path = Some(path));
        return crate::actions::run(ctx, "dlg:IDD_AVI_OUTPUT");
    }
    match STATE.with_borrow_mut(|s| s.avi_answers.pop_front()) {
        Some(settings) => record_path(ctx, &path, &settings),
        None => Ok(()),
    }
}

/// `StartAviRecordWindow` to `path` with the dialog's `settings`: the recording runs in the
/// editor's pumps from the next one on.
pub fn record_path(ctx: &mut Ctx, path: &Path, settings: &AviSettings) -> Result<(), String> {
    ctx.editor.start_recording(settings, path)
}

/// Esc while recording (`PumpEscStop`): the recording ends now.
fn stop_recording(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.stop_recording()
}

/// Menu 284 (`MDS_CMD_TOGGLE_WAVE_ON_FRAME`).
fn toggle_wave_on_frame(_: &mut Ctx) -> Result<(), String> {
    crate::audio::set_on_frame_move(!crate::audio::on_frame_move());
    Ok(())
}

/// Menu 297 (`MDS_CMD_TOGGLE_WAVE_DISABLED`).
fn toggle_wave_muted(_: &mut Ctx) -> Result<(), String> {
    crate::audio::set_muted(!crate::audio::muted());
    Ok(())
}

fn toggle_previous_folder(_: &mut Ctx) -> Result<(), String> {
    STATE.with_borrow_mut(|s| s.remember = !s.remember);
    Ok(())
}

// ---- dropped files ----

/// `HandleDropFiles`: each file by its extension, in the order dropped. A `.pmm` asks when the
/// scene is modified (cancel drops the rest); a `.vpd` and a `.vsq` in camera mode show a box
/// (`ui_dropfiles.cpp:177`, `:253`).
pub fn drop_files(ctx: &mut Ctx, paths: &[PathBuf]) {
    for path in paths {
        let ext = path
            .extension()
            .map(|e| e.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        let r = match ext.as_str() {
            "pmm" => {
                if !confirm(ctx, Prompt::Open) {
                    return;
                }
                open_path(ctx, path)
            }
            "pmd" | "pmx" => ctx.editor.load_model(path),
            "vpd" if ctx.editor.doc.pmm.settings.options[0] != 0 => {
                let (caption, text) = match english(ctx) {
                    true => ("open pose data", "Not selected model!"),
                    false => ("ポーズ読込", "カメラ・照明モードでは読めません"),
                };
                tell(ctx, caption, text);
                Ok(())
            }
            "vpd" => load_pose_path(ctx, path),
            "vmd" => load_motion_path(ctx, path),
            "x" => load_accessory_path(ctx, path),
            "vac" => load_vac_path(ctx, path),
            "wav" => load_wave_path(ctx, path),
            "avi" => super::background::load_movie_path(ctx, path),
            "bmp" | "jpg" => super::background::load_picture_path(ctx, path),
            "vsq" if ctx.editor.doc.pmm.settings.options[0] != 0 => {
                let (caption, text) = match english(ctx) {
                    true => ("open vsq data", "Not selected model!"),
                    false => ("vsq", "カメラ・照明モードではvsqデータは読めません"),
                };
                tell(ctx, caption, text);
                Ok(())
            }
            "vsq" => super::expression::lip_sync(ctx, path, true),
            "oni" => crate::actions::run(ctx, "menu:296"),
            "emm" => super::mme_dialog::drop_files(ctx, std::slice::from_ref(path)),
            "fx" | "fxm" | "fxsub" => assign_effect(ctx, path),
            _ => Err(format!(
                "{}: this file type is not supported yet",
                path.display()
            )),
        };
        if let Err(e) = r {
            *ctx.status = e;
        }
    }
}

/// `LoadAccessoryFile` of a `.vac` (`ui_dropfiles.cpp:211`): the mesh it names is the file of
/// that name beside it (`LoadAccessoryObject`, `src/render/accessory.cpp:461`).
pub fn load_vac_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let vac = read(path)?;
    let name = mds_formats::text::decode_sjis(&mds_doc::vac_mesh_name(&vac));
    let mesh = path.with_file_name(name.replace('\\', "/"));
    let resolved = mds_formats::path::resolve_path_ci(&mesh).unwrap_or_else(|| mesh.clone());
    let stored = |p: &Path| p.to_string_lossy().replace('/', "\\");
    ctx.editor.apply(Command::LoadVac {
        path: stored(path),
        vac,
        mesh_path: stored(&mesh),
        mesh: read(&resolved)?,
    })
}

/// An effect file dropped on the window: the effect of the selected model in model mode, of the
/// selected accessory in camera mode.
fn assign_effect(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let p = &ctx.editor.doc.pmm;
    let object = match p.settings.options[0] {
        0 => p
            .models
            .iter()
            .position(|m| m.slot == p.selected_model_slot),
        _ => p
            .accessories
            .iter()
            .position(|a| a.slot == p.selected_accessory_slot)
            .map(|i| p.models.len() + i),
    };
    let mme = &mut ctx.editor.mme;
    let a = object
        .and_then(|o| mme.assignments.get_mut(o))
        .ok_or("no object selected for the effect")?;
    a.effect = path.to_string_lossy().into_owned();
    a.shown = true;
    mme.unload();
    Ok(())
}

/// `LoadAccessoryFile` of a `.x`. The document takes the accessory's name from what follows the
/// last backslash of its path, so a path with `/` separators is handed over with `\`; the
/// editor finds the file again either way.
pub fn load_accessory_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let stored = path.to_string_lossy().replace('/', "\\");
    ctx.editor.apply(Command::LoadAccessory {
        path: stored,
        data: read(path)?,
    })
}
