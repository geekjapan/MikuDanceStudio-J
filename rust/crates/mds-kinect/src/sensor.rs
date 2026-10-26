//! What a running capture reads from DxOpenNI.dll each frame, behind one
//! trait so the application drives a [`Fake`] the same way as the device:
//! `OpenNIIsTracking`, `OpenNIGetSkeltonJointPosition`, `OpenNIDrawDepthMap`
//! and `OpenNIClean` (`src/app/frame_driver.cpp` 444-458,
//! `src/app/oni_skeleton_pump.cpp`, `src/app/oni_kinect.cpp`
//! `DisableKinect`).

use std::sync::{Arc, Mutex, MutexGuard};

use crate::joints::{JOINT_COUNT, LOST};
use crate::session::Version;

/// A started sensor or `.oni` player.
pub trait Sensor: Send {
    /// `OpenNIGetVersion`, read when the session started.
    fn version(&self) -> Version;
    /// `OpenNIIsTracking`.
    fn is_tracking(&mut self) -> bool;
    /// `OpenNIGetSkeltonJointPosition(id, slot)`.
    fn joint(&mut self, id: i32, slot: &mut [f32; 3]);
    /// `OpenNIDrawDepthMap`.
    fn draw_depth_map(&mut self, draw: bool);
    /// `OpenNIClean`.
    fn stop(self: Box<Self>);
}

#[cfg(all(windows, feature = "dxopenni"))]
impl Sensor for crate::dll::OpenNi {
    fn version(&self) -> Version {
        self.version
    }
    fn is_tracking(&mut self) -> bool {
        crate::dll::OpenNi::is_tracking(self)
    }
    fn joint(&mut self, id: i32, slot: &mut [f32; 3]) {
        crate::dll::OpenNi::joint(self, id, slot)
    }
    fn draw_depth_map(&mut self, draw: bool) {
        crate::dll::OpenNi::draw_depth_map(self, draw)
    }
    fn stop(self: Box<Self>) {
        crate::dll::OpenNi::stop(*self)
    }
}

/// What a [`Fake`] answers and what it was asked, shared with its [`FakeHandle`].
#[derive(Clone, Debug, PartialEq)]
pub struct FakeState {
    pub tracking: bool,
    /// The position of each OpenNI joint id; every id starts lost.
    pub joints: [[f32; 3]; JOINT_COUNT],
    /// The ids read since the last [`FakeHandle::take_reads`].
    pub reads: Vec<i32>,
    /// The last `OpenNIDrawDepthMap` argument.
    pub depth_map: Option<bool>,
    pub stopped: bool,
}

/// A sensor without a device, for tests.
pub struct Fake {
    version: Version,
    handle: FakeHandle,
}

/// The test's side of a [`Fake`].
#[derive(Clone)]
pub struct FakeHandle(Arc<Mutex<FakeState>>);

impl Fake {
    /// A fake that tracks a performer whose every joint is lost.
    pub fn start(version: Version) -> (Box<dyn Sensor>, FakeHandle) {
        let handle = FakeHandle(Arc::new(Mutex::new(FakeState {
            tracking: true,
            joints: [[0.0, LOST, 0.0]; JOINT_COUNT],
            reads: Vec::new(),
            depth_map: None,
            stopped: false,
        })));
        (
            Box::new(Fake {
                version,
                handle: handle.clone(),
            }),
            handle,
        )
    }
}

impl FakeHandle {
    pub fn state(&self) -> MutexGuard<'_, FakeState> {
        self.0.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn take_reads(&self) -> Vec<i32> {
        std::mem::take(&mut self.state().reads)
    }
}

impl Sensor for Fake {
    fn version(&self) -> Version {
        self.version
    }
    fn is_tracking(&mut self) -> bool {
        self.handle.state().tracking
    }
    fn joint(&mut self, id: i32, slot: &mut [f32; 3]) {
        let mut s = self.handle.state();
        s.reads.push(id);
        if let Some(p) = usize::try_from(id).ok().and_then(|i| s.joints.get(i)) {
            *slot = *p;
        }
    }
    fn draw_depth_map(&mut self, draw: bool) {
        self.handle.state().depth_map = Some(draw);
    }
    fn stop(self: Box<Self>) {
        self.handle.state().stopped = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::joints::{self, Joints, TrackedJoint};

    /// `CaptureSkeletonJoints`: ids 0..=17, then 18 and 19 from 1.40, 20..=22 for 1.50.
    #[test]
    fn a_fake_answers_the_ids_each_version_reads() {
        for (version, last) in [
            (Version::V130, 17),
            (Version::V140, 19),
            (Version::V150, 22),
        ] {
            let (mut sensor, handle) = Fake::start(version);
            handle.state().joints[0] = [1.0, 2.0, 3.0];
            let mut j = Joints::default();
            joints::capture(&mut j, u32::from(sensor.version().code()), |id, slot| {
                sensor.joint(id, slot)
            });
            assert_eq!(handle.take_reads(), (0..=last).collect::<Vec<_>>());
            assert_eq!(j[TrackedJoint::Center], [1.0, 2.0, 3.0]);
            assert_eq!(j[TrackedJoint::Neck][1], LOST);
            sensor.draw_depth_map(true);
            assert!(sensor.is_tracking());
            sensor.stop();
            assert!(handle.state().stopped && handle.state().depth_map == Some(true));
        }
    }
}
