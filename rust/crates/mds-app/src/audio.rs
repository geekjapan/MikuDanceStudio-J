//! WAV playback in step with the timeline, and the byte arithmetic the recording shares.
//!
//! The C++ streams the WAV to DirectSound: `WaveSeekAndFeed` (`src/app/subsystem_init.cpp:214`)
//! seeks the file to a time and starts the feed thread, `WaveStartPlayback` after
//! `CloseDataFile` stops it. Its callers:
//!
//! * play (`ApplyPlaybackRangeEdits`, `src/window/command_frame_edit.cpp:622`): from the play
//!   start time, unless menu 297 is checked; the play button while playing stops it;
//! * past the end (`PlayingBeyondEnd`, `src/app/playback_catchup.cpp:244`): stops, and with loop
//!   on starts again at the loop start unless 297 is checked;
//! * a frame move with menu 284 checked (`RefreshTimeline`, `src/window/ui_frame_step.cpp:132`,
//!   and the frame strip, `src/window/ui_mouse_misc.cpp:211`): `WaveRestartAt` from the frame
//!   before, `(u32)(frame - 1) / 30.0` seconds, for the 33 ms of timer 100 (`HandleTimer100`,
//!   `src/window/ui_control_text.cpp:75`, closes the file).
//!
//! Menu 284 is `wavPlaysOnFrameMove`; menu 297 is the byte the C++ calls
//! `automaticFrameAdvanceEnabled`, which only gates these seeks: it mutes the WAV.
//!
//! [`play`] and [`stop`] keep what the output plays ([`playing`]) per thread, with the two menu
//! switches, because the window replaces its [`crate::editor::Editor`] on open. The sound itself
//! goes out only after [`open_device`] (the window calls it; tests never do), and only with the
//! `audio` feature (cpal).

use mds_media::wav::Wave;
use std::cell::RefCell;
use std::ops::Range;
use std::sync::Arc;

/// Timer 100 of `WaveRestartAt` (`SetTimer(hwnd, 0x64, 0x21, 0)`): how long a frame move plays.
pub const FRAME_MOVE_SECONDS: f64 = 0.033;

/// What the output plays: these bytes of the WAV's data chunk ([`Wave::pcm`]).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Play {
    pub bytes: Range<usize>,
}

/// The byte of the data chunk at `seconds`: the offset `WaveSeekAndFeed` seeks to
/// ([`Wave::seek_offset`]) less the chunk's own, within the chunk. A time past the end (the
/// C++ frame move from frame 0 asks for `(u32)-1 / 30` seconds) is the end.
pub fn byte_at(wave: &Wave, seconds: f64) -> usize {
    let len = wave.pcm().len();
    // `seek_offset` truncates to i32 as the C++ does; past that no file is that long.
    if f64::from(wave.format.avg_bytes_per_sec) * seconds >= f64::from(i32::MAX) {
        return len;
    }
    let at = i64::from(wave.seek_offset(seconds)) - i64::from(wave.data.offset);
    at.clamp(0, len as i64) as usize
}

/// The time of a frame move's sound: the frame before `frame`, unsigned as the C++ takes it.
pub fn frame_move_seconds(frame: u32) -> f64 {
    f64::from(frame.wrapping_sub(1)) / 30.0
}

/// The bytes of recorded frame `k` (0 is the first) of a recording at `fps` whose sound starts
/// at byte `start` of the data chunk: whole blocks from `k / fps` to `(k + 1) / fps` seconds
/// after the start, within the chunk.
pub fn frame_bytes(wave: &Wave, start: usize, k: u32, fps: f32) -> Range<usize> {
    let block = u64::from(wave.format.block_align.max(1));
    let rate = f64::from(wave.format.samples_per_sec);
    let at = |k: u32| {
        let blocks = (f64::from(k) * rate / f64::from(fps)) as u64;
        (start as u64 + blocks * block).min(wave.pcm().len() as u64) as usize
    };
    at(k)..at(k + 1)
}

#[derive(Default)]
struct Player {
    on_frame_move: bool,
    muted: bool,
    playing: Option<Play>,
    #[cfg(feature = "audio")]
    out: Option<device::Out>,
}

thread_local! {
    static PLAYER: RefCell<Player> = RefCell::default();
}

/// Menu 284 (`MDS_CMD_TOGGLE_WAVE_ON_FRAME`): a frame move plays the WAV briefly.
pub fn on_frame_move() -> bool {
    PLAYER.with_borrow(|p| p.on_frame_move)
}

pub fn set_on_frame_move(on: bool) {
    PLAYER.with_borrow_mut(|p| p.on_frame_move = on);
}

/// Menu 297 (`MDS_CMD_TOGGLE_WAVE_DISABLED`): the WAV does not play.
pub fn muted() -> bool {
    PLAYER.with_borrow(|p| p.muted)
}

pub fn set_muted(on: bool) {
    PLAYER.with_borrow_mut(|p| p.muted = on);
}

