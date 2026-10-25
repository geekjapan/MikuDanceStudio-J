//! The bone readout edits 544..549 in model mode: `CommitEditControlTail`
//! (`src/window/ui_edit_commit.cpp`, VA 0x0044BEF0) and the Euler readout
//! of `PostViewRefresh` (`src/window/ui_view_refresh.cpp`, VA 0x0040D130)
//! that the rotation edits start from.

use mds_math::{Mat4, Quat};

/// `kPiLit` of the edit handlers.
const PI_LIT: f64 = 3.141592025756836;
/// `3.141592f` (0x40490FD8) of the readout.
fn pi_f() -> f32 {
    f32::from_bits(0x4049_0fd8)
}

/// The readout degrees `(x, y, z)` of a bone rotation (`0xA04C0..C8`).
pub(crate) fn euler_degrees(q: [f32; 4]) -> [f32; 3] {
    let m = Mat4::rotation_quaternion(Quat(q)).0;
    let (m12, m22, m31, m32, m33) = (m[1], m[5], m[8], m[9], m[10]);
    let d = f64::from;
    let mut rz = d(m12).atan2(d(m22)) as f32;
    let mut rx = (-d(m32)).asin() as f32;
    let mut ry = d(m31).atan2(d(m33)) as f32;
    let c = d(rx).cos() as f32;
    if d(c).abs() < d(1e-6f32) {
        let pi = d(pi_f());
        rz = (d(rz) + if m12 > 0.0 { pi } else { -pi }) as f32;
        ry = (d(ry) + if m31 > 0.0 { pi } else { -pi }) as f32;
    }
    for a in [&mut rx, &mut ry, &mut rz] {
        if d(*a).abs() < d(1e-6f32) {
            *a = 0.0;
        }
    }
    [
        (d(rx) / d(pi_f()) * 180.0) as f32,
        (-d(ry) / d(pi_f()) * 180.0) as f32,
        (180.0 * (-d(rz) / d(pi_f()))) as f32,
    ]
}

/// A rotation edit (`axis` 0..2 for 547..549) of the value `v`, from the
/// readout `deg`: the other two axes are the readout re-converted, then
/// `ComposeEulerToBone`, `Rz * Rx * Ry` into a quaternion.
pub(crate) fn rotation_edit(deg: [f32; 3], axis: usize, v: f64) -> [f32; 4] {
    let d = f64::from;
    let x = if axis == 0 { v } else { d(deg[0]) };
    let ex = (x * PI_LIT / 180.0) as f32;
    let ey = if axis == 1 {
        (-v * PI_LIT / 180.0) as f32
    } else {
        (-d(deg[1]) * PI_LIT / 180.0) as f32
    };
    let ez = if axis == 2 {
        (PI_LIT * -v / 180.0) as f32
    } else {
        (PI_LIT * -d(deg[2]) / 180.0) as f32
    };
    let r = Mat4::multiply(&Mat4::rotation_z(ez), &Mat4::rotation_x(ex));
    let r = Mat4::multiply(&r, &Mat4::rotation_y(ey));
    Quat::from_matrix(&r).0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_rotation_edit_reads_back() {
        let q = rotation_edit([0.0; 3], 1, 45.0);
        let deg = euler_degrees(q);
        assert!((deg[1] - 45.0).abs() < 1e-3, "{deg:?}");
        assert_eq!((deg[0], deg[2]), (0.0, 0.0));
    }
}
