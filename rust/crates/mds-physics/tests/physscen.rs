//! Gate: the physscen traces of the x64 app (`tests/fixtures/rust/physscen`),
//! every `rigid` line of every block, bit for bit. Each script drives
//! playback and physics on swing600.pmm through the app's handlers and frame
//! loop (`src/tools/script_mode.cpp`), and the replay runs the same commands
//! through the interactive API with the same clock steps.
//!
//! The runner pumps twice before the first command (`RunScriptMode`), so the
//! PMM loads into a world that has pumped: [`PhysicsScene::open_running`].
//! The application state the API leaves to its caller is modelled here as
//! the handlers keep it: the play-range edits (`ApplyPlaybackRangeEdits`,
//! `FrameToSeconds`, `command_frame_edit.cpp`), the stop frame
//! (`StopPlayback`, `playback_state.cpp`), the current frame of the frame
//! edit (`CommitEditControl`, `ui_edit_commit.cpp`) and of `StepFrame`
//! (`ui_frame_step.cpp`), the settle request of the physics menus
//! (`command_view_menu.cpp`), and the wall-clock target and loop restart of
//! `PlaybackCatchup` and `PlayingBeyondEnd` (`playback_catchup.cpp`).

use mds_formats::pmm::Pmm;
use mds_physics::PhysicsScene;
use std::path::{Path, PathBuf};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// What the C++ app keeps outside the physics scene.
struct App {
    scene: PhysicsScene,
    /// `currentFrame`.
    current_frame: i32,
    /// The start edit 409, which the loop restart reads again.
    start_edit: i32,
    /// `PlaybackLoopEnabled`.
    loop_on: bool,
    /// `playbackReturnsToStartFrame`.
    return_to_start: bool,
    /// `PlaybackStartsAtCurrentFrame`.
    start_at_current: bool,
    last_registered_frame: i32,
    /// `PlaybackStartSeconds`, `PlaybackEndSeconds`.
    start: f32,
    end: f32,
    /// The clock `TimeNow` and the play anchor `T0`, in milliseconds.
    now: u64,
    anchor: u64,
}

/// `FrameToSeconds`: the unsigned frame over 30 in double, stored as float.
fn frame_seconds(frame: i32) -> f32 {
    (f64::from(frame as u32) / 30.0) as f32
}

impl App {
    fn load(dir: &Path, name: &str) -> App {
        let pmm = Pmm::read(&std::fs::read(dir.join(name)).unwrap()).unwrap();
        let t = &pmm.timeline;
        App {
            current_frame: t.current_frame,
            start_edit: t.play_start_frame,
            loop_on: t.playback_loop != 0,
            return_to_start: t.return_to_start != 0,
            start_at_current: t.start_at_current != 0,
            last_registered_frame: t.last_registered_frame,
            start: 0.0,
            end: 0.0,
            now: 0,
            anchor: 0,
            scene: PhysicsScene::open_running(&pmm, |path| {
                std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"))
            })
            .unwrap(),
        }
    }

    /// `ApplyPlaybackRangeEdits` while stopped.
    fn play(&mut self, start: i32, end: i32) {
        self.start_edit = start;
        let changed = if self.start_at_current {
            self.start = frame_seconds(self.current_frame);
            true
        } else {
            self.start = frame_seconds(start);
            start == self.current_frame
        };
        let end = if end == 0 {
            self.last_registered_frame
        } else {
            end
        };
        self.end = frame_seconds(end);
        self.scene.start_playback(self.start, changed);
        self.anchor = self.now;
    }

    /// `StopPlayback`.
    fn stop(&mut self) {
        if self.return_to_start {
            self.current_frame = (f64::from(self.scene.scene.cursor) * 30.0) as i32;
        }
        self.scene.stop_playback(self.current_frame as u32);
    }

    /// `StepFrame`.
    fn step(&mut self, forward: bool) {
        if forward {
            self.current_frame += 1;
        } else if self.current_frame != 0 {
            self.current_frame -= 1;
        }
        self.scene.step_frame(self.current_frame as u32, forward);
    }

    /// One pass of the winmain.cpp loop body as `Pump` runs it.
    fn pump(&mut self, ms: u32) {
        self.now += u64::from(ms);
        let dt = ms as f32 * 0.001;
        if !self.scene.playing() {
            return self.scene.tick(dt).unwrap();
        }
        let target = (self.now - self.anchor) as f32 * 0.001 + self.start;
        if target <= self.end {
            return self.scene.catch_up(target, dt).unwrap();
        }
        self.scene.scene.cursor = target;
        if self.loop_on {
            self.start = (self.start_edit as u32) as f32 / 30.0;
            self.anchor = self.now;
            self.scene.loop_restart(self.start, dt).unwrap();
        } else {
            self.stop();
            self.scene.tick(dt).unwrap();
        }
    }
}

