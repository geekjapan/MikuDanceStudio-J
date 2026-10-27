//! Recording (menu 223, `MDS_CMD_RENDER_VIDEO`): the frame-step loop of the C++ recorder, with
//! the built-in writers in place of DirectShow.
//!
//! The C++ arms the recording in `RecordStartTail` (`src/app/avi_record_start.cpp:180`: the
//! saved current frame, a seek to the start frame) and section 10 of `FrameDriver` at the end of
//! the next pass (`src/app/frame_driver.cpp:624`: the cursor at the start frame, `PlaybackActive`,
//! `UpdateBoneFrames`, the counter N at 0). Each pass then draws the frame at the cursor and
//! pushes it (`RecordingReadbackPass`, `src/app/record_readback.cpp:128`), and
//! `PlaybackCatchup` (`src/app/playback_catchup.cpp:287`) counts N up and runs the frame-step
//! block: the target [`term`] `N * 30 / fps + start` frames,
//! one `1 / fps` time budget per pass, until the target's whole frame passes the end frame
//! ([`records`]); then `FinishAviRecord` (`src/app/late_ports.cpp:63`) stops as `StopPlayback`.
//! Esc stops it early (`PumpEscStop`, `src/app/pump_edit_keys.cpp:368`).
//!
//! The frame dump's `ArmFrameStep` (`src/tools/trace_mode.cpp:214`) arms the same loop but poses
//! every model once more (`PoseAllModels`, `:234`); the application does not, so frame 0 of a
//! scene with physics differs from the dump in the last bits of the physics bones.
//!
//! [`crate::editor::Editor`] runs that loop in its pump; this file has the arithmetic and the
//! output. Each frame is the frame dump's image ([`crate::dump`]: the 8x sample pattern, the
//! track camera at the frame), at the size the AVI dialog shows (the render size of menu 212).
//!
//! The output is the operator's choice of 2026-10-25: an uncompressed AVI ([`mds_media::avi`],
//! with the loaded WAV as PCM when the dialog asks for it) or a PNG sequence, no codec picker,
//! no 3D Vision. The C++ muxes the WAV only when the recording starts at frame 0
//! (`StartRecordGraph`); here the sound starts at the start frame's time.

use crate::audio;
use crate::ui::dialog::{AviFormat, AviSettings};
use mds_media::avi::{AudioFormat, AviWriter, Config};
use mds_media::wav::Wave;
use mds_render::Gpu;
use std::fs::File;
use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// The frame-step target in frames after N passes (x64 0x7FF7CB44B92E): single precision, in
/// this order; the start frame unsigned.
pub fn term(n: u32, start: i32, fps: f32) -> f32 {
    (n as i32) as f32 * 30.0 / fps + (start as u32) as f32
}

/// Whether the pass after N passes still records: the target's whole frame (`cvttss2si r64`,
/// the low half) below `end + 1`, unsigned (0x46F06A `jb`).
pub fn records(n: u32, start: i32, end: i32, fps: f32) -> bool {
    ((term(n, start, fps) as i64) as u32) < (end.wrapping_add(1) as u32)
}

/// The frame number of the recording window's title (0x46EEE0): `N * 30` as an integer first,
/// unlike [`term`].
pub fn shown(n: u32, start: i32, fps: f32) -> i32 {
    ((n as i32).wrapping_mul(30) as f32 / fps + (start as u32) as f32) as i32
}

/// The window title text: `" %d"`, or `" %dframe recording(until %dframe)"` in English.
pub fn title(n: u32, s: &AviSettings, english: bool) -> String {
    let frame = shown(n, s.start_frame, s.fps);
    match english {
        true => format!(" {frame}frame recording(until {}frame)", s.end_frame),
        false => format!(" {frame}"),
    }
}

/// The AVI frame rate as a fraction: whole rates over 1, else thousandths.
pub fn fps_fraction(fps: f32) -> (u32, u32) {
    if fps.fract() == 0.0 {
        (fps as u32, 1)
    } else {
        ((f64::from(fps) * 1000.0).round() as u32, 1000)
    }
}

/// The file of recorded frame `k` of a PNG sequence named after `path`:
/// `<folder>/<stem>_<k, 5 digits>.png`.
pub fn png_path(path: &Path, k: u32) -> PathBuf {
    let stem = path
        .file_stem()
        .map_or("frame".into(), |s| s.to_string_lossy());
    path.with_file_name(format!("{stem}_{k:05}.png"))
}

enum Sink {
    Avi {
        writer: Box<AviWriter<BufWriter<File>>>,
        /// The WAV and the byte of the data chunk at the start frame.
        sound: Option<(Arc<Wave>, usize)>,
    },
    Png(PathBuf),
}

/// A running recording.
pub struct Recording {
    pub settings: AviSettings,
    /// `recordedFrameCount`, N: the frames written.
    pub n: u32,
    /// `PlaybackCursorSeconds`.
    pub cursor: f32,
    /// `recordPlaybackStartPending`: the frame steps start after the next pass.
    pub pending: bool,
    sink: Sink,
    gpu: Gpu,
}

