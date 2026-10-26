//! Recording and WAV playback in the editor: the recording against the frame dump
//! ([`record`]), the WAV following playback and frame moves ([`audio`]), and the file area's
//! rows 223, 284, 297, Esc@recording and the WAV drop through the action table.

use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use std::path::{Path, PathBuf};

mod audio;
mod record;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// A fresh temporary folder for one test.
pub fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-app-media-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// The golden2 scenes with the shared models and accessories beside them, as
/// `tests/app_core` stages them.
pub fn stage(dir: &Path) {
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

/// Runs `id` through the table with no window, as a menu item or key would.
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

/// The WAV fixture of `tests/fixtures/rust/media/wav`.
pub fn wav(name: &str) -> PathBuf {
    fixtures().join("media/wav").join(name)
}
