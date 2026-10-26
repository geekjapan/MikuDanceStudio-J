//! A recording (menu 223) of a scene from frame 0 at 30 fps runs the frame steps of the frame
//! dump (`RunFrameDump` arms the same frame-step mode, `src/tools/trace_mode.cpp:220`), so its
//! frames are the dump's: the PNG sequence byte for byte, the AVI's frames by
//! `ffmpeg -f framemd5` against the dump's PNGs. The WAV muxed into the AVI is the data chunk
//! from the start frame on. A host without a wgpu adapter, `ffprobe` or `ffmpeg` prints SKIP,
//! which is not a pass.

use super::{run, scratch, stage, wav};
use mds_app::dump;
use mds_app::editor::Editor;
use mds_app::ui::dialog::{AviFormat, AviSettings};
use mds_app::ui::file::{answer, answer_avi};
use mds_doc::Command;
use mds_render::Gpu;
use std::path::Path;
use std::process::Command as Process;

/// The golden2 scene without physics and the swing scene with it.
const SCENES: [&str; 2] = ["perspective", "swing600-golden"];
const FRAMES: u32 = 4;

fn gpu() -> Option<Gpu> {
    let gpu = Gpu::new().expect("device");
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
    }
    gpu
}

fn have_ffmpeg() -> bool {
    let ok = ["ffprobe", "ffmpeg"].iter().all(|t| {
        Process::new(t)
            .arg("-version")
            .output()
            .is_ok_and(|o| o.status.success())
    });
    if !ok {
        eprintln!("SKIP: ffprobe or ffmpeg missing (not a pass)");
    }
    ok
}

fn settings(end_frame: i32, format: AviFormat) -> AviSettings {
    AviSettings {
        start_frame: 0,
        end_frame,
        fps: 30.0,
        width: dump::WIDTH as i32,
        height: dump::HEIGHT as i32,
        include_wave: false,
        format,
    }
}

/// The scene opened as the window opens it, at the dump's size.
fn open(pmm: &Path) -> Editor {
    let mut e = Editor::open(pmm).unwrap();
    e.apply(Command::SetRenderSize {
        width: dump::WIDTH as i32,
        height: dump::HEIGHT as i32,
    })
    .unwrap();
    e
}

/// Menu 223 with the save dialog answered `path` and the AVI dialog `settings`, then the pumps
/// until the recording ends; returns the frames written. The first pump (the window's first,
/// at 0 ms) is the pass that arms the frame steps, as the dump's load pass and `ArmFrameStep`.
fn record(e: &mut Editor, path: &Path, settings: AviSettings) -> u32 {
    answer(Some(path.to_path_buf()));
    answer_avi(settings);
    run(e, "menu:223").unwrap();
    assert!(e.recording.is_some() && e.playing());
    let mut pumps = 0;
    while e.recording.is_some() {
        e.pump(u64::from(pumps) * 33).unwrap();
        pumps += 1;
        assert!(pumps < 1000);
    }
    pumps - 1
}

fn dump_frames(gpu: &Gpu, pmm: &Path, out: &Path) {
    dump::run(
        gpu,
        &dump::Request {
            pmm: pmm.to_path_buf(),
            out: out.to_path_buf(),
            frames: (0..FRAMES).collect(),
            picture_viewport: None,
        },
    )
    .unwrap();
}

/// `ffmpeg -f framemd5` of the video frames of `input` (extra input arguments first) as bgr24.
fn frame_md5s(input_args: &[&str], input: &Path) -> Vec<String> {
    let out = Process::new("ffmpeg")
        .args(["-v", "error"])
        .args(input_args)
        .arg("-i")
        .arg(input)
        .args(["-map", "0:v:0", "-pix_fmt", "bgr24", "-f", "framemd5", "-"])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .unwrap()
        .lines()
        .filter(|l| !l.starts_with('#'))
        .map(|l| l.rsplit(',').next().unwrap().trim().to_string())
        .collect()
}

/// `key=value` lines of `ffprobe -of flat`.
fn probe(path: &Path) -> Vec<(String, String)> {
    let out = Process::new("ffprobe")
        .args([
            "-v",
            "error",
            "-count_frames",
            "-of",
            "flat",
            "-show_streams",
        ])
        .arg(path)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .unwrap()
        .lines()
        .filter_map(|l| l.split_once('='))
        .map(|(k, v)| (k.to_string(), v.trim_matches('"').to_string()))
        .collect()
}

fn get<'a>(p: &'a [(String, String)], key: &str) -> &'a str {
    &p.iter()
        .find(|(k, _)| k == key)
        .unwrap_or_else(|| panic!("no {key}: {p:?}"))
        .1
}

#[test]
fn the_png_sequence_is_the_frame_dump() {
    let Some(gpu) = gpu() else { return };
    let dir = scratch("png");
    stage(&dir);
    for name in SCENES {
        let pmm = dir.join(format!("{name}.pmm"));
        let dumps = dir.join(format!("{name}-dump"));
        dump_frames(&gpu, &pmm, &dumps);
        let mut e = open(&pmm);
        let path = dir.join(format!("{name}.avi"));
        let pumps = record(
            &mut e,
            &path,
            settings(FRAMES as i32 - 1, AviFormat::PngSequence),
        );
        assert_eq!(pumps, FRAMES, "{name}: frames 0 to 3, one per pump");
        for k in 0..FRAMES {
            let got = std::fs::read(mds_app::record::png_path(&path, k)).unwrap();
            let want = std::fs::read(dumps.join(format!("{name}-{k}.png"))).unwrap();
            assert!(
                got == want,
                "{name}: recorded frame {k} differs from the dump"
            );
        }
        assert!(!mds_app::record::png_path(&path, FRAMES).exists());
        eprintln!("{name}: {FRAMES} PNG frames equal the dump");
    }
}

