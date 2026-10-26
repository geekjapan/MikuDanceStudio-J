//! The `mocap` area through the action table, without a window and without a sensor. Expected
//! values come from the C++ lines named at each test (`command_view_menu.cpp`, `wndproc.cpp`,
//! `app_defaults.cpp`).

mod labels;

use mds_app::actions::{self, Handler};
use mds_app::editor::Editor;
use mds_app::ui::mocap::{self, State, STAGE_RECORDING, STAGE_TIMER_MS, UNAVAILABLE};
use mds_app::ui::{Ctx, AREAS};
use mds_doc::Command;
use mds_kinect::joints::TrackedJoint;
use mds_kinect::register::INTERPOLATION;
use mds_kinect::{Bone, Capture, Fake, FakeHandle, PumpInput, Version};
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

    /// `OpenNiInit` succeeded on a fake sensor.
    fn start(&mut self, version: Version) -> FakeHandle {
        let (sensor, handle) = Fake::start(version);
        mocap::start_session(&mut self.ctx(0), sensor, false).unwrap();
        handle
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
            ..State::default()
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

/// `ManageKinectRecordGate` (`oni_skeleton_pump.cpp:545`): losing the performer (or leaving model
/// mode) unchecks 292 and clears the stage; the options are untouched. The depth map is asked for
/// whenever the stage is not 0.
#[test]
fn losing_the_sensor_drops_the_stage() {
    let mut rig = Rig::model_mode();
    let fake = rig.start(Version::V130);
    rig.pass(0);
    assert!(rig.state().tracking);
    assert_eq!(fake.state().depth_map, Some(false));
    rig.run("menu:292").unwrap();
    rig.run("menu:294").unwrap();
    rig.pass(10);
    assert_eq!(rig.state().stage, 1);
    assert_eq!(fake.state().depth_map, Some(true));
    fake.state().tracking = false;
    rig.pass(20);
    let st = rig.state();
    assert_eq!(
        (st.stage, st.tracking, st.lost_bone, st.mirror),
        (0, false, true, true)
    );
    assert_eq!(rig.run("menu:292"), Err(UNAVAILABLE.to_string()));
}

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("mocap", mocap::LABELS);
}

/// The end of a recording (`oni_skeleton_pump.cpp:510` to `:524`): `DisableKinect` drops the
/// stage, and the samples become keys of the bone from the current frame on, with the
/// interpolation 20/20/107/107 of `RegisterTraceBoneKey` (`:313`), as one undo entry.
#[test]
fn registering_a_capture_writes_the_keys_and_ends_the_stage() {
    let mut rig = Rig::model_mode();
    rig.track(true);
    rig.run("menu:292").unwrap();
    for now in [0, 1500, 3000, 4500] {
        rig.pass(now);
    }
    assert_eq!(rig.state().stage, STAGE_RECORDING);

    let keys: Vec<_> = (0..3)
        .map(|k| mds_kinect::KeyRegistration {
            bone: 1,
            frame: 5 + k,
            position: [k as f32, 2.0, 3.0],
            rotation: [0.0, 0.0, 0.5, 0.5],
        })
        .collect();
    let frames = |rig: &Rig| {
        let pool = &rig.editor.doc.selected_model().unwrap().bone_keys;
        let (mut i, mut out) = (1u32, Vec::new());
        loop {
            let k = pool.get(i).unwrap();
            out.push((k.frame, k.position, k.interpolation, k.allocated));
            if k.next == 0 {
                return out;
            }
            i = k.next;
        }
    };
    let before = frames(&rig);
    mocap::register_capture(&mut rig.ctx(5000), 5, 3, keys).unwrap();
    assert_eq!(rig.state().stage, 0);

    let after = frames(&rig);
    assert_eq!(after.len(), before.len() + 3);
    for (k, key) in after[before.len()..].iter().enumerate() {
        assert_eq!(key.0, 5 + k as u32);
        assert_eq!(key.1, [k as f32, 2.0, 3.0]);
        assert_eq!(key.2, mds_kinect::register::INTERPOLATION);
        assert_eq!(key.3, 1);
    }
    rig.editor.apply(Command::Undo).unwrap();
    assert_eq!(frames(&rig), before);
}

/// Model mode only: the C++ pump never runs in camera mode (`oni_skeleton_pump.cpp:472`).
#[test]
fn registering_a_capture_needs_model_mode() {
    let mut rig = Rig::new();
    assert!(mocap::register_capture(&mut rig.ctx(0), 0, 0, vec![]).is_err());
}

