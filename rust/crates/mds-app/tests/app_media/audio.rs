//! The WAV follows the editor as the C++ `WaveSeekAndFeed` callers do (see `mds_app::audio`):
//! what the output is told to play, checked with no device. The byte offsets are
//! `Wave::seek_offset`, which `mds-media/tests/wav_dump.rs` holds to the C++ dump.

use super::{run, wav};
use mds_app::audio::{self, FRAME_MOVE_SECONDS};
use mds_app::editor::Editor;
use mds_app::playback::{frame_to_seconds, loop_start_seconds};
use mds_app::ui::file::{answer, drop_files};
use mds_app::ui::Ctx;
use mds_media::wav::Wave;

/// The data-chunk byte `WaveSeekAndFeed` seeks to for `seconds`.
fn seek(w: &Wave, seconds: f64) -> usize {
    (w.seek_offset(seconds) - w.data.offset) as usize
}

fn loaded(name: &str) -> Editor {
    let mut e = Editor::empty();
    answer(Some(wav(name)));
    run(&mut e, "menu:206").unwrap();
    e
}

/// Menu 206 and the drop load the WAV into the editor (`CmdOpenWave`, `ui_dropfiles.cpp:240`:
/// the path, `LoadWaveFile`, `SceneModified`).
#[test]
fn the_menu_and_the_drop_load_the_wave() {
    let e = loaded("pcm16_stereo_44100.wav");
    let w = e.wave.as_ref().expect("menu 206 loads the WAV");
    assert_eq!(w.format.samples_per_sec, 44100);
    assert!(e.modified && e.doc.pmm.wave.enabled == 1);

    let mut e = Editor::empty();
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: &mut e,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    drop_files(&mut ctx, &[wav("pcm8_mono_8000.wav")]);
    assert_eq!(status, "");
    assert_eq!(e.wave.as_ref().unwrap().format.bits_per_sample, 8);
    assert!(e.modified);
    assert!(e.doc.pmm.wave.path.text.ends_with("pcm8_mono_8000.wav"));
}

/// Play starts the WAV at the play start (`ApplyPlaybackRangeEdits`,
/// `command_frame_edit.cpp:677`), the play button while playing stops it (`:625`), and the
/// end with loop off stops it (`PlayingBeyondEnd`, `playback_catchup.cpp:246`).
#[test]
fn play_and_stop_move_the_sound() {
    let mut e = loaded("pcm16_stereo_44100.wav");
    let w = e.wave.clone().unwrap();
    e.options.start_frame = 3;
    e.options.stop_frame = 5;
    e.toggle_play(1000).unwrap();
    let from = seek(&w, f64::from(frame_to_seconds(3)));
    assert_eq!(
        audio::playing().unwrap().bytes,
        from..w.pcm().len(),
        "play from frame 3"
    );
    e.toggle_play(1010).unwrap();
    assert_eq!(audio::playing(), None, "the play button stops it");

    e.toggle_play(2000).unwrap();
    assert!(audio::playing().is_some());
    e.pump(2000).unwrap();
    e.pump(2100).unwrap();
    assert!(!e.playing(), "frame 5 passed");
    assert_eq!(audio::playing(), None, "the end stops it");
}

/// Past the end with loop on, the WAV starts again at the loop start (409), not where play
/// started (`PlayingBeyondEnd`, `playback_catchup.cpp:265`).
#[test]
fn a_loop_restarts_the_sound() {
    let mut e = loaded("pcm16_stereo_44100.wav");
    let w = e.wave.clone().unwrap();
    e.options.looped = true;
    e.options.from_current = true;
    e.options.start_frame = 2;
    e.options.stop_frame = 4;
    e.apply(mds_doc::Command::SetFrame(1)).unwrap();
    e.toggle_play(0).unwrap();
    let start = f64::from(frame_to_seconds(1));
    assert_eq!(audio::playing().unwrap().bytes.start, seek(&w, start));
    e.pump(0).unwrap();
    e.pump(500).unwrap();
    assert!(e.playing());
    let loop_start = f64::from(loop_start_seconds(2));
    assert_eq!(audio::playing().unwrap().bytes.start, seek(&w, loop_start));
}

/// Menu 284 plays 33 ms from the frame before on a frame step or a seek (`RefreshTimeline`,
/// `ui_frame_step.cpp:132`); menu 297 mutes it and the playback (`:133`,
/// `command_frame_edit.cpp:677`).
#[test]
fn the_switches_gate_the_frame_moves() {
    let mut e = loaded("pcm16_stereo_44100.wav");
    let w = e.wave.clone().unwrap();
    e.step_frame(true).unwrap();
    assert_eq!(
        audio::playing(),
        None,
        "284 is off at start (`app_defaults.cpp:172`)"
    );

    run(&mut e, "menu:284").unwrap();
    assert!(audio::on_frame_move());
    for _ in 0..3 {
        e.step_frame(true).unwrap();
    }
    // Now at frame 4: from frame 3's time, for timer 100's 33 ms.
    let t = 3.0 / 30.0;
    assert_eq!(
        audio::playing().unwrap().bytes,
        seek(&w, t)..seek(&w, t + FRAME_MOVE_SECONDS)
    );
    e.seek(1).unwrap();
    assert_eq!(audio::playing().unwrap().bytes.start, 0, "frame 0's time");
    // From frame 0 the C++ asks for (u32)-1 / 30 seconds: past the end, nothing plays.
    e.seek(0).unwrap();
    assert!(audio::playing().unwrap().bytes.is_empty());

    run(&mut e, "menu:297").unwrap();
    assert!(audio::muted());
    audio::stop();
    e.step_frame(true).unwrap();
    e.toggle_play(0).unwrap();
    assert_eq!(
        audio::playing(),
        None,
        "297 mutes the frame moves and the play"
    );
    e.toggle_play(10).unwrap();
    run(&mut e, "menu:297").unwrap();
    run(&mut e, "menu:284").unwrap();
    assert!(!audio::muted() && !audio::on_frame_move());
}

/// A new scene drops the WAV (`ResetAppState` zeroes the wave path).
#[test]
fn a_new_scene_has_no_wave() {
    let mut e = loaded("pcm16_mono_11025.wav");
    e.toggle_play(0).unwrap();
    e.toggle_play(1).unwrap();
    e.apply(mds_doc::Command::NewScene).unwrap();
    assert!(e.wave.is_none() && e.doc.pmm.wave.enabled == 0);
}
