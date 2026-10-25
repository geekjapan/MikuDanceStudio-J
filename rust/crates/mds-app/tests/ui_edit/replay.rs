//! The select-all and frame-line lines of the `--mds-script` oracle
//! (`tests/fixtures/rust/script/README.md`), run through the action table instead of
//! `Document::apply`; every file the script saves must equal the C++ output. The other lines run
//! on `mds_doc::script::Runner`, which owns the document, so the document is swapped into the
//! editor for the lines of this area and back.
//!
//! `bones.txt` and `motion.txt` are not replayed: `mds-doc` cannot run them yet (its own
//! `tests/script.rs` ignores them).

use super::{fixtures, run, Editor};
use mds_doc::script::Runner;
use std::collections::BTreeMap;

fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [fixtures(), fixtures().join("script/inputs")]
        .iter()
        .find_map(|d| std::fs::read(d.join(name)).ok())
}

/// The action ids of a script line of this area; `keys` takes the frame-line keys instead of
/// their menu items.
fn action(line: &str, keys: bool) -> Option<&'static str> {
    let id = |menu, key| if keys { key } else { menu };
    Some(match line.trim() {
        "select all bone" => "menu:217",
        "select all display" => "menu:218",
        "select all morph" => "menu:220",
        "select all camera" => "menu:237",
        "select all light" => "menu:238",
        "select all shadow" => "menu:239",
        "select all gravity" => "menu:240",
        "select all accessory" => "menu:241",
        "line insert bone" => id("menu:255", "key:I"),
        "line delete bone" => id("menu:256", "key:K"),
        "line insert morph" => id("menu:257", "key:U"),
        "line delete morph" => id("menu:258", "key:J"),
        _ => return None,
    })
}

/// `(files compared, lines through the table)`.
fn replay(name: &str, keys: bool) -> (usize, usize) {
    let root = fixtures().join("script");
    let expected_dir = root.join("expected").join(name);
    let script = std::fs::read_to_string(root.join(format!("{name}.txt"))).unwrap();
    let mut runner = Runner::new();
    let mut editor = Editor::empty();
    let (mut compared, mut through_table) = (0, 0);
    for (n, line) in script.lines().enumerate() {
        let saved = match action(line, keys) {
            Some(id) => {
                std::mem::swap(&mut editor.doc, &mut runner.doc);
                let r = run(&mut editor, id);
                std::mem::swap(&mut editor.doc, &mut runner.doc);
                r.unwrap_or_else(|e| panic!("{name}.txt line {} ({line}): {e}", n + 1));
                through_table += 1;
                Vec::new()
            }
            None => runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{name}.txt line {} ({line}): {e}", n + 1)),
        };
        for s in saved.into_iter().filter(|s| !s.name.ends_with(".emm")) {
            let want = std::fs::read(expected_dir.join(&s.name)).unwrap();
            assert!(
                s.bytes == want,
                "{name}.txt line {} {}: differs from the C++ output ({} and {} bytes)",
                n + 1,
                s.name,
                s.bytes.len(),
                want.len()
            );
            compared += 1;
        }
    }
    (compared, through_table)
}

fn check(name: &str, lines: usize, files: usize) {
    if !fixtures().join("script/expected").join(name).is_dir() {
        println!("SKIP: tests/fixtures/rust/script/expected/{name} is missing");
        return;
    }
    let mut seen = BTreeMap::new();
    for keys in [false, true] {
        let (compared, through) = replay(name, keys);
        eprintln!(
            "{name} (keys: {keys}): {compared} files equal, {through} lines through the table"
        );
        seen.insert(keys, (compared, through));
    }
    for (compared, through) in seen.into_values() {
        assert_eq!((through, compared), (lines, files), "{name}");
    }
}

#[test]
fn camera_script() {
    check("camera", 10, 8);
}

#[test]
fn morphs_script() {
    check("morphs", 7, 7);
}

#[test]
fn accessory_script() {
    check("accessory", 2, 3);
}