/// The `rigid` lines of one trace block.
fn block(out: &mut String, scene: &PhysicsScene, block: u32) {
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

/// Replays `physscen/<name>.txt` and returns the trace it writes.
fn replay(dir: &Path, name: &str) -> String {
    let script = std::fs::read_to_string(dir.join(format!("physscen/{name}.txt"))).unwrap();
    let mut app: Option<App> = None;
    let mut out: Option<String> = None;
    let mut passes = 0;
    for line in script.lines() {
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.is_empty() || words[0].starts_with('#') {
            continue;
        }
        let num = |i: usize| words[i].parse::<i32>().unwrap();
        match words[..] {
            // Only `pump` runs frames.
            ["settle", "0"] => continue,
            ["load", "pmm", file] => {
                app = Some(App::load(dir, file));
                continue;
            }
            _ => {}
        }
        let a = app.as_mut().expect("a command before the load");
        match words[..] {
            ["save", "pmm", _] => {}
            ["trace", _] => {
                let mut s = String::from(mds_pose::trace::HEADER);
                block(&mut s, &a.scene, 0);
                out = Some(s);
            }
            ["frame", _] => {
                a.current_frame = num(1);
                a.scene.seek(a.current_frame as u32);
            }
            ["play", _, _] => a.play(num(1), num(2)),
            ["stop"] => {
                assert!(a.scene.playing(), "{line}: not playing");
                a.stop();
            }
            ["loop", on] => a.loop_on = on == "on",
            ["step", dir] => a.step(dir == "forward"),
            ["physics", "mode", mode] => {
                let mode: u8 = mode.parse().unwrap();
                a.scene.set_physics_mode(mode).unwrap();
                // Menus 265, 269 and 270 request a settle; 272 does not.
                if mode != 0 {
                    a.scene.reset();
                }
            }
            ["physics", "playback", "toggle"] => {
                a.scene.always_on_off = !a.scene.always_on_off;
            }
            ["physics", "reset"] => a.scene.reset(),
            ["pump", _, _] => {
                for _ in 0..num(1) {
                    a.pump(num(2) as u32);
                    if let Some(out) = out.as_mut() {
                        passes += 1;
                        block(out, &a.scene, passes);
                    }
                }
            }
            _ => panic!("{name}.txt: unknown command {line}"),
        }
    }
    out.expect("the script opens no trace")
}

fn gate(name: &str, blocks: usize) {
    let dir = fixtures();
    let path = dir.join(format!("physscen/expected/{name}/{name}.trace"));
    let Ok(expected) = std::fs::read_to_string(&path) else {
        println!("SKIP {name}: {} is missing", path.display());
        return;
    };
    // 25 rigid bodies per block.
    assert_eq!(expected.lines().count(), 1 + blocks * 25, "{name}");
    let actual = replay(&dir, name);
    let difference = mds_trace::diff(actual.as_bytes(), expected.as_bytes()).unwrap();
    assert!(difference.is_none(), "{name}: {}", difference.unwrap());
    assert!(actual == expected, "{name}: traces differ in formatting");
}

#[test]
fn seek() {
    gate("seek", 1 + 3);
}

#[test]
fn play() {
    gate("play", 1 + 13);
}

#[test]
fn stop() {
    gate("stop", 1 + 20);
}

#[test]
fn loop_restart() {
    gate("loop", 1 + 31);
}

#[test]
fn step() {
    gate("step", 1 + 6);
}

#[test]
fn mode() {
    gate("mode", 1 + 34);
}

#[test]
fn budget() {
    gate("budget", 1 + 20);
}

/// A fresh world spends its first 1/60 s on the first step after the load;
/// the script runner's world spent it on the empty scene.
#[test]
fn a_fresh_world_does_not_replay_the_runner() {
    let dir = fixtures();
    let pmm = Pmm::read(&std::fs::read(dir.join("swing600.pmm")).unwrap()).unwrap();
    let read = |path: &str| std::fs::read(dir.join(path)).map_err(|e| format!("{path}: {e}"));
    let mut fresh = PhysicsScene::open(&pmm, read).unwrap();
    let mut running = PhysicsScene::open_running(&pmm, read).unwrap();
    assert!(fresh.body_poses().unwrap() == running.body_poses().unwrap());
    fresh.seek(300);
    running.seek(300);
    fresh.tick(0.033).unwrap();
    running.tick(0.033).unwrap();
    assert!(fresh.body_poses().unwrap() != running.body_poses().unwrap());
}
