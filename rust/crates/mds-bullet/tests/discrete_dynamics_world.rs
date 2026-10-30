#![allow(dead_code)]
#[path = "../src/core/mod.rs"]
mod core;

use core::dbvt::DbvtPolicy;
use core::discrete_dynamics_world::{DiscreteDynamicsWorld, DynamicsEvent, StepError};
use core::islands::SolverEvent;
use core::math::{Quat, Vec3};
use core::world_objects::{BodyDesc, JointDesc, Pose};

fn world() -> DiscreteDynamicsWorld {
    DiscreteDynamicsWorld::public(DbvtPolicy::GenericReference)
}

fn sphere(x: f32, y: f32, mass: f32) -> BodyDesc {
    BodyDesc {
        shape_kind: 0,
        shape_params: [0.5, 0.0, 0.0, 0.0],
        mass,
        pose: Pose {
            position: Vec3([x, y, 0.0]),
            rotation: Quat([0.0, 0.0, 0.0, 1.0]),
        },
        kinematic: false,
        linear_damping: 0.0,
        angular_damping: 0.0,
        restitution: 0.0,
        friction: 0.5,
        filter: None,
    }
}

#[test]
fn dynamics_world_initial_zero_time_executes_and_clamp_returns_requested() {
    let mut w = world();
    w.create_body(sphere(0.0, 10.0, 1.0)).unwrap();
    let mut clock = None;
    assert_eq!(
        w.step_simulation(0.0, 1, 1.0 / 60.0, |event| {
            if let DynamicsEvent::Clock(step) = event {
                clock = Some(step);
            }
        }),
        Ok(1)
    );
    assert_eq!(clock.unwrap().executed, 1);
    assert!(
        w.collision().objects().bodies()[0]
            .snapshot()
            .world
            .origin
            .0[1]
            < 10.0
    );
    assert_eq!(
        w.step_simulation(0.125, 2, 0.03125, |event| {
            if let DynamicsEvent::Clock(step) = event {
                clock = Some(step);
            }
        }),
        Ok(4)
    );
    assert_eq!(clock.unwrap().executed, 2);
}

#[test]
fn dynamics_world_gravity_once_and_forces_clear_after_outer_call() {
    let mut w = world();
    w.create_body(sphere(0.0, 10.0, 1.0)).unwrap();
    w.set_gravity(Vec3([0.0, -8.0, 0.0])).unwrap();
    assert_eq!(w.step_simulation(0.125, 0, 0.03125, |_| {}), Ok(1));
    assert_eq!(w.step_simulation(0.125, 4, 0.03125, |_| {}), Ok(8));
    let body = w.collision().objects().bodies()[0].snapshot();
    assert_eq!(body.linear_velocity, Vec3([0.0, -2.0, 0.0]));
    assert_eq!(body.total_force, Vec3::ZERO);
    assert_eq!(body.total_torque, Vec3::ZERO);
    assert_eq!(body.interpolation_linear_velocity, body.linear_velocity);
    assert_eq!(body.interpolation_world, body.world);
}

#[test]
fn dynamics_world_zero_substep_synchronizes_motion_and_hash() {
    let mut w = world();
    let body = w.create_body(sphere(0.0, 10.0, 1.0)).unwrap();
    w.set_gravity(Vec3([0.0, -8.0, 0.0])).unwrap();
    w.step_simulation(0.125, 0, 0.03125, |_| {}).unwrap();
    w.set_public_transform(body, sphere(0.0, 10.0, 1.0).pose)
        .unwrap();
    let before = w.state_hash();
    let current = w.collision().objects().bodies()[0].snapshot();
    assert_eq!(current.world.origin, Vec3([0.0, 10.0, 0.0]));
    assert_eq!(current.interpolation_world, current.world);
    assert_eq!(current.interpolation_linear_velocity, Vec3([0.0, -1.0, 0.0]));
    let mut clock = None;
    assert_eq!(
        w.step_simulation(0.0, 1, 1.0, |event| {
            if let DynamicsEvent::Clock(step) = event {
                clock = Some(step);
            }
        }),
        Ok(0)
    );
    let clock = clock.unwrap();
    assert_eq!(clock.requested, 0);
    assert_eq!(clock.executed, 0);
    assert_eq!(clock.remainder, 0.125);
    let motion = w.public_transform(body).unwrap();
    assert_eq!(motion.origin, Vec3([0.0, 9.875, 0.0]));
    assert_eq!(motion.basis, current.world.basis);
    assert_ne!(before, w.state_hash());
    let after = w.collision().objects().bodies()[0].snapshot();
    assert_eq!(after.world, current.world);
    assert_eq!(after.interpolation_world, current.interpolation_world);
    assert_eq!(after.linear_velocity, current.linear_velocity);
    assert_eq!(
        after.interpolation_linear_velocity,
        current.interpolation_linear_velocity
    );
    let synchronized = w.state_hash();
    assert_eq!(w.step_simulation(0.0, 1, 1.0, |_| {}), Ok(0));
    assert_eq!(w.public_transform(body).unwrap(), motion);
    assert_eq!(w.state_hash(), synchronized);
}

