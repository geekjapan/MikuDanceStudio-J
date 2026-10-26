//! Two editor calls next to MME: the physics world after the physics model dialog's OK, and
//! the viewport `MediaAspect` reads.

use super::fixtures;
use mds_app::editor::Editor;
use mds_app::viewport::media_viewport;
use mds_doc::{Command, ModelFile};

#[test]
fn the_physics_model_ok_rebuilds_the_world_with_the_edited_bodies() {
    // `CommitPhysicsEdits` (physics_model_dialog.cpp 1129-1295) puts the dialog's bodies into
    // the world.
    let mut e = Editor::empty();
    let data = std::fs::read(fixtures().join("chain8.pmd")).unwrap();
    e.apply(Command::LoadModel {
        path: "chain8.pmd".into(),
        data,
    })
    .unwrap();
    let ModelFile::Pmd(pmd) = &e.doc.models[0] else {
        panic!("a PMD")
    };
    let p = pmd.extension.as_ref().unwrap().physics.as_ref().unwrap();
    let (mut rigids, joints) = (p.rigids.clone(), p.joints.clone().unwrap());
    rigids[0].mass = 2.5;
    rigids[0].size[0] = 3.0;
    let opens = e.physics_opens;
    e.apply(Command::SetPhysicsModel { rigids, joints })
        .unwrap();
    assert_eq!(e.physics_opens, opens + 1);
    let live = &e.physics.scene.models[0].rigids[0];
    assert_eq!((live.mass, live.size[0]), (2.5, 3.0));
}

#[test]
fn the_media_viewport_follows_the_cpp_refresh() {
    // RefreshMainWindowViewport (ui_viewport_refresh.cpp:224): viewScale = width * 1.2 / 1280;
    // hideLeft holds the right edge, hideRight the left one. The values of
    // mds-doc/tests/dialogs.rs (a 800 px view from x = 216).
    let vp = media_viewport([216, 0, 1016, 601]);
    assert_eq!(
        (vp.hide_left, vp.hide_right, vp.hide_top, vp.hide_bottom),
        (1016, 216, 0, 601)
    );
    assert_eq!(vp.view_scale, 0.75);
}
