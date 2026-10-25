//! The per-model capture state and the per-frame pose setup:
//! `ModelStandardPoseSetup` of `src/features/dialog_helpers.cpp` (x86
//! `0x4B5760`) and the model fields it keeps (`currentJoints`,
//! `skeletonHistory`, `standardPose`, `lightDir`, the pose trace buffer).

use crate::joints::{self, JointHistory, Joints, TrackedJoint, LOST};
use crate::names;
use crate::pose::{init_standard_pose, Calibration, StandardPose};

/// One sample of the pose trace, `float[77]` (308 bytes) in the C++. A bone
/// writes at the float index given by its slot below: position (3 floats,
/// only the center and the leg IKs) and then `w, x, y, z` of the rotation.
pub type TraceSample = [f32; 77];

/// The trace buffer of the C++ holds 12600 samples (`0x3B3760` bytes). The
/// pump ends the recording when it is full.
pub const TRACE_CAPACITY: usize = 12600;

/// The float index of each bone's group in a [`TraceSample`] (`RegisterKinectPoseCapture`
/// passes these as `slot`).
pub mod slot {
    pub const CENTER: usize = 0;
    pub const UPPER_BODY: usize = 3;
    pub const NECK: usize = 7;
    pub const LEFT_ARM: usize = 11;
    pub const LEFT_ELBOW: usize = 15;
    pub const RIGHT_ARM: usize = 19;
    pub const RIGHT_ELBOW: usize = 23;
    pub const LOWER_BODY: usize = 27;
    pub const LEFT_LEG: usize = 31;
    pub const RIGHT_LEG: usize = 35;
    pub const LEFT_KNEE: usize = 39;
    pub const RIGHT_KNEE: usize = 43;
    pub const LEFT_LEG_IK: usize = 47;
    pub const RIGHT_LEG_IK: usize = 54;
    pub const LEFT_WRIST: usize = 61;
    pub const RIGHT_WRIST: usize = 65;
    pub const LEFT_SHOULDER: usize = 69;
    pub const RIGHT_SHOULDER: usize = 73;
}

/// What the setup reads and writes of a model bone. `translation` and
/// `rotation` are the bone's current pose (`BoneRecord::trans`, `rotQuat`);
/// the leg IK bones keep them when the ankle is lost and are traced as they
/// stand.
#[derive(Clone, Debug)]
pub struct Bone {
    /// The 20-byte PMD name field.
    pub name: [u8; 20],
    /// `position[1]` of the bind pose. `-1` means unset.
    pub bind_y: f32,
    pub translation: [f32; 3],
    /// `[x, y, z, w]`.
    pub rotation: [f32; 4],
}

/// A model IK chain: the bone it hangs on and whether it is on.
#[derive(Clone, Copy, Debug)]
pub struct IkChain {
    pub bone: usize,
    pub enabled: bool,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SetupOptions {
    /// The capture stage is 4 ("recording").
    pub record: bool,
    /// Menu 293, `kinectMirrorEnabled`: the performer faces the viewer like
    /// a mirror, so left is left.
    pub mirror: bool,
    /// Menu 294, `kinectInitLostBone`: reset the bones whose joints are lost.
    pub lost_bone: bool,
}

/// The Kinect state one model carries.
#[derive(Clone, Debug, Default)]
pub struct Capture {
    pub joints: Joints,
    pub history: JointHistory,
    pub pose: StandardPose,
    pub calibration: Calibration,
    /// `openniVersion`: 13, 14 or 15, copied from the app when the capture
    /// stage starts (menu 292).
    pub version: u8,
    tracing: bool,
    trace: Vec<TraceSample>,
}

impl Capture {
    /// A model's state for DxOpenNI `version` (13, 14 or 15).
    pub fn new(version: u8) -> Capture {
        Capture {
            version,
            ..Capture::default()
        }
    }

    /// `ModelInitMorphSlots`: empty history and the default calibration. The
    /// C++ also turns the trace off; the buffer stays (it is freed by the
    /// next recording or by the key registration).
    pub fn reset(&mut self) {
        self.history = JointHistory::default();
        self.calibration = Calibration::default();
        self.tracing = false;
    }

