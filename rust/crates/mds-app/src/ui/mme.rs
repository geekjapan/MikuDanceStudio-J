//! The `mme` area: the MMEffect menu (`third_party/mmeffect/res/MMEffect.rc`, dispatched by
//! `MmeMainWindowProc` in `third_party/mmeffect/src/mmeffect/mme_ui.cpp`) and its log window; and
//! in [`dialog`], the `mme-dialog` area: the effect mapping dialog (`mme_dlg.cpp`).
//!
//! The switches live in the editor's [`crate::mme::Mme`]; which windows are open, and the file
//! answers of the window-less runs, in [`STATE`].

use super::Ctx;
use crate::actions::Action;
use std::cell::RefCell;
use std::collections::{BTreeSet, VecDeque};
use std::path::PathBuf;

const ACTIONS: &[Action] = &[
    Action::run("menu:mme-40005", open_mapping, false),
    Action::run("menu:mme-40006", toggle_effects, false),
    Action::run("key:Ctrl+Shift+E", toggle_effects, false),
    Action::run("menu:mme-40001", toggle_auto_reload, false),
    Action::run("menu:mme-40022", toggle_auto_save, false),
    Action::run("menu:mme-40004", reload_all, false),
    Action::run("menu:mme-40002", open_log, false),
    Action::run("menu:mme-40003", open_about, false),
    Action::inline("dlg:IDD_MME_LOG"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// A row of the mapping dialog's list.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Row {
    /// `(default)`: the EMM's `Default` effect.
    Default,
    /// An object: an index into the assignments (models, then accessories).
    Object(usize),
    /// A material subset of a model, after Subset-Extract.
    Subset(usize, i32),
}

#[derive(Default)]
struct State {
    log: bool,
    about: bool,
    dialog: bool,
    selected: BTreeSet<Row>,
    /// The objects Subset-Extract expanded.
    expanded: BTreeSet<usize>,
    /// The Apply button is enabled: an edit since the last Apply.
    dirty: bool,
    /// The default effect Cancel restores (taken at open and at Apply).
    default_snapshot: String,
    /// The answers of the file dialogs without a window, in order; `None` is a cancel.
    answers: VecDeque<Option<PathBuf>>,
    /// The text of the open Disassemble Effect window (40014).
    disassembly: Option<String>,
    /// The offscreen tab (1002): the file of the effect declaring the target and its name;
    /// `None` is Main.
    tab: Option<(PathBuf, String)>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::default();
}

/// Queues the answer of the next file dialog of the window-less runs.
pub fn answer(path: Option<PathBuf>) {
    STATE.with_borrow_mut(|s| s.answers.push_back(path));
}

/// Whether the log window (40002), the About box (40003) and the mapping dialog (40005) are open.
pub fn open_windows() -> [bool; 3] {
    STATE.with_borrow(|s| [s.log, s.about, s.dialog])
}

/// Selects the rows of the mapping dialog (a click in the list, 1003).
pub fn select(rows: &[Row]) {
    STATE.with_borrow_mut(|s| s.selected = rows.iter().copied().collect());
}

/// Selects a tab of the mapping dialog (a click on the tab control, 1002): an offscreen target
/// by its effect file and name, `None` Main.
pub fn select_tab(tab: Option<(PathBuf, String)>) {
    STATE.with_borrow_mut(|s| s.tab = tab);
}

/// Whether Apply (1005) is enabled.
pub fn dirty() -> bool {
    STATE.with_borrow(|s| s.dirty)
}

fn english(ctx: &Ctx) -> bool {
    ctx.egui.as_ref().is_some_and(super::help::english)
}

/// 40005: the modeless dialog; the default effect is snapshotted for Cancel.
fn open_mapping(ctx: &mut Ctx) -> Result<(), String> {
    let default = ctx.editor.mme.default.clone();
    STATE.with_borrow_mut(|s| {
        s.dialog = true;
        s.dirty = false;
        s.default_snapshot = default;
    });
    Ok(())
}

/// 40006 and Ctrl+Shift+E: `effectEnabled` flips (`mme_ui.cpp:367`, default on,
/// `mme_context.cpp:124`). The effects stay loaded and assigned.
fn toggle_effects(ctx: &mut Ctx) -> Result<(), String> {
    let s = &mut ctx.editor.mme.switches;
    s.enabled = !s.enabled;
    Ok(())
}

/// 40001: `g_autoReload` flips (`mme_ui.cpp:331`, default on, `mme_globals.cpp:59`).
fn toggle_auto_reload(ctx: &mut Ctx) -> Result<(), String> {
    let s = &mut ctx.editor.mme.switches;
    s.auto_reload = !s.auto_reload;
    Ok(())
}

/// 40022: `g_emmAutoSave` flips (`mme_ui.cpp:383`, default on, `callbacks.cpp:445`). The C++ also
/// writes it to `MMEffect.ini`; the application keeps no such file.
fn toggle_auto_save(ctx: &mut Ctx) -> Result<(), String> {
    let s = &mut ctx.editor.mme.switches;
    s.auto_save = !s.auto_save;
    Ok(())
}

/// 40004: `MmeUiReloadAllEffects` (`mme_ui.cpp:614`): every effect compiles again from the
/// assignment as it is; the EMM is not read again.
fn reload_all(ctx: &mut Ctx) -> Result<(), String> {
    // The C++ keeps the dialog's offscreen edits on the effect's targets, which load anew.
    ctx.editor.mme.offscreen.clear();
    ctx.editor.mme.unload();
    Ok(())
}

fn open_log(_: &mut Ctx) -> Result<(), String> {
    STATE.with_borrow_mut(|s| s.log = true);
    Ok(())
}

fn open_about(_: &mut Ctx) -> Result<(), String> {
    STATE.with_borrow_mut(|s| s.about = true);
    Ok(())
}

/// The About text of `mme_ui.cpp:342` (the author's name decoded from Shift-JIS).
pub const ABOUT: &str = "MikuMikuEffect ver0.37 in MikuMikuDance\n(by 舞力介入Ｐ)";

/// A menu item of action `id`, with a check mark when `checked` is `Some(true)`.
fn item(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, ja: &str, en: &str, checked: Option<bool>) {
    let label = if english(ctx) { en } else { ja };
    let label = match checked {
        Some(true) => format!("✔ {label}"),
        Some(false) => format!("   {label}"),
        None => label.to_string(),
    };
    super::button(ui, ctx, id, &label);
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let s = ctx.editor.mme.switches;
    item(
        ui,
        ctx,
        "menu:mme-40005",
        "特效配置(&M)",
        "Effect Mapping(&M)",
        None,
    );
    ui.separator();
    let enable = (
        "使用特效(&E)  Ctrl+Shift+E",
        "Enable Effect(&E)  Ctrl+Shift+E",
    );
    item(
        ui,
        ctx,
        "menu:mme-40006",
        enable.0,
        enable.1,
        Some(s.enabled),
    );
    let reload = ("自动更新(&O)", "Auto Reload(&O)");
    item(
        ui,
        ctx,
        "menu:mme-40001",
        reload.0,
        reload.1,
        Some(s.auto_reload),
    );
    let save = ("自动保存配置文件(&S)", "Auto Save Mapping File(&S)");
    item(ui, ctx, "menu:mme-40022", save.0, save.1, Some(s.auto_save));
    ui.separator();
    item(
        ui,
        ctx,
        "menu:mme-40004",
        "全部更新(&R)",
        "Reload All(&R)",
        None,
    );
    item(
        ui,
        ctx,
        "menu:mme-40002",
        "日志窗口(&L)",
        "Log Window(&L)",
        None,
    );
    ui.separator();
    let about = ("MMEffect版本信息(&A)", "About MMEffect(&A)");
    item(ui, ctx, "menu:mme-40003", about.0, about.1, None);
}

/// The log window (`IDD_MME_LOG`: the read-only log, Close) and the About box.
pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let [mut log, mut about, _] = open_windows();
    if log {
        let mut text = ctx.editor.mme.log.borrow().join("\r\n");
        egui::Window::new("MMEffect Log")
            .open(&mut log)
            .show(ui.ctx(), |ui| {
                egui::ScrollArea::vertical()
                    .max_height(300.0)
                    .show(ui, |ui| {
                        ui.add(egui::TextEdit::multiline(&mut text).interactive(false))
                    });
                if ui.button("Close").clicked() {
                    STATE.with_borrow_mut(|s| s.log = false);
                }
            });
        if !log {
            STATE.with_borrow_mut(|s| s.log = false);
        }
    }
    if about {
        egui::Window::new("About MikuMikuEffect")
            .open(&mut about)
            .collapsible(false)
            .show(ui.ctx(), |ui| {
                ui.label(ABOUT);
                if ui.button("OK").clicked() {
                    STATE.with_borrow_mut(|s| s.about = false);
                }
            });
        if !about {
            STATE.with_borrow_mut(|s| s.about = false);
        }
    }
}

