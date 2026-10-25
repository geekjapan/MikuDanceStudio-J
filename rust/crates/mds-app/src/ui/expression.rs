//! The `expression` area: the facial expression menu (`MDS_CMD_*` 224 to 231,
//! `src/window/command_file_menu.cpp:1147` to `:1765`) and the H key (`key_ladder.cpp:122`).
//!
//! Every row waits for a document command: the operations exist (`mds-ops` `delete_lip_frames`,
//! `shift_lip_frames`, `random_blinks`, `delete_eye_frames`, `delete_eyebrow_frames`,
//! `reset_morphs`, `register_all_morph_frames`, and `mds-vsq` for the VSQ lip sync), but
//! `mds_doc::Command` has none of them, and the UI changes the document only through
//! `Editor::apply`. The menu is drawn greyed out, in the order of the C++ menu, until the
//! actions are registered; the slice report lists the commands.

use super::help;
use super::{button, Ctx};
use crate::actions::Action;

pub fn actions() -> &'static [Action] {
    &[]
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

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let order = [
        "menu:226", "menu:224", "menu:225", "menu:228", "menu:227", "menu:231", "menu:230",
        "menu:229",
    ];
    for id in order {
        let &(_, ja, en) = LABELS.iter().find(|l| l.0 == id).expect("label");
        button(ui, ctx, id, help::pick(ui.ctx(), ja, en));
        if SEPARATED.contains(&id) {
            ui.separator();
        }
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
