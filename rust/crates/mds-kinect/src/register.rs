//! The keys a finished recording registers: `RegisterKinectPoseCapture` and
//! `RegisterTraceBoneKey` of `src/app/oni_skeleton_pump.cpp`, minus the undo
//! snapshot and the key-pool bookkeeping, which belong to the key editor.
//!
//! The caller (the document layer) inserts the returned keys into the bone
//! key tracks, starting from the track of the bone, and reports a full pool
//! as the C++ does. After the call it clears the trace
//! ([`crate::Capture::clear_trace`]).

use crate::capture::{slot, Bone, IkChain, TraceSample};
use crate::names;

/// The interpolation bytes of every registered key: four curves of
/// `{x1, y1, x2, y2} = {20, 20, 107, 107}` (`FillTraceKey`).
pub const INTERPOLATION: [u8; 16] = [
    20, 20, 107, 107, 20, 20, 107, 107, 20, 20, 107, 107, 20, 20, 107, 107,
];

/// One bone key: what goes into `BoneKey::{frame, position, rotation}`.
#[derive(Clone, Debug, PartialEq)]
pub struct KeyRegistration {
    /// Index into the `bones` slice passed to [`register`].
    pub bone: usize,
    pub frame: u32,
    pub position: [f32; 3],
    /// `[x, y, z, w]`.
    pub rotation: [f32; 4],
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    /// `mode 0`: position only (the center), rotation identity.
    Position,
    /// `mode 1`: rotation only, position zero.
    Rotation,
    /// `mode 2`: position and rotation (the leg IK bones).
    Both,
}

/// The standard bones in registration order, with the trace slot and mode,
/// for a DxOpenNI `version` (13, 14 or 15) and the two leg IK flags.
fn plan(version: u8, left_ik: bool, right_ik: bool) -> Vec<(&'static [u8], usize, Mode)> {
    use Mode::*;
    let mut plan = vec![
        (names::CENTER, slot::CENTER, Position),
        (names::UPPER_BODY, slot::UPPER_BODY, Rotation),
    ];
    if version >= 14 {
        plan.push((names::NECK, slot::NECK, Rotation));
    }
    plan.extend([
        (names::LEFT_ARM, slot::LEFT_ARM, Rotation),
        (names::LEFT_ELBOW, slot::LEFT_ELBOW, Rotation),
        (names::RIGHT_ARM, slot::RIGHT_ARM, Rotation),
        (names::RIGHT_ELBOW, slot::RIGHT_ELBOW, Rotation),
        (names::LOWER_BODY, slot::LOWER_BODY, Rotation),
        (names::LEFT_LEG, slot::LEFT_LEG, Rotation),
        (names::RIGHT_LEG, slot::RIGHT_LEG, Rotation),
        if left_ik {
            (names::LEFT_LEG_IK, slot::LEFT_LEG_IK, Both)
        } else {
            (names::LEFT_KNEE, slot::LEFT_KNEE, Rotation)
        },
        if right_ik {
            (names::RIGHT_LEG_IK, slot::RIGHT_LEG_IK, Both)
        } else {
            (names::RIGHT_KNEE, slot::RIGHT_KNEE, Rotation)
        },
    ]);
    if version >= 14 {
        plan.push((names::LEFT_WRIST, slot::LEFT_WRIST, Rotation));
        plan.push((names::RIGHT_WRIST, slot::RIGHT_WRIST, Rotation));
    }
    if version >= 15 {
        plan.push((names::LEFT_SHOULDER, slot::LEFT_SHOULDER, Rotation));
        plan.push((names::RIGHT_SHOULDER, slot::RIGHT_SHOULDER, Rotation));
    }
    plan
}

/// The key of one trace sample. The trace stores a rotation as `w, x, y, z`;
/// the key holds `x, y, z, w`.
///
/// `RegisterTraceBoneKey` of the C++ copies the four trace floats as they
/// are and, for the leg IK bones, reads the rotation 16 bytes into the group
/// where it starts at 12. `RegisterPhysicsPoseChain`
/// (`src/features/audio_pose_helpers.cpp`, x86 `0x4A4A50`), the x86 twin of
/// the same original function, swaps them as done here. Which one is right
/// against the original binary is open (see the slice report).
fn key(sample: &TraceSample, at: usize, mode: Mode) -> ([f32; 3], [f32; 4]) {
    let float3 = |i: usize| [sample[i], sample[i + 1], sample[i + 2]];
    match mode {
        Mode::Position => (float3(at), [0.0, 0.0, 0.0, 1.0]),
        Mode::Rotation => (
            [0.0; 3],
            [sample[at + 1], sample[at + 2], sample[at + 3], sample[at]],
        ),
        Mode::Both => (
            float3(at),
            [
                sample[at + 4],
                sample[at + 5],
                sample[at + 6],
                sample[at + 3],
            ],
        ),
    }
}

