//! Button 437 (delete model) through the action table: `script3/deletemodel.txt` with its
//! `delete model` lines pressed on the editor, every saved PMM equal to the C++ output.

use crate::common::{editor, fixtures, run};
use mds_doc::script::Runner;

fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    ["script/inputs", "script2/inputs", "script3/inputs", ""]
        .iter()
        .find_map(|d| std::fs::read(fixtures().join(d).join(name)).ok())
}

#[test]
fn deletemodel_txt_saves_the_bytes_of_the_cpp_application() {
    let root = fixtures().join("script3");
    let script = std::fs::read_to_string(root.join("deletemodel.txt")).unwrap();
    let mut runner = Runner::new();
    let mut e = editor();
    let (mut files, mut pressed) = (0, 0);
    for (n, line) in script.lines().enumerate() {
        let at = format!("deletemodel.txt line {} ({line})", n + 1);
        let saved = if line.trim() == "delete model" {
            std::mem::swap(&mut e.doc, &mut runner.doc);
            let r = run(&mut e, "ctl:437");
            std::mem::swap(&mut e.doc, &mut runner.doc);
            r.unwrap_or_else(|x| panic!("{at}: {x}"));
            runner.pump(&mut |p| read_input(p)).unwrap();
            pressed += 1;
            Vec::new()
        } else {
            runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|x| panic!("{at}: {x}"))
        };
        for s in saved.into_iter().filter(|s| !s.name.ends_with(".emm")) {
            let want = std::fs::read(root.join("expected/deletemodel").join(&s.name)).unwrap();
            assert!(
                s.bytes == want,
                "{at} {}: differs from the C++ output",
                s.name
            );
            files += 1;
        }
    }
    assert_eq!((pressed, files), (2, 3));
}

#[test]
fn the_button_needs_a_model_and_is_a_model_mode_action() {
    let mut e = editor();
    assert!(run(&mut e, "ctl:437").is_err(), "no model is loaded");
    let a = mds_app::actions::find("ctl:437").unwrap();
    assert!(a.needs_document);
    assert_eq!(a.only, mds_app::actions::Mode::Model);
}

#[test]
fn the_question_names_the_model_in_both_languages() {
    use mds_app::ui::model_panel::delete_question;
    let (caption, en) = delete_question("Miku", true);
    assert_eq!(caption, "モデル削除");
    assert!(en.starts_with("Trying to delete Model(Miku)."));
    assert!(delete_question("初音", false)
        .1
        .starts_with("モデル：初音を削除します"));
}
