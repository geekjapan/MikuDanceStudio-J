use mds_app::{
    editor::Editor,
    navigation::KeyState,
    scene,
    ui::{
        viewport::{self, Input},
        Ctx,
    },
};
use mds_doc::{Command, GlobalTrack};

fn camera(e: &mut Editor, yaw: f32) {
    e.apply(Command::SetCamera {
        position: [0.0; 3],
        rotation: [0.0, yaw, 0.0],
        distance: -45.0,
        fov: 45.0,
        perspective: false,
    })
    .unwrap();
    e.apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]))
        .unwrap();
}

fn input(e: &mut Editor, right: bool, wheel: f32) {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: e,
        now_ms: 1000,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    viewport::input(
        &mut ctx,
        &Input {
            pos: Some([100.0, 100.0]),
            size: [640.0, 480.0],
            left: KeyState::Idle,
            right: if right {
                KeyState::Held
            } else {
                KeyState::Idle
            },
            middle: KeyState::Idle,
            right_double_click: false,
            pixels: [10, 0],
            wheel,
            shift: false,
            ctrl: false,
        },
    );
    assert!(status.is_empty(), "{status}");
}

fn clip(e: &Editor) -> [f32; 4] {
    e.with_frame([640, 480], &[[0.0; 2]], |f| f.view.clip([4.0, 7.0, -2.0]))
        .unwrap()
}

fn live_yaw() -> Editor {
    let mut e = Editor::empty();
    e.load_model(
        &std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/chain8.pmx"),
    )
    .unwrap();
    e.apply(Command::SetPhysicsMode(0)).unwrap();
    e.apply(Command::SelectCameraMode).unwrap();
    camera(&mut e, 0.0);
    e.seek(30).unwrap();
    camera(&mut e, 1.0);
    assert_eq!(scene::track_camera(&e.doc, 0).unwrap().rotation[1], 0.0);
    assert_eq!(scene::track_camera(&e.doc, 30).unwrap().rotation[1], 1.0);
    e.seek(0).unwrap();
    e.apply(Command::SelectModel(0)).unwrap();
    e.apply(Command::SetFollowCamera(true)).unwrap();
    e.options.from_current = true;
    e.options.stop_frame = 90;
    e.toggle_play(0).unwrap();
    e.pump(1000).unwrap();
    assert!(e.playing());
    assert_eq!(e.shown_frame(), 30);
    assert_eq!(e.current_frame(), 0);
    assert_eq!(e.doc.camera_controls().rotation[1], 1.0);
    assert_eq!(scene::state_camera(&e.doc).rotation[1], 1.0);
    e
}

#[test]
fn live_drag_and_track_off_keep_current_raw_camera() {
    let mut e = live_yaw();
    let before = clip(&e);
    input(&mut e, true, 0.0);
    let raw = scene::state_camera(&e.doc);
    let mut native = raw;
    native.rotation[1] = 0.9;
    let actual = clip(&e);
    let expected = native.view(640, 480).clip([4.0, 7.0, -2.0]);
    println!("DRAG keys=[(0,0),(30,1)] playing={} shown={} stored_frame={} before_clip={before:?} raw_after={} actual_clip={actual:?} native_raw_expected=0.9 native_clip_expected={expected:?}", e.playing(), e.shown_frame(), e.current_frame(), raw.rotation[1]);
    assert!((raw.rotation[1] - 0.9).abs() < 0.00001);
    assert_eq!(actual, expected);
    let mut e = live_yaw();
    let before = clip(&e);
    e.apply(Command::SetFollowCamera(false)).unwrap();
    let immediately = clip(&e);
    e.pump(1001).unwrap();
    let after = clip(&e);
    println!("TRACK_OFF shown={} raw_yaw={} before_clip={before:?} immediate_clip={immediately:?} next_pump_clip={after:?} native_expected_clip={before:?}", e.shown_frame(), scene::state_camera(&e.doc).rotation[1]);
    assert_eq!(immediately, before);
    assert_eq!(after, before);
    assert!(
        (raw.rotation[1] - 0.9).abs() < 0.00001,
        "live drag uses evaluated yaw and Track-off retains it"
    );
}

