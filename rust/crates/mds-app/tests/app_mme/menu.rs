//! The `mme` and `mme-dialog` areas through the action table, without a window, on the staged
//! `control` scene of mmegold (two models, `control.fx` on the first) and on the `accessory`
//! script of `tests/fixtures/rust/script` for the auto-saved EMM.

use super::{fixtures, stage, vkd3d_lib};
use mds_app::editor::Editor;
use mds_app::mme::{emm_path, View};
use mds_app::ui::mme::{answer, dialog, dirty, open_windows, select, select_tab, Row};
use mds_app::ui::Ctx;
use mds_doc::script::Runner;
use std::path::{Path, PathBuf};

fn ctx<'a>(editor: &'a mut Editor, status: &'a mut String) -> Ctx<'a> {
    Ctx {
        editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status,
    }
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-app-mme-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// The `control` scene of mmegold, staged and opened as `mds-app <pmm>` opens it.
fn control(name: &str) -> (Editor, PathBuf) {
    let dir = scratch(name);
    stage("control", &dir, Path::new(""));
    (Editor::open(&dir.join("control.pmm")).unwrap(), dir)
}

fn run(editor: &mut Editor, id: &str) {
    let mut status = String::new();
    let mut c = ctx(editor, &mut status);
    c.run(id);
    assert!(status.is_empty(), "{id}: {status}");
}

#[test]
fn the_emm_beside_the_pmm_assigns_the_effects() {
    let (editor, dir) = control("autoload");
    let mme = &editor.mme;
    // `MmeAutoLoadEmmForPmm` (emm_manager.cpp:1777): the `Pmd0` row; `morph4.pmx` has none.
    assert_eq!(mme.assignments.len(), 2);
    assert_eq!(
        Path::new(&mme.assignments[0].effect),
        dir.join("mmegold/control.fx")
    );
    assert_eq!(mme.assignments[1].effect, "");
    assert_eq!(mme.default, "");
    assert!(mme.active());
    // A scene without an EMM and without effect files beside its objects has none.
    assert!(!Editor::empty().mme.active());
}

#[test]
fn the_menu_switches_flip() {
    let (mut editor, _) = control("switches");
    let s = editor.mme.switches;
    // effectEnabled(1) (mme_context.cpp:124), g_autoReload = 1 (mme_globals.cpp:59),
    // g_emmAutoSave = 1 (callbacks.cpp:445).
    assert!(s.enabled && s.auto_reload && s.auto_save);
    // 40006 and its Ctrl+Shift+E hook (mme_ui.cpp:236, :367) flip the one flag.
    run(&mut editor, "menu:mme-40006");
    assert!(!editor.mme.switches.enabled && !editor.mme.active());
    run(&mut editor, "key:Ctrl+Shift+E");
    assert!(editor.mme.switches.enabled && editor.mme.active());
    // 40001 (mme_ui.cpp:331) and 40022 (:383).
    run(&mut editor, "menu:mme-40001");
    run(&mut editor, "menu:mme-40022");
    let s = editor.mme.switches;
    assert!(!s.auto_reload && !s.auto_save && s.enabled);
    // The effects stay assigned with the effects off.
    assert!(!editor.mme.assignments[0].effect.is_empty());
}

#[test]
fn the_log_and_about_windows_open() {
    let (mut editor, _) = control("windows");
    assert_eq!(open_windows(), [false; 3]);
    run(&mut editor, "menu:mme-40002");
    run(&mut editor, "menu:mme-40003");
    run(&mut editor, "menu:mme-40005");
    assert_eq!(open_windows(), [true; 3]);
    assert_eq!(
        mds_app::ui::mme::ABOUT,
        "MikuMikuEffect ver0.37 in MikuMikuDance\n(by 舞力介入Ｐ)"
    );
}

/// `EmmFile::Save` with the C++ checkout's folder in place of `dir`, `\` as `/`.
fn normalized(bytes: &[u8], prefix: &str) -> String {
    String::from_utf8(bytes.to_vec())
        .unwrap()
        .replace('\\', "/")
        .replace(prefix, "<dir>/")
}

#[test]
fn saving_writes_the_emm_the_cpp_writes() {
    // `accessory.txt` through the script runner, then saved through the editor: the PMM bytes
    // and, with Auto Save on, the `.emm` beside it (`MmeAutoSaveEmmForPmm`, emm_manager.cpp:1751)
    // equal `expected/accessory/`. The C++ wrote the paths it resolved in its build folder.
    let script = fixtures().join("script");
    let dir = scratch("autosave");
    for (from, name) in [
        (fixtures(), "chain8.pmx"),
        (script.join("inputs"), "tri.x"),
        (script.join("inputs"), "tone.wav"),
    ] {
        std::fs::copy(from.join(name), dir.join(name)).unwrap();
    }
    let mut runner = Runner::new();
    let text = std::fs::read_to_string(script.join("accessory.txt")).unwrap();
    let read = &mut |p: &str| std::fs::read(dir.join(p.trim_start_matches(".\\"))).ok();
    for line in text.lines() {
        runner.run_line(line, read).unwrap();
    }
    let mut editor = Editor::new(runner.doc, Some(dir.join("x.pmm"))).unwrap();
    let pmm = dir.join("accessory.pmm");
    editor.save_as(&pmm).unwrap();
    let expected = script.join("expected/accessory");
    assert_eq!(
        std::fs::read(&pmm).unwrap(),
        std::fs::read(expected.join("accessory.pmm")).unwrap()
    );
    let cpp = std::fs::read(expected.join("accessory.emm")).unwrap();
    let rust = std::fs::read(emm_path(&pmm)).unwrap();
    let ours = format!("{}/", dir.to_string_lossy());
    assert_eq!(
        normalized(&rust, &ours),
        normalized(&cpp, "C:/mds/w2-script/repo/out/ci/build/Release/")
    );
    // Auto Save off: no EMM.
    run(&mut editor, "menu:mme-40022");
    let other = dir.join("other.pmm");
    editor.save_as(&other).unwrap();
    assert!(other.is_file() && !emm_path(&other).exists());
}

#[test]
fn the_mapping_dialog_edits_the_assignment() {
    let (mut editor, dir) = control("dialog");
    let fx = dir.join("mmegold/anime.fx");
    let fx_text = fx.to_string_lossy().into_owned();
    run(&mut editor, "menu:mme-40005");
    assert!(!dirty());

    // Set Effect (1007, `DlgWriteEffectForSelection`, mme_dlg.cpp:1228) on morph4.pmx.
    select(&[Row::Object(1)]);
    answer(Some(fx.clone()));
    run(&mut editor, "ctl:mme-dialog-1007");
    assert_eq!(editor.mme.assignments[1].effect, fx_text);
    assert!(dirty());
    // Apply (1005, mme_dlg.cpp:1995) greys out until the next edit.
    run(&mut editor, "ctl:mme-dialog-1005");
    assert!(!dirty());
    // Hide/Show (1011, `DlgToggleHideShowFlow`): one shown row hides them all, then shows.
    select(&[Row::Object(0), Row::Object(1)]);
    run(&mut editor, "menu:mme-dialog-40013");
    assert!(editor.mme.assignments.iter().all(|a| !a.shown));
    run(&mut editor, "ctl:mme-dialog-1011");
    assert!(editor.mme.assignments.iter().all(|a| a.shown));
    // Remove (1008 and 40012): unassigned.
    select(&[Row::Object(1)]);
    run(&mut editor, "ctl:mme-dialog-1008");
    assert_eq!(editor.mme.assignments[1].effect, "");

    // Subset-Extract (40006) expands chain8.pmx into one row per material; a subset row takes
    // its own effect.
    select(&[Row::Object(0)]);
    run(&mut editor, "menu:mme-dialog-40006");
    let materials = match &editor.doc.models[0] {
        mds_doc::ModelFile::Pmx(p) => p.materials.len() as i32,
        _ => unreachable!(),
    };
    let mut status = String::new();
    let rows = dialog::rows(&ctx(&mut editor, &mut status));
    assert_eq!(rows.len(), 3 + materials as usize);
    assert_eq!(rows[2], Row::Subset(0, 0));
    select(&[Row::Subset(0, 0)]);
    answer(Some(fx.clone()));
    run(&mut editor, "menu:mme-dialog-40007");
    assert_eq!(editor.mme.assignments[0].subsets[&0], fx_text);

    // Save (40010) and Open (40009) the mapping: the EMM round trips the assignment.
    let saved = dir.join("saved.emm");
    answer(Some(saved.clone()));
    run(&mut editor, "menu:mme-dialog-40010");
    let before = editor.mme.assignments.clone();
    // Reset with default (40008, mme_dlg.cpp:1378): the subset rows go, and with no file beside
    // the model and no default the effect too.
    select(&[Row::Object(0)]);
    run(&mut editor, "menu:mme-dialog-40008");
    assert_eq!(editor.mme.assignments[0].effect, "");
    assert!(editor.mme.assignments[0].subsets.is_empty());
    answer(Some(saved.clone()));
    run(&mut editor, "menu:mme-dialog-40009");
    assert_eq!(editor.mme.assignments, before);

    // Save by Model (40017) needs exactly one whole object; Open by Model (40016) puts its rows
    // on every selected one.
    let emd = dir.join("chain8.emd");
    select(&[Row::Object(0), Row::Object(1)]);
    answer(Some(emd.clone()));
    run(&mut editor, "menu:mme-dialog-40017");
    assert!(!emd.exists());
    select(&[Row::Object(0)]);
    run(&mut editor, "menu:mme-dialog-40017");
    assert!(emd.is_file());
    select(&[Row::Object(1)]);
    answer(Some(emd.clone()));
    run(&mut editor, "menu:mme-dialog-40016");
    assert_eq!(
        editor.mme.assignments[1].effect,
        editor.mme.assignments[0].effect
    );

    // The (default) row sets the EMM default; Cancel (2) restores the default of the last Apply
    // and closes (mme_dlg.cpp:1976).
    select(&[Row::Default]);
    answer(Some(fx.clone()));
    run(&mut editor, "ctl:mme-dialog-1007");
    assert_eq!(editor.mme.default, fx_text);
    run(&mut editor, "ctl:mme-dialog-2");
    assert_eq!(editor.mme.default, "");
    assert!(!open_windows()[2]);
    // OK (1) and Close (40011) close as they are.
    run(&mut editor, "menu:mme-40005");
    run(&mut editor, "ctl:mme-dialog-1");
    assert!(!open_windows()[2]);

    // A dropped file (`WM_DROPFILES`): one .fx goes to the selection, one .emm loads, two are
    // refused.
    let mut status = String::new();
    let mut c = ctx(&mut editor, &mut status);
    select(&[Row::Object(1)]);
    dialog::drop_files(&mut c, std::slice::from_ref(&fx)).unwrap();
    assert_eq!(c.editor.mme.assignments[1].effect, fx_text);
    dialog::drop_files(&mut c, &[dir.join("control.emm")]).unwrap();
    assert_eq!(c.editor.mme.assignments[1].effect, fx_text);
    assert!(c.editor.mme.assignments[0].effect.ends_with("control.fx"));
    assert!(dialog::drop_files(&mut c, &[fx.clone(), fx]).is_err());
}

#[test]
fn a_runtime_that_cannot_start_leaves_the_scene_without_effects() {
    let (editor, dir) = control("nostart");
    let camera = *editor.camera_frame();
    let mut mme = editor.mme;
    mme.vkd3d = Some(dir.join("no-such-vkd3d.dylib"));
    assert!(mme.active());
    let view = View {
        camera: &camera,
        view_offset: [0.0; 2],
        shadow_map: Default::default(),
        shadow_map_display: false,
        light: [0.6, 0.6, 0.6, -0.5, -1.0, 0.5],
        frame: 0,
        elapsed: 0.0,
        size: [64, 36],
    };
    assert!(mme.render(&editor.doc, &editor.physics, &view).is_err());
    assert!(!mme.active(), "one failed start, not one per frame");
    // Reload All tries again.
    mme.unload();
    assert!(mme.active());
}

#[test]
fn reload_all_loads_the_effects_again() {
    if mds_render::Gpu::new().expect("device").is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    }
    let lib = vkd3d_lib();
    if let Err(e) = mds_shader::vkd3d::Vkd3d::open(&lib) {
        eprintln!("SKIP: vkd3d-shader not loaded: {e} (not a pass)");
        return;
    }
    let (mut editor, _) = control("reload");
    editor.mme.vkd3d = Some(lib);
    let draw = |e: &Editor| {
        let view: View = e.view(0, [64, 36], 0.0).unwrap();
        e.mme.render(&e.doc, &e.physics, &view).unwrap()
    };
    let px = draw(&editor);
    assert_eq!(px.len(), 64 * 36 * 4);
    assert_eq!(editor.mme.loaded(), 1);
    // 40004 (`MmeUiReloadAllEffects`, mme_ui.cpp:614): unloaded, compiled again at the next frame.
    run(&mut editor, "menu:mme-40004");
    assert_eq!(editor.mme.loaded(), 0);
    assert_eq!(draw(&editor), px);
    assert_eq!(editor.mme.loaded(), 1);
}

