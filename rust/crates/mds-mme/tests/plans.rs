//! The gate: regenerate every committed plan under `tests/fixtures/rust/mme/` and compare it
//! with the oracle line by line.
//!
//! `extra/` plans (the small effects in `effects/`) always run. `ray-mmd/` plans need the
//! corpus of `tools/fixtures/fetch_corpus.sh` (`$MDS_CORPUS` or `${TMPDIR:-/tmp}/mds-corpus`)
//! and print SKIP when it is absent; a skip is not a pass.
//!
//! The plans that do not match yet are listed in `tests/mismatches.txt`. The test fails when a
//! listed plan matches (update the list) or an unlisted one does not (a regression).

use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::{Path, PathBuf};

/// The commit `tools/fixtures/fetch_corpus.sh` pins.
const CORPUS_COMMIT: &str = "218a91cd1c53f49850b2772ebbcb98bf258e75b1";

/// Writes to stderr directly: libtest captures `println!` of passing tests, and the counts and
/// a SKIP must show in a plain `cargo test`.
fn report(text: &str) {
    let _ = writeln!(std::io::stderr(), "{text}");
}

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/mme")
}

fn corpus_dir() -> PathBuf {
    match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd")
}

fn plans(dir: &Path, out: &mut Vec<PathBuf>) {
    let mut entries: Vec<_> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect();
    entries.sort();
    for p in entries {
        if p.is_dir() {
            plans(&p, out);
        } else if p.to_string_lossy().ends_with(".plan.txt") {
            out.push(p);
        }
    }
}

/// The first differing line of a plan: (line number, expected, got).
fn first_diff(expected: &str, got: &str) -> Option<(usize, String, String)> {
    let (e, g): (Vec<_>, Vec<_>) = (expected.lines().collect(), got.lines().collect());
    (0..e.len().max(g.len()))
        .find(|&i| e.get(i) != g.get(i))
        .map(|i| {
            let at = |v: &[&str]| v.get(i).copied().unwrap_or("<eof>").to_string();
            (i + 1, at(&e), at(&g))
        })
        .or_else(|| (expected != got).then(|| (e.len(), "<bytes>".into(), "<bytes>".into())))
}

/// The line kind of a plan line: its first word, with the indentation.
fn kind(line: &str) -> String {
    let indent = line.len() - line.trim_start().len();
    let word = line.split_whitespace().next().unwrap_or("");
    format!("{}{word}", " ".repeat(indent))
}

/// Compares the plans of `group` (`extra` or `ray-mmd`) and returns the mismatching ones,
/// relative to `fixtures()`, with a printed report.
fn compare(group: &str, effects: &Path) -> BTreeSet<String> {
    let mut list = Vec::new();
    plans(&fixtures().join(group), &mut list);
    let mut bad = BTreeSet::new();
    let mut causes: BTreeMap<String, (usize, String)> = BTreeMap::new();
    for plan in &list {
        let rel = plan
            .strip_prefix(fixtures().join(group))
            .unwrap()
            .to_string_lossy()
            .replace('\\', "/");
        let effect = effects.join(rel.trim_end_matches(".plan.txt"));
        let expected = std::fs::read_to_string(plan).unwrap();
        let got = mds_mme::plan(&effect, effects);
        if let Some((n, e, g)) = first_diff(&expected, &got) {
            let name = format!("{group}/{rel}");
            let c = causes.entry(kind(&e)).or_insert((0, String::new()));
            c.0 += 1;
            if c.1.is_empty() {
                c.1 = format!("{name}:{n}\n      expected: {e}\n      got:      {g}");
            }
            bad.insert(name);
        }
    }
    report(&format!(
        "{group}: {} of {} plans match",
        list.len() - bad.len(),
        list.len()
    ));
    for (k, (n, example)) in &causes {
        report(&format!(
            "  first mismatch at {k:?}: {n} plans, e.g. {example}"
        ));
    }
    bad
}

fn expected_mismatches(group: &str) -> BTreeSet<String> {
    let text =
        std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/mismatches.txt"))
            .unwrap();
    text.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .filter(|l| l.starts_with(&format!("{group}/")))
        .map(String::from)
        .collect()
}

fn check(group: &str, effects: &Path) {
    let bad = compare(group, effects);
    let listed = expected_mismatches(group);
    let regressed: Vec<_> = bad.difference(&listed).collect();
    let fixed: Vec<_> = listed.difference(&bad).collect();
    assert!(
        regressed.is_empty() && fixed.is_empty(),
        "plans that no longer match: {regressed:?}\nlisted plans that now match (remove them from tests/mismatches.txt): {fixed:?}"
    );
}

#[test]
fn extra_plans_match() {
    check("extra", &fixtures().join("effects"));
}

#[test]
fn ray_mmd_plans_match() {
    let corpus = corpus_dir();
    if !corpus.is_dir() {
        report(&format!(
            "SKIP: corpus not found at {}; run tools/fixtures/fetch_corpus.sh (a skip is not a pass)",
            corpus.display()
        ));
        return;
    }
    if let Ok(head) = std::fs::read_to_string(corpus.join(".git/HEAD")) {
        assert_eq!(
            head.trim(),
            CORPUS_COMMIT,
            "the corpus at {} is not at the pinned commit",
            corpus.display()
        );
    }
    check("ray-mmd", &corpus);
}
