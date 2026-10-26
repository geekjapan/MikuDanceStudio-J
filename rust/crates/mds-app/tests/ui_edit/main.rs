//! The `edit` area of the UI through the action table, with no window, and the dialogs of the
//! bulk menus (`expression` and the dialog rows of `view` and `help` are in `ui_view`).

mod dialogs;
mod gates;
#[allow(dead_code)]
#[path = "../ui_view/labels.rs"]
mod labels;
mod replay;
#[allow(dead_code)]
#[path = "../ui_view/rig.rs"]
mod rig;

use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

pub fn open(name: &str) -> Editor {
    Editor::open(&fixtures().join(name)).unwrap_or_else(|e| panic!("{name}: {e}"))
}

/// Runs `id` through the table as a menu item or key would.
pub fn run(editor: &mut Editor, id: &str) -> Result<(), String> {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    mds_app::actions::run(&mut ctx, id)
}