/// The `mme-dialog` area: `IDD_MME_MAPPING` (`mme_dlg.cpp`), on the Main tab and on a tab per
/// offscreen target of the loaded effects (`DlgSyncTabs`, `mme_dlg.cpp:440`), where the edits
/// are the target's overrides of its `DefaultEffect` rows (`DlgUpsertOffscreenRow`, `:357`).
pub mod dialog {
    use super::{english, select_tab, Row, State, STATE};
    use crate::actions::Action;
    use crate::mme::{effect_file, live};
    use crate::ui::Ctx;
    use mds_mmert::emm::{self, Assignment};
    use mds_mmert::host::OffscreenTarget;
    use mds_mmert::scene::{self, Overrides, RowText, TurnObject, NO_OVERRIDES};
    use std::path::{Path, PathBuf};

    const ACTIONS: &[Action] = &[
        Action::inline("dlg:IDD_MME_MAPPING"),
        Action::run("menu:mme-dialog-40009", open_emm, false),
        Action::run("menu:mme-dialog-40010", save_emm, false),
        Action::run("menu:mme-dialog-40016", open_emd, false),
        Action::run("menu:mme-dialog-40017", save_emd, false),
        Action::run("menu:mme-dialog-40011", close, false),
        Action::run("menu:mme-dialog-40007", set_effect, false),
        Action::run("menu:mme-dialog-40012", remove_effect, false),
        Action::run("menu:mme-dialog-40013", hide_show, false),
        Action::run("menu:mme-dialog-40008", reset_default, false),
        Action::run("menu:mme-dialog-40006", subset_extract, false),
        Action::run("menu:mme-dialog-40014", disassemble, false),
        Action::run("ctl:mme-dialog-1", close, false),
        Action::run("ctl:mme-dialog-2", cancel, false),
        Action::run("ctl:mme-dialog-1005", apply, false),
        Action::run("ctl:mme-dialog-1007", set_effect, false),
        Action::run("ctl:mme-dialog-1008", remove_effect, false),
        Action::run("ctl:mme-dialog-1011", hide_show, false),
        Action::inline("ctl:mme-dialog-1002"),
        Action::inline("ctl:mme-dialog-1003"),
        Action::inline("mouse:mme-dialog-dblclick"),
        Action::inline("drop:mme-dialog"),
        // `DlgToggleSkipValidation` (mme_dlg.cpp:1992) flips the engine's SkipValidation, read
        // when an effect loads; wgpu validates every pipeline and has no switch to skip it.
        Action::dropped(
            "menu:mme-dialog-40028",
            "wgpu has no switch to skip device validation (default reported to the operator 2026-10-26)",
        ),
    ];

