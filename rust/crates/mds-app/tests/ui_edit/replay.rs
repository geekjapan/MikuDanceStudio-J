//! The lines of the `--mds-script` oracle (`tests/fixtures/rust/script/README.md` and
//! `script2/README.md`) that drive a menu of the `edit`, `expression` and `help` areas, run
//! through the action table instead of `Document::apply`: the select-all and frame-line menus,
//! paste to another bone, delete unused frames, the bias and multiply dialogs, the lip, blink and
//! register-all menus, and save enhanced model. Dialogs go through their form: open it with the
//! menu's action, type the script's values into the edit boxes, press OK. Every file the script
//! saves must equal the C++ output, and the info boxes the C++ answered (`messages.tsv`) are the
//! status line.
//!
//! The other lines run on `mds_doc::script::Runner`, which owns the document, so the document is
//! swapped into the editor for the lines of this area and back.

use super::{fixtures, rig::Rig};
use mds_app::ui::help;
use mds_doc::script::{Runner, Saved};
use std::collections::BTreeMap;

fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [
        fixtures(),
        fixtures().join("script/inputs"),
        fixtures().join("script2/inputs"),
    ]
    .iter()
    .find_map(|d| std::fs::read(d.join(name)).ok())
}

/// A script line of this area: the action id and, for a dialog, what the script types into its
/// edit boxes (empty for a question).
struct Step {
    id: &'static str,
    boxes: Option<Vec<String>>,
    /// The saved pose depends on the frame loop that follows the line. The runner pumps
    /// the frame loop after every line; the editor's pump is another world, so the line runs on
    /// the runner as the oracle does, and the table's result on a copy of the document before it
    /// is compared with the runner's key pools.
    mirror: bool,
}

/// `keys` takes the letter keys instead of their menu items.
fn step(line: &str, keys: bool) -> Option<Step> {
    let id = |menu, key| if keys { key } else { menu };
    let w: Vec<&str> = line.split_whitespace().collect();
    let plain = |id| {
        Some(Step {
            id,
            boxes: None,
            mirror: false,
        })
    };
    let dialog = |id, boxes: &[&str]| {
        Some(Step {
            id,
            boxes: Some(boxes.iter().map(|b| b.to_string()).collect()),
            mirror: false,
        })
    };
    match w.as_slice() {
        ["select", "all", what] => plain(match *what {
            "bone" => "menu:217",
            "display" => "menu:218",
            "morph" => "menu:220",
            "camera" => "menu:237",
            "light" => "menu:238",
            "shadow" => "menu:239",
            "gravity" => "menu:240",
            "accessory" => "menu:241",
            _ => return None,
        }),
        ["line", "insert", "bone"] => plain(id("menu:255", "key:I")),
        ["line", "delete", "bone"] => plain(id("menu:256", "key:K")),
        ["line", "insert", "morph"] => plain(id("menu:257", "key:U")),
        ["line", "delete", "morph"] => plain(id("menu:258", "key:J")),
        ["paste", "different"] => {
            let mut s = dialog(id("menu:250", "key:F"), &[])?;
            s.mirror = true;
            Some(s)
        }
        ["delete", "unused"] => plain("menu:222"),
        ["bias", x, y, z] => dialog(id("menu:219", "key:D"), &[x, y, z]),
        ["shift", "lip", n] => dialog("menu:225", &[n]),
        ["delete", "lip"] => dialog("menu:226", &[]),
        ["delete", "eye"] => dialog("menu:228", &[]),
        ["delete", "eyebrow"] => dialog("menu:231", &[]),
        ["register", "blink", from, to] => dialog("menu:227", &[from, to]),
        ["register", "all", "morph"] => plain(id("menu:229", "key:H")),
        ["reset", "morphs"] => plain("menu:230"),
        ["multiply", "camera", rest @ ..] if rest.len() == 16 => dialog("menu:242", rest),
        ["multiply", "bone", rest @ ..] if rest.len() == 12 => {
            let mut s = dialog(id("menu:251", "key:R"), rest)?;
            s.mirror = true;
            Some(s)
        }
        ["multiply", "morph", scale, add] => dialog("menu:252", &[scale, add]),
        _ => None,
    }
}

/// The text of every answered info box, by script line.
fn messages(dir: &std::path::Path) -> BTreeMap<usize, String> {
    let Ok(text) = std::fs::read_to_string(dir.join("messages.tsv")) else {
        return BTreeMap::new();
    };
    text.lines()
        .skip(1)
        .map(|l| {
            let w: Vec<&str> = l.split('\t').collect();
            (w[0].parse().unwrap(), w[2].to_string())
        })
        .collect()
}

