//! The dialog lines of the `--mds-script` oracle (`tests/fixtures/rust/script/README.md`,
//! `script2/README.md`) run through the action table, the form and its OK button instead of
//! `Document::apply`; every file the script saves must equal the C++ output, and the info box of
//! the blinking dialog must say what `messages.tsv` recorded. The other lines run on
//! `mds_doc::script::Runner`, which owns the document, so the document is swapped into the
//! editor for the dialog lines and back.

use super::{fixtures, Rig};
use mds_app::navigation::KeyState;
use mds_app::ui::{dialog, viewport};
use mds_doc::script::Runner;

fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [
        fixtures(),
        fixtures().join("script/inputs"),
        fixtures().join("script2/inputs"),
        fixtures().join("script3/inputs"),
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

/// The words of a script line; a quoted word keeps its spaces (`mds_doc::script`'s `words`).
fn words(line: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut rest = line.trim_start();
    while !rest.is_empty() {
        let (word, tail) = match rest.strip_prefix('"') {
            Some(q) => q.split_once('"').expect("a closed quote"),
            None => rest.split_once(char::is_whitespace).unwrap_or((rest, "")),
        };
        out.push(word);
        rest = tail.trim_start();
    }
    out
}

/// The boxes and combos of the English names dialog (`english_name_dialog.cpp`): edits 667 the
/// model name, 668 the comment, 672, 676 and 680 the bone, morph and group of combos 669, 673
/// and 677.
const NAME_BOXES: [&str; 5] = ["667", "668", "672", "676", "680"];
const NAME_COMBOS: [&str; 3] = ["669", "673", "677"];

/// What the dialog does for a script line, or `None` if the line is not of this area.
fn drive(rig: &mut Rig, line: &str) -> Option<Result<(), String>> {
    let w = words(line);
    let names = rig.shown() == Some("IDD_ENGLISH_NAMES");
    Some(match w.as_slice() {
        ["english", "open"] => rig.run("dlg:IDD_ENGLISH_NAMES"),
        ["dialog", "text", id, text] if names => {
            let i = NAME_BOXES.iter().position(|b| b == id).expect("a name box");
            rig.type_into(i, text);
            Ok(())
        }
        ["dialog", "select", id, n] if names => {
            let combo = NAME_COMBOS.iter().position(|c| c == id).expect("a combo");
            rig.with(|c| dialog::names_select(c, combo, n.parse().unwrap()))
        }
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
        ["scale", "range", a, b, rate, bone, morph, display] => {
            rig.run("dlg:IDD_FRAME_SCALE").and_then(|()| {
                for (i, v) in [a, b, rate].into_iter().enumerate() {
                    rig.type_into(i, v);
                }
                for (i, on) in [bone, morph, display].into_iter().enumerate() {
                    rig.with(|c| dialog::set_check(c, i, *on == "on"));
                }
                rig.ok()
            })
        }
        // Menu 261: the edit `708 + slot`, then OK.
        ["toon", slot, name] => rig.run("dlg:IDD_TOON_TEXTURE").and_then(|()| {
            rig.type_into(slot.parse::<usize>().unwrap() - 1, name);
            rig.ok()
        }),
        ["physics", "model", "open"] => rig.run("dlg:IDD_PHYSICS_MODEL"),
        ["dialog", "text", id, text] => {
            rig.with(|c| dialog::physics_text(c, id.parse().unwrap(), text))
        }
        ["dialog", "select", id, n] => {
            rig.with(|c| dialog::physics_pick(c, id.parse().unwrap(), n.parse().unwrap()))
        }
        ["dialog", "click", id] => rig.with(|c| dialog::physics_press(c, id.parse().unwrap())),
        ["physics", "drag", what, axis, modifier, dy] => {
            record_drag(rig, what, axis, *modifier == "shift", dy.parse().unwrap());
            Ok(())
        }
        ["dialog", "ok"] => rig.ok(),
        ["dialog", "cancel"] => {
            rig.cancel();
            Ok(())
        }
        _ => return None,
    })
}

/// A left drag on a model tool row of an 800 x 600 viewport (`ViewportToolAtPoint`,
/// `frame_modes.cpp:115`: the upper row rotates, the lower one moves, the columns are X, Y and Z),
/// moved down by `dy` rows: the record drag of the physics model dialog
/// (`EditModeRecord`, `frame_modes_bone.cpp:158`).
fn record_drag(rig: &mut Rig, what: &str, axis: &str, shift: bool, dy: f32) {
    let x = match axis {
        "x" => 690.0,
        "y" => 730.0,
        _ => 770.0,
    };
    let y = if what == "rotate" { 535.0 } else { 575.0 };
    let pass = |pos: [f32; 2], left| viewport::Input {
        pos: Some(pos),
        size: [800.0, 600.0],
        left,
        right: KeyState::Idle,
        middle: KeyState::Idle,
        right_double_click: false,
        pixels: [0, 0],
        wheel: 0.0,
        shift,
        ctrl: false,
    };
    for i in [
        pass([x, y], KeyState::Pressed),
        pass([x, y + dy], KeyState::Held),
        pass([x, y + dy], KeyState::Released),
    ] {
        rig.with(|c| viewport::input(c, &i));
    }
    // The window draws the dialog after the viewport in the same pass, which echoes the drag into
    // its boxes (`EchoRecord`) before OK can read them.
    rig.draw(Vec::new());
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
    // The toon dialog looks for a file beside the model: `.\lips.pmd` is in script3/inputs.
    rig.editor.path = Some(fixtures().join("script3/inputs/scene.pmm"));
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
        let words: Vec<&str> = line.split_whitespace().collect();
        let saved: Vec<(String, Vec<u8>)> = match driven {
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
            // The path of a "save enhanced model" is the dialog's `.\<name>`, which a later PMM
            // records; the runner records the bare name.
            None if matches!(words.as_slice(), ["save", "pmd", _]) => {
                let name = words[2];
                let bytes = runner
                    .doc
                    .save_pmd(&format!(".\\{name}"))
                    .unwrap_or_else(|e| panic!("{at}: {e}"));
                vec![(name.to_string(), bytes)]
            }
            None => runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{at}: {e}"))
                .into_iter()
                .map(|s| (s.name, s.bytes))
                .collect(),
        };
        for (name, bytes) in saved.into_iter().filter(|s| !s.0.ends_with(".emm")) {
            let want = std::fs::read(expected_dir.join(&name)).unwrap();
            assert!(
                bytes == want,
                "{at} {name}: differs from the C++ output ({} and {} bytes, first difference at {:?})",
                bytes.len(),
                want.len(),
                bytes.iter().zip(&want).position(|(a, b)| a != b)
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

/// Button 424 (`script2/scalerange.txt`): the frame scale dialog on a model with keys.
#[test]
fn scale_range_script() {
    check("script2", "scalerange", 2, 4);
}

/// Menu 261 and 262 (`script3/pmdedit.txt`): a toon name, then the physics model dialog with the
/// mass of body 0, the position and box shape of body 3, and OK; the saved PMD is the C++ one,
/// and Cancel drops what was typed. The two reminder boxes say what `messages.tsv` recorded.
/// Menu 259 (`script3/english.txt`): the five boxes and three combos, OK, then Cancel. The PMM
/// saved after OK holds the selection of the bone combo (`SelectEnglishNameBone`) and edit mode 0
/// from the opening of the dialog.
#[test]
fn english_script() {
    let out = check("script3", "english", 13, 3);
    assert_eq!(
        out.messages,
        ["編集結果は'拡張モデル保存'で新しいモデルとして保存して下さい"]
    );
}

#[test]
fn pmdedit_script() {
    let out = check("script3", "pmdedit", 10, 3);
    let tsv =
        std::fs::read_to_string(fixtures().join("script3/expected/pmdedit/messages.tsv")).unwrap();
    let want: Vec<&str> = tsv
        .lines()
        .skip(1)
        .map(|l| l.split('\t').nth(2).unwrap())
        .collect();
    assert_eq!(out.messages, want);
}

/// `script4/jointdrag.txt`: on the joint page (801) the record drag edits the selected joint, and
/// the dialog opened again drags a body (`physicsEditorJointPage`, `frame_modes_bone.cpp:158`);
/// the three OK boxes say what `messages.tsv` recorded.
#[test]
fn jointdrag_script() {
    let out = check("script4", "jointdrag", 15, 5);
    let tsv = std::fs::read_to_string(fixtures().join("script4/expected/jointdrag/messages.tsv"))
        .unwrap();
    let want: Vec<&str> = tsv
        .lines()
        .skip(1)
        .map(|l| l.split('\t').nth(2).unwrap())
        .collect();
    assert_eq!(out.messages, want);
}
