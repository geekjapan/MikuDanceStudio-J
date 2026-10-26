//! Play, stop and loop timing, without the physics: the decisions of the playing branch of
//! `PlaybackCatchup` (`src/app/playback_catchup.cpp`, x86 0x46F264 to 0x46F3D1), the play
//! button 408 (`ApplyPlaybackRangeEdits` in `src/window/command_frame_edit.cpp`) and the frame
//! that `StopPlayback` (`src/app/playback_state.cpp`) returns to.
//!
//! The caller steps the pose and the physics up to [`Playback::cursor`] after each pass.

/// `MilliToSec` (`src/main/winmain.cpp`).
const MILLI_TO_SEC: f32 = 0.001;

/// `FrameToSeconds` (`command_frame_edit.cpp`, case 408): the frame as unsigned, in `f64`
/// divided by 30, rounded once to `f32`.
pub fn frame_to_seconds(frame: i32) -> f32 {
    (f64::from(frame as u32) / 30.0) as f32
}

/// The loop restart's start time (`PlayingBeyondEnd`, x64 0x7FF7CB44BC3E): the unsigned frame
/// converted to `f32`, then divided by `30.0f`.
pub fn loop_start_seconds(frame: i32) -> f32 {
    (frame as u32) as f32 / 30.0
}

/// [`Playback::stop_frame`] for a cursor at `cursor` seconds; the end of a recording too
/// (`FinishAviRecord` runs `StopPlayback`, `src/app/late_ports.cpp:63`).
pub fn stop_frame(options: &Options, cursor: f32, current_frame: i32) -> i32 {
    if options.stop_at_playhead {
        (f64::from(cursor) * 30.0) as i32
    } else {
        current_frame
    }
}

/// The check boxes and edits of the play panel, as the PMM stores them (`Timeline`).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Options {
    /// 411, `PlaybackLoopEnabled`.
    pub looped: bool,
    /// Check box 413. The C++ calls the byte `playbackReturnsToStartFrame`, but when it is set the stop
    /// moves the current frame to the playhead, and when it is clear the current frame stays
    /// where play started (`StopPlayback`).
    pub stop_at_playhead: bool,
    /// 414, `PlaybackStartsAtCurrentFrame`.
    pub from_current: bool,
    /// 409, the play start edit.
    pub start_frame: i32,
    /// 410, the play stop edit; 0 means the last registered frame.
    pub stop_frame: i32,
}

impl Options {
    pub fn of(timeline: &mds_formats::pmm::Timeline) -> Options {
        Options {
            looped: timeline.playback_loop != 0,
            stop_at_playhead: timeline.return_to_start != 0,
            from_current: timeline.start_at_current != 0,
            start_frame: timeline.play_start_frame,
            stop_frame: timeline.play_stop_frame,
        }
    }
}

/// A running playback.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Playback {
    /// `PlaybackStartSeconds` (app+0x9E654).
    pub start: f32,
    /// `PlaybackEndSeconds` (app+0x9E658).
    pub end: f32,
    /// `PlaybackCursorSeconds` (app+0x9E64C).
    pub cursor: f32,
    /// The wall-clock anchor T0 in milliseconds (app+0x9EDA8).
    anchor_ms: u64,
}

/// What one pass did.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Pass {
    /// The cursor moved to the target (BLOCK 2).
    Playing,
    /// The target passed the end with loop on: the cursor is back at the start.
    Looped,
    /// The target passed the end with loop off: playback is over.
    Stopped,
}

impl Playback {
    /// The play button while stopped (`ApplyPlaybackRangeEdits`, x86 0x487446).
    pub fn start(
        options: &Options,
        current_frame: i32,
        last_registered_frame: i32,
        now_ms: u64,
    ) -> Playback {
        let start = frame_to_seconds(if options.from_current {
            current_frame
        } else {
            options.start_frame
        });
        let end = if options.stop_frame == 0 {
            last_registered_frame
        } else {
            options.stop_frame
        };
        Playback {
            start,
            end: frame_to_seconds(end),
            cursor: start,
            anchor_ms: now_ms,
        }
    }

    /// `9E654 + (TimeNow - T0) * MilliToSec`, in `f32` (x64 0x7FF7CB44BB86).
    pub fn target(&self, now_ms: u64) -> f32 {
        (now_ms.wrapping_sub(self.anchor_ms) as i64) as f32 * MILLI_TO_SEC + self.start
    }

    /// One pass of the playing branch.
    pub fn pass(&mut self, options: &Options, now_ms: u64) -> Pass {
        let target = self.target(now_ms);
        self.cursor = target;
        // `!(end < target)`: a NaN target plays on (x86 0x46F2A9 jp).
        if self.end.partial_cmp(&target) != Some(std::cmp::Ordering::Less) {
            return Pass::Playing;
        }
        if !options.looped {
            return Pass::Stopped;
        }
        self.start = loop_start_seconds(options.start_frame);
        self.cursor = self.start;
        self.anchor_ms = now_ms;
        Pass::Looped
    }