/// `OpenNiInit` checks 291 (`oni_kinect.cpp`); a second 291 is `DisableKinect`: `OpenNIClean`,
/// 291 unchecked, the stage cleared.
#[test]
fn the_kinect_item_stops_a_running_session() {
    let mut rig = Rig::model_mode();
    let fake = rig.start(Version::V140);
    assert!(rig.state().kinect);
    rig.pass(0);
    rig.run("menu:292").unwrap();
    fake.take_reads();
    rig.run("menu:291").unwrap();
    let st = rig.state();
    assert_eq!((st.kinect, st.stage, st.tracking), (false, 0, false));
    assert!(fake.state().stopped);
    rig.pass(10);
    assert!(fake.take_reads().is_empty() && !rig.state().tracking);
    assert_eq!(rig.run("menu:291"), Err(UNAVAILABLE.to_string()));
}

/// `PumpKinectSkeleton` (`oni_skeleton_pump.cpp:475`) runs only while tracking in model mode: in
/// camera mode the sensor is probed but no joint is read.
#[test]
fn the_pump_reads_the_joints_only_in_model_mode() {
    let mut rig = Rig::model_mode();
    let fake = rig.start(Version::V150);
    rig.pass(0);
    // `CaptureSkeletonJoints`: 0..=17, 18 and 19 from 1.40, 20..=22 for 1.50.
    assert_eq!(fake.take_reads(), (0..=22).collect::<Vec<_>>());
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    rig.pass(10);
    assert!(fake.take_reads().is_empty());
    assert!(rig.state().tracking);
}

/// A whole recording through the fake: 292, the timer to stage 4 (`wndproc.cpp:206`), three
/// recorded passes, 292 again, and the pass that sees the stage drop ends the session
/// (`DisableKinect`, `:512`) and registers the trace (`RegisterKinectPoseCapture`, `:318`): one run
/// of keys per standard bone the model has from the current frame on (`:256` to `:308`), with
/// interpolation 20/20/107/107 and allocated set (`:200` to `:206`), the max frame raised (`:300`),
/// one undo entry (`:338` to `:346`).
#[test]
fn a_recording_through_the_pump_registers_its_keys() {
    let mut rig = Rig::model_mode();
    rig.editor.apply(Command::SetFrame(10)).unwrap();
    let fake = rig.start(Version::V140);
    // The center at (900, 1800, 2700) mm: the センター key is that over the scale 90
    // (`ModelStandardPoseSetup`; chain8.pmx has no 左足, so the scale keeps its default).
    fake.state().joints[0] = [900.0, 1800.0, 2700.0];
    let keys_before = keys(&rig);
    rig.pass(0);
    rig.run("menu:292").unwrap();
    for now in [1500, 3000, 4500, 4501, 4502] {
        rig.pass(now);
    }
    assert_eq!(rig.state().stage, STAGE_RECORDING);
    rig.run("menu:292").unwrap();
    assert!(rig.editor.modified);
    let reference = reference_keys(&rig, &fake);
    rig.pass(4503);

    let st = rig.state();
    assert_eq!((st.kinect, st.stage), (false, 0));
    assert!(fake.state().stopped);
    let m = rig.editor.doc.selected_model().unwrap();
    assert!(m.selection.max_frame >= 12);
    let got = keys(&rig);
    // センター, 上半身 and 首 (1.40 adds the neck); the other five bones keep their keys.
    for bone in [1usize, 2, 3] {
        let run: Vec<_> = got[bone]
            .iter()
            .filter(|k| (10..13).contains(&k.0))
            .collect();
        assert_eq!(
            run.iter().map(|k| k.0).collect::<Vec<_>>(),
            [10, 11, 12],
            "bone {bone}"
        );
        for (k, want) in run.iter().zip(reference.iter().filter(|r| r.bone == bone)) {
            assert_eq!((k.1, k.2), (want.position, want.rotation), "bone {bone}");
            assert_eq!((k.3, k.4), (INTERPOLATION, 1), "bone {bone}");
        }
    }
    let center: Vec<_> = got[1]
        .iter()
        .filter(|k| k.0 >= 10)
        .map(|k| (k.1, k.2))
        .take(3)
        .collect();
    assert_eq!(center, [([10.0, 20.0, 30.0], [0.0, 0.0, 0.0, 1.0]); 3]);
    for bone in [0usize, 4, 5, 6, 7] {
        assert_eq!(got[bone], keys_before[bone], "bone {bone}");
    }

    rig.editor.apply(Command::Undo).unwrap();
    let undone = keys(&rig);
    for bone in 0..8 {
        let frames = |k: &Vec<Key>| k.iter().map(|k| (k.0, k.1, k.2)).collect::<Vec<_>>();
        assert_eq!(
            frames(&undone[bone]),
            frames(&keys_before[bone]),
            "bone {bone}"
        );
    }
}

