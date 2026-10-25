use super::common::*;
use mds_app::actions;
use mds_doc::Command;

/// `bones.txt` up to its first save: load, frame 10, the centre bone's pose, register (button
/// 500), frame 20, the upper body's rotation, register (Enter), frame 15, register display (438).
/// `src/app/pump_edit_keys.cpp:358` sends Enter as the button 500.
#[test]
fn bone_keys_register_like_the_script() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    frame(&mut e, 10);
    select_bone(&mut e, "センター");
    for (axis, v) in [(0, 1.0), (1, 2.0), (2, 3.0), (3, 10.0), (4, 20.0), (5, 30.0)] {
        e.apply(Command::BoneReadoutEdit { axis, value: v }).unwrap();
    }
    run(&mut e, "ctl:500").unwrap();
    frame(&mut e, 20);
    select_bone(&mut e, "上半身");
    for (axis, v) in [(3, 0.0), (4, 45.0), (5, 0.0)] {
        e.apply(Command::BoneReadoutEdit { axis, value: v }).unwrap();
    }
    run(&mut e, "key:Enter@model-mode").unwrap();
    frame(&mut e, 15);
    run(&mut e, "ctl:438").unwrap();
    assert_saved(&e, "bones", "registered.pmm");
    assert!(e.modified);
}

#[test]
fn register_does_nothing_without_a_model_and_not_while_playing() {
    let mut e = editor();
    let before = e.doc.save().unwrap();
    run(&mut e, "ctl:500").unwrap();
    assert_eq!(e.doc.save().unwrap(), before, "no model: no-op");
    assert!(!e.modified);
    assert_eq!(
        run(&mut e, "ctl:438"),
        Err("no model selected".into()),
        "camera mode has no model to register"
    );
    load_model(&mut e, "chain8.pmx");
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:500", "key:Enter@model-mode", "ctl:438"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}

/// The rows that wait for a document command stay unregistered, so the table never claims them.
#[test]
fn rows_without_a_command_are_not_registered() {
    for id in ["ctl:490", "ctl:494", "ctl:495", "ctl:501", "key:A", "key:C", "ctl:449"] {
        assert!(actions::find(id).is_none(), "{id}");
    }
}
