//! Rust traces of the RM-1 PMM fixtures against C++ L1 traces committed in
//! `tests/l1/`. The C++ side ran on macOS arm64 (Apple clang, `-O3
//! -ffp-contract=off`); the Linux amd64 and arm64 runs of `check-linux.sh`
//! compare against the same files, so a platform libm leak would fail there.
//!
//! * `<fixture>-600.trace`: `mds_scene_cli <pmm> out.pmm --root
//!   tests/fixtures/rust --trace <file> --frames 600` (the stateless
//!   `EvaluatePmmSceneFrame` path).
//! * `<fixture>-seconds.trace`, `<fixture>-half-frames-40.trace`: the
//!   fractional-frame playback path, from `playback_trace.cpp` (this
//!   directory), built against `libmikudancestudio_formats.a`. The C++ trace
//!   mode cannot evaluate a fractional frame, so the driver calls
//!   `StartPmmScenePlayback` and `AdvancePmmScenePlayback` instead:
//!   `playback_trace <pmm> <out> --seconds 0,0.0166667,0.5,1.2345,3.3333,7.77,10,19.99,19.9999,25`
//!   and `playback_trace <pmm> <out> --half-frames 40`.

use mds_formats::pmm::Pmm;
use mds_scene::trace::{write_playback_trace, write_scene_trace};
use mds_scene::{evaluate_scene_frame, load_scene};
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn scene(name: &str) -> Pmm {
    let data = std::fs::read(root().join("tests/fixtures/rust").join(name)).unwrap();
    load_scene(&data).unwrap()
}

fn reference(name: &str) -> Vec<u8> {
    std::fs::read(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/l1")
            .join(name),
    )
    .unwrap()
}

/// `mds-trace-diff` semantics, then the stricter byte comparison.
fn assert_same_trace(actual: &[u8], expected: &[u8], what: &str) {
    let difference = mds_trace::diff(actual, expected).unwrap_or_else(|e| panic!("{what}: {e}"));
    assert!(difference.is_none(), "{what}: {}", difference.unwrap());
    assert!(actual == expected, "{what}: traces differ in formatting");
}

const SECONDS: [f32; 10] = [
    0.0,
    0.016_666_7,
    0.5,
    1.2345,
    3.3333,
    7.77,
    10.0,
    19.99,
    19.9999,
    25.0,
];

fn half_frames(n: u32) -> Vec<f32> {
    (0..=2 * n).map(|k| k as f32 / 60.0f32).collect()
}

fn check_fixture(fixture: &str, stem: &str) {
    let scene = scene(fixture);

    let mut out = Vec::new();
    write_scene_trace(&mut out, &scene, 600).unwrap();
    assert_same_trace(&out, &reference(&format!("{stem}-600.trace")), "600 frames");

    let mut out = Vec::new();
    write_playback_trace(&mut out, &scene, &SECONDS).unwrap();
    assert_same_trace(
        &out,
        &reference(&format!("{stem}-seconds.trace")),
        "seconds",
    );

    let mut out = Vec::new();
    write_playback_trace(&mut out, &scene, &half_frames(40)).unwrap();
    assert_same_trace(
        &out,
        &reference(&format!("{stem}-half-frames-40.trace")),
        "half frames",
    );
}

#[test]
fn swing600_matches_cpp() {
    check_fixture("swing600.pmm", "swing600");
}

#[test]
fn camera3_matches_cpp() {
    check_fixture("camera3.pmm", "camera3");
}

/// Past the last key every track holds: frames 600..700 repeat frame 599.
#[test]
fn frames_after_the_last_key_hold() {
    for fixture in ["swing600.pmm", "camera3.pmm"] {
        let scene = scene(fixture);
        let last = evaluate_scene_frame(&scene, 599).unwrap();
        for frame in [600, 650, 699, 5000] {
            let mut held = evaluate_scene_frame(&scene, frame).unwrap();
            assert_eq!(held.frame, frame);
            held.frame = 599;
            assert_eq!(held, last, "{fixture} frame {frame}");
        }
    }
}

#[test]
fn broken_links_do_not_evaluate() {
    let mut scene = scene("swing600.pmm");
    // Bone 0 of model 0 links to record 62 at frame 599; make the record's
    // back link point elsewhere.
    let model = &mut scene.models[0];
    let next = model.bone_keys.heads()[0].next;
    assert_ne!(next, 0);
    model.bone_keys.get_mut(next).unwrap().previous = 9999;
    assert!(evaluate_scene_frame(&scene, 599).is_none());
    assert!(
        evaluate_scene_frame(&scene, 0).is_some(),
        "frame 0 never leaves the head"
    );
}

#[test]
fn trace_of_zero_frames_is_the_header() {
    let mut out = Vec::new();
    write_scene_trace(&mut out, &scene("swing600.pmm"), 0).unwrap();
    assert_eq!(out, b"mds-trace 1 L1\n");
}
