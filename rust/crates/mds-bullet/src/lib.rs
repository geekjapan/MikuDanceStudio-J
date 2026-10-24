//! Safe wrapper over the vendored Bullet 2.75.
//!
//! A [`World`] owns every body and joint made through it and frees them when
//! dropped. [`BodyId`] and [`JointId`] are plain indices tagged with their
//! world, so they carry no lifetime and cannot be used on another world.
//! Quaternions are `[x, y, z, w]`.

use std::fmt;
use std::sync::atomic::{AtomicU64, Ordering};

use mds_bullet_sys as sys;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    /// A handle does not belong to this world.
    InvalidHandle,
    /// A value is non-finite, out of range, or unsupported for this call.
    InvalidArgument,
    OutOfMemory,
    /// Bullet threw an exception.
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

fn check(rc: i32) -> Result<()> {
    match rc {
        sys::MDS_BT_OK => Ok(()),
        sys::MDS_BT_ERR_NULL => Err(Error::InvalidHandle),
        sys::MDS_BT_ERR_INVALID => Err(Error::InvalidArgument),
        sys::MDS_BT_ERR_ALLOC => Err(Error::OutOfMemory),
        _ => Err(Error::Internal),
    }
}

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
            Shape::Sphere { radius } => (sys::MDS_BT_SHAPE_SPHERE, [radius, 0.0, 0.0, 0.0]),
            Shape::Box { half_extents: h } => (sys::MDS_BT_SHAPE_BOX, [h[0], h[1], h[2], 0.0]),
            Shape::Capsule { radius, height } => {
                (sys::MDS_BT_SHAPE_CAPSULE, [radius, height, 0.0, 0.0])
            }
            Shape::StaticPlane {
                normal: n,
                constant,
            } => (sys::MDS_BT_SHAPE_STATIC_PLANE, [n[0], n[1], n[2], constant]),
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

pub struct World {
    raw: *mut sys::mds_bt_world,
    id: u64,
    bodies: Vec<*mut sys::mds_bt_body>,
    joints: usize,
}

// World is neither Send nor Sync: Bullet keeps process-wide mutable statics
// (btRigidBody's id counter, the aligned-allocator counters) that are not atomic.

impl World {
    /// A world with gravity (0, -9.8, 0).
    pub fn new() -> Result<World> {
        let raw = unsafe { sys::mds_bt_world_create() };
        if raw.is_null() {
            return Err(Error::OutOfMemory);
        }
        Ok(World {
            raw,
            id: NEXT_WORLD_ID.fetch_add(1, Ordering::Relaxed),
            bodies: Vec::new(),
            joints: 0,
        })
    }

    /// Set gravity before adding bodies: Bullet gives each body the gravity
    /// of the moment it is added and only refreshes active bodies afterwards.
    pub fn set_gravity(&mut self, gravity: [f32; 3]) -> Result<()> {
        check(unsafe {
            sys::mds_bt_world_set_gravity(self.raw, gravity[0], gravity[1], gravity[2])
        })
    }

    pub fn add_body(&mut self, desc: &BodyDesc) -> Result<BodyId> {
        let (shape_kind, shape_params) = desc.shape.raw();
        let filter = desc.filter.unwrap_or(Filter { group: 0, mask: 0 });
        let raw_desc = sys::mds_bt_body_desc {
            shape_kind,
            shape_params,
            mass: desc.mass,
            linear_damping: desc.linear_damping,
            angular_damping: desc.angular_damping,
            restitution: desc.restitution,
            friction: desc.friction,
            has_filter: desc.filter.is_some() as i32,
            collision_group: filter.group,
            collision_mask: filter.mask,
            kinematic: desc.kinematic as i32,
            position: desc.transform.position,
            rotation: desc.transform.rotation,
        };
        let mut body = std::ptr::null_mut();
        check(unsafe { sys::mds_bt_body_create(self.raw, &raw_desc, &mut body) })?;
        self.bodies.push(body);
        Ok(BodyId {
            world: self.id,
            index: self.bodies.len() - 1,
        })
    }

    pub fn add_joint(&mut self, desc: &JointDesc) -> Result<JointId> {
        let raw_desc = sys::mds_bt_joint_desc {
            body_a: self.body(desc.body_a)?,
            body_b: self.body(desc.body_b)?,
            frame_a_position: desc.frame_a.position,
            frame_a_rotation: desc.frame_a.rotation,
            frame_b_position: desc.frame_b.position,
            frame_b_rotation: desc.frame_b.rotation,
            use_linear_reference_frame_a: desc.use_linear_reference_frame_a as i32,
            disable_collision_between_bodies: desc.disable_collision_between_bodies as i32,
            linear_lower: desc.linear_lower,
            linear_upper: desc.linear_upper,
            angular_lower: desc.angular_lower,
            angular_upper: desc.angular_upper,
            spring_enabled: desc.spring_enabled.map(|b| b as i32),
            spring_stiffness: desc.spring_stiffness,
        };
        let mut joint = std::ptr::null_mut();
        check(unsafe { sys::mds_bt_joint_create(self.raw, &raw_desc, &mut joint) })?;
        self.joints += 1;
        Ok(JointId {
            world: self.id,
            index: self.joints - 1,
        })
    }

    pub fn body_count(&self) -> usize {
        self.bodies.len()
    }

    pub fn joint_count(&self) -> usize {
        self.joints
    }

    pub fn transform(&self, id: BodyId) -> Result<Transform> {
        let body = self.body(id)?;
        let mut t = Transform::IDENTITY;
        check(unsafe {
            sys::mds_bt_body_get_transform(
                self.raw,
                body,
                t.position.as_mut_ptr(),
                t.rotation.as_mut_ptr(),
            )
        })?;
        Ok(t)
    }

    /// Moves a kinematic or dynamic body. Static bodies cannot be moved.
    pub fn set_transform(&mut self, id: BodyId, t: &Transform) -> Result<()> {
        let body = self.body(id)?;
        check(unsafe {
            sys::mds_bt_body_set_transform(self.raw, body, t.position.as_ptr(), t.rotation.as_ptr())
        })
    }

    /// Advances the simulation like `btDiscreteDynamicsWorld::stepSimulation`
    /// and returns the number of fixed substeps taken.
    pub fn step(&mut self, dt: f32, max_sub_steps: i32, fixed_step: f32) -> Result<i32> {
        let mut substeps = 0;
        check(unsafe {
            sys::mds_bt_world_step(self.raw, dt, max_sub_steps, fixed_step, &mut substeps)
        })?;
        Ok(substeps)
    }

    /// FNV-1a over the transform, linear velocity x and angular velocity y of
    /// every non-static body in creation order.
    pub fn state_hash(&self) -> Result<u64> {
        let mut h = 0;
        check(unsafe { sys::mds_bt_world_state_hash(self.raw, &mut h) })?;
        Ok(h)
    }

    fn body(&self, id: BodyId) -> Result<*mut sys::mds_bt_body> {
        match self.bodies.get(id.index) {
            Some(&b) if id.world == self.id => Ok(b),
            _ => Err(Error::InvalidHandle),
        }
    }
}

impl Drop for World {
    fn drop(&mut self) {
        unsafe { sys::mds_bt_world_destroy(self.raw) }
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
    let mut c = [0i64; 3];
    let rc = unsafe { sys::mds_bt_live_counts(c.as_mut_ptr()) };
    debug_assert_eq!(rc, sys::MDS_BT_OK);
    LiveCounts {
        worlds: c[0],
        bodies: c[1],
        joints: c[2],
    }
}
