//! The three D3DX functions the pose math calls that `mds-math` does not
//! carry. `tests/fixtures/rust/math/d3dx-vectors.txt` has no vectors for
//! them, so their operation order is the plain textbook one (the Wine
//! source) and is **not** checked against `d3dx9_43.dll`. A later change
//! should add them to `tools/oracle/math_vectors.cpp` and move them into
//! `mds-math`.

use mds_math::Mat4;

/// `D3DXQuaternionInverse`: conjugate over the squared length; a zero
/// quaternion gives zeros.
pub fn quat_inverse(q: [f32; 4]) -> [f32; 4] {
    let [x, y, z, w] = q;
    let norm = ((x * x + y * y) + z * z) + w * w;
    if norm == 0.0 {
        return [0.0; 4];
    }
    [-x / norm, -y / norm, -z / norm, w / norm]
}

/// `D3DXQuaternionRotationAxis`: the axis is normalized with
/// `D3DXVec3Normalize`, sine and cosine of half the angle come from `f64`.
pub fn quat_rotation_axis(axis: [f32; 3], angle: f32) -> [f32; 4] {
    let n = mds_math::Vec3(axis).normalize().0;
    let half = f64::from(angle * 0.5);
    let (s, c) = (libm::sin(half) as f32, libm::cos(half) as f32);
    [s * n[0], s * n[1], s * n[2], c]
}

/// `D3DXVec3Transform`: `[x y z 1] * m`, four components.
pub fn vec3_transform(v: [f32; 3], m: &Mat4) -> [f32; 4] {
    let g = |i: usize| m.0[i];
    let col = |c: usize| ((g(c) * v[0] + g(4 + c) * v[1]) + g(8 + c) * v[2]) + g(12 + c);
    [col(0), col(1), col(2), col(3)]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inverse_of_a_unit_quaternion_is_its_conjugate() {
        assert_eq!(quat_inverse([0.0, 0.0, 0.0, 1.0]), [-0.0, -0.0, -0.0, 1.0]);
        assert_eq!(quat_inverse([0.0; 4]), [0.0; 4]);
        assert_eq!(quat_inverse([0.5, 0.5, 0.5, 0.5]), [-0.5, -0.5, -0.5, 0.5]);
    }

    #[test]
    fn rotation_axis_quarter_turn() {
        let q = quat_rotation_axis([0.0, 0.0, 2.0], std::f32::consts::FRAC_PI_2);
        let h = std::f32::consts::FRAC_1_SQRT_2;
        assert!((q[2] - h).abs() < 1e-7 && (q[3] - h).abs() < 1e-7 && q[0] == 0.0);
    }

    #[test]
    fn transform_adds_the_translation_row() {
        let m = Mat4::translation(1.0, 2.0, 3.0);
        assert_eq!(vec3_transform([1.0, 1.0, 1.0], &m), [2.0, 3.0, 4.0, 1.0]);
    }
}