/// `RegisterKinectPoseCapture`: the keys for the standard bones the model
/// has, one run of `trace.len()` frames per bone starting at `frame`.
///
/// A bone is found by the first name match; a leg IK counts as on when the
/// last IK chain hung on a bone of that name is enabled, and then replaces
/// the knee.
pub fn register(
    trace: &[TraceSample],
    version: u8,
    frame: u32,
    bones: &[Bone],
    ik: &[IkChain],
) -> Vec<KeyRegistration> {
    let (mut left_ik, mut right_ik) = (false, false);
    for chain in ik {
        if let Some(bone) = bones.get(chain.bone) {
            if names::matches(&bone.name, names::LEFT_LEG_IK) {
                left_ik = chain.enabled;
            }
            if names::matches(&bone.name, names::RIGHT_LEG_IK) {
                right_ik = chain.enabled;
            }
        }
    }
    let mut keys = Vec::new();
    for (name, at, mode) in plan(version, left_ik, right_ik) {
        let Some(index) = bones.iter().position(|b| names::matches(&b.name, name)) else {
            continue;
        };
        for (k, sample) in trace.iter().enumerate() {
            let (position, rotation) = key(sample, at, mode);
            keys.push(KeyRegistration {
                bone: index,
                frame: frame + k as u32,
                position,
                rotation,
            });
        }
    }
    keys
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

    fn all_bones() -> Vec<Bone> {
        [
            names::CENTER,
            names::UPPER_BODY,
            names::NECK,
            names::LEFT_ARM,
            names::LEFT_ELBOW,
            names::RIGHT_ARM,
            names::RIGHT_ELBOW,
            names::LOWER_BODY,
            names::LEFT_LEG,
            names::RIGHT_LEG,
            names::LEFT_KNEE,
            names::RIGHT_KNEE,
            names::LEFT_LEG_IK,
            names::RIGHT_LEG_IK,
            names::LEFT_WRIST,
            names::RIGHT_WRIST,
            names::LEFT_SHOULDER,
            names::RIGHT_SHOULDER,
        ]
        .into_iter()
        .map(bone)
        .collect()
    }

    fn sample(seed: f32) -> TraceSample {
        std::array::from_fn(|i| seed + i as f32)
    }

    fn registered(version: u8, ik: &[IkChain]) -> Vec<usize> {
        let keys = register(&[sample(0.0)], version, 7, &all_bones(), ik);
        keys.iter().map(|k| k.bone).collect()
    }

    #[test]
    fn the_bone_list_grows_with_the_dll_version() {
        let ik = [
            IkChain {
                bone: 12,
                enabled: true,
            },
            IkChain {
                bone: 13,
                enabled: false,
            },
        ];
        // center upper | neck | larm lelbow rarm relbow lower lleg rleg |
        // left ik, right knee | wrists | shoulders
        let v13 = [0, 1, 3, 4, 5, 6, 7, 8, 9, 12, 11];
        assert_eq!(registered(13, &ik), v13);
        let v14: Vec<usize> = [&v13[..2], &[2], &v13[2..], &[14, 15]].concat();
        assert_eq!(registered(14, &ik), v14);
        let v15 = [&v14[..], &[16, 17]].concat();
        assert_eq!(registered(15, &ik), v15);
    }

    #[test]
    fn a_leg_ik_replaces_its_knee_only_when_enabled() {
        let knees = |l, r| {
            let ik = [
                IkChain {
                    bone: 12,
                    enabled: l,
                },
                IkChain {
                    bone: 13,
                    enabled: r,
                },
            ];
            let got = registered(13, &ik);
            (
                got.contains(&10) as u8,
                got.contains(&11) as u8,
                got.contains(&12) as u8,
                got.contains(&13) as u8,
            )
        };
        assert_eq!(knees(false, false), (1, 1, 0, 0));
        assert_eq!(knees(true, false), (0, 1, 1, 0));
        assert_eq!(knees(false, true), (1, 0, 0, 1));
        assert_eq!(knees(true, true), (0, 0, 1, 1));
        // The last chain on a bone name wins.
        let ik = [
            IkChain {
                bone: 12,
                enabled: true,
            },
            IkChain {
                bone: 12,
                enabled: false,
            },
        ];
        assert!(!registered(13, &ik).contains(&12));
    }

    #[test]
    fn a_missing_bone_is_skipped_and_frames_count_up() {
        let bones: Vec<Bone> = [names::CENTER, names::LEFT_ARM]
            .into_iter()
            .map(bone)
            .collect();
        let trace = [sample(0.0), sample(100.0), sample(200.0)];
        let keys = register(&trace, 15, 40, &bones, &[]);
        let at: Vec<(usize, u32)> = keys.iter().map(|k| (k.bone, k.frame)).collect();
        assert_eq!(at, [(0, 40), (0, 41), (0, 42), (1, 40), (1, 41), (1, 42)]);
        assert!(register(&[], 15, 40, &bones, &[]).is_empty());
    }

    #[test]
    fn a_key_takes_its_values_from_the_trace_group() {
        let bones = all_bones();
        let s = sample(0.0);
        let ik = [IkChain {
            bone: 12,
            enabled: true,
        }];
        let keys = register(&[s], 13, 0, &bones, &ik);
        let by_bone = |b: usize| keys.iter().find(|k| k.bone == b).unwrap();
        // Position only: the center's xyz, rotation identity.
        assert_eq!(by_bone(0).position, [0.0, 1.0, 2.0]);
        assert_eq!(by_bone(0).rotation, [0.0, 0.0, 0.0, 1.0]);
        // Rotation only: w, x, y, z at slot 3 become x, y, z, w.
        assert_eq!(by_bone(1).position, [0.0; 3]);
        assert_eq!(by_bone(1).rotation, [4.0, 5.0, 6.0, 3.0]);
        // Both: xyz at slot 47, then w, x, y, z.
        assert_eq!(by_bone(12).position, [47.0, 48.0, 49.0]);
        assert_eq!(by_bone(12).rotation, [51.0, 52.0, 53.0, 50.0]);
    }

    #[test]
    fn the_interpolation_bytes_are_the_cpp_ones() {
        assert_eq!(&INTERPOLATION[..4], &[20, 20, 107, 107]);
        assert!(INTERPOLATION.chunks(4).all(|c| c == [20, 20, 107, 107]));
    }
}
