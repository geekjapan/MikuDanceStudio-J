//! expf, logf, powf: the UCRT FMA3 paths, after the AMD AOCL-LibM FMA3
//! assembly. expf and powf work in f64, logf in f32 with fused steps.

use crate::tables::{LOGF_INV, LOGF_LEAD, LOGF_TAIL, POWF_INV, POWF_LOG, TWO_TO_JBY64};

const SIXTY_FOUR_BY_LN2: f64 = f64::from_bits(0x4057_1547_652B_82FE);
const LN2_BY_64: f64 = f64::from_bits(0x3F86_2E42_FEFA_39EF);
const ONE_SIXTH: f64 = f64::from_bits(0x3FC5_5555_5555_5555);

/// e^w for w in the range where the result is a finite float or rounds to
/// zero: e^w = 2^m * 2^(j/64) * e^r with |r| <= ln2/128.
fn exp_core(w: f64) -> f32 {
    let n = (w * SIXTY_FOUR_BY_LN2).round_ties_even() as i32;
    let r = (-f64::from(n)).mul_add(LN2_BY_64, w);
    let q = r.mul_add(ONE_SIXTH, 0.5).mul_add(r * r, r);
    let f = f64::from_bits(TWO_TO_JBY64[(n & 0x3F) as usize]);
    let v = f.mul_add(q, f);
    f64::from_bits(v.to_bits().wrapping_add((i64::from(n >> 6) as u64) << 52)) as f32
}

pub fn expf(x: f32) -> f32 {
    if x.is_nan() {
        return x + x;
    }
    if x > f32::from_bits(0x42B1_7218) {
        return f32::INFINITY;
    }
    // Below ln(2^-150) every result rounds to zero. Any cut in
    // [-110, -103.972] gives the same results; the UCRT constant is unknown.
    if x < -104.0 {
        return 0.0;
    }
    exp_core(f64::from(x))
}

pub fn logf(x: f32) -> f32 {
    let ux = x.to_bits();
    if ux & 0x7F80_0000 == 0x7F80_0000 {
        return if ux == 0x7F80_0000 { x } else { f32::NAN };
    }
    if x <= 0.0 {
        return if x == 0.0 {
            f32::NEG_INFINITY
        } else {
            f32::NAN
        };
    }
    let xm1 = x - 1.0;
    if xm1.abs() < 0.0625 {
        // log(1 + r) = 2 atanh(u / 2) with u = 2r / (2 + r).
        let u = xm1 / (2.0 + xm1);
        let correction = xm1 * u;
        let u = u + u;
        let v = u * u;
        let p = v.mul_add(f32::from_bits(0x3C4C_CCCD), f32::from_bits(0x3DAA_AAAB));
        return xm1 + (u * v).mul_add(p, -correction);
    }
    let (mut xb, mut xexp) = (ux, (ux >> 23) as i32 - 127);
    if xexp == -127 {
        // Subnormal: normalise through 1.m - 1.
        xb = (f32::from_bits((ux & 0x007F_FFFF) | 0x3F80_0000) - 1.0).to_bits();
        xexp = (xb >> 23) as i32 - 253;
        xb &= 0x007F_FFFF;
    }
    let xexp = xexp as f32;
    // F = 1/2 + j/256 is Y = 1/2 * 1.m rounded to 7 mantissa bits.
    let fbits = (xb & 0x007F_0000) + ((xb & 0x8000) << 1);
    let j = (fbits >> 16) as usize;
    let y = f32::from_bits((xb & 0x007F_FFFF) | 0x3F00_0000);
    let r = (f32::from_bits(fbits | 0x3F00_0000) - y) * f32::from_bits(LOGF_INV[j]);
    let poly = r
        .mul_add(f32::from_bits(0x3EAA_AAAB), 0.5)
        .mul_add(r * r, r);
    let z2 = xexp.mul_add(f32::from_bits(0x3805_FDF4), -poly) + f32::from_bits(LOGF_TAIL[j]);
    let z1 = xexp.mul_add(f32::from_bits(0x3F31_7000), f32::from_bits(LOGF_LEAD[j]));
    z1 + z2
}

