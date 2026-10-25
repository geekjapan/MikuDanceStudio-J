//! A document in an editor, driven through the action table with a headless egui context, and
//! the `--mds-script` oracle (`tests/fixtures/rust/script/`) to set it up and to compare with.

use mds_app::editor::Editor;
use mds_app::ui::timeline::{self, Panel};
use mds_app::ui::Ctx;
use mds_doc::script::Runner;
use mds_doc::{Document, GlobalTrack, Track};
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// A load path as the C++ handlers get it (`script/inputs` holds the accessory and WAVE files).
fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [fixtures(), fixtures().join("script/inputs")]
        .iter()
        .find_map(|d| std::fs::read(d.join(name)).ok())
}

/// The runner after lines `1..=upto` of `<name>.txt`.
pub fn runner(name: &str, upto: usize) -> Runner {
    let text =
        std::fs::read_to_string(fixtures().join("script").join(format!("{name}.txt"))).unwrap();
    let mut runner = Runner::new();
    for (n, line) in text.lines().take(upto).enumerate() {
        runner
            .run_line(line, &mut |p| read_input(p))
            .unwrap_or_else(|e| panic!("{name}.txt line {}: {e}", n + 1));
    }
    runner
}

/// What the C++ saved at some step of a script.
pub fn expected(script: &str, file: &str) -> Vec<u8> {
    let path = fixtures().join("script/expected").join(script).join(file);
    std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// The first byte that differs, or the shorter length.
pub fn first_diff(a: &[u8], b: &[u8]) -> Option<usize> {
    a.iter()
        .zip(b)
        .position(|(x, y)| x != y)
        .or((a.len() != b.len()).then(|| a.len().min(b.len())))
}

pub fn assert_bytes(what: &str, got: &[u8], want: &[u8]) {
    if let Some(at) = first_diff(got, want) {
        panic!(
            "{what}: first difference at byte {at} (lengths {} and {})",
            got.len(),
            want.len()
        );
    }
}

pub struct Rig {
    pub editor: Editor,
    pub egui: egui::Context,
    pub status: String,
}

impl Rig {
    pub fn of(doc: Document) -> Rig {
        let path = fixtures().join("ui_timeline.pmm");
        Rig {
            editor: Editor::new(doc, Some(path)).unwrap(),
            egui: egui::Context::default(),
            status: String::new(),
        }
    }

    /// A PMM fixture opened as the application opens a file.
    pub fn open(name: &str) -> Rig {
        Rig {
            editor: Editor::open(&fixtures().join(name)).unwrap(),
            egui: egui::Context::default(),
            status: String::new(),
        }
    }

    /// The document after lines `1..=upto` of a script.
    pub fn replay(name: &str, upto: usize) -> Rig {
        Rig::of(runner(name, upto).doc)
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
        mds_app::actions::run(&mut self.ctx(), id)
    }

    pub fn panel(&mut self) -> Panel {
        timeline::panel(&self.ctx())
    }

    pub fn update(&mut self, f: impl FnOnce(&mut Panel)) {
        timeline::update(&self.ctx(), f)
    }

    /// Types `frame` into the go-to edit and presses Go.
    pub fn goto(&mut self, frame: u32) {
        self.update(|p| p.goto = frame);
        self.run("ctl:553").unwrap();
    }

    /// Types a range and a scope into the range edits.
    pub fn range(&mut self, from: u32, to: u32, scope: usize) {
        self.update(|p| {
            p.range = [from, to];
            p.scope = scope;
        });
    }

    pub fn save(&self) -> Vec<u8> {
        self.editor.doc.save().unwrap()
    }

    pub fn marks(&self) -> Vec<(Track, u32)> {
        timeline::marks(&self.editor.doc)
    }

    pub fn bone(&self, name: &str) -> u32 {
        self.editor.doc.pmm.models[0]
            .bone_names
            .iter()
            .position(|n| n.text == name)
            .unwrap_or_else(|| panic!("no bone {name}")) as u32
    }

    pub fn morph(&self, name: &str) -> u32 {
        self.editor.doc.pmm.models[0]
            .morph_names
            .iter()
            .position(|n| n.text == name)
            .unwrap_or_else(|| panic!("no morph {name}")) as u32
    }

    pub fn row(&self, track: Track) -> timeline::Row {
        let p = timeline::Panel::default();
        timeline::rows(&self.editor.doc, &p.folded)
            .into_iter()
            .find(|r| r.track() == Some(track))
            .unwrap_or_else(|| panic!("no row for {track:?}"))
    }
}

pub fn global(g: GlobalTrack) -> Track {
    Track::Global(g)
}
