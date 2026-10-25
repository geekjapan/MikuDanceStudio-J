//! The editor's derived state against the C++ frame loop: the view camera after a camera edit,
//! edits while playing, the modified flag, a model load, and the startup scene.

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
            assert_eq!(
                e.apply(Command::RegisterBoneKeys),
                Err("not while playing".into()),
                "the C++ greys out every register path while playing"
            );
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
    e.apply(Command::ClickFrame(7)).unwrap();
    assert_eq!(
        e.camera,
        scene::track_camera(&e.doc, 7).unwrap(),
        "a click seeks"
    );
    let grouped = e
        .doc
        .pmm
        .models
        .iter()
        .find(|m| m.group_count > 0)
        .unwrap()
        .slot;
    e.apply(Command::SelectModel(grouped)).unwrap();
    e.apply(Command::ToggleDisplayGroup(0)).unwrap();
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