#[test]
fn disassemble_lists_the_selected_rows_effect() {
    let lib = vkd3d_lib();
    if let Err(e) = mds_shader::vkd3d::Vkd3d::open(&lib) {
        eprintln!("SKIP: vkd3d-shader not loaded: {e} (not a pass)");
        return;
    }
    let (mut editor, _) = control("disassemble");
    editor.mme.vkd3d = Some(lib);
    run(&mut editor, "menu:mme-40005");
    // `DlgSelectedEffectPath` (mme_dlg.cpp:652): the (default) row and an object without an
    // effect have none, and the window opens empty (`DlgDisassembleFlow`, :1459).
    for row in [Row::Default, Row::Object(1)] {
        select(&[row]);
        run(&mut editor, "menu:mme-dialog-40014");
        assert_eq!(dialog::disassembly().as_deref(), Some(""));
    }
    // chain8.pmx with control.fx: every pass in shader assembly, CRLF line ends (:1406).
    select(&[Row::Object(0)]);
    run(&mut editor, "menu:mme-dialog-40014");
    let text = dialog::disassembly().unwrap();
    assert!(text.starts_with("technique "), "{text}");
    assert!(text.contains("\r\n  pass ") && text.contains(" = compile vs_"));
    assert!(text
        .lines()
        .any(|l| l.trim() == "ps_3_0" || l.trim() == "ps_2_0"));
    assert_eq!(text.matches('\n').count(), text.matches("\r\n").count());
    assert!(
        text.ends_with("\r\n") && !text.contains("// error"),
        "{text}"
    );
}

