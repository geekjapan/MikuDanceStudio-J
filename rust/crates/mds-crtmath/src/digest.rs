//! Port of `tools/oracle/math_digest.hpp`: block digests of a float function
//! over all 2^32 float bit patterns, 4096 blocks of 2^20 inputs each.

pub const BLOCK_COUNT: u32 = 4096;
pub const BLOCK_SIZE: u32 = 1 << 20;

fn fmix32(mut h: u32) -> u32 {
    h ^= h >> 16;
    h = h.wrapping_mul(0x85EB_CA6B);
    h ^= h >> 13;
    h = h.wrapping_mul(0xC2B2_AE35);
    h ^ (h >> 16)
}

/// How the digest derives the arguments of a function from the input bits.
#[derive(Clone, Copy)]
pub enum Func {
    One(fn(f32) -> f32),
    /// `atan2f(y, x)`: the swept value is `y`.
    Atan2(fn(f32, f32) -> f32),
    Pow(fn(f32, f32) -> f32),
}

/// The second argument of a two-argument function for input bits `b`.
pub fn second_argument(atan2: bool, b: u32) -> f32 {
    let h = fmix32(b);
    let exponent = if atan2 {
        (((b >> 23) & 0xFF) as i32 + ((h >> 23) % 9) as i32 - 4).clamp(1, 254) as u32
    } else {
        123 + (h >> 23) % 9
    };
    f32::from_bits((h & 0x807F_FFFF) | (exponent << 23))
}

fn canonical(v: f32) -> u32 {
    let bits = v.to_bits();
    if bits & 0x7FFF_FFFF > 0x7F80_0000 {
        0x7FC0_0000
    } else {
        bits
    }
}

pub fn eval(f: Func, b: u32) -> f32 {
    let x = f32::from_bits(b);
    match f {
        Func::One(f) => f(x),
        Func::Atan2(f) => f(x, second_argument(true, b)),
        Func::Pow(f) => f(x, second_argument(false, b)),
    }
}

pub fn block_digest(f: Func, block: u32) -> u64 {
    let mut state: u64 = 0xCBF2_9CE4_8422_2325;
    let first = block * BLOCK_SIZE;
    for i in 0..BLOCK_SIZE {
        let b = first + i;
        state = (state ^ canonical(eval(f, b)) as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
        state ^= state >> 32;
    }
    state
}
