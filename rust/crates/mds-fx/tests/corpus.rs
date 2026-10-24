//! Tests over the ray-mmd corpus. They need the corpus (see `common::require_corpus`) and fail
//! when it is missing.

mod common;

use mds_fx::preprocess::{resolved_includes, Via};
use mds_fx::{Effect, Options};
use std::path::Path;
use std::process::Command;

fn ray_fx_files() -> Vec<std::path::PathBuf> {
    let files = common::fx_files(&common::require_corpus().join("ray-mmd"));
    assert_eq!(files.len(), 515, "the pinned corpus holds 515 .fx files");
    files
}

#[test]
fn every_effect_parses_with_the_d3dx_include_rule() {
    // Default options skip #include lines in disabled #if branches, as D3DX does. ray.fx
    // includes the missing CameraMotion.fxsub only under AA_QUALITY == 6, so it parses.
    let files = ray_fx_files();
    let results = common::par_map(&files, |f| Effect::parse_file(f).map(|_| ()));
    let failures: Vec<_> = files
        .iter()
        .zip(&results)
        .filter_map(|(f, r)| r.as_ref().err().map(|e| format!("{}: {e}", f.display())))
        .collect();
    assert!(
        failures.is_empty(),
        "{} files failed:\n{}",
        failures.len(),
        failures.join("\n")
    );
}

#[test]
fn strict_includes_flag_only_the_dangling_include() {
    let files = ray_fx_files();
    let strict = Options {
        strict_includes: true,
        ..Options::default()
    };
    let results = common::par_map(&files, |f| Effect::parse_file_with(f, &strict).map(|_| ()));
    let failed: Vec<_> = files
        .iter()
        .zip(&results)
        .filter(|(_, r)| r.is_err())
        .collect();
    assert_eq!(failed.len(), 1, "exactly one file fails");
    let (path, err) = (failed[0].0, failed[0].1.as_ref().unwrap_err());
    assert!(path.ends_with("ray-mmd/ray.fx"));
    assert_eq!(err.line, 142);
    assert!(err.message.contains("shader/CameraMotion.fxsub"), "{err}");
    assert!(err.path.ends_with("ray.fx"));
}

#[test]
fn all_2303_includes_resolve_against_the_top_level_directory() {
    let files = ray_fx_files();
    let strict = Options {
        strict_includes: true,
        ..Options::default()
    };
    let counts = common::par_map(&files, |f| {
        let bytes = std::fs::read(f).unwrap();
        let inc = resolved_includes(f, &bytes, &strict);
        (
            inc.len(),
            inc.iter().filter(|i| i.via == Via::TopLevelDir).count(),
        )
    });
    // The two standard effects have no includes, so the corpus alone gives the total.
    let total: usize = counts.iter().map(|c| c.0).sum();
    let top: usize = counts.iter().map(|c| c.1).sum();
    assert_eq!((total, top), (2303, 2303));
}

/// The entry set of `mds-fx scan --entries` equals the first four columns of the P2
/// prototype's `shaders-direct.tsv` (kept in `tests/golden/entries.tsv`).
#[test]
fn scan_entries_equal_the_prototype_entry_set() {
    let corpus = common::require_corpus();
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let out = Command::new(env!("CARGO_BIN_EXE_mds-fx"))
        .current_dir(&repo)
        .args(["scan", "--entries"])
        .arg(corpus.join("ray-mmd"))
        .arg("res/assets")
        .output()
        .unwrap();
    let stdout = String::from_utf8(out.stdout).unwrap();
    let stderr = String::from_utf8(out.stderr).unwrap();
    assert!(stderr.contains("unique files: 490"), "{stderr}");
    assert!(stderr.contains("unique entries: 1483"), "{stderr}");
    let mut got: Vec<&str> = stdout.lines().collect();
    let mut want: Vec<&str> = include_str!("golden/entries.tsv").lines().collect();
    got.sort_unstable();
    want.sort_unstable();
    assert_eq!(want.len(), 1483);
    assert_eq!(got.len(), want.len());
    let missing: Vec<_> = want
        .iter()
        .filter(|l| got.binary_search(l).is_err())
        .take(5)
        .collect();
    assert!(got == want, "entry sets differ; first missing: {missing:?}");
}

/// Lane 10: a syntax error at line 12 of an included .fxsub is reported against that file.
#[test]
fn syntax_error_in_an_included_file_names_that_file_and_line() {
    let ray = common::require_corpus().join("ray-mmd");
    let tmp = std::env::temp_dir().join(format!("mds-fx-linemap-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&tmp);
    std::fs::create_dir_all(tmp.join("Shader")).unwrap();
    for f in ["ray.fx", "ray.conf", "ray_advanced.conf"] {
        std::fs::copy(ray.join(f), tmp.join(f)).unwrap();
    }
    for e in std::fs::read_dir(ray.join("Shader")).unwrap().flatten() {
        if e.file_type().unwrap().is_file() {
            std::fs::copy(e.path(), tmp.join("Shader").join(e.file_name())).unwrap();
        }
    }
    // Line 12 of Shader/common.fxsub is `float4x4 matProject : PROJECTION;`, a global.
    let target = tmp.join("Shader/common.fxsub");
    let text = std::fs::read_to_string(&target).unwrap();
    let mut lines: Vec<&str> = text.split('\n').collect();
    assert!(
        lines[11].starts_with("float4x4 matProject"),
        "{:?}",
        lines[11]
    );
    lines[11] = "float4 __broken = ;\r";
    std::fs::write(&target, lines.join("\n")).unwrap();

    let err = Effect::parse_file(&tmp.join("ray.fx"))
        .map(|_| ())
        .unwrap_err();
    std::fs::remove_dir_all(&tmp).unwrap();
    assert!(err.path.ends_with("Shader/common.fxsub"), "{err}");
    assert_eq!(err.line, 12, "{err}");
}
