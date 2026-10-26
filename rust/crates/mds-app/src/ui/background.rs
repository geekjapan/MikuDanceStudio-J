//! The `background` area: the Background menu, 13 inventory rows.
//!
//! * 249, 288 and 289 open the accessory order, model draw order and model calculation order
//!   dialogs (`dlg:IDD_ACCESSORY_ORDER`, `dlg:IDD_MODEL_DRAW_ORDER`, `dlg:IDD_MODEL_CALCULATE_ORDER`
//!   of [`super::dialog`], which hold their forms).
//! * 282 and `key:B` flip the black background (`ViewOption::BlackBackground`, the PMM's
//!   `black_background`). The C++ handlers do not set `SceneModified`. Whether the key reaches the
//!   action (the window has the focus, no edit box has it) is the window shell's decision, as in
//!   `PumpDisplayShortcuts`.
//! * 213 and 232 pick a file and load it as the background movie or picture
//!   (`Command::LoadBackgroundMovie`, `LoadBackgroundPicture`) and then set `SceneModified`
//!   whatever the loader said (`CmdLoadAvi`, `command_file_menu.cpp:1829`). [`load_movie_path`] and
//!   [`load_picture_path`] are the part after the dialog.
//! * 216 and 233 show or hide them; showing needs a loaded file, and nothing happens without one.
//! * 243 to 246 set the screen capture mode (`pmm.view.capture_mode`: 0 off, 1 full frame, 2 the
//!   4:3 crop, 3 background refresh). `mds-doc` has no command for it, so the radio writes the
//!   PMM's field; nothing reads it yet (the capture is the recorder's).
//!
//! # What does not work yet
//!
//! The loaders place the file with `MediaAspect`, which reads `EditState::viewport` (the
//! rectangle and `viewScale` of the window). Nothing sets it: `window.rs` would have to build an
//! `mds_media::background::Viewport` from the viewport, and `mds-app` has no `mds-media`
//! dependency to name that type with. Until then both loads fail with "no viewport for
//! MediaAspect" and change nothing.
//!
//! Without a window (`Ctx::egui` is `None`) the two file dialogs return an error; the `*_path`
//! functions are the testable entry points.

use super::{dialog, help, Ctx};
use crate::actions::{self, Action};
use mds_doc::{Command, ViewOption};
use rfd::FileDialog;
use std::path::Path;

