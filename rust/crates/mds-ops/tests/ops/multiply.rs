//! Menus 242, 251 and 252 (`src/window/misc_dialogs.cpp`:
//! `ApplyCameraFrameScaleAdd` 361-402, `ApplyBoneFrameScaleAdd` 530-591,
//! `ApplyMorphScaleAdd` 604-628).

use super::common::*;
use mds_ops::*;

#[allow(clippy::approx_constant)]
const PI_C: f64 = 3.141592;

/// `static_cast<float>(add * factor) / 180.0f`, written out.
fn radians(add: f32, factor: f64) -> f32 {
    let product = f64::from(add) * factor;
    (product as f32) / 180.0f32
}

#[test]
fn pi_literal_rounds_the_same_in_f32() {
    // The C++ writes 3.141592f for the gimbal-lock patch.
    #[allow(clippy::approx_constant)]
    let literal = 3.141592f32;
    assert_eq!(PI_C as f32, literal);
}

#[test]
fn camera_applies_each_pair_to_selected_keys_only() {
    // 376-398: selected keys, head included; the target angle adds are
    // degrees converted at 372-374; fov truncates (396-397); a pair of
    // (1.0, 0.0) is skipped, which keeps a -0.0.
    let mut p = camera3();
    camera_mode(&mut p, true);
    {
        let h = &mut p.camera.heads_mut()[0];
        h.selected = 1;
        h.eye = [3.0, 10.0, -0.0];
        h.target = [0.0, 1.0, 2.0];
        h.distance = -45.0;
        h.fov = 30;
    }
    p.camera.get_mut(1).unwrap().selected = 1;
    let other = p.camera.get(2).unwrap().clone();
    let s = CameraScale {
        scale: [2.0, 1.0, 1.0, 1.0, 3.0, 1.0, 0.5, 2.0],
        add: [0.0, 1.0, 0.0, 90.0, 0.0, 0.0, 0.0, 0.5],
    };
    multiply_camera_frames(&mut p, &s).unwrap();
    let h = &p.camera.heads()[0];
    assert_eq!(h.eye[0], 6.0);
    assert_eq!(h.eye[1], 11.0);
    assert_eq!(h.eye[2].to_bits(), (-0.0f32).to_bits(), "(1, 0) is skipped");
    // target.x: 1 * 0 + (90 * -3.141592) / 180.
    assert_eq!(h.target[0], radians(90.0, -PI_C));
    assert_eq!(h.target[1], 3.0);
    assert_eq!(h.target[2], 2.0);
    assert_eq!(h.distance, -22.5);
    assert_eq!(h.fov, 60, "30 * 2 + 0.5 truncates");
    let k = p.camera.get(1).unwrap();
    assert_eq!(k.eye[0], 0.0);
    assert_eq!(k.eye[1], 9.0);
    assert_eq!(k.distance, -15.0);
    assert_eq!(k.fov, 70);
    // The unselected key is untouched.
    assert_eq!(
        format!("{:?}", p.camera.get(2).unwrap()),
        format!("{other:?}")
    );
    assert_valid(&p);
}

#[test]
fn camera_target_angles_convert_with_the_sign_of_each_axis() {
    // 372-374: x is negated, y and z are not.
    let mut p = camera3();
    camera_mode(&mut p, true);
    p.camera.heads_mut()[0].selected = 1;
    p.camera.heads_mut()[0].target = [0.0; 3];
    let s = CameraScale {
        add: [0.0, 0.0, 0.0, 45.0, 45.0, 45.0, 0.0, 0.0],
        ..CameraScale::default()
    };
    multiply_camera_frames(&mut p, &s).unwrap();
    let t = p.camera.heads()[0].target;
    assert_eq!(t[0], radians(45.0, -PI_C));
    assert_eq!(t[1], radians(45.0, PI_C));
    assert_eq!(t[2], t[1]);
    assert!(t[0] < 0.0 && (t[1] - std::f32::consts::FRAC_PI_4).abs() < 1e-5);
}

#[test]
fn camera_dialog_opens_only_in_camera_mode() {
    // 1940-1949: the gate is inverted against the bone and morph dialogs.
    let mut p = camera3();
    p.camera.heads_mut()[0].selected = 1;
    let before = format!("{:?}", p.camera.heads()[0]);
    let s = CameraScale {
        scale: [2.0; 8],
        ..CameraScale::default()
    };
    assert_eq!(multiply_camera_frames(&mut p, &s), Err(Error::WrongMode));
    assert_eq!(format!("{:?}", p.camera.heads()[0]), before);
}

#[test]
fn bone_positions_scale_and_add_on_marked_keys() {
    // 557-566: allocated keys, heads included; a pair of (1, 0) is skipped.
    let mut p = swing600();
    {
        let pool = &mut p.models[0].bone_keys;
        pool.heads_mut()[0].position = [1.0, -0.0, 3.0];
        pool.get_mut(62).unwrap().position = [-0.08, 0.0, 0.0];
        pool.get_mut(63).unwrap().allocated = 0;
        pool.get_mut(63).unwrap().position = [5.0, 6.0, 7.0];
    }
    let s = BoneScale {
        scale: [2.0, 1.0, 0.5, 1.0, 1.0, 1.0],
        add: [0.5, 0.0, 1.0, 0.0, 0.0, 0.0],
    };
    multiply_bone_frames(&mut p, &s).unwrap();
    let pool = &p.models[0].bone_keys;
    let h = pool.heads()[0].position;
    assert_eq!((h[0], h[2]), (2.5, 2.5));
    assert_eq!(h[1].to_bits(), (-0.0f32).to_bits(), "(1, 0) is skipped");
    assert_eq!(
        pool.get(62).unwrap().position,
        [2.0 * -0.08 + 0.5, 1.0 * 0.0 + 0.0, 1.0]
    );
    assert_eq!(pool.get(63).unwrap().position, [5.0, 6.0, 7.0], "unmarked");
    // Rotations stay bit for bit when no rotation pair is set.
    assert_eq!(
        pool.get(64).unwrap().rotation,
        [0.0, 0.0, -0.002499996, 0.9999969]
    );
    assert_valid(&p);
}

