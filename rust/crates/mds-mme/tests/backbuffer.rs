//! `plan_at` sizes `ViewportRatio` targets and the device surfaces against the back buffer it
//! is given; at 1000x600 it is the oracle's plan.

use std::path::Path;

#[test]
fn viewport_ratio_targets_follow_the_back_buffer() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/mme");
    let effects = root.join("effects");
    let fx = effects.join("post.fx");
    let oracle = std::fs::read_to_string(root.join("extra/post.fx.plan.txt")).unwrap();
    assert_eq!(mds_mme::plan_at(&fx, &effects, (1000, 600)), oracle);

    let plan = mds_mme::plan_at(&fx, &effects, (1920, 1080));
    // Every size of the oracle's plan, scaled: 1000x600 -> 1920x1080, the 0.5 ratio
    // 500x300 -> 960x540, and int(1000 * 0.3333) x int(600 * 0.3333) -> 639x359.
    let scaled = oracle
        .replace("1000x600", "1920x1080")
        .replace("500x300", "960x540")
        .replace("333x199", "639x359");
    assert_eq!(plan, scaled);
}
