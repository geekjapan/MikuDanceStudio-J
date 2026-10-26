//! The `file` area through the action table, with the dialogs answered as the C++ `--mds-script`
//! runner answers them ([`answer`]), on `motion.txt` and `bones.txt`: every PMM, VMD and VPD
//! save of the scripts runs through this area and equals the C++ output
//! (`tests/fixtures/rust/script/expected/`). The other lines run on `mds_doc::script::Runner`,
//! whose document is swapped into the editor for the lines of this area. The loads stay on the
//! runner, because it pumps the frame loop after each line as the C++ runner does, which a pose
//! load's saved pose depends on; each load also runs through this area on a copy of the
//! document, which must end as the document command it stands for leaves it.

use super::{fixtures, run, scratch, stage_golden2};
use mds_app::editor::Editor;
use mds_app::ui::file::{answer, drop_files, remembers};
use mds_app::ui::Ctx;
use mds_doc::script::Runner;
use mds_doc::Command;
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

fn read_input(path: &str, out: &Path) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [
        out.to_path_buf(),
        fixtures(),
        fixtures().join("script/inputs"),
    ]
    .iter()
    .find_map(|d| std::fs::read(d.join(name)).ok())
}

/// The document command a load line of this area stands for.
fn command(line: &str) -> Option<Command> {
    let w: Vec<_> = line.split_whitespace().collect();
    let data = |p: &str| std::fs::read(fixtures().join(p)).unwrap();
    Some(match w.as_slice() {
        ["load", "model", p] => Command::LoadModel {
            path: p.to_string(),
            data: data(p),
        },
        ["load", "vmd", p] => Command::LoadMotion(data(p)),
        ["load", "vpd", p] => Command::LoadPose(data(p)),
        _ => return None,
    })
}

/// A line of this area: the action and the dialog's answer, or a drop.
fn file_line(line: &str, out: &Path) -> Option<(&'static str, PathBuf)> {
    let w: Vec<_> = line.split_whitespace().collect();
    let input = |n: &str| fixtures().join(n);
    Some(match w.as_slice() {
        ["load", "model", p] => ("drop", PathBuf::from(p)),
        ["load", "vmd", p] => ("menu:209", input(p)),
        ["load", "vpd", p] => ("menu:202", input(p)),
        ["save", "pmm", n] => ("menu:208", out.join(n)),
        ["save", "vmd", n] => ("menu:210", out.join(n)),
        ["save", "vpd", n] => ("menu:203", out.join(n)),
        _ => return None,
    })
}

/// `(files equal, lines through this area)`.
fn replay(name: &str) -> (usize, usize) {
    let root = fixtures().join("script");
    let expected = root.join("expected").join(name);
    let script = std::fs::read_to_string(root.join(format!("{name}.txt"))).unwrap();
    let out = scratch(&format!("script-{name}"));
    let mut runner = Runner::new();
    // The scene's folder is the fixtures, where the C++ runner staged the inputs.
    let mut editor =
        Editor::new(mds_doc::Document::startup(), Some(fixtures().join("x.pmm"))).unwrap();
    let (mut equal, mut through) = (0, 0);
    for (n, line) in script.lines().enumerate() {
        let at = || format!("{name}.txt line {} ({line})", n + 1);
        let Some((id, path)) = file_line(line, &out) else {
            for s in runner.run_line(line, &mut |p| read_input(p, &out)).unwrap() {
                if !s.name.ends_with(".emm") {
                    std::fs::write(out.join(&s.name), s.bytes).unwrap();
                }
            }
            continue;
        };
        let load = command(line);
        let before = runner.doc.clone();
        std::mem::swap(&mut editor.doc, &mut runner.doc);
        let mut status = String::new();
        let mut c = ctx(&mut editor, &mut status);
        let r = if id == "drop" {
            drop_files(&mut c, std::slice::from_ref(&path));
            match status.is_empty() {
                true => Ok(()),
                false => Err(status.clone()),
            }
        } else {
            answer(Some(path.clone()));
            mds_app::actions::run(&mut c, id)
        };
        std::mem::swap(&mut editor.doc, &mut runner.doc);
        r.unwrap_or_else(|e| panic!("{}: {e}", at()));
        through += 1;
        if let Some(cmd) = load {
            let mut want = before.clone();
            want.apply(cmd).unwrap();
            assert!(
                runner.doc.save().unwrap() == want.save().unwrap(),
                "{}: not the document command",
                at()
            );
            runner.doc = before;
            runner.run_line(line, &mut |p| read_input(p, &out)).unwrap();
        }
        if line.starts_with("save") {
            let got = std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", at()));
            let want = std::fs::read(expected.join(path.file_name().unwrap())).unwrap();
            assert!(got == want, "{}: differs from the C++ output", at());
            equal += 1;
        }
    }
    std::fs::remove_dir_all(&out).unwrap();
    (equal, through)
}