#[test]
fn bone_rotation_pairs_rebuild_the_quaternion_through_euler_angles() {
    // 567-583: Rz * Rx * Ry from the key's matrix; z takes pair 5, x pair 3,
    // y pair 4; the adds are degrees (x positive, y and z negated).
    let mut p = swing600();
    let pool = &mut p.models[0].bone_keys;
    // Identity: all three angles are 0, so the result is Rz(add_z).
    pool.heads_mut()[1].rotation = [0.0, 0.0, 0.0, 1.0];
    let s = BoneScale {
        add: [0.0, 0.0, 0.0, 0.0, 0.0, 90.0],
        ..BoneScale::default()
    };
    multiply_bone_frames(&mut p, &s).unwrap();
    let q = p.models[0].bone_keys.heads()[1].rotation;
    // Rz(-pi/2) in D3DX's left-handed convention: a rotation of -90 degrees
    // about z, the quaternion (0, 0, sin(a/2), cos(a/2)) with a = -pi/2.
    let r = std::f32::consts::FRAC_1_SQRT_2;
    for (got, want) in q.iter().zip([0.0, 0.0, -r, r]) {
        assert!((got - want).abs() < 1e-5, "{q:?}");
    }
    // A scale of 2 on the z angle of Rz(0.5) gives Rz(1.0).
    let mut p = swing600();
    let half = (0.25f32).sin(); // quaternion z for 0.5 rad about z
    let k = &mut p.models[0].bone_keys.heads_mut()[2];
    k.rotation = [0.0, 0.0, half, (0.25f32).cos()];
    let s = BoneScale {
        scale: [1.0, 1.0, 1.0, 1.0, 1.0, 2.0],
        ..BoneScale::default()
    };
    multiply_bone_frames(&mut p, &s).unwrap();
    let q = p.models[0].bone_keys.heads()[2].rotation;
    let want = (0.5f32).sin();
    assert!(
        (q[2] - want).abs() < 1e-4 && (q[3] - (0.5f32).cos()).abs() < 1e-4,
        "{q:?}"
    );
}

#[test]
fn bone_rotation_is_untouched_when_every_rotation_pair_is_the_identity() {
    // 567-568: the block does not run, so a quaternion that is not a
    // rotation matrix survives bit for bit.
    let mut p = swing600();
    let odd = [0.1, 0.2, 0.3, 0.4];
    p.models[0].bone_keys.heads_mut()[3].rotation = odd;
    multiply_bone_frames(
        &mut p,
        &BoneScale {
            scale: [3.0, 3.0, 3.0, 1.0, 1.0, 1.0],
            ..BoneScale::default()
        },
    )
    .unwrap();
    assert_eq!(p.models[0].bone_keys.heads()[3].rotation, odd);
    // ... but any rotation pair that is not the identity runs it on every
    // marked key, and a non-unit quaternion is normalized by the matrix.
    let s = BoneScale {
        add: [0.0, 0.0, 0.0, 1e-3, 0.0, 0.0],
        ..BoneScale::default()
    };
    multiply_bone_frames(&mut p, &s).unwrap();
    assert_ne!(p.models[0].bone_keys.heads()[3].rotation, odd);
}

#[test]
fn bone_dialog_is_a_model_mode_command() {
    let mut p = swing600();
    camera_mode(&mut p, true);
    assert_eq!(
        multiply_bone_frames(&mut p, &BoneScale::default()),
        Err(Error::WrongMode)
    );
    assert_eq!(
        multiply_morph_frames(&mut p, 2.0, 0.0),
        Err(Error::WrongMode)
    );
}

#[test]
fn morph_values_scale_and_add_on_marked_keys() {
    // 615-620: allocated keys, heads included, unless the pair is (1, 0).
    let mut p = swing600();
    select(&mut p, 1);
    {
        let pool = &mut p.models[1].morph_keys;
        pool.heads_mut()[0].value = 0.5;
        pool.get_mut(5).unwrap().allocated = 0;
    }
    let before5 = p.models[1].morph_keys.get(5).unwrap().value;
    multiply_morph_frames(&mut p, 2.0, -0.25).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(pool.heads()[0].value, 0.75);
    assert_eq!(pool.get(4).unwrap().value, 2.0 * 0.125 - 0.25);
    assert_eq!(pool.get(6).unwrap().value, 1.75);
    assert_eq!(pool.get(5).unwrap().value, before5, "unmarked");
    let snapshot = shape(pool);
    multiply_morph_frames(&mut p, 1.0, 0.0).unwrap();
    assert_eq!(shape(&p.models[1].morph_keys), snapshot);
    assert_eq!(p.models[1].morph_keys.get(6).unwrap().value, 1.75);
    assert_valid(&p);
}