    /// The current frame after the stop (`StopPlayback`, x86 0x434383): the playhead
    /// `(int)(cursor * 30.0)` with 413 set, else the frame play started from, unchanged.
    pub fn stop_frame(&self, options: &Options, current_frame: i32) -> i32 {
        stop_frame(options, self.cursor, current_frame)
    }

    /// The whole frame the cursor reached: the frame rounding of `PlaybackPoseAdvance`
    /// (`src/app/timeline_advance.cpp`, 0x4175ED, `mds_scene::playback_frame`), then the whole part.
    pub fn frame(&self) -> u32 {
        mds_scene::playback_frame(self.cursor).map_or(0, |f| f as u32)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const OPTIONS: Options = Options {
        looped: false,
        stop_at_playhead: false,
        from_current: false,
        start_frame: 10,
        stop_frame: 40,
    };

    #[test]
    fn frame_seconds_keep_each_precision_of_the_cpp() {
        assert_eq!(frame_to_seconds(30), 1.0);
        // The frame is unsigned in both: fadd 2^32 (x86) / zero-extended cvtsi2ss (x64).
        assert_eq!(frame_to_seconds(-1), (4_294_967_295.0f64 / 30.0) as f32);
        assert_eq!(loop_start_seconds(-1), 4_294_967_296.0f32 / 30.0);
        // Below 2^24 the frame is exact in f32 and the two forms agree.
        assert!((0..100_000).all(|f| frame_to_seconds(f) == loop_start_seconds(f)));
    }

    #[test]
    fn play_starts_at_the_start_edit_or_the_current_frame() {
        let p = Playback::start(&OPTIONS, 25, 99, 1000);
        assert_eq!(
            (p.start, p.cursor, p.end),
            (
                frame_to_seconds(10),
                frame_to_seconds(10),
                frame_to_seconds(40)
            )
        );
        let p = Playback::start(
            &Options {
                from_current: true,
                ..OPTIONS
            },
            25,
            99,
            1000,
        );
        assert_eq!(p.start, frame_to_seconds(25));
        // Stop edit 0: up to the last registered frame.
        let p = Playback::start(
            &Options {
                stop_frame: 0,
                ..OPTIONS
            },
            25,
            99,
            1000,
        );
        assert_eq!(p.end, frame_to_seconds(99));
    }

    #[test]
    fn the_target_is_start_plus_wall_clock() {
        let p = Playback::start(
            &Options {
                start_frame: 30,
                ..OPTIONS
            },
            0,
            0,
            1000,
        );
        assert_eq!(p.target(2500), 1500.0f32 * 0.001 + 1.0);
        assert_eq!(p.target(1000), 1.0);
    }

    #[test]
    fn the_end_frame_itself_still_plays() {
        // end = 40/30 s; the target reaches it exactly at elapsed 1000 ms from frame 10.
        let options = Options {
            start_frame: 10,
            stop_frame: 40,
            ..OPTIONS
        };
        let mut p = Playback::start(&options, 0, 0, 0);
        p.end = p.target(1000);
        assert_eq!(p.pass(&options, 1000), Pass::Playing);
        assert_eq!(p.cursor, p.end);
        assert_eq!(p.pass(&options, 1001), Pass::Stopped);
        assert_eq!(p.cursor, p.target(1001));
    }

    #[test]
    fn loop_restarts_from_the_start_edit_with_a_new_anchor() {
        // Loop reads 409 even when play started at the current frame.
        let options = Options {
            looped: true,
            from_current: true,
            ..OPTIONS
        };
        let mut p = Playback::start(&options, 25, 0, 0);
        assert_eq!(p.pass(&options, 5000), Pass::Looped);
        assert_eq!(
            (p.start, p.cursor),
            (loop_start_seconds(10), loop_start_seconds(10))
        );
        assert_eq!(p.target(5000), loop_start_seconds(10));
        assert_eq!(p.pass(&options, 5100), Pass::Playing);
    }

    #[test]
    fn stop_keeps_the_frame_unless_413_is_set() {
        let mut p = Playback::start(&OPTIONS, 7, 0, 0);
        p.cursor = 2.0999;
        assert_eq!(p.stop_frame(&OPTIONS, 7), 7);
        // (int)(2.0999 * 30.0) truncates 62.997.
        let options = Options {
            stop_at_playhead: true,
            ..OPTIONS
        };
        assert_eq!(p.stop_frame(&options, 7), 62);
    }

    #[test]
    fn the_cursor_frame_rounds_to_a_thousandth_first() {
        let mut p = Playback::start(&OPTIONS, 0, 0, 0);
        // n/30 s in f32 can be a hair under frame n; the 1/1000 rounding makes it n.
        let n = (1..1000)
            .find(|&n| f64::from(n as f32 / 30.0) * 30.0 < f64::from(n))
            .unwrap();
        p.cursor = n as f32 / 30.0;
        assert_eq!(p.frame(), n);
        p.cursor = 0.0;
        assert_eq!(p.frame(), 0);
    }
}
