//! Gate: the `bone`, `bonew` and `morph` lines of
//! `tests/fixtures/rust/l2/swing600-nophys-600.trace` (the x64 app, physics
//! mode 0), bit for bit. The reference's `rigid` lines are dropped.

use mds_formats::pmm::Pmm;
use mds_pose::Scene;
use std::path::PathBuf;

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

#[test]
fn swing600_nophys_matches_the_l2_trace() {
    let dir = fixtures();
    let pmm = Pmm::read(&std::fs::read(dir.join("swing600-nophys.pmm")).unwrap()).unwrap();
    let mut scene = Scene::new(&pmm, |path| {
        std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"))
    })
    .unwrap();
    let actual = scene.trace(600).unwrap();

    let reference = std::fs::read_to_string(dir.join("l2/swing600-nophys-600.trace")).unwrap();
    let expected: String = reference
        .split_inclusive('\n')
        .filter(|line| line.split(' ').nth(1) != Some("rigid"))
        .collect();
    // 600 frames of 9 + 2 + 8 + 8 bones (bone and bonew) and 4 morphs.
    assert_eq!(expected.lines().count(), 1 + 600 * (2 * 27 + 4));

    let difference = mds_trace::diff(actual.as_bytes(), expected.as_bytes()).unwrap();
    assert!(difference.is_none(), "{}", difference.unwrap());
    assert!(actual == expected, "traces differ in formatting");
}
