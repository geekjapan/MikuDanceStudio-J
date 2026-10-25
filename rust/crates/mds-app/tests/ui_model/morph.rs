use super::common::*;
use mds_app::editor::Editor;
use mds_app::ui::morph_panel;
use mds_formats::pmx::Pmx;

fn pick(e: &mut Editor, lane: u8, name: &str) {
    let (n, _) = morph_panel::lane_morphs(&e.doc, lane)
        .into_iter()
        .find(|(_, t)| t == name)
        .unwrap();
    let mut status = String::new();
    morph_panel::pick(&mut ctx(e, &mut status), lane, n).unwrap();
}

fn slide(e: &mut Editor, lane: u8, pos: i32) {
    let mut status = String::new();
    morph_panel::slide(&mut ctx(e, &mut status), lane, pos).unwrap();
}

fn commit(e: &mut Editor, lane: u8, text: &str) {
    let mut status = String::new();
    morph_panel::commit(&mut ctx(e, &mut status), lane, text).unwrap();
}

/// `morphs.txt` up to its first save: the combos (504, 509, 514, 519), the weight edit and slider
/// (506, 505), and the four register buttons (525, 524, 527, 526 for lanes 0 to 3). The lanes with
/// no morph in `morph4.pmx` register -1, which only clears the key marks.
#[test]
fn morph_keys_register_like_the_script() {
    let mut e = editor();
    load_model(&mut e, "morph4.pmx");
    assert_eq!(
        morph_panel::lane_morphs(&e.doc, 1),
        vec![(0, "まばたき".to_string())]
    );
    assert_eq!(morph_panel::lane_morphs(&e.doc, 2).len(), 3);
    assert!(morph_panel::lane_morphs(&e.doc, 0).is_empty());
    pick(&mut e, 1, "まばたき");
    pick(&mut e, 2, "あ");
    frame(&mut e, 0);
    commit(&mut e, 1, "0.25");
    run(&mut e, "ctl:524").unwrap();
    frame(&mut e, 12);
    slide(&mut e, 1, 100);
    run(&mut e, "ctl:524").unwrap();
    commit(&mut e, 2, "0.5");
    run(&mut e, "ctl:527").unwrap();
    frame(&mut e, 24);
    slide(&mut e, 2, 0);
    run(&mut e, "ctl:527").unwrap();
    run(&mut e, "ctl:525").unwrap();
    run(&mut e, "ctl:526").unwrap();
    assert_saved(&e, "morphs", "registered.pmm");
}

/// The edit commits `atof` of its first 7 characters (`GetWindowTextA(edit, text, 8)`,
/// `ui_edit_commit.cpp:415`), unclamped; the slider is `pos / 100`, 0 to 100.
#[test]
fn the_weight_edit_and_slider_follow_the_cpp_parsing() {
    let mut e = editor();
    load_model(&mut e, "morph4.pmx");
    pick(&mut e, 2, "い");
    let weight = |e: &Editor| e.doc.selected_model().unwrap().morph_pose[2];
    for (text, want) in [
        ("0.75", 0.75),
        ("  1.5xyz", 1.5),
        ("-0.2500000", -0.25),
        ("0.12345678", 0.12345),
        ("abc", 0.0),
        ("", 0.0),
    ] {
        commit(&mut e, 2, text);
        assert_eq!(weight(&e), want as f32, "{text:?}");
    }
    slide(&mut e, 2, 37);
    assert_eq!(weight(&e), (37.0f64 / 100.0) as f32);
    slide(&mut e, 2, 500);
    assert_eq!(weight(&e), 1.0, "the slider range ends at 100");
    commit(&mut e, 0, "0.5");
    slide(&mut e, 0, 50);
    assert!(e.modified);
    assert_eq!(e.doc.selected_model().unwrap().morph_pose, vec![0.0, 0.0, 1.0, 0.0], "lane 0 has no morph selected");
}

/// A model whose morphs sit in the panels `panels`, loaded from a temporary folder.
fn model_with_panels(panels: [u8; 4]) -> (Editor, std::path::PathBuf) {
    let data = std::fs::read(fixtures().join("morph4.pmx")).unwrap();
    let mut pmx = Pmx::read(&data).unwrap();
    for (m, p) in pmx.morphs.iter_mut().zip(panels) {
        m.panel = p;
    }
    let dir = std::env::temp_dir().join(format!("mds-ui-model-{}-{}", std::process::id(), panels.iter().map(|p| p.to_string()).collect::<String>()));
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("steps.pmx"), pmx.write().unwrap()).unwrap();
    let mut e = editor_in(dir.clone());
    let mut status = String::new();
    mds_app::ui::model_panel::load(&mut ctx(&mut e, &mut status), "steps.pmx", pmx.write().unwrap()).unwrap();
    (e, dir)
}

fn selected(e: &Editor, lane: usize) -> i32 {
    e.doc.selected_model().unwrap().selection.selected_morphs[lane]
}

/// `MorphStep` (`command_frame_register.cpp:253`): one step with a wrap, skipping every morph whose
/// panel is not the eyebrow panel (in all four lanes, as the C++ tests it), and no change after a
/// full circle.
#[test]
fn previous_and_next_step_over_the_eyebrow_morphs() {
    // Morphs 0 and 3 are eyebrow (panel 1).
    let (mut e, dir) = model_with_panels([1, 2, 3, 1]);
    let mut status = String::new();
    morph_panel::pick(&mut ctx(&mut e, &mut status), 0, 0).unwrap();
    run(&mut e, "ctl:508").unwrap();
    assert_eq!(selected(&e, 0), 3, "next skips panels 2 and 3");
    run(&mut e, "ctl:508").unwrap();
    assert_eq!(selected(&e, 0), 0, "and wraps");
    run(&mut e, "ctl:507").unwrap();
    assert_eq!(selected(&e, 0), 3, "previous wraps the other way");
    run(&mut e, "ctl:507").unwrap();
    assert_eq!(selected(&e, 0), 0);

    let (lane2, lane3) = (selected(&e, 2), selected(&e, 3));
    morph_panel::pick(&mut ctx(&mut e, &mut status), 1, 1).unwrap();
    run(&mut e, "ctl:513").unwrap();
    assert_eq!(selected(&e, 1), 3, "lane 1 steps to an eyebrow morph too");
    run(&mut e, "ctl:512").unwrap();
    assert_eq!(selected(&e, 1), 0);
    assert_eq!((selected(&e, 2), selected(&e, 3)), (lane2, lane3), "other lanes keep their selection");
    std::fs::remove_dir_all(dir).unwrap();

    // Only morph 3 is eyebrow: the walk comes back to it and nothing changes.
    let (mut e, dir) = model_with_panels([2, 2, 3, 1]);
    morph_panel::pick(&mut ctx(&mut e, &mut status), 0, 3).unwrap();
    run(&mut e, "ctl:508").unwrap();
    run(&mut e, "ctl:507").unwrap();
    assert_eq!(selected(&e, 0), 3);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn morph_actions_refuse_while_playing_and_in_camera_mode() {
    let mut e = editor();
    assert_eq!(run(&mut e, "ctl:525"), Err("no model selected".into()));
    load_model(&mut e, "morph4.pmx");
    pick(&mut e, 1, "まばたき");
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:507", "ctl:508", "ctl:524", "ctl:525", "ctl:526", "ctl:527"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
    let mut status = String::new();
    assert!(!mds_app::actions::enabled(&ctx(&mut e, &mut status), "ctl:524"));
}
