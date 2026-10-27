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

/// Numeric constructor inputs. Shape inertia is calculated by the caller.
#[derive(Clone, Copy, Debug)]
pub struct BodyInit {
    pub mass: f32,
    pub local_inertia: Vec3,
    /// Already resolved center-of-mass transform; motion-state offsets are external.
    pub center_of_mass: Transform,
    pub linear_damping: f32,
    pub angular_damping: f32,
}

/// Initialized numeric state of the bounded btRigidBody kernel.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BodySnapshot {
    pub inverse_mass: f32,
    pub inverse_inertia_local: Vec3,
    pub inverse_inertia_world: Basis,
    pub world: Transform,
    pub interpolation_world: Transform,
    pub linear_velocity: Vec3,
    pub angular_velocity: Vec3,
    pub interpolation_linear_velocity: Vec3,
    pub interpolation_angular_velocity: Vec3,
    pub gravity_acceleration: Vec3,
    pub gravity_force: Vec3,
    pub total_force: Vec3,
    pub total_torque: Vec3,
    pub linear_damping: f32,
    pub angular_damping: f32,
    pub is_static: bool,
    pub is_kinematic: bool,
}

/// Altered translation of the supported-target btRigidBody numeric operations.
/// Sleeping, activation, motion states and world registration are outside this kernel.
pub struct RigidBody {
    state: BodySnapshot,
    linear_factor: Vec3,
    angular_factor: Vec3,
    friction: f32,
    restitution: f32,
}

impl RigidBody {
    pub fn new(init: BodyInit) -> Self {
        let mut body = Self {
            friction: 0.5,
            restitution: 0.0,
            linear_factor: Vec3([1.0; 3]),
            angular_factor: Vec3([1.0; 3]),
            state: BodySnapshot {
                inverse_mass: 0.0,
                inverse_inertia_local: Vec3::ZERO,
                inverse_inertia_world: Basis([[0.0; 3]; 3]),
                world: init.center_of_mass,
                interpolation_world: init.center_of_mass,
                linear_velocity: Vec3::ZERO,
                angular_velocity: Vec3::ZERO,
                interpolation_linear_velocity: Vec3::ZERO,
                interpolation_angular_velocity: Vec3::ZERO,
                gravity_acceleration: Vec3::ZERO,
                gravity_force: Vec3::ZERO,
                total_force: Vec3::ZERO,
                total_torque: Vec3::ZERO,
                linear_damping: init.linear_damping.clamp(0.0, 1.0),
                angular_damping: init.angular_damping.clamp(0.0, 1.0),
                is_static: true,
                is_kinematic: false,
            },
        };
        body.set_mass_properties(init.mass, init.local_inertia);
        body.update_inertia_tensor();
        body
    }

    pub fn contact_body(&self) -> super::contact::ContactBody {
        super::contact::ContactBody {
            world: self.state.world,
            friction: self.friction,
            restitution: self.restitution,
        }
    }

    pub fn set_friction(&mut self, friction: f32) {
        self.friction = friction;
    }

    pub fn set_restitution(&mut self, restitution: f32) {
        self.restitution = restitution;
    }

    pub fn linear_factor(&self) -> Vec3 {
        self.linear_factor
    }

    pub fn angular_factor(&self) -> Vec3 {
        self.angular_factor
    }

    pub fn set_linear_factor(&mut self, factor: Vec3) {
        self.linear_factor = factor;
    }

    pub fn set_angular_factor(&mut self, factor: Vec3) {
        self.angular_factor = factor;
    }

    pub fn snapshot(&self) -> BodySnapshot {
        self.state
    }

    /// Like setMassProps, this does not refresh world inertia or gravity force.
    pub fn set_mass_properties(&mut self, mass: f32, inertia: Vec3) {
        self.state.is_static = mass == 0.0;
        self.state.inverse_mass = if mass == 0.0 { 0.0 } else { 1.0 / mass };
        self.state.inverse_inertia_local =
            Vec3(inertia.0.map(|v| if v != 0.0 { 1.0 / v } else { 0.0 }));
    }

    pub fn update_inertia_tensor(&mut self) {
        let basis = self.state.world.basis;
        let local = self.state.inverse_inertia_local;
        let scaled = Basis(
            basis
                .0
                .map(|row| std::array::from_fn(|i| row[i] * local.0[i])),
        );
        self.state.inverse_inertia_world = scaled.multiply(basis.transpose());
    }

    pub fn set_gravity(&mut self, acceleration: Vec3) {
        if self.state.inverse_mass != 0.0 {
            self.state.gravity_force = acceleration.scale(1.0 / self.state.inverse_mass);
        }
        self.state.gravity_acceleration = acceleration;
    }

    pub fn add_force(&mut self, force: Vec3) {
        self.state.total_force = self.state.total_force.add(Vec3(std::array::from_fn(|i| {
            force.0[i] * self.linear_factor.0[i]
        })));
    }

    pub fn add_torque(&mut self, torque: Vec3) {
        self.state.total_torque = self.state.total_torque.add(Vec3(std::array::from_fn(|i| {
            torque.0[i] * self.angular_factor.0[i]
        })));
    }

    pub fn apply_gravity(&mut self) {
        if !self.state.is_static && !self.state.is_kinematic {
            self.add_force(self.state.gravity_force);
        }
    }

    pub fn integrate_velocities(&mut self, dt: f32) {
        if self.state.is_static || self.state.is_kinematic {
            return;
        }
        let s = &mut self.state;
        s.linear_velocity = s
            .linear_velocity
            .add(s.total_force.scale(s.inverse_mass * dt));
        s.angular_velocity = s
            .angular_velocity
            .add(s.inverse_inertia_world.apply(s.total_torque).scale(dt));
        let angular_speed = s.angular_velocity.length();
        let maximum = std::f32::consts::PI * 0.5;
        if angular_speed * dt > maximum {
            s.angular_velocity = s.angular_velocity.scale((maximum / dt) / angular_speed);
        }
    }

    pub fn apply_damping(&mut self, dt: f32) {
        self.state.linear_velocity = self
            .state
            .linear_velocity
            .scale(mds_crtmath::powf(1.0 - self.state.linear_damping, dt));
        self.state.angular_velocity = self
            .state
            .angular_velocity
            .scale(mds_crtmath::powf(1.0 - self.state.angular_damping, dt));
    }

    pub fn predict_transform(&self, dt: f32) -> Transform {
        self.state
            .world
            .integrate(self.state.linear_velocity, self.state.angular_velocity, dt)
    }

    pub fn set_center_of_mass_transform(&mut self, transform: Transform) {
        self.state.interpolation_world = if self.state.is_static || self.state.is_kinematic {
            self.state.world
        } else {
            transform
        };
        self.state.interpolation_linear_velocity = self.state.linear_velocity;
        self.state.interpolation_angular_velocity = self.state.angular_velocity;
        self.state.world = transform;
        self.update_inertia_tensor();
    }

    pub fn clear_forces(&mut self) {
        self.state.total_force = Vec3::ZERO;
        self.state.total_torque = Vec3::ZERO;
    }

    pub fn set_linear_velocity(&mut self, velocity: Vec3) {
        self.state.linear_velocity = velocity;
    }

    pub fn set_angular_velocity(&mut self, velocity: Vec3) {
        self.state.angular_velocity = velocity;
    }

    pub fn set_kinematic(&mut self, kinematic: bool) {
        self.state.is_kinematic = kinematic;
    }
}
