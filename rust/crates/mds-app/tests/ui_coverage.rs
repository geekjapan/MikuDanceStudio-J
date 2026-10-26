//! The action table against `tools/ui_inventory/inventory.tsv`: every action id is an inventory
//! row of the area whose file registers it, no id is registered twice, and every row of an area
//! in `ui::COMPLETE` has an action. Prints implemented / dropped / missing per area.

use mds_app::actions::{Action, Handler};
use mds_app::ui::{AREAS, COMPLETE};
use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;

/// `(id, area)` of every inventory row.
fn inventory() -> Vec<(String, String)> {
    let path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tools/ui_inventory/inventory.tsv");
    let text = std::fs::read_to_string(&path).unwrap();
    let mut lines = text.lines();
    let header: Vec<_> = lines.next().unwrap().split('\t').collect();
    let col = |name| header.iter().position(|h| *h == name).unwrap();
    let (id, area) = (col("id"), col("area"));
    lines
        .map(|l| {
            let f: Vec<_> = l.split('\t').collect();
            (f[id].to_string(), f[area].to_string())
        })
        .collect()
}

#[derive(Default, Debug)]
struct Count {
    implemented: usize,
    dropped: usize,
    missing: Vec<String>,
}

/// The per-area counts, or every violation of the rules in the file doc.
fn check(
    rows: &[(String, String)],
    registered: &[(&str, &Action)],
    complete: &[&str],
) -> Result<BTreeMap<String, Count>, Vec<String>> {
    let area_of: HashMap<&str, &str> = rows.iter().map(|(i, a)| (i.as_str(), a.as_str())).collect();
    let mut errors = Vec::new();
    let mut by_id: HashMap<&str, &Action> = HashMap::new();
    for &(area, action) in registered {
        match area_of.get(action.id) {
            None => errors.push(format!("{}: not in the inventory", action.id)),
            Some(&a) if a != area => errors.push(format!(
                "{}: registered by {area}, inventory area {a}",
                action.id
            )),
            Some(_) => {}
        }
        if by_id.insert(action.id, action).is_some() {
            errors.push(format!("{}: registered twice", action.id));
        }
    }
    let mut counts: BTreeMap<String, Count> = BTreeMap::new();
    for (id, area) in rows {
        let c = counts.entry(area.clone()).or_default();
        match by_id.get(id.as_str()).map(|a| a.handler) {
            Some(Handler::Run(_) | Handler::Inline) => c.implemented += 1,
            Some(Handler::Dropped(_)) => c.dropped += 1,
            None => c.missing.push(id.clone()),
        }
    }
    for area in complete {
        match counts.get(*area) {
            None => errors.push(format!("complete area {area} has no inventory rows")),
            Some(c) if !c.missing.is_empty() => {
                errors.push(format!("complete area {area} misses {:?}", c.missing))
            }
            Some(_) => {}
        }
    }
    if errors.is_empty() {
        Ok(counts)
    } else {
        Err(errors)
    }
}

fn registered() -> Vec<(&'static str, &'static Action)> {
    AREAS
        .iter()
        .flat_map(|a| (a.actions)().iter().map(move |x| (a.name, x)))
        .collect()
}

#[test]
fn the_action_table_covers_the_inventory() {
    let rows = inventory();
    assert_eq!(rows.len(), 431);
    let counts = check(&rows, &registered(), COMPLETE).unwrap_or_else(|e| panic!("{e:#?}"));
    let (mut done, mut dropped, mut missing) = (0, 0, 0);
    for (area, c) in &counts {
        eprintln!(
            "{area:16} implemented {:3}  dropped {:3}  missing {:3}",
            c.implemented,
            c.dropped,
            c.missing.len()
        );
        done += c.implemented;
        dropped += c.dropped;
        missing += c.missing.len();
    }
    eprintln!(
        "{:16} implemented {done:3}  dropped {dropped:3}  missing {missing:3}",
        "total"
    );
    let areas: Vec<_> = AREAS.iter().map(|a| a.name).collect();
    assert_eq!(counts.keys().collect::<Vec<_>>().len(), areas.len());
    assert!(
        counts.keys().all(|k| areas.contains(&k.as_str())),
        "an inventory area without a ui file"
    );
}

#[test]
fn the_check_rejects_what_it_should() {
    let rows = inventory();
    let ok = registered();
    let bogus = Action::inline("menu:99999");
    let wrong_area = Action::inline("menu:268");
    let mut bad = ok.clone();
    bad.push(("file", &bogus));
    bad.push(("file", &wrong_area));
    let errors = check(&rows, &bad, COMPLETE).unwrap_err();
    assert!(
        errors.iter().any(|e| e.starts_with("menu:99999: not in")),
        "{errors:?}"
    );
    assert!(errors
        .iter()
        .any(|e| e.contains("registered by file, inventory area physics")));
    assert!(errors.iter().any(|e| e == "menu:268: registered twice"));
    let errors = check(&rows, &ok, &["file"]).unwrap_err();
    assert!(
        errors[0].starts_with("complete area file misses"),
        "{errors:?}"
    );
}
