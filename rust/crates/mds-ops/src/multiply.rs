//! The scale-and-add dialogs of the bone (251), camera (242) and morph
//! (252) frames. Each applies `value = scale * value + add` to every marked
//! key, and skips a field whose pair is the identity (`scale == 1` and
//! `add == 0`). The dialog fields are `atof` reads of the edit boxes; the
//! caller converts them to `f32` as the C++ does.

use crate::model::active_model;
use crate::pool::indices;
use crate::{Error, Result};
use mds_crtmath::{asinf, atan2f, cosf};
use mds_formats::pmm::Pmm;
use mds_math::{Mat4, Quat};

fn camera_mode(pmm: &Pmm) -> bool {
    pmm.settings.options[0] != 0
}

/// The literal the C++ uses for pi, which is not `PI`.
#[allow(clippy::approx_constant)]
const PI_C: f64 = 3.141592;

fn identity(scale: f32, add: f32) -> bool {
    scale == 1.0 && add == 0.0
}

fn apply(value: f32, scale: f32, add: f32) -> f32 {
    scale * value + add
}

/// `static_cast<float>(add * factor) / 180.0f`: the product is a double.
fn degrees(add: f32, factor: f64) -> f32 {
    (f64::from(add) * factor) as f32 / 180.0
}

/// `cvttss2si`: the integer a float converts to, `i32::MIN` when it does
/// not fit.
pub(crate) fn truncate(v: f32) -> i32 {
    if v.is_nan() || !(-2_147_483_648.0..2_147_483_648.0).contains(&v) {
        i32::MIN
    } else {
        v as i32
    }
}

/// The eight (scale, add) pairs of the camera dialog, in edit-box order.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CameraScale {
    /// Eye x, y, z; target x, y, z; distance; field of view.
    pub scale: [f32; 8],
    /// The same eight adds. The target adds are angles in degrees.
    pub add: [f32; 8],
}

impl Default for CameraScale {
    fn default() -> Self {
        CameraScale {
            scale: [1.0; 8],
            add: [0.0; 8],
        }
    }
}

/// Menu 242, `ApplyCameraFrameScaleAdd` (`src/window/misc_dialogs.cpp`
/// 361-402): applies the pairs to the eye, target, distance and field of
/// view of every marked camera key, track head included. The target adds are
/// degrees; the dialog turns them into radians with x negated
/// (`add * -3.141592 / 180`) and y and z positive. The field of view is an
/// integer: the float result truncates.
///
/// The menu opens only in camera mode (the gate is inverted against the
/// other dialogs), so the model modes return [`Error::WrongMode`].
pub fn multiply_camera_frames(pmm: &mut Pmm, p: &CameraScale) -> Result<()> {
    if !camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let (s, mut a) = (p.scale, p.add);
    a[3] = degrees(a[3], -PI_C);
    a[4] = degrees(a[4], PI_C);
    a[5] = degrees(a[5], PI_C);
    for i in indices(&pmm.camera, |_, k| k.selected != 0) {
        let Some(k) = pmm.camera.get_mut(i) else {
            continue;
        };
        for (n, v) in k.eye.iter_mut().chain(k.target.iter_mut()).enumerate() {
            if !identity(s[n], a[n]) {
                *v = apply(*v, s[n], a[n]);
            }
        }
        if !identity(s[6], a[6]) {
            k.distance = apply(k.distance, s[6], a[6]);
        }
        if !identity(s[7], a[7]) {
            k.fov = truncate((k.fov as f32) * s[7] + a[7]);
        }
    }
    Ok(())
}

/// The six (scale, add) pairs of the bone dialog.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BoneScale {
    /// Position x, y, z; rotation about x, y, z.
    pub scale: [f32; 6],
    /// The same six adds. The rotation adds are degrees.
    pub add: [f32; 6],
}

impl Default for BoneScale {
    fn default() -> Self {
        BoneScale {
            scale: [1.0; 6],
            add: [0.0; 6],
        }
    }
}

/// The rotation block of `ApplyBoneFrameScaleAdd`: the key's quaternion as
/// Rz * Rx * Ry angles, scaled and shifted, and back.
fn turn(q: [f32; 4], s: &[f32; 6], a: &[f32; 6]) -> [f32; 4] {
    let m = Mat4::rotation_quaternion(Quat(q)).0;
    let mut z = atan2f(m[1], m[5]);
    let x = asinf(-m[9]);
    let mut y = atan2f(m[8], m[10]);
    if 1e-6f32 > cosf(x).abs() {
        z += if m[1] > 0.0 {
            PI_C as f32
        } else {
            -PI_C as f32
        };
        y += if m[8] > 0.0 {
            PI_C as f32
        } else {
            -PI_C as f32
        };
    }
    let rz = Mat4::rotation_z(z * s[5] + a[5]);
    let rx = Mat4::rotation_x(x * s[3] + a[3]);
    let ry = Mat4::rotation_y(y * s[4] + a[4]);
    Quat::from_matrix(&Mat4::multiply(&Mat4::multiply(&rz, &rx), &ry)).0
}

/// Menu 251, `ApplyBoneFrameScaleAdd` (`misc_dialogs.cpp` 530-591): applies
/// the position pairs, and the rotation pairs when any is not the identity,
/// to every marked bone key of the model, track head included. The rotation
/// adds are degrees, converted as `x * pi / 180`, `y * -pi / 180`,
/// `z * -pi / 180`. The rotation uses the D3DX and UCRT ports of
/// `mds-math` and `mds-crtmath`.
pub fn multiply_bone_frames(pmm: &mut Pmm, p: &BoneScale) -> Result<()> {
    if camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    let s = p.scale;
    let mut a = p.add;
    a[3] = degrees(a[3], PI_C);
    a[4] = degrees(a[4], -PI_C);
    a[5] = degrees(a[5], -PI_C);
    let turns = s[3..].iter().any(|&v| v != 1.0) || a[3..].iter().any(|&v| v != 0.0);
    let pool = &mut pmm.models[m].bone_keys;
    for i in indices(pool, |_, k| k.allocated != 0) {
        let Some(k) = pool.get_mut(i) else {
            continue;
        };
        for (n, v) in k.position.iter_mut().enumerate() {
            if !identity(s[n], a[n]) {
                *v = apply(*v, s[n], a[n]);
            }
        }
        if turns {
            k.rotation = turn(k.rotation, &s, &a);
        }
    }
    Ok(())
}

/// Menu 252, `ApplyMorphScaleAdd` (`misc_dialogs.cpp` 604-628): applies the
/// pair to the value of every marked morph key, track head included, unless
/// the pair is the identity.
pub fn multiply_morph_frames(pmm: &mut Pmm, scale: f32, add: f32) -> Result<()> {
    if camera_mode(pmm) {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    if identity(scale, add) {
        return Ok(());
    }
    let pool = &mut pmm.models[m].morph_keys;
    for i in indices(pool, |_, k| k.allocated != 0) {
        if let Some(k) = pool.get_mut(i) {
            k.value = apply(k.value, scale, add);
        }
    }
    Ok(())
}
