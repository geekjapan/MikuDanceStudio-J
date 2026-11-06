//! Rust implementation of the vendored Bullet 2.75 public world.
//!
//! A [`World`] owns every body and joint made through it and frees them when
//! dropped. [`BodyId`] and [`JointId`] are plain indices tagged with their
//! world, so they carry no lifetime and cannot be used on another world.
//! Quaternions are `[x, y, z, w]`.

use std::fmt;
use std::marker::PhantomData;
use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};

#[allow(dead_code)]
mod core;

use core::dbvt::DbvtPolicy;
use core::discrete_dynamics_world::{DiscreteDynamicsWorld, StepError};
use core::math::{Quat, Vec3};
use core::world_objects::{BodyHandle, Pose};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    /// A handle does not belong to this world.
    InvalidHandle,
    /// A value is non-finite, out of range, or unsupported for this call.
    InvalidArgument,
    OutOfMemory,
    /// The physics solver could not complete the step.
    Internal,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Error::InvalidHandle => "handle does not belong to this world",
            Error::InvalidArgument => "invalid argument",
            Error::OutOfMemory => "out of memory",
            Error::Internal => "internal physics error",
        })
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Shape {
    Sphere {
        radius: f32,
    },
    Box {
        half_extents: [f32; 3],
    },
    /// `height` is the length of the cylinder part along Y, as in Bullet.
    Capsule {
        radius: f32,
        height: f32,
    },
    /// `normal` must be unit length. A plane is always static.
    StaticPlane {
        normal: [f32; 3],
        constant: f32,
    },
}

