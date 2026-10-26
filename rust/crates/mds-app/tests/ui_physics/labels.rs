//! The labels of `tools/ui_inventory/inventory.tsv`, mnemonics dropped.

use std::path::PathBuf;

pub struct Row {
    pub id: String,
    pub area: String,
    pub ja: String,
    pub en: String,
}

/// `(&D)` and `&D` are Win32 mnemonics; a lone `&` ("camera & lighting") is text.
fn plain(label: &str) -> String {
    let c: Vec<char> = label.chars().collect();
    let (mut out, mut i) = (String::new(), 0);
    while i < c.len() {
        if c[i] == '(' && c.get(i + 1) == Some(&'&') && c.get(i + 3) == Some(&')') {
            i += 4;
        } else if c[i] == '&' && c.get(i + 1).is_some_and(|n| n.is_alphanumeric()) {
            i += 1;
        } else {
            out.push(c[i]);
            i += 1;
        }
    }
    out
}

pub fn inventory() -> Vec<Row> {
    let path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tools/ui_inventory/inventory.tsv");
    let text = std::fs::read_to_string(path).unwrap();
    text.lines()
        .skip(1)
        .map(|l| {
            let f: Vec<_> = l.split('\t').collect();
            Row {
                id: f[0].into(),
                area: f[5].into(),
                ja: plain(f[2]),
                en: plain(f[3]),
            }
        })
        .collect()
}

/// Every menu row of `area` has the label of `labels` in both languages.
pub fn check(area: &str, labels: &[(&str, &str, &str)]) {
    let rows: Vec<_> = inventory()
        .into_iter()
        .filter(|r| r.area == area && r.id.starts_with("menu:"))
        .collect();
    let menus: Vec<_> = labels.iter().filter(|l| l.0.starts_with("menu:")).collect();
    assert_eq!(rows.len(), menus.len(), "{area}: menu rows without a label");
    for r in rows {
        let &&(_, ja, en) = menus
            .iter()
            .find(|l| l.0 == r.id)
            .unwrap_or_else(|| panic!("{}: no label", r.id));
        assert_eq!((ja, en), (r.ja.as_str(), r.en.as_str()), "{}", r.id);
    }
}
