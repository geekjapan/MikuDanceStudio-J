//! The self-shadow range slider 560 (`ui_hscroll.cpp:261` to `:272`).

use super::open;
use mds_app::ui::shadow_panel::set_slider;
use mds_app::ui::Ctx;
use mds_doc::Command;

fn slide(e: &mut mds_app::editor::Editor, position: i32) -> Result<(), String> {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: e,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    set_slider(&mut ctx, position)
}

/// The distance is `(10000 - pos) / 100000`, the mode stays, and `SceneModified = 1` (`:270`).
#[test]
fn the_slider_sets_the_distance_and_marks_the_scene() {
    let mut e = open("camera3.pmm");
    e.apply(Command::SelectCameraMode).unwrap();
    e.apply(Command::SetSelfShadow {
        mode: 2,
        distance: 0.02,
    })
    .unwrap();
    e.modified = false;
    slide(&mut e, 8000).unwrap();
    assert_eq!(
        e.doc.pmm.physics_interval,
        (f64::from(10000 - 8000) / 100000.0) as f32
    );
    assert_eq!(e.doc.edit.self_shadow_mode, 2);
    assert!(e.modified);
}

#[test]
fn the_slider_is_a_camera_mode_control() {
    let mut e = open("swing600.pmm");
    let before = e.doc.save().unwrap();
    assert!(slide(&mut e, 8000).is_err());
    assert!(e.doc.save().unwrap() == before && !e.modified);
}
