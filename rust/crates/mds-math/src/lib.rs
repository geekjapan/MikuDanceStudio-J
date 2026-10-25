//! Rust equivalents of the D3DX9 math functions that MikuDanceStudio calls.
//!
//! The target is bit equality with `d3dx9_43.dll` on x64 Intel, as recorded in
//! `tests/fixtures/rust/math/d3dx-vectors.txt`. The orders of float operations
//! and the reciprocal and reciprocal-square-root approximations below were
//! worked out from that data alone. Everything is plain `f32` arithmetic (Rust
//! never fuses multiply and add), so results do not depend on the host CPU.
//!
//! Matrices are row-major like `D3DXMATRIX`. Quaternions are `[x, y, z, w]`.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vec3(pub [f32; 3]);
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Quat(pub [f32; 4]);
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Mat4(pub [f32; 16]);

// ---------------------------------------------------------------------------
// Hardware approximations. D3DX takes a 12-bit reciprocal or reciprocal square
// root estimate and refines it with one Newton step; the estimate comes from the
// table of the Intel CPU that wrote the vectors. The table is modelled as: bucket
// the mantissa, take the bucket centre, and round the exact result to 13 bits.
// Only normal, non-zero inputs are modelled; other inputs are not covered by
// the vectors.
// ---------------------------------------------------------------------------

fn pow2(k: i32) -> f64 {
    f64::from_bits(((k + 1023) as u64) << 52)
}

/// Estimate of `1 / x`: 2048 buckets over the mantissa.
fn rcp_estimate(x: f32) -> f32 {
    let bits = x.to_bits();
    let exp = ((bits >> 23) & 0xff) as i32;
    if exp == 0 {
        return f32::INFINITY.copysign(x);
    }
    if exp == 255 {
        return if x.is_nan() { x } else { 0.0f32.copysign(x) };
    }
    let centre = 1.0 + (f64::from((bits & 0x7f_ffff) >> 12) + 0.5) / 2048.0;
    let q = (8192.0 / centre).round_ties_even();
    ((q / 8192.0 * pow2(127 - exp)) as f32).copysign(x)
}

/// Estimate of `1 / sqrt(x)` for `x > 0`: 1024 buckets for each exponent parity.
fn rsqrt_estimate(x: f32) -> f32 {
    let bits = x.to_bits();
    let exp = ((bits >> 23) & 0xff) as i32;
    if exp == 0 {
        return f32::INFINITY;
    }
    if exp == 255 || x < 0.0 {
        return if x == f32::INFINITY { 0.0 } else { f32::NAN };
    }
    let mut e = exp - 127;
    let mut centre = 1.0 + (f64::from((bits & 0x7f_ffff) >> 13) + 0.5) / 1024.0;
    if e & 1 != 0 {
        centre *= 2.0;
        e -= 1;
    }
    let q = (8192.0 / centre.sqrt()).round_ties_even();
    (q / 8192.0 * pow2(-e / 2)) as f32
}

/// `1 / x` as D3DX computes it: estimate, then `r + r - x * r * r`.
fn rcp(x: f32) -> f32 {
    let r = rcp_estimate(x);
    (r + r) - x * (r * r)
}

/// `1 / sqrt(x)` as D3DX computes it: estimate, then `0.5 * r * (3 - x * r * r)`.
fn rsqrt(x: f32) -> f32 {
    let r = rsqrt_estimate(x);
    (0.5 * r) * (3.0 - (x * r) * r)
}

// ---------------------------------------------------------------------------
// Vec3, Quat
// ---------------------------------------------------------------------------

impl Vec3 {
    /// `D3DXVec3Normalize`. A zero (or underflowing) vector gives zeros.
    pub fn normalize(self) -> Vec3 {
        let [x, y, z] = self.0;
        let dot = (x * x + y * y) + z * z;
        if dot == 0.0 {
            return Vec3([0.0; 3]);
        }
        let r = rsqrt(dot);
        Vec3([x * r, y * r, z * r])
    }
}

impl Quat {
    /// `D3DXQuaternionMultiply(out, a, b)`. The result is the Hamilton product `b * a`.
    pub fn multiply(a: Quat, b: Quat) -> Quat {
        let [ax, ay, az, aw] = a.0;
        let [bx, by, bz, bw] = b.0;
        Quat([
            (bw * ax + bx * aw) + (by * az - bz * ay),
            (bw * ay - bx * az) + (by * aw + bz * ax),
            (bw * az + bx * ay) + (bz * aw - by * ax),
            (bw * aw - bx * ax) + (-(by * ay) - bz * az),
        ])
    }

