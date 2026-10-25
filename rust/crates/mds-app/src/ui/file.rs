//! The `file` area: File > New, Open, Save, Save As and Exit, Ctrl+S, a dropped PMM, and the
//! prompt when the window closes. The file side is [`crate::file`]; this file has the dialogs
//! (`CmdResetState`, `CmdOpenScene`, `CmdSaveScene`, `src/window/command_impl.cpp`; `WM_CLOSE`,
//! `src/window/wndproc.cpp`).
//!
//! Not yet: pose, motion, WAV, model and accessory files (`mds-doc` has no command that loads
//! them), AVI and picture output.

use super::{button, Ctx};
use crate::actions::Action;
use crate::editor::Editor;
use crate::file::Prompt;
use mds_doc::Command;
use rfd::{FileDialog, MessageButtons, MessageDialog, MessageDialogResult};
use std::path::{Path, PathBuf};

const ACTIONS: &[Action] = &[
    Action::run("menu:204", new_scene, true),
    Action::run("menu:205", open, true),
    Action::run("menu:207", save, true),
    Action::run("menu:208", save_as, true),
    Action::run("menu:200", exit, false),
    Action::run("key:Ctrl+S", save, true),
    Action::inline("drop:pmm"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    button(ui, ctx, "menu:204", "New");
    button(ui, ctx, "menu:205", "Open...");
    button(ui, ctx, "menu:207", "Save");
    button(ui, ctx, "menu:208", "Save As...");
    ui.separator();
    button(ui, ctx, "menu:200", "Exit");
}

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    if ui.input(|i| i.viewport().close_requested()) && !confirm(Prompt::Quit, ctx.editor.modified) {
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
    let pmm = dropped
        .into_iter()
        .find(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("pmm")));
    if let Some(path) = pmm.filter(|_| !ctx.editor.playing()) {
        if confirm(Prompt::Open, ctx.editor.modified) {
            if let Err(e) = open_path(ctx, &path) {
                *ctx.status = e;
            }
        }
    }
}

/// The OK/Cancel box of `prompt`; `true` when there is none or OK was chosen.
fn confirm(prompt: Prompt, modified: bool) -> bool {
    let Some((caption, text)) = prompt.text(modified) else {
        return true;
    };
    MessageDialog::new()
        .set_title(caption)
        .set_description(text)
        .set_buttons(MessageButtons::OkCancel)
        .show()
        == MessageDialogResult::Ok
}

fn pmm_dialog(title: &str) -> FileDialog {
    FileDialog::new()
        .set_title(title)
        .add_filter("PolygonMovieMaker files(*.pmm)", &["pmm"])
}

fn open_path(ctx: &mut Ctx, path: &Path) -> Result<(), String> {
    *ctx.editor = Editor::open(path)?;
    *ctx.status = path.display().to_string();
    Ok(())
}

fn new_scene(ctx: &mut Ctx) -> Result<(), String> {
    if confirm(Prompt::New, ctx.editor.modified) {
        ctx.editor.apply(Command::NewScene)?;
    }
    Ok(())
}

fn open(ctx: &mut Ctx) -> Result<(), String> {
    if !confirm(Prompt::Open, ctx.editor.modified) {
        return Ok(());
    }
    match pmm_dialog("open file data").pick_file() {
        Some(path) => open_path(ctx, &path),
        None => Ok(()),
    }
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
    let Some(mut path) = pmm_dialog("save file").save_file() else {
        return Ok(());
    };
    // `lpstrDefExt = L"pmm"`.
    if path.extension().is_none() {
        path.set_extension("pmm");
    }
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