#[test]
fn dynamics_world_collision_solver_writes_persistent_contact_impulses() {
    let mut w = world();
    w.create_body(sphere(0.0, 0.0, 0.0)).unwrap();
    w.create_body(sphere(0.0, 0.9, 1.0)).unwrap();
    let mut groups = 0;
    w.step_simulation(0.0, 1, 1.0 / 60.0, |event| {
        if let DynamicsEvent::Solver(SolverEvent::SolveGroup { island, .. }) = event {
            assert_eq!(island.manifolds.len(), 1);
            groups += 1;
        }
    })
    .unwrap();
    assert_eq!(groups, 1);
    let key = w.collision().manifolds()[0].owner();
    assert!(w.collision().manifolds()[0].manifold.contacts()[0].applied_impulse > 0.0);
    w.step_simulation(1.0 / 60.0, 1, 1.0 / 60.0, |_| {})
        .unwrap();
    assert_eq!(w.collision().manifolds()[0].owner(), key);
    assert!(w.collision().manifolds()[0].manifold.contacts()[0].lifetime > 0);
    assert_eq!(w.solver_workspace().live_len(), 0);
    assert!(w.solver_workspace().native_capacity() > 0);
}

#[test]
fn dynamics_world_multiple_islands_preserve_global_joint_and_body_indices() {
    let mut w = world();
    w.set_gravity(Vec3::ZERO).unwrap();
    let handles: Vec<_> = (0..4)
        .map(|i| {
            w.create_body(sphere((i / 2) as f32 * 10.0, (i % 2) as f32 * 0.9, 1.0))
                .unwrap()
        })
        .collect();
    let identity = Pose {
        position: Vec3::ZERO,
        rotation: Quat([0.0, 0.0, 0.0, 1.0]),
    };
    for pair in handles.chunks_exact(2) {
        w.create_joint(JointDesc {
            bodies: [pair[0], pair[1]],
            frames: [identity; 2],
            linear_lower: Vec3::ZERO,
            linear_upper: Vec3::ZERO,
            angular_lower: Vec3::ZERO,
            angular_upper: Vec3::ZERO,
            spring_enabled: [false; 6],
            spring_stiffness: [0.0; 6],
            use_linear_reference_frame_a: false,
            disable_collisions: false,
        })
        .unwrap();
    }
    let mut groups = Vec::new();
    w.step_simulation(0.0, 1, 1.0 / 60.0, |event| {
        if let DynamicsEvent::Solver(SolverEvent::SolveGroup {
            island,
            constraints,
        }) = event
        {
            groups.push((island.bodies.to_vec(), constraints.to_vec()));
        }
    })
    .unwrap();
    assert_eq!(groups.len(), 2);
    assert!(groups.iter().any(|(bodies, joints)| {
        bodies.len() == 2 && bodies.contains(&0) && bodies.contains(&1) && joints == &[0]
    }));
    assert!(groups.iter().any(|(bodies, joints)| {
        bodies.len() == 2 && bodies.contains(&2) && bodies.contains(&3) && joints == &[1]
    }));
}

#[test]
fn dynamics_world_kinematic_save_and_invalid_step_leave_clock_intact() {
    let mut w = world();
    let mut desc = sphere(0.0, 0.0, 1.0);
    desc.kinematic = true;
    let handle = w.create_body(desc).unwrap();
    w.set_public_transform(handle, sphere(2.0, 0.0, 1.0).pose)
        .unwrap();
    assert_eq!(
        w.step_simulation(f32::NAN, 1, 0.125, |_| panic!("invalid step observed")),
        Err(StepError::InvalidArgument)
    );
    assert_eq!(w.step_simulation(0.0, 1, 1.0 / 60.0, |_| {}), Ok(1));
    let body = w.collision().objects().bodies()[0].snapshot();
    assert_eq!(body.world.origin, Vec3([2.0, 0.0, 0.0]));
    assert_eq!(body.interpolation_world, body.world);
    assert_eq!(body.linear_velocity, Vec3([2.0 / (1.0 / 60.0), 0.0, 0.0]));
}
