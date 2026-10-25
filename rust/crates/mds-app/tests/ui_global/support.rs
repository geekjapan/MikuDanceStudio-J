use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use mds_doc::{Command, Document};
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// `Document::startup` then `load_scene`, as the script runner opens a PMM.
pub fn load(name: &str) -> Editor {
    let data = std::fs::read(fixtures().join(name)).unwrap();
    let mut editor = Editor::new(Document::startup(), None).unwrap();
    editor
        .doc
        .load_scene(&data, |p| std::fs::read(fixtures().join(p)).ok())
        .unwrap_or_else(|e| panic!("{name}: {e}"));
    editor
}

/// `camera3.pmm` in camera mode.
pub fn camera_mode() -> Editor {
    let mut editor = load("camera3.pmm");
    editor.apply(Command::SelectCameraMode).unwrap();
    editor
}

/// `swing600.pmm` in model mode.
pub fn model_mode() -> Editor {
    let editor = Editor::open(&fixtures().join("swing600.pmm")).unwrap();
    assert_eq!(editor.doc.pmm.settings.options[0], 0);
    editor
}

pub fn with_ctx<R>(editor: &mut Editor, f: impl FnOnce(&mut Ctx) -> R) -> (R, String) {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    (f(&mut ctx), status)
}

/// Runs `id` through the action table as a button or key would.
pub fn run(editor: &mut Editor, id: &str) -> Result<(), String> {
    with_ctx(editor, |ctx| mds_app::actions::run(ctx, id)).0
}

/// The PMM bytes of the document, for a whole-document comparison.
pub fn saved(editor: &Editor) -> Vec<u8> {
    editor.doc.save().unwrap()
}
