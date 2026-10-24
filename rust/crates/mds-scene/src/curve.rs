//! Bezier easing of bone and camera keys: `BoneEase` and `CameraEase` of
//! `src/io/pmm_scene_evaluation.cpp`. Every operation is `f32`, in the C++
//! order; Rust never fuses a multiply-add, so the results match bit for bit.

/// Control byte as the C++ `static_cast<float>(static_cast<std::int8_t>(b))`.
fn signed(b: u8) -> f32 {
    f32::from(b as i8)
}

/// Eases `t` along the bone curve of `channel` (0..3 translation, 3 rotation).
/// `curve` holds `x1[4] y1[4] x2[4] y2[4]` in C++ memory order.
pub fn bone_ease(curve: &[u8; 16], channel: usize, t: f32) -> f32 {
    let (x1, y1) = (curve[channel], curve[channel + 4]);
    let (x2, y2) = (curve[channel + 8], curve[channel + 12]);
    if x1 == y1 && x2 == y2 {
        return t;
    }
    const SCALE: f32 = 0.023_622;
    let control_x1 = signed(x1) * SCALE;
    let control_x2 = signed(x2) * SCALE;
    let mut u = 0.5f32;
    let mut step = 0.5f32;
    for _ in 0..12 {
        let opposite = 1.0f32 - u;
        let x =
            (opposite * opposite * u) * control_x1 + (opposite * u * u) * control_x2 + u * u * u;
        if x == t {
            break;
        }
        step *= 0.5;
        u = if x >= t { u - step } else { u + step };
    }
    let opposite = 1.0f32 - u;
    (opposite * opposite * u) * signed(y1) * SCALE
        + (opposite * u * u) * signed(y2) * SCALE
        + u * u * u
}

/// Eases `t` along the camera curve of `channel` (0..3 position, 3 rotation,
/// 4 distance, 5 fov). `curve` is `[row][channel]` as `PmmCameraKey`.
pub fn camera_ease(curve: &[[u8; 6]; 4], channel: usize, t: f32) -> f32 {
    if curve[0][channel] == curve[1][channel] && curve[2][channel] == curve[3][channel] {
        return t;
    }
    let x1 = signed(curve[0][channel]) / 127.0f32;
    let x2 = signed(curve[2][channel]) / 127.0f32;
    let y1 = signed(curve[1][channel]);
    let y2 = signed(curve[3][channel]);
    let mut u = 0.5f32;
    let mut half = 0.25f32;
    for _ in 0..12 {
        let v = 1.0f32 - u;
        let v3 = v * 3.0f32;
        let x = (v3 * v * u) * x1 + (v3 * u * u) * x2 + u * u * u;
        if x == t {
            break;
        }
        u = if x >= t { u - half } else { u + half };
        half *= 0.5;
    }
    let v = 1.0f32 - u;
    let v3 = v * 3.0f32;
    (v3 * v * u) * y1 / 127.0f32 + (v3 * u * u) * y2 / 127.0f32 + u * u * u
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A curve whose control points are not on the diagonal: x1 = 20,
    /// y1 = 100, x2 = 107, y2 = 27 for every channel.
    const BONE: [u8; 16] = [
        20, 20, 20, 20, 100, 100, 100, 100, 107, 107, 107, 107, 27, 27, 27, 27,
    ];
    const LINEAR: [u8; 16] = [
        20, 20, 20, 20, 20, 20, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107,
    ];

    #[test]
    fn scale_is_the_cpp_float_literal() {
        // 0.02362200058996677f in C++.
        assert_eq!(0.023_622f32.to_bits(), 0x3cc1_82ed);
    }

    #[test]
    fn linear_curve_returns_t_unchanged() {
        for t in [0.0f32, 0.25, 0.5, 0.123_456_79, 1.0] {
            assert_eq!(bone_ease(&LINEAR, 0, t).to_bits(), t.to_bits());
        }
        let camera = [[20; 6], [20; 6], [107; 6], [107; 6]];
        assert_eq!(camera_ease(&camera, 3, 0.3).to_bits(), 0.3f32.to_bits());
    }

    #[test]
    fn bone_curve_at_zero_and_one() {
        // 12 bisection steps leave u within 2^-12 of the end, so the curve
        // value is within a few thousandths of the end value.
        assert!(bone_ease(&BONE, 0, 0.0).abs() < 2e-3);
        assert!((bone_ease(&BONE, 0, 1.0) - 1.0).abs() < 2e-3);
    }

    #[test]
    fn bone_curve_midpoint_is_deterministic() {
        let mid = bone_ease(&BONE, 1, 0.5);
        assert_eq!(mid.to_bits(), bone_ease(&BONE, 1, 0.5).to_bits());
        assert!(
            mid > 0.5,
            "an ease with y1 > x1 runs ahead of linear: {mid}"
        );
    }

    #[test]
    fn camera_curve_at_zero_and_one() {
        let camera = [[30; 6], [10; 6], [100; 6], [120; 6]];
        assert!(camera_ease(&camera, 0, 0.0).abs() < 2e-3);
        assert!((camera_ease(&camera, 0, 1.0) - 1.0).abs() < 2e-3);
    }
}
