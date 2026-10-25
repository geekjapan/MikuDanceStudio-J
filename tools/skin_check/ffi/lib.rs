//! The D3DX entry points the checked C++ calls, as `mds-math` computes them.
//! `shim/mikudancestudio/d3dx_dyn.hpp` declares them. The `mds_crt_*`
//! functions come from `mds-crtmath` itself.
//!
//! Every input is read before the output is written, because the callers
//! pass the output as an input too (`multiply(&m, &m, &t)`).

use mds_math::{Mat4, Quat, Vec3};

// Links mds-crtmath, whose #[no_mangle] mds_crt_* functions the shims call.
use mds_crtmath as _;

unsafe fn mat(p: *const f32) -> Mat4 {
    Mat4(std::ptr::read(p.cast::<[f32; 16]>()))
}

unsafe fn put<const N: usize>(p: *mut f32, v: [f32; N]) {
    std::ptr::write(p.cast::<[f32; N]>(), v);
}

/// # Safety
/// `out` holds 4 floats, `m` 16.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_quat_from_matrix(out: *mut f32, m: *const f32) {
    put(out, Quat::from_matrix(&mat(m)).0);
}

/// # Safety
/// `out` holds 16 floats, `q` 4.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_rotation_quaternion(out: *mut f32, q: *const f32) {
    put(
        out,
        Mat4::rotation_quaternion(Quat(std::ptr::read(q.cast()))).0,
    );
}

/// # Safety
/// `out` and `v` hold 3 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_vec3_normalize(out: *mut f32, v: *const f32) {
    put(out, Vec3(std::ptr::read(v.cast())).normalize().0);
}

/// # Safety
/// `out`, `a` and `b` hold 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_multiply(out: *mut f32, a: *const f32, b: *const f32) {
    put(out, Mat4::multiply(&mat(a), &mat(b)).0);
}

/// # Safety
/// `out` holds 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_translation(out: *mut f32, x: f32, y: f32, z: f32) {
    put(out, Mat4::translation(x, y, z).0);
}

/// # Safety
/// `out` holds 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_rotation_x(out: *mut f32, angle: f32) {
    put(out, Mat4::rotation_x(angle).0);
}

/// # Safety
/// `out` holds 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_rotation_y(out: *mut f32, angle: f32) {
    put(out, Mat4::rotation_y(angle).0);
}

/// # Safety
/// `out` holds 16 floats.
#[no_mangle]
pub unsafe extern "C" fn mds_d3dx_matrix_rotation_z(out: *mut f32, angle: f32) {
    put(out, Mat4::rotation_z(angle).0);
}
