//! The `dialog` area of the UI through the action table, with no window: an action opens the
//! dialog, the seams type into its form and press its buttons, the document is the result.

mod forms;
mod model_dialogs;
mod prompts;
mod replay;

use mds_app::actions;
use mds_app::editor::Editor;
use mds_app::ui::{dialog, Ctx};
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// An editor and the egui context that keeps the dialog between calls.
pub struct Rig {
    pub editor: Editor,
    pub egui: egui::Context,
    pub status: String,
}

impl Rig {
    pub fn new(editor: Editor) -> Self {
        Rig {
            editor,
            egui: egui::Context::default(),
            status: String::new(),
        }
    }

    pub fn open(name: &str) -> Self {
        let e = Editor::open(&fixtures().join(name)).unwrap_or_else(|e| panic!("{name}: {e}"));
        Self::new(e)
    }

    pub fn with<R>(&mut self, f: impl FnOnce(&mut Ctx) -> R) -> R {
        let mut ctx = Ctx {
            editor: &mut self.editor,
            now_ms: 0,
            egui: Some(self.egui.clone()),
            viewport: None,
            status: &mut self.status,
        };
        f(&mut ctx)
    }

    pub fn run(&mut self, id: &str) -> Result<(), String> {
        self.with(|c| actions::run(c, id))
    }

    pub fn shown(&self) -> Option<&'static str> {
        dialog::current(&self.egui)
    }

    pub fn field(&mut self, i: usize) -> String {
        self.with(|c| dialog::field(c, i))
            .expect("an open dialog with that box")
    }

    pub fn type_into(&mut self, i: usize, text: &str) {
        self.with(|c| dialog::set_field(c, i, text));
    }

    pub fn ok(&mut self) -> Result<(), String> {
        self.with(dialog::submit)
    }

    pub fn cancel(&mut self) {
        self.with(dialog::cancel);
    }

    /// Opens the dialog of `id` and types `values` into its boxes from the first.
    pub fn fill(&mut self, id: &str, values: &[&str]) {
        self.run(id).unwrap_or_else(|e| panic!("{id}: {e}"));
        for (i, v) in values.iter().enumerate() {
            self.type_into(i, v);
        }
    }

    /// Draws one pass of the open dialog with `events` pending.
    pub fn draw(&mut self, events: Vec<egui::Event>) {
        let egui = self.egui.clone();
        let input = egui::RawInput {
            events,
            ..egui::RawInput::default()
        };
        let mut out = egui.run_ui(input, |ui| self.with(|c| dialog::show(ui, c)));
        out.textures_delta.clear();
    }

    pub fn saved(&self) -> Vec<u8> {
        self.editor.doc.save().unwrap()
    }
}