#[test]
fn live_parent_transition_wheel_uses_current_raw_parent() {
    let mut observations = Vec::new();
    for ms in [400, 734] {
        let mut e = Editor::empty();
        let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/chain8.pmx");
        for _ in 0..2 {
            e.load_model(&path).unwrap();
        }
        e.apply(Command::SetPhysicsMode(0)).unwrap();
        e.apply(Command::SelectModel(1)).unwrap();
        e.apply(Command::SetBonePose {
            bone: 0,
            translation: [20.0, 0.0, 0.0],
            rotation: [0.0, 0.0, 0.0, 1.0],
        })
        .unwrap();
        e.apply(Command::RegisterBoneKeys).unwrap();
        e.pump(0).unwrap();
        e.apply(Command::SelectCameraMode).unwrap();
        for (frame, parent) in [(0, Some(0)), (10, Some(1)), (20, None)] {
            e.seek(frame).unwrap();
            e.apply(Command::SetCameraParentModel(parent)).unwrap();
            e.apply(Command::SetCameraParentBone(2)).unwrap();
            camera(&mut e, 0.0);
        }
        e.seek(0).unwrap();
        e.options.from_current = true;
        e.options.stop_frame = 60;
        e.toggle_play(0).unwrap();
        e.pump(ms).unwrap();
        assert!(e.playing());
        assert!(e.shown_frame() >= if ms == 400 { 10 } else { 20 });
        let (live, parent) = mds_render::scene::camera_with_parent_at(
            &e.doc.pmm,
            e.shown_frame(),
            mds_scene::track::CameraMode::Playback,
        )
        .unwrap();
        assert_eq!(parent[0], if ms == 400 { 1 } else { -1 });
        assert_eq!(e.doc.pmm.appearance.camera_parent_model, parent[0]);
        let before = clip(&e);
        let stored_before = scene::state_camera(&e.doc);
        let mut native_camera = *e.camera_frame();
        native_camera.distance += 6.0;
        let expected_clip = native_camera.view(640, 480).clip([4.0, 7.0, -2.0]);
        input(&mut e, false, 120.0);
        let after = scene::state_camera(&e.doc);
        let actual = clip(&e);
        let native_z = live.target[2] + if parent[0] >= 0 { 6.0 } else { 0.0 };
        let native_distance = if parent[0] >= 0 {
            native_z
        } else {
            live.distance + 6.0
        };
        println!("PARENT_WHEEL ms={ms} shown={} live_parent={parent:?} stored_parent={} live_raw={live:?} stored_before={stored_before:?} stored_after={after:?} before_clip={before:?} after_clip={actual:?} native_expected_z={native_z} native_expected_distance={native_distance} native_expected_clip={expected_clip:?}", e.shown_frame(), e.doc.pmm.appearance.camera_parent_model);
        assert!((after.target[2] - native_z).abs() < 0.00001);
        assert_eq!(after.distance, native_distance);
        assert_eq!(
            actual, expected_clip,
            "live parent attachment must survive the wheel input"
        );
        observations.push((
            parent[0],
            after.target[2],
            after.distance,
            native_z,
            native_distance,
        ));
    }
    assert!(
        observations
            .iter()
            .all(|(_, z, d, nz, nd)| (z - nz).abs() < 0.00001 && (d - nd).abs() < 0.00001),
        "wheel must use current parent including track detachment: {observations:?}"
    );
}

