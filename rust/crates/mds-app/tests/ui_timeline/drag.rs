//! `mouse:timeline-key-drag`: the whole move of a drag is one `MoveSelectedKeys`, compared with
//! the C++ `drag` steps of `tests/fixtures/rust/script3/` (`drag.txt`, `dragcamera.txt`).

use crate::rig::{assert_bytes, expected_in, Rig};
use mds_app::ui::timeline;
use mds_doc::Track;

/// `drag.txt` after `frame 20` (line 23) with the bone keys marked (line 22), and the C++ file
/// of the step after `drag 20 -15`.
#[test]
fn a_model_drag_back_saves_what_the_cpp_saved() {
    let mut rig = Rig::replay_in("script3", "drag", 23);
    timeline::move_keys(&mut rig.ctx(), -15).unwrap();
    assert_bytes(
        "back.pmm",
        &rig.save(),
        &expected_in("script3", "drag", "back.pmm"),
    );
}

/// Lines 27 to 30: the bone and display keys dragged by +40, after the first drag.
#[test]
fn a_model_drag_forward_saves_what_the_cpp_saved() {
    let mut rig = Rig::replay_in("script3", "drag", 29);
    timeline::move_keys(&mut rig.ctx(), 40).unwrap();
    assert_bytes(
        "forward.pmm",
        &rig.save(),
        &expected_in("script3", "drag", "forward.pmm"),
    );
}

/// `dragcamera.txt` lines 20 to 24, and 27 to 29: camera mode moves the camera, light, self
/// shadow, gravity and accessory keys.
#[test]
fn camera_mode_drags_save_what_the_cpp_saved() {
    let mut rig = Rig::replay_in("script3", "dragcamera", 23);
    timeline::move_keys(&mut rig.ctx(), 7).unwrap();
    assert_bytes(
        "forward.pmm",
        &rig.save(),
        &expected_in("script3", "dragcamera", "forward.pmm"),
    );
    let mut rig = Rig::replay_in("script3", "dragcamera", 28);
    timeline::move_keys(&mut rig.ctx(), -30).unwrap();
    assert_bytes(
        "back.pmm",
        &rig.save(),
        &expected_in("script3", "dragcamera", "back.pmm"),
    );
}

/// The C++ pushes its undo entry at the mouse-down, so a drag of any length is one entry.
#[test]
fn one_drag_is_one_undo_entry() {
    let mut rig = Rig::replay_in("script3", "drag", 23);
    let cursor = |rig: &Rig| rig.editor.doc.edit.models[0].history.cursor;
    let before = cursor(&rig);
    timeline::move_keys(&mut rig.ctx(), -15).unwrap();
    assert_eq!(cursor(&rig), (before + 1) % mds_doc::history::SLOTS);
}

/// A press takes the marked keys along only on a marked key (`ToggleModelKeyAllocated`: a
/// marked key stays marked and flags the selection as changed).
#[test]
fn a_press_grabs_only_a_marked_key() {
    let rig = Rig::replay_in("script3", "drag", 22);
    let center = Track::Bone(rig.bone("センター"));
    let doc = &rig.editor.doc;
    for frame in [10, 20, 30] {
        assert!(timeline::grabs_marked_key(doc, center, frame), "{frame}");
    }
    assert!(!timeline::grabs_marked_key(doc, center, 11));
    assert!(!timeline::grabs_marked_key(doc, Track::Display, 20));
    let unmarked = Rig::replay_in("script3", "drag", 21);
    assert!(!timeline::grabs_marked_key(
        &unmarked.editor.doc,
        center,
        20
    ));
}

#[test]
fn a_drag_is_refused_while_playing() {
    let mut rig = Rig::replay_in("script3", "drag", 23);
    rig.run("ctl:408").unwrap();
    assert_eq!(
        timeline::move_keys(&mut rig.ctx(), 5),
        Err("not while playing".into())
    );
}

/// The grid paints where the marked keys would land while the drag runs.
#[test]
fn the_grid_draws_a_drag_in_progress() {
    let mut rig = Rig::replay_in("script3", "drag", 23);
    rig.update(|p| p.key_drag = Some([20, 14]));
    crate::draw(&mut rig);
    assert_eq!(rig.panel().key_drag, Some([20, 14]));
}
