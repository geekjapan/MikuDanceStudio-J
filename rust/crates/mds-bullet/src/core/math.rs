//! Altered Rust translation of Bullet LinearMath; see mod.rs for the zlib notice.
//! Operation association is intentional. Do not use D3DX math or fused operations.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vec3(pub [f32; 3]);

impl Vec3 {
    pub const ZERO: Self = Self([0.0; 3]);

    pub fn add(self, rhs: Self) -> Self {
        Self(std::array::from_fn(|i| self.0[i] + rhs.0[i]))
    }

    pub fn sub(self, rhs: Self) -> Self {
        Self(std::array::from_fn(|i| self.0[i] - rhs.0[i]))
    }

    pub fn negate(self) -> Self {
        Self(self.0.map(|v| -v))
    }

    pub fn scale(self, scalar: f32) -> Self {
        Self(self.0.map(|v| v * scalar))
    }

    pub fn dot(self, rhs: Self) -> f32 {
        (self.0[0] * rhs.0[0] + self.0[1] * rhs.0[1]) + self.0[2] * rhs.0[2]
    }

    /// Solver SIMD rows accumulate in the reverse order of LinearMath's dot.
    pub fn dot_sse(self, rhs: Self) -> f32 {
        (self.0[2] * rhs.0[2] + self.0[1] * rhs.0[1]) + self.0[0] * rhs.0[0]
    }

    pub fn cross(self, rhs: Self) -> Self {
        let [x, y, z] = self.0;
        let [a, b, c] = rhs.0;
        Self([y * c - z * b, z * a - x * c, x * b - y * a])
    }

    pub fn length2(self) -> f32 {
        self.dot(self)
    }

    pub fn length(self) -> f32 {
        self.length2().sqrt()
    }

    /// Requires a nonzero vector, as does btVector3::normalize.
    pub fn normalize(self) -> Self {
        self.scale(1.0 / self.length())
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Quat(pub [f32; 4]);

impl Quat {
    pub const IDENTITY: Self = Self([0.0, 0.0, 0.0, 1.0]);

    /// Requires a nonzero axis, as does btQuaternion::setRotation.
    pub fn from_axis_angle(axis: Vec3, angle: f32) -> Self {
        let s = mds_crtmath::sinf(angle * 0.5) / axis.length();
        let [x, y, z] = axis.scale(s).0;
        Self([x, y, z, mds_crtmath::cosf(angle * 0.5)])
    }

    /// Bullet's inverse is the conjugate; rotation quaternions must be unit length.
    pub fn inverse(self) -> Self {
        let [x, y, z, w] = self.0;
        Self([-x, -y, -z, w])
    }

    pub fn rotate(self, vector: Vec3) -> Vec3 {
        let [x, y, z, w] = self.0;
        let [a, b, c] = vector.0;
        let q = Self([
            (w * a + y * c) - z * b,
            (w * b + z * a) - x * c,
            (w * c + x * b) - y * a,
            (-x * a - y * b) - z * c,
        ])
        .multiply(self.inverse());
        Vec3([q.0[0], q.0[1], q.0[2]])
    }

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
    pub const IDENTITY: Self = Self([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]);

    pub fn apply(self, vector: Vec3) -> Vec3 {
        Vec3(self.0.map(|row| Vec3(row).dot(vector)))
    }

    pub fn transpose(self) -> Self {
        Self(std::array::from_fn(|i| {
            std::array::from_fn(|j| self.0[j][i])
        }))
    }

    pub fn multiply(self, rhs: Self) -> Self {
        let columns = rhs.transpose();
        Self(
            self.0
                .map(|row| columns.0.map(|column| Vec3(column).dot(Vec3(row)))),
        )
    }

    /// Requires a nonsingular basis, as does btMatrix3x3::inverse.
    pub fn inverse(self) -> Self {
        let m = self.0;
        let cofac = |r1: usize, c1: usize, r2: usize, c2: usize| {
            m[r1][c1] * m[r2][c2] - m[r1][c2] * m[r2][c1]
        };
        let co = Vec3([cofac(1, 1, 2, 2), cofac(1, 2, 2, 0), cofac(1, 0, 2, 1)]);
        let s = 1.0 / Vec3(m[0]).dot(co);
        Self([
            [co.0[0] * s, cofac(0, 2, 2, 1) * s, cofac(0, 1, 1, 2) * s],
            [co.0[1] * s, cofac(0, 0, 2, 2) * s, cofac(0, 2, 1, 0) * s],
            [co.0[2] * s, cofac(0, 1, 2, 0) * s, cofac(0, 0, 1, 1) * s],
        ])
    }

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
    pub const IDENTITY: Self = Self {
        basis: Basis::IDENTITY,
        origin: Vec3::ZERO,
    };

    pub fn apply(self, point: Vec3) -> Vec3 {
        self.basis.apply(point).add(self.origin)
    }

    pub fn multiply(self, rhs: Self) -> Self {
        Self {
            basis: self.basis.multiply(rhs.basis),
            origin: self.apply(rhs.origin),
        }
    }

    /// Like btTransform::inverse, this requires an orthonormal rotation basis.
    pub fn inverse(self) -> Self {
        let basis = self.basis.transpose();
        Self {
            basis,
            origin: basis.apply(self.origin.negate()),
        }
    }

    pub fn inverse_apply(self, point: Vec3) -> Vec3 {
        self.basis.transpose().apply(point.sub(self.origin))
    }

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
