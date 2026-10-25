//! The 23 tracked joints and their history, from `include/mikudancestudio/
//! skeleton_tracking.hpp` (`TrackedJoint`, `PushSkeletonJointHistory`,
//! `CaptureSkeletonJoints`) and `src/features/dialog_helpers.cpp`
//! (`ModelVertexHistoryPush`, `ModelInitMorphSlots`).

use std::ops::{Index, IndexMut};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(usize)]
pub enum TrackedJoint {
    Center,
    Torso,
    Neck,
    Head,
    RightShoulder,
    RightElbow,
    RightWrist,
    RightHand,
    LeftShoulder,
    LeftElbow,
    LeftWrist,
    LeftHand,
    RightHip,
    RightKnee,
    RightAnkle,
    RightFoot,
    LeftHip,
    LeftKnee,
    LeftAnkle,
    LeftFoot,
    RightClavicle,
    LeftClavicle,
    HeadDirection,
}

pub const JOINT_COUNT: usize = 23;
/// `kSkeletonHistoryLength`.
pub const HISTORY_LENGTH: usize = 30;
/// The y value of a joint the sensor does not see.
pub const LOST: f32 = -999.0;

/// `SkeletonJoints`: one `[x, y, z]` per joint. A lost joint has `y == LOST`.
#[derive(Clone, Debug, PartialEq)]
pub struct Joints(pub [[f32; 3]; JOINT_COUNT]);

impl Default for Joints {
    /// `ModelInit`: only y is set to the lost marker.
    fn default() -> Self {
        Joints([[0.0, LOST, 0.0]; JOINT_COUNT])
    }
}

impl Index<TrackedJoint> for Joints {
    type Output = [f32; 3];
    fn index(&self, joint: TrackedJoint) -> &[f32; 3] {
        &self.0[joint as usize]
    }
}

impl IndexMut<TrackedJoint> for Joints {
    fn index_mut(&mut self, joint: TrackedJoint) -> &mut [f32; 3] {
        &mut self.0[joint as usize]
    }
}

/// `SkeletonHistory`: per joint, 30 samples of `[x, y, z]` laid out flat.
#[derive(Clone, Debug, PartialEq)]
pub struct JointHistory(pub [[f32; HISTORY_LENGTH * 3]; JOINT_COUNT]);

impl Default for JointHistory {
    /// `ModelInitMorphSlots`: every sample is `(0, LOST, 0)`.
    fn default() -> Self {
        let mut joint = [0.0; HISTORY_LENGTH * 3];
        for sample in joint.chunks_exact_mut(3) {
            sample[1] = LOST;
        }
        JointHistory([joint; JOINT_COUNT])
    }
}

/// `PushSkeletonJointHistory`: shift the first `count` samples of `history`
/// one slot toward index 0, append `current`, and replace `current` with the
/// mean of the samples whose y is not `LOST`. The sums add in `f32`; the
/// reciprocal of the sample count and the products go through `f64`.
/// A `count` outside `1..=30` changes nothing.
pub fn push_history(current: &mut [f32; 3], history: &mut [f32; HISTORY_LENGTH * 3], count: i32) {
    if count <= 0 || count > HISTORY_LENGTH as i32 {
        return;
    }
    let count = count as usize;
    history.copy_within(3..3 * count, 0);
    history[3 * (count - 1)..3 * count].copy_from_slice(current);
    let mut sums = [0.0f32; 3];
    let mut used = 0u32;
    for entry in history[..3 * count].chunks_exact(3) {
        if entry[1] == LOST {
            continue;
        }
        used += 1;
        for (sum, value) in sums.iter_mut().zip(entry) {
            *sum += value;
        }
    }
    if used != 0 {
        let inverse = 1.0 / f64::from(used);
        for (value, sum) in current.iter_mut().zip(sums) {
            *value = (inverse * f64::from(sum)) as f32;
        }
    }
}

/// `ModelVertexHistoryPush`: smooth every joint over `samples` frames
/// (clamped to 30). `samples <= 0` changes nothing.
pub fn smooth(joints: &mut Joints, history: &mut JointHistory, samples: i32) {
    if samples <= 0 {
        return;
    }
    let count = samples.min(HISTORY_LENGTH as i32);
    for (current, history) in joints.0.iter_mut().zip(history.0.iter_mut()) {
        push_history(current, history, count);
    }
}

