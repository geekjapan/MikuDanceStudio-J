use mds_app::actions;
use mds_app::editor::Editor;
use mds_app::ui::edit;
use mds_app::ui::view::{self, ViewOptions};
use mds_app::ui::Ctx;
use mds_doc::script::Runner;
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// A load path as the C++ handlers get it: the lane stages the fixtures and the inputs of the
/// script directories next to the exe.
fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [
        fixtures(),
        fixtures().join("script/inputs"),
        fixtures().join("script2/inputs"),
        fixtures().join("script3/inputs"),
        fixtures().join("vsq"),
    ]
    .iter()
    .find_map(|d| std::fs::read(d.join(name)).ok())
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

    /// The document after lines `1..=upto` of `tests/fixtures/rust/<dir>/<name>.txt`, with the
    /// models of `<dir>/inputs`.
    pub fn replay(dir: &str, name: &str, upto: usize) -> Rig {
        let text =
            std::fs::read_to_string(fixtures().join(dir).join(format!("{name}.txt"))).unwrap();
        let mut runner = Runner::new();
        for (n, line) in text.lines().take(upto).enumerate() {
            runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{dir}/{name}.txt line {}: {e}", n + 1));
        }
        // The scene's folder is where the model paths of the script resolve.
        let path = fixtures().join(dir).join("inputs/ui_view.pmm");
        Rig::with(Editor::new(runner.doc, Some(path)).unwrap())
    }

    pub fn with_editor(editor: Editor) -> Rig {
        Rig::with(editor)
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
