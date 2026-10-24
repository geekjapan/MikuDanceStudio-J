//! Golden test: 20 hand-checked annotation values from the ray-mmd corpus.
//! The rows live in `tests/golden/annotations.tsv`. The test needs the corpus (see
//! `common::require_corpus`) and fails when it is missing.

mod common;

use mds_fx::{Effect, Value};
use std::collections::HashMap;

fn fmt(v: &Value) -> String {
    match v {
        Value::Int(i) => i.to_string(),
        Value::Float(f) => format!("{f:?}"),
        Value::Bool(b) => b.to_string(),
        Value::Str(s) => format!("{s:?}"),
        Value::Ident(s) => format!("ident({s})"),
        Value::Vector(vs) => format!("{{{}}}", vs.iter().map(fmt).collect::<Vec<_>>().join(", ")),
        Value::Expr(s) => format!("expr({s})"),
    }
}

#[test]
fn twenty_annotation_values_match_the_source() {
    let corpus = common::require_corpus();
    let table = include_str!("golden/annotations.tsv");
    let rows: Vec<Vec<&str>> = table
        .lines()
        .filter(|l| !l.starts_with('#') && !l.trim().is_empty())
        .map(|l| l.split('\t').collect())
        .collect();
    assert_eq!(rows.len(), 20, "the golden table holds exactly 20 values");

    let mut effects: HashMap<&str, Effect> = HashMap::new();
    let mut failures = Vec::new();
    for r in &rows {
        assert_eq!(r.len(), 6, "bad golden row: {r:?}");
        let (effect, source, owner, name, expected) = (r[0], r[1], r[2], r[3], r[4]);
        if !effects.contains_key(effect) {
            let fx = Effect::parse_file(&corpus.join(effect))
                .unwrap_or_else(|e| panic!("{effect} must parse: {e}"));
            effects.insert(effect, fx);
        }
        let fx = &effects[effect];
        let (kind, owner_name) = owner.split_once(' ').unwrap();
        let annotations = match kind {
            "global" => {
                let g: Vec<_> = fx
                    .ast
                    .globals
                    .iter()
                    .filter(|g| g.name == owner_name)
                    .collect();
                assert_eq!(
                    g.len(),
                    1,
                    "{owner} must match exactly one global in {effect}"
                );
                &g[0].annotations
            }
            "technique" => {
                let t: Vec<_> = fx
                    .ast
                    .techniques
                    .iter()
                    .filter(|t| t.name.as_deref() == Some(owner_name))
                    .collect();
                assert_eq!(
                    t.len(),
                    1,
                    "{owner} must match exactly one technique in {effect}"
                );
                &t[0].annotations
            }
            other => panic!("bad owner kind {other}"),
        };
        let a: Vec<_> = annotations.iter().filter(|a| a.name == name).collect();
        assert_eq!(
            a.len(),
            1,
            "{owner} must have exactly one annotation {name}"
        );
        let got = fmt(&a[0].value);
        let ok = match expected.strip_prefix('^') {
            Some(prefix) => {
                let prefix = prefix.trim_end_matches('"');
                got.starts_with(prefix) && got.len() > prefix.len()
            }
            None => got == expected,
        };
        if !ok {
            failures.push(format!(
                "{owner}.{name} in {effect}: expected {expected}, got {got}"
            ));
        }
        // The annotation must come from the source line the table names.
        let (path, src_line) = fx.origin(a[0].line).unwrap();
        let (want_file, want_line) = source.rsplit_once(':').unwrap();
        if !path.ends_with(want_file) || src_line.to_string() != want_line {
            failures.push(format!(
                "{owner}.{name}: expected source {source}, got {}:{src_line}",
                path.display()
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "golden mismatches:\n{}",
        failures.join("\n")
    );
    println!(
        "golden: {} of {} annotation values match",
        rows.len(),
        rows.len()
    );
}