/// What the output was last told to play; `None` after [`stop`].
pub fn playing() -> Option<Play> {
    PLAYER.with_borrow(|p| p.playing.clone())
}

/// Plays `bytes` of `wave`'s data chunk, replacing what played.
pub fn play(wave: &Arc<Wave>, bytes: Range<usize>) {
    PLAYER.with_borrow_mut(|p| {
        #[cfg(feature = "audio")]
        if let Some(out) = &p.out {
            out.feed(Some((wave.clone(), bytes.clone())));
        }
        #[cfg(not(feature = "audio"))]
        let _ = wave;
        p.playing = Some(Play { bytes });
    });
}

/// `CloseDataFile`: nothing plays.
pub fn stop() {
    PLAYER.with_borrow_mut(|p| {
        #[cfg(feature = "audio")]
        if let Some(out) = &p.out {
            out.feed(None);
        }
        p.playing = None;
    });
}

/// Play from `seconds` to the end (play, and the loop restart), unless 297 mutes the WAV.
pub fn play_from(wave: Option<&Arc<Wave>>, seconds: f32) {
    stop();
    if let Some(w) = wave.filter(|_| !muted()) {
        play(w, byte_at(w, f64::from(seconds))..w.pcm().len());
    }
}

/// A frame move to `frame`: with 284 checked and 297 not, the 33 ms from the frame before.
pub fn frame_moved(wave: Option<&Arc<Wave>>, frame: u32) {
    if let Some(w) = wave.filter(|_| on_frame_move() && !muted()) {
        let t = frame_move_seconds(frame);
        play(w, byte_at(w, t)..byte_at(w, t + FRAME_MOVE_SECONDS));
    }
}

/// Opens the system's default output for this thread; the sound of [`play`] goes there from now
/// on. Without the `audio` feature, an error.
pub fn open_device() -> Result<(), String> {
    #[cfg(feature = "audio")]
    {
        let out = device::Out::open()?;
        PLAYER.with_borrow_mut(|p| p.out = Some(out));
        Ok(())
    }
    #[cfg(not(feature = "audio"))]
    Err("built without the audio feature".into())
}

#[cfg(feature = "audio")]
mod device {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
    use cpal::{FromSample, SampleFormat, SizedSample, StreamConfig};
    use mds_media::wav::Wave;
    use std::ops::Range;
    use std::sync::{Arc, Mutex};

    /// What the callback reads: the WAV and the byte range left to play.
    #[derive(Default)]
    struct Feed {
        wave: Option<Arc<Wave>>,
        /// The position in source sample frames (fractional: the device rate differs).
        pos: f64,
        end: f64,
    }

    pub struct Out {
        feed: Arc<Mutex<Feed>>,
        _stream: cpal::Stream,
    }

    impl Out {
        pub fn open() -> Result<Out, String> {
            let device = cpal::default_host()
                .default_output_device()
                .ok_or("no audio output device")?;
            let supported = device.default_output_config().map_err(|e| e.to_string())?;
            let config: StreamConfig = supported.config();
            let feed = Arc::new(Mutex::new(Feed::default()));
            let stream = match supported.sample_format() {
                SampleFormat::F32 => build::<f32>(&device, &config, feed.clone()),
                SampleFormat::I16 => build::<i16>(&device, &config, feed.clone()),
                SampleFormat::U16 => build::<u16>(&device, &config, feed.clone()),
                SampleFormat::I32 => build::<i32>(&device, &config, feed.clone()),
                f => Err(format!("audio output format {f} is not supported")),
            }?;
            stream.play().map_err(|e| e.to_string())?;
            Ok(Out {
                feed,
                _stream: stream,
            })
        }

        pub fn feed(&self, what: Option<(Arc<Wave>, Range<usize>)>) {
            let mut f = self.feed.lock().unwrap_or_else(|e| e.into_inner());
            *f = match what {
                Some((wave, bytes)) => {
                    let block = f64::from(wave.format.block_align.max(1));
                    Feed {
                        pos: bytes.start as f64 / block,
                        end: bytes.end as f64 / block,
                        wave: Some(wave),
                    }
                }
                None => Feed::default(),
            };
        }
    }

    fn build<T: SizedSample + FromSample<f32>>(
        device: &cpal::Device,
        config: &StreamConfig,
        feed: Arc<Mutex<Feed>>,
    ) -> Result<cpal::Stream, String> {
        let (rate, channels) = (config.sample_rate, usize::from(config.channels));
        device
            .build_output_stream(
                *config,
                move |out: &mut [T], _| {
                    let mut f = feed.lock().unwrap_or_else(|e| e.into_inner());
                    for frame in out.chunks_mut(channels) {
                        let v = next(&mut f, rate);
                        for (c, s) in frame.iter_mut().enumerate() {
                            *s = T::from_sample(v[c.min(1)]);
                        }
                    }
                },
                |e| eprintln!("mds-app: audio: {e}"),
                None,
            )
            .map_err(|e| e.to_string())
    }

