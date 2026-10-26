//! Kinect / OpenNI capture of the C++ application: `src/app/oni_kinect.cpp`,
//! `src/app/oni_skeleton_pump.cpp`, `include/mikudancestudio/
//! skeleton_tracking.hpp`, and the pose math of
//! `src/features/audio_pose_helpers.cpp` and `src/features/dialog_helpers.cpp`.
//!
//! Everything but the DLL binding is pure and builds on every platform:
//!
//! * [`joints`]: the 23 joints, the 30-sample history and its smoothing.
//! * [`pose`]: the joints to the standard pose (`InitStandardSkeletonQuats`).
//! * [`capture`]: the per-model state and the standard pose written to the
//!   model's bones (`ModelStandardPoseSetup`), with the pose trace.
//! * [`register`]: the bone keys a finished recording registers, as a plain
//!   list for the document layer.
//! * [`session`]: start and stop of a capture, the per-frame pump, and the
//!   constants the application wires to its menus and timers.
//! * [`sensor`]: what a running capture reads each frame, as a trait the
//!   DLL and a [`sensor::Fake`] (for tests without a device) implement.
//! * [`error`]: the load failures with their English and Japanese texts.
//! * `dll` (feature `dxopenni`, Windows only): `Data\DxOpenNI.dll` through
//!   `libloading`. Unverified on hardware: no sensor was available.
//!
//! `tests/pose_oracle.rs` compares [`pose::init_standard_pose`] and
//! [`capture::Capture::standard_pose_setup`] with the real C++ run by
//! `tests/cxx/run.sh`.

pub mod capture;
pub mod d3dx;
#[cfg(all(windows, feature = "dxopenni"))]
pub mod dll;
pub mod error;
pub mod joints;
pub mod names;
pub mod pose;
pub mod register;
pub mod sensor;
pub mod session;

pub use capture::{Bone, Capture, IkChain, SetupOptions, TraceSample};
pub use error::Error;
pub use register::KeyRegistration;
pub use sensor::{Fake, FakeHandle, Sensor};
pub use session::{Pump, PumpInput, Session, Version};