impl Recording {
    /// The writer of `settings` at `path` (`ProbeWritable` first: a file that cannot be made is
    /// refused), with the cursor at the start frame.
    pub fn new(
        settings: &AviSettings,
        path: &Path,
        wave: Option<&Arc<Wave>>,
    ) -> Result<Recording, String> {
        let [width, height] = [settings.width, settings.height].map(|n| n.max(1) as u32);
        let gpu = Gpu::new()?.ok_or("no wgpu adapter")?;
        let fail = |e: &dyn std::fmt::Display| format!("{}: {e}", path.display());
        let sink = match settings.format {
            AviFormat::PngSequence => {
                std::fs::write(png_path(path, 0), []).map_err(|e| fail(&e))?;
                Sink::Png(path.to_path_buf())
            }
            AviFormat::UncompressedAvi => {
                let sound = match wave.filter(|_| settings.include_wave) {
                    Some(w) => {
                        let f = w.format;
                        if !matches!(f.bits_per_sample, 8 | 16) {
                            return Err("the AVI takes 8 or 16 bit WAV only".into());
                        }
                        let start = audio::byte_at(
                            w,
                            f64::from(crate::playback::frame_to_seconds(settings.start_frame)),
                        );
                        Some((w.clone(), start))
                    }
                    None => None,
                };
                let (fps_num, fps_den) = fps_fraction(settings.fps);
                let config = Config {
                    width,
                    height,
                    fps_num,
                    fps_den,
                    audio: sound.as_ref().map(|(w, _)| AudioFormat {
                        channels: w.format.channels,
                        sample_rate: w.format.samples_per_sec,
                        bits: w.format.bits_per_sample,
                    }),
                };
                let file = File::create(path).map_err(|e| fail(&e))?;
                let writer = AviWriter::new(BufWriter::new(file), config).map_err(|e| fail(&e))?;
                Sink::Avi {
                    writer: Box::new(writer),
                    sound,
                }
            }
        };
        Ok(Recording {
            settings: settings.clone(),
            n: 0,
            cursor: crate::playback::frame_to_seconds(settings.start_frame),
            pending: true,
            sink,
            gpu,
        })
    }

    pub fn size(&self) -> [u32; 2] {
        [self.settings.width, self.settings.height].map(|n| n.max(1) as u32)
    }

    pub fn gpu(&self) -> &Gpu {
        &self.gpu
    }

    /// Writes frame N (`rgba` at [`Recording::size`], top-down), with its sound.
    pub fn write(&mut self, rgba: &[u8]) -> Result<(), String> {
        let [w, h] = self.size();
        match &mut self.sink {
            Sink::Png(path) => {
                let file = png_path(path, self.n);
                std::fs::write(&file, mds_render::encode_png(w, h, rgba))
                    .map_err(|e| format!("{}: {e}", file.display()))
            }
            Sink::Avi { writer, sound } => {
                if let Some((wave, start)) = sound {
                    let bytes = audio::frame_bytes(wave, *start, self.n, self.settings.fps);
                    if !bytes.is_empty() {
                        writer
                            .write_audio(&wave.pcm()[bytes])
                            .map_err(|e| e.to_string())?;
                    }
                }
                let bgr: Vec<u8> = rgba
                    .chunks_exact(4)
                    .flat_map(|p| [p[2], p[1], p[0]])
                    .collect();
                writer.write_frame(&bgr).map_err(|e| e.to_string())
            }
        }
    }

    /// Closes the output (the AVI index and header).
    pub fn finish(self) -> Result<(), String> {
        match self.sink {
            Sink::Avi { writer, .. } => writer.finish().map(drop).map_err(|e| e.to_string()),
            Sink::Png(_) => Ok(()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_target_advances_n_over_fps_seconds() {
        // At 30 fps the target is frame N exactly, as the frame dump's `next_target`.
        assert!((0..2000).all(|n| term(n, 0, 30.0) == (n as f32 * 30.0) / 30.0 + 0.0));
        assert_eq!(term(3, 10, 30.0), 13.0);
        // At 60 fps two passes per frame; at 15 one pass per two frames.
        assert_eq!(term(3, 0, 60.0), 1.5);
        assert_eq!(term(3, 0, 15.0), 6.0);
        // The start frame is unsigned.
        assert_eq!(term(0, -1, 30.0), 4_294_967_295u32 as f32);
    }

    #[test]
    fn the_end_frame_is_recorded_then_it_stops() {
        // Frames 0 to 3 at 30 fps: passes 0..=3 record, the fourth stops.
        let passes = (0..).take_while(|&n| records(n, 0, 3, 30.0)).count();
        assert_eq!(passes, 4);
        // At 60 fps the end frame's two halves are recorded: 0, 0.5, ..., 3.5.
        assert_eq!((0..).take_while(|&n| records(n, 0, 3, 60.0)).count(), 8);
        // 29.97 fps: term 89.9 truncates to frame 89 < 90, term 90.09 does not.
        assert!(records(89, 0, 89, 29.97) && !records(90, 0, 89, 29.97));
        assert_eq!((0..).take_while(|&n| records(n, 5, 5, 30.0)).count(), 1);
    }

    #[test]
    fn the_title_multiplies_as_integers() {
        let s = AviSettings {
            start_frame: 10,
            end_frame: 99,
            fps: 60.0,
            width: 640,
            height: 360,
            include_wave: false,
            format: AviFormat::UncompressedAvi,
        };
        assert_eq!(shown(3, 10, 60.0), 11);
        assert_eq!(title(3, &s, false), " 11");
        assert_eq!(title(3, &s, true), " 11frame recording(until 99frame)");
        // `N * 30` overflows as the C++ int does; the float form of the target does not.
        assert_eq!(
            shown(80_000_000, 0, 30.0),
            (80_000_000i32.wrapping_mul(30) as f32 / 30.0) as i32
        );
    }

    #[test]
    fn rates_and_names() {
        assert_eq!(fps_fraction(30.0), (30, 1));
        assert_eq!(fps_fraction(29.97), (29970, 1000));
        assert_eq!(
            png_path(Path::new("/out/take.avi"), 7),
            Path::new("/out/take_00007.png")
        );
    }
}
