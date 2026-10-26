//! The editor's derived state against the C++ frame loop: the view camera after a camera edit,
//! edits while playing, the modified flag, a model load, the startup scene, and gate A of the
//! physics with menu 299 on.

use super::{fixtures, run, scratch, stage_golden2};
use mds_app::editor::Editor;
use mds_app::scene;
use mds_doc::{Command, GlobalTrack};
use mds_render::Camera;

fn open(name: &str) -> Editor {
    Editor::open(&fixtures().join(name)).unwrap_or_else(|e| panic!("{name}: {e}"))
}

/// `CommitEditControl` writes the camera state and `PostViewRefresh` draws it; only the
/// register button (452) writes a key (`src/window/ui_edit_commit.cpp`,
/// `src/model/global_key_registration.cpp`).
#[test]
fn a_camera_edit_shows_before_it_is_registered() {
    let mut e = open("camera3.pmm");
    e.apply(Command::SelectCameraMode).unwrap();
    e.seek(10).unwrap();
    let track = scene::track_camera(&e.doc, 10).unwrap();
    assert_eq!(e.camera, track);
    let edited = Camera {
        target: [1.0, 2.0, 3.0],
        rotation: [0.25, 0.5, 0.0],
        distance: -30.0,
        fov_deg: 40.0,
        orthographic: false,
    };
    e.apply(Command::SetCamera {
        position: edited.target,
        rotation: edited.rotation,
        distance: edited.distance,
        fov: edited.fov_deg,
        perspective: false,
    })
    .unwrap();
    assert_eq!(e.camera, edited, "the view draws the edited state");
    assert_eq!(
        scene::track_camera(&e.doc, 10).unwrap(),
        track,
        "no key yet"
    );
    e.apply(Command::SetLight {
        color: [0.5; 3],
        direction: [0.0, -1.0, 0.0],
    })
    .unwrap();
    assert_eq!(e.camera, edited, "another edit keeps the edited view");
    e.apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]))
        .unwrap();
    assert_eq!(scene::track_camera(&e.doc, 10).unwrap(), edited);
    e.seek(0).unwrap();
    assert_eq!(e.camera, scene::track_camera(&e.doc, 0).unwrap());
}

/// Plays `name` for `passes` window passes after `edit_at`, with `edit` applied there, and
/// returns the physics trace of every pass.
fn play(name: &str, edit: Option<Command>) -> String {
    let mut e = open(name);
    let mut trace = String::new();
    e.toggle_play(0).unwrap();
    for pass in 1..=30u64 {
        if pass == 10 {
            if let Some(c) = edit.clone() {
                e.apply(c).unwrap();
            }
        }
        e.pump(pass * 33).unwrap();
        e.physics.write_frame(&mut trace, e.shown_frame()).unwrap();
    }
    assert!(e.playing() && e.shown_frame() > 20);
    trace
}

/// An edit while playing moves no physics: no seek and no settle mid-playback.
#[test]
fn an_edit_while_playing_does_not_seek_the_world() {
    let plain = play("swing600-golden.pmm", None);
    let edited = play(
        "swing600-golden.pmm",
        Some(Command::SetLight {
            color: [0.25; 3],
            direction: [0.5, -1.0, 0.0],
        }),
    );
    assert!(plain.lines().filter(|l| l.contains(" rigid ")).count() > 100);
    assert!(
        plain == edited,
        "the edit changed the physics of the playback"
    );
}

/// `MorphRowSelect`, the accessory combo (471), a click on the frame strip, a display group
/// fold, the edit mode, the bone selections, the pose copy, the follow-camera switch and the
/// morph reset do not set `SceneModified`.
#[test]
fn selections_leave_the_scene_unmodified() {
    let dir = scratch("selections");
    stage_golden2(&dir);
    let mut e = Editor::open(&dir.join("accessory.pmm")).unwrap();
    let slot = e.doc.pmm.accessories[1].slot;
    e.apply(Command::SelectAccessory(slot)).unwrap();
    assert!(!e.modified);
    let mut e = open("swing600.pmm");
    e.apply(Command::SelectModel(e.doc.pmm.models[1].slot))
        .unwrap();
    e.apply(Command::SelectMorphLane { lane: 2, morph: 0 })
        .unwrap();
    let camera = e.camera;
    e.apply(Command::ClickFrame(7)).unwrap();
    assert_eq!(e.doc.pmm.timeline.current_frame, 7, "a click seeks");
    // The model view does not follow the camera track (`cameraView`,
    // `src/render/debug_geometry.cpp:476`).
    assert_eq!(e.camera, camera);
    let grouped = e
        .doc
        .pmm
        .models
        .iter()
        .find(|m| m.group_count > 1)
        .unwrap()
        .slot;
    e.apply(Command::SelectModel(grouped)).unwrap();
    e.apply(Command::ToggleDisplayGroup(1)).unwrap();
    for c in [
        Command::SetEditMode(1),
        Command::SelectAllBones,
        Command::SelectUnregisteredBones,
        Command::CopyBonePose,
        Command::SetFollowCamera(false),
        Command::ResetMorphs,
    ] {
        e.apply(c.clone())
            .unwrap_or_else(|err| panic!("{c:?}: {err}"));
    }
    assert!(!e.modified, "a strip click and a group fold are no edits");
    e.apply(Command::SetFrame(3)).unwrap();
    e.apply(Command::RegisterBoneKeys).unwrap();
    assert!(e.modified, "an edit still sets it");
    std::fs::remove_dir_all(&dir).unwrap();
}

