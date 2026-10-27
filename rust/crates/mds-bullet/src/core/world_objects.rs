//! Altered translation of the two shims' registered object ownership.
//! World stepping and broadphase ownership remain external. See mod.rs for the zlib notice.

use std::sync::atomic::{AtomicU64, Ordering};

use super::activation::{ActivationState, BodyActivation, CollisionClassification};
use super::body::{BodyInit, RigidBody};
use super::dispatcher::DispatchObject;
use super::islands::{IslandConstraint, IslandObject};
use super::joint_coordinates::calculate_coordinates;
use super::joint_rows::{normalize_angle, AngularMotor, AxisMotor, JointState, Spring};
use super::math::{Basis, Quat, Transform, Vec3};
use super::shape::Shape;
use super::solver::Joint;
use super::InvalidArgument;

static NEXT_WORLD: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BodyHandle {
    world: u64,
    index: usize,
}

#[derive(Clone, Copy, Debug)]
pub struct Pose {
    pub position: Vec3,
    pub rotation: Quat,
}

impl Pose {
    fn valid(self) -> bool {
        finite(self.position.0) && finite(self.rotation.0) && self.rotation.length2() > 1e-12
    }

    pub fn transform(self) -> Transform {
        Transform {
            basis: Basis::from_rotation(self.rotation),
            origin: self.position,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct MotionState {
    pub graphics_world: Transform,
    pub center_of_mass_offset: Transform,
    pub start_world: Transform,
}

impl MotionState {
    pub fn new(start_world: Transform, center_of_mass_offset: Transform) -> Self {
        Self {
            graphics_world: start_world,
            center_of_mass_offset,
            start_world,
        }
    }

    pub fn get_world_transform(self) -> Transform {
        self.center_of_mass_offset
            .inverse()
            .multiply(self.graphics_world)
    }

    pub fn set_world_transform(&mut self, world: Transform) {
        self.graphics_world = world.multiply(self.center_of_mass_offset);
    }
}

#[derive(Clone, Copy, Debug)]
pub struct BodyDesc {
    pub shape_kind: i32,
    pub shape_params: [f32; 4],
    pub mass: f32,
    pub pose: Pose,
    pub kinematic: bool,
    pub linear_damping: f32,
    pub angular_damping: f32,
    pub restitution: f32,
    pub friction: f32,
    pub filter: Option<[i16; 2]>,
}

pub struct BodyData {
    pub shape: Shape,
    pub motion: MotionState,
    pub collision_flags: i32,
    pub filter: [i16; 2],
    pub disabled_collision_refs: Vec<IslandConstraint>,
    pub processing_threshold: f32,
    public_kinematic: bool,
    hashed: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct JointDesc {
    pub bodies: [BodyHandle; 2],
    pub frames: [Pose; 2],
    pub linear_lower: Vec3,
    pub linear_upper: Vec3,
    pub angular_lower: Vec3,
    pub angular_upper: Vec3,
    pub spring_enabled: [bool; 6],
    pub spring_stiffness: [f32; 6],
    pub use_linear_reference_frame_a: bool,
    pub disable_collisions: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct JointData {
    pub use_linear_reference_frame_a: bool,
    pub disable_collisions: bool,
    /// The public shim leaves native m_uid uninitialized.
    pub mmd_uid: Option<i32>,
}

pub struct WorldObjects {
    identity: u64,
    gravity: Vec3,
    bodies: Vec<RigidBody>,
    objects: Vec<IslandObject>,
    data: Vec<BodyData>,
    non_static: Vec<usize>,
    joints: Vec<Joint>,
    joint_data: Vec<JointData>,
    mmd: bool,
}

fn finite<const N: usize>(values: [f32; N]) -> bool {
    values.into_iter().all(f32::is_finite)
}

impl WorldObjects {
    fn new(gravity: Vec3, mmd: bool) -> Self {
        Self {
            identity: NEXT_WORLD.fetch_add(1, Ordering::Relaxed),
            gravity,
            bodies: Vec::new(),
            objects: Vec::new(),
            data: Vec::new(),
            non_static: Vec::new(),
            joints: Vec::new(),
            joint_data: Vec::new(),
            mmd,
        }
    }

    pub fn public() -> Self {
        Self::new(Vec3([0.0, -9.8, 0.0]), false)
    }

    pub fn mmd() -> Self {
        let mut world = Self::new(Vec3([0.0, -98.0, 0.0]), true);
        world.register(
            Shape::static_plane(Vec3([0.0, 1.0, 0.0]), 0.0),
            0.0,
            MotionState::new(Transform::IDENTITY, Transform::IDENTITY),
            0.0,
            0.0,
            0.88,
            0.5,
            false,
            Some([i16::MIN, -1]),
            false,
        );
        world
    }

    pub fn gravity(&self) -> Vec3 {
        self.gravity
    }
    pub fn bodies(&self) -> &[RigidBody] {
        &self.bodies
    }
    pub fn objects(&self) -> &[IslandObject] {
        &self.objects
    }
    pub fn data(&self) -> &[BodyData] {
        &self.data
    }
    pub fn non_static(&self) -> &[usize] {
        &self.non_static
    }
    pub fn joints(&self) -> &[Joint] {
        &self.joints
    }
    pub fn joint_data(&self) -> &[JointData] {
        &self.joint_data
    }

    pub fn solver_parts(&mut self) -> (&mut [RigidBody], &mut [IslandObject], &mut [Joint]) {
        (&mut self.bodies, &mut self.objects, &mut self.joints)
    }

    pub fn dispatch_objects(&self) -> Vec<DispatchObject<'_>> {
        self.data
            .iter()
            .enumerate()
            .map(|(i, data)| DispatchObject {
                shape: data.shape,
                contact: self.bodies[i].contact_body(),
                activation: &self.objects[i].activation,
                constraints: &data.disabled_collision_refs,
                processing_threshold: data.processing_threshold,
            })
            .collect()
    }

    pub fn index(&self, body: BodyHandle) -> Result<usize, InvalidArgument> {
        if body.world != self.identity || body.index >= self.bodies.len() {
            Err(InvalidArgument)
        } else {
            Ok(body.index)
        }
    }

    pub fn set_gravity(&mut self, gravity: Vec3) -> Result<(), InvalidArgument> {
        if !self.mmd && !finite(gravity.0) {
            return Err(InvalidArgument);
        }
        self.gravity = gravity;
        for &i in &self.non_static {
            if self.objects[i].activation.is_active() {
                self.bodies[i].set_gravity(gravity);
            }
        }
        Ok(())
    }

    pub fn create_public_body(&mut self, desc: BodyDesc) -> Result<BodyHandle, InvalidArgument> {
        let p = desc.shape_params;
        if !finite(p)
            || !finite([
                desc.mass,
                desc.linear_damping,
                desc.angular_damping,
                desc.restitution,
                desc.friction,
            ])
            || desc.mass < 0.0
            || !desc.pose.valid()
        {
            return Err(InvalidArgument);
        }
        let shape = match desc.shape_kind {
            0 if p[0] > 0.0 => Shape::Sphere { radius: p[0] },
            1 if p[..3].iter().all(|&v| v > 0.0) => Shape::box_shape(Vec3([p[0], p[1], p[2]])),
            2 if p[0] > 0.0 && p[1] >= 0.0 => Shape::capsule_y(p[0], p[1]),
            3 if ((p[0] * p[0] + p[1] * p[1]) + p[2] * p[2] - 1.0).abs() <= 1e-3
                && desc.mass == 0.0
                && !desc.kinematic =>
            {
                Shape::static_plane(Vec3([p[0], p[1], p[2]]), p[3])
            }
            _ => return Err(InvalidArgument),
        };
        let mass = if desc.kinematic { 0.0 } else { desc.mass };
        Ok(self.register(
            shape,
            mass,
            MotionState::new(desc.pose.transform(), Transform::IDENTITY),
            desc.linear_damping,
            desc.angular_damping,
            desc.restitution,
            desc.friction,
            desc.kinematic,
            desc.filter,
            false,
        ))
    }

    pub fn create_mmd_body(
        &mut self,
        desc: BodyDesc,
        mode: i32,
    ) -> Result<BodyHandle, InvalidArgument> {
        let p = desc.shape_params;
        let shape = match desc.shape_kind {
            0 => Shape::Sphere { radius: p[0] },
            1 => Shape::box_shape(Vec3([p[0], p[1], p[2]])),
            2 => Shape::capsule_y(p[0], p[1]),
            _ => return Err(InvalidArgument),
        };
        let mass = if mode == 0 { 0.0 } else { desc.mass };
        let handle = self.register(
            shape,
            mass,
            MotionState::new(desc.pose.transform(), Transform::IDENTITY),
            desc.linear_damping,
            desc.angular_damping,
            desc.restitution,
            desc.friction,
            false,
            Some(desc.filter.unwrap_or([0, 0])),
            true,
        );
        if mode == 0 {
            self.set_kinematic(handle, true)?;
        }
        Ok(handle)
    }

    #[allow(clippy::too_many_arguments)]
    fn register(
        &mut self,
        shape: Shape,
        mass: f32,
        motion: MotionState,
        linear_damping: f32,
        angular_damping: f32,
        restitution: f32,
        friction: f32,
        kinematic: bool,
        filter: Option<[i16; 2]>,
        mmd_model: bool,
    ) -> BodyHandle {
        let index = self.bodies.len();
        let mut body = RigidBody::new(BodyInit {
            mass,
            local_inertia: if mass != 0.0 {
                shape.local_inertia(mass)
            } else {
                Vec3::ZERO
            },
            center_of_mass: motion.get_world_transform(),
            linear_damping,
            angular_damping,
        });
        body.set_friction(friction);
        body.set_restitution(restitution);
        body.set_kinematic(kinematic);
        let mut activation = BodyActivation::default();
        if kinematic {
            activation.set_activation_state(ActivationState::DisableDeactivation);
        }
        if mass != 0.0 && !kinematic {
            body.set_gravity(self.gravity);
        }
        if mass != 0.0 {
            self.non_static.push(index);
        } else {
            activation.set_activation_state(ActivationState::IslandSleeping);
        }
        if mmd_model {
            activation.set_activation_state(ActivationState::DisableDeactivation);
        }
        let flags = i32::from(mass == 0.0) | (i32::from(kinematic) << 1);
        self.bodies.push(body);
        self.objects.push(IslandObject {
            activation,
            classification: classification(flags),
            contact_response: true,
            island_tag: -1,
            companion_id: -1,
            hit_fraction: 1.0,
        });
        self.data.push(BodyData {
            shape,
            motion,
            collision_flags: flags,
            filter: filter.unwrap_or(if mass != 0.0 && !kinematic {
                [1, -1]
            } else {
                [2, -3]
            }),
            disabled_collision_refs: Vec::new(),
            processing_threshold: 1e18,
            public_kinematic: kinematic,
            hashed: kinematic || mass > 0.0,
        });
        BodyHandle {
            world: self.identity,
            index,
        }
    }

    pub fn set_kinematic(&mut self, handle: BodyHandle, on: bool) -> Result<(), InvalidArgument> {
        let i = self.index(handle)?;
        let flags = self.data[i].collision_flags;
        self.set_flags(i, if on { flags | 2 } else { flags & !2 });
        Ok(())
    }

    fn set_flags(&mut self, i: usize, flags: i32) {
        self.data[i].collision_flags = flags;
        self.bodies[i].set_kinematic(flags & 2 != 0);
        self.objects[i].classification = classification(flags);
        self.objects[i].contact_response = flags & 4 == 0;
    }

    pub fn set_floor(&mut self, on: bool) -> Result<(), InvalidArgument> {
        if !self.mmd {
            return Err(InvalidArgument);
        }
        self.set_flags(0, if on { 1 } else { -1 });
        Ok(())
    }

    pub fn public_transform(&self, handle: BodyHandle) -> Result<Transform, InvalidArgument> {
        Ok(self.data[self.index(handle)?].motion.get_world_transform())
    }

    pub fn set_public_transform(
        &mut self,
        handle: BodyHandle,
        pose: Pose,
    ) -> Result<(), InvalidArgument> {
        let i = self.index(handle)?;
        if !self.data[i].hashed || !pose.valid() {
            return Err(InvalidArgument);
        }
        let world = pose.transform();
        self.data[i].motion.set_world_transform(world);
        if !self.data[i].public_kinematic {
            self.bodies[i].set_world_transform(world);
            self.bodies[i].set_interpolation_world_transform(world);
        }
        Ok(())
    }

    pub fn set_motion_state(
        &mut self,
        handle: BodyHandle,
        world: Transform,
    ) -> Result<(), InvalidArgument> {
        let i = self.index(handle)?;
        self.data[i].motion.set_world_transform(world);
        Ok(())
    }

    pub fn reseat(&mut self, handle: BodyHandle, world: Transform) -> Result<(), InvalidArgument> {
        let i = self.index(handle)?;
        self.bodies[i].set_world_transform(world);
        self.bodies[i].set_linear_velocity(Vec3::ZERO);
        self.bodies[i].set_angular_velocity(Vec3::ZERO);
        self.bodies[i].set_interpolation_velocities(Vec3::ZERO, Vec3::ZERO);
        Ok(())
    }

    pub fn stop_at(&mut self, handle: BodyHandle, origin: Vec3) -> Result<(), InvalidArgument> {
        let i = self.index(handle)?;
        let mut world = self.bodies[i].snapshot().world;
        world.origin = origin;
        self.bodies[i].set_world_transform(world);
        self.bodies[i].set_linear_velocity(Vec3::ZERO);
        self.bodies[i].set_angular_velocity(Vec3::ZERO);
        Ok(())
    }

    pub fn create_joint(
        &mut self,
        desc: JointDesc,
        mmd_uid: Option<i32>,
    ) -> Result<usize, InvalidArgument> {
        let a = self.index(desc.bodies[0])?;
        let b = self.index(desc.bodies[1])?;
        if mmd_uid.is_none()
            && (a == b
                || !desc.frames.iter().all(|p| p.valid())
                || !finite(desc.linear_lower.0)
                || !finite(desc.linear_upper.0)
                || !finite(desc.angular_lower.0)
                || !finite(desc.angular_upper.0)
                || !finite(desc.spring_stiffness))
        {
            return Err(InvalidArgument);
        }
        let frames = desc.frames.map(Pose::transform);
        let mut state = joint_state(desc, mmd_uid.is_some());
        if mmd_uid.is_some() && state.springs.iter().any(|s| s.enabled) {
            let c = calculate_coordinates(
                self.bodies[a].snapshot().world,
                self.bodies[b].snapshot().world,
                frames[0],
                frames[1],
            )
            .coordinates;
            for i in 0..3 {
                state.springs[i].equilibrium = c.linear_diff.0[i];
                state.springs[i + 3].equilibrium = c.angular_diff.0[i];
            }
        }
        let index = self.joints.len();
        let disable_collisions = mmd_uid.is_none() && desc.disable_collisions;
        if disable_collisions {
            for i in [a, b] {
                self.data[i]
                    .disabled_collision_refs
                    .push(IslandConstraint { bodies: [a, b] });
            }
        }
        self.joints.push(Joint {
            bodies: [a, b],
            frames,
            state,
        });
        self.joint_data.push(JointData {
            use_linear_reference_frame_a: mmd_uid.is_some() || desc.use_linear_reference_frame_a,
            disable_collisions,
            mmd_uid,
        });
        Ok(index)
    }
}

fn classification(flags: i32) -> CollisionClassification {
    match flags & 3 {
        0 => CollisionClassification::Dynamic,
        1 => CollisionClassification::Static,
        2 => CollisionClassification::Kinematic,
        _ => CollisionClassification::StaticAndKinematic,
    }
}

fn joint_state(desc: JointDesc, mmd: bool) -> JointState {
    let motor = |i: usize, angular: bool| {
        let limit = |v: f32| {
            if angular {
                normalize_angle(if mmd && v == 0.0 { 0.0 } else { v })
            } else {
                v
            }
        };
        AxisMotor {
            lower: limit(if angular {
                desc.angular_lower.0[i]
            } else {
                desc.linear_lower.0[i]
            }),
            upper: limit(if angular {
                desc.angular_upper.0[i]
            } else {
                desc.linear_upper.0[i]
            }),
            enabled: if mmd {
                desc.spring_stiffness[i + if angular { 3 } else { 0 }] > 0.0
            } else {
                desc.spring_enabled[i + if angular { 3 } else { 0 }]
            },
            target_velocity: 0.0,
            max_motor_force: if angular { 0.1 } else { 0.0 },
            current_position: 0.0,
            current_limit: 0,
            current_limit_error: 0.0,
        }
    };
    JointState {
        linear: std::array::from_fn(|i| motor(i, false)),
        angular: std::array::from_fn(|i| AngularMotor {
            motor: motor(i, true),
            erp: 0.5,
            bounce: 0.0,
        }),
        linear_erp: 0.5,
        springs: std::array::from_fn(|i| {
            let enabled = if mmd {
                desc.spring_stiffness[i] > 0.0
            } else {
                desc.spring_enabled[i]
            };
            Spring {
                enabled,
                equilibrium: 0.0,
                stiffness: if enabled {
                    desc.spring_stiffness[i]
                } else {
                    0.0
                },
                damping: 1.0,
            }
        }),
    }
}