/// `CaptureSkeletonJoints`: the OpenNI joint ids 0..=17 always, 18 and 19
/// for DxOpenNI 1.40 and 1.50 (`version` 14 and 15), 20..=22 for 1.50.
/// `get_joint(id, slot)` fills `slot`, like `OpenNIGetSkeltonJointPosition`.
pub fn capture(joints: &mut Joints, version: u32, mut get_joint: impl FnMut(i32, &mut [f32; 3])) {
    use TrackedJoint::*;
    const INITIAL: [TrackedJoint; 18] = [
        Center,
        Neck,
        Head,
        RightShoulder,
        RightElbow,
        RightWrist,
        LeftShoulder,
        LeftElbow,
        LeftWrist,
        RightHip,
        RightKnee,
        RightAnkle,
        LeftHip,
        LeftKnee,
        LeftAnkle,
        Torso,
        RightHand,
        LeftHand,
    ];
    for (id, joint) in INITIAL.into_iter().enumerate() {
        get_joint(id as i32, &mut joints[joint]);
    }
    if version == 14 || version == 15 {
        get_joint(18, &mut joints[RightFoot]);
        get_joint(19, &mut joints[LeftFoot]);
    }
    if version == 15 {
        get_joint(20, &mut joints[RightClavicle]);
        get_joint(21, &mut joints[LeftClavicle]);
        get_joint(22, &mut joints[HeadDirection]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn history_of(samples: &[[f32; 3]]) -> [f32; HISTORY_LENGTH * 3] {
        let mut h = JointHistory::default().0[0];
        for (i, s) in samples.iter().enumerate() {
            h[3 * i..3 * i + 3].copy_from_slice(s);
        }
        h
    }

    #[test]
    fn push_averages_the_window_and_shifts() {
        let mut h = history_of(&[[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]);
        let mut cur = [5.0, 6.0, 7.0];
        push_history(&mut cur, &mut h, 3);
        // The window is (3,4,5), a lost sample, and the new (5,6,7).
        assert_eq!(&h[..9], &[3.0, 4.0, 5.0, 0.0, LOST, 0.0, 5.0, 6.0, 7.0]);
        assert_eq!(cur, [4.0, 5.0, 6.0]);
    }

    #[test]
    fn push_skips_lost_samples_and_keeps_a_lost_current() {
        let mut h = JointHistory::default().0[0];
        let mut cur = [9.0, LOST, 9.0];
        push_history(&mut cur, &mut h, 4);
        assert_eq!(cur, [9.0, LOST, 9.0]);
        assert_eq!(&h[9..12], &[9.0, LOST, 9.0]);
    }

    #[test]
    fn push_ignores_a_bad_count() {
        for count in [0, -1, 31] {
            let mut h = history_of(&[[1.0, 1.0, 1.0]]);
            let before = h;
            let mut cur = [2.0, 2.0, 2.0];
            push_history(&mut cur, &mut h, count);
            assert_eq!((h, cur), (before, [2.0, 2.0, 2.0]));
        }
    }

    #[test]
    fn push_divides_through_f64() {
        // Three samples of 0.1: the f32 sum is 0.3 (rounded), the mean goes
        // through 1/3 in f64, which differs from an f32 division.
        let mut h = JointHistory::default().0[0];
        let mut cur = [0.0; 3];
        for _ in 0..3 {
            cur = [0.1, 0.1, 0.1];
            push_history(&mut cur, &mut h, 3);
        }
        let sum = 0.1f32 + 0.1 + 0.1;
        assert_eq!(cur[0], ((1.0 / 3.0) * f64::from(sum)) as f32);
    }

    #[test]
    fn smooth_clamps_to_thirty_and_skips_nonpositive() {
        let mut joints = Joints::default();
        let mut history = JointHistory::default();
        smooth(&mut joints, &mut history, 0);
        assert_eq!(history, JointHistory::default());
        joints.0[0] = [1.0, 2.0, 3.0];
        smooth(&mut joints, &mut history, 99);
        assert_eq!(&history.0[0][3 * 29..], &[1.0, 2.0, 3.0]);
    }

    #[test]
    fn capture_maps_openni_ids_by_version() {
        for (version, ids) in [(13, 18), (14, 20), (15, 23)] {
            let mut joints = Joints::default();
            let mut seen = Vec::new();
            capture(&mut joints, version, |id, slot| {
                seen.push(id);
                *slot = [id as f32, 0.0, 0.0];
            });
            assert_eq!(seen, (0..ids).collect::<Vec<_>>(), "version {version}");
            let lost = joints.0.iter().filter(|j| j[1] == LOST).count();
            assert_eq!(lost, JOINT_COUNT - ids as usize, "version {version}");
        }
        let mut joints = Joints::default();
        capture(&mut joints, 15, |id, slot| *slot = [id as f32, 0.0, 0.0]);
        use TrackedJoint::*;
        let x = |j| joints[j][0] as i32;
        assert_eq!(
            [
                x(Center),
                x(Neck),
                x(Head),
                x(RightShoulder),
                x(LeftShoulder),
                x(RightHip),
                x(LeftHip),
                x(Torso),
                x(RightHand),
                x(LeftHand),
                x(RightFoot),
                x(LeftFoot),
                x(RightClavicle),
                x(LeftClavicle),
                x(HeadDirection)
            ],
            [0, 1, 2, 3, 6, 9, 12, 15, 16, 17, 18, 19, 20, 21, 22]
        );
    }

    #[test]
    fn joint_enum_matches_the_array_size() {
        assert_eq!(TrackedJoint::HeadDirection as usize + 1, JOINT_COUNT);
    }
}