    /// The recorded samples (`PoseTraceBuffer` up to `matMisc`).
    pub fn trace(&self) -> &[TraceSample] {
        &self.trace
    }

    pub fn is_recording(&self) -> bool {
        self.tracing
    }

    /// Frees the trace after its keys are registered.
    pub fn clear_trace(&mut self) {
        self.trace.clear();
    }

    /// Reads the joints from the sensor and smooths them over `fps / 10`
    /// frames (steps 1 and 2 of `PumpKinectSkeleton`).
    pub fn sample(&mut self, fps: i32, get_joint: impl FnMut(i32, &mut [f32; 3])) {
        joints::capture(&mut self.joints, u32::from(self.version), get_joint);
        joints::smooth(&mut self.joints, &mut self.history, fps / 10);
    }

    /// `ModelStandardPoseSetup`: derive the standard pose and write it to
    /// the model's standard bones; while recording, append the resulting
    /// pose as one trace sample. Returns whether a recording just ended.
    pub fn standard_pose_setup(
        &mut self,
        options: SetupOptions,
        bones: &mut [Bone],
        ik: &[IkChain],
    ) -> bool {
        let SetupOptions {
            record,
            mirror,
            lost_bone,
        } = options;
        let mut was_recording = false;
        if !self.tracing && record {
            self.tracing = true;
            self.trace.clear();
        }
        if !record {
            was_recording = self.tracing;
            self.tracing = false;
        }

        // The C++ passes the `record` argument on as the left IK flag and
        // overwrites it only when the model has a left leg IK chain.
        let mut left_ik_add = record;
        let mut right_ik_add = false;
        for chain in ik {
            if let Some(bone) = bones.get(chain.bone) {
                if names::matches(&bone.name, names::LEFT_LEG_IK) {
                    left_ik_add = chain.enabled;
                }
                if names::matches(&bone.name, names::RIGHT_LEG_IK) {
                    right_ik_add = chain.enabled;
                }
            }
        }

        init_standard_pose(
            &mut self.pose,
            &mut self.calibration,
            &self.joints,
            lost_bone,
        );
        self.derive_scale(bones);

        let inv = 1.0 / f64::from(self.calibration.scale);
        let c = &self.calibration;
        let p = &self.pose;
        let joints = &self.joints;
        if self.tracing {
            self.trace.push([0.0; 77]);
        }
        let mut sample = if self.tracing {
            self.trace.last_mut()
        } else {
            None
        };
        let mut put = |at: usize, floats: &[f32]| {
            if let Some(sample) = sample.as_mut() {
                sample[at..at + floats.len()].copy_from_slice(floats);
            }
        };
        // The rotation of a standard bone: its own quaternion when mirroring,
        // else the other side's with y and z negated.
        let flip = |q: [f32; 4]| [q[0], -q[1], -q[2], q[3]];
        let side = |own: [f32; 4], other: [f32; 4]| if mirror { own } else { flip(other) };
        let body = |q: [f32; 4]| if mirror { q } else { flip(q) };
        let identity = [0.0, 0.0, 0.0, 1.0];

        let mut center_pos = [0.0f32; 3];
        for bone in bones.iter_mut() {
            let n = &bone.name;
            let (at, q) = if names::matches(n, names::CENTER) {
                let center = joints[TrackedJoint::Center];
                if center[1] != LOST {
                    bone.translation[0] = (f64::from(center[0]) * inv) as f32;
                    bone.translation[1] = (f64::from(center[1]) * inv) as f32;
                    bone.translation[2] = (inv * f64::from(center[2])) as f32;
                    if !mirror {
                        bone.translation[0] = -bone.translation[0];
                    }
                }
                bone.rotation = identity;
                put(slot::CENTER, &bone.translation);
                center_pos = bone.translation;
                continue;
            } else if names::matches(n, names::UPPER_BODY) {
                (slot::UPPER_BODY, body(p.upper_body))
            } else if names::matches(n, names::NECK) {
                (slot::NECK, body(p.neck))
            } else if names::matches(n, names::LEFT_ARM) {
                (slot::LEFT_ARM, side(p.left_arm, p.right_arm))
            } else if names::matches(n, names::LEFT_ELBOW) {
                (slot::LEFT_ELBOW, side(p.left_elbow, p.right_elbow))
            } else if names::matches(n, names::RIGHT_ARM) {
                (slot::RIGHT_ARM, side(p.right_arm, p.left_arm))
            } else if names::matches(n, names::RIGHT_ELBOW) {
                (slot::RIGHT_ELBOW, side(p.right_elbow, p.left_elbow))
            } else if names::matches(n, names::LOWER_BODY) {
                (slot::LOWER_BODY, body(p.lower_body))
            } else if names::matches(n, names::LEFT_LEG) {
                (slot::LEFT_LEG, side(p.left_leg, p.right_leg))
            } else if names::matches(n, names::RIGHT_LEG) {
                (slot::RIGHT_LEG, side(p.right_leg, p.left_leg))
            } else if names::matches(n, names::LEFT_KNEE) {
                let q = if left_ik_add {
                    identity
                } else {
                    side(p.left_knee, p.right_knee)
                };
                (slot::LEFT_KNEE, q)
            } else if names::matches(n, names::RIGHT_KNEE) {
                let q = if right_ik_add {
                    identity
                } else {
                    side(p.right_knee, p.left_knee)
                };
                (slot::RIGHT_KNEE, q)
            } else if names::matches(n, names::LEFT_WRIST) {
                (slot::LEFT_WRIST, side(p.left_wrist, p.right_wrist))
            } else if names::matches(n, names::RIGHT_WRIST) {
                (slot::RIGHT_WRIST, side(p.right_wrist, p.left_wrist))
            } else if names::matches(n, names::LEFT_SHOULDER) {
                (slot::LEFT_SHOULDER, side(p.left_shoulder, p.right_shoulder))
            } else if names::matches(n, names::RIGHT_SHOULDER) {
                (
                    slot::RIGHT_SHOULDER,
                    side(p.right_shoulder, p.left_shoulder),
                )
            } else if names::matches(n, names::LEFT_LEG_IK)
                || names::matches(n, names::RIGHT_LEG_IK)
            {
                let left_bone = names::matches(n, names::LEFT_LEG_IK);
                // Mirrored, a leg IK follows the ankle on its own side;
                // otherwise the opposite one, with x, y and z mirrored.
                let ankle_left = left_bone == mirror;
                let ankle = joints[if ankle_left {
                    TrackedJoint::LeftAnkle
                } else {
                    TrackedJoint::RightAnkle
                }];
                if ankle[1] != LOST {
                    bone.translation[0] = (inv * f64::from(ankle[0])) as f32;
                    bone.translation[1] = (f64::from(ankle[1]) * inv) as f32;
                    bone.translation[2] = (inv * f64::from(ankle[2])) as f32;
                    bone.translation[1] += c.ankle_offset;
                    bone.translation[0] = if ankle_left {
                        bone.translation[0] - c.leg_ik_x_offset
                    } else {
                        bone.translation[0] + c.leg_ik_x_offset
                    };
                    let foot = if ankle_left {
                        p.left_foot
                    } else {
                        p.right_foot
                    };
                    if !mirror {
                        bone.translation[0] = -bone.translation[0];
                    }
                    bone.rotation = if mirror { foot } else { flip(foot) };
                } else if lost_bone {
                    bone.translation = center_pos;
                }
                let at = if left_bone {
                    slot::LEFT_LEG_IK
                } else {
                    slot::RIGHT_LEG_IK
                };
                put(at, &bone.translation);
                let r = bone.rotation;
                put(at + 3, &[r[3], r[0], r[1], r[2]]);
                continue;
            } else {
                continue;
            };
            bone.rotation = q;
            put(at, &[q[3], q[0], q[1], q[2]]);
        }
        was_recording
    }

