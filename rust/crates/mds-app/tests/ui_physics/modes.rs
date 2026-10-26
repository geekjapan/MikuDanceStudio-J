//! The mode radios 265, 269, 270 and 272, the floor 285 and the check box 499
//! (`command_view_menu.cpp:1048` to `:1110` and `:1437`; `model_keyframe_edit.cpp:277`).

use crate::rig::Rig;
use mds_app::ui::physics;
use mds_doc::Command;

const RADIOS: [(&str, u8); 4] = [
    ("menu:265", 1),
    ("menu:269", 2),
    ("menu:270", 3),
    ("menu:272", 0),
];

/// `PlaybackPhysicsMode() = mode` and `ModelKinematicSync` of every model: the document's mode
/// and the live world's agree, `StopPlayback` puts the mode back (`playback_state.cpp:379`), and
/// no radio sets `SceneModified`.
#[test]
fn a_radio_sets_the_playback_mode_of_the_document_and_the_world() {
    for (id, mode) in RADIOS {
        // 270 is greyed for a PMX model, which swing600 has.
        let mut r = if id == "menu:270" {
            Rig::pmd()
        } else {
            Rig::open("swing600.pmm")
        };
        r.editor.modified = false;
        r.run(id).unwrap();
        assert_eq!(r.editor.doc.pmm.physics.playback_mode, mode, "{id}");
        assert_eq!(r.editor.physics.scene.physics_mode, i32::from(mode), "{id}");
        assert!(!r.editor.modified, "{id}");

        r.run("menu:271").unwrap();
        r.run("ctl:408").unwrap();
        assert_eq!(r.editor.physics.scene.physics_mode, 2, "{id}: playing");
        r.run("ctl:408").unwrap();
        assert_eq!(
            r.editor.physics.scene.physics_mode,
            i32::from(mode),
            "{id}: the saved mode is the new one"
        );
    }
}

/// Modes 1 to 3 set `PhysicsResetPending`; 0 does not. A settle seats the bodies on the pose.
#[test]
fn modes_1_to_3_settle_the_bodies() {
    let origin = |r: &Rig| {
        let m = &r.editor.physics.scene.models[0];
        physics::world_poses(&r.editor)[&(m.slot, 7)].0[12..15].to_vec()
    };
    let far = |a: &[f32], b: &[f32]| (0..3).map(|c| (a[c] - b[c]).powi(2)).sum::<f32>().sqrt();
    for id in ["menu:265", "menu:269"] {
        let mut r = Rig::open("swing600.pmm");
        r.editor.physics.tick(0.0).unwrap();
        let bind = origin(&r);
        for _ in 0..38 {
            r.editor.physics.tick(1.0 / 30.0).unwrap();
        }
        let swung = origin(&r);
        assert!(far(&swung, &bind) > 0.5, "{id}: the body did not swing");
        r.run(id).unwrap();
        r.editor.physics.tick(0.0).unwrap();
        assert!(far(&origin(&r), &bind) < far(&swung, &bind) / 2.0, "{id}");
    }
}

/// `SetPhysicsMenuState` (`playback_state.cpp:46`) greys the third item while playing
/// (`:77`), in camera mode (`ui_model_reload.cpp:474`) and for a PMX model (`:553`); the other
/// radios stay enabled while playing.
#[test]
fn trace_mode_is_greyed_while_playing_in_camera_mode_and_for_a_pmx() {
    let mut r = Rig::open("swing600.pmm");
    let before = r.editor.doc.pmm.physics.playback_mode;
    assert_eq!(
        r.run("menu:270"),
        Err("menu:270: not for a PMX model".into())
    );
    assert_eq!(r.editor.doc.pmm.physics.playback_mode, before);

    let mut r = Rig::pmd();
    r.run("menu:270").unwrap();
    r.run("ctl:408").unwrap();
    assert_eq!(r.run("menu:270"), Err("menu:270: not while playing".into()));
    for id in ["menu:265", "menu:269", "menu:272"] {
        r.run(id).unwrap();
    }
    r.run("ctl:408").unwrap();

    r.editor.apply(Command::SelectCameraMode).unwrap();
    assert_eq!(r.run("menu:270"), Err("menu:270: model mode only".into()));
}

/// The floor flips (`command_view_menu.cpp:1437`: `floorVisible` 1 to 0 and back) and is saved.
#[test]
fn the_floor_flips_the_flag_and_it_is_saved() {
    let mut r = Rig::open("swing600.pmm");
    r.editor.modified = false;
    let was = r.editor.doc.pmm.appearance.floor_visible != 0;
    let saved = |r: &Rig| {
        let data = r.editor.doc.save().unwrap();
        mds_doc::Document::load(&data, |_| None)
            .map(|d| d.pmm.appearance.floor_visible)
            .unwrap_or_else(|e| panic!("{e:?}"))
    };
    r.run("menu:285").unwrap();
    assert_eq!(r.editor.doc.pmm.appearance.floor_visible != 0, !was);
    assert_eq!(saved(&r) != 0, !was);
    r.run("menu:285").unwrap();
    assert_eq!(r.editor.doc.pmm.appearance.floor_visible != 0, was);
    assert!(!r.editor.modified);
}

/// Check box 499 flips `EditState::physics_checkbox`; "register" stores the negated box as the
/// key's `physicsDisabled` for a bone with a rigid body (`model_keyframe_edit.cpp:277` to
/// `:283`).
#[test]
fn the_check_box_decides_physics_disabled_of_the_registered_key() {
    let mut r = Rig::open("swing600.pmm");
    assert!(r.editor.doc.edit.physics_checkbox);
    let disabled_at = |r: &Rig, frame: u32| {
        let pool = &r.editor.doc.selected_model().unwrap().bone_keys;
        let (mut i, mut found) = (7u32, None);
        loop {
            let k = pool.get(i).unwrap();
            if k.frame == frame {
                found = Some(k.physics_disabled);
            }
            if k.next as i32 <= 0 {
                return found.unwrap_or_else(|| panic!("no key at {frame}"));
            }
            i = k.next;
        }
    };
    r.editor.apply(Command::SetFrame(10)).unwrap();
    r.run("menu:273").unwrap();
    r.run("ctl:499").unwrap();
    assert!(!r.editor.doc.edit.physics_checkbox);
    r.editor.apply(Command::RegisterBoneKeys).unwrap();
    assert_eq!(disabled_at(&r, 10), 1);
    r.editor.apply(Command::SetFrame(20)).unwrap();
    r.run("menu:273").unwrap();
    r.run("ctl:499").unwrap();
    assert!(r.editor.doc.edit.physics_checkbox);
    r.editor.apply(Command::RegisterBoneKeys).unwrap();
    assert_eq!(disabled_at(&r, 20), 0);
}

/// `PhysicsScene::body_poses` replaces the parse of the trace: one pose per rigid body, and the
/// first body's matrix is the pose Bullet reports.
#[test]
fn the_world_poses_come_from_the_body_getter() {
    let mut r = Rig::open("swing600.pmm");
    r.editor.physics.tick(1.0 / 30.0).unwrap();
    let bodies: usize = r
        .editor
        .physics
        .scene
        .models
        .iter()
        .map(|m| m.rigids.len())
        .sum();
    let poses = physics::world_poses(&r.editor);
    assert_eq!(poses.len(), bodies);
    let raw = r.editor.physics.body_poses().unwrap();
    let slot = r.editor.physics.scene.models[0].slot;
    let (origin, _) = raw[0][0].unwrap();
    assert_eq!(poses[&(slot, 0)].0[12..15], origin);
}