    /// `D3DXQuaternionNormalize`. A zero quaternion gives zeros.
    pub fn normalize(self) -> Quat {
        let [x, y, z, w] = self.0;
        let dot = ((x * x + y * y) + z * z) + w * w;
        if dot == 0.0 {
            return Quat([0.0; 4]);
        }
        let r = rsqrt(dot);
        Quat([x * r, y * r, z * r, w * r])
    }

    /// `D3DXQuaternionToAxisAngle`. The axis is `(x, y, z)` unchanged. The angle is
    /// `2 * acos(w)`, and NaN with the x86 default NaN bits when `|w| > 1`.
    pub fn to_axis_angle(self) -> (Vec3, f32) {
        let [x, y, z, w] = self.0;
        (Vec3([x, y, z]), 2.0 * acosf(w))
    }

    /// `D3DXQuaternionRotationMatrix`.
    pub fn from_matrix(m: &Mat4) -> Quat {
        let m = &m.0;
        let g = |i: usize, j: usize| m[i * 4 + j];
        let trace = ((g(0, 0) + g(1, 1)) + g(2, 2)) + 1.0;
        if trace > 1.0 {
            let s = trace.sqrt();
            let r = 0.5 / s;
            return Quat([
                (g(1, 2) - g(2, 1)) * r,
                (g(2, 0) - g(0, 2)) * r,
                (g(0, 1) - g(1, 0)) * r,
                s * 0.5,
            ]);
        }
        let mut k = 0;
        for i in 1..3 {
            if g(i, i) > g(k, k) {
                k = i;
            }
        }
        // The vectors do not tell the grouping of the radicand apart; any of
        // `(1 + a) - (b + c)`, `1 + (a - (b + c))`, `(1 - b) - (c - a)` fits.
        let radicand = |a: f32, b: f32, c: f32| (1.0 + a) - (b + c);
        match k {
            0 => {
                let s = radicand(g(0, 0), g(1, 1), g(2, 2)).sqrt();
                let r = 0.5 / s;
                Quat([
                    s * 0.5,
                    (g(0, 1) + g(1, 0)) * r,
                    (g(0, 2) + g(2, 0)) * r,
                    (g(1, 2) - g(2, 1)) * r,
                ])
            }
            1 => {
                let s = radicand(g(1, 1), g(0, 0), g(2, 2)).sqrt();
                let r = 0.5 / s;
                Quat([
                    (g(0, 1) + g(1, 0)) * r,
                    s * 0.5,
                    (g(1, 2) + g(2, 1)) * r,
                    (g(2, 0) - g(0, 2)) * r,
                ])
            }
            _ => {
                let s = radicand(g(2, 2), g(0, 0), g(1, 1)).sqrt();
                let r = 0.5 / s;
                Quat([
                    (g(0, 2) + g(2, 0)) * r,
                    (g(1, 2) + g(2, 1)) * r,
                    s * 0.5,
                    (g(0, 1) - g(1, 0)) * r,
                ])
            }
        }
    }
}

// ---------------------------------------------------------------------------
// acosf. The D3DX result is the float version of the classic fdlibm algorithm
// evaluated with `f64` intermediates; only the square root is a real `f32`
// (`sqrtf`). The constants are the `f32` values of the fdlibm table.
// ---------------------------------------------------------------------------

