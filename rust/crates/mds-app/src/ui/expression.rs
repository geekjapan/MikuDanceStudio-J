//! The `expression` area: the facial expression menu (`MDS_CMD_*` 224 to 231,
//! `src/window/command_file_menu.cpp:1147` to `:1765`) and the H key (`key_ladder.cpp:122`).
//!
//! Done: delete all lip, eye and eyebrow frames (226, 228, 231; each asks first, as the C++
//! does), shift the lip frames (225), random blinks (227), reset every weight (230) and register
//! every weight (229 and H). All of them are model-mode menus: in camera mode the C++ returns at
//! its gate and `RestorePlaybackMenus` grays the items, and so does the menu here. The dialogs and
//! question boxes are [`super::edit::Form`]s.
//!
//! The VSQ lip sync (224, `LoadVsqFile`) asks for a `.vsq` file and runs
//! [`crate::editor::Editor::lip_sync`] on it, in model mode only (`ApplyModelComboSelection` greys
//! the item in camera mode, `src/window/ui_model_reload.cpp:453`): the keys, the live models at
//! the frame the load moved to, the modified flag (`:1169`) and the text dump beside the VSQ.
//! The message box of a rejected file is the error on the status line.
//!
//! The menus pick morphs by their kind (`MorphRecord::type`), not by their lane, so on a PMD the
//! three deletes and the shift find nothing (`tests/fixtures/rust/script2/README.md`).

use super::edit::{gated, localized, open, say, Field, Form, Mode, Text};
use super::{button, help, Ctx};
use crate::actions::Action;
use mds_doc::Command;
use mds_formats::text::decode_sjis;
use rfd::FileDialog;
use std::path::Path;

