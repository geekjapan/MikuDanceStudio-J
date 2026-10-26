//! Source-derived camera expectations from `PostModelReload` and its callers.

use mds_doc::{Command, Document, ModelFile};
use mds_math::Mat4;
use mds_pose::model::Model;
use std::path::PathBuf;

fn fixture(name: &str) -> Vec<u8> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    std::fs::read(dir.join(name)).unwrap()
}

fn doc() -> Document {
    let mut d = Document::startup();
    for _ in 0..3 {
        d.apply(Command::LoadModel {
            path: "chain8.pmx".into(),
            data: fixture("chain8.pmx"),
        })
        .unwrap();
    }
    for (i, m) in d.pmm.models.iter_mut().enumerate() {
        m.bone_pose[0].translation = [3.0 + i as f32, -2.0, 5.0];
        m.bone_pose[0].rotation = [0.0, 0.0, 0.6, 0.8];
        m.selection.selected_bone = 2;
    }
    d
}

fn pose(d: &Document, slot: usize) -> Model {
    let ModelFile::Pmx(p) = &d.models[slot] else {
        panic!("PMX")
    };
    let mut p = Model::from_pmx(slot as u8, p).unwrap();
    p.apply_pmm(&d.pmm.models[slot]).unwrap();
    mds_pose::pose::apply_morphs(&mut p);
    mds_pose::pose::set_physics_mode(
        &mut p,
        0,
        &mds_pose::pose::Others { models: [&[], &[]] },
        i32::from(d.pmm.physics.playback_mode),
    );
    p
}

fn configure(d: &mut Document, parent: bool, reference: u8, follow: bool) {
    d.pmm.settings.options[0] = 1;
    d.pmm.timeline.camera_reference_mode = reference;
    d.pmm.appearance.follow_camera = u8::from(follow);
    d.pmm.appearance.camera_parent_model = if parent { 0 } else { -1 };
    d.pmm.appearance.camera_parent_bone = 2;
    d.pmm.appearance.suppress_camera_transform = 1;
    d.pmm.camera_state = [11.0, 13.0, 17.0, 19.0, 23.0, -29.0, 0.2, -0.4, 0.3];
    let k = &mut d.pmm.camera.heads_mut()[0];
    k.eye = [31.0, 37.0, 41.0];
    k.target = [0.1, -0.3, 0.5];
    k.distance = -43.0;
    k.parent_model = if parent { 0 } else { -1 };
    k.parent_bone = 2;
}

fn close(got: &[f32], want: &[f32]) -> bool {
    got.iter().zip(want).all(|(a, b)| (a - b).abs() < 0.00005)
}

fn transform(m: &Mat4, p: [f32; 3]) -> [f32; 3] {
    std::array::from_fn(|c| {
        (f64::from(m.0[12 + c])
            + (0..3)
                .map(|a| f64::from(p[a]) * f64::from(m.0[a * 4 + c]))
                .sum::<f64>()) as f32
    })
}

fn native_expected(d: &Document, selected: usize, s: [f32; 9]) -> Option<([f32; 3], Mat4)> {
    use std::fmt::Write;
    use std::io::Write as _;
    use std::process::{Command as Process, Stdio};
    let exe = std::env::var_os("MDS_CAMERA_RELOAD_ORACLE")?;
    let a = &d.pmm.appearance;
    let mut input = format!(
        "{} {} {selected} {} {}\n",
        a.camera_parent_model,
        a.camera_parent_bone,
        d.pmm.timeline.camera_reference_mode,
        d.models.len()
    );
    for v in s {
        write!(input, "{v} ").unwrap();
    }
    for i in 0..d.models.len() {
        let p = pose(d, i);
        write!(
            input,
            "{} {} {} ",
            p.center_bone,
            d.pmm.models[i].selection.selected_bone,
            p.bones.len()
        )
        .unwrap();
        for b in p.bones {
            for v in b.mat_init.0.into_iter().chain(b.position) {
                write!(input, "{v} ").unwrap();
            }
        }
    }
    let mut child = Process::new(exe)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(out.status.success(), "native camera oracle failed");
    let values: Vec<f32> = String::from_utf8(out.stdout)
        .unwrap()
        .split_whitespace()
        .map(|v| v.parse().unwrap())
        .collect();
    assert_eq!(values.len(), 25);
    Some((
        values[3..6].try_into().unwrap(),
        Mat4(values[9..].try_into().unwrap()),
    ))
}

