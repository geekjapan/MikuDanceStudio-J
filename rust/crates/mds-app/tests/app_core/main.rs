//! The application core: the frame dump of the golden2 scenes ([`golden2`]), the editor
//! ([`editor`]), the action modes ([`modes`]) and the file area ([`file`]).

use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use std::path::{Path, PathBuf};

mod editor;
mod file;
mod golden2;
mod modes;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// A fresh temporary folder for one test.
pub fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-app-core-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// The golden2 scenes with the shared models and the accessory fixtures beside them (the
/// scene's own files win), as `tools/oracle/golden2.ps1` stages them next to the exe.
pub fn stage_golden2(dir: &Path) {
    let f = fixtures();
    for from in [f.join("accessory"), f.clone(), f.join("golden2")] {
        for e in std::fs::read_dir(&from).unwrap() {
            let e = e.unwrap();
            if e.file_type().unwrap().is_file() {
                std::fs::copy(e.path(), dir.join(e.file_name())).unwrap();
            }
        }
    }
}

/// Runs `id` through the table as a button or key would.
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
