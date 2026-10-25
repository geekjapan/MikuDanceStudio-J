//! Runs the cases of `fixtures/pose_cases.txt` through the Rust pose chain
//! and compares every frame with `fixtures/pose_expected.txt`, which
//! `cxx/run.sh` wrote from the real C++ (`ModelStandardPoseSetup`,
//! `InitStandardSkeletonQuats`, `ModelVertexHistoryPush`). Float words are
//! the bit patterns. The format is documented in `cxx/harness.cpp`.

use std::fmt::Write;
use std::fs;
use std::path::Path;

use mds_kinect::joints::JOINT_COUNT;
use mds_kinect::names;
use mds_kinect::{Bone, Capture, IkChain, SetupOptions};

fn float(hex: &str) -> f32 {
    f32::from_bits(u32::from_str_radix(hex, 16).expect("hex float"))
}

fn bone_name(key: &str) -> Vec<u8> {
    let standard: &[u8] = match key {
        "center" => names::CENTER,
        "upper" => names::UPPER_BODY,
        "neck" => names::NECK,
        "larm" => names::LEFT_ARM,
        "lelbow" => names::LEFT_ELBOW,
        "rarm" => names::RIGHT_ARM,
        "relbow" => names::RIGHT_ELBOW,
        "lower" => names::LOWER_BODY,
        "lleg" => names::LEFT_LEG,
        "rleg" => names::RIGHT_LEG,
        "lknee" => names::LEFT_KNEE,
        "rknee" => names::RIGHT_KNEE,
        "lik" => names::LEFT_LEG_IK,
        "rik" => names::RIGHT_LEG_IK,
        "lshoulder" => names::LEFT_SHOULDER,
        "rshoulder" => names::RIGHT_SHOULDER,
        "lankle" => names::LEFT_ANKLE,
        "other" => b"other\0",
        _ => panic!("bone key {key}"),
    };
    standard.to_vec()
}

fn words(out: &mut String, floats: &[f32]) {
    for f in floats {
        write!(out, " {:08x}", f.to_bits()).unwrap();
    }
}

#[derive(Default)]
struct Frame {
    record: bool,
    joints: [[f32; 3]; JOINT_COUNT],
}

#[derive(Default)]
struct Case {
    name: String,
    version: u8,
    fps: i32,
    mirror: bool,
    lost: bool,
    bones: Vec<(String, Bone)>,
    ik: Vec<(String, bool)>,
    frames: Vec<Frame>,
}

fn run(case: &Case, out: &mut String) {
    let mut bones: Vec<Bone> = case.bones.iter().map(|(_, b)| b.clone()).collect();
    let ik: Vec<IkChain> = case
        .ik
        .iter()
        .map(|(key, enabled)| IkChain {
            bone: case.bones.iter().position(|(k, _)| k == key).unwrap(),
            enabled: *enabled,
        })
        .collect();
    let mut capture = Capture::new(case.version);
    writeln!(out, "case {}", case.name).unwrap();
    for (index, frame) in case.frames.iter().enumerate() {
        capture.sample(case.fps, |id, slot| *slot = frame.joints[id as usize]);
        let options = SetupOptions {
            record: frame.record,
            mirror: case.mirror,
            lost_bone: case.lost,
        };
        let ended = capture.standard_pose_setup(options, &mut bones, &ik);
        writeln!(out, "frame {index} ended {}", u8::from(ended)).unwrap();
        out.push_str("joints");
        words(out, &capture.joints.0.concat());
        out.push_str("\npose");
        let p = &capture.pose;
        for q in [
            p.upper_body,
            p.neck,
            p.left_arm,
            p.left_wrist,
            p.left_elbow,
            p.right_arm,
            p.right_wrist,
            p.right_elbow,
            p.lower_body,
            p.left_leg,
            p.left_knee,
            p.left_foot,
            p.right_leg,
            p.right_knee,
            p.right_foot,
            p.left_shoulder,
            p.right_shoulder,
        ] {
            words(out, &q);
        }
        let c = &capture.calibration;
        out.push_str("\ncal");
        words(
            out,
            &[c.leg_length, c.scale, c.ankle_offset, c.leg_ik_x_offset],
        );
        out.push('\n');
        for (i, b) in bones.iter().enumerate() {
            write!(out, "b {i}").unwrap();
            words(out, &b.translation);
            words(out, &b.rotation);
            out.push('\n');
        }
        let trace = capture.trace();
        writeln!(out, "trace {}", trace.len()).unwrap();
        if capture.is_recording() {
            if let Some(last) = trace.last() {
                out.push('t');
                words(out, last);
                out.push('\n');
            }
        }
    }
    out.push_str("end\n");
}

fn parse(text: &str) -> Vec<Case> {
    let mut cases = Vec::new();
    let mut case = Case::default();
    for line in text
        .lines()
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
    {
        let w: Vec<&str> = line.split_whitespace().collect();
        match w[0] {
            "case" => {
                case = Case {
                    name: w[1].into(),
                    ..Case::default()
                }
            }
            "config" => {
                case.version = w[1].parse().unwrap();
                case.fps = w[2].parse().unwrap();
                case.mirror = w[3] != "0";
                case.lost = w[4] != "0";
            }
            "bone" => {
                let mut name = [0u8; 20];
                let standard = bone_name(w[1]);
                name[..standard.len()].copy_from_slice(&standard);
                let f: Vec<f32> = w[2..].iter().map(|h| float(h)).collect();
                let bone = Bone {
                    name,
                    bind_y: f[0],
                    translation: [f[1], f[2], f[3]],
                    rotation: [f[4], f[5], f[6], f[7]],
                };
                case.bones.push((w[1].into(), bone));
            }
            "ik" => case.ik.push((w[1].into(), w[2] != "0")),
            "frame" => case.frames.push(Frame {
                record: w[1] != "0",
                ..Frame::default()
            }),
            "j" => {
                let id: usize = w[1].parse().unwrap();
                case.frames.last_mut().unwrap().joints[id] =
                    [float(w[2]), float(w[3]), float(w[4])];
            }
            "end" => cases.push(std::mem::take(&mut case)),
            other => panic!("unknown line {other}"),
        }
    }
    cases
}

#[test]
fn matches_the_cpp_bit_for_bit() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let (Ok(cases), Ok(expected)) = (
        fs::read_to_string(dir.join("pose_cases.txt")),
        fs::read_to_string(dir.join("pose_expected.txt")),
    ) else {
        println!("SKIP: tests/fixtures/pose_cases.txt or pose_expected.txt is missing");
        return;
    };
    let cases = parse(&cases);
    assert!(cases.len() >= 20, "{} cases", cases.len());
    let mut actual = String::new();
    for case in &cases {
        run(case, &mut actual);
    }
    let mut current = String::new();
    let mut frames = 0;
    let mut lines = expected.lines();
    for (n, got) in actual.lines().enumerate() {
        let want = lines.next().unwrap_or("<end of file>");
        if let Some(name) = got.strip_prefix("case ") {
            current = name.into();
        }
        if got.starts_with("frame ") {
            frames += 1;
        }
        if got != want {
            let at = got
                .split(' ')
                .zip(want.split(' '))
                .position(|(a, b)| a != b);
            panic!(
                "case {current}, line {}: first differing word {at:?}\n rust: {got}\n  c++: {want}",
                n + 1
            );
        }
    }
    assert_eq!(lines.next(), None, "the C++ dump is longer");
    println!("{} cases, {frames} frames identical", cases.len());
}