/// `(frame, position, rotation, interpolation, allocated)` of a bone key.
type Key = (u32, [f32; 3], [f32; 4], [u8; 16], u8);

/// The bone tracks of the selected model, head first.
fn keys(rig: &Rig) -> Vec<Vec<Key>> {
    let m = rig.editor.doc.selected_model().unwrap();
    (0..m.bone_pose.len() as u32)
        .map(|head| {
            let (mut i, mut out) = (head, Vec::new());
            loop {
                let k = m.bone_keys.get(i).unwrap();
                out.push((
                    k.frame,
                    k.position,
                    k.rotation,
                    k.interpolation,
                    k.allocated,
                ));
                if k.next == 0 {
                    return out;
                }
                i = k.next;
            }
        })
        .collect()
}

/// What `mds_kinect` itself makes of the same four samples (the oracle-tested pose and register):
/// the keys the app's pump must hand over.
fn reference_keys(rig: &Rig, fake: &FakeHandle) -> Vec<mds_kinect::KeyRegistration> {
    let m = rig.editor.doc.selected_model().unwrap();
    let mut bones: Vec<Bone> = m
        .bone_names
        .iter()
        .zip(&rig.editor.physics.scene.models[0].bones)
        .map(|(n, b)| {
            let mut name = [0u8; 20];
            name[..n.raw.len()].copy_from_slice(&n.raw);
            Bone {
                name,
                bind_y: b.position[1],
                translation: [0.0; 3],
                rotation: [0.0, 0.0, 0.0, 1.0],
            }
        })
        .collect();
    let joints = fake.state().joints;
    let mut capture = Capture::new(14);
    let input = |stage| PumpInput {
        tracking: true,
        model_mode: true,
        frame_step_playback: false,
        fps: 0,
        stage,
        frame: 10,
        mirror: true,
        lost_bone: false,
    };
    let sensor = |id: i32, slot: &mut [f32; 3]| *slot = joints[id as usize];
    for _ in 0..3 {
        capture.pump(input(STAGE_RECORDING), sensor, &mut bones, &[]);
    }
    let keys = capture
        .pump(input(0), sensor, &mut bones, &[])
        .finished
        .unwrap();
    assert_eq!(keys.len(), 9);
    assert_eq!(
        capture.joints[TrackedJoint::Center],
        [900.0, 1800.0, 2700.0]
    );
    keys
}

/// `overlay_producers.cpp:162` to `:172`: the countdown cell 160 pixels left of the right edge and
/// 30 below the top, 40 x 60, showing 3, 2, 1; the stage 4 cell at 200 and 120, 120 x 20.
#[test]
fn the_stage_overlay_sits_where_the_cpp_draws_it() {
    let view = [100.0, 50.0, 1100.0, 800.0];
    let (rect, text, color) = mocap::countdown(view, 1).unwrap();
    assert_eq!(
        (rect.min.x, rect.min.y, rect.width(), rect.height()),
        (940.0, 80.0, 40.0, 60.0)
    );
    assert_eq!((text, color.a()), ("3", 0xBB));
    assert_eq!(mocap::countdown(view, 3).unwrap().1, "1");
    let (rect, _, color) = mocap::countdown(view, 4).unwrap();
    assert_eq!(
        (rect.min.x, rect.min.y, rect.width(), rect.height()),
        (900.0, 170.0, 120.0, 20.0)
    );
    assert_eq!(color.a(), 0xFF);
    assert!(mocap::countdown(view, 0).is_none());
}

/// `ui_viewport_refresh.cpp:144`: the inset from `right - 220` to `right - 60`, 120 high; the red
/// man stays inside it and draws only limbs whose joints are both seen.
#[test]
fn the_red_man_fits_the_depth_map_inset() {
    let view = [0.0, 20.0, 1000.0, 700.0];
    let inset = mocap::red_man_rect(view);
    assert_eq!(
        (inset.min.x, inset.min.y, inset.max.x, inset.max.y),
        (780.0, 20.0, 940.0, 140.0)
    );
    let mut j = mds_kinect::joints::Joints::default();
    assert!(mocap::red_man(view, &j).is_empty());
    j[TrackedJoint::Head] = [0.0, 700.0, 2000.0];
    j[TrackedJoint::Neck] = [0.0, 500.0, 2000.0];
    j[TrackedJoint::LeftShoulder] = [-200.0, 500.0, 2000.0];
    let lines = mocap::red_man(view, &j);
    assert_eq!(lines.len(), 2);
    assert!(lines.iter().flatten().all(|p| inset.contains(*p)));
    // The head is above the neck on screen.
    assert!(lines[0][0].y < lines[0][1].y);
}
