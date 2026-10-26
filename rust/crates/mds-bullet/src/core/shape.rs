//! Altered Rust translation of Bullet 2.75 collision shapes, including local patches.
//! See mod.rs for the retained Bullet zlib notice. Scaling is fixed at identity.

use super::math::{Transform, Vec3};

const CONVEX_MARGIN: f32 = 0.04;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Shape {
    Sphere { radius: f32 },
    Box { half_extents_without_margin: Vec3 },
    CapsuleY { radius: f32, half_height: f32 },
    StaticPlane { normal: Vec3, constant: f32 },
}

impl Shape {
    /// Raw construction also serves mds_mmd, which does not validate dimensions.
    pub(crate) fn box_shape(half_extents: Vec3) -> Self {
        Self::Box {
            half_extents_without_margin: Vec3(half_extents.0.map(|v| v * 1.0 - CONVEX_MARGIN)),
        }
    }

    /// Height is the distance between cap centers, excluding both hemispheres.
    pub(crate) fn capsule_y(radius: f32, height: f32) -> Self {
        Self::CapsuleY {
            radius,
            half_height: 0.5 * height,
        }
    }

    pub(crate) fn static_plane(normal: Vec3, constant: f32) -> Self {
        let inverse_length = 1.0 / normal.dot(normal).sqrt();
        Self::StaticPlane {
            normal: normal.scale(inverse_length),
            constant,
        }
    }

    pub fn margin(self) -> f32 {
        match self {
            Self::Sphere { radius } => radius,
            Self::Box { .. } | Self::CapsuleY { .. } => CONVEX_MARGIN,
            Self::StaticPlane { .. } => 0.0,
        }
    }

    pub fn local_inertia(self, mass: f32) -> Vec3 {
        match self {
            Self::Sphere { radius } => {
                // The vendored MMD patch rounds the double expression only once.
                let r = f64::from(radius);
                let element = (r * r * f64::from(mass) * f64::from(0.4_f32)) as f32;
                Vec3([element; 3])
            }
            Self::Box {
                half_extents_without_margin: half,
            } => {
                let [lx, ly, lz] = half.0.map(|v| 2.0 * (v + CONVEX_MARGIN));
                Vec3([
                    ((ly * ly + lz * lz) * mass) * 0.083_333_336,
                    ((lx * lx + lz * lz) * mass) * 0.083_333_336,
                    ((lx * lx + ly * ly) * mass) * 0.083_333_336,
                ])
            }
            Self::CapsuleY {
                radius,
                half_height,
            } => {
                let lx = 2.0 * (radius + CONVEX_MARGIN);
                let ly = 2.0 * ((radius + half_height) + CONVEX_MARGIN);
                let lz = lx;
                let (x2, y2, z2) = (lx * lx, ly * ly, lz * lz);
                // The vendored capsule coefficient is one ULP below the box coefficient.
                let scaled_mass = mass * f32::from_bits(0x3daa_aaaa);
                Vec3([
                    scaled_mass * (y2 + z2),
                    scaled_mass * (x2 + z2),
                    scaled_mass * (x2 + y2),
                ])
            }
            Self::StaticPlane { .. } => Vec3::ZERO,
        }
    }

    pub fn aabb(self, transform: Transform) -> (Vec3, Vec3) {
        let half = match self {
            Self::Sphere { radius } => {
                let center = transform.origin.0;
                return (
                    Vec3(center.map(|v| v - radius)),
                    Vec3(center.map(|v| v + radius)),
                );
            }
            Self::Box {
                half_extents_without_margin: half,
            } => Vec3(half.0.map(|v| v + CONVEX_MARGIN)),
            Self::CapsuleY {
                radius,
                half_height,
            } => Vec3([
                radius + CONVEX_MARGIN,
                (radius + half_height) + CONVEX_MARGIN,
                radius + CONVEX_MARGIN,
            ]),
            Self::StaticPlane { .. } => return (Vec3([-1e18; 3]), Vec3([1e18; 3])),
        };
        let extent = transform
            .basis
            .0
            .map(|row| Vec3(row.map(f32::abs)).dot(half));
        (
            Vec3(std::array::from_fn(|i| transform.origin.0[i] - extent[i])),
            Vec3(std::array::from_fn(|i| transform.origin.0[i] + extent[i])),
        )
    }
}
