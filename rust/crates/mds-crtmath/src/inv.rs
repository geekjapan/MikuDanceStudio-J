//! asinf, acosf, atanf, atan2f: the UCRT FMA3 paths. The algorithms are AMD
//! AOCL-LibM's C reference versions; asinf and acosf fuse every a * b + c, as
//! a compiler contracting for FMA3 would. atanf and atan2f have no fusable
//! site whose rounding shows (the UCRT FMA3 and non-FMA3 digests agree).

use crate::tables::ATAN_JBY256;

const PI: f64 = f64::from_bits(0x4009_21FB_5444_2D18);
const PIBY2: f64 = f64::from_bits(0x3FF9_21FB_5444_2D18);

/// u = (asin(y) - y) / y^3 at r = y^2: the rational approximation shared by
/// asinf and acosf.
fn asin_ratio(r: f32) -> f32 {
    let p = f32::from_bits(0xBB81_CE6B).mul_add(r, f32::from_bits(0xBC5B_3FE1));
    let p = p.mul_add(r, f32::from_bits(0xBD67_8BDD));
    let p = p.mul_add(r, f32::from_bits(0x3E3C_94DC));
    let q = f32::from_bits(0xBF56_1F0D).mul_add(r, f32::from_bits(0x3F8D_6FA5));
    r * p / q
}

/// For 0.5 <= |x| < 1: r = (1 - |x|) / 2, s = sqrt(r), u = asin_ratio(r).
fn transform(ax: f32) -> (f32, f32, f32) {
    let r = 0.5 * (1.0 - ax);
    let s = r.sqrt();
    (r, s, asin_ratio(r))
}

/// s with the low 16 bits cleared, and the correction c with s1 + c = sqrt(r).
fn split_sqrt(r: f32, s: f32) -> (f32, f32) {
    let s1 = f32::from_bits(s.to_bits() & 0xFFFF_0000);
    (s1, (-s1).mul_add(s1, r) / (s + s1))
}

pub fn asinf(x: f32) -> f32 {
    const PIBY2_TAIL: f32 = f32::from_bits(0x33A2_2168);
    const HPIBY2_HEAD: f32 = f32::from_bits(0x3F49_0FDA);
    let ux = x.to_bits();
    let ax = f32::from_bits(ux & 0x7FFF_FFFF);
    let xexp = ((ux >> 23) & 0xFF) as i32 - 127;
    if ax.is_nan() {
        return f32::NAN;
    }
    if xexp < -14 {
        return x;
    }
    if xexp >= 0 {
        return if ax == 1.0 {
            (PIBY2 as f32).copysign(x)
        } else {
            f32::NAN
        };
    }
    let v = if xexp >= -1 {
        let (r, s, u) = transform(ax);
        let (s1, c) = split_sqrt(r, s);
        let p = (2.0 * s).mul_add(u, -(-2.0f32).mul_add(c, PIBY2_TAIL));
        let q = HPIBY2_HEAD - 2.0 * s1;
        HPIBY2_HEAD - (p - q)
    } else {
        ax.mul_add(asin_ratio(ax * ax), ax)
    };
    v.copysign(x)
}

pub fn acosf(x: f32) -> f32 {
    const PIBY2_TAIL: f64 = f64::from_bits(0x3C91_A626_3314_5C07);
    let ux = x.to_bits();
    let ax = f32::from_bits(ux & 0x7FFF_FFFF);
    let xexp = ((ux >> 23) & 0xFF) as i32 - 127;
    if ax.is_nan() {
        return f32::NAN;
    }
    if xexp < -26 {
        return PIBY2 as f32;
    }
    if xexp >= 0 {
        return if x == 1.0 {
            0.0
        } else if x == -1.0 {
            PI as f32
        } else {
            f32::NAN
        };
    }
    if xexp < -1 {
        let u = asin_ratio(x * x);
        let t = PIBY2_TAIL - f64::from(x * u);
        return (PIBY2 - (f64::from(x) - t)) as f32;
    }
    let (r, s, u) = transform(ax);
    if x < 0.0 {
        let t = f64::from(s * u) - PIBY2_TAIL;
        (PI - 2.0 * (f64::from(s) + t)) as f32
    } else {
        let (s1, c) = split_sqrt(r, s);
        2.0 * s1 + (2.0 * s).mul_add(u, 2.0 * c)
    }
}

