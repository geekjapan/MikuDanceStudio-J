//! The `view` area: the View menu (`MDS_CMD_*` 211 to 299 in `src/window/command_dispatch.cpp`,
//! `command_view_menu.cpp` and `command_file_menu.cpp`), the three panel mirrors of its check
//! boxes (551, 552, 557), the frame volume slider 534, and the V, Shift+V, Alt+Enter and Esc keys
//! (`src/app/key_ladder.cpp:68` and `:79`, `src/app/pump_edit_keys.cpp:298`).
//!
//! The display options live in egui's memory as a [`ViewOptions`] (see [`options`]). Nothing
//! draws from them yet: `mds-render` has no grid, axes, info overlay, wire frame or edge switch,
//! and the window shell shows one window. The ones the PMM stores are seeded from it whenever a
//! document is opened, but no `mds-doc` command writes them back, so a save does not keep them.
//!
//! Not here, for lack of a document command (see the report of the slice): 212 (screen size),
//! 247 (camera and lighting tracking), 253 (edge thickness) and 286 (edge color).

use super::help;
use super::Ctx;
use crate::actions::Action;
use crate::editor::Editor;
use egui::{Id, ViewportCommand, WindowLevel};

/// The View menu's switches.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ViewOptions {
    /// `fpsOverlayEnabled` (menu 211, check box 551); PMM `view.fps_overlay`.
    pub info: bool,
    /// `groundGridEnabled` (menu 215, check box 557); PMM `view.ground_grid`.
    pub axes: bool,
    /// `groundShadowEnabled` (menu 221); PMM `view.ground_shadow`.
    pub ground_shadow: bool,
    /// `projectedShadowBlendEnabled` (menu 254); PMM `physics.projected_shadow_blend`.
    pub ground_shadow_transparent: bool,
    /// `selfShadowEnabled` (menu 279); PMM `self_shadow_mode != 0`.
    pub self_shadow: bool,
    /// `fpsLimit` (menus 234 to 236): 1000, 30 or 60; PMM `view.fps_limit`.
    pub fps_limit: f32,
    /// `GroundShadowColor()[0..4]`, the one value of the color dialog (menu 248), 0 to 2.
    pub ground_shadow_gray: f32,
    /// The ground shadow color dialog is open.
    pub shadow_color_dialog: bool,
    /// `characterTransparentMode` (menu 214, V).
    pub transparent_models: bool,
    /// `modelNonDisplayMode` (menu 283, Shift+V).
    pub hide_models: bool,
    /// Multisample anti-aliasing (menu 277).
    pub antialias: bool,
    /// Mipmap, anisotropic filter (menu 298); checked at start (`ui_init.cpp`).
    pub mipmap: bool,
    /// `WireframeRenderingEnabled` (menu 287).
    pub wireframe: bool,
    /// `FullscreenMode` (menu 290, Alt+Enter, Esc).
    pub fullscreen: bool,
    /// The panel column in its own window (menu 280). The shell has no second window yet.
    pub separate_window: bool,
    /// Menu 281: that window above the others.
    pub on_top: bool,
    /// `FrameVolumeControlEnabled` (menu 299, check box 552).
    pub low_power: bool,
    /// `FrameNormalization`, 0 to 100; slider 534 shows `100 - FrameNormalization`.
    pub frame_normalization: u8,
}

impl ViewOptions {
    /// What a freshly opened document and the application start-up give. `previous` carries the
    /// options that are no document's: they stay across New and Open.
    fn seed(editor: &Editor, previous: Option<&ViewOptions>) -> ViewOptions {
        let p = &editor.doc.pmm;
        let mut o = previous.cloned().unwrap_or_else(|| ViewOptions {
            ground_shadow_gray: 1.0,
            mipmap: true,
            frame_normalization: 100,
            ..ViewOptions::default()
        });
        o.info = p.view.fps_overlay != 0;
        o.axes = p.view.ground_grid != 0;
        o.ground_shadow = p.view.ground_shadow != 0;
        o.ground_shadow_transparent = p.physics.projected_shadow_blend != 0;
        o.self_shadow = p.self_shadow_mode != 0;
        o.fps_limit = p.view.fps_limit;
        o
    }
}

/// The options in egui's memory, with the document-seeded ones reloaded when the editor built a
/// new world (open, new scene).
#[derive(Clone)]
struct Slot {
    opens: usize,
    options: ViewOptions,
}

fn with<R>(egui: &egui::Context, editor: &Editor, f: impl FnOnce(&mut ViewOptions) -> R) -> R {
    let id = Id::unique("view-options");
    egui.data_mut(|d| {
        let slot = d.get_temp_mut_or_insert_with(id, || Slot {
            opens: editor.physics_opens,
            options: ViewOptions::seed(editor, None),
        });
        if slot.opens != editor.physics_opens {
            slot.options = ViewOptions::seed(editor, Some(&slot.options));
            slot.opens = editor.physics_opens;
        }
        f(&mut slot.options)
    })
}

