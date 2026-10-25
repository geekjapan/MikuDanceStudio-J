//! Joints to the standard pose: `BuildLookAtQuaternion` and
//! `InitStandardSkeletonQuats` of `src/features/audio_pose_helpers.cpp`
//! (x86 `0x4A60F0`, `0x4A6520`).
//!
//! Quaternions are `[x, y, z, w]` like D3DX. The calls to the D3DX
//! functions go through `mds-math` and [`crate::d3dx`]; `acosf` is the CRT
//! one of `mds-crtmath`, as in the C++.

use crate::d3dx::{quat_inverse, quat_rotation_axis, vec3_transform};
use crate::joints::{Joints, TrackedJoint, LOST};
use mds_crtmath::acosf;
use mds_math::{Mat4, Quat, Vec3};

const PI: f32 = f32::from_bits(0x40490FD8); // flt_52B738
const DEG35: f32 = f32::from_bits(0x3F1C61A8); // 0x5311A4
const DEG30: f32 = f32::from_bits(0x3F060A90); // 0x53119C
const NEG_0_7: f32 = f32::from_bits(0xBF333333); // 0x531190
const NEG_0_3: f32 = f32::from_bits(0xBE99999A); // 0x531198
const AXIS_Z: [f32; 3] = [0.0, 0.0, 1.0];
const IDENTITY: [f32; 4] = [0.0, 0.0, 0.0, 1.0];

/// `StandardSkeletonPose`: one quaternion per standard bone. The model
/// starts with all of them at identity (`ModelInit`).
#[derive(Clone, Debug, PartialEq)]
pub struct StandardPose {
    pub upper_body: [f32; 4],
    pub neck: [f32; 4],
    pub left_arm: [f32; 4],
    pub left_wrist: [f32; 4],
    pub left_elbow: [f32; 4],
    pub right_arm: [f32; 4],
    pub right_wrist: [f32; 4],
    pub right_elbow: [f32; 4],
    pub lower_body: [f32; 4],
    pub left_leg: [f32; 4],
    pub left_knee: [f32; 4],
    pub left_foot: [f32; 4],
    pub right_leg: [f32; 4],
    pub right_knee: [f32; 4],
    pub right_foot: [f32; 4],
    pub left_shoulder: [f32; 4],
    pub right_shoulder: [f32; 4],
}

impl Default for StandardPose {
    fn default() -> Self {
        StandardPose {
            upper_body: IDENTITY,
            neck: IDENTITY,
            left_arm: IDENTITY,
            left_wrist: IDENTITY,
            left_elbow: IDENTITY,
            right_arm: IDENTITY,
            right_wrist: IDENTITY,
            right_elbow: IDENTITY,
            lower_body: IDENTITY,
            left_leg: IDENTITY,
            left_knee: IDENTITY,
            left_foot: IDENTITY,
            right_leg: IDENTITY,
            right_knee: IDENTITY,
            right_foot: IDENTITY,
            left_shoulder: IDENTITY,
            right_shoulder: IDENTITY,
        }
    }
}

/// The body-size state the C++ keeps in the model's `lightDir` triple and
/// `legIkXOffset` (a name left over from a mis-labeled field).
#[derive(Clone, Debug, PartialEq)]
pub struct Calibration {
    /// `lightDir[0]`: hip-to-ankle length of the performer in sensor units,
    /// `-1` until a leg is seen.
    pub leg_length: f32,
    /// `lightDir[1]`: sensor units per model unit; `90` until derived.
    pub scale: f32,
    /// `lightDir[2]`: vertical offset added to the leg IK targets.
    pub ankle_offset: f32,
    /// `legIkXOffset`: half the stance width in model units.
    pub leg_ik_x_offset: f32,
}

impl Default for Calibration {
    /// `ModelInit` / `ModelInitMorphSlots`. A model reload sets `ankle_offset`
    /// to 11.5 instead (`src/window/ui_model_reload.cpp`).
    fn default() -> Self {
        Calibration {
            leg_length: -1.0,
            scale: 90.0,
            ankle_offset: 10.0,
            leg_ik_x_offset: 1.0,
        }
    }
}

fn mul(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    Quat::multiply(Quat(a), Quat(b)).0
}

fn norm3(v: [f32; 3]) -> [f32; 3] {
    Vec3(v).normalize().0
}

