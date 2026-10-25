//! Gate: every line of the x64 app's L2 traces of the swing600 scene,
//! `rigid` included, bit for bit: physics mode 2 (`swing600.pmm`) and
//! physics off (`swing600-nophys.pmm`), and the golden scene
//! (`swing600-golden.pmm`, physics mode 2), 600 frames each.

use mds_formats::pmm::Pmm;
use mds_physics::PhysicsScene;
use std::path::PathBuf;

fn gate(pmm: &str, trace: &str) {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    let pmm = Pmm::read(&std::fs::read(dir.join(pmm)).unwrap()).unwrap();
    let mut scene = PhysicsScene::new(&pmm, |path| {
        std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"))
    })
    .unwrap();
    let actual = scene.trace(600).unwrap();
    let expected = std::fs::read_to_string(dir.join("l2").join(trace)).unwrap();
    // 600 frames of 27 bones (bone and bonew), 4 morphs and 25 rigid bodies.
    assert_eq!(expected.lines().count(), 1 + 600 * (2 * 27 + 4 + 25));

    let difference = mds_trace::diff(actual.as_bytes(), expected.as_bytes()).unwrap();
    assert!(difference.is_none(), "{}", difference.unwrap());
    assert!(actual == expected, "traces differ in formatting");
}

#[test]
fn swing600_matches_the_l2_trace() {
    gate("swing600.pmm", "swing600-600.trace");
}

#[test]
fn swing600_golden_matches_the_l2_trace() {
    gate("swing600-golden.pmm", "swing600-golden-600.trace");
}

#[test]
fn swing600_nophys_matches_the_l2_trace() {
    gate("swing600-nophys.pmm", "swing600-nophys-600.trace");
}
