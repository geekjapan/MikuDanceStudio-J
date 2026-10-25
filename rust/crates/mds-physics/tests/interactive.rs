//! The interactive path is deterministic: a seek to frame N with the world
//! kept alive, stopped pumps, playback with wall-clock catch-up, a stop and
//! frame steps give the same bytes in every run and on parallel threads.

use mds_formats::pmm::Pmm;
use mds_physics::PhysicsScene;
use std::path::PathBuf;

/// The `write_frame` lines after every pump of a session that seeks to
/// `seek` first.
fn session(pmm: &str, seek: u32) -> String {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    let pmm = Pmm::read(&std::fs::read(dir.join(pmm)).unwrap()).unwrap();
    let mut s = PhysicsScene::open(&pmm, |path| {
        std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"))
    })
    .unwrap();
    let mut out = String::new();
    let mut pump = 0;
    let mut dump = |s: &PhysicsScene| {
        s.write_frame(&mut out, pump).unwrap();
        pump += 1;
    };
    s.tick(0.0).unwrap();
    dump(&s);
    s.seek(seek);
    for _ in 0..20 {
        s.tick(0.017).unwrap();
        dump(&s);
    }
    let start = seek as f32 / 30.0;
    s.start_playback(start, true);
    for i in 1..=60 {
        s.catch_up(start + i as f32 * 0.021, 0.021).unwrap();
        dump(&s);
    }
    s.loop_restart(start, 0.021).unwrap();
    dump(&s);
    s.stop_playback(seek + 30);
    for _ in 0..10 {
        s.tick(0.016).unwrap();
        dump(&s);
    }
    s.step_frame(seek + 31, true);
    s.tick(0.016).unwrap();
    dump(&s);
    s.step_frame(seek + 30, false);
    s.tick(0.016).unwrap();
    dump(&s);
    out
}

#[test]
fn a_seek_then_stepping_is_deterministic() {
    for pmm in ["swing600.pmm", "swing600-golden.pmm"] {
        let first = session(pmm, 120);
        assert!(session(pmm, 120) == first, "{pmm}: a second run differs");
        assert!(
            session(pmm, 300) != first,
            "{pmm}: the seek changed nothing"
        );
        let threads: Vec<_> = (0..8)
            .map(|_| std::thread::spawn(move || session(pmm, 120)))
            .collect();
        for t in threads {
            assert!(t.join().unwrap() == first, "{pmm}: a parallel run differs");
        }
    }
}