/// `BuildLookAtQuaternion(out, quat, a, b, mode)`: the rotation that turns
/// the segment `a -> b`, seen in the frame of `quat`, to the axis chosen by
/// `mode` (0 and 1 for limbs, 2 and 3 for hips, 4 for the body, 5 for the
/// head direction), with the y component negated.
pub fn look_at(quat: [f32; 4], a: [f32; 3], b: [f32; 3], mode: u8) -> [f32; 4] {
    let m1 = Mat4::rotation_quaternion(Quat(quat_inverse(quat)));
    let m3 = Mat4::multiply(&m1, &Mat4::rotation_y(PI));
    let dir = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let t = vec3_transform(dir, &m3);
    let n = norm3([t[0], if mode == 5 { 0.0 } else { t[1] }, t[2]]);

    let len = (n[2] * n[2] + n[0] * n[0]).sqrt();
    let (c, s) = if mode == 5 {
        (-n[2] / len, n[0] / len)
    } else {
        (n[0] / len, n[2] / len)
    };
    let mut ang = 0.0;
    if mode == 1 {
        let a = acosf(c);
        ang = if s < 0.0 { -a } else { a };
    } else if mode >= 2 {
        let ang0 = acosf(c);
        if s < 0.0 {
            let r = if c < 0.0 { acosf(-s) } else { -acosf(-s) };
            ang = -ang0 - r * len;
        } else {
            let r = if c < 0.0 { acosf(s) } else { -acosf(s) };
            ang = ang0 - r * len;
        }
    }
    let mut yaw = [0.0; 16];
    (yaw[0], yaw[2], yaw[8], yaw[10], yaw[5], yaw[15]) = (c, -s, s, c, 1.0, 1.0);
    let (e1, e2) = if mode != 0 { (-n[1], len) } else { (len, n[1]) };
    let mut pitch = [0.0; 16];
    (pitch[0], pitch[1], pitch[4], pitch[5], pitch[10], pitch[15]) = (e1, -e2, e2, e1, 1.0, 1.0);

    let (yaw, pitch) = (Mat4(yaw), Mat4(pitch));
    let mut r = if mode < 4 {
        Mat4::multiply(&yaw, &pitch)
    } else {
        yaw
    };
    if (1..=3).contains(&mode) {
        r = Mat4::multiply(&r, &Mat4::rotation_y(-ang));
    }
    let mut out = Quat::from_matrix(&r).0;
    out[1] = -out[1];
    out
}

/// The vector between the mid-point of both shoulders and one of them,
/// and the one to the clavicle, as a rotation (`shoulder mid quat` blocks).
fn shoulder_rotation(shoulder: [f32; 3], clavicle: [f32; 3], mid: [f32; 3]) -> [f32; 4] {
    let a = norm3([
        shoulder[0] - mid[0],
        shoulder[1] - mid[1],
        shoulder[2] - mid[2],
    ]);
    let b = norm3([
        clavicle[0] - mid[0],
        clavicle[1] - mid[1],
        clavicle[2] - mid[2],
    ]);
    let c = [
        b[2] * a[1] - b[1] * a[2],
        b[0] * a[2] - b[2] * a[0],
        b[1] * a[0] - b[0] * a[1],
    ];
    let dot = a[1] * b[1] + b[0] * a[0] + a[2] * b[2];
    quat_rotation_axis(norm3(c), acosf(dot))
}

/// The rotation from straight up to the direction `d` (a unit vector) about
/// the cross product with up, as `InitStandardSkeletonQuats` builds it for
/// the upper and the lower body.
fn lean(d: [f32; 3]) -> [f32; 4] {
    let c = [
        d[2] * 1.0 - d[1] * 0.0,
        d[0] * 0.0 - d[2] * 0.0,
        d[1] * 0.0 - d[0] * 1.0,
    ];
    let dot = 1.0 * d[1] + d[0] * 0.0 + 0.0 * d[2];
    quat_rotation_axis(norm3(c), acosf(dot))
}

