//! The `mocap` area through the action table, without a window and without a sensor. Expected
//! values come from the C++ lines named at each test (`command_view_menu.cpp`, `wndproc.cpp`,
//! `app_defaults.cpp`).

mod labels;

use mds_app::actions::{self, Handler};
use mds_app::editor::Editor;
use mds_app::ui::mocap::{self, State, STAGE_RECORDING, STAGE_TIMER_MS, UNAVAILABLE};
use mds_app::ui::{Ctx, AREAS};
use mds_doc::Command;
use std::path::PathBuf;

const IDS: [&str; 6] = [
    "menu:291", "menu:292", "menu:293", "menu:294", "menu:295", "menu:296",
];

struct Rig {
    editor: Editor,
    egui: egui::Context,
    status: String,
}

impl Rig {
    fn new() -> Rig {
        Rig {
            editor: Editor::empty(),
            egui: egui::Context::default(),
            status: String::new(),
        }
    }

    fn ctx(&mut self, now_ms: u64) -> Ctx<'_> {
        Ctx {
            editor: &mut self.editor,
            now_ms,
            egui: Some(self.egui.clone()),
            viewport: None,
            status: &mut self.status,
        }
    }

    fn run(&mut self, id: &str) -> Result<(), String> {
        actions::run(&mut self.ctx(0), id)
    }

    fn state(&self) -> State {
        mocap::state(&self.egui)
    }

    /// The pump has seen a performer: what `OpenNIIsTracking` sets each frame.
    fn track(&mut self, tracking: bool) {
        mocap::update(&self.egui, |s| s.tracking = tracking);
    }

    /// One window pass at `now_ms`.
    fn pass(&mut self, now_ms: u64) {
        let egui = self.egui.clone();
        let mut output = egui.run_ui(egui::RawInput::default(), |ui| {
            mocap::pass(ui, &mut self.ctx(now_ms));
        });
        output.textures_delta.clear();
    }

    /// A model is selected: model mode (the start-up scene is in camera mode).
    fn model_mode() -> Rig {
        let mut rig = Rig::new();
        let path = fixtures().join("chain8.pmx");
        rig.editor
            .apply(Command::LoadModel {
                path: "chain8.pmx".into(),
                data: std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display())),
            })
            .unwrap();
        assert_eq!(rig.editor.doc.pmm.settings.options[0], 0);
        rig.editor.modified = false;
        rig
    }
}

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

#[test]
fn every_row_has_a_run_action() {
    let rows: Vec<_> = mocap::actions().iter().map(|a| a.id).collect();
    assert_eq!(rows, IDS);
    assert!(mocap::actions()
        .iter()
        .all(|a| matches!(a.handler, Handler::Run(_))));
    assert!(AREAS.iter().any(|a| a.name == "mocap"));
}

/// `app_defaults.cpp:199` to `:201`: mirror 1, lost bone 0, red man 1; `ui_init.cpp:664` checks
/// 293 and 295 at start; the stage byte is 0.
#[test]
fn the_defaults_are_the_apps() {
    let rig = Rig::new();
    assert_eq!(
        rig.state(),
        State {
            stage: 0,
            stage_since_ms: 0,
            mirror: true,
            lost_bone: false,
            red_man: true,
            tracking: false,
        }
    );
}

/// `command_view_menu.cpp:1594`, `:1605`, `:1617`: each item flips its own byte.
#[test]
fn the_three_options_flip_their_own_flag() {
    type Flag = fn(&State) -> bool;
    let flags: [(&str, Flag); 3] = [
        ("menu:293", |s| s.mirror),
        ("menu:294", |s| s.lost_bone),
        ("menu:295", |s| s.red_man),
    ];
    for (id, flag) in flags {
        let mut rig = Rig::new();
        let before = rig.state();
        rig.run(id).unwrap();
        assert_eq!(flag(&rig.state()), !flag(&before), "{id}");
        let others: Vec<_> = flags
            .iter()
            .filter(|(o, _)| *o != id)
            .map(|(_, f)| f(&rig.state()) == f(&before))
            .collect();
        assert_eq!(others, [true, true], "{id} moved another option");
        rig.run(id).unwrap();
        assert_eq!(rig.state(), before, "{id} twice");
        assert!(!rig.editor.modified, "{id}: the C++ sets no SceneModified");
    }
}