const ACTIONS: &[Action] = &[
    Action::run("menu:226", delete_lip, true),
    Action::run("menu:224", load_vsq, true),
    Action::run("menu:225", shift_lip, true),
    Action::run("menu:228", delete_eye, true),
    Action::run("menu:227", register_blinks, true),
    Action::run("menu:231", delete_eyebrow, true),
    Action::run("menu:230", reset_morphs, true),
    Action::run("menu:229", register_all, true),
    Action::run("key:H", key_register_all, true),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// `(id, label_ja, label_en)` of the menu rows, mnemonics dropped.
pub const LABELS: &[(&str, &str, &str)] = &[
    (
        "menu:226",
        "リップフレーム全て削除",
        "delete all mouse frame",
    ),
    (
        "menu:224",
        "vsqによるリップシンク",
        "lip-sync with .VSQ file",
    ),
    (
        "menu:225",
        "リップフレーム時間シフト",
        "time shifting mouse frame",
    ),
    ("menu:228", "目フレーム全て削除", "delete all eye frame"),
    (
        "menu:227",
        "まばたきランダム登録",
        "randomly register blinking",
    ),
    (
        "menu:231",
        "まゆフレーム全て削除",
        "delete all eyebrow frame",
    ),
    ("menu:230", "全ての表情リセット", "reset all facial value"),
    (
        "menu:229",
        "全ての表情フレーム登録(Hｷｰ)",
        "regist all facial frame(H_key)",
    ),
];

/// The menu's order, with the separators of `menus.rc` after the ids listed.
const SEPARATED: &[&str] = &["menu:225", "menu:227", "menu:231", "menu:230"];

/// The question of the three deletes (`MessageBoxA` with `MB_OKCANCEL`): caption and text as the
/// C++ has them, including the captions it reuses.
fn confirm(
    ctx: &mut Ctx,
    id: &str,
    caption: Text,
    text: Text,
    ok: super::edit::Commit,
) -> Result<(), String> {
    gated(ctx, Mode::Model, id)?;
    open(ctx, Form::new(caption, ok).message(text))
}

/// Menu 224 (`command_file_menu.cpp:1147`): the open dialog for `.vsq` files, then [`lip_sync`].
fn load_vsq(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:224")?;
    let egui = ctx.egui.clone().ok_or("no window")?;
    let Some(path) = FileDialog::new()
        .set_title(help::pick(&egui, "vsqデータ読込", "load vsq data"))
        .add_filter("vsq files(*.vsq)", &["vsq"])
        .pick_file()
    else {
        return Ok(());
    };
    lip_sync(ctx, &path, false)
}

/// `LoadVsqFile` of the `.vsq` at `path` ([`crate::editor::Editor::lip_sync`]; `dropped` for a
/// dropped file). A rejected file's message box (`mds_vsq::Reject::message`) is the error, as
/// `caption: text`, on the status line like the other info boxes of the area.
pub fn lip_sync(ctx: &mut Ctx, path: &Path, dropped: bool) -> Result<(), String> {
    if !dropped {
        gated(ctx, Mode::Model, "menu:224")?;
    }
    let stop = match ctx.editor.lip_sync(path, dropped)? {
        Ok(()) => return Ok(()),
        Err(stop) => stop,
    };
    let mds_vsq::Stop::Rejected(reject) = stop else {
        return Err(format!("lip sync stopped: {stop:?}"));
    };
    let english = ctx.egui.as_ref().is_some_and(help::english);
    let (text, caption) = reject.message(english);
    Err(format!("{}: {}", decode_sjis(caption), decode_sjis(text)))
}

/// Menu 226 (`command_file_menu.cpp:1323`): `PurgeMorphFrames(app, 3)`.
fn delete_lip(ctx: &mut Ctx) -> Result<(), String> {
    confirm(
        ctx,
        "menu:226",
        ("リップフレーム削除", "delete lip frame"),
        (
            "リップのフレームを全て削除します\n表情フレームの変更は元に戻せません\n\nよろしいですか？",
            "Trying to delete all lip frame.\nYou cannot undo this oparation.\n\nAre you OK?",
        ),
        |ctx, _| ctx.editor.apply(Command::DeleteLipFrames),
    )
}

/// Menu 228 (`:1440`): `PurgeMorphFrames(app, 2)`.
fn delete_eye(ctx: &mut Ctx) -> Result<(), String> {
    confirm(
        ctx,
        "menu:228",
        ("新規作成", "delete lip frame"),
        (
            "目のフレームを全て削除します\n表情フレームの変更は元に戻せません\n\nよろしいですか？",
            "Trying to delete all eyes frame.\nYou cannot undo this oparation.\n\nAre you OK?",
        ),
        |ctx, _| ctx.editor.apply(Command::DeleteEyeFrames),
    )
}

/// Menu 231 (`:1737`): `PurgeMorphFrames(app, 1)`.
fn delete_eyebrow(ctx: &mut Ctx) -> Result<(), String> {
    confirm(
        ctx,
        "menu:231",
        ("新規作成", "delete lip frame"),
        (
            "まゆのフレームを全て削除します\n表情フレームの変更は元に戻せません\n\nよろしいですか？",
            "Trying to delete all eyebrow frame.\nYou cannot undo this oparation.\n\nAre you OK?",
        ),
        |ctx, _| ctx.editor.apply(Command::DeleteEyebrowFrames),
    )
}

/// Menu 225 (`FrameShiftDlgProc`, `:502`): one box holding "0".
fn shift_lip(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:225")?;
    let form = Form::new(
        ("シフトするﾌﾚｰﾑ数", "frame number to shift"),
        |ctx, f: &[Field]| ctx.editor.apply(Command::ShiftLipFrames(f[0].integer())),
    )
    .field(("ﾌﾚｰﾑ数", "frames"), "0");
    open(ctx, form)
}

/// "まばたき" in Shift-JIS, as `memcmp(name, kNameMabataki, 9)` sees it: the ninth byte is the NUL.
const MABATAKI: [u8; 8] = [0x82, 0xDC, 0x82, 0xCE, 0x82, 0xBD, 0x82, 0xAB];

fn is_blink(name: &[u8]) -> bool {
    name.get(..MABATAKI.len()) == Some(&MABATAKI)
        && name.get(MABATAKI.len()).is_none_or(|&b| b == 0)
}

/// Menu 227 (`:1352`): without a morph named まばたき a box says so before any dialog; then the
/// dialog (`BlinkRegisterDlgProc`, `:524`) with two empty boxes, and after OK the count.
fn register_blinks(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:227")?;
    let blink = ctx
        .editor
        .doc
        .selected_model()
        .is_some_and(|m| m.morph_names.iter().any(|n| is_blink(&n.raw)));
    if !blink {
        return Err(localized(
            ctx,
            "このモデルの表情に”まばたき”がない為\n自動リップシンクはできません".into(),
            "You cannot register blinking because this model has not facial motion of 'blink'."
                .into(),
        ));
    }
    let form = Form::new(("まばたき登録", "register blinking"), commit_blinks)
        .field(("開始ﾌﾚｰﾑ", "frame from"), "")
        .field(("終了ﾌﾚｰﾑ", "frame to"), "");
    open(ctx, form)
}

fn commit_blinks(ctx: &mut Ctx, f: &[Field]) -> Result<(), String> {
    ctx.editor.apply(Command::RegisterBlinks {
        start: f[0].integer(),
        end: f[1].integer(),
    })?;
    if let Some(n) = ctx.editor.doc.edit.reported {
        say(
            ctx,
            format!("{n}回のまばたきを追加しました"),
            format!("{n} blinking is registerd"),
        );
    }
    Ok(())
}

/// Menu 230 (`:1709`): every morph weight 0. The C++ sets no modified flag.
fn reset_morphs(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:230")?;
    ctx.editor.apply(Command::ResetMorphs)
}

/// Menu 229 (`:1654`): the marks go, every morph registers at the current frame.
fn register_all(ctx: &mut Ctx) -> Result<(), String> {
    gated(ctx, Mode::Model, "menu:229")?;
    ctx.editor.apply(Command::RegisterAllMorphFrames)
}

/// Key H (`PumpFrameLineShortcuts`, `key_ladder.cpp:122`): menu 229 in model mode, not playing
/// (`needs_document`); nothing in camera mode.
fn key_register_all(ctx: &mut Ctx) -> Result<(), String> {
    match ctx.editor.doc.pmm.settings.options[0] != 0 {
        true => Ok(()),
        false => register_all(ctx),
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let model_mode = ctx.editor.doc.pmm.settings.options[0] == 0;
    let order = [
        "menu:226", "menu:224", "menu:225", "menu:228", "menu:227", "menu:231", "menu:230",
        "menu:229",
    ];
    for id in order {
        let &(_, ja, en) = LABELS.iter().find(|l| l.0 == id).expect("label");
        ui.add_enabled_ui(model_mode, |ui| {
            button(ui, ctx, id, help::pick(ui.ctx(), ja, en))
        });
        if SEPARATED.contains(&id) {
            ui.separator();
        }
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