fn sub(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

/// A foot rotation: the lower-leg chain when the foot points forward or
/// the joint is lost, else the rotation from the foot's direction to the
/// toe-down default.
fn foot(
    joints: &Joints,
    (knee, ankle, toe): (TrackedJoint, TrackedJoint, TrackedJoint),
    (knee_q, leg_q, lower): ([f32; 4], [f32; 4], [f32; 4]),
) -> [f32; 4] {
    let chain = || mul(mul(knee_q, leg_q), lower);
    if joints[toe][1] == LOST || joints[ankle][1] == LOST {
        return chain();
    }
    let [ax, ay, az] = norm3(sub(joints[ankle], joints[knee]));
    let [bx, by, bz] = norm3(sub(joints[toe], joints[ankle]));
    let dot = by * ay + bx * ax + bz * az;
    let straight = joints[toe][2] - joints[ankle][2] > 0.0
        && (joints[toe][0] - joints[ankle][0]).abs() < 75.0
        && dot > 0.5;
    if dot < NEG_0_3 || straight {
        return chain();
    }
    let [ex, ey, ez] = norm3([0.0, NEG_0_7, -1.0]);
    let c = [bz * ey - by * ez, bx * ez - bz * ex, by * ex - bx * ey];
    let dot2 = ey * by + bx * ex + ez * bz;
    quat_rotation_axis(norm3(c), acosf(dot2))
}

/// `InitStandardSkeletonQuats(model, flag)`: derive the standard pose from
/// the smoothed joints. A block whose joints are all seen overwrites its
/// quaternion; otherwise it keeps the old value, except where the C++ resets
/// it to identity (always for the neck and both shoulders, with `lost_bone`
/// for the rest, which is the "initialize lost bone" menu option).
///
/// Also fills `calibration.leg_length` the first time a leg is seen.
pub fn init_standard_pose(
    pose: &mut StandardPose,
    calibration: &mut Calibration,
    joints: &Joints,
    lost_bone: bool,
) {
    use TrackedJoint::*;
    let seen = |list: &[TrackedJoint]| list.iter().all(|&j| joints[j][1] != LOST);
    let j = |t: TrackedJoint| joints[t];

    // Leg length (first complete leg wins; the left branch tests RightKnee,
    // as the C++ does).
    if calibration.leg_length == -1.0 {
        let length = |hip, knee, ankle| {
            let d1 = sub(j(ankle), j(knee));
            let d2 = sub(j(knee), j(hip));
            let len1 = (d1[1] * d1[1] + d1[0] * d1[0] + d1[2] * d1[2]).sqrt();
            let len2 = (d2[0] * d2[0] + d2[1] * d2[1] + d2[2] * d2[2]).sqrt();
            (len1, len2)
        };
        if seen(&[RightKnee, RightAnkle, RightHip]) {
            let (len1, len2) = length(RightHip, RightKnee, RightAnkle);
            calibration.leg_length = len2 + len1;
        } else if seen(&[RightKnee, LeftAnkle, LeftHip]) {
            let (len1, len2) = length(LeftHip, LeftKnee, LeftAnkle);
            calibration.leg_length = len2 + len1;
        }
    }

    // Upper body.
    let mut q150 = [0.0; 4];
    let mut q155 = [0.0; 4];
    if seen(&[Torso, RightShoulder, LeftShoulder, Neck]) {
        let d = norm3(sub(j(Neck), j(Torso)));
        let lean_q = lean(d);
        q150 = look_at(pose.upper_body, j(LeftShoulder), j(RightShoulder), 4);
        pose.upper_body = mul(q150, lean_q);
    } else if lost_bone {
        pose.upper_body = IDENTITY;
    }

    // Neck.
    if seen(&[Center, Head, Neck]) {
        pose.neck = look_at(pose.upper_body, j(Head), j(Neck), 1);
        if joints[HeadDirection][1] != LOST {
            let q = mul(pose.neck, pose.upper_body);
            let head = look_at(q, j(HeadDirection), j(Head), 5);
            pose.neck = mul(head, pose.neck);
        }
    } else {
        pose.neck = IDENTITY;
    }

    let mid = |axis: usize| (j(RightShoulder)[axis] + j(LeftShoulder)[axis]) * 0.5;
    let mid_shoulders = [
        mid(0),
        (j(LeftShoulder)[1] + j(RightShoulder)[1]) * 0.5,
        mid(2),
    ];

    // Right arm chain.
    if seen(&[LeftShoulder, RightClavicle, RightShoulder]) {
        pose.right_shoulder = shoulder_rotation(j(RightShoulder), j(RightClavicle), mid_shoulders);
    } else {
        pose.right_shoulder = IDENTITY;
    }
    if seen(&[RightShoulder, RightElbow, Neck]) {
        let qa = quat_rotation_axis(AXIS_Z, -DEG35);
        q150 = if joints[RightClavicle][1] == LOST {
            look_at(pose.upper_body, j(RightShoulder), j(RightElbow), 0)
        } else {
            let q = mul(pose.right_shoulder, pose.upper_body);
            look_at(q, j(RightClavicle), j(RightElbow), 0)
        };
        pose.right_arm = mul(qa, q150);
    } else if lost_bone {
        pose.right_arm = quat_rotation_axis(AXIS_Z, DEG35);
    }
    if seen(&[RightElbow, RightWrist, RightShoulder]) {
        let t2 = mul(mul(q150, pose.right_shoulder), pose.upper_body);
        q155 = look_at(t2, j(RightElbow), j(RightWrist), 0);
        let e = mul(quat_rotation_axis(AXIS_Z, -DEG30), q155);
        pose.right_elbow = mul(e, quat_rotation_axis(AXIS_Z, DEG30));
    } else if lost_bone {
        pose.right_elbow = IDENTITY;
    }
    if seen(&[RightWrist, RightHand, RightElbow]) {
        if j(RightHand) == j(RightWrist) {
            pose.right_wrist = IDENTITY;
        } else {
            let qb = mul(mul(mul(q155, q150), pose.right_shoulder), pose.upper_body);
            let q159 = look_at(qb, j(RightWrist), j(RightHand), 0);
            let w = mul(quat_rotation_axis(AXIS_Z, -DEG30), q159);
            pose.right_wrist = mul(w, quat_rotation_axis(AXIS_Z, DEG30));
        }
    } else if lost_bone {
        pose.right_wrist = IDENTITY;
    }

    // Left arm chain.
    if seen(&[LeftShoulder, LeftClavicle, RightShoulder]) {
        pose.left_shoulder = shoulder_rotation(j(LeftShoulder), j(LeftClavicle), mid_shoulders);
    } else {
        pose.left_shoulder = IDENTITY;
    }
    if seen(&[LeftShoulder, LeftElbow, Neck]) {
        let qa = quat_rotation_axis(AXIS_Z, DEG35);
        q150 = if joints[LeftClavicle][1] == LOST {
            look_at(pose.upper_body, j(LeftElbow), j(LeftShoulder), 0)
        } else {
            let q = mul(pose.left_shoulder, pose.upper_body);
            look_at(q, j(LeftElbow), j(LeftClavicle), 0)
        };
        pose.left_arm = mul(qa, q150);
    } else if lost_bone {
        pose.left_arm = quat_rotation_axis(AXIS_Z, -DEG35);
    }
    if seen(&[LeftElbow, LeftWrist, LeftShoulder]) {
        let t2 = mul(mul(q150, pose.left_shoulder), pose.upper_body);
        q155 = look_at(t2, j(LeftWrist), j(LeftElbow), 0);
        let e = mul(quat_rotation_axis(AXIS_Z, DEG30), q155);
        pose.left_elbow = mul(e, quat_rotation_axis(AXIS_Z, -DEG30));
    } else if lost_bone {
        pose.left_elbow = IDENTITY;
    }
    if seen(&[LeftWrist, LeftHand, LeftElbow]) {
        if j(LeftHand) == j(LeftWrist) {
            pose.left_wrist = IDENTITY;
        } else {
            let qb = mul(mul(mul(q155, q150), pose.left_shoulder), pose.upper_body);
            let q159 = look_at(qb, j(LeftHand), j(LeftWrist), 0);
            let w = mul(quat_rotation_axis(AXIS_Z, DEG30), q159);
            pose.left_wrist = mul(w, quat_rotation_axis(AXIS_Z, -DEG30));
        }
    } else if lost_bone {
        pose.left_wrist = IDENTITY;
    }

    // Lower body.
    let hip = |axis: usize| (j(LeftHip)[axis] + j(RightHip)[axis]) * 0.5;
    let hip_mid = [hip(0), hip(1), hip(2)];
    if seen(&[Torso, RightHip, LeftHip]) && hip_mid[1] != LOST {
        let lean_q = lean(norm3(sub(j(Torso), hip_mid)));
        let low = look_at(lean_q, j(LeftHip), j(RightHip), 4);
        pose.lower_body = mul(low, lean_q);
    } else if lost_bone {
        pose.lower_body = IDENTITY;
    }

    // Legs.
    let legs = [
        (RightHip, RightKnee, 2, true),
        (LeftHip, LeftKnee, 3, false),
    ];
    for (hip_j, knee_j, mode, right) in legs {
        if seen(&[hip_j, knee_j, Center]) {
            let q = look_at(pose.lower_body, j(hip_j), j(knee_j), mode);
            if right {
                pose.right_leg = q;
            } else {
                pose.left_leg = q;
            }
        } else if lost_bone {
            if right {
                pose.right_leg = IDENTITY;
            } else {
                pose.left_leg = IDENTITY;
            }
        }
    }
    if seen(&[RightKnee, RightAnkle, Center]) {
        let q = mul(pose.right_leg, pose.lower_body);
        pose.right_knee = look_at(q, j(RightKnee), j(RightAnkle), 1);
    } else if lost_bone {
        pose.right_knee = IDENTITY;
    }
    if seen(&[LeftKnee, LeftAnkle, Center]) {
        let q = mul(pose.left_leg, pose.lower_body);
        pose.left_knee = look_at(q, j(LeftKnee), j(LeftAnkle), 1);
    } else if lost_bone {
        pose.left_knee = IDENTITY;
    }

    pose.right_foot = foot(
        joints,
        (RightKnee, RightAnkle, RightFoot),
        (pose.right_knee, pose.right_leg, pose.lower_body),
    );
    pose.left_foot = foot(
        joints,
        (LeftKnee, LeftAnkle, LeftFoot),
        (pose.left_knee, pose.left_leg, pose.lower_body),
    );
}