const ACTIONS: &[Action] = &[
    Action::run(
        "menu:249",
        |c| actions::run(c, "dlg:IDD_ACCESSORY_ORDER"),
        true,
    ),
    Action::run(
        "menu:288",
        |c| actions::run(c, "dlg:IDD_MODEL_DRAW_ORDER"),
        true,
    ),
    Action::run(
        "menu:289",
        |c| actions::run(c, "dlg:IDD_MODEL_CALCULATE_ORDER"),
        true,
    ),
    Action::run("menu:282", toggle_black, false),
    Action::run("key:B", toggle_black, false),
    Action::run("menu:213", load_movie, true),
    Action::run("menu:232", load_picture, true),
    Action::run("menu:216", show_movie, false),
    Action::run("menu:233", show_picture, false),
    Action::run("menu:243", |c| capture(c, 0), false),
    Action::run("menu:244", |c| capture(c, 1), false),
    Action::run("menu:245", |c| capture(c, 2), false),
    Action::run("menu:246", |c| capture(c, 3), false),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// `(id, ja, en)` of the menu items, as the resource labels them.
const LABELS: &[(&str, &str, &str)] = &[
    (
        "menu:213",
        "背景AVIファイル読込",
        "load background AVI file",
    ),
    ("menu:216", "背景AVI表示", "show background AVI file"),
    (
        "menu:232",
        "背景画像ファイル読込",
        "load background picture file",
    ),
    ("menu:233", "背景画像表示", "show background picture file"),
    ("menu:282", "背景黒化", "black background"),
    ("menu:243", "ｽｸﾘｰﾝ用ｷｬﾌﾟﾁｬOFF", "screen capture mode OFF"),
    ("menu:244", "ON･モード１(全画面)", "ON.mode01"),
    ("menu:245", "ON･モード２(4:3比率)", "ON.mode02"),
    ("menu:246", "ON･モード３(背景AVI)", "ON.mode03"),
    ("menu:249", "アクセサリ編集", "accessories edit"),
    ("menu:288", "モデル描画順", "model draw order"),
    ("menu:289", "モデル計算順", "model calculate order"),
];

fn item(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, checked: Option<bool>) {
    let &(_, ja, en) = LABELS
        .iter()
        .find(|l| l.0 == id)
        .unwrap_or_else(|| panic!("{id}: no label"));
    let label = if help::english(ui.ctx()) { en } else { ja };
    let button = egui::Button::new(label).selected(checked.unwrap_or(false));
    if ui.add_enabled(ctx.enabled(id), button).clicked() {
        ctx.run(id);
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let pmm = &ctx.editor.doc.pmm;
    let (movie, picture) = (pmm.avi.enabled != 0, pmm.picture.enabled != 0);
    let (black, mode) = (pmm.appearance.black_background != 0, pmm.view.capture_mode);
    item(ui, ctx, "menu:213", None);
    item(ui, ctx, "menu:216", Some(movie));
    ui.separator();
    item(ui, ctx, "menu:232", None);
    item(ui, ctx, "menu:233", Some(picture));
    ui.separator();
    item(ui, ctx, "menu:282", Some(black));
    ui.separator();
    for (n, id) in ["menu:243", "menu:244", "menu:245", "menu:246"]
        .into_iter()
        .enumerate()
    {
        item(ui, ctx, id, Some(mode == n as i32));
    }
    ui.separator();
    for id in ["menu:249", "menu:288", "menu:289"] {
        item(ui, ctx, id, None);
    }
}

/// `B` is handled by the `key:B` action, wherever the window routes the key.
pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}

// ---- 282, key:B ----

/// Menu 282 and the `B` key flip `blackBackgroundEnabled`.
fn toggle_black(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.pmm.appearance.black_background != 0;
    dialog::apply_cpp(
        ctx,
        Command::SetViewOption {
            option: ViewOption::BlackBackground,
            on: !on,
        },
    )
}

// ---- 243 to 246 ----

fn capture(ctx: &mut Ctx, mode: i32) -> Result<(), String> {
    ctx.editor.doc.pmm.view.capture_mode = mode;
    Ok(())
}

// ---- 216, 233 ----

fn show_movie(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.pmm.avi.enabled != 0;
    dialog::apply_cpp(ctx, Command::ShowBackgroundMovie(!on))
}

fn show_picture(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.pmm.picture.enabled != 0;
    dialog::apply_cpp(ctx, Command::ShowBackgroundPicture(!on))
}

// ---- 213, 232 ----

const PICTURES: &[&str] = &["bmp", "jpg", "png", "tga", "dds", "dib", "pfm", "hdr"];

fn pick(
    ctx: &Ctx,
    title: (&str, &str),
    filter: (&str, &str),
    ext: &[&str],
) -> Result<Option<std::path::PathBuf>, String> {
    if ctx.egui.is_none() {
        return Err("no window for the file dialog".into());
    }
    let en = ctx.egui.as_ref().is_some_and(help::english);
    Ok(FileDialog::new()
        .set_title(if en { title.1 } else { title.0 })
        .add_filter(if en { filter.1 } else { filter.0 }, ext)
        .pick_file())
}

fn load_movie(ctx: &mut Ctx) -> Result<(), String> {
    let title = ("AVI", "load AVI file");
    match pick(
        ctx,
        title,
        ("avi files(*.avi)", "avi files(*.avi)"),
        &["avi"],
    )? {
        Some(path) => load_movie_path(ctx, &path),
        None => Ok(()),
    }
}

fn load_picture(ctx: &mut Ctx) -> Result<(), String> {
    let title = ("背景画像データ読込", "load picture data");
    let filter = ("全ての対応フォーマット", "All Picture files");
    match pick(ctx, title, filter, PICTURES)? {
        Some(path) => load_picture_path(ctx, &path),
        None => Ok(()),
    }
}

/// `LoadAviFile` of the file at `path`, then `SceneModified`: the C++ sets it whatever the
/// loader did. (Here a load that could not start, for the missing viewport, leaves it alone.)
pub fn load_movie_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let data = read(path)?;
    let cmd = Command::LoadBackgroundMovie {
        path: stored(path),
        data,
    };
    attempt(ctx, cmd)
}

/// `LoadBackgroundPicture` of the file at `path`, then `SceneModified`.
pub fn load_picture_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let data = read(path)?;
    let cmd = Command::LoadBackgroundPicture {
        path: stored(path),
        data,
    };
    attempt(ctx, cmd)
}

fn attempt(ctx: &mut Ctx, cmd: Command) -> Result<(), String> {
    let r = ctx.editor.apply(cmd);
    if r.is_ok() || ctx.editor.doc.edit.viewport.is_some() {
        ctx.editor.modified = true;
    }
    r
}

/// The document keeps the path with backslashes, as the C++ dialogs return it.
fn stored(path: &Path) -> String {
    path.to_string_lossy().replace('/', "\\")
}

fn read(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))
}
