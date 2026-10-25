//! The editor through the action table: saving, undo and redo, and the live physics world.

use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use mds_doc::{Command, Document};
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn open(name: &str) -> Editor {
    Editor::open(&dir().join(name)).unwrap_or_else(|e| panic!("{name}: {e}"))
}

/// Runs `id` through the table as a button or key would.
fn run(editor: &mut Editor, now_ms: u64, id: &str) -> Result<(), String> {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor,
        now_ms,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    mds_app::actions::run(&mut ctx, id)
}

fn fixtures() -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(dir())
        .unwrap()
        .filter_map(|e| e.ok()?.file_name().into_string().ok())
        .filter(|n| n.ends_with(".pmm"))
        .collect();
    names.sort();
    names
}

#[test]
fn open_then_save_writes_what_the_document_saves() {
    let out = std::env::temp_dir().join(format!("mds-app-save-{}", std::process::id()));
    std::fs::create_dir_all(&out).unwrap();
    let mut saved = 0;
    for name in fixtures() {
        let mut editor = match Editor::open(&dir().join(&name)) {
            Ok(e) => e,
            Err(e) => {
                eprintln!("SKIP {name}: the editor does not open it: {e}");
                continue;
            }
        };
        let data = std::fs::read(dir().join(&name)).unwrap();
        let doc = Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap();
        let path = out.join(&name);
        editor.path = Some(path.clone());
        editor.modified = true;
        run(&mut editor, 0, "menu:207").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), doc.save().unwrap(), "{name}");
        assert!(!editor.modified, "{name}: save clears the modified flag");
        saved += 1;
        eprintln!(
            "{name}: {} bytes, as Document::save",
            doc.save().unwrap().len()
        );
    }
    std::fs::remove_dir_all(&out).unwrap();
    assert_eq!(saved, 4, "every PMM fixture opens");
}

/// `(index, frame, previous, next)` of the first model's bone keys, heads first.
fn bone_links(d: &Document) -> Vec<(u32, u32, u32, u32)> {
    let pool = &d.pmm.models[0].bone_keys;
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    heads
        .chain(pool.records().iter().map(|(i, k)| (*i, k)))
        .map(|(i, k)| (i, k.frame, k.previous, k.next))
        .collect()
}

#[test]
fn undo_and_redo_through_the_table() {
    let mut editor = open("swing600.pmm");
    for c in [
        Command::SetFrame(150),
        Command::SelectBones(vec![1, 2]),
        Command::RegisterBoneKeys,
    ] {
        editor.apply(c).unwrap();
    }
    let registered = editor.doc.save().unwrap();
    let mut reference = open("swing600.pmm").doc;
    reference.apply(Command::SetFrame(150)).unwrap();
    reference.apply(Command::SelectBones(vec![1, 2])).unwrap();
    assert!(registered != reference.save().unwrap());

    run(&mut editor, 0, "ctl:400").unwrap();
    // UndoModelEdit restores the records' links and frames, not the freed slots' bytes.
    assert!(
        editor.doc.save().unwrap() != registered,
        "undo changes the document"
    );
    assert_eq!(
        bone_links(&editor.doc),
        bone_links(&reference),
        "undo restores the keys"
    );
    assert_eq!(
        run(&mut editor, 0, "key:Ctrl+Z"),
        Err("not applicable: nothing to undo".into())
    );
    run(&mut editor, 0, "key:Ctrl+X").unwrap();
    assert!(
        editor.doc.save().unwrap() == registered,
        "redo restores the register"
    );
    assert!(editor.modified);
    assert_eq!(editor.physics_opens, 1, "an edit keeps the physics world");

    run(&mut editor, 0, "ctl:408").unwrap();
    assert_eq!(
        run(&mut editor, 0, "ctl:400"),
        Err("ctl:400: not while playing".into())
    );
}

/// Seeks back and forth, plays for a while across a loop, stops, and returns the physics trace
/// of the frames on screen along the way.
fn session(name: &str) -> (String, usize) {
    let mut editor = open(name);
    let mut trace = String::new();
    let mut now = 0;
    let mut pump = |editor: &mut Editor, passes: u32, trace: &mut String| {
        for _ in 0..passes {
            now += 33;
            editor.pump(now).unwrap();
        }
        let frame = editor.shown_frame();
        editor.physics.write_frame(trace, frame).unwrap();
        now
    };
    pump(&mut editor, 3, &mut trace);
    editor.seek(150).unwrap();
    pump(&mut editor, 10, &mut trace);
    editor.seek(30).unwrap();
    pump(&mut editor, 10, &mut trace);
    run(&mut editor, 0, "ctl:418").unwrap();
    pump(&mut editor, 2, &mut trace);
    editor.options.looped = true;
    editor.options.start_frame = 30;
    editor.options.stop_frame = 60;
    let t = pump(&mut editor, 0, &mut trace);
    run(&mut editor, t, "ctl:408").unwrap();
    pump(&mut editor, 40, &mut trace);
    let t = pump(&mut editor, 0, &mut trace);
    run(&mut editor, t, "key:P").unwrap();
    pump(&mut editor, 5, &mut trace);
    run(&mut editor, 0, "menu:268").unwrap();
    pump(&mut editor, 5, &mut trace);
    (trace, editor.physics_opens)
}

#[test]
fn seeks_keep_the_world_and_two_runs_agree() {
    let (a, opens) = session("swing600-golden.pmm");
    assert_eq!(opens, 1, "a backward seek reopened the physics scene");
    assert!(a.lines().filter(|l| l.contains(" rigid ")).count() > 100);
    let (b, _) = session("swing600-golden.pmm");
    assert!(a == b, "two runs differ");
    eprintln!("{} trace lines, identical in two runs", a.lines().count());
}
