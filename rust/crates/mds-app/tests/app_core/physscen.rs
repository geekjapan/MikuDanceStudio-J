//! The physscen traces of the C++ app (`tests/fixtures/rust/physscen`) through the editor, every
//! `rigid` line of every block, bit for bit: what `mds-physics/tests/physscen.rs` models beside
//! the physics API is here the editor's own (the play button, the wall-clock target, the loop
//! restart, the stop frame, the frame edit and the steps, the physics menus).
//!
//! The script runner pumps twice before its first command (`RunScriptMode`), so `load pmm` is a
//! File > Open in a running application: [`Editor::open`] adopted by the startup editor, as
//! `ui::file::open_path` does, after a pump. Each `pump <n> <ms>` is n [`Editor::pump`]s, the
//! clock `ms` later each time. The play edits 409 and 410 are inline rows; the test sets them as
//! typing does.

use super::fixtures;
use mds_app::editor::Editor;
use mds_app::ui::Ctx;
use mds_doc::Command;

fn run(editor: &mut Editor, now_ms: u64, id: &str) {
    let mut status = String::new();
    let mut ctx = Ctx {
        editor,
        now_ms,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    mds_app::actions::run(&mut ctx, id).unwrap_or_else(|e| panic!("{id}: {e}"));
}

/// The `rigid` lines of one trace block (`src/tools/trace_l2.hpp`).
fn block(out: &mut String, editor: &Editor, block: u32) {
    let scene = &editor.physics;
    for (model, poses) in scene.scene.models.iter().zip(scene.body_poses().unwrap()) {
        for (i, pose) in poses.into_iter().enumerate() {
            let (origin, rotation) = pose.expect("every swing600 body is built");
            out.push_str(&format!("{block} rigid {} {i}", model.slot));
            mds_pose::trace::floats(out, &origin).unwrap();
            mds_pose::trace::floats(out, &rotation).unwrap();
            out.push('\n');
        }
    }
}

/// Replays `physscen/<name>.txt` through the editor and returns the trace it writes.
fn replay(name: &str) -> String {
    let dir = fixtures().join("physscen");
    let script = std::fs::read_to_string(dir.join(format!("{name}.txt"))).unwrap();
    let mut e = Editor::empty();
    let mut now = 0;
    e.pump(now).unwrap();
    let mut out: Option<String> = None;
    let mut passes = 0;
    for line in script.lines() {
        let w: Vec<&str> = line.split_whitespace().collect();
        let num = |i: usize| w[i].parse::<i32>().unwrap();
        match w[..] {
            [] => {}
            [c, ..] if c.starts_with('#') => {}
            ["settle", "0"] | ["save", "pmm", _] => {}
            ["load", "pmm", file] => {
                let opened = Editor::open(&fixtures().join(file)).unwrap();
                e.adopt(opened).unwrap();
            }
            ["trace", _] => {
                let mut s = String::from(mds_pose::trace::HEADER);
                block(&mut s, &e, 0);
                out = Some(s);
            }
            ["frame", _] => e.seek(num(1) as u32).unwrap(),
            ["play", _, _] => {
                assert!(!e.playing(), "{line}: playing");
                e.options.start_frame = num(1);
                e.options.stop_frame = num(2);
                run(&mut e, now, "ctl:408");
            }
            ["stop"] => {
                assert!(e.playing(), "{line}: not playing");
                run(&mut e, now, "ctl:408");
            }
            ["loop", on] => e.options.looped = on == "on",
            ["step", "forward"] => run(&mut e, now, "ctl:419"),
            ["step", "back"] => run(&mut e, now, "ctl:418"),
            // swing600's model is a PMX, for which menu 270 is greyed (`ui_model_reload.cpp:553`);
            // the runner's `WM_COMMAND` (`script_mode.cpp:479`) runs the handler all the same.
            ["physics", "mode", "3"] => e.apply(Command::SetPhysicsMode(3)).unwrap(),
            ["physics", "mode", m] => {
                let id = ["menu:272", "menu:265", "menu:269"][m.parse::<usize>().unwrap()];
                run(&mut e, now, id);
            }
            ["physics", "playback", "toggle"] => run(&mut e, now, "menu:271"),
            ["physics", "reset"] => run(&mut e, now, "menu:268"),
            ["pump", _, _] => {
                for _ in 0..num(1) {
                    now += num(2) as u64;
                    e.pump(now).unwrap();
                    if let Some(out) = out.as_mut() {
                        passes += 1;
                        block(out, &e, passes);
                    }
                }
            }
            _ => panic!("{name}.txt: unknown command {line}"),
        }
    }
    out.expect("the script opens no trace")
}

fn gate(name: &str) {
    let path = fixtures().join(format!("physscen/expected/{name}/{name}.trace"));
    let Ok(want) = std::fs::read_to_string(&path) else {
        println!("SKIP {name}: {} is missing", path.display());
        return;
    };
    let got = replay(name);
    if let Some((i, (g, w))) = got
        .lines()
        .zip(want.lines())
        .enumerate()
        .find(|(_, (g, w))| g != w)
    {
        panic!("{name}: line {}: got\n{g}\nwant\n{w}", i + 1);
    }
    assert_eq!(got.lines().count(), want.lines().count(), "{name}: blocks");
    assert!(got == want, "{name}: formatting");
    eprintln!("{name}: {} lines, bit for bit", got.lines().count());
}

#[test]
fn seek() {
    gate("seek");
}

#[test]
fn play() {
    gate("play");
}

#[test]
fn stop() {
    gate("stop");
}

#[test]
fn loop_restart() {
    gate("loop");
}

#[test]
fn step() {
    gate("step");
}

#[test]
fn mode() {
    gate("mode");
}

#[test]
fn budget() {
    gate("budget");
}

#[test]
fn negstep() {
    gate("negstep");
}

#[test]
fn seeksettle() {
    gate("seeksettle");
}

#[test]
fn playsettle() {
    gate("playsettle");
}

#[test]
fn mode3() {
    gate("mode3");
}

#[test]
fn toggle() {
    gate("toggle");
}

#[test]
fn reset() {
    gate("reset");
}