/// `LoadModelFile` (`src/model/add_model.cpp`): the first free slot, selected, model mode; the
/// world gets the model's bodies; the scene then saves as the C++ `motion.txt` saves after the
/// same load.
#[test]
fn load_model_adds_a_drawn_model_with_physics() {
    let mut e = Editor::empty();
    let opens = e.physics_opens;
    e.load_model(&fixtures().join("chain8.pmx")).unwrap();
    e.load_model(&fixtures().join("morph4.pmx")).unwrap();
    let p = &e.doc.pmm;
    let slots: Vec<_> = p.models.iter().map(|m| m.slot).collect();
    assert_eq!(slots, [0, 1]);
    assert_eq!((p.selected_model_slot, p.settings.options[0]), (1, 0));
    assert!(e.modified);
    assert_eq!(e.physics_opens, opens + 2);
    assert_eq!(e.physics.scene.models.len(), 2);
    let rigid = |s: u8| e.physics.scene.models.iter().find(|m| m.slot == s).unwrap();
    assert!(
        !rigid(0).rigids.is_empty(),
        "chain8 has bodies in the world"
    );
    let covered = e
        .with_frame([64, 64], &[[0.0, 0.0]], |_| ())
        .map(|()| true)
        .unwrap();
    assert!(covered);
}

/// The startup scene saves as the C++ application saves it on start (`empty.txt`), with
/// automatic interpolation on (`checkPhysicsFrame`, `src/window/window_init.cpp`).
#[test]
fn the_startup_scene_is_the_cpp_startup() {
    let e = Editor::empty();
    let want = std::fs::read(fixtures().join("script/expected/empty/empty.pmm")).unwrap();
    assert!(e.doc.save().unwrap() == want);
    assert!(e.doc.edit.auto_interpolation && e.doc.edit.physics_checkbox);
    let opened = open("swing600.pmm");
    assert!(opened.doc.edit.auto_interpolation);
    assert!(run(&mut Editor::empty(), "menu:204").is_ok());
}

/// A bone pose edit (`BonePosEdit`, `BoneRotEdit`, the viewport drags) stays on screen through
/// the frame loop until it is registered or the frame changes; the frame change shows the keys
/// again.
#[test]
fn an_unregistered_pose_edit_stays_on_screen() {
    let mut e = Editor::new(mds_doc::Document::startup(), Some(fixtures().join("x.pmm"))).unwrap();
    e.load_model(std::path::Path::new("chain8.pmx")).unwrap();
    let slot = e.doc.pmm.models[0].slot;
    let bone = 3;
    let rotation = [0.0, 0.38268343, 0.0, 0.9238795];
    e.apply(Command::SetBonePose {
        bone,
        translation: [0.0; 3],
        rotation,
    })
    .unwrap();
    for t in 1..=5 {
        e.pump(t * 33).unwrap();
    }
    let live = |e: &Editor| {
        let m = e
            .physics
            .scene
            .models
            .iter()
            .find(|m| m.slot == slot)
            .unwrap();
        m.bones[bone as usize].rot_quat
    };
    assert_eq!(live(&e), rotation, "the edited pose is shown");
    e.seek(5).unwrap();
    e.pump(200).unwrap();
    assert_eq!(
        live(&e),
        [0.0, 0.0, 0.0, 1.0],
        "the keys' pose at another frame"
    );
}

