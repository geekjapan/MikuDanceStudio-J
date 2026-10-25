//! Scenes on different threads step at the same time without sharing state,
//! and each gives the trace a single thread gives.

use mds_formats::pmm::Pmm;
use mds_physics::PhysicsScene;
use std::path::PathBuf;

fn trace(frames: u32) -> String {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    let pmm = Pmm::read(&std::fs::read(dir.join("swing600-golden.pmm")).unwrap()).unwrap();
    let mut scene = PhysicsScene::new(&pmm, |path| {
        std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"))
    })
    .unwrap();
    scene.trace(frames).unwrap()
}

#[test]
fn scenes_step_on_parallel_threads() {
    let alone = trace(600);
    let threads: Vec<_> = (0..16).map(|_| std::thread::spawn(|| trace(600))).collect();
    for t in threads {
        assert!(t.join().unwrap() == alone, "a parallel scene gave another trace");
    }
}
