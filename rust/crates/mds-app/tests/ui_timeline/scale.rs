//! Button 424 (`IDD_FRAME_SCALE`), compared with the C++ `scale range` steps of
//! `tests/fixtures/rust/script2/scalerange.txt`.

use crate::rig::{assert_bytes, expected_in, Rig};
use mds_app::ui::timeline::{self, Scale};

fn open(rig: &mut Rig, range: [u32; 2]) {
    rig.update(|p| p.range = range);
    rig.run("ctl:424").unwrap();
}

fn type_in(rig: &mut Rig, rate: &str, checks: [bool; 3]) {
    rig.update(|p| {
        let s = p.scale.as_mut().expect("the window is open");
        s.text[2] = rate.into();
        s.checks = checks;
    });
}

fn ok(rig: &mut Rig) -> Result<(), String> {
    timeline::scale_submit(&mut rig.ctx())
}

/// `FrameRangeDlgProc` (`dialog_procs.cpp:62`): the range edits as `%d`, the rate "1.0", all three
/// check boxes on.
#[test]
fn the_window_opens_with_the_range_and_the_defaults() {
    let mut rig = Rig::replay_in("script2", "scalerange", 5);
    assert_eq!(rig.panel().scale, None);
    open(&mut rig, [3, 40]);
    assert_eq!(
        rig.panel().scale,
        Some(Scale {
            text: ["3".into(), "40".into(), "1.0".into()],
            checks: [true; 3],
        })
    );
}

/// `scalerange.txt` line 6, `scale range 0 300 1.5 on on on` on chain8_ik.pmx with swing600.vmd,
/// and line 13, `scale range 0 600 0.5 off on off` on morph4.pmx after the first scale.
#[test]
fn ok_saves_what_the_cpp_saved() {
    let mut rig = Rig::replay_in("script2", "scalerange", 5);
    open(&mut rig, [0, 300]);
    type_in(&mut rig, "1.5", [true; 3]);
    ok(&mut rig).unwrap();
    assert_eq!(rig.panel().scale, None, "OK ends the dialog");
    assert_bytes(
        "scaled-chain8.pmm",
        &rig.save(),
        &expected_in("script2", "scalerange", "scaled-chain8.pmm"),
    );

    let mut rig = Rig::replay_in("script2", "scalerange", 12);
    open(&mut rig, [0, 600]);
    type_in(&mut rig, "0.5", [false, true, false]);
    ok(&mut rig).unwrap();
    assert_bytes(
        "scaled-morph4.pmm",
        &rig.save(),
        &expected_in("script2", "scalerange", "scaled-morph4.pmm"),
    );
}

/// `ApplyFrameRangeScale` returns without a change when the end is not past the start
/// (`frame_range_apply.cpp:312`) or the rate is below 0.00001 or exactly 1 (`:319`); the dialog
/// ends all the same.
#[test]
fn a_range_or_rate_that_changes_nothing_ends_the_dialog_with_the_document_alone() {
    for (range, rate) in [
        ([10, 10], "2"),
        ([20, 10], "2"),
        ([0, 300], "1"),
        ([0, 300], "0"),
    ] {
        let mut rig = Rig::replay_in("script2", "scalerange", 5);
        let before = rig.save();
        open(&mut rig, range);
        type_in(&mut rig, rate, [true; 3]);
        assert!(ok(&mut rig).is_err(), "{range:?} {rate}");
        assert_eq!(rig.panel().scale, None);
        assert!(rig.save() == before, "{range:?} {rate}");
    }
}

/// The boxes are read as `GetWindowTextA(.., text, 8)`: seven characters.
#[test]
fn a_box_is_read_up_to_seven_characters() {
    let mut rig = Rig::replay_in("script2", "scalerange", 5);
    open(&mut rig, [0, 300]);
    type_in(&mut rig, "1.5000009", [true; 3]);
    ok(&mut rig).unwrap();
    let mut by_rate = Rig::replay_in("script2", "scalerange", 5);
    open(&mut by_rate, [0, 300]);
    type_in(&mut by_rate, "1.5000", [true; 3]);
    ok(&mut by_rate).unwrap();
    assert!(rig.save() == by_rate.save());
}

/// `command_frame_edit.cpp:1686` returns in camera mode; playback greys the button.
#[test]
fn the_button_is_a_model_mode_one_and_stops_during_playback() {
    let mut rig = Rig::open("camera3.pmm");
    rig.editor
        .apply(mds_doc::Command::SelectCameraMode)
        .unwrap();
    assert_eq!(rig.run("ctl:424"), Err("ctl:424: model mode only".into()));
    assert_eq!(rig.panel().scale, None);

    let mut rig = Rig::open("swing600.pmm");
    rig.run("ctl:408").unwrap();
    assert_eq!(rig.run("ctl:424"), Err("ctl:424: not while playing".into()));
}

#[test]
fn without_a_window_the_button_says_so() {
    let mut rig = Rig::replay_in("script2", "scalerange", 5);
    let mut status = String::new();
    let mut ctx = mds_app::ui::Ctx {
        editor: &mut rig.editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    assert_eq!(
        mds_app::actions::run(&mut ctx, "ctl:424"),
        Err("no window".into())
    );
}

#[test]
fn the_window_draws_in_both_languages() {
    let mut rig = Rig::replay_in("script2", "scalerange", 5);
    open(&mut rig, [0, 300]);
    crate::draw(&mut rig);
    rig.run("menu:260").unwrap();
    crate::draw(&mut rig);
    assert!(rig.panel().scale.is_some(), "drawing keeps the window");
}