/// c - (q - x) with q the Remez(2,2) approximation of x - atan(x) on
/// [-7/16, 7/16], in double.
fn atan_core(x: f64, c: f64) -> f64 {
    let s = x * x;
    let num = f64::from_bits(0x3FD2_FA53_1690_7834)
        + (f64::from_bits(0x3FC8_9E17_3A81_EE7F) + f64::from_bits(0x3F73_476A_758D_A22A) * s) * s;
    let den = f64::from_bits(0x3FEC_777C_A210_53F0)
        + (f64::from_bits(0x3FF1_C587_93DA_6EA4) + f64::from_bits(0x3FD3_27E3_DF2C_F2AA) * s) * s;
    let q = x * s * num / den;
    c - (q - x)
}

pub fn atanf(x: f32) -> f32 {
    if x.is_nan() {
        return f32::NAN;
    }
    let v = f64::from(x).abs();
    let av = v.to_bits();
    let z = if av < 0x3EC0_0000_0000_0000 {
        return x;
    } else if av < 0x3FDC_0000_0000_0000 {
        atan_core(v, 0.0)
    } else if av < 0x3FE6_0000_0000_0000 {
        atan_core(
            (2.0 * v - 1.0) / (2.0 + v),
            f64::from_bits(0x3FDD_AC67_0561_BB4F),
        )
    } else if av < 0x3FF3_0000_0000_0000 {
        atan_core((v - 1.0) / (1.0 + v), f64::from_bits(0x3FE9_21FB_5444_2D18))
    } else if av < 0x4003_8000_0000_0000 {
        atan_core(
            (v - 1.5) / (1.0 + 1.5 * v),
            f64::from_bits(0x3FEF_730B_D281_F69B),
        )
    } else if av > 0x4190_0000_0000_0000 {
        PIBY2
    } else {
        atan_core(-1.0 / v, PIBY2)
    };
    (z as f32).copysign(x)
}

pub fn atan2f(y: f32, x: f32) -> f32 {
    if x.is_nan() || y.is_nan() {
        return f32::NAN;
    }
    let xneg = x.is_sign_negative();
    let quadrant = |q: f64| (q as f32).copysign(y);
    if y == 0.0 {
        return if xneg { quadrant(PI) } else { y };
    }
    if x == 0.0 {
        return quadrant(PIBY2);
    }
    let (xd, yd) = (f64::from(x), f64::from(y));
    // Exponents of the doubles, so subnormal floats count at their true scale.
    let diffexp = ((yd.to_bits() >> 52) & 0x7FF) as i32 - ((xd.to_bits() >> 52) & 0x7FF) as i32;
    if diffexp > 26 {
        return quadrant(PIBY2);
    }
    if diffexp < -13 && !xneg {
        return if diffexp < -150 {
            0.0f32.copysign(y)
        } else {
            (yd / xd) as f32
        };
    }
    if diffexp < -26 && xneg {
        return quadrant(PI);
    }
    if x.is_infinite() && y.is_infinite() {
        let q = if xneg {
            f64::from_bits(0x4002_D97C_7F33_21D2)
        } else {
            f64::from_bits(0x3FE9_21FB_5444_2D18)
        };
        return quadrant(q);
    }
    let (mut u, mut v) = (xd.abs(), yd.abs());
    let swap = u < v;
    if swap {
        std::mem::swap(&mut u, &mut v);
    }
    let vbyu = v / u;
    let mut q = if vbyu > 0.0625 {
        let index = (256.0 * vbyu + 0.5) as u32;
        let fi = f64::from(index);
        let r = (256.0 * v - fi * u) / (256.0 * u + fi * v);
        let s = r * r;
        f64::from_bits(ATAN_JBY256[index as usize - 16]) + r
            - r * s * f64::from_bits(0x3FD5_5555_5555_0877)
    } else if vbyu < 1.0e-4 {
        vbyu
    } else {
        let s = vbyu * vbyu;
        vbyu - vbyu
            * s
            * (f64::from_bits(0x3FD5_5555_5555_5538)
                - s * (f64::from_bits(0x3FC9_9999_9996_43A3)
                    - s * f64::from_bits(0x3FC2_4924_82BD_6BE1)))
    };
    if swap {
        q = PIBY2 - q;
    }
    if xneg {
        q = PI - q;
    }
    quadrant(q)
}
