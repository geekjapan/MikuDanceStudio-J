//! The dialog lines of the `--mds-script` oracle (`tests/fixtures/rust/script/README.md`,
//! `script2/README.md`) run through the action table, the form and its OK button instead of
//! `Document::apply`; every file the script saves must equal the C++ output, and the info box of
//! the blinking dialog must say what `messages.tsv` recorded. The other lines run on
//! `mds_doc::script::Runner`, which owns the document, so the document is swapped into the
//! editor for the dialog lines and back.

use super::{fixtures, Rig};
use mds_app::ui::dialog;
use mds_doc::script::Runner;

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

fn fill(rig: &mut Rig, id: &str, values: &[&str]) -> Result<(), String> {
    rig.run(id)?;
    for (i, v) in values.iter().enumerate() {
        rig.type_into(i, v);
    }
    rig.ok()
}

/// What the dialog does for a script line, or `None` if the line is not of this area.
fn drive(rig: &mut Rig, line: &str) -> Option<Result<(), String>> {
    let w: Vec<&str> = line.split_whitespace().collect();
    Some(match w.as_slice() {
        ["bias", v @ ..] => fill(rig, "dlg:IDD_CENTER_POSITION_BIAS", v),
        ["shift", "lip", n] => fill(rig, "dlg:IDD_FRAME_SHIFT", &[n]),
        ["register", "blink", a, b] => fill(rig, "dlg:IDD_REGISTER_BLINKING", &[a, b]),
        ["multiply", "camera", v @ ..] => fill(rig, "dlg:IDD_CAMERA_FRAME_MULTIPLY", v),
        ["multiply", "bone", v @ ..] => fill(rig, "dlg:IDD_BONE_FRAME_MULTIPLY", v),
        ["multiply", "morph", v @ ..] => fill(rig, "dlg:IDD_MORPH_MULTIPLY", v),
        // Combo item 0 is "ON (X印)", item 1 "OFF".
        ["physics", "frames", on] => rig.run("dlg:IDD_PHYSICS_FRAME_CONVERSION").and_then(|()| {
            rig.with(|c| dialog::set_pick(c, usize::from(*on == "off")));
            rig.ok()
        }),
        ["gravity", "open"] => rig.run("dlg:IDD_GRAVITY"),
        ["gravity", "magnitude", m] => {
            rig.type_into(0, m);
            Ok(())
        }
        ["gravity", "direction", x, y, z] => {
            for (i, v) in [x, y, z].into_iter().enumerate() {
                rig.type_into(1 + i, v);
            }
            Ok(())
        }
        ["register", "gravity"] => {
            rig.with(dialog::register_gravity);
            Ok(())
        }
        ["gravity", "close"] => {
            rig.cancel();
            Ok(())
        }
        _ => return None,
    })
}

struct Outcome {
    files: usize,
    dialog_lines: usize,
    messages: Vec<String>,
}

fn replay(dir: &str, name: &str) -> Outcome {
    let root = fixtures().join(dir);
    let expected_dir = root.join("expected").join(name);
    let script = std::fs::read_to_string(root.join(format!("{name}.txt"))).unwrap();
    let mut runner = Runner::new();
    let mut rig = Rig::new(mds_app::editor::Editor::empty());
    let mut out = Outcome {
        files: 0,
        dialog_lines: 0,
        messages: Vec::new(),
    };
    for (n, line) in script.lines().enumerate() {
        let at = format!("{name}.txt line {} ({line})", n + 1);
        std::mem::swap(&mut rig.editor.doc, &mut runner.doc);
        let driven = drive(&mut rig, line);
        std::mem::swap(&mut rig.editor.doc, &mut runner.doc);
        let saved = match driven {
            Some(r) => {
                r.unwrap_or_else(|e| panic!("{at}: {e}"));
                // The runner pumps the frame loop twice after each step it runs, and the poses
                // of a physics model depend on it. `gravity open` only sets the runner's flag.
                runner
                    .run_line("gravity open", &mut |p| read_input(p))
                    .unwrap();
                out.dialog_lines += 1;
                if !rig.status.is_empty() {
                    out.messages.push(std::mem::take(&mut rig.status));
                }
                Vec::new()
            }
            None => runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{at}: {e}")),
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
            out.files += 1;
        }
    }
    out
}

fn check(dir: &str, name: &str, dialog_lines: usize, files: usize) -> Outcome {
    let out = replay(dir, name);
    eprintln!(
        "{dir}/{name}: {} files equal, {} lines through the dialogs",
        out.files, out.dialog_lines
    );
    assert_eq!(
        (out.dialog_lines, out.files),
        (dialog_lines, files),
        "{name}"
    );
    out
}

#[test]
fn bias_script() {
    check("script2", "bias", 1, 2);
}

#[test]
fn lip_shift_script() {
    check("script2", "lipshift", 2, 4);
}

/// The info box of case 227 (`まばたき追加`), as `messages.tsv` recorded it.
#[test]
fn blink_script() {
    let out = check("script2", "blink", 2, 4);
    let tsv =
        std::fs::read_to_string(fixtures().join("script2/expected/blink/messages.tsv")).unwrap();
    let want: Vec<&str> = tsv
        .lines()
        .skip(1)
        .map(|l| l.split('\t').nth(2).unwrap())
        .collect();
    assert_eq!(out.messages, want);
}

#[test]
fn multiply_scripts() {
    check("script2", "multiply-bone", 1, 2);
    check("script2", "multiply-camera", 1, 2);
    check("script2", "multiply-morph", 1, 2);
}

#[test]
fn physics_frames_script() {
    check("script2", "physicsframes", 2, 4);
}

/// Gravity: open, magnitude, direction (X, Y, Z), register, close.
#[test]
fn gravity_lines_of_the_camera_script() {
    check("script", "camera", 5, 8);
}