#[allow(clippy::excessive_precision)]
fn acosf(x: f32) -> f32 {
    const PI_HI: f64 = 3.1415925026e+00_f32 as f64; // 0x40490fda
    const PIO2_HI: f64 = 1.5707962513e+00_f32 as f64; // 0x3fc90fda
    const PIO2_LO: f64 = 7.5497894159e-08_f32 as f64; // 0x33a22168
    const P_S0: f64 = 1.6666586697e-01_f32 as f64;
    const P_S1: f64 = -4.2743422091e-02_f32 as f64;
    const P_S2: f64 = -8.6563630030e-03_f32 as f64;
    const Q_S1: f64 = -7.0662963390e-01_f32 as f64;
    if x.is_nan() || x.abs() > 1.0 {
        return f32::from_bits(0xffc0_0000);
    }
    let xd = f64::from(x);
    let ratio = |z: f64| z * (P_S0 + z * (P_S1 + z * P_S2)) / (1.0 + z * Q_S1);
    if x.abs() == 1.0 {
        return if x > 0.0 {
            0.0
        } else {
            (PI_HI + f64::from((2.0 * PIO2_LO) as f32)) as f32
        };
    }
    if x.abs() < 0.5 {
        if x.abs() <= f32::from_bits(0x2300_0000) {
            return (PIO2_HI + PIO2_LO) as f32;
        }
        let r = ratio(xd * xd);
        return (PIO2_HI - (xd - (PIO2_LO - xd * r))) as f32;
    }
    if x < 0.0 {
        let z = (1.0 + xd) * 0.5;
        let s = f64::from(z.sqrt() as f32);
        let w = ratio(z) * s - PIO2_LO;
        return (PI_HI - 2.0 * (s + w)) as f32;
    }
    let z = (1.0 - xd) * 0.5;
    let s = f64::from(z.sqrt() as f32);
    let df = f64::from(f32::from_bits((s as f32).to_bits() & 0xffff_f000));
    let c = (z - df * df) / (s + df);
    let w = ratio(z) * s + c;
    (2.0 * (df + w)) as f32
}

// ---------------------------------------------------------------------------
// Mat4
// ---------------------------------------------------------------------------

type Lanes = [f32; 4];

fn shuf(a: Lanes, b: Lanes, imm: u8) -> Lanes {
    let i = |n: u8| usize::from((imm >> n) & 3);
    [a[i(0)], a[i(2)], b[i(4)], b[i(6)]]
}
fn mul4(a: Lanes, b: Lanes) -> Lanes {
    [a[0] * b[0], a[1] * b[1], a[2] * b[2], a[3] * b[3]]
}
fn add4(a: Lanes, b: Lanes) -> Lanes {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3]]
}
fn sub4(a: Lanes, b: Lanes) -> Lanes {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2], a[3] - b[3]]
}

impl Mat4 {
    pub const IDENTITY: Mat4 = Mat4([
        1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
    ]);

    /// `D3DXMatrixMultiply(out, a, b)`: `out = a * b`. Rows 0 and 3 of the result add
    /// their four products as `(p0 + p1) + (p2 + p3)`, rows 1 and 2 add them in sequence.
    pub fn multiply(a: &Mat4, b: &Mat4) -> Mat4 {
        let mut out = [0.0f32; 16];
        for i in 0..4 {
            for j in 0..4 {
                let p: [f32; 4] = std::array::from_fn(|k| a.0[i * 4 + k] * b.0[k * 4 + j]);
                out[i * 4 + j] = if i == 0 || i == 3 {
                    (p[0] + p[1]) + (p[2] + p[3])
                } else {
                    ((p[0] + p[1]) + p[2]) + p[3]
                };
            }
        }
        Mat4(out)
    }