impl Shape {
    fn raw(&self) -> (i32, [f32; 4]) {
        match *self {
            Shape::Sphere { radius } => (0, [radius, 0.0, 0.0, 0.0]),
            Shape::Box { half_extents: h } => (1, [h[0], h[1], h[2], 0.0]),
            Shape::Capsule { radius, height } => (2, [radius, height, 0.0, 0.0]),
            Shape::StaticPlane {
                normal: n,
                constant,
            } => (3, [n[0], n[1], n[2], constant]),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Transform {
    pub position: [f32; 3],
    pub rotation: [f32; 4],
}

impl Transform {
    pub const IDENTITY: Transform = Transform {
        position: [0.0; 3],
        rotation: [0.0, 0.0, 0.0, 1.0],
    };

    pub fn at(position: [f32; 3]) -> Transform {
        Transform {
            position,
            ..Transform::IDENTITY
        }
    }
}

/// Collision group and mask. Two bodies collide when each one's group
/// intersects the other's mask.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Filter {
    pub group: u16,
    pub mask: u16,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BodyDesc {
    pub shape: Shape,
    /// Zero makes the body static.
    pub mass: f32,
    pub linear_damping: f32,
    pub angular_damping: f32,
    pub restitution: f32,
    pub friction: f32,
    /// `None` keeps Bullet's default filter for the body kind.
    pub filter: Option<Filter>,
    /// A kinematic body is moved with [`World::set_transform`] and has no mass.
    pub kinematic: bool,
    pub transform: Transform,
}

impl BodyDesc {
    pub fn new(shape: Shape) -> BodyDesc {
        BodyDesc {
            shape,
            mass: 0.0,
            linear_damping: 0.0,
            angular_damping: 0.0,
            restitution: 0.0,
            friction: 0.5,
            filter: None,
            kinematic: false,
            transform: Transform::IDENTITY,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct JointDesc {
    pub body_a: BodyId,
    pub body_b: BodyId,
    pub frame_a: Transform,
    pub frame_b: Transform,
    pub use_linear_reference_frame_a: bool,
    pub disable_collision_between_bodies: bool,
    pub linear_lower: [f32; 3],
    pub linear_upper: [f32; 3],
    pub angular_lower: [f32; 3],
    pub angular_upper: [f32; 3],
    /// Spring per degree of freedom: 0 to 2 linear, 3 to 5 angular.
    pub spring_enabled: [bool; 6],
    pub spring_stiffness: [f32; 6],
}

impl JointDesc {
    /// A joint that locks all six degrees of freedom, with no springs.
    pub fn new(body_a: BodyId, body_b: BodyId) -> JointDesc {
        JointDesc {
            body_a,
            body_b,
            frame_a: Transform::IDENTITY,
            frame_b: Transform::IDENTITY,
            use_linear_reference_frame_a: true,
            disable_collision_between_bodies: true,
            linear_lower: [0.0; 3],
            linear_upper: [0.0; 3],
            angular_lower: [0.0; 3],
            angular_upper: [0.0; 3],
            spring_enabled: [false; 6],
            spring_stiffness: [0.0; 6],
        }
    }
}

static NEXT_WORLD_ID: AtomicU64 = AtomicU64::new(1);
static LIVE_WORLDS: AtomicI64 = AtomicI64::new(0);
static LIVE_BODIES: AtomicI64 = AtomicI64::new(0);
static LIVE_JOINTS: AtomicI64 = AtomicI64::new(0);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct BodyId {
    world: u64,
    index: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct JointId {
    world: u64,
    index: usize,
}

impl BodyId {
    pub fn index(&self) -> usize {
        self.index
    }
}

impl JointId {
    pub fn index(&self) -> usize {
        self.index
    }
}

/// Owns the simulation and remains confined to its creating thread.
///
/// ```compile_fail
/// fn require_send<T: Send>() {}
/// require_send::<mds_bullet::World>();
/// ```
///
/// ```compile_fail
/// fn require_sync<T: Sync>() {}
/// require_sync::<mds_bullet::World>();
/// ```
pub struct World {
    inner: DiscreteDynamicsWorld,
    id: u64,
    bodies: Vec<BodyHandle>,
    // Preserve the public wrapper's thread confinement.
    _thread: PhantomData<*mut ()>,
}

fn pose(t: &Transform) -> Pose {
    Pose {
        position: Vec3(t.position),
        rotation: Quat(t.rotation),
    }
}

impl World {
    /// A world with gravity (0, -9.8, 0).
    pub fn new() -> Result<World> {
        let policy = if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
            DbvtPolicy::MmdWin64Sse
        } else {
            DbvtPolicy::GenericReference
        };
        let world = World {
            inner: DiscreteDynamicsWorld::public(policy),
            id: NEXT_WORLD_ID.fetch_add(1, Ordering::Relaxed),
            bodies: Vec::new(),
            _thread: PhantomData,
        };
        LIVE_WORLDS.fetch_add(1, Ordering::Relaxed);
        Ok(world)
    }

    /// Set gravity before adding bodies: each body keeps its creation gravity
    /// until a later gravity change refreshes active bodies.
    pub fn set_gravity(&mut self, gravity: [f32; 3]) -> Result<()> {
        self.inner
            .set_gravity(Vec3(gravity))
            .map_err(|_| Error::InvalidArgument)
    }

    pub fn add_body(&mut self, desc: &BodyDesc) -> Result<BodyId> {
        let (shape_kind, shape_params) = desc.shape.raw();
        self.bodies.try_reserve(1).map_err(|_| Error::OutOfMemory)?;
        let body = self
            .inner
            .create_body(core::world_objects::BodyDesc {
                shape_kind,
                shape_params,
                mass: desc.mass,
                pose: pose(&desc.transform),
                kinematic: desc.kinematic,
                linear_damping: desc.linear_damping,
                angular_damping: desc.angular_damping,
                restitution: desc.restitution,
                friction: desc.friction,
                filter: desc.filter.map(|f| [f.group as i16, f.mask as i16]),
            })
            .map_err(|_| Error::InvalidArgument)?;
        self.bodies.push(body);
        LIVE_BODIES.fetch_add(1, Ordering::Relaxed);
        Ok(BodyId {
            world: self.id,
            index: self.bodies.len() - 1,
        })
    }

    pub fn add_joint(&mut self, desc: &JointDesc) -> Result<JointId> {
        let bodies = [self.body(desc.body_a)?, self.body(desc.body_b)?];
        let index = self
            .inner
            .create_joint(core::world_objects::JointDesc {
                bodies,
                frames: [pose(&desc.frame_a), pose(&desc.frame_b)],
                linear_lower: Vec3(desc.linear_lower),
                linear_upper: Vec3(desc.linear_upper),
                angular_lower: Vec3(desc.angular_lower),
                angular_upper: Vec3(desc.angular_upper),
                spring_enabled: desc.spring_enabled,
                spring_stiffness: desc.spring_stiffness,
                use_linear_reference_frame_a: desc.use_linear_reference_frame_a,
                disable_collisions: desc.disable_collision_between_bodies,
            })
            .map_err(|_| Error::InvalidArgument)?;
        LIVE_JOINTS.fetch_add(1, Ordering::Relaxed);
        Ok(JointId {
            world: self.id,
            index,
        })
    }

    pub fn body_count(&self) -> usize {
        self.bodies.len()
    }

    pub fn joint_count(&self) -> usize {
        self.inner.collision().objects().joints().len()
    }

    pub fn transform(&self, id: BodyId) -> Result<Transform> {
        let body = self.body(id)?;
        let t = self
            .inner
            .public_transform(body)
            .map_err(|_| Error::InvalidArgument)?;
        Ok(Transform {
            position: t.origin.0,
            rotation: t.basis.rotation().0,
        })
    }

    /// Moves a kinematic or dynamic body. Static bodies cannot be moved.
    pub fn set_transform(&mut self, id: BodyId, t: &Transform) -> Result<()> {
        let body = self.body(id)?;
        self.inner
            .set_public_transform(body, pose(t))
            .map_err(|_| Error::InvalidArgument)
    }

    /// Advances the simulation like `btDiscreteDynamicsWorld::stepSimulation`
    /// and returns its requested number of substeps before the execution clamp.
    pub fn step(&mut self, dt: f32, max_sub_steps: i32, fixed_step: f32) -> Result<i32> {
        self.inner
            .step_simulation(dt, max_sub_steps, fixed_step, |_| {})
            .map_err(|error| match error {
                StepError::InvalidArgument => Error::InvalidArgument,
                StepError::UninitializedSolverSlot(_) => Error::Internal,
            })
    }

    /// FNV-1a over the transform, linear velocity x and angular velocity y of
    /// every non-static body in creation order.
    pub fn state_hash(&self) -> Result<u64> {
        Ok(self.inner.state_hash())
    }

    fn body(&self, id: BodyId) -> Result<BodyHandle> {
        match self.bodies.get(id.index) {
            Some(&body) if id.world == self.id => Ok(body),
            _ => Err(Error::InvalidHandle),
        }
    }
}

impl Drop for World {
    fn drop(&mut self) {
        LIVE_JOINTS.fetch_sub(self.joint_count() as i64, Ordering::Relaxed);
        LIVE_BODIES.fetch_sub(self.body_count() as i64, Ordering::Relaxed);
        LIVE_WORLDS.fetch_sub(1, Ordering::Relaxed);
    }
}

/// Live object counts across all worlds in the process.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LiveCounts {
    pub worlds: i64,
    pub bodies: i64,
    pub joints: i64,
}

/// For leak checks: how many worlds, bodies and joints exist right now.
pub fn live_counts() -> LiveCounts {
    LiveCounts {
        worlds: LIVE_WORLDS.load(Ordering::Relaxed),
        bodies: LIVE_BODIES.load(Ordering::Relaxed),
        joints: LIVE_JOINTS.load(Ordering::Relaxed),
    }
}
