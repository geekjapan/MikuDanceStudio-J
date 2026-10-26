//! Altered Rust translation of Bullet LinearMath; see mod.rs for the zlib notice.
//! Operation association is intentional. Do not use D3DX math or fused operations.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vec3(pub [f32; 3]);

impl Vec3 {
    pub const ZERO: Self = Self([0.0; 3]);

    pub fn add(self, rhs: Self) -> Self {
        Self(std::array::from_fn(|i| self.0[i] + rhs.0[i]))
    }

    pub fn scale(self, scalar: f32) -> Self {
        Self(self.0.map(|v| v * scalar))
    }

    pub fn dot(self, rhs: Self) -> f32 {
        (self.0[0] * rhs.0[0] + self.0[1] * rhs.0[1]) + self.0[2] * rhs.0[2]
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Quat(pub [f32; 4]);

impl Quat {
    pub fn length2(self) -> f32 {
        let [x, y, z, w] = self.0;
        ((x * x + y * y) + z * z) + w * w
    }

    pub fn normalize(self) -> Self {
        let inverse_length = 1.0 / self.length2().sqrt();
        Self(self.0.map(|v| v * inverse_length))
    }

    pub fn multiply(self, rhs: Self) -> Self {
        let [x, y, z, w] = self.0;
        let [a, b, c, d] = rhs.0;
        Self([
            ((w * a + x * d) + y * c) - z * b,
            ((w * b + y * d) + z * a) - x * c,
            ((w * c + z * d) + x * b) - y * a,
            ((w * d - x * a) - y * b) - z * c,
        ])
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Basis(pub [[f32; 3]; 3]);

impl Basis {
    pub fn from_rotation(q: Quat) -> Self {
        let [x, y, z, w] = q.0;
        let s = 2.0 / q.length2();
        let (xs, ys, zs) = (x * s, y * s, z * s);
        let (wx, wy, wz) = (w * xs, w * ys, w * zs);
        let (xx, xy, xz) = (x * xs, x * ys, x * zs);
        let (yy, yz, zz) = (y * ys, y * zs, z * zs);
        Self([
            [1.0 - (yy + zz), xy - wz, xz + wy],
            [xy + wz, 1.0 - (xx + zz), yz - wx],
            [xz - wy, yz + wx, 1.0 - (xx + yy)],
        ])
    }

    pub fn rotation(self) -> Quat {
        let m = self.0;
        let trace = (m[0][0] + m[1][1]) + m[2][2];
        let mut q = [0.0; 4];
        if trace > 0.0 {
            let mut s = (trace + 1.0).sqrt();
            q[3] = s * 0.5;
            s = 0.5 / s;
            q[0] = (m[2][1] - m[1][2]) * s;
            q[1] = (m[0][2] - m[2][0]) * s;
            q[2] = (m[1][0] - m[0][1]) * s;
        } else {
            let i = if m[0][0] < m[1][1] {
                if m[1][1] < m[2][2] {
                    2
                } else {
                    1
                }
            } else if m[0][0] < m[2][2] {
                2
            } else {
                0
            };
            let j = (i + 1) % 3;
            let k = (i + 2) % 3;
            let mut s = (((m[i][i] - m[j][j]) - m[k][k]) + 1.0).sqrt();
            q[i] = s * 0.5;
            s = 0.5 / s;
            q[3] = (m[k][j] - m[j][k]) * s;
            q[j] = (m[j][i] + m[i][j]) * s;
            q[k] = (m[k][i] + m[i][k]) * s;
        }
        Quat(q)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Transform {
    pub basis: Basis,
    pub origin: Vec3,
}

impl Transform {
    pub fn integrate(self, linear: Vec3, angular: Vec3, dt: f32) -> Self {
        let mut angle = angular.dot(angular).sqrt();
        // Bullet's SIMD_PI is converted to f32 before the threshold arithmetic.
        let threshold = 0.5 * (std::f32::consts::PI * 0.5);
        if angle * dt > threshold {
            angle = threshold / dt;
        }
        let factor = if angle < 0.001 {
            0.5 * dt - (((dt * dt) * dt) * 0.020_833_334) * angle * angle
        } else {
            mds_crtmath::sinf((0.5 * angle) * dt) / angle
        };
        let axis = angular.scale(factor).0;
        let delta = Quat([
            axis[0],
            axis[1],
            axis[2],
            mds_crtmath::cosf((angle * dt) * 0.5),
        ]);
        Self {
            origin: self.origin.add(linear.scale(dt)),
            basis: Basis::from_rotation(delta.multiply(self.basis.rotation()).normalize()),
        }
    }
}
