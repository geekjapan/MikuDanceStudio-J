use mds_app::actions;
use mds_app::editor::Editor;
use mds_app::ui::edit;
use mds_app::ui::view::{self, ViewOptions};
use mds_app::ui::Ctx;
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// An editor and the egui context a window would give the areas.
pub struct Rig {
    pub editor: Editor,
    pub egui: Option<egui::Context>,
    pub status: String,
}

impl Rig {
    pub fn new() -> Rig {
        Rig::with(Editor::empty())
    }

    pub fn open(name: &str) -> Rig {
        Rig::with(Editor::open(&fixtures().join(name)).unwrap_or_else(|e| panic!("{name}: {e}")))
    }

    fn with(editor: Editor) -> Rig {
        Rig {
            editor,
            egui: Some(egui::Context::default()),
            status: String::new(),
        }
    }

    pub fn run(&mut self, id: &str) -> Result<(), String> {
        let mut ctx = Ctx {
            editor: &mut self.editor,
            now_ms: 0,
            egui: self.egui.clone(),
            viewport: None,
            status: &mut self.status,
        };
        actions::run(&mut ctx, id)
    }

    pub fn options(&self) -> ViewOptions {
        view::options(self.egui.as_ref().unwrap(), &self.editor)
    }
}

impl Rig {
    /// Runs `f` with the context of the rig, as an action of the table gets it.
    pub fn with_ctx<R>(&mut self, f: impl FnOnce(&mut Ctx) -> R) -> R {
        let mut ctx = Ctx {
            editor: &mut self.editor,
            now_ms: 0,
            egui: self.egui.clone(),
            viewport: None,
            status: &mut self.status,
        };
        f(&mut ctx)
    }

    /// OK of the form that is open.
    pub fn submit(&mut self) -> Result<(), String> {
        self.with_ctx(edit::submit)
    }

    /// Opens the form of `id`, types `values` into its edit boxes and presses OK.
    #[allow(dead_code)]
    pub fn answer(&mut self, id: &str, values: &[&str]) -> Result<(), String> {
        self.run(id)?;
        let egui = self.egui.clone().expect("a window");
        for (i, v) in values.iter().enumerate() {
            edit::set_text(&egui, i, v);
        }
        self.submit()
    }

    /// Runs one egui pass with `events`; `f` gets the root ui and a [`Ctx`].
    pub fn frame(&mut self, events: Vec<egui::Event>, mut f: impl FnMut(&mut egui::Ui, &mut Ctx)) {
        let egui = self.egui.clone().unwrap();
        let input = egui::RawInput {
            events,
            ..Default::default()
        };
        let mut output = egui.run_ui(input, |ui| {
            let mut ctx = Ctx {
                editor: &mut self.editor,
                now_ms: 0,
                egui: Some(ui.ctx().clone()),
                viewport: None,
                status: &mut self.status,
            };
            f(ui, &mut ctx);
        });
        // There is no renderer to take the font atlas.
        output.textures_delta.clear();
    }
}
