//! The labels of `tools/ui_inventory/inventory.tsv`, mnemonics dropped.

use std::path::PathBuf;

/// `(&D)` and `&D` are Win32 mnemonics.
fn plain(label: &str) -> String {
    let c: Vec<char> = label.chars().collect();
    let (mut out, mut i) = (String::new(), 0);
    while i < c.len() {
        if c[i] == '(' && c.get(i + 1) == Some(&'&') && c.get(i + 3) == Some(&')') {
            i += 4;
        } else {
            out.push(c[i]);
            i += 1;
        }
    }
    out
}

/// Every menu row of `area` has the label of `labels` in both languages.
pub fn check(area: &str, labels: &[(&str, &str, &str)]) {
    let path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tools/ui_inventory/inventory.tsv");
    let text = std::fs::read_to_string(path).unwrap();
    let rows: Vec<Vec<&str>> = text
        .lines()
        .skip(1)
        .map(|l| l.split('\t').collect::<Vec<_>>())
        .filter(|f| f[5] == area && f[0].starts_with("menu:"))
        .collect();
    assert_eq!(
        rows.len(),
        labels.len(),
        "{area}: menu rows without a label"
    );
    for f in rows {
        let &(_, ja, en) = labels
            .iter()
            .find(|l| l.0 == f[0])
            .unwrap_or_else(|| panic!("{}: no label", f[0]));
        assert_eq!(
            (ja, en),
            (plain(f[2]).as_str(), plain(f[3]).as_str()),
            "{}",
            f[0]
        );
    }
}
