use mds_app::editor::Editor;
use mds_app::ui::{model_panel, Ctx};
use mds_doc::{Command, Document};
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

pub fn expected(script: &str, file: &str) -> Vec<u8> {
    std::fs::read(fixtures().join("script/expected").join(script).join(file)).unwrap()
}

/// The start-up scene with model paths resolved against `dir`.
pub fn editor_in(dir: PathBuf) -> Editor {
    Editor::new(Document::startup(), Some(dir.join("scratch.pmm"))).unwrap()
}

pub fn editor() -> Editor {
    editor_in(fixtures())
}

pub fn ctx<'a>(editor: &'a mut Editor, status: &'a mut String) -> Ctx<'a> {
    Ctx {
        editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status,
    }
}

/// Runs action `id` as a button or key would; `Err` is what the status line would show.
pub fn run(editor: &mut Editor, id: &str) -> Result<(), String> {
    let mut status = String::new();
    mds_app::actions::run(&mut ctx(editor, &mut status), id)
}

/// `load model <name>` of the script runner, then the helper the Load button runs.
pub fn load_model(editor: &mut Editor, name: &str) {
    let data = std::fs::read(fixtures().join(name)).unwrap();
    let mut status = String::new();
    model_panel::load(&mut ctx(editor, &mut status), name, data).unwrap();
}

pub fn frame(editor: &mut Editor, n: u32) {
    editor.seek(n).unwrap();
}

/// `select bone <name>` (`SelectDisplayBone`): that bone only.
pub fn select_bone(editor: &mut Editor, name: &str) {
    let m = editor.doc.selected_model().unwrap();
    let b = m.bone_names.iter().position(|n| n.text == name).unwrap();
    editor.apply(Command::SelectBones(vec![b as u32])).unwrap();
}

/// The first byte that differs, or the shorter length.
pub fn first_diff(a: &[u8], b: &[u8]) -> Option<usize> {
    a.iter()
        .zip(b)
        .position(|(x, y)| x != y)
        .or((a.len() != b.len()).then(|| a.len().min(b.len())))
}

pub fn assert_saved(editor: &Editor, script: &str, file: &str) {
    let got = editor.doc.save().unwrap();
    let want = expected(script, file);
    assert_eq!(
        first_diff(&got, &want),
        None,
        "{script}/{file}: {} bytes, C++ {}",
        got.len(),
        want.len()
    );
}