/// `(files compared, lines through the table)`.
fn replay(set: &str, name: &str, keys: bool) -> (usize, usize) {
    let root = fixtures().join(set);
    let expected_dir = root.join("expected").join(name);
    let script = std::fs::read_to_string(root.join(format!("{name}.txt"))).unwrap();
    let mut boxes = messages(&expected_dir);
    let mut runner = Runner::new();
    let mut rig = Rig::new();
    let (mut compared, mut through_table) = (0, 0);
    for (n, line) in script.lines().enumerate() {
        let at = format!("{name}.txt line {} ({line})", n + 1);
        let swap = |rig: &mut Rig, runner: &mut Runner| {
            std::mem::swap(&mut rig.editor.doc, &mut runner.doc);
        };
        let step = step(line, keys);
        let saved = if let Some(step) = step.as_ref().filter(|s| s.mirror) {
            rig.editor.doc = runner.doc.clone();
            let b: Vec<&str> = step.boxes.iter().flatten().map(String::as_str).collect();
            rig.answer(step.id, &b)
                .unwrap_or_else(|e| panic!("{at}: {e}"));
            let saved = runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{at}: {e}"));
            for (a, b) in rig.editor.doc.pmm.models.iter().zip(&runner.doc.pmm.models) {
                assert_eq!(
                    format!("{:?}", a.bone_keys),
                    format!("{:?}", b.bone_keys),
                    "{at}: the bone keys"
                );
            }
            through_table += 1;
            saved
        } else if let Some(step) = step {
            swap(&mut rig, &mut runner);
            let r = match &step.boxes {
                None => rig.run(step.id),
                Some(b) => {
                    let b: Vec<&str> = b.iter().map(String::as_str).collect();
                    rig.answer(step.id, &b)
                }
            };
            swap(&mut rig, &mut runner);
            r.unwrap_or_else(|e| panic!("{at}: {e}"));
            if let Some(text) = boxes.remove(&(n + 1)) {
                assert_eq!(rig.status, text, "{at}: the info box");
            }
            through_table += 1;
            Vec::new()
        } else if let Some(file) = line.trim().strip_prefix("save pmd ") {
            // The C++ saves to the path the file dialog returns; here a file of the temp folder.
            let path =
                std::env::temp_dir().join(format!("mds-uimenus2-{}-{file}", std::process::id()));
            swap(&mut rig, &mut runner);
            let r = rig.with_ctx(|ctx| help::save_enhanced(ctx, &path));
            swap(&mut rig, &mut runner);
            r.unwrap_or_else(|e| panic!("{at}: {e}"));
            let bytes = std::fs::read(&path).unwrap();
            std::fs::remove_file(&path).unwrap();
            through_table += 1;
            vec![Saved {
                name: file.to_string(),
                bytes,
            }]
        } else {
            runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{at}: {e}"))
        };
        for s in saved.into_iter().filter(|s| !s.name.ends_with(".emm")) {
            let want = std::fs::read(expected_dir.join(&s.name)).unwrap();
            assert!(
                s.bytes == want,
                "{at} {}: differs from the C++ output ({} and {} bytes)",
                s.name,
                s.bytes.len(),
                want.len()
            );
            compared += 1;
        }
    }
    assert!(
        boxes.is_empty(),
        "{name}: info boxes never shown: {boxes:?}"
    );
    (compared, through_table)
}

fn check(set: &str, name: &str, lines: usize, files: usize) {
    if !fixtures().join(set).join("expected").join(name).is_dir() {
        println!("SKIP: tests/fixtures/rust/{set}/expected/{name} is missing");
        return;
    }
    for keys in [false, true] {
        let (compared, through) = replay(set, name, keys);
        eprintln!(
            "{name} (keys: {keys}): {compared} files equal, {through} lines through the table"
        );
        assert_eq!((through, compared), (lines, files), "{name}, keys: {keys}");
    }
}

#[test]
fn camera_script() {
    check("script", "camera", 10, 8);
}

#[test]
fn morphs_script() {
    check("script", "morphs", 7, 7);
}

#[test]
fn accessory_script() {
    check("script", "accessory", 2, 3);
}

#[test]
fn bones_script() {
    check("script", "bones", 8, 12);
}

#[test]
fn bias_script() {
    check("script2", "bias", 3, 2);
}

#[test]
fn unused_script() {
    check("script2", "unused", 4, 6);
}

#[test]
fn lipshift_script() {
    check("script2", "lipshift", 4, 4);
}

#[test]
fn facial_script() {
    check("script2", "facial", 7, 8);
}

#[test]
fn blink_script() {
    check("script2", "blink", 4, 4);
}

#[test]
fn registerall_script() {
    check("script2", "registerall", 2, 2);
}

#[test]
fn resetmorphs_script() {
    check("script2", "resetmorphs", 2, 4);
}

#[test]
fn multiply_scripts() {
    check("script2", "multiply-camera", 3, 2);
    check("script2", "multiply-bone", 3, 2);
    check("script2", "multiply-morph", 3, 2);
}
