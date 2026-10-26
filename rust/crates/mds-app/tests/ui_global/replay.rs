//! `tests/fixtures/rust/script/camera.txt` up to the first save, through the panels' actions and
//! commit helpers, against the C++ output `expected/camera/registered.pmm`.

use crate::support::{camera_mode, fixtures, run, saved, with_ctx};
use mds_app::editor::Editor;
use mds_app::ui::camera_panel::{commit_fov, commit_readout};
use mds_app::ui::light_panel::{color_edit, direction_edit};
use mds_app::ui::shadow_panel::commit_range;
use mds_doc::{Command, Document, GlobalTrack};

#[test]
fn camera_txt_saves_the_bytes_of_the_cpp_application() {
    let mut e = camera_mode();
    e.seek(30).unwrap();
    // camera position / rotation / distance / fov: edits 544 to 550 and 448.
    for (field, text) in [
        (0, "1"),
        (1, "2"),
        (2, "3"),
        (3, "10"),
        (4, "-20"),
        (5, "5"),
        (6, "25"),
    ] {
        with_ctx(&mut e, |c| commit_readout(c, field, text))
            .0
            .unwrap();
    }
    with_ctx(&mut e, |c| commit_fov(c, "40")).0.unwrap();
    run(&mut e, "ctl:452").unwrap();

    e.seek(45).unwrap();
    for (ch, text) in ["200", "100", "50"].into_iter().enumerate() {
        with_ctx(&mut e, |c| color_edit(c, ch, text)).0.unwrap();
    }
    for (axis, text) in ["0.5", "-1", "0.25"].into_iter().enumerate() {
        with_ctx(&mut e, |c| direction_edit(c, axis, text))
            .0
            .unwrap();
    }
    run(&mut e, "ctl:468").unwrap();

    e.seek(50).unwrap();
    run(&mut e, "ctl:564").unwrap();
    with_ctx(&mut e, |c| commit_range(c, "8000")).0.unwrap();
    run(&mut e, "ctl:565").unwrap();

    // The gravity dialog is not a panel of these areas: the same commands the script runner sends.
    e.seek(60).unwrap();
    e.apply(Command::SetGravityChannel(0, 5.0)).unwrap();
    for (i, v) in [1.0, -1.0, 0.0].into_iter().enumerate() {
        e.apply(Command::SetGravityChannel(1 + i as u8, v)).unwrap();
    }
    e.apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Gravity]))
        .unwrap();
    e.apply(Command::CloseGravityDialog).unwrap();

    let want = std::fs::read(fixtures().join("script/expected/camera/registered.pmm")).unwrap();
    let got = saved(&e);
    let first = got.iter().zip(&want).position(|(a, b)| a != b);
    assert!(
        got == want,
        "registered.pmm differs: {} bytes against {}, first difference at {first:?}",
        got.len(),
        want.len()
    );
    eprintln!(
        "registered.pmm: {} bytes, identical to the C++ output",
        got.len()
    );
}

#[test]
fn the_rows_without_an_action_are_the_listed_ones() {
    let text =
        std::fs::read_to_string(fixtures().join("../../../tools/ui_inventory/inventory.tsv"))
            .unwrap();
    let mut rows = 0;
    let mut missing = Vec::new();
    for line in text.lines().skip(1) {
        let f: Vec<_> = line.split('\t').collect();
        if !["camera-panel", "light-panel", "shadow-panel"].contains(&f[5]) {
            continue;
        }
        rows += 1;
        if mds_app::actions::find(f[0]).is_none() {
            missing.push(f[0].to_string());
        }
    }
    assert_eq!(rows, 51);
    assert_eq!(missing, Vec::<String>::new());
}

fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    ["script/inputs", "script2/inputs", "script3/inputs", ""]
        .iter()
        .find_map(|d| std::fs::read(fixtures().join(d).join(name)).ok())
}

/// `script3/camref.txt`: the two check boxes 412 and 531, pressed the way the script's
/// `camera reference N` lines set the mode, in model mode and in camera mode; every PMM it saves
/// equals the C++ output.
#[test]
fn camref_txt_saves_the_bytes_of_the_cpp_application() {
    use mds_doc::script::Runner;
    let root = fixtures().join("script3");
    let script = std::fs::read_to_string(root.join("camref.txt")).unwrap();
    let mut runner = Runner::new();
    let mut e = Editor::new(Document::startup(), None).unwrap();
    let mut files = 0;
    for (n, line) in script.lines().enumerate() {
        let at = format!("camref.txt line {} ({line})", n + 1);
        let w: Vec<&str> = line.split_whitespace().collect();
        let saved = if let ["camera", "reference", m] = w.as_slice() {
            let want: u8 = m.parse().unwrap();
            std::mem::swap(&mut e.doc, &mut runner.doc);
            let now = e.doc.pmm.timeline.camera_reference_mode;
            // Checking a box sets its mode; unchecking the checked box sets 0.
            let press = match (want, now) {
                (w, n) if w == n => None,
                (0, 1) | (1, _) => Some("ctl:412"),
                _ => Some("ctl:531"),
            };
            let r = press.map_or(Ok(()), |id| run(&mut e, id));
            let modified = e.modified;
            std::mem::swap(&mut e.doc, &mut runner.doc);
            r.unwrap_or_else(|x| panic!("{at}: {x}"));
            assert!(!modified, "{at}: the boxes do not set SceneModified");
            runner.pump(&mut |p| read_input(p)).unwrap();
            Vec::new()
        } else {
            runner
                .run_line(line, &mut |p| read_input(p))
                .unwrap_or_else(|x| panic!("{at}: {x}"))
        };
        for s in saved.into_iter().filter(|s| !s.name.ends_with(".emm")) {
            let want = std::fs::read(root.join("expected/camref").join(&s.name)).unwrap();
            assert!(
                s.bytes == want,
                "{at} {}: differs from the C++ output",
                s.name
            );
            files += 1;
        }
    }
    assert_eq!(files, 4);
}