    /// `D3DXMatrixInverse`: the inverse and the determinant, or `None` when the
    /// determinant is zero. This is the Cramer's rule routine with SSE lanes and a
    /// reciprocal estimate, so near-singular matrices lose a few low bits.
    pub fn inverse(&self) -> Option<(Mat4, f32)> {
        let s = &self.0;
        let t = [s[0], s[1], s[4], s[5]];
        let mut row1 = [s[8], s[9], s[12], s[13]];
        let row0 = shuf(t, row1, 0x88);
        row1 = shuf(row1, t, 0xDD);
        let t = [s[2], s[3], s[6], s[7]];
        let mut row3 = [s[10], s[11], s[14], s[15]];
        let mut row2 = shuf(t, row3, 0x88);
        row3 = shuf(row3, t, 0xDD);

        let p = mul4(row2, row3);
        let mut t = shuf(p, p, 0xB1);
        let mut minor0 = mul4(row1, t);
        let mut minor1 = mul4(row0, t);
        t = shuf(t, t, 0x4E);
        minor0 = sub4(mul4(row1, t), minor0);
        minor1 = sub4(mul4(row0, t), minor1);
        minor1 = shuf(minor1, minor1, 0x4E);

        let p = mul4(row1, row2);
        t = shuf(p, p, 0xB1);
        minor0 = add4(mul4(row3, t), minor0);
        let mut minor3 = mul4(row0, t);
        t = shuf(t, t, 0x4E);
        minor0 = sub4(minor0, mul4(row3, t));
        minor3 = sub4(mul4(row0, t), minor3);
        minor3 = shuf(minor3, minor3, 0x4E);

        let p = mul4(shuf(row1, row1, 0x4E), row3);
        t = shuf(p, p, 0xB1);
        row2 = shuf(row2, row2, 0x4E);
        minor0 = add4(mul4(row2, t), minor0);
        let mut minor2 = mul4(row0, t);
        t = shuf(t, t, 0x4E);
        minor0 = sub4(minor0, mul4(row2, t));
        minor2 = sub4(mul4(row0, t), minor2);
        minor2 = shuf(minor2, minor2, 0x4E);

        let p = mul4(row0, row1);
        t = shuf(p, p, 0xB1);
        minor2 = add4(mul4(row3, t), minor2);
        minor3 = sub4(mul4(row2, t), minor3);
        t = shuf(t, t, 0x4E);
        minor2 = sub4(mul4(row3, t), minor2);
        minor3 = sub4(minor3, mul4(row2, t));

        let p = mul4(row0, row3);
        t = shuf(p, p, 0xB1);
        minor1 = sub4(minor1, mul4(row2, t));
        minor2 = add4(mul4(row1, t), minor2);
        t = shuf(t, t, 0x4E);
        minor1 = add4(mul4(row2, t), minor1);
        minor2 = sub4(minor2, mul4(row1, t));

        let p = mul4(row0, row2);
        t = shuf(p, p, 0xB1);
        minor1 = add4(mul4(row3, t), minor1);
        minor3 = sub4(minor3, mul4(row1, t));
        t = shuf(t, t, 0x4E);
        minor1 = sub4(minor1, mul4(row3, t));
        minor3 = add4(mul4(row1, t), minor3);

        let d = mul4(row0, minor0);
        let d = add4(shuf(d, d, 0x4E), d);
        let det = shuf(d, d, 0xB1)[0] + d[0];
        if det == 0.0 {
            return None;
        }
        let r = rcp(det);
        let mut out = [0.0f32; 16];
        for (k, m) in [minor0, minor1, minor2, minor3].iter().enumerate() {
            for l in 0..4 {
                out[k * 4 + l] = r * m[l];
            }
        }
        Some((Mat4(out), det))
    }

    /// `D3DXMatrixTranslation`.
    pub fn translation(x: f32, y: f32, z: f32) -> Mat4 {
        let mut m = Mat4::IDENTITY;
        m.0[12..15].copy_from_slice(&[x, y, z]);
        m
    }

    /// `D3DXMatrixRotationX`.
    pub fn rotation_x(angle: f32) -> Mat4 {
        let (s, c) = sin_cos(angle);
        let mut m = Mat4::IDENTITY;
        (m.0[5], m.0[6], m.0[9], m.0[10]) = (c, s, -s, c);
        m
    }

    /// `D3DXMatrixRotationY`.
    pub fn rotation_y(angle: f32) -> Mat4 {
        let (s, c) = sin_cos(angle);
        let mut m = Mat4::IDENTITY;
        (m.0[0], m.0[2], m.0[8], m.0[10]) = (c, -s, s, c);
        m
    }

    /// `D3DXMatrixRotationZ`.
    pub fn rotation_z(angle: f32) -> Mat4 {
        let (s, c) = sin_cos(angle);
        let mut m = Mat4::IDENTITY;
        (m.0[0], m.0[1], m.0[4], m.0[5]) = (c, s, -s, c);
        m
    }

    /// `D3DXMatrixRotationQuaternion`. The quaternion is used as given, not normalized.
    pub fn rotation_quaternion(q: Quat) -> Mat4 {
        let [x, y, z, w] = q.0;
        let diag = |a: f32, b: f32| (1.0 - 2.0 * (a * a)) - 2.0 * (b * b);
        let pair = |a: f32, b: f32| 2.0 * (a * b);
        Mat4([
            diag(y, z),
            pair(x, y) + pair(z, w),
            pair(x, z) - pair(y, w),
            0.0,
            pair(x, y) - pair(z, w),
            diag(x, z),
            pair(y, z) + pair(x, w),
            0.0,
            pair(x, z) + pair(y, w),
            pair(y, z) - pair(x, w),
            diag(x, y),
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
        ])
    }
}

/// Sine and cosine rounded to `f32` from `f64` results, which matches D3DX on every
/// vector. `libm` keeps the `f64` values identical on every host.
fn sin_cos(angle: f32) -> (f32, f32) {
    let a = f64::from(angle);
    (libm::sin(a) as f32, libm::cos(a) as f32)
}
