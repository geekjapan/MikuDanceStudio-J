//! The physics menu state that lives in the C++ world, which is built once (`SceneConstruct`,
//! `src/window/ui_init.cpp:219`): the editor builds a world again on a model or body change and on
//! a scene load, and each of them keeps the floor (285) and the playtime on/off switch (271).

use crate::rig::{fixtures, Rig};
use mds_app::editor::Editor;
use mds_doc::{Command, ModelFile};

/// `chain8.pmd` with its bodies replaced by one free box at y 20 above bone 0, in physics mode 1
/// (anytime), so the stopped world steps it. The OK of the physics model dialog
/// (`CommitPhysicsEdits`) makes the editor build the world again.
fn falling_box(r: &mut Rig) {
    let ModelFile::Pmd(pmd) = &r.editor.doc.models[0] else {
        panic!("chain8 is a PMD");
    };
    let physics = pmd.extension.as_ref().and_then(|e| e.physics.as_ref());
    let mut body = physics.expect("chain8 has bodies").rigids[0].clone();
    (body.mode, body.shape, body.size) = (1, 1, [1.0; 3]);
    (body.position, body.rotation, body.mask) = ([0.0, 20.0, 0.0], [0.0; 3], 0xFFFF);
    r.editor
        .apply(Command::SetPhysicsModel {
            rigids: vec![body],
            joints: Vec::new(),
        })
        .unwrap();
    r.run("menu:265").unwrap();
}

/// The box's height after two seconds of stopped passes.
fn fallen(r: &mut Rig) -> f32 {
    for _ in 0..60 {
        r.editor.physics.tick(1.0 / 30.0).unwrap();
    }
    r.editor.physics.body_poses().unwrap()[0][0].unwrap().0[1]
}

/// Menu 285 stores 1 or -1 into the ground body's collision flags (`command_view_menu.cpp:1437` to
/// `:1452`): off, the box falls through the floor (damped by the body's 0.5, it ends far below
/// it). The menu ran before the world was built again for the new bodies.
#[test]
fn the_floor_menu_reaches_every_world_the_editor_builds() {
    let mut r = Rig::pmd();
    falling_box(&mut r);
    let rest = fallen(&mut r);
    assert!(rest > -1.0, "on the floor: {rest}");

    let mut r = Rig::pmd();
    r.run("menu:285").unwrap();
    let opens = r.editor.physics_opens;
    falling_box(&mut r);
    assert_eq!(r.editor.physics_opens, opens + 1, "a new world");
    let through = fallen(&mut r);
    assert!(through < -50.0, "through the floor: {through}");

    let mut r = Rig::pmd();
    r.run("menu:285").unwrap();
    r.run("menu:285").unwrap();
    falling_box(&mut r);
    assert_eq!(fallen(&mut r), rest, "on again is the startup state");
}

/// Menu 271's `playbackAlwaysOnOffMode` is cleared only at start-up (`app_defaults.cpp:239`): a
/// model load and a scene load keep it, as the floor.
#[test]
fn the_playtime_switch_survives_model_and_scene_loads() {
    let mut r = Rig::pmd();
    r.run("menu:271").unwrap();
    let data = std::fs::read(fixtures().join("chain8.pmd")).unwrap();
    mds_app::ui::model_panel::load(&mut r.ctx(), "chain8.pmd", data).unwrap();
    assert!(r.editor.physics.always_on_off, "model load");
    let fresh = Editor::open(&fixtures().join("swing600.pmm")).unwrap();
    r.editor.adopt(fresh).unwrap();
    assert!(r.editor.physics.always_on_off, "scene load");
}

/// The modes reach the world while playing too: the radios are not greyed then
/// (`DisablePlaybackMenus` greys only 270, `playback_state.cpp:77`), and `ModelKinematicSync`
/// runs (`command_view_menu.cpp:1048`).
#[test]
fn a_radio_while_playing_reaches_the_world() {
    let mut r = Rig::open("swing600.pmm");
    r.run("ctl:408").unwrap();
    r.run("menu:272").unwrap();
    assert_eq!(r.editor.physics.scene.physics_mode, 0);
    assert_eq!(r.editor.doc.pmm.physics.playback_mode, 0);
}
