//! `tests/fixtures/rust/script4/viewoffset.txt` with its `view drag` lines through
//! `viewport::input`: every PMM it saves equals the C++ output, `orbit.pmm` included, which
//! holds the plain and Ctrl right drags of model mode (`pump_navigation.cpp:335-342`). The other
//! lines run on `mds_doc::script::Runner`, which owns the document, so the document is swapped
//! into the editor for a UI line, and the runner pumps after it as after its own steps.

use super::{fixtures, input, Rig, SIZE};
use mds_app::editor::Editor;
use mds_app::navigation::KeyState;
use mds_app::ui::viewport;
use mds_doc::script::Runner;
use mds_doc::Document;

fn read_input(path: &str) -> Option<Vec<u8>> {
    std::fs::read(fixtures().join(path.trim_start_matches(".\\"))).ok()
}

/// One held pass of `button` that moved the cursor by `d`.
fn drag(button: &str, modifier: &str, d: [i32; 2]) -> viewport::Input {
    let mut i = input(Some([SIZE[0] / 2.0, SIZE[1] / 2.0]), KeyState::Idle, modifier == "shift");
    i.ctrl = modifier == "ctrl";
    i.pixels = d;
    match button {
        "right" => i.right = KeyState::Held,
        "middle" => i.middle = KeyState::Held,
        _ => panic!("button {button}"),
    }
    i
}

#[test]
fn viewoffset_txt_saves_the_bytes_of_the_cpp_application() {
    let root = fixtures().join("script4");
    let expected = root.join("expected/viewoffset");
    let script = std::fs::read_to_string(root.join("viewoffset.txt")).unwrap();
    let mut runner = Runner::new();
    let mut r = Rig::new(Editor::new(Document::startup(), None).unwrap());
    let (mut drags, mut files) = (0, 0);
    for (n, line) in script.lines().enumerate() {
        let at = format!("viewoffset.txt line {} ({line})", n + 1);
        let w: Vec<&str> = line.split_whitespace().collect();
        let saved = if let ["view", "drag", button, modifier, dx, dy] = w.as_slice() {
            let d = [dx, dy].map(|v| v.parse::<i32>().unwrap());
            std::mem::swap(&mut r.e.doc, &mut runner.doc);
            r.pass(drag(button, modifier, d));
            std::mem::swap(&mut r.e.doc, &mut runner.doc);
            runner.pump(&mut |p| read_input(p)).unwrap();
            drags += 1;
            Vec::new()
        } else {
            runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|e| panic!("{at}: {e}"))
        };
        for s in saved.into_iter().filter(|s| !s.name.ends_with(".emm")) {
            let want = std::fs::read(expected.join(&s.name)).unwrap();
            let first = s.bytes.iter().zip(&want).position(|(a, b)| a != b);
            assert!(s.bytes == want, "{at} {}: first difference at {first:?}", s.name);
            files += 1;
        }
    }
    assert_eq!((drags, files), (6, 4));
    assert!(!r.e.modified, "a view drag is not a scene edit");
}