/// The model view (`src/render/debug_geometry.cpp:472` to `:566`): the camera state's rotation
/// and distance about the reference point (the origin in mode 0), the eye moved by the view
/// offsets `camera_state[3..5]`. A document that opens in it shows its offsets, and the pans
/// (`SetViewOffset` and the moved view) survive a seek and a frame step, which move the camera
/// state in camera mode only.
#[test]
fn the_model_view_keeps_its_view_offsets() {
    let mut e = open("swing600.pmm");
    assert_eq!(e.doc.pmm.settings.options[0], 0, "model mode");
    e.doc.pmm.camera_state[3] = 2.0;
    e.doc.pmm.camera_state[4] = 5.0;
    let s = e.doc.pmm.camera_state;
    let reopened = Editor::new(e.doc.clone(), e.path.clone()).unwrap();
    let mut want = Camera {
        target: [0.0; 3],
        ..scene::state_camera(&e.doc)
    };
    mds_app::ui::viewport::pan_view_offset(&mut want, s[3], s[4]);
    assert_eq!(reopened.camera, want);
    assert_eq!(
        want.target,
        [2.0, 5.0, 0.0],
        "no rotation: the offsets are x and y"
    );

    let mut e = reopened;
    e.apply(Command::SetViewOffset([3.0, 4.0])).unwrap();
    mds_app::ui::viewport::pan_view_offset(&mut e.camera, 1.0, -1.0);
    let panned = e.camera;
    e.seek(20).unwrap();
    e.step_frame(true).unwrap();
    assert_eq!(e.camera, panned);

    // Playback films the camera track only with tracking on (`cameraView`,
    // `debug_geometry.cpp:476`; `InitGlobalTracks`, `playback_state.cpp:327`).
    e.toggle_play(0).unwrap();
    for t in 1..10 {
        e.pump(t * 33).unwrap();
    }
    assert_eq!(e.camera, panned, "the model view while playing");
    e.toggle_play(330).unwrap();
    e.apply(Command::SetFollowCamera(true)).unwrap();
    e.toggle_play(400).unwrap();
    e.pump(433).unwrap();
    assert_eq!(
        e.camera,
        scene::track_camera(&e.doc, e.doc.pmm.timeline.current_frame as u32).unwrap()
    );
}

/// The mean color of the pixels the models cover, and their count.
fn model_pixels(e: &Editor, gpu: &mds_render::Gpu) -> (usize, [f32; 3]) {
    let px = e
        .with_stage([640, 360], &[[0.0, 0.0]], |f, s| {
            mds_render::render_frame_with(gpu, f, s)
        })
        .unwrap()
        .unwrap();
    let covered: Vec<&[u8]> = px.chunks(4).filter(|p| *p != scene::BACKGROUND).collect();
    let mut mean = [0.0; 3];
    for p in &covered {
        for c in 0..3 {
            mean[c] += f32::from(p[c]) / covered.len() as f32;
        }
    }
    (covered.len(), mean)
}

/// The model view of `swing600-golden.pmm` plays at the camera state it saved, yaw 0: the front
/// view (`ResetViewPreset(Front)`, `command_frame_edit.cpp:1403`), which looks at the backs of the
/// strips (its camera key is turned half a turn to face their fronts, `golden/README.md`). An
/// opaque PMD material culls its back faces (`model_renderers.cpp:869-882`) and the edge pass
/// draws the back faces of the hull (`D3DCULL_CW`, `:1312`), so the strips show their black edge
/// color only. The back view faces their fronts, which are lit.
#[test]
fn the_front_view_of_the_golden_strips_shows_their_edge_color() {
    let Some(gpu) = mds_render::Gpu::new().expect("device") else {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    };
    let mut e = open("swing600-golden.pmm");
    e.toggle_play(0).unwrap();
    e.pump(33).unwrap();
    assert_eq!(
        e.camera.rotation, [0.0; 3],
        "the saved model view while playing"
    );
    let (n, front) = model_pixels(&e, &gpu);
    assert!(n > 1000 && front == [0.0; 3], "front: {n} px of {front:?}");
    e.toggle_play(66).unwrap();
    run(&mut e, "ctl:403").unwrap();
    let (n, back) = model_pixels(&e, &gpu);
    assert!(
        n > 1000 && back.iter().all(|&c| c > 100.0),
        "back: {n} px of {back:?}"
    );
}