/// The offscreen tab (1002, `mme_dlg.cpp:1746`) on the mmegold `offscreen` scene: `chain8.pmx`
/// with `offscreen.fx`, whose `MirrorRT` rows are `self=hide; *=none;`. The tab's edits are the
/// target's overrides (`DlgUpsertOffscreenRow` :357, `DlgApplyShown` :741,
/// `DlgRemoveOffscreenRows` :363), its texts those of `DlgOffscreenRowText` (:383) and
/// `DlgOffscreenDefaultRowText` (:393), and the turn draws as they say.
#[test]
fn the_offscreen_tab_edits_the_targets_overrides() {
    if mds_render::Gpu::new().expect("device").is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    }
    let lib = vkd3d_lib();
    if let Err(e) = mds_shader::vkd3d::Vkd3d::open(&lib) {
        eprintln!("SKIP: vkd3d-shader not loaded: {e} (not a pass)");
        return;
    }
    let dir = scratch("offscreen-tab");
    stage("offscreen", &dir, Path::new(""));
    let mut editor = Editor::open(&dir.join("offscreen.pmm")).unwrap();
    editor.mme.vkd3d = Some(lib);
    let draw = |e: &Editor| {
        let view: View = e.view(0, [64, 36], 0.0).unwrap();
        e.mme.render(&e.doc, &e.physics, &view).unwrap();
    };
    run(&mut editor, "menu:mme-40005");
    draw(&editor);
    assert_eq!(editor.mme.loaded(), 1);
    let targets = editor.mme.offscreen_targets();
    assert_eq!(targets.len(), 1);
    let t = &targets[0];
    assert_eq!(
        (t.name.as_str(), t.description.as_str(), t.owner),
        ("MirrorRT", "Mirror", 0)
    );
    let key = (t.file.clone(), t.name.clone());
    let mut status = String::new();
    let text = |editor: &mut Editor, row: Row| {
        let mut status = String::new();
        dialog::row_text(&ctx(editor, &mut status), row)
    };
    let main_effect = text(&mut editor, Row::Object(0)).1;
    assert!(main_effect.ends_with("offscreen.fx"), "{main_effect}");

    select_tab(Some(key.clone()));
    assert!(dialog::current_tab(&ctx(&mut editor, &mut status)).is_some());
    assert_eq!(
        text(&mut editor, Row::Default),
        ("(default)".into(), "self=hide; *=none; ".into())
    );
    // The owner is `self`: hidden.
    assert_eq!(
        text(&mut editor, Row::Object(0)),
        ("chain8.pmx (hide)".into(), "(hide)".into())
    );
    // The (default) row is not collected on a target tab: no effect to disassemble, none set.
    select(&[Row::Default]);
    run(&mut editor, "menu:mme-dialog-40014");
    assert_eq!(dialog::disassembly().as_deref(), Some(""));
    run(&mut editor, "menu:mme-dialog-40007");
    assert!(editor.mme.offscreen.is_empty());
    // Shown: the `hide` row is no effect, the host's draw.
    select(&[Row::Object(0)]);
    run(&mut editor, "ctl:mme-dialog-1011");
    assert_eq!(
        text(&mut editor, Row::Object(0)),
        ("chain8.pmx".into(), "(none)".into())
    );
    // An effect for the target: the turn loads it.
    let fx = dir.join("mmegold/control.fx");
    answer(Some(fx.clone()));
    run(&mut editor, "menu:mme-dialog-40007");
    let fx_text = fx.to_string_lossy().into_owned();
    assert_eq!(text(&mut editor, Row::Object(0)).1, fx_text);
    assert_eq!(
        dialog::selected_effect(&ctx(&mut editor, &mut status)),
        fx_text
    );
    select_tab(None);
    assert_eq!(
        text(&mut editor, Row::Object(0)).1,
        main_effect,
        "Main is unchanged"
    );
    draw(&editor);
    assert_eq!(
        editor.mme.loaded(),
        2,
        "the turn draws chain8.pmx with control.fx"
    );
    select_tab(Some(key.clone()));
    // Remove writes `none`; Reset drops every override of the object.
    run(&mut editor, "menu:mme-dialog-40012");
    assert_eq!(text(&mut editor, Row::Object(0)).1, "(none)");
    run(&mut editor, "menu:mme-dialog-40008");
    assert_eq!(text(&mut editor, Row::Object(0)).1, "(hide)");
    assert!(editor.mme.offscreen[&key].is_empty());
    // Reload All loads the effects, and their targets, anew.
    run(&mut editor, "ctl:mme-dialog-1011");
    run(&mut editor, "menu:mme-40004");
    assert!(editor.mme.offscreen.is_empty());
    select_tab(None);
}

#[test]
fn resetting_keeps_the_mixed_case_adjacent_effect_loaded_at_open() {
    let (mut editor, dir) = control("mixed-case-reset");
    let materials = dir.join("Materials");
    std::fs::create_dir_all(&materials).unwrap();
    let model = materials.join("material_2.0.pmx");
    std::fs::copy(fixtures().join("chain8.pmx"), &model).unwrap();
    let effect = materials.join("Material_2.0.fx");
    std::fs::write(&effect, b"effect").unwrap();
    editor.doc.pmm.models[0].path.text = model.to_string_lossy().into_owned();
    editor.mme = mds_app::mme::Mme::autoload(&editor.doc, None);
    assert!(editor.mme.default.is_empty());
    let loaded = editor.mme.assignments[0].effect.clone();
    assert!(!loaded.is_empty());
    assert_eq!(mds_app::mme::effect_file(&dir, &loaded), effect);

    run(&mut editor, "menu:mme-40005");
    select(&[Row::Object(0)]);
    run(&mut editor, "menu:mme-dialog-40008");
    assert_eq!(editor.mme.assignments[0].effect, loaded);
    std::fs::remove_dir_all(dir).unwrap();
}
