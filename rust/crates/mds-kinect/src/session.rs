//! The capture session and the per-frame pump: `OpenNiInit` and
//! `DisableKinect` (`src/app/oni_kinect.cpp`), `PumpKinectSkeleton` and
//! `ManageKinectRecordGate` (`src/app/oni_skeleton_pump.cpp`), without the
//! window, menu and timer calls, which stay with the application.
//!
//! What the application does around this crate:
//! * Menu 291 starts a live capture ([`Session::start`] with no file) or
//!   stops it ([`Session::stop`]); menu 296 and a dropped `.oni` file stop a
//!   running capture and start one with the file. Menu 296 and the drop are
//!   refused with a message while the camera mode is on.
//! * Menu 292 (the record stage): stage 0 to 1, copy [`Session::version`] into
//!   every model's [`Capture::version`], and every [`STAGE_TIMER_MS`] add 1
//!   up to [`STAGE_RECORDING`]; the stage at 4 records.
//! * Menus 293 and 294 toggle [`SetupOptions::mirror`] and
//!   [`SetupOptions::lost_bone`], which start on and off.

use crate::capture::{Bone, Capture, IkChain, SetupOptions, TRACE_CAPACITY};
use crate::register::{register, KeyRegistration};

/// The frame-rate cap while a capture file drives the frame rate.
pub const CAPTURE_FPS_LIMIT: f32 = 30.0;
/// The capture stage in which the pump records.
pub const STAGE_RECORDING: u8 = 4;
/// The interval of the stage timer (`WM_TIMER` 101).
pub const STAGE_TIMER_MS: u32 = 1500;

/// The DxOpenNI.dll version, from `OpenNIGetVersion`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Version {
    V130 = 13,
    V140 = 14,
    V150 = 15,
}

impl Version {
    /// The C++ compares the float with `==`.
    pub fn from_sensor(version: f32) -> Option<Version> {
        match version {
            1.3 => Some(Version::V130),
            1.4 => Some(Version::V140),
            1.5 => Some(Version::V150),
            _ => None,
        }
    }

    /// The code the models keep (`openniVersion`).
    pub fn code(self) -> u8 {
        self as u8
    }
}

/// A running capture: what `OpenNiInit` leaves in the application state.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Session {
    pub version: Version,
    /// A `.oni` file drives the capture (`kinectCaptureActive`).
    pub from_file: bool,
    fps_limit_saved: f32,
}

impl Session {
    /// The state after `OpenNIInit` succeeded, and the frame-rate limit to
    /// set: [`CAPTURE_FPS_LIMIT`] for a file, else `fps_limit` unchanged.
    /// The application also resets the selected model's history when the
    /// camera mode is off ([`Capture::reset`]) and clears the record stage.
    pub fn start(version: Version, from_file: bool, fps_limit: f32) -> (Session, f32) {
        let session = Session {
            version,
            from_file,
            fps_limit_saved: fps_limit,
        };
        (
            session,
            if from_file {
                CAPTURE_FPS_LIMIT
            } else {
                fps_limit
            },
        )
    }

    /// `DisableKinect`: the frame-rate limit to restore. The application also
    /// clears the record stage, unchecks menus 292 and 291, and seeks the
    /// model to the current frame.
    pub fn stop(self) -> f32 {
        self.fps_limit_saved
    }
}

/// What the application knows each frame while a capture runs.
#[derive(Clone, Copy, Debug)]
pub struct PumpInput {
    /// `OpenNIIsTracking`.
    pub tracking: bool,
    /// The camera mode is off (a model is being edited).
    pub model_mode: bool,
    /// `frameStepPlayback`.
    pub frame_step_playback: bool,
    /// `framesPerSecond`, the measured rate; the smoothing window is a tenth.
    pub fps: i32,
    /// The record stage (`autoRepeat`).
    pub stage: u8,
    /// The frame the recording registers from (`currentFrame`).
    pub frame: u32,
    pub mirror: bool,
    pub lost_bone: bool,
}

/// What a pump asks the application to do.
#[derive(Debug, Default, PartialEq)]
pub struct Pump {
    /// The record stage after the pump.
    pub stage: u8,
    /// The trace filled up: uncheck menu 292.
    pub uncheck_record_menu: bool,
    /// A recording ended. The application then runs [`Session::stop`],
    /// inserts these keys into the model's bone key tracks, seeks the model
    /// to the current frame, raises `lastRegisteredFrame` to the model's
    /// `maxFrame`, resets physics, restores the frame-rate limit, and
    /// repaints.
    pub finished: Option<Vec<KeyRegistration>>,
}

impl Capture {
    /// `PumpKinectSkeleton` for the selected model: read and smooth the
    /// joints, set the model's standard bones, and when a recording just
    /// ended, collect its keys. Does nothing unless the sensor tracks a
    /// performer and a model is being edited.
    pub fn pump(
        &mut self,
        input: PumpInput,
        get_joint: impl FnMut(i32, &mut [f32; 3]),
        bones: &mut [Bone],
        ik: &[IkChain],
    ) -> Pump {
        let mut pump = Pump {
            stage: input.stage,
            ..Pump::default()
        };
        if !input.tracking || !input.model_mode || input.frame_step_playback {
            return pump;
        }
        self.sample(input.fps, get_joint);
        if self.trace().len() >= TRACE_CAPACITY {
            pump.uncheck_record_menu = true;
            pump.stage = 0;
        }
        let options = SetupOptions {
            record: pump.stage == STAGE_RECORDING,
            mirror: input.mirror,
            lost_bone: input.lost_bone,
        };
        if self.standard_pose_setup(options, bones, ik) {
            pump.finished = Some(register(self.trace(), self.version, input.frame, bones, ik));
            self.clear_trace();
        }
        pump
    }
}

