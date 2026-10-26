//! `PhysicsScene::body_poses` against the `rigid` lines of the x64 app's
//! L2 trace of swing600 (physics mode 2), frames 0 to 59, bit for bit.

use mds_formats::pmm::Pmm;
use mds_physics::PhysicsScene;
use std::path::PathBuf;

#[test]
fn body_poses_are_the_rigid_lines_of_the_l2_trace() {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    let pmm = Pmm::read(&std::fs::read(dir.join("swing600.pmm")).unwrap()).unwrap();
    let mut scene = PhysicsScene::new(&pmm, |path| {
        std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"))
    })
    .unwrap();
    let trace = std::fs::read_to_string(dir.join("l2/swing600-600.trace")).unwrap();
    let mut checked = 0;
    for frame in 0..60u32 {
        if frame > 0 {
            scene.step().unwrap();
        }
        let prefix = format!("{frame} rigid ");
        let expected: Vec<&str> = trace.lines().filter(|l| l.starts_with(&prefix)).collect();
        let mut actual = Vec::new();
        for (model, poses) in scene.scene.models.iter().zip(scene.body_poses().unwrap()) {
            for (i, pose) in poses.into_iter().enumerate() {
                let (origin, rotation) = pose.expect("every swing600 body is built");
                let mut line = format!("{prefix}{} {i}", model.slot);
                mds_pose::trace::floats(&mut line, &origin).unwrap();
                mds_pose::trace::floats(&mut line, &rotation).unwrap();
                actual.push(line);
            }
        }
        assert_eq!(actual.len(), 25);
        assert_eq!(actual, expected, "frame {frame}");
        checked += actual.len();
    }
    assert_eq!(checked, 60 * 25);
}