#[test]
fn motion_script_through_the_file_area() {
    assert_eq!(replay("motion"), (4, 8));
}

#[test]
fn bones_script_saves_through_the_file_area() {
    assert_eq!(replay("bones"), (11, 13));
}

/// Load pose (202) and save pose (203) are model mode only; save pose with no selected bone and
/// save motion with no marked key show a box and write nothing (`CmdSavePose`, `CmdSaveMotion`).
#[test]
fn pose_and_motion_gates() {
    let out = scratch("gates");
    let mut e = Editor::new(mds_doc::Document::startup(), Some(fixtures().join("x.pmm"))).unwrap();
    let mut status = String::new();
    assert!(run(&mut e, "menu:202")
        .unwrap_err()
        .ends_with("model mode only"));
    e.load_model(Path::new("chain8.pmx")).unwrap();
    e.apply(Command::SelectBones(Vec::new())).unwrap();
    answer(Some(out.join("a.vpd")));
    let mut c = ctx(&mut e, &mut status);
    mds_app::actions::run(&mut c, "menu:203").unwrap();
    assert!(status.starts_with("ポーズデータ保存"), "{status}");
    let mut c = ctx(&mut e, &mut status);
    mds_app::actions::run(&mut c, "menu:210").unwrap();
    assert!(status.starts_with("モーションデータ保存"), "{status}");
    assert!(!out.join("a.vpd").exists());
    // The answer queued for 203 is still there: no dialog opened.
    answer(None);
    std::fs::remove_dir_all(&out).unwrap();
}

/// A pose load leaves the scene unmodified (`CmdLoadPose`); a motion or wave load sets it.
#[test]
fn which_loads_modify_the_scene() {
    let mut e = Editor::new(mds_doc::Document::startup(), Some(fixtures().join("x.pmm"))).unwrap();
    e.load_model(Path::new("chain8.pmx")).unwrap();
    e.modified = false;
    answer(Some(fixtures().join("pose.vpd")));
    run(&mut e, "menu:202").unwrap();
    assert!(!e.modified);
    answer(Some(fixtures().join("script/inputs/tone.wav")));
    run(&mut e, "menu:206").unwrap();
    assert!(e.modified && e.doc.pmm.wave.enabled != 0);
    e.modified = false;
    answer(Some(fixtures().join("swing600.vmd")));
    run(&mut e, "menu:209").unwrap();
    assert!(e.modified);
}