#[test]
fn the_avi_decodes_to_the_frame_dump() {
    let Some(gpu) = gpu() else { return };
    if !have_ffmpeg() {
        return;
    }
    let dir = scratch("avi");
    stage(&dir);
    for name in SCENES {
        let pmm = dir.join(format!("{name}.pmm"));
        let dumps = dir.join(format!("{name}-dump"));
        dump_frames(&gpu, &pmm, &dumps);
        let mut e = open(&pmm);
        let path = dir.join(format!("{name}.avi"));
        record(
            &mut e,
            &path,
            settings(FRAMES as i32 - 1, AviFormat::UncompressedAvi),
        );
        let p = probe(&path);
        assert_eq!(get(&p, "streams.stream.0.codec_name"), "rawvideo");
        assert_eq!(get(&p, "streams.stream.0.width"), "640");
        assert_eq!(get(&p, "streams.stream.0.r_frame_rate"), "30/1");
        assert_eq!(
            get(&p, "streams.stream.0.nb_read_frames"),
            FRAMES.to_string()
        );
        let got = frame_md5s(&[], &path);
        let pattern = dumps.join(format!("{name}-%d.png"));
        let want = frame_md5s(&["-framerate", "30"], &pattern);
        assert_eq!(want.len(), FRAMES as usize);
        assert_eq!(got, want, "{name}: framemd5 of the AVI and of the dump");
        eprintln!("{name}: AVI framemd5 {got:?}");
    }
}

/// "WAVEも出力する": the data chunk's bytes from the start frame's time, in whole blocks per
/// frame, decode back unchanged; a start past 0 starts the sound there.
#[test]
fn the_avi_carries_the_wave() {
    let Some(_gpu) = gpu() else { return };
    if !have_ffmpeg() {
        return;
    }
    let dir = scratch("wave");
    stage(&dir);
    let mut e = open(&dir.join("perspective.pmm"));
    answer(Some(wav("pcm16_stereo_44100.wav")));
    run(&mut e, "menu:206").unwrap();
    let w = e.wave.clone().unwrap();
    for start in [0, 2] {
        let path = dir.join(format!("wave-{start}.avi"));
        let s = AviSettings {
            start_frame: start,
            include_wave: true,
            ..settings(start + 3, AviFormat::UncompressedAvi)
        };
        assert_eq!(record(&mut e, &path, s), 4);
        let p = probe(&path);
        assert_eq!(get(&p, "streams.stream.1.codec_name"), "pcm_s16le");
        assert_eq!(get(&p, "streams.stream.1.sample_rate"), "44100");
        assert_eq!(get(&p, "streams.stream.1.channels"), "2");
        // 1470 sample frames per video frame at 44100 Hz and 30 fps.
        let from = (w.seek_offset(f64::from(start as f32 / 30.0)) - w.data.offset) as usize;
        let want = &w.pcm()[from..(from + 4 * 1470 * 4).min(w.pcm().len())];
        let raw = dir.join(format!("wave-{start}.raw"));
        let out = Process::new("ffmpeg")
            .args(["-v", "error", "-y", "-i"])
            .arg(&path)
            .args(["-map", "0:a:0", "-f", "s16le"])
            .arg(&raw)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(
            std::fs::read(&raw).unwrap() == want,
            "start {start}: the sound differs"
        );
    }
}

/// Esc stops the recording at once (`PumpEscStop`), and `FinishAviRecord` closes a whole AVI
/// of the frames written; the current frame stays where it was (`StopPlayback` with 413 off).
#[test]
fn esc_stops_the_recording() {
    let Some(_gpu) = gpu() else { return };
    let dir = scratch("esc");
    stage(&dir);
    let mut e = open(&dir.join("perspective.pmm"));
    e.apply(Command::SetFrame(5)).unwrap();
    let path = dir.join("esc.avi");
    answer(Some(path.clone()));
    answer_avi(settings(99, AviFormat::UncompressedAvi));
    run(&mut e, "menu:223").unwrap();
    assert!(run(&mut e, "ctl:408").is_err(), "no play while recording");
    for t in [0, 33, 66] {
        e.pump(t).unwrap();
    }
    assert_eq!(e.recording.as_ref().unwrap().n, 2);
    assert_eq!(e.shown_frame(), 2);
    run(&mut e, "key:Esc@recording").unwrap();
    assert!(e.recording.is_none() && !e.playing());
    assert_eq!(e.current_frame(), 5);
    if have_ffmpeg() {
        assert_eq!(get(&probe(&path), "streams.stream.0.nb_read_frames"), "2");
    }
}

/// Other rates step `30 / fps` frames per pass and record up to the end frame's last step.
#[test]
fn other_frame_rates_step_their_own_time() {
    let Some(_gpu) = gpu() else { return };
    let dir = scratch("fps");
    stage(&dir);
    let mut e = open(&dir.join("perspective.pmm"));
    let s = |fps| AviSettings {
        fps,
        ..settings(3, AviFormat::PngSequence)
    };
    assert_eq!(record(&mut e, &dir.join("a60.avi"), s(60.0)), 8);
    assert_eq!(record(&mut e, &dir.join("a15.avi"), s(15.0)), 2);
    // The first frame is always the start frame's, whatever the rate.
    let first = std::fs::read(mds_app::record::png_path(&dir.join("a60.avi"), 0)).unwrap();
    assert_eq!(
        first,
        std::fs::read(mds_app::record::png_path(&dir.join("a15.avi"), 0)).unwrap()
    );
}