    /// The height-scale block of `ModelStandardPoseSetup`: while the scale
    /// still holds its 90 default and a leg length is known, take the scale
    /// from the bind height of 左足 and the offsets from 左足首. The ankle
    /// offset reads the right ankle joint, not the left, as in the C++.
    fn derive_scale(&mut self, bones: &[Bone]) {
        let c = &mut self.calibration;
        if f64::from(c.scale) != 90.0 || f64::from(c.leg_length) == -1.0 {
            return;
        }
        let find = |standard: &[u8]| bones.iter().find(|b| names::matches(&b.name, standard));
        let Some(leg) = find(names::LEFT_LEG) else {
            return;
        };
        if f64::from(leg.bind_y) == -1.0 {
            return;
        }
        let scale = c.leg_length / leg.bind_y;
        let scale_d = f64::from(scale);
        c.scale = scale;
        let offset = -self.joints[TrackedJoint::RightAnkle][1] / scale;
        c.ankle_offset = offset;
        if let Some(ankle) = find(names::LEFT_ANKLE) {
            if f64::from(ankle.bind_y) != -1.0 {
                c.ankle_offset = (f64::from(ankle.bind_y) / scale_d + f64::from(offset)) as f32;
            }
        }
        c.leg_ik_x_offset = (80.0 / scale_d) as f32;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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

    /// The wrist bones are the one thing the C++ oracle cannot cover: its
    /// constant matches no bone name (see `names`).
    #[test]
    fn a_wrist_gets_its_side_and_is_traced_at_slot_61() {
        let mut capture = Capture::new(14);
        capture.pose.left_wrist = [0.1, 0.2, 0.3, 0.9];
        capture.pose.right_wrist = [0.4, 0.5, 0.6, 0.7];
        let mut bones = [bone(names::LEFT_WRIST), bone(names::RIGHT_WRIST)];
        let record = SetupOptions {
            record: true,
            mirror: true,
            lost_bone: false,
        };
        capture.standard_pose_setup(record, &mut bones, &[]);
        assert_eq!(bones[0].rotation, [0.1, 0.2, 0.3, 0.9]);
        assert_eq!(bones[1].rotation, [0.4, 0.5, 0.6, 0.7]);
        assert_eq!(&capture.trace()[0][61..65], &[0.9, 0.1, 0.2, 0.3]);
        assert_eq!(&capture.trace()[0][65..69], &[0.7, 0.4, 0.5, 0.6]);
        // Not mirrored, the left wrist takes the right one with y and z negated.
        capture.standard_pose_setup(
            SetupOptions {
                mirror: false,
                ..record
            },
            &mut bones,
            &[],
        );
        assert_eq!(bones[0].rotation, [0.4, -0.5, -0.6, 0.7]);
    }

    #[test]
    fn recording_starts_a_fresh_trace_and_ends_once() {
        let mut capture = Capture::new(15);
        let mut bones = [bone(names::CENTER)];
        let on = SetupOptions {
            record: true,
            mirror: true,
            lost_bone: false,
        };
        let off = SetupOptions {
            record: false,
            ..on
        };
        assert!(!capture.standard_pose_setup(on, &mut bones, &[]));
        assert!(!capture.standard_pose_setup(on, &mut bones, &[]));
        assert_eq!(capture.trace().len(), 2);
        assert!(capture.standard_pose_setup(off, &mut bones, &[]));
        assert!(!capture.standard_pose_setup(off, &mut bones, &[]));
        assert_eq!(capture.trace().len(), 2);
        assert!(!capture.standard_pose_setup(on, &mut bones, &[]));
        assert_eq!(capture.trace().len(), 1);
    }

    #[test]
    fn reset_restores_the_defaults() {
        let mut capture = Capture::new(15);
        capture.calibration.scale = 3.0;
        capture.history.0[0][0] = 5.0;
        capture.reset();
        assert_eq!(capture.calibration, Calibration::default());
        assert_eq!(capture.history, JointHistory::default());
    }
}