fn expected(d: &Document, selected: usize, reload: bool) -> ([f32; 3], Mat4) {
    let mut s = d.pmm.camera_state;
    if reload {
        let k = &d.pmm.camera.heads()[0];
        s[..3].copy_from_slice(&k.eye);
        s[6..].copy_from_slice(&k.target);
        s[3..5].fill(0.0);
        s[5] = k.distance;
    }
    if let Some(native) = native_expected(d, selected, s) {
        return native;
    }
    let parent = d.pmm.appearance.camera_parent_model >= 0;
    let p = pose(d, selected);
    let point = |b: &mds_pose::model::Bone| transform(&b.mat_init, b.position);
    let reference = match d.pmm.timeline.camera_reference_mode {
        1 => {
            let m = &p.bones[p.center_bone].mat_init.0;
            [m[12], m[13], m[14]]
        }
        2 if parent || d.pmm.models[selected].selection.selected_bone >= 0 => {
            point(&p.bones[d.pmm.models[selected].selection.selected_bone.max(0) as usize])
        }
        _ => [0.0; 3],
    };
    let mut basis = Mat4::IDENTITY;
    let target = if parent {
        let p = pose(d, 0);
        let b = &p.bones[2];
        basis = Mat4(std::array::from_fn(|i| b.mat_init.0[(i % 4) * 4 + i / 4]));
        for i in [3, 7, 11, 12, 13, 14] {
            basis.0[i] = 0.0;
        }
        point(b)
    } else {
        [s[0], s[1], s[2]]
    };
    let r = Mat4::multiply(
        &Mat4::multiply(&Mat4::rotation_y(s[7]), &Mat4::rotation_x(s[6])),
        &Mat4::rotation_z(s[8]),
    );
    let r = Mat4::multiply(&basis, &r);
    let delta = std::array::from_fn(|i| target[i] - reference[i]);
    let delta = transform(&r, delta);
    let out = std::array::from_fn(|i| {
        if parent {
            delta[i] + s[i]
        } else {
            delta[i] + s[3 + i]
        }
    });
    (out, basis)
}

