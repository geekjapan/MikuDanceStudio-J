//! The `viewport` area with no window: key L through the action table, the mouse rows through
//! `viewport::input` (the function `show` feeds egui's pointer to), and the pure projection, hit
//! and drag functions. Expected values are worked out from the C++ lines each test names.
//!
//! The scene: `chain8.pmx` (a vertical chain of eight bones one unit apart, bone 0 at the
//! origin, bones 5 to 7 with rigid bodies) in the start-up camera (target (0, 10, 0), distance
//! -45, no rotation), on an 800 x 600 viewport: bone `k` sits at x 400, y about 548 - 24.6 k.

mod math;
mod mouse;
mod replay;

use mds_app::editor::Editor;
use mds_app::navigation::KeyState;
use mds_app::ui::{model_panel, viewport, Ctx};
use mds_doc::{Command, Document};
use std::path::PathBuf;

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

pub const SIZE: [f32; 2] = [800.0, 600.0];

/// The start-up scene (camera mode), posed.
pub fn startup() -> Editor {
    let mut e = Editor::new(Document::startup(), Some(fixtures().join("scratch.pmm"))).unwrap();
    e.pump(0).unwrap();
    e
}

/// `chain8.pmx` loaded (model mode, bone 0 selected), posed.
pub fn chain() -> Editor {
    let mut e = startup();
    let data = std::fs::read(fixtures().join("chain8.pmx")).unwrap();
    let mut status = String::new();
    model_panel::load(&mut ctx(&mut e, None, &mut status), "chain8.pmx", data).unwrap();
    e.pump(0).unwrap();
    e
}

/// `chain8.pmd` loaded (model mode), posed: the same chain with the rigid bodies and joints the
/// physics model dialog edits.
pub fn chain_pmd() -> Editor {
    let mut e = startup();
    let data = std::fs::read(fixtures().join("chain8.pmd")).unwrap();
    let mut status = String::new();
    model_panel::load(&mut ctx(&mut e, None, &mut status), "chain8.pmd", data).unwrap();
    e.pump(0).unwrap();
    e
}

pub fn ctx<'a>(e: &'a mut Editor, egui: Option<egui::Context>, status: &'a mut String) -> Ctx<'a> {
    Ctx {
        editor: e,
        now_ms: 0,
        egui,
        viewport: None,
        status,
    }
}

/// An editor with the egui memory the area keeps its state in.
pub struct Rig {
    pub e: Editor,
    pub egui: egui::Context,
    pub status: String,
}

impl Rig {
    pub fn new(e: Editor) -> Rig {
        Rig {
            e,
            egui: egui::Context::default(),
            status: String::new(),
        }
    }

    pub fn with<R>(&mut self, f: impl FnOnce(&mut Ctx) -> R) -> R {
        f(&mut ctx(
            &mut self.e,
            Some(self.egui.clone()),
            &mut self.status,
        ))
    }

    pub fn pass(&mut self, i: viewport::Input) {
        self.with(|c| viewport::input(c, &i));
        assert_eq!(self.status, "", "status line");
    }

    /// A left press at `at`, held moves through `path`, and the release.
    pub fn left_drag(&mut self, at: [f32; 2], path: &[[f32; 2]], shift: bool) {
        self.pass(input(Some(at), KeyState::Pressed, shift));
        for &p in path {
            self.pass(input(Some(p), KeyState::Held, shift));
        }
        let end = path.last().copied().unwrap_or(at);
        self.pass(input(Some(end), KeyState::Released, shift));
    }

    pub fn click(&mut self, at: [f32; 2], shift: bool) {
        self.left_drag(at, &[], shift);
    }

    pub fn run(&mut self, id: &str) {
        self.with(|c| c.run(id));
        assert_eq!(self.status, "", "{id}");
    }

    pub fn apply(&mut self, cmd: Command) {
        self.e.apply(cmd).unwrap();
        self.e.pump(0).unwrap();
    }

    pub fn state(&mut self) -> viewport::State {
        self.with(|c| viewport::state(c))
    }

    /// The saved view offsets `camera_state[3..5]`.
    pub fn offset(&self) -> [f32; 2] {
        let s = &self.e.doc.pmm.camera_state;
        [s[3], s[4]]
    }

    /// The selected model's marked bones and `selectedBone`.
    pub fn selection(&self) -> (Vec<usize>, i32) {
        let m = self.e.doc.selected_model().unwrap();
        let marks = (0..m.bone_pose.len())
            .filter(|&i| m.bone_pose[i].flags[2] != 0)
            .collect();
        (marks, m.selection.selected_bone)
    }

    pub fn pose(&self, bone: usize) -> ([f32; 3], [f32; 4]) {
        let p = &self.e.doc.selected_model().unwrap().bone_pose[bone];
        (p.translation, p.rotation)
    }

    /// Selects `bones`, the first as `selectedBone`.
    pub fn select(&mut self, bones: &[u32]) {
        self.apply(Command::SelectBones(bones.to_vec()));
    }

    /// The screen point of bone `k` on [`SIZE`].
    pub fn bone_at(&self, k: usize) -> [f32; 2] {
        let r = viewport::rig(&self.e).unwrap();
        let view = self.e.camera.view(SIZE[0] as u32, SIZE[1] as u32);
        let ([x, y], _) = viewport::screen(&r, &view, SIZE.map(|v| v as i32))[k].unwrap();
        [x as f32, y as f32]
    }
}

/// A left-button pass at `pos` on [`SIZE`].
pub fn input(pos: Option<[f32; 2]>, left: KeyState, shift: bool) -> viewport::Input {
    viewport::Input {
        pos,
        size: SIZE,
        left,
        right: KeyState::Idle,
        middle: KeyState::Idle,
        right_double_click: false,
        pixels: [0, 0],
        wheel: 0.0,
        shift,
        ctrl: false,
    }
}

pub fn close(a: &[f32], b: &[f32], what: &str) {
    assert!(
        a.iter().zip(b).all(|(x, y)| (x - y).abs() < 1e-5),
        "{what}: {a:?} != {b:?}"
    );
}