/// The current options: what the window shell and the renderer read.
pub fn options(egui: &egui::Context, editor: &Editor) -> ViewOptions {
    with(egui, editor, |o| o.clone())
}

fn update<R>(ctx: &mut Ctx, f: impl FnOnce(&mut ViewOptions) -> R) -> Result<R, String> {
    let egui = ctx.egui.as_ref().ok_or("no window")?;
    Ok(with(egui, ctx.editor, f))
}

macro_rules! flip {
    ($field:ident) => {
        |c: &mut Ctx| update(c, |o| o.$field = !o.$field)
    };
}

macro_rules! fps {
    ($limit:expr) => {
        |c: &mut Ctx| update(c, |o| o.fps_limit = $limit)
    };
}

const ACTIONS: &[Action] = &[
    Action::run("menu:211", flip!(info), false),
    Action::run("ctl:551", flip!(info), false),
    Action::run("menu:215", flip!(axes), false),
    Action::run("ctl:557", flip!(axes), false),
    Action::run("menu:221", flip!(ground_shadow), false),
    Action::run("menu:254", flip!(ground_shadow_transparent), false),
    Action::run("menu:279", flip!(self_shadow), false),
    Action::run("menu:248", open_shadow_color, false),
    Action::run("menu:214", flip!(transparent_models), false),
    Action::run("key:V", flip!(transparent_models), false),
    Action::run("menu:283", flip!(hide_models), false),
    Action::run("key:Shift+V", flip!(hide_models), false),
    Action::run("menu:277", flip!(antialias), false),
    Action::run("menu:298", flip!(mipmap), false),
    Action::run("menu:287", flip!(wireframe), false),
    Action::run("menu:234", fps!(1000.0), false),
    Action::run("menu:235", fps!(30.0), false),
    Action::run("menu:236", fps!(60.0), false),
    Action::run("menu:299", flip!(low_power), false),
    Action::run("ctl:552", flip!(low_power), false),
    Action::run("menu:280", flip!(separate_window), false),
    Action::run("menu:281", toggle_on_top, false),
    Action::run("menu:290", toggle_fullscreen, false),
    Action::run("key:Alt+Enter", toggle_fullscreen, false),
    Action::run("key:Esc@fullscreen", leave_fullscreen, false),
    Action::inline("ctl:534"),
    Action::inline("mouse:sidebar-resize"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn open_shadow_color(ctx: &mut Ctx) -> Result<(), String> {
    update(ctx, |o| o.shadow_color_dialog = true)
}

/// Menu 281 sets `HWND_TOPMOST` on the separate window, which the shell lacks: it applies to the
/// main window instead.
fn toggle_on_top(ctx: &mut Ctx) -> Result<(), String> {
    let on = update(ctx, |o| {
        o.on_top = !o.on_top;
        o.on_top
    })?;
    send(
        ctx,
        ViewportCommand::WindowLevel(match on {
            true => WindowLevel::AlwaysOnTop,
            false => WindowLevel::Normal,
        }),
    );
    Ok(())
}

fn send(ctx: &Ctx, cmd: ViewportCommand) {
    if let Some(egui) = &ctx.egui {
        egui.send_viewport_cmd(cmd);
    }
}

fn set_fullscreen(ctx: &mut Ctx, on: bool) -> Result<(), String> {
    update(ctx, |o| o.fullscreen = on)?;
    send(ctx, ViewportCommand::Fullscreen(on));
    Ok(())
}

fn toggle_fullscreen(ctx: &mut Ctx) -> Result<(), String> {
    let on = update(ctx, |o| o.fullscreen)?;
    set_fullscreen(ctx, !on)
}

/// Esc while full screen (`PumpFullscreenKeys`, `pump_edit_keys.cpp:308`); nothing otherwise.
fn leave_fullscreen(ctx: &mut Ctx) -> Result<(), String> {
    match update(ctx, |o| o.fullscreen)? {
        true => set_fullscreen(ctx, false),
        false => Ok(()),
    }
}

/// Slider 534 at `position`: `FrameNormalization = 100 - position`
/// (`ui_scroll_mouse.cpp:108`).
pub fn set_frame_volume(ctx: &mut Ctx, position: u8) -> Result<(), String> {
    update(ctx, |o| o.frame_normalization = 100 - position.min(100))
}

/// `(id, label_ja, label_en)` of the menu rows, mnemonics dropped.
pub const LABELS: &[(&str, &str, &str)] = &[
    ("menu:212", "出力サイズ", "screen size"),
    ("menu:280", "別窓", "separate window"),
    ("menu:281", "別窓最前列表示", "to the fore"),
    (
        "menu:247",
        "ﾓﾃﾞﾙ編集時ｶﾒﾗ･照明追従",
        "camera & lighting tracking",
    ),
    ("menu:211", "情報表示", "information display"),
    ("menu:215", "座標軸表示", "display coordinate axis"),
    ("menu:221", "地面影表示", "display ground shadow"),
    ("menu:248", "地面影色設定", "ground shadow color"),
    ("menu:254", "地面影色透明化", "transparent ground shadow"),
    (
        "menu:214",
        "半透明化(Vｷｰ)",
        "character transparent mode(V_key)",
    ),
    ("menu:283", "モデル非表示", "character Non-display mode"),
    ("menu:253", "エッジ太さ", "thickness of edge line"),
    ("menu:286", "エッジ色", "edge line color"),
    ("menu:277", "アンチエイリアス", "anti-aliasing"),
    (
        "menu:298",
        "ミップマップ(異方性フィルタ)",
        "mipmap(anisotropic)",
    ),
    ("menu:279", "セルフシャドウ表示", "self-shadow"),
    ("menu:287", "ワイヤーフレーム表示", "wire frame"),
    (
        "menu:290",
        "フルスクリーン表示(Alt+Enter)",
        "full screen(Alt+Enter)",
    ),
    ("menu:234", "fps無制限", "fps no limit"),
    ("menu:235", "30fps制限", "max fps restricted to 30fps"),
    ("menu:236", "60fps制限", "max fps restricted to 60fps"),
    ("menu:299", "省エネモード", "save CPU power"),
];

/// A menu item for `id` that shows `checked` (a check or a radio mark) and runs the action when
/// clicked; greyed out when the action cannot run.
fn item(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, checked: Option<bool>) {
    let en = help::english(ui.ctx());
    let &(_, ja, e) = LABELS
        .iter()
        .find(|l| l.0 == id)
        .unwrap_or_else(|| panic!("{id}: no label"));
    let label = if en { e } else { ja };
    let button = egui::Button::new(label).selected(checked.unwrap_or(false));
    if ui.add_enabled(ctx.enabled(id), button).clicked() {
        ctx.run(id);
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let o = options(ui.ctx(), ctx.editor);
    item(ui, ctx, "menu:212", None);
    ui.separator();
    item(ui, ctx, "menu:280", Some(o.separate_window));
    item(ui, ctx, "menu:281", Some(o.on_top));
    ui.separator();
    item(ui, ctx, "menu:247", None);
    ui.separator();
    item(ui, ctx, "menu:211", Some(o.info));
    item(ui, ctx, "menu:215", Some(o.axes));
    ui.separator();
    item(ui, ctx, "menu:221", Some(o.ground_shadow));
    item(ui, ctx, "menu:248", None);
    item(ui, ctx, "menu:254", Some(o.ground_shadow_transparent));
    ui.separator();
    item(ui, ctx, "menu:214", Some(o.transparent_models));
    item(ui, ctx, "menu:283", Some(o.hide_models));
    ui.separator();
    item(ui, ctx, "menu:253", None);
    item(ui, ctx, "menu:286", None);
    ui.separator();
    item(ui, ctx, "menu:277", Some(o.antialias));
    ui.separator();
    item(ui, ctx, "menu:298", Some(o.mipmap));
    ui.separator();
    item(ui, ctx, "menu:279", Some(o.self_shadow));
    ui.separator();
    item(ui, ctx, "menu:287", Some(o.wireframe));
    ui.separator();
    item(ui, ctx, "menu:290", Some(o.fullscreen));
    ui.separator();
    for (id, limit) in [("menu:234", 1000.0), ("menu:235", 30.0), ("menu:236", 60.0)] {
        item(ui, ctx, id, Some(o.fps_limit == limit));
    }
    ui.separator();
    item(ui, ctx, "menu:299", Some(o.low_power));
    let mut position = 100 - o.frame_normalization.min(100);
    let label = help::pick(ui.ctx(), "フレーム音量", "frame volume");
    if ui
        .add(egui::Slider::new(&mut position, 0..=100).text(label))
        .changed()
    {
        if let Err(e) = set_frame_volume(ctx, position) {
            *ctx.status = e;
        }
    }
}

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let Some(egui) = ctx.egui.clone() else {
        return;
    };
    // The window can leave full screen by itself (the system button).
    if let Some(real) = ui.input(|i| i.viewport().fullscreen) {
        with(&egui, ctx.editor, |o| o.fullscreen = real);
    }
    let esc = !egui.egui_wants_keyboard_input()
        && ui.input(|i| i.key_pressed(egui::Key::Escape) && i.modifiers.is_none());
    if esc && with(&egui, ctx.editor, |o| o.fullscreen) {
        ctx.run("key:Esc@fullscreen");
    }
    let mut o = options(&egui, ctx.editor);
    if o.shadow_color_dialog {
        let mut open = true;
        let title = help::pick(&egui, "地面影色設定", "ground shadow color");
        egui::Window::new(title).open(&mut open).show(&egui, |ui| {
            // `GroundShadowColorDlgProc`: slider 0 to 200 over 100, edit "%3.2f".
            ui.add(egui::Slider::new(&mut o.ground_shadow_gray, 0.0..=2.0).step_by(0.01));
        });
        with(&egui, ctx.editor, |s| {
            s.ground_shadow_gray = o.ground_shadow_gray;
            s.shadow_color_dialog = open;
        });
    }
}