    /// The next output frame (left, right) at the device's `rate`: the nearest source frame,
    /// silence once the range is played.
    fn next(f: &mut Feed, rate: u32) -> [f32; 2] {
        let Some(w) = &f.wave else {
            return [0.0; 2];
        };
        if f.pos >= f.end {
            return [0.0; 2];
        }
        let fmt = w.format;
        let at = f.pos as usize * usize::from(fmt.block_align);
        let pcm = w.pcm();
        let sample = |c: u16| -> f32 {
            let c = c.min(fmt.channels.saturating_sub(1));
            match fmt.bits_per_sample {
                8 => pcm
                    .get(at + usize::from(c))
                    .map_or(0.0, |&b| (f32::from(b) - 128.0) / 128.0),
                16 => {
                    let i = at + 2 * usize::from(c);
                    pcm.get(i..i + 2).map_or(0.0, |b| {
                        f32::from(i16::from_le_bytes([b[0], b[1]])) / 32768.0
                    })
                }
                _ => 0.0,
            }
        };
        let v = [sample(0), sample(1)];
        f.pos += f64::from(fmt.samples_per_sec) / f64::from(rate);
        v
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A 16-bit stereo WAV at 44100 Hz holding `seconds` of silence.
    fn wave(seconds: u32) -> Arc<Wave> {
        let data = 44100 * 4 * seconds;
        let mut f = b"RIFF".to_vec();
        f.extend((36 + data).to_le_bytes());
        f.extend(b"WAVEfmt ");
        f.extend(16u32.to_le_bytes());
        f.extend(1u16.to_le_bytes());
        f.extend(2u16.to_le_bytes());
        f.extend(44100u32.to_le_bytes());
        f.extend((44100u32 * 4).to_le_bytes());
        f.extend(4u16.to_le_bytes());
        f.extend(16u16.to_le_bytes());
        f.extend(b"data");
        f.extend(data.to_le_bytes());
        f.resize(f.len() + data as usize, 0);
        Arc::new(Wave::from_bytes(f).unwrap())
    }

    #[test]
    fn bytes_follow_the_seek_of_the_cpp() {
        let w = wave(2);
        assert_eq!(w.data.offset, 44);
        // 30 frames is one second: 176400 bytes, a whole number of 4-byte blocks.
        assert_eq!(byte_at(&w, 1.0), 176_400);
        // 1/30 s is 5880 bytes; the frame 7 time rounds down to a block.
        let t = 7.0 / 30.0;
        assert_eq!(byte_at(&w, t), (w.seek_offset(t) - 44) as usize);
        assert_eq!(byte_at(&w, t) % 4, 0);
        assert_eq!(byte_at(&w, 99.0), w.pcm().len());
        assert_eq!(byte_at(&w, frame_move_seconds(0)), w.pcm().len());
        assert_eq!(frame_move_seconds(31), 1.0);
    }

    #[test]
    fn recorded_frames_take_whole_blocks_of_their_time() {
        let w = wave(2);
        // 44100 / 30 = 1470 sample frames per video frame.
        assert_eq!(frame_bytes(&w, 0, 0, 30.0), 0..5880);
        assert_eq!(frame_bytes(&w, 0, 1, 30.0), 5880..11760);
        // At 24 fps a frame is 1837.5 samples: the boundaries truncate, so the sizes alternate.
        let sizes: Vec<usize> = (0..4).map(|k| frame_bytes(&w, 0, k, 24.0).len()).collect();
        assert_eq!(sizes, [1837 * 4, 1838 * 4, 1837 * 4, 1838 * 4]);
        // From a start byte, and never past the chunk.
        assert_eq!(frame_bytes(&w, 176_400, 0, 30.0), 176_400..182_280);
        assert_eq!(frame_bytes(&w, 0, 59, 30.0).end, w.pcm().len());
        assert!(frame_bytes(&w, 0, 60, 30.0).is_empty());
    }

    #[test]
    fn play_mute_and_frame_moves() {
        let w = wave(2);
        play_from(Some(&w), 1.0);
        assert_eq!(playing().unwrap().bytes, 176_400..w.pcm().len());
        stop();
        assert_eq!(playing(), None);
        // 284 off: a frame move is silent.
        frame_moved(Some(&w), 31);
        assert_eq!(playing(), None);
        set_on_frame_move(true);
        frame_moved(Some(&w), 31);
        // 33 ms at 176400 bytes per second, block-aligned: 5821.2 -> 5820.
        assert_eq!(playing().unwrap().bytes, 176_400..176_400 + 5820);
        stop();
        set_muted(true);
        frame_moved(Some(&w), 31);
        play_from(Some(&w), 0.0);
        assert_eq!(playing(), None, "297 mutes both");
        set_muted(false);
        play_from(None, 0.0);
        assert_eq!(playing(), None, "no WAV, nothing plays");
    }
}
