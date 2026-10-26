//! The `help` area: the Help menu, which in this application also holds the language switch and
//! the model tools (`src/window/command_dispatch.cpp:417`, `command_view_menu.cpp:903` to `:1022`
//! and `:1343`).
//!
//! Here: About (201), the language switch (260), English names (259), toon textures (261), the
//! physics model (262) and save enhanced model (263). Menus 259, 261 and 262 open the window
//! of the dialog area (`IDD_ENGLISH_NAMES`, `IDD_TOON_TEXTURE`, `IDD_PHYSICS_MODEL`) by running
//! its `dlg:*` action, in model mode only (`command_view_menu.cpp:911`, `:938`, `:968`). The
//! language is the UI's: [`english`] and [`pick`] choose between `label_ja`, the default, and
//! `label_en` for every area.
//!
//! Not here: 278 (restore textures, `InitToonTextures` and `ReloadTextureCache`), for lack of an
//! `Editor` call that loads the textures of the meshes again; the slice report names it. Its item
//! is drawn greyed out.
//!
//! The default egui fonts have no Japanese, so the first pass loads a system font that has it,
//! when there is one.

use super::{button, Ctx};
use crate::actions::{self, Action, Mode};
use egui::Id;
use rfd::FileDialog;
use std::path::Path;

const ACTIONS: &[Action] = &[
    Action::run("menu:260", toggle_language, false),
    Action::run("menu:201", about, false),
    Action::run("menu:263", save_enhanced_model, false),
    Action::run(
        "menu:259",
        |c| open_dialog(c, "dlg:IDD_ENGLISH_NAMES"),
        false,
    )
    .in_mode(Mode::Model),
    Action::run(
        "menu:261",
        |c| open_dialog(c, "dlg:IDD_TOON_TEXTURE"),
        false,
    )
    .in_mode(Mode::Model),
    Action::run(
        "menu:262",
        |c| open_dialog(c, "dlg:IDD_PHYSICS_MODEL"),
        false,
    )
    .in_mode(Mode::Model),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// `EnglishUI()`: the interface is in English. The C++ starts in Japanese on a Japanese system
/// and in English otherwise; here it starts in Japanese.
pub fn english(egui: &egui::Context) -> bool {
    egui.data(|d| d.get_temp(Id::unique("help-english")).unwrap_or(false))
}

/// `ja` or `en` by the interface language.
pub fn pick(egui: &egui::Context, ja: &'static str, en: &'static str) -> &'static str {
    if english(egui) {
        en
    } else {
        ja
    }
}

fn window(ctx: &Ctx) -> Result<egui::Context, String> {
    ctx.egui.clone().ok_or_else(|| "no window".to_string())
}

/// Menu 260: `englishUI` flips, then `LocalizeUI` and `RefreshMenuLanguage` (the labels read
/// [`english`] every pass).
fn toggle_language(ctx: &mut Ctx) -> Result<(), String> {
    let egui = window(ctx)?;
    let now = english(&egui);
    egui.data_mut(|d| d.insert_temp(Id::unique("help-english"), !now));
    Ok(())
}

/// Menu 201: the banner of `command_dispatch.cpp:436` in a window.
fn about(ctx: &mut Ctx) -> Result<(), String> {
    window(ctx)?.data_mut(|d| d.insert_temp(Id::unique("help-about"), true));
    Ok(())
}

/// Menus 259, 261 and 262: the dialog opens as the dialog area's action opens it. The menus are in
/// none of the ranges `DisablePlaybackMenus` greys (`playback_state.cpp:67`).
fn open_dialog(ctx: &mut Ctx, dialog: &str) -> Result<(), String> {
    actions::run(ctx, dialog)
}

/// Menu 263 (`command_view_menu.cpp:989`): the save dialog for `.pmd` files, then
/// [`save_enhanced`]. Not gated by mode or playback in the C++ (it saves `SelectedModel`).
fn save_enhanced_model(ctx: &mut Ctx) -> Result<(), String> {
    window(ctx)?;
    let Some(mut path) = FileDialog::new()
        .set_title(pick(&window(ctx)?, "拡張モデル保存", "save enhanced model"))
        .add_filter("Polygon Model files(*.pmd)", &["pmd"])
        .save_file()
    else {
        return Ok(());
    };
    // `lpstrDefExt = L"pmd"`.
    if path.extension().is_none() {
        path.set_extension("pmd");
    }
    save_enhanced(ctx, &path)
}