/// What `ManageKinectRecordGate` asks for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RecordGate {
    /// `OpenNIDrawDepthMap` argument: draw the depth map.
    pub draw_depth_map: bool,
    /// Menu 292 is enabled. When not, it is also unchecked and the record
    /// stage is cleared.
    pub record_menu_enabled: bool,
}

/// `ManageKinectRecordGate`, run each frame after the tracking probe while
/// a capture runs and `frameStepPlayback` is off.
pub fn record_gate(session: &Session, stage: u8, tracking: bool, model_mode: bool) -> RecordGate {
    RecordGate {
        draw_depth_map: session.from_file || stage != 0,
        record_menu_enabled: tracking && model_mode,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::joints::LOST;

    #[test]
    fn version_gate_is_exact() {
        assert_eq!(Version::from_sensor(1.3), Some(Version::V130));
        assert_eq!(Version::from_sensor(1.4).map(Version::code), Some(14));
        assert_eq!(Version::from_sensor(1.5).map(Version::code), Some(15));
        for v in [1.30001, 1.0, 0.0, f32::NAN, 1.6] {
            assert_eq!(Version::from_sensor(v), None);
        }
    }

    #[test]
    fn a_file_caps_the_frame_rate_and_stop_restores_it() {
        let (live, fps) = Session::start(Version::V140, false, 60.0);
        assert_eq!((fps, live.stop()), (60.0, 60.0));
        let (file, fps) = Session::start(Version::V140, true, 60.0);
        assert_eq!((fps, file.stop()), (CAPTURE_FPS_LIMIT, 60.0));
    }

    #[test]
    fn the_gate_asks_for_the_depth_map_unless_idle() {
        let (live, _) = Session::start(Version::V130, false, 60.0);
        let (file, _) = Session::start(Version::V130, true, 60.0);
        assert!(!record_gate(&live, 0, true, true).draw_depth_map);
        assert!(record_gate(&live, 2, true, true).draw_depth_map);
        assert!(record_gate(&file, 0, true, true).draw_depth_map);
        assert!(record_gate(&live, 0, true, true).record_menu_enabled);
        assert!(!record_gate(&live, 0, false, true).record_menu_enabled);
        assert!(!record_gate(&live, 0, true, false).record_menu_enabled);
    }

    fn input(stage: u8) -> PumpInput {
        PumpInput {
            tracking: true,
            model_mode: true,
            frame_step_playback: false,
            fps: 30,
            stage,
            frame: 100,
            mirror: true,
            lost_bone: false,
        }
    }

    fn bone(name: &[u8]) -> Bone {
        let mut n = [0u8; 20];
        n[..name.len()].copy_from_slice(name);
        Bone {
            name: n,
            bind_y: -1.0,
            translation: [0.0; 3],
            rotation: [0.0, 0.0, 0.0, 1.0],
        }
    }

    #[test]
    fn the_pump_idles_when_nothing_is_tracked() {
        let mut capture = Capture::new(15);
        let mut bones = [bone(crate::names::CENTER)];
        for tweak in [
            |i: &mut PumpInput| i.tracking = false,
            |i: &mut PumpInput| i.model_mode = false,
            |i: &mut PumpInput| i.frame_step_playback = true,
        ] {
            let mut i = input(STAGE_RECORDING);
            tweak(&mut i);
            let pump = capture.pump(i, |_, _| panic!("no sensor read"), &mut bones, &[]);
            assert_eq!(
                pump,
                Pump {
                    stage: STAGE_RECORDING,
                    ..Pump::default()
                }
            );
        }
    }

    #[test]
    fn a_recording_runs_and_registers_when_the_stage_drops() {
        let mut capture = Capture::new(13);
        let mut bones = [bone(crate::names::CENTER)];
        let sensor = |id: i32, slot: &mut [f32; 3]| {
            *slot = if id == 0 {
                [10.0, 20.0, 30.0]
            } else {
                [0.0, LOST, 0.0]
            };
        };
        for _ in 0..3 {
            let pump = capture.pump(input(STAGE_RECORDING), sensor, &mut bones, &[]);
            assert!(pump.finished.is_none() && pump.stage == STAGE_RECORDING);
        }
        assert_eq!(capture.trace().len(), 3);
        let pump = capture.pump(input(0), sensor, &mut bones, &[]);
        let keys = pump.finished.expect("the recording ended");
        assert_eq!(keys.len(), 3);
        assert_eq!(
            keys.iter().map(|k| k.frame).collect::<Vec<_>>(),
            [100, 101, 102]
        );
        assert!(keys
            .iter()
            .all(|k| k.bone == 0 && k.rotation == [0.0, 0.0, 0.0, 1.0]));
        assert!(capture.trace().is_empty() && !capture.is_recording());
    }

    #[test]
    fn a_full_trace_ends_the_recording() {
        let mut capture = Capture::new(13);
        let mut bones = [bone(crate::names::CENTER)];
        let sensor = |_: i32, slot: &mut [f32; 3]| *slot = [0.0, 1000.0, 2000.0];
        let mut pump = Pump::default();
        for _ in 0..TRACE_CAPACITY {
            pump = capture.pump(input(STAGE_RECORDING), sensor, &mut bones, &[]);
            assert!(pump.finished.is_none());
        }
        assert_eq!(capture.trace().len(), TRACE_CAPACITY);
        assert!(!pump.uncheck_record_menu);
        // The next frame sees the full trace: the stage drops to 0 and the
        // recording ends in that same frame.
        let pump = capture.pump(input(STAGE_RECORDING), sensor, &mut bones, &[]);
        assert!(pump.uncheck_record_menu && pump.stage == 0);
        assert_eq!(pump.finished.map(|k| k.len()), Some(TRACE_CAPACITY));
    }
}
