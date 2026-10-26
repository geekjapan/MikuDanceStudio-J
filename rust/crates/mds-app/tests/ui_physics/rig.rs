use mds_app::actions;
use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// An editor and the egui context a window would give the areas.
pub struct Rig {
    pub editor: Editor,
    pub egui: egui::Context,
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
            egui: egui::Context::default(),
            status: String::new(),
        }
    }

    pub fn ctx(&mut self) -> Ctx<'_> {
        Ctx {
            editor: &mut self.editor,
            now_ms: 0,
            egui: Some(self.egui.clone()),
            viewport: None,
            status: &mut self.status,
        }
    }

    pub fn run(&mut self, id: &str) -> Result<(), String> {
        actions::run(&mut self.ctx(), id)
    }
}

impl Rig {
    /// Runs one egui pass with `events`; `f` gets the root ui and a [`Ctx`].
    pub fn frame(&mut self, events: Vec<egui::Event>, mut f: impl FnMut(&mut egui::Ui, &mut Ctx)) {
        let input = egui::RawInput {
            events,
            ..Default::default()
        };
        let mut output = self.egui.clone().run_ui(input, |ui| {
            let mut ctx = Ctx {
                editor: &mut self.editor,
                now_ms: 0,
                egui: Some(ui.ctx().clone()),
                viewport: None,
                status: &mut self.status,
            };
            f(ui, &mut ctx);
        });
        output.textures_delta.clear();
    }
}