    pub fn actions() -> &'static [Action] {
        ACTIONS
    }

    fn state<T>(f: impl FnOnce(&mut State) -> T) -> T {
        STATE.with_borrow_mut(f)
    }

    /// The file a dialog returns: the queued answer without a window, else the system dialog.
    fn pick(ctx: &Ctx, filter: &str, ext: &str, save: bool) -> Option<PathBuf> {
        if ctx.egui.is_none() {
            return state(|s| s.answers.pop_front().flatten());
        }
        let f = rfd::FileDialog::new().add_filter(filter, &[ext]);
        let mut path = if save { f.save_file()? } else { f.pick_file()? };
        if save && path.extension().is_none() {
            path.set_extension(ext);
        }
        Some(path)
    }

    fn edited(ctx: &mut Ctx) {
        ctx.editor.mme.unload();
        state(|s| s.dirty = true);
    }

    /// The selected rows, without the `(default)` row when `objects` or on an offscreen tab
    /// (`DlgCollectSelected`, `mme_dlg.cpp:603`).
    fn selected(objects: bool) -> Vec<Row> {
        state(|s| {
            let objects = objects || s.tab.is_some();
            s.selected
                .iter()
                .copied()
                .filter(|r| !objects || *r != Row::Default)
                .collect()
        })
    }

    /// The object and subset (`-1` the whole object) of a row.
    fn subset_of(r: Row) -> Option<(usize, i32)> {
        match r {
            Row::Default => None,
            Row::Object(o) => Some((o, -1)),
            Row::Subset(o, s) => Some((o, s)),
        }
    }

    /// The offscreen target of the selected tab (`DlgCurrentOffscreen`, `mme_dlg.cpp:326`):
    /// `None` on Main, and when the tab's target is not loaded.
    pub fn current_tab(ctx: &Ctx) -> Option<OffscreenTarget> {
        let tab = state(|s| s.tab.clone())?;
        let targets = ctx.editor.mme.offscreen_targets();
        targets.into_iter().find(|t| key(t) == tab)
    }

    fn key(t: &OffscreenTarget) -> (PathBuf, String) {
        (t.file.clone(), t.name.clone())
    }

    fn as_stored(p: &str) -> PathBuf {
        PathBuf::from(p)
    }

    /// The overrides of object `o` in target `t`.
    fn overrides<'a>(ctx: &'a Ctx, t: &OffscreenTarget, o: usize) -> &'a Overrides {
        let m = ctx.editor.mme.offscreen.get(&key(t));
        m.and_then(|m| m.get(&o)).unwrap_or(&NO_OVERRIDES)
    }

    fn overrides_mut<'a>(ctx: &'a mut Ctx, t: &OffscreenTarget, o: usize) -> &'a mut Overrides {
        let m = ctx.editor.mme.offscreen.entry(key(t)).or_default();
        m.entry(o).or_default()
    }

    /// Object `o` as the turn of target `t` sees it, for the row text and the shown state.
    fn turn_object<'a>(
        ctx: &'a Ctx,
        t: &OffscreenTarget,
        name: &'a str,
        o: usize,
    ) -> TurnObject<'a> {
        TurnObject {
            name,
            owner: t.owner == o,
            render_class: i32::from(t.carriers.get(o).copied().unwrap_or(false)),
            main: &ctx.editor.mme.assignments[o],
            overrides: overrides(ctx, t, o),
            resolve: &as_stored,
        }
    }

    fn file_name(path: &str) -> &str {
        path.rsplit(['\\', '/']).next().unwrap_or("")
    }

    /// `MmeOffscreenObjectShown` of subset `s` of object `o` in target `t`.
    fn tab_shown(ctx: &Ctx, t: &OffscreenTarget, o: usize, s: i32) -> bool {
        let live = live(&ctx.editor.doc);
        let obj = turn_object(ctx, t, file_name(&live[o].path), o);
        scene::shown(&t.rows, &obj, s)
    }

    /// `EffectTextForModel` (`mme_dlg.cpp:240`): the main tab's effect of subset `s`.
    fn main_text(a: &Assignment, s: i32) -> String {
        if !a.subset_shown(s) {
            return "(hide)".into();
        }
        let p = a.subsets.get(&s).filter(|_| s >= 0).unwrap_or(&a.effect);
        if p.is_empty() {
            "(none)".into()
        } else {
            p.clone()
        }
    }

    /// `DlgOffscreenRowText` (`mme_dlg.cpp:383`): subset `s` of object `o` in target `t`.
    fn tab_text(ctx: &Ctx, t: &OffscreenTarget, o: usize, s: i32) -> String {
        let live = live(&ctx.editor.doc);
        let obj = turn_object(ctx, t, file_name(&live[o].path), o);
        match scene::row_text(&t.rows, &obj, s) {
            RowText::Hide => "(hide)".into(),
            RowText::None => "(none)".into(),
            RowText::MainDefault => main_text(&ctx.editor.mme.assignments[o], s),
            RowText::Effect(p) => p.to_string(),
        }
    }

    /// `DlgOffscreenDefaultRowText` (`mme_dlg.cpp:393`): the target's rows.
    fn rows_text(t: &OffscreenTarget) -> String {
        let text: String = t.rows.iter().map(|(k, v)| format!("{k}={v}; ")).collect();
        if text.is_empty() {
            "*=none;".into()
        } else {
            text
        }
    }

    /// The selected whole-object rows (`DlgCollectSelected(true, true)`).
    fn whole_objects() -> Vec<usize> {
        selected(true)
            .into_iter()
            .filter_map(|r| match r {
                Row::Object(o) => Some(o),
                _ => None,
            })
            .collect()
    }

    /// 40009: `MmeEmmLoad` of the picked file.
    fn open_emm(ctx: &mut Ctx) -> Result<(), String> {
        let Some(path) = pick(ctx, "emm files(*.emm)", "emm", false) else {
            return Ok(());
        };
        let editor = &mut *ctx.editor;
        editor.mme.load_emm(&editor.doc, &path)?;
        edited(ctx);
        Ok(())
    }

    /// 40010: `MmeEmmSave` to the picked file.
    fn save_emm(ctx: &mut Ctx) -> Result<(), String> {
        let Some(path) = pick(ctx, "emm files(*.emm)", "emm", true) else {
            return Ok(());
        };
        let bytes = ctx.editor.mme.save_emm(&ctx.editor.doc);
        std::fs::write(&path, bytes).map_err(|e| format!("{}: {e}", path.display()))
    }

    fn materials(ctx: &Ctx, o: usize) -> i32 {
        live(&ctx.editor.doc).get(o).map_or(0, |l| l.materials)
    }

    /// 40016: `MmeEmdLoad` over every selected whole-object row (none selected: nothing).
    fn open_emd(ctx: &mut Ctx) -> Result<(), String> {
        let rows = whole_objects();
        if rows.is_empty() {
            return Ok(());
        }
        let Some(path) = pick(ctx, "emd files(*.emd)", "emd", false) else {
            return Ok(());
        };
        let bytes = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        let name = path.to_string_lossy();
        let (emd, log) = emm::parse_emd(&bytes, &name);
        let mme = &mut ctx.editor.mme;
        mme.log.borrow_mut().extend(log.into_iter().map(|l| l.text));
        let emd = emd.ok_or_else(|| format!("{name}: not an EMD file"))?;
        let counts: Vec<i32> = rows.iter().map(|&o| materials(ctx, o)).collect();
        let exists = |p: &str| Path::new(p).is_file();
        let mme = &mut ctx.editor.mme;
        for (&o, n) in rows.iter().zip(counts) {
            let r = emm::apply_emd(&emd, &name, n, &mut mme.assignments[o], &exists);
            mme.log
                .borrow_mut()
                .extend(r.log.into_iter().map(|l| l.text));
        }
        edited(ctx);
        Ok(())
    }

    /// 40017: `MmeEmdSave` of the one selected whole-object row (else nothing).
    fn save_emd(ctx: &mut Ctx) -> Result<(), String> {
        let [o] = whole_objects()[..] else {
            return Ok(());
        };
        let Some(path) = pick(ctx, "emd files(*.emd)", "emd", true) else {
            return Ok(());
        };
        let n = materials(ctx, o);
        let mme = &ctx.editor.mme;
        let cwd = path.parent().unwrap_or(Path::new(".")).to_string_lossy();
        let bytes = emm::save_emd(&mme.assignments[o], &path.to_string_lossy(), n, 0, &cwd);
        std::fs::write(&path, bytes).map_err(|e| format!("{}: {e}", path.display()))
    }

    /// OK (1) and 40011: the assignments are live already; the dialog closes.
    fn close(_: &mut Ctx) -> Result<(), String> {
        state(|s| s.dialog = false);
        Ok(())
    }

    /// Cancel (2): the default effect of the snapshot again (`MmeEmmSetDefaultEffect`), then close.
    fn cancel(ctx: &mut Ctx) -> Result<(), String> {
        ctx.editor.mme.default = state(|s| s.default_snapshot.clone());
        close(ctx)
    }

    /// Apply (1005): the default effect is snapshotted, the button greys out.
    fn apply(ctx: &mut Ctx) -> Result<(), String> {
        let default = ctx.editor.mme.default.clone();
        state(|s| {
            s.default_snapshot = default;
            s.dirty = false;
        });
        Ok(())
    }

    /// `DlgWriteEffectForSelection` (`mme_dlg.cpp:780`): `effect` (`""` to unassign) on every
    /// selected row; on an offscreen tab the target's override, `none` to unassign.
    fn write_selection(ctx: &mut Ctx, effect: &str) {
        if let Some(t) = current_tab(ctx) {
            let value = if effect.is_empty() { "none" } else { effect };
            for (o, s) in selected(false).into_iter().filter_map(subset_of) {
                overrides_mut(ctx, &t, o)
                    .effects
                    .insert(s, value.to_string());
            }
            state(|s| s.dirty = true);
            return;
        }
        let mme = &mut ctx.editor.mme;
        for row in selected(false) {
            match row {
                Row::Default => mme.default = effect.to_string(),
                Row::Object(o) => {
                    let a = &mut mme.assignments[o];
                    a.effect = effect.to_string();
                    a.shown = true;
                }
                Row::Subset(o, s) => {
                    mme.assignments[o].subsets.insert(s, effect.to_string());
                }
            }
        }
        edited(ctx);
    }

    /// 40007 and 1007: an `.fx` for the selection.
    fn set_effect(ctx: &mut Ctx) -> Result<(), String> {
        if selected(false).is_empty() {
            return Ok(());
        }
        if let Some(path) = pick(ctx, "effect files(*.fx)", "fx", false) {
            write_selection(ctx, &path.to_string_lossy());
        }
        Ok(())
    }

    /// 40012 and 1008: the selection unassigned.
    fn remove_effect(ctx: &mut Ctx) -> Result<(), String> {
        if !selected(true).is_empty() {
            write_selection(ctx, "");
        }
        Ok(())
    }

    /// 40013 and 1011 (`DlgToggleHideShowFlow`): hide every selected row when one is shown, else
    /// show them all.
    fn hide_show(ctx: &mut Ctx) -> Result<(), String> {
        let rows = selected(true);
        if let Some(t) = current_tab(ctx) {
            // `DlgApplyShown` (`mme_dlg.cpp:741`) writes the target's shown overrides.
            let rows: Vec<(usize, i32)> = rows.into_iter().filter_map(subset_of).collect();
            let show = !rows.iter().any(|&(o, s)| tab_shown(ctx, &t, o, s));
            for (o, s) in rows {
                overrides_mut(ctx, &t, o).shown.insert(s, show);
            }
            state(|s| s.dirty = true);
            return Ok(());
        }
        let mme = &mut ctx.editor.mme;
        let shown = |r: &Row| match *r {
            Row::Object(o) => mme.assignments[o].shown,
            Row::Subset(o, s) => mme.assignments[o].subset_shown(s),
            Row::Default => false,
        };
        let show = !rows.iter().any(shown);
        for r in rows {
            match r {
                Row::Object(o) => mme.assignments[o].shown = show,
                Row::Subset(o, s) => {
                    mme.assignments[o].subset_shows.insert(s, show);
                }
                Row::Default => {}
            }
        }
        edited(ctx);
        Ok(())
    }

    /// 40008 (`DlgResetWithDefaultFlow`): each selected whole object back to the effect it gets
    /// at load (the file beside it, else the default), its subset rows and shows cleared.
    fn reset_default(ctx: &mut Ctx) -> Result<(), String> {
        if let Some(t) = current_tab(ctx) {
            // `DlgRemoveOffscreenRows` (`mme_dlg.cpp:363`): every override of the object.
            let rows = selected(true).into_iter().filter_map(subset_of);
            let objects: Vec<usize> = rows.map(|(o, _)| o).collect();
            if let Some(m) = ctx.editor.mme.offscreen.get_mut(&key(&t)) {
                for o in objects {
                    m.remove(&o);
                }
            }
            state(|s| s.dirty = true);
            return Ok(());
        }
        let objects = whole_objects();
        let live = live(&ctx.editor.doc);
        let mme = &mut ctx.editor.mme;
        let dir = mme.dir().to_path_buf();
        for o in objects {
            let file = crate::scene::resolve(&dir, &live[o].path);
            let default = effect_file(&dir, &mme.default);
            let a = &mut mme.assignments[o];
            a.effect =
                emm::effect_for_model(&file.to_string_lossy(), &default.to_string_lossy(), &|p| {
                    Path::new(p).is_file()
                });
            a.subsets.clear();
            a.subset_shows.clear();
        }
        edited(ctx);
        Ok(())
    }

    /// 40006 (`DlgSubsetExtractFlow`): the selected whole-object rows expand into a row per
    /// material, or collapse when every one is expanded already.
    fn subset_extract(ctx: &mut Ctx) -> Result<(), String> {
        let objects = whole_objects();
        let models = ctx.editor.doc.pmm.models.len();
        state(|s| {
            let collapse = objects.iter().all(|o| s.expanded.contains(o));
            for o in objects.into_iter().filter(|&o| o < models) {
                match collapse {
                    true => s.expanded.remove(&o),
                    false => s.expanded.insert(o),
                };
            }
        });
        Ok(())
    }

    /// `DlgSelectedEffectPath` (`mme_dlg.cpp:652`): the effect of the first selected row in
    /// list order, the object's own for a subset row; `""` for the `(default)` row or none. On
    /// an offscreen tab the row's text, unless it names no file.
    pub fn selected_effect(ctx: &Ctx) -> String {
        let selected = state(|s| s.selected.clone());
        let row = rows(ctx).into_iter().find(|r| selected.contains(r));
        let Some((o, s)) = row.and_then(subset_of) else {
            return String::new();
        };
        match current_tab(ctx) {
            Some(t) => {
                let text = tab_text(ctx, &t, o, s);
                let none = ["", "(none)", "none", "hide", "main_default"];
                match none.iter().any(|n| text.eq_ignore_ascii_case(n)) {
                    true => String::new(),
                    false => text,
                }
            }
            None => ctx.editor.mme.assignments[o].effect.clone(),
        }
    }

    /// 40014 (`DlgDisassembleFlow`, `mme_dlg.cpp:1459`): the selected row's effect in shader
    /// assembly, in the Disassemble Effect window; the window opens empty when there is none.
    fn disassemble(ctx: &mut Ctx) -> Result<(), String> {
        let path = selected_effect(ctx);
        let text = match path.is_empty() {
            true => String::new(),
            false => ctx.editor.mme.disassemble(&path),
        };
        state(|s| s.disassembly = Some(text));
        Ok(())
    }

    /// The text of the Disassemble Effect window, when it is open.
    pub fn disassembly() -> Option<String> {
        state(|s| s.disassembly.clone())
    }

    /// The dialog's `WM_DROPFILES`: one `.emm` loads, one `.fx`, `.fxm` or `.fxsub` goes to the
    /// selection; anything else is refused.
    pub fn drop_files(ctx: &mut Ctx, paths: &[PathBuf]) -> Result<(), String> {
        let [path] = paths else {
            return Err("Two or more files cannot be specified.".into());
        };
        let ext = path
            .extension()
            .map(|e| e.to_string_lossy().to_ascii_lowercase());
        match ext.as_deref() {
            Some("emm") => {
                let editor = &mut *ctx.editor;
                editor.mme.load_emm(&editor.doc, path)?;
                edited(ctx);
                Ok(())
            }
            Some("fx" | "fxm" | "fxsub") => {
                write_selection(ctx, &path.to_string_lossy());
                Ok(())
            }
            _ => Err("Please specify .fx file or .emm file.".into()),
        }
    }

    /// The list rows: `(default)`, then each object, with its subsets when expanded.
    pub fn rows(ctx: &Ctx) -> Vec<Row> {
        let live = live(&ctx.editor.doc);
        let expanded = state(|s| s.expanded.clone());
        let mut rows = vec![Row::Default];
        for (o, l) in live.iter().enumerate() {
            rows.push(Row::Object(o));
            if expanded.contains(&o) {
                rows.extend((0..l.materials).map(|s| Row::Subset(o, s)));
            }
        }
        rows
    }

    /// The name and effect columns of `row` on the selected tab.
    pub fn row_text(ctx: &Ctx, row: Row) -> (String, String) {
        if let Some(t) = current_tab(ctx) {
            let (name, _) = main_row_text(ctx, row);
            return match row {
                Row::Default => (name, rows_text(&t)),
                Row::Object(o) => {
                    let live = live(&ctx.editor.doc);
                    let hidden = if tab_shown(ctx, &t, o, -1) {
                        ""
                    } else {
                        " (hide)"
                    };
                    let name = format!("{}{hidden}", file_name(&live[o].path));
                    (name, tab_text(ctx, &t, o, -1))
                }
                Row::Subset(o, s) => (name, tab_text(ctx, &t, o, s)),
            };
        }
        main_row_text(ctx, row)
    }

    fn main_row_text(ctx: &Ctx, row: Row) -> (String, String) {
        let mme = &ctx.editor.mme;
        let live = live(&ctx.editor.doc);
        let none = |p: &str| {
            if p.is_empty() {
                "(none)".to_string()
            } else {
                p.to_string()
            }
        };
        match row {
            Row::Default => ("(default)".into(), none(&mme.default)),
            Row::Object(o) => {
                let name = live[o].path.rsplit(['\\', '/']).next().unwrap_or("");
                let a = &mme.assignments[o];
                let hidden = if a.shown { "" } else { " (hide)" };
                (format!("{name}{hidden}"), none(&a.effect))
            }
            Row::Subset(o, s) => {
                let a = &mme.assignments[o];
                let last = s + 1 == live[o].materials;
                let lead = if last { "  `--" } else { "  |--" };
                let effect = a
                    .subsets
                    .get(&s)
                    .cloned()
                    .unwrap_or_else(|| a.effect.clone());
                (format!("{lead} {s}:"), none(&effect))
            }
        }
    }

    pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
        if !state(|s| s.dialog) {
            return;
        }
        let en = english(ctx);
        let t = |ja: &'static str, e: &'static str| if en { e } else { ja };
        let mut open = true;
        let b = crate::ui::button;
        egui::Window::new(t("エフェクトファイル割り当て", "Map Effect File"))
            .open(&mut open)
            .show(ui.ctx(), |ui| {
                egui::MenuBar::new().ui(ui, |ui| {
                    ui.menu_button(t("文件(&F)", "File(&F)"), |ui| {
                        b(
                            ui,
                            ctx,
                            "menu:mme-dialog-40009",
                            t("导入设定(&O)", "Open(&O)"),
                        );
                        b(
                            ui,
                            ctx,
                            "menu:mme-dialog-40010",
                            t("保存设定(&S)", "Save(&S)"),
                        );
                        ui.separator();
                        let m = t("模型为单位导入设定(&M)", "Open by Model(&M)");
                        b(ui, ctx, "menu:mme-dialog-40016", m);
                        let n = t("模型为单位保存设定(&N)", "Save by Model(&N)");
                        b(ui, ctx, "menu:mme-dialog-40017", n);
                        ui.separator();
                        b(ui, ctx, "menu:mme-dialog-40011", t("关闭(&C)", "Close(&C)"));
                    });
                    ui.menu_button(t("编辑(&E)", "Edit(&E)"), |ui| {
                        let f = t("文件选择(&F)", "Set Effect File(&F)");
                        b(ui, ctx, "menu:mme-dialog-40007", f);
                        let n = t("解除(&N)", "Remove Effect(&N)");
                        b(ui, ctx, "menu:mme-dialog-40012", n);
                        let h = t("不显示/显示(&H)", "Hide/Show(&H)");
                        b(ui, ctx, "menu:mme-dialog-40013", h);
                        let r = t("重置为默认设定(&R)", "Reset with default(&R)");
                        b(ui, ctx, "menu:mme-dialog-40008", r);
                        ui.separator();
                        let e = t("子集展开(&E)", "Subset-Extract(&E)");
                        b(ui, ctx, "menu:mme-dialog-40006", e);
                    });
                    ui.menu_button(t("工具(&T)", "Tool(&T)"), |ui| {
                        // Enabled only when the first selected row has an effect (mme_dlg.cpp:1088).
                        let d = t("反编译特效文件(&D)", "Disassemble Effect(&D)");
                        let has = !selected_effect(ctx).is_empty();
                        ui.add_enabled_ui(has, |ui| b(ui, ctx, "menu:mme-dialog-40014", d));
                    });
                });
                // The tab control (1002) and its caption (1004, `DlgRefreshCaption`,
                // `mme_dlg.cpp:423`).
                let current = current_tab(ctx);
                let targets = ctx.editor.mme.offscreen_targets();
                ui.horizontal(|ui| {
                    if ui.selectable_label(current.is_none(), "Main").clicked() {
                        select_tab(None);
                    }
                    for t in &targets {
                        let on = current.as_ref() == Some(t);
                        if ui.selectable_label(on, &t.name).clicked() {
                            select_tab(Some(key(t)));
                        }
                    }
                });
                let caption = current.as_ref().map(|t| t.description.as_str());
                ui.label(caption.unwrap_or("Main Render Target"));
                egui::ScrollArea::vertical()
                    .max_height(240.0)
                    .show(ui, |ui| {
                        egui::Grid::new("mme-dialog-list")
                            .striped(true)
                            .show(ui, |ui| {
                                ui.strong("Object");
                                ui.strong("Effect File");
                                ui.end_row();
                                for row in rows(ctx) {
                                    let (name, effect) = row_text(ctx, row);
                                    let on = state(|s| s.selected.contains(&row));
                                    let r = ui.selectable_label(on, name);
                                    ui.label(effect);
                                    ui.end_row();
                                    if r.clicked() {
                                        let add =
                                            ui.input(|i| i.modifiers.command || i.modifiers.shift);
                                        state(|s| {
                                            if !add {
                                                s.selected.clear();
                                            }
                                            if !s.selected.insert(row) {
                                                s.selected.remove(&row);
                                            }
                                        });
                                    }
                                    if r.double_clicked() {
                                        state(|s| s.selected = [row].into());
                                        ctx.run("menu:mme-dialog-40007");
                                    }
                                }
                            });
                    });
                ui.horizontal(|ui| {
                    b(ui, ctx, "ctl:mme-dialog-1007", t("文件选择", "Set Effect"));
                    b(ui, ctx, "ctl:mme-dialog-1008", t("解除", "Remove Effect"));
                    b(
                        ui,
                        ctx,
                        "ctl:mme-dialog-1011",
                        t("不显示/显示", "Hide/Show"),
                    );
                    ui.separator();
                    b(ui, ctx, "ctl:mme-dialog-1", t("确定", "OK"));
                    b(ui, ctx, "ctl:mme-dialog-2", t("取消", "Cancel"));
                    let dirty = super::dirty();
                    ui.add_enabled_ui(dirty, |ui| {
                        b(ui, ctx, "ctl:mme-dialog-1005", t("更新", "Apply"))
                    });
                });
            });
        if !open {
            state(|s| s.dialog = false);
        }
        if let Some(mut text) = disassembly() {
            let (mut open, mut close) = (true, false);
            egui::Window::new("Disassemble Effect")
                .open(&mut open)
                .show(ui.ctx(), |ui| {
                    egui::ScrollArea::both().max_height(400.0).show(ui, |ui| {
                        ui.add(
                            egui::TextEdit::multiline(&mut text)
                                .code_editor()
                                .interactive(false),
                        )
                    });
                    close = ui.button("Close").clicked();
                });
            if !open || close {
                state(|s| s.disassembly = None);
            }
        }
    }

    /// Files dropped while the dialog is open go to it.
    pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
        if !state(|s| s.dialog) {
            return;
        }
        let paths: Vec<PathBuf> = ui.input(|i| {
            i.raw
                .dropped_files
                .iter()
                .map(|f| f.path().to_path_buf())
                .collect()
        });
        if !paths.is_empty() {
            if let Err(e) = drop_files(ctx, &paths) {
                *ctx.status = e;
            }
        }
    }
}