/// None when y is not an integer; |y| >= 2^24 counts as an even integer.
fn odd_integer(y: f32) -> Option<bool> {
    if y.to_bits() & 0x7F80_0000 > 0x4B00_0000 {
        return Some(false);
    }
    let i = y.round_ties_even() as i32;
    (i as f32 == y).then_some(i & 1 == 1)
}

/// ln|x| for a finite x != 0. Negative x never takes the near-one path,
/// because the UCRT tests x - 1 with the sign of x.
fn log_core(xd: f64) -> f64 {
    let r = xd - 1.0;
    if r.abs() < 0.0625 {
        // 2 atanh(u / 2) with u = 2r / (2 + r), to u^9.
        let half_u = r / (r + 2.0);
        let u = half_u + half_u;
        let u2 = u * u;
        let u3 = u * u2;
        let a = u2.mul_add(
            f64::from_bits(0x3F89_9999_99BA_C6D4),
            f64::from_bits(0x3FB5_5555_5555_54E6),
        );
        let b = u2.mul_add(
            f64::from_bits(0x3F3C_8034_C85D_FFF0),
            f64::from_bits(0x3F62_4923_07F1_519F),
        );
        let tail = (u2 * u2 * u3) * b + u3 * a;
        return r + (-r).mul_add(half_u, tail);
    }
    let xb = xd.to_bits();
    let mant = xb & 0x000F_FFFF_FFFF_FFFF;
    let j = ((mant >> 44) + ((mant >> 43) & 1)) as usize;
    let f = f64::from_bits((j as u64 | 0x3FE00) << 44);
    let y = f64::from_bits(mant | 0x3FE0_0000_0000_0000);
    let m = f64::from(((xb >> 52) & 0x7FF) as i32 - 1023);
    let r = (f - y) * f64::from_bits(POWF_INV[j]);
    let poly = (r * f64::from_bits(0x3FD5_5555_5555_5555) + 0.5).mul_add(r * r, r);
    f64::from_bits(0x3FE6_2E42_FEFA_39EF) * m + f64::from_bits(POWF_LOG[j]) - poly
}

pub fn powf(x: f32, y: f32) -> f32 {
    let (ux, uy) = (x.to_bits(), y.to_bits());
    let (ax, ay) = (ux & 0x7FFF_FFFF, uy & 0x7FFF_FFFF);
    if ay > 0x7F80_0000 {
        return if ux == 0x3F80_0000 { 1.0 } else { y + y };
    }
    if ay == 0x7F80_0000 {
        if ax > 0x7F80_0000 {
            return x + x;
        }
        if ax == 0x3F80_0000 {
            return 1.0;
        }
        return if (ax > 0x3F80_0000) == (uy >> 31 == 0) {
            f32::INFINITY
        } else {
            0.0
        };
    }
    if ay == 0 {
        return if ax > 0x7F80_0000 { x + x } else { 1.0 };
    }
    if uy == 0x3F80_0000 {
        return x;
    }
    let ypos = uy >> 31 == 0;
    // Sign of x^y for x < 0: negative for odd integer y.
    let odd_sign = |sx: u32| if odd_integer(y) == Some(true) { sx } else { 0 };
    if ax > 0x7F80_0000 {
        return x + x;
    }
    if ax == 0x7F80_0000 || ax == 0 {
        let big = (ax == 0) != ypos;
        let mag = if big { 0x7F80_0000 } else { 0 };
        return f32::from_bits(mag | odd_sign(ux & 0x8000_0000));
    }
    let mut sign = 0;
    if ux >> 31 == 1 {
        match odd_integer(y) {
            None => return f32::NAN,
            Some(odd) => sign = if odd { 0x8000_0000 } else { 0 },
        }
    }
    let w = f64::from(y) * log_core(f64::from(x));
    let v = if w > f64::from_bits(0x4056_2E43_0000_0000) {
        f32::INFINITY
    } else if w <= f64::from_bits(0xC059_D1DA_0000_0000) {
        0.0
    } else {
        exp_core(w)
    };
    f32::from_bits(v.to_bits() | sign)
}