/// `HandleDropFiles` dispatches by extension: a model, an accessory, a `.vpd` in camera mode (a
/// box, nothing loaded) and a PMM.
#[test]
fn dropped_files_load_by_extension() {
    let dir = scratch("drops");
    stage_golden2(&dir);
    let mut e = Editor::empty();
    let mut status = String::new();
    let mut c = ctx(&mut e, &mut status);
    drop_files(&mut c, &[dir.join("chain8.pmx"), dir.join("cube.x")]);
    assert!(status.is_empty(), "{status}");
    assert_eq!(e.doc.pmm.models.len(), 1);
    let a = &e.doc.pmm.accessories;
    assert_eq!(a.len(), 1);
    assert_eq!(a[0].name.text, "cube.x");
    e.with_frame([64, 64], &[[0.0, 0.0]], |_| ()).unwrap();
    e.apply(Command::SelectCameraMode).unwrap();
    let mut c = ctx(&mut e, &mut status);
    drop_files(&mut c, &[fixtures().join("pose.vpd")]);
    assert!(status.starts_with("ポーズ読込"), "{status}");
    status.clear();
    let mut c = ctx(&mut e, &mut status);
    drop_files(&mut c, &[dir.join("accessory.pmm")]);
    assert_eq!(
        e.doc.pmm.accessories.len(),
        2,
        "the dropped scene replaced it"
    );
    assert_eq!(e.path.as_deref(), Some(dir.join("accessory.pmm").as_path()));
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A dropped `.vac` (`ui_dropfiles.cpp:211`) is `LoadAccessoryFile` of it with the mesh beside it,
/// as the script runner's `load accessory` of the same path (`script3/vac.txt`) does it.
#[test]
fn a_dropped_vac_loads_the_mesh_beside_it() {
    let dir = scratch("drop-vac");
    let inputs = fixtures().join("script3/inputs");
    for name in ["tri2.vac", "tri2.x"] {
        std::fs::copy(inputs.join(name), dir.join(name)).unwrap();
    }
    let vac = dir.join("tri2.vac");
    let mut e = Editor::empty();
    let mut status = String::new();
    drop_files(&mut ctx(&mut e, &mut status), std::slice::from_ref(&vac));
    assert!(status.is_empty(), "{status}");
    assert!(e.modified, "render/accessory.cpp:615");

    let stored = vac.to_string_lossy().replace('/', "\\");
    let mut runner = Runner::new();
    runner
        .run_line(&format!("load accessory {stored}"), &mut |p: &str| {
            let name = p.rsplit('\\').next().unwrap();
            std::fs::read(dir.join(name)).ok()
        })
        .unwrap();
    assert!(e.doc.save().unwrap() == runner.doc.save().unwrap());
    std::fs::remove_dir_all(&dir).unwrap();
}

/// The other drops of `HandleDropFiles`: `.bmp` and `.jpg` load the background picture and `.avi`
/// the movie, each setting `SceneModified` whatever the loader did (`ui_dropfiles.cpp:220` to
/// `:289`); `.oni` is the MoCap load, which says why it cannot run (`:265`). The MMEffect files
/// go to the effects: an `.emm` loads and an `.fx` is the selected model's effect.
#[test]
fn the_media_and_effect_drops_reach_their_loads() {
    let dir = scratch("drop-media");
    stage_golden2(&dir);
    std::fs::write(dir.join("bad.avi"), b"RIFF").unwrap();
    std::fs::write(dir.join("bad.jpg"), b"not a jpeg").unwrap();
    let mut e = Editor::open(&dir.join("accessory.pmm")).unwrap();
    e.doc.edit.viewport = Some(mds_app::viewport::media_viewport([0, 0, 640, 480]));
    let mut status = String::new();

    e.modified = false;
    drop_files(&mut ctx(&mut e, &mut status), &[dir.join("cube.bmp")]);
    assert!(status.is_empty(), "{status}");
    assert!(e.doc.pmm.picture.path.text.ends_with("cube.bmp"));
    assert!(e.modified);
    for bad in ["bad.avi", "bad.jpg"] {
        e.modified = false;
        status.clear();
        drop_files(&mut ctx(&mut e, &mut status), &[dir.join(bad)]);
        assert!(
            !status.contains("file type is not supported"),
            "{bad}: {status}"
        );
        assert!(e.modified, "{bad}");
    }

    // The scene is in camera mode: the box of `ui_dropfiles.cpp:271`.
    status.clear();
    drop_files(&mut ctx(&mut e, &mut status), &[dir.join("x.oni")]);
    assert_eq!(status, "カメラ・照明モードではoniデータは読めません");
    e.apply(Command::SelectModel(e.doc.pmm.models[0].slot))
        .unwrap();
    status.clear();
    drop_files(&mut ctx(&mut e, &mut status), &[dir.join("x.oni")]);
    assert_eq!(status, mds_app::ui::mocap::UNAVAILABLE);

    let fx = fixtures().join("mmegold/control.fx");
    status.clear();
    drop_files(&mut ctx(&mut e, &mut status), std::slice::from_ref(&fx));
    assert!(status.is_empty(), "{status}");
    assert_eq!(e.mme.assignments[0].effect, fx.to_string_lossy());
    status.clear();
    drop_files(
        &mut ctx(&mut e, &mut status),
        &[fixtures().join("mmegold/objects.emm")],
    );
    assert!(status.is_empty(), "{status}");
    std::fs::remove_dir_all(&dir).unwrap();
}

/// Menu 301 toggles; with it on, each dialog kind starts in the folder last used.
#[test]
fn previous_folder_toggles() {
    let mut e = Editor::empty();
    assert!(!remembers());
    run(&mut e, "menu:301").unwrap();
    assert!(remembers());
    run(&mut e, "menu:301").unwrap();
    assert!(!remembers());
}

/// Menu 276 writes the frame at the render size.
#[test]
fn render_to_picture_writes_the_frame() {
    if mds_render::Gpu::new().expect("device").is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    }
    let out = scratch("picture");
    let mut e = Editor::open(&fixtures().join("swing600-nophys.pmm")).unwrap();
    answer(Some(out.join("frame")));
    run(&mut e, "menu:276").unwrap();
    let data = std::fs::read(out.join("frame.png")).unwrap();
    let info = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap()
        .info()
        .clone();
    let s = &e.doc.pmm.settings;
    assert_eq!(
        (info.width as i32, info.height as i32),
        (s.render_width, s.render_height)
    );
    std::fs::remove_dir_all(&out).unwrap();
}