#[test]
fn camera_to_model_parent_reference_follow_matrix() {
    let mut failures = Vec::new();
    for parent in [false, true] {
        for reference in 0..=2 {
            for follow in [false, true] {
                let mut d = doc();
                configure(&mut d, parent, reference, follow);
                let before = d.pmm.models[1].bone_pose.clone();
                let history = format!("{:?}", d.edit.models[1].history);
                let (want, basis) = expected(&d, 1, follow);
                let result = d.apply(Command::SelectModel(1));
                if result.is_err() || !close(&d.pmm.camera_state[3..6], &want) {
                    failures.push(format!("parent={parent} reference={reference} follow={follow}: {result:?}, {:?} != {want:?}", &d.pmm.camera_state[3..6]));
                    continue;
                }
                assert_eq!(d.pmm.settings.options[0], 0);
                assert_eq!(d.pmm.appearance.suppress_camera_transform, 0);
                if parent {
                    assert!(close(&d.pmm.appearance.camera_attachment_basis, &basis.0));
                }
                assert_eq!(
                    format!("{:?}", d.pmm.models[1].bone_pose),
                    format!("{before:?}")
                );
                assert_eq!(format!("{:?}", d.edit.models[1].history), history);
                let saved = d.save().unwrap();
                let saved = Document::load(&saved, |_| Some(fixture("chain8.pmx"))).unwrap();
                assert_eq!(saved.pmm.camera_state, d.pmm.camera_state);
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} / 12 failed:\n{}",
        failures.len(),
        failures.join("\n")
    );
}

#[test]
fn model_selection_reloads_only_across_the_followed_parent() {
    for parent in [false, true] {
        for reference in 0..=2 {
            for follow in [false, true] {
                for (old, new) in [(0, 1), (1, 0), (1, 2)] {
                    let mut d = doc();
                    configure(&mut d, parent, reference, follow);
                    d.pmm.settings.options[0] = 0;
                    d.pmm.selected_model_slot = old;
                    let before = d.pmm.camera_state;
                    let want = expected(&d, new as usize, true).0;
                    d.apply(Command::SelectModel(new)).unwrap();
                    if parent && follow && (old == 0 || new == 0) {
                        assert!(close(&d.pmm.camera_state[3..6], &want));
                        assert_eq!(d.pmm.appearance.suppress_camera_transform, 0);
                    } else {
                        assert_eq!(d.pmm.camera_state, before);
                        assert_eq!(d.pmm.appearance.suppress_camera_transform, 1);
                    }
                }
            }
        }
    }
}

#[test]
fn camera_model_loading_uses_the_new_model_as_reference() {
    for parent in [false, true] {
        for reference in 0..=2 {
            for follow in [false, true] {
                let mut d = doc();
                configure(&mut d, parent, reference, follow);
                let mut expected_doc = d.clone();
                expected_doc.pmm.settings.options[0] = 0;
                let load = || Command::LoadModel {
                    path: "chain8.pmx".into(),
                    data: fixture("chain8.pmx"),
                };
                let before = expected_doc.pmm.camera_state;
                expected_doc.apply(load()).unwrap();
                assert_eq!(
                    expected_doc.pmm.camera_state, before,
                    "model-mode loading keeps the view"
                );
                let want = expected(&expected_doc, 3, follow).0;
                d.apply(load()).unwrap();
                assert_eq!(d.pmm.selected_model_slot, 3);
                assert!(close(&d.pmm.camera_state[3..6], &want));
            }
        }
    }
}

#[test]
fn model_mode_frame_follow_refreshes_global_tracks_and_camera() {
    for parent in [false, true] {
        for reference in 0..=2 {
            for follow in [false, true] {
                let mut d = doc();
                configure(&mut d, parent, reference, follow);
                d.pmm.settings.options[0] = 0;
                d.pmm.selected_model_slot = 1;
                d.apply(Command::LoadAccessory {
                    path: r"C:\fixtures\cube.x".into(),
                    data: fixture("accessory/cube.x"),
                })
                .unwrap();
                let root = &mut d.pmm.models[0].bone_keys.heads_mut()[0];
                root.position = [9.0, -7.0, 3.0];
                root.rotation = [0.0, 0.0, 0.6, 0.8];
                d.pmm.light_state.fill(77.0);
                d.edit.self_shadow_mode = 8;
                d.pmm.accessories[0].state.scale = 77.0;
                d.pmm.physics.gravity_magnitude = 91.0;
                let before = d.pmm.camera_state;
                d.apply(Command::SetFrame(0)).unwrap();
                let mut original = d.clone();
                original.pmm.camera_state = before;
                let want = expected(&original, 1, true).0;
                if follow {
                    assert!(close(&d.pmm.camera_state[3..6], &want));
                    assert_ne!(d.pmm.light_state, [77.0; 6]);
                    assert_ne!(d.pmm.physics.gravity_magnitude, 91.0);
                    assert_ne!(d.edit.self_shadow_mode, 8);
                    assert_ne!(d.pmm.accessories[0].state.scale, 77.0);
                } else {
                    assert_eq!(d.pmm.camera_state, before);
                    assert_eq!(d.edit.self_shadow_mode, 8);
                    assert_eq!(d.pmm.accessories[0].state.scale, 77.0);
                }
                assert_eq!(d.pmm.models[0].bone_pose[0].translation, [9.0, -7.0, 3.0]);
            }
        }
    }
}

#[test]
fn negative_selected_bone_uses_zero_only_with_a_parent() {
    for parent in [false, true] {
        let mut d = doc();
        configure(&mut d, parent, 2, false);
        d.pmm.models[1].selection.selected_bone = -1;
        let want = expected(&d, 1, false).0;
        d.apply(Command::SelectModel(1)).unwrap();
        assert!(close(&d.pmm.camera_state[3..6], &want));
    }
}
