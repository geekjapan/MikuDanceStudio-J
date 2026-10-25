//! sinf, cosf, tanf: the UCRT FMA3 paths. Evaluated in f64 with fused
//! multiply-adds where the FMA3 code fuses. Structure after AMD AOCL-LibM.

use crate::tables::TWO_BY_PI_BITS;

const TWO_BY_PI: f64 = f64::from_bits(0x3FE4_5F30_6DC9_C883);
const PIBY2_1: f64 = f64::from_bits(0x3FF9_21FB_5440_0000);
const PIBY2_1TAIL: f64 = f64::from_bits(0x3DD0_B461_1A62_6331);
const PIBY2: f64 = f64::from_bits(0x3FF9_21FB_5444_2D18);
const PI_BY_4_BITS: u64 = 0x3FE9_21FB_5444_2D18;
const TWO_M7_BITS: u64 = 0x3F80_0000_0000_0000;
const TWO_M13_BITS: u64 = 0x3F20_0000_0000_0000;
/// Cody-Waite below, Payne-Hanek above. Any cut in [5.88e8, 3.3e9] gives the
/// same results for all floats; the UCRT constant is unknown, 2^30 is used.
const PAYNE_HANEK_BITS: u64 = 0x41D0_0000_0000_0000;

// Taylor coefficients of sin and cos.
const S: [f64; 4] = [
    f64::from_bits(0xBFC5_5555_5555_5555),
    f64::from_bits(0x3F81_1111_1111_1111),
    f64::from_bits(0xBF2A_01A0_1A01_A01A),
    f64::from_bits(0x3EC7_1DE3_A556_C734),
];
const C: [f64; 4] = [
    f64::from_bits(0x3FA5_5555_5555_5555),
    f64::from_bits(0xBF56_C16C_16C1_6C16),
    f64::from_bits(0x3EFA_01A0_1A01_A019),
    f64::from_bits(0xBE92_7E4F_B778_9F5C),
];
const TAN: [f64; 5] = [
    f64::from_bits(0x3FD8_A8B0_DA56_CB17),
    f64::from_bits(0x3F91_9DBA_6EFD_6AAD),
    f64::from_bits(0x3FF2_7E84_A3E7_3A2E),
    f64::from_bits(0xBFE0_7266_D7B3_511B),
    f64::from_bits(0x3F92_E290_03C6_92D9),
];

fn sin_poly(x: f64) -> f64 {
    let x2 = x * x;
    let p = x2.mul_add(x2.mul_add(x2.mul_add(S[3], S[2]), S[1]), S[0]);
    (x2 * x).mul_add(p, x)
}

fn cos_poly(x: f64) -> f64 {
    let x2 = x * x;
    let p = x2.mul_add(x2.mul_add(x2.mul_add(C[3], C[2]), C[1]), C[0]);
    (x2 * x2).mul_add(p, 1.0 - 0.5 * x2)
}

fn tan_poly(x: f64) -> f64 {
    let x2 = x * x;
    let num = (-x2).mul_add(TAN[1], TAN[0]);
    let den = x2.mul_add(x2.mul_add(TAN[4], TAN[3]), TAN[2]);
    (x2 * x).mul_add(num / den, x)
}

/// |x| > pi/4 into r in about [-pi/4, pi/4] and the quadrant.
fn reduce(ax: f64) -> (f64, u32) {
    if ax.to_bits() >= PAYNE_HANEK_BITS {
        return payne_hanek(ax);
    }
    let n = ax.mul_add(TWO_BY_PI, 0.5) as i32;
    let nd = f64::from(n);
    let rhead = (-nd).mul_add(PIBY2_1, ax);
    (rhead - nd * PIBY2_1TAIL, (n & 3) as u32)
}

fn pi_bits(i: usize) -> u64 {
    u64::from_le_bytes(TWO_BY_PI_BITS[i..i + 8].try_into().unwrap())
}

