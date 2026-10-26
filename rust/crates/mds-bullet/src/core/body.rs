//! Altered Rust translation of the noncolliding btRigidBody integration path.
//! See mod.rs for the zlib notice.

use super::math::{Basis, Quat, Transform, Vec3};
use super::time::Step;
use super::InvalidArgument;

/// A dynamic sphere with no contacts, joints, torque or externally set velocity.
/// shortcut: activation and sleeping are absent, replace with full rigid-body
/// activation before enabling this core for general worlds.
pub struct FreeBody {
    inverse_mass: f32,
    gravity_force: Vec3,
    linear_damping: f32,
    linear_velocity: Vec3,
    world: Transform,
    motion: Transform,
}

impl FreeBody {
    pub fn sphere(
        radius: f32,
        mass: f32,
        damping: f32,
        gravity: Vec3,
        origin: Vec3,
        rotation: Quat,
    ) -> Result<Self, InvalidArgument> {
        if !radius.is_finite()
            || radius <= 0.0
            || !mass.is_finite()
            || mass <= 0.0
            || !damping.is_finite()
            || !gravity
                .0
                .iter()
                .chain(origin.0.iter())
                .chain(rotation.0.iter())
                .all(|v| v.is_finite())
            || rotation.length2() <= 1e-12
        {
            return Err(InvalidArgument);
        }
        let inverse_mass = 1.0 / mass;
        let world = Transform {
            basis: Basis::from_rotation(rotation),
            origin,
        };
        Ok(Self {
            inverse_mass,
            gravity_force: gravity.scale(1.0 / inverse_mass),
            linear_damping: damping.clamp(0.0, 1.0),
            linear_velocity: Vec3::ZERO,
            world,
            motion: world,
        })
    }

    /// Gravity is added once and forces are cleared once per outer step call.
    pub fn step(&mut self, step: Step) {
        let total_force = Vec3::ZERO.add(self.gravity_force);
        for _ in 0..step.executed {
            self.linear_velocity = self
                .linear_velocity
                .add(total_force.scale(self.inverse_mass * step.dt));
            self.linear_velocity = self
                .linear_velocity
                .scale(mds_crtmath::powf(1.0 - self.linear_damping, step.dt));
            self.world = self
                .world
                .integrate(self.linear_velocity, Vec3::ZERO, step.dt);
        }
        // The shim reads the motion state, extrapolated by the remaining time.
        self.motion = self
            .world
            .integrate(self.linear_velocity, Vec3::ZERO, step.remainder);
    }

    pub fn transform(&self) -> Transform {
        self.motion
    }

    /// Append the shim's 15 little-endian float words in creation order.
    pub fn hash_into(&self, hash: &mut u64) {
        let words = self
            .motion
            .basis
            .0
            .into_iter()
            .flatten()
            .chain(self.motion.origin.0)
            .chain([self.linear_velocity.0[0], 0.0, 0.0]);
        for word in words {
            for byte in word.to_le_bytes() {
                *hash = (*hash ^ u64::from(byte)).wrapping_mul(1_099_511_628_211);
            }
        }
    }
}
