//! Lane 9 of RM-8: `mds-fx reflect` against the `fx_reflect.exe` JSON of RM-3.
//!
//! Set `MDS_FX_REFLECT` to the JSON-lines file (and have the corpus, see `common`). Without
//! it the test prints "skipped" and passes: the JSON is a Windows artifact, not in the repo.
//! The comparison itself is `tools/rust/fx_reflect_compare.py`, which also runs by hand.

mod common;

use std::path::Path;
use std::process::Command;

#[test]
fn reflect_matches_d3dx() {
    let Some(json) = std::env::var_os("MDS_FX_REFLECT") else {
        eprintln!("skipped: MDS_FX_REFLECT is not set");
        return;
    };
    let corpus = common::require_corpus();
    let script =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tools/rust/fx_reflect_compare.py");
    let out = Command::new("python3")
        .arg("-I")
        .arg(script)
        .arg("--d3dx")
        .arg(json)
        .arg("--corpus")
        .arg(corpus)
        .arg("--bin")
        .arg(env!("CARGO_BIN_EXE_mds-fx"))
        .output()
        .expect("python3 is needed to compare");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        out.status.success(),
        "{}",
        &stdout[stdout.len().saturating_sub(4000)..]
    );
}