/// Payne-Hanek reduction of a finite ax >= 2^30: 192 bits of 2/pi times the
/// mantissa, then r = (x + xx) * pi/2 in double-double, rounded to double.
fn payne_hanek(ax: f64) -> (f64, u32) {
    let ux = ax.to_bits();
    let xexp = (ux >> 52) as i64 - 1023;
    let last = (134 - (xexp >> 3)) as usize;
    let mant = u128::from((ux & 0x000F_FFFF_FFFF_FFFF) | (1 << 52));
    let p0 = u128::from(pi_bits(last)) * mant;
    let p1 = u128::from(pi_bits(last + 8)) * mant + (p0 >> 64);
    let mut lo = p0 as u64;
    let mut mid = p1 as u64;
    let mut hi = ((p1 >> 64) as u64).wrapping_add((u128::from(pi_bits(last + 16)) * mant) as u64);

    // The binary point sits 54 - (xexp & 7) bits above the bottom of hi.
    let resexp = (xexp & 7) as u32;
    let half = (hi >> (53 - resexp)) & 1;
    let region = (((hi >> (54 - resexp)) + half) & 3) as u32;
    let mut sign = 0u64;
    if half == 1 {
        hi = !hi;
        mid = !mid;
        lo = !lo;
        sign = 1 << 63;
    }
    let int_bits = resexp + 10;
    hi = (hi << int_bits) >> int_bits;
    let mut e = i64::from(int_bits) - 64;
    if hi == 0 {
        hi = mid;
        mid = lo;
        lo = 0;
        e -= 64;
    }
    let hsb = 63 - i64::from(hi.leading_zeros());
    e += hsb;
    let shift = hsb - 52;
    if shift > 0 {
        let s = shift as u32;
        mid = (mid >> s) | (hi << (64 - s));
        hi >>= s;
    } else if shift < 0 {
        let s = (-shift) as u32;
        hi = (hi << s) | (mid >> (64 - s));
        mid = (mid << s) | (lo >> (64 - s));
    }
    let be = (e + 1023) as u64;
    let x = f64::from_bits((hi & !(1 << 52)) | sign | (be << 52));
    let mid_hsb = if mid == 0 {
        0
    } else {
        63 - u64::from(mid.leading_zeros())
    };
    let up = 64 - mid_hsb;
    let xx = f64::from_bits(((mid << (up & 63)) >> 12) | sign | (be.wrapping_sub(up + 52) << 52));

    let part1 = f64::from_bits(0x3FF9_21FB_5000_0000);
    let part2 = f64::from_bits(0x3E51_10B4_6000_0000);
    let part3 = f64::from_bits(0x3C91_A626_3314_5C06);
    let hx = f64::from_bits(x.to_bits() & 0xFFFF_FFFF_F800_0000);
    let tx = x - hx;
    let c = x * PIBY2;
    let mut cc = hx * part1 - c;
    cc = tx.mul_add(part1, cc);
    cc = hx.mul_add(part2, cc);
    cc = tx.mul_add(part2, cc);
    cc += x.mul_add(part3, xx * PIBY2);
    (c + cc, region)
}

pub fn sinf(x: f32) -> f32 {
    if x.to_bits() & 0x7F80_0000 == 0x7F80_0000 {
        return f32::NAN;
    }
    let xd = f64::from(x);
    let ax = xd.abs();
    let ab = ax.to_bits();
    if ab > PI_BY_4_BITS {
        let (r, region) = reduce(ax);
        let v = if region & 1 == 1 {
            cos_poly(r)
        } else {
            sin_poly(r)
        };
        return (if (region >= 2) != (x < 0.0) { -v } else { v }) as f32;
    }
    if ab >= TWO_M7_BITS {
        return sin_poly(xd) as f32;
    }
    if ab >= TWO_M13_BITS {
        return (-(xd * xd * xd)).mul_add(-S[0], xd) as f32;
    }
    x
}

pub fn cosf(x: f32) -> f32 {
    if x.to_bits() & 0x7F80_0000 == 0x7F80_0000 {
        return f32::NAN;
    }
    let ax = f64::from(x).abs();
    let ab = ax.to_bits();
    if ab > PI_BY_4_BITS {
        let (r, region) = reduce(ax);
        let v = if region & 1 == 1 {
            sin_poly(r)
        } else {
            cos_poly(r)
        };
        return (if region == 1 || region == 2 { -v } else { v }) as f32;
    }
    if ab >= TWO_M7_BITS {
        return cos_poly(ax) as f32;
    }
    if ab >= TWO_M13_BITS {
        return (-(ax * 0.5)).mul_add(ax, 1.0) as f32;
    }
    1.0
}

pub fn tanf(x: f32) -> f32 {
    if x.to_bits() & 0x7F80_0000 == 0x7F80_0000 {
        return f32::NAN;
    }
    let xd = f64::from(x);
    let ax = xd.abs();
    let ab = ax.to_bits();
    if ab > PI_BY_4_BITS {
        let (r, region) = reduce(ax);
        let t = tan_poly(r);
        let v = if region & 1 == 1 { -1.0 / t } else { t };
        return (if x < 0.0 { -v } else { v }) as f32;
    }
    if ab >= TWO_M13_BITS {
        return tan_poly(xd) as f32;
    }
    x
}