#[test]
fn terminal_manual_edit_gate_and_loop_keep_native_cursor_lifetime() {
    let mut e = live_yaw();
    assert_eq!(e.doc.camera_controls().rotation[1], 1.0);
    e.pump(1001).unwrap();
    e.edit_camera_controls(|c| c.rotation[1] = 0.7).unwrap();
    e.pump(1100).unwrap();
    assert_eq!(e.doc.camera_controls().rotation[1], 0.7);
    e.apply(Command::SetFollowCamera(false)).unwrap();
    e.pump(1200).unwrap();
    assert_eq!(e.doc.camera_controls().rotation[1], 0.7);
    e.apply(Command::SetFollowCamera(true)).unwrap();
    e.edit_camera_controls(|c| c.rotation[1] = 0.6).unwrap();
    e.pump(1300).unwrap();
    assert_eq!(
        e.doc.camera_controls().rotation[1],
        0.6,
        "Follow-on must not reactivate the expired track"
    );
    e.options.looped = true;
    e.pump(3100).unwrap();
    assert_eq!(
        e.doc.camera_controls().rotation[1],
        0.0,
        "loop restarts camera from the head"
    );
}

#[test]
fn fractional_raw_state_is_saved_and_registered_without_render_feedback() {
    let mut e = live_yaw();
    e.toggle_play(1000).unwrap();
    e.seek(0).unwrap();
    e.modified = false;
    let keys = e.doc.pmm.camera.records().len();
    e.toggle_play(2000).unwrap();
    e.pump(2517).unwrap();
    let cursor = e.playback.unwrap().cursor;
    let at = mds_scene::playback_frame(cursor).unwrap();
    assert_ne!(at, at.floor());
    let sample = mds_scene::track::evaluate_camera(
        &e.doc.pmm.camera,
        at,
        mds_scene::track::CameraMode::Playback,
    )
    .unwrap();
    assert_eq!(e.doc.camera_controls().rotation, sample.rotation);
    assert_eq!(e.doc.pmm.camera.records().len(), keys);
    assert!(!e.modified);
    let saved = e.doc.save().unwrap();
    let pmm = mds_formats::pmm::Pmm::read(&saved).unwrap();
    assert_eq!(pmm.camera_state, e.doc.pmm.camera_state);
    e.apply(Command::SetFollowCamera(false)).unwrap();
    e.toggle_play(2518).unwrap();
    e.apply(Command::SelectCameraMode).unwrap();
    e.edit_camera_controls(|c| {
        c.target = [7.0, 8.0, 9.0];
        c.rotation = [0.3, 0.8, 0.4];
    })
    .unwrap();
    let current = e.doc.camera_controls();
    e.apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]))
        .unwrap();
    let registered = scene::track_camera(&e.doc, e.current_frame()).unwrap();
    assert_eq!(registered.target, current.target);
    assert_eq!(registered.rotation, current.rotation);
}

#[test]
fn follow_gate_reopens_without_reinitializing_active_cursor() {
    let mut e = live_yaw();
    e.apply(Command::SetFollowCamera(false)).unwrap();
    e.edit_camera_controls(|c| c.rotation[1] = 0.7).unwrap();
    e.pump(1100).unwrap();
    assert_eq!(e.doc.camera_controls().rotation[1], 0.7);
    e.apply(Command::SetFollowCamera(true)).unwrap();
    e.pump(1200).unwrap();
    assert_eq!(e.doc.camera_controls().rotation[1], 1.0);
    e.edit_camera_controls(|c| c.rotation[1] = 0.6).unwrap();
    e.pump(1300).unwrap();
    assert_eq!(e.doc.camera_controls().rotation[1], 0.6);
}

#[test]
fn stop_clears_parent_for_both_playhead_settings_and_keeps_free_raw_state() {
    for at_playhead in [false, true] {
        let mut e = live_yaw();
        e.apply(Command::SetFollowCamera(false)).unwrap();
        e.apply(Command::SetCameraParentModel(Some(0))).unwrap();
        let before = e.doc.pmm.camera_state;
        e.options.stop_at_playhead = at_playhead;
        e.toggle_play(1000).unwrap();
        assert!(!e.playing());
        assert_eq!(e.doc.pmm.appearance.camera_parent_model, -1);
        assert_eq!(e.current_frame(), if at_playhead { 30 } else { 0 });
        assert_eq!(e.doc.pmm.camera_state, before);
    }
}
