//! The `background` area through the action table, with no window: the 13 rows of the
//! Background menu. The loads need `EditState::viewport`, which the window sets; the tests set it
//! where they load.

use mds_app::actions;
use mds_app::editor::Editor;
use mds_app::ui::{background, dialog, Ctx};
use mds_doc::{Command, ViewOption};
use mds_formats::pmm::Pmm;
use mds_formats::text::FixedSjis;
use std::path::PathBuf;

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn swing() -> Editor {
    Editor::open(&fixtures().join("swing600.pmm")).unwrap()
}

fn run(e: &mut Editor, egui: Option<&egui::Context>, id: &str) -> Result<(), String> {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: e,
        now_ms: 0,
        egui: egui.cloned(),
        viewport: None,
        status: &mut status,
    };
    actions::run(&mut ctx, id)
}

fn reload(e: &Editor) -> Pmm {
    Pmm::read(&e.doc.save().unwrap()).unwrap()
}

const ROWS: [&str; 13] = [
    "menu:249", "menu:288", "menu:289", "menu:282", "key:B", "menu:213", "menu:232", "menu:216",
    "menu:233", "menu:243", "menu:244", "menu:245", "menu:246",
];

#[test]
fn the_area_registers_its_thirteen_rows() {
    let mut ids: Vec<&str> = background::actions().iter().map(|a| a.id).collect();
    let mut want = ROWS.to_vec();
    ids.sort_unstable();
    want.sort_unstable();
    assert_eq!(ids, want);
}

/// Menu 282 and `B` flip `blackBackgroundEnabled`; the handler leaves `SceneModified` alone, and
/// the PMM keeps the flag.
#[test]
fn black_background_is_flipped_by_the_menu_and_the_key() {
    let mut e = swing();
    e.modified = false;
    let was = e.doc.pmm.appearance.black_background;
    for (n, id) in ["menu:282", "key:B", "key:B"].into_iter().enumerate() {
        run(&mut e, None, id).unwrap();
        let on = e.doc.pmm.appearance.black_background;
        assert_eq!(on != 0, (was != 0) ^ (n % 2 == 0), "{id} #{n}");
        assert!(!e.modified, "{id}");
    }
    assert_eq!(reload(&e).appearance.black_background, u8::from(was == 0));
    let mut oracle = swing();
    oracle
        .doc
        .apply(Command::SetViewOption {
            option: ViewOption::BlackBackground,
            on: was == 0,
        })
        .unwrap();
    assert!(e.doc.save().unwrap() == oracle.doc.save().unwrap());
}

/// The radio items 243 to 246 store 0 to 3 in the PMM's capture mode.
#[test]
fn the_capture_modes_are_a_radio() {
    let mut e = swing();
    for (id, mode) in [
        ("menu:244", 1),
        ("menu:246", 3),
        ("menu:245", 2),
        ("menu:243", 0),
    ] {
        run(&mut e, None, id).unwrap();
        assert_eq!(e.doc.pmm.view.capture_mode, mode, "{id}");
        assert_eq!(reload(&e).view.capture_mode, mode, "{id} saved");
        assert!(!e.modified);
    }
}

fn path(text: &str) -> FixedSjis<256> {
    let mut raw = [0u8; 256];
    raw[..text.len()].copy_from_slice(text.as_bytes());
    FixedSjis {
        raw,
        text: text.into(),
    }
}

/// Menu 216 and 233: showing needs a loaded file, hiding is free.
#[test]
fn showing_a_background_needs_a_loaded_file() {
    let mut e = swing();
    e.doc.pmm.avi.enabled = 0;
    e.doc.pmm.avi.path = path("");
    e.doc.pmm.picture.enabled = 0;
    e.doc.pmm.picture.path = path("");
    e.modified = false;
    run(&mut e, None, "menu:216").unwrap();
    run(&mut e, None, "menu:233").unwrap();
    assert_eq!((e.doc.pmm.avi.enabled, e.doc.pmm.picture.enabled), (0, 0));

    e.doc.pmm.avi.path = path("C:\\bg\\a.avi");
    e.doc.pmm.picture.path = path("C:\\bg\\a.bmp");
    run(&mut e, None, "menu:216").unwrap();
    run(&mut e, None, "menu:233").unwrap();
    assert_eq!((e.doc.pmm.avi.enabled, e.doc.pmm.picture.enabled), (1, 1));
    run(&mut e, None, "menu:216").unwrap();
    assert_eq!((e.doc.pmm.avi.enabled, e.doc.pmm.picture.enabled), (0, 1));
    run(&mut e, None, "menu:233").unwrap();
    assert_eq!((e.doc.pmm.avi.enabled, e.doc.pmm.picture.enabled), (0, 0));
    assert!(!e.modified, "the handlers do not set SceneModified");
}