/// `:1550` and `:1638` need a session, which this build cannot start; the status line gets the
/// text through `Ctx::run`, as a menu click does.
#[test]
fn the_device_rows_report_that_kinect_is_not_available() {
    let mut rig = Rig::model_mode();
    for id in ["menu:291", "menu:296"] {
        assert_eq!(rig.run(id), Err(UNAVAILABLE.to_string()), "{id}");
        rig.status.clear();
        rig.ctx(0).run(id);
        assert_eq!(rig.status, UNAVAILABLE, "{id}");
    }
    assert_eq!(UNAVAILABLE, "Kinect is not available on this system");
    assert!(!rig.editor.modified);
}

/// `command_view_menu.cpp:1638`: in camera mode the C++ shows "Please select model!" before the
/// file dialog (the Japanese text is `kMsgOpenOniJp`, `:374`, decoded from Shift-JIS).
#[test]
fn loading_an_oni_file_in_camera_mode_asks_for_a_model() {
    let mut rig = Rig::new();
    assert_eq!(rig.editor.doc.pmm.settings.options[0], 1);
    assert_eq!(
        rig.run("menu:296"),
        Err("カメラ・照明モードではoniデータは読めません".to_string())
    );
    rig.run("menu:260").unwrap();
    assert_eq!(rig.run("menu:296"), Err("Please select model!".to_string()));
}

/// `ManageKinectRecordGate` (`oni_skeleton_pump.cpp`) greys 292 unless a sensor tracks in model
/// mode; `ui_init.cpp:635` starts it greyed.
#[test]
fn the_record_item_needs_a_tracking_sensor_in_model_mode() {
    let mut rig = Rig::model_mode();
    assert_eq!(rig.run("menu:292"), Err(UNAVAILABLE.to_string()));
    assert_eq!(rig.state().stage, 0);
    rig.track(true);
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    assert_eq!(rig.run("menu:292"), Err(UNAVAILABLE.to_string()));
    assert_eq!(rig.state().stage, 0);
}

/// `:1565` to `:1592`: stage 0 becomes 1 (timer 101 armed); a second click stops it, marks the
/// scene modified. The start leaves `SceneModified` alone.
#[test]
fn the_record_item_starts_and_stops_the_countdown() {
    let mut rig = Rig::model_mode();
    rig.track(true);
    actions::run(&mut rig.ctx(700), "menu:292").unwrap();
    assert_eq!((rig.state().stage, rig.state().stage_since_ms), (1, 700));
    assert!(!rig.editor.modified);
    rig.run("menu:292").unwrap();
    assert_eq!(rig.state().stage, 0);
    assert!(rig.editor.modified);
}

/// `wndproc.cpp:206`: each `WM_TIMER` 101 adds one, re-arms 1500 ms later, and stops at 4.
#[test]
fn the_stage_timer_walks_to_four_and_stops() {
    let mut rig = Rig::model_mode();
    rig.track(true);
    actions::run(&mut rig.ctx(1000), "menu:292").unwrap();
    let mut seen = vec![];
    for now in [1000, 2499, 2500, 3999, 4000, 5500, 7000, 60_000] {
        rig.pass(now);
        seen.push(rig.state().stage);
    }
    assert_eq!(seen, [1, 1, 2, 2, 3, 4, 4, 4]);
    assert_eq!(STAGE_RECORDING, 4);
    assert_eq!(STAGE_TIMER_MS, 1500);
    assert_eq!(rig.state().stage_since_ms, 5500);
}

/// `ManageKinectRecordGate`: losing the performer (or leaving model mode) unchecks 292 and clears
/// the stage; the options are untouched.
#[test]
fn losing_the_sensor_drops_the_stage() {
    let mut rig = Rig::model_mode();
    rig.track(true);
    rig.run("menu:292").unwrap();
    rig.run("menu:294").unwrap();
    rig.pass(0);
    assert_eq!(rig.state().stage, 1);
    rig.track(false);
    rig.pass(10);
    let st = rig.state();
    assert_eq!((st.stage, st.lost_bone, st.mirror), (0, true, true));
}

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("mocap", mocap::LABELS);
}
