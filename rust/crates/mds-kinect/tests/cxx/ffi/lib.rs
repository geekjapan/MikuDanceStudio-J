//! The D3DX entry points the checked C++ calls. `shim/mikudancestudio/
//! d3dx_dyn.hpp` declares them. The `mds_crt_*` functions come from
//! `mds-crtmath` itself.
//!
//! Every input is read before the output is written, because the callers
//! pass the output as an input too (`quatMultiply(q, q, qA)`).

use mds_math::{Mat4, Quat, Vec3};

// Links mds-crtmath, whose #[no_mangle] mds_crt_* functions the shims call.
use mds_crtmath as _;

unsafe fn read<const N: usize>(p: *const f32) -> [f32; N] {
    std::ptr::read(p.cast::<[f32; N]>())
}

unsafe fn put<const N: usize>(p: *mut f32, v: [f32; N]) {
    std::ptr::write(p.cast::<[f32; N]>(), v);
}

/// # Safety
/// `out` holds 4 floats, `m` 16.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_quat_from_matrix(out: *mut f32, m: *const f32) {
    put(out, Quat::from_matrix(&Mat4(read(m))).0);
}

/// # Safety
/// `out` holds 16 floats, `q` 4.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_rotation_quaternion(out: *mut f32, q: *const f32) {
    put(out, Mat4::rotation_quaternion(Quat(read(q))).0);
}

/// # Safety
/// `out` and `v` hold 3 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_vec3_normalize(out: *mut f32, v: *const f32) {
    put(out, Vec3(read(v)).normalize().0);
}

/// # Safety
/// `out`, `a` and `b` hold 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_multiply(out: *mut f32, a: *const f32, b: *const f32) {
    put(out, Mat4::multiply(&Mat4(read(a)), &Mat4(read(b))).0);
}

/// # Safety
/// `out` holds 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_rotation_y(out: *mut f32, angle: f32) {
    put(out, Mat4::rotation_y(angle).0);
}

/// # Safety
/// `out`, `a` and `b` hold 4 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_quat_multiply(out: *mut f32, a: *const f32, b: *const f32) {
    put(out, Quat::multiply(Quat(read(a)), Quat(read(b))).0);
}

/// # Safety
/// `out` and `q` hold 4 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_quat_inverse(out: *mut f32, q: *const f32) {
    put(out, mds_kinect::d3dx::quat_inverse(read(q)));
}

/// # Safety
/// `out` holds 4 floats, `axis` 3.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_quat_rotation_axis(out: *mut f32, axis: *const f32, angle: f32) {
    put(out, mds_kinect::d3dx::quat_rotation_axis(read(axis), angle));
}

/// # Safety
/// `out` holds 4 floats, `v` 3, `m` 16.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_vec3_transform(out: *mut f32, v: *const f32, m: *const f32) {
    put(out, mds_kinect::d3dx::vec3_transform(read(v), &Mat4(read(m))));
}