/// `SaveEnhancedModel` (`src/window/enhance_model_io.cpp:133`) of the selected model to `path`,
/// by the PMD writer of `mds-doc`, whose output the script oracle pins (`save pmd`). The file
/// becomes the model's path. The C++ writer reads PMD-only data and ends the process on a PMX
/// model, so a PMX model is refused with a message instead. The scene's modified flag stays, as
/// in the C++.
pub fn save_enhanced(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    let bytes = ctx
        .editor
        .doc
        .save_pmd(&path.display().to_string())
        .map_err(|e| e.to_string())?;
    std::fs::write(path, bytes)
        .map_err(|e| format!("Cannot save file: {}: {e}", path.display()))?;
    *ctx.status = format!("saved {}", path.display());
    Ok(())
}

/// The text of the About box: `sprintf_s(text, 256, ...)` at `command_dispatch.cpp:436`, with
/// `kVersion` the repository's `VERSION` file and the 64-bit tag of the x64 build. The Japanese
/// author line is the Shift-JIS bytes `94 F3 8C FB 97 44`.
pub fn about_text(english: bool) -> String {
    let version = include_str!("../../../../../VERSION").trim();
    let author = if english { "Yu Higuchi" } else { "樋口優" };
    format!("MikuDanceStudio Ver.{version}\n  (64bitOS Version)\n\nprogrammed by {author}")
}

/// `(id, label_ja, label_en)` of the menu rows, mnemonics dropped.
pub const LABELS: &[(&str, &str, &str)] = &[
    ("menu:260", "English Mode", "Japanese Mode"),
    ("menu:259", "英語名編集", "edit English name"),
    ("menu:261", "ﾄｩｰﾝﾃｸｽﾁｬ変更", "toon texture"),
    ("menu:262", "物理演算編集", "physics model"),
    ("menu:263", "拡張モデル保存", "save enhanced model"),
    ("menu:278", "ﾃｸｽﾁｬ読直し", "restore texture"),
    ("menu:201", "ﾊﾞｰｼﾞｮﾝ情報", "About"),
];

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    for &(id, ja, en) in LABELS {
        button(ui, ctx, id, pick(ui.ctx(), ja, en));
    }
}

/// System fonts that have kana and kanji, tried in order.
const FONTS: &[&str] = &[
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:\\Windows\\Fonts\\YuGothR.ttc",
    "C:\\Windows\\Fonts\\meiryo.ttc",
    "C:\\Windows\\Fonts\\msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
];

fn load_font(egui: &egui::Context) {
    let id = Id::unique("help-font");
    if egui.data_mut(|d| d.get_temp::<bool>(id).is_some()) {
        return;
    }
    egui.data_mut(|d| d.insert_temp(id, true));
    // Two, because the half-width katakana of the labels are missing from the first one on macOS.
    let found: Vec<_> = FONTS
        .iter()
        .filter_map(|p| std::fs::read(p).ok())
        .take(2)
        .collect();
    if found.is_empty() {
        return;
    }
    let mut fonts = egui::FontDefinitions::default();
    for (i, bytes) in found.into_iter().enumerate() {
        let name = format!("japanese-{i}");
        fonts
            .font_data
            .insert(name.clone(), egui::FontData::from_owned(bytes).into());
        for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
            fonts.families.entry(family).or_default().push(name.clone());
        }
    }
    egui.set_fonts(fonts);
}

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let Some(egui) = ctx.egui.clone() else {
        return;
    };
    load_font(&egui);
    let id = Id::unique("help-about");
    let mut open = egui.data(|d| d.get_temp(id).unwrap_or(false));
    if open {
        let en = english(&egui);
        egui::Window::new("About")
            .open(&mut open)
            .collapsible(false)
            .resizable(false)
            .show(ui.ctx(), |ui| {
                ui.label(about_text(en));
            });
        egui.data_mut(|d| d.insert_temp(id, open));
    }
}