/// Gate A of `PhysicsFrame` (`physics_frame.cpp:688`) with menu 299 on: `AdvanceFrameRenderGate`
/// (`frame_driver.cpp:61-77`) walks the message counter 1, 2, 3, 0 when nothing holds it, so the
/// third stopped pump after the last message runs no physics, and a message opens it again. With
/// 299 off (the start-up state, `app_defaults.cpp:215`) every pump runs it.
#[test]
fn low_power_stops_the_idle_physics_two_pumps_after_the_last_message() {
    let opened = || {
        let mut e = Editor::empty();
        e.pump(0).unwrap();
        e.adopt(open("swing600.pmm")).unwrap();
        e.seek(300).unwrap();
        e
    };
    let (mut on, mut off) = (opened(), opened());
    on.low_power = true;
    on.message();
    let mut now = 0;
    let mut pump = |on: &mut Editor, off: &mut Editor| {
        now += 33;
        on.pump(now).unwrap();
        off.pump(now).unwrap();
        (
            on.physics.body_poses().unwrap(),
            off.physics.body_poses().unwrap(),
        )
    };
    let mut last = pump(&mut on, &mut off);
    assert!(last.0 == last.1);
    for pass in 2..=4 {
        let poses = pump(&mut on, &mut off);
        assert!(poses.1 != last.1, "pass {pass}: the bodies move");
        match pass {
            2 => assert!(poses.0 == poses.1, "pass 2 runs"),
            _ => assert!(poses.0 == last.0, "pass {pass} is gated"),
        }
        last = poses;
    }
    on.message();
    let poses = pump(&mut on, &mut off);
    assert!(poses.0 != last.0, "a message opens the gate");
}

/// The PMM named on the command line loads before the first paint (`window_init.cpp:402`, then
/// `UpdateWindow` at `:423`), into a world whose substep clock still holds its first 1/60 s; a
/// File > Open loads into the world that paint stepped. The two differ from the first tick.
#[test]
fn the_command_line_load_gets_the_fresh_world() {
    let path = fixtures().join("swing600.pmm");
    let read = |p: &str| std::fs::read(fixtures().join(p)).map_err(|e| e.to_string());
    let pmm = mds_formats::pmm::Pmm::read(&std::fs::read(&path).unwrap()).unwrap();
    let mut fresh = mds_physics::PhysicsScene::open(&pmm, read).unwrap();
    let (mut startup, mut opened) = (Editor::startup(&path).unwrap(), open("swing600.pmm"));
    fresh.seek(300);
    for e in [&mut startup, &mut opened] {
        e.seek(300).unwrap();
        e.pump(0).unwrap();
        e.pump(33).unwrap();
    }
    fresh.tick(0.0).unwrap();
    fresh.tick(0.033).unwrap();
    let poses = |e: &Editor| e.physics.body_poses().unwrap();
    assert!(poses(&startup) == fresh.body_poses().unwrap());
    assert!(poses(&startup) != poses(&opened));
}

/// The light drawn: in model mode the light state stays during playback with camera tracking off,
/// because `PlaybackPoseAdvance` plays the light track only behind the camera's gate
/// (`timeline_advance.cpp:389-394`, `CameraMode() || followCameraEnabled`) and `UpdateBoneFrames`
/// starts the global tracks only there (`playback_state.cpp:327`); with tracking on the playback
/// plays the track, and camera mode shows the track at the frame.
#[test]
fn the_light_track_plays_only_behind_the_camera_gate() {
    let mut e = open("swing600.pmm");
    if e.doc.pmm.settings.options[0] != 0 {
        e.apply(Command::SelectModel(e.doc.pmm.models[0].slot))
            .unwrap();
    }
    e.doc.pmm.appearance.follow_camera = 0;
    let state = mds_render::Light {
        color: [0.25, 0.5, 0.75],
        direction: [1.0, -0.5, 0.0],
    };
    e.apply(Command::SetLight {
        color: state.color,
        direction: state.direction,
    })
    .unwrap();
    let track = |e: &Editor| mds_render::scene::light_at(&e.doc.pmm, e.shown_frame()).unwrap();
    let drawn = |e: &Editor| e.with_frame([8, 8], &[[0.0, 0.0]], |f| f.light).unwrap();
    assert!(track(&e) != state, "the state is not the track's");
    assert_eq!(drawn(&e), state, "model mode, stopped");
    e.toggle_play(0).unwrap();
    e.pump(500).unwrap();
    assert_eq!(drawn(&e), state, "model mode, playing, tracking off");
    e.doc.pmm.appearance.follow_camera = 1;
    assert_eq!(drawn(&e), track(&e), "tracking on, playing");
    e.toggle_play(500).unwrap();
    assert_eq!(drawn(&e), state, "tracking on, stopped");
    e.apply(Command::SelectCameraMode).unwrap();
    assert_eq!(drawn(&e), track(&e), "camera mode");
}
