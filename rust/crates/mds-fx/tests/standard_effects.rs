//! Tests on the two MikuMikuDance standard effects in `res/assets` (Shift-JIS bytes).

mod common;

use mds_fx::Effect;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::PathBuf;

fn sm(name: &str) -> PathBuf {
    common::repo_assets().join(name)
}

/// Counts lines that start a `keyword` block, the way a reader counts them in the source.
fn count_blocks(text: &str, keyword: &str) -> usize {
    text.lines()
        .filter(|l| {
            l.trim_start()
                .strip_prefix(keyword)
                .is_some_and(|r| !r.starts_with(|c: char| c.is_ascii_alphanumeric() || c == '_'))
        })
        .count()
}

#[test]
fn technique_and_pass_counts_match_the_source() {
    for name in ["skin_effect_sm2.fx", "skin_effect_sm3.fx"] {
        let bytes = std::fs::read(sm(name)).unwrap();
        assert!(
            std::str::from_utf8(&bytes).is_err(),
            "{name} is expected to be Shift-JIS"
        );
        let text = mds_fx::decode(&bytes);
        let fx = Effect::parse_bytes(&sm(name), &bytes).unwrap();
        assert_eq!(
            fx.ast.techniques.len(),
            count_blocks(&text, "technique"),
            "{name} techniques"
        );
        assert_eq!(
            fx.ast.pass_count(),
            count_blocks(&text, "pass"),
            "{name} passes"
        );
        assert!(fx.ast.techniques.len() >= 10, "{name} has many techniques");
        // every entry builds a wrapper, and every compile names a defined function
        for e in fx.entries() {
            fx.wrapper(&e).unwrap_or_else(|err| panic!("{name}: {err}"));
        }
    }
}

#[test]
fn shift_jis_and_utf8_copies_give_the_same_result() {
    let dir = std::env::temp_dir().join(format!("mds-fx-sjis-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let raw = std::fs::read(sm("skin_effect_sm3.fx")).unwrap();
    let (text, _, bad) = encoding_rs::SHIFT_JIS.decode(&raw);
    assert!(!bad);
    let utf8_path = dir.join("skin_effect_sm3.fx");
    std::fs::write(&utf8_path, text.as_bytes()).unwrap();
    let a = Effect::parse_bytes(&sm("skin_effect_sm3.fx"), &raw).unwrap();
    let b = Effect::parse_file(&utf8_path).unwrap();
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(a.ast, b.ast);
    assert_eq!(a.shader_source(), b.shader_source());
    assert_eq!(a.entries(), b.entries());
    assert_eq!(a.content_key(), b.content_key());
    // the Japanese comments and strings really were decoded
    assert!(a.preprocessed().text.contains('\n'));
    println!(
        "sjis: {} techniques, {} passes, key {:016x}",
        a.ast.techniques.len(),
        a.ast.pass_count(),
        a.content_key()
    );
}

fn truncation_run(step: usize) -> (usize, usize, usize) {
    let path = sm("skin_effect_sm3.fx");
    let bytes = std::fs::read(&path).unwrap();
    let offsets: Vec<usize> = (0..=bytes.len()).step_by(step).collect();
    let results = common::par_map(&offsets, |&k| {
        match catch_unwind(AssertUnwindSafe(|| {
            Effect::parse_bytes(&path, &bytes[..k]).is_ok()
        })) {
            Ok(true) => (1, 0, 0),
            Ok(false) => (0, 1, 0),
            Err(_) => (0, 0, 1),
        }
    });
    let sum = |f: fn(&(usize, usize, usize)) -> usize| results.iter().map(f).sum::<usize>();
    (sum(|r| r.0), sum(|r| r.1), sum(|r| r.2))
}

/// A sample of cut points in every run; `truncation_every_byte` does all of them.
#[test]
fn truncation_sample_never_panics() {
    let (ok, err, panics) = truncation_run(61);
    assert_eq!(panics, 0);
    assert!(ok > 0 && err > 0);
}

/// Lane 7: cut skin_effect_sm3.fx at every byte offset. Run with
/// `cargo test --release -- --ignored truncation_every_byte --nocapture`.
#[test]
#[ignore = "slow in debug builds; run in release"]
fn truncation_every_byte() {
    let len = std::fs::metadata(sm("skin_effect_sm3.fx")).unwrap().len();
    let (ok, err, panics) = truncation_run(1);
    println!(
        "truncation: offsets 0..={len}: {ok} parsed, {err} returned an error, {panics} panicked"
    );
    assert_eq!(panics, 0);
    assert_eq!(ok + err, len as usize + 1);
}