#[test]
fn the_three_dialog_rows_open_their_dialogs() {
    let mut e = swing();
    let egui = egui::Context::default();
    for (id, name) in [
        ("menu:249", "IDD_ACCESSORY_ORDER"),
        ("menu:288", "IDD_MODEL_DRAW_ORDER"),
        ("menu:289", "IDD_MODEL_CALCULATE_ORDER"),
    ] {
        run(&mut e, Some(&egui), id).unwrap();
        assert_eq!(dialog::current(&egui), Some(name), "{id}");
        let mut status = String::new();
        dialog::cancel(&mut Ctx {
            editor: &mut e,
            now_ms: 0,
            egui: Some(egui.clone()),
            viewport: None,
            status: &mut status,
        });
        assert_eq!(dialog::current(&egui), None);
        assert!(actions::find(id).unwrap().needs_document);
    }
}

/// The loads read the file, then the document refuses to place it without a viewport; nothing
/// changes (no path, no `enabled`, no `SceneModified`). With a window the file dialog opens
/// first, so the actions themselves need one.
#[test]
fn a_load_without_a_viewport_changes_nothing() {
    let dir = std::env::temp_dir().join(format!("mds-bg-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let (avi, bmp) = (dir.join("a.avi"), dir.join("a.bmp"));
    std::fs::write(&avi, b"RIFF").unwrap();
    std::fs::write(&bmp, b"BM").unwrap();
    let mut e = swing();
    e.modified = false;
    let before = e.doc.save().unwrap();
    for id in ["menu:213", "menu:232"] {
        assert_eq!(
            run(&mut e, None, id).unwrap_err(),
            "no window for the file dialog"
        );
    }
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: &mut e,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    let a = background::load_movie_path(&mut ctx, &avi).unwrap_err();
    let b = background::load_picture_path(&mut ctx, &bmp).unwrap_err();
    assert!(
        a.contains("viewport") && b.contains("viewport"),
        "{a} / {b}"
    );
    assert!(background::load_picture_path(&mut ctx, &dir.join("missing.bmp")).is_err());
    assert!(!e.modified);
    assert!(e.doc.save().unwrap() == before);
    std::fs::remove_dir_all(&dir).unwrap();
}

/// With a viewport the picture load marks the scene through the command when it places the file,
/// and by hand when the decoder refuses it (`command_file_menu.cpp:1888` sets `SceneModified`
/// after `LoadBackgroundPicture`, whatever it did); the refused file clears the path
/// (`media_load.cpp:331-361`).
#[test]
fn a_picture_load_marks_the_scene_whether_or_not_it_decodes() {
    let dir = std::env::temp_dir().join(format!("mds-bg-marks-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let bad = dir.join("bad.bmp");
    std::fs::write(&bad, b"BM").unwrap();
    let good = fixtures().join("script3/inputs/toonx.bmp");
    let mut e = swing();
    e.doc.edit.viewport = Some(mds_app::viewport::media_viewport([0, 0, 1280, 720]));
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: &mut e,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    ctx.editor.modified = false;
    background::load_picture_path(&mut ctx, &good).unwrap();
    assert!(ctx.editor.modified, "a placed picture");
    assert_eq!(ctx.editor.doc.pmm.picture.enabled, 1);
    assert!(ctx.editor.doc.pmm.picture.path.text.ends_with("toonx.bmp"));
    ctx.editor.modified = false;
    assert!(background::load_picture_path(&mut ctx, &bad).is_err());
    assert!(ctx.editor.modified, "a refused picture");
    assert_eq!(ctx.editor.doc.pmm.picture.path.text, "");
    std::fs::remove_dir_all(&dir).unwrap();
}
