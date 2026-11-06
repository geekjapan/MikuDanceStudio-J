#![allow(dead_code)]
#[path = "../src/core/mod.rs"]
mod core;

use core::activation::ActivationState;
use core::axis_sweep::AxisSweep32;
use core::discrete_dynamics_world::{DynamicsEvent, StepError};
use core::islands::SolverEvent;
use core::math::{Quat, Transform, Vec3};
use core::mmd_collision_world::MmdCollisionWorld;
use core::mmd_dynamics_world::MmdDynamicsWorld;
use core::solver::UninitializedSolverSlot;
use core::world_objects::{BodyDesc, BodyHandle, JointDesc, Pose};
use core::InvalidArgument;

fn sphere(x: f32, y: f32) -> BodyDesc {
    BodyDesc {
        shape_kind: 0,
        shape_params: [0.5, 0.0, 0.0, 0.0],
        mass: 2.0,
        pose: Pose {
            position: Vec3([x, y, 0.0]),
            rotation: Quat([0.0, 0.0, 0.0, 1.0]),
        },
        kinematic: false,
        linear_damping: 0.0,
        angular_damping: 0.0,
        restitution: 0.0,
        friction: 0.5,
        filter: Some([1, -1]),
    }
}

fn joint(a: BodyHandle, b: BodyHandle) -> JointDesc {
    JointDesc {
        bodies: [a, b],
        frames: [sphere(0.0, 0.0).pose; 2],
        linear_lower: Vec3::ZERO,
        linear_upper: Vec3::ZERO,
        angular_lower: Vec3::ZERO,
        angular_upper: Vec3::ZERO,
        spring_enabled: [false; 6],
        spring_stiffness: [0.0; 6],
        use_linear_reference_frame_a: false,
        disable_collisions: true,
    }
}

#[test]
fn mmd_dynamics_startup_zero_dt_uses_fixed_step_and_ground_first() {
    let mut w = MmdDynamicsWorld::new();
    let a = w.create_body(sphere(0.0, 10.0), 1).unwrap();
    let objects = w.collision().objects();
    assert_eq!(objects.index(a).unwrap(), 1);
    assert_eq!(objects.gravity(), Vec3([0.0, -98.0, 0.0]));
    assert_eq!(objects.data()[0].filter, [i16::MIN, -1]);
    assert_eq!(objects.bodies()[0].contact_body().restitution, 0.88);
    let mut clocks = Vec::new();
    assert_eq!(
        w.step_simulation(0.0, 1, 1.0 / 60.0, |e| {
            if let DynamicsEvent::Clock(s) = e {
                clocks.push(s);
            }
        }),
        Ok(1)
    );
    assert_eq!(clocks.len(), 1);
    assert_eq!(clocks[0].executed, 1);
    assert_eq!(clocks[0].dt, 1.0 / 60.0);
    let body = w.collision().objects().bodies()[1].snapshot();
    let velocity = -98.0 * (1.0 / 60.0);
    assert_eq!(body.linear_velocity, Vec3([0.0, velocity, 0.0]));
    assert_eq!(
        body.world.origin,
        Vec3([0.0, 10.0 + velocity * (1.0 / 60.0), 0.0])
    );
    assert_eq!(body.total_force, Vec3::ZERO);
    assert_eq!(body.total_torque, Vec3::ZERO);
}

#[test]
fn mmd_dynamics_variable_clamped_steps_apply_gravity_once_and_clear_forces() {
    let mut w = MmdDynamicsWorld::new();
    w.create_body(sphere(0.0, 10.0), 1).unwrap();
    w.set_gravity(Vec3([0.0, -8.0, 0.0])).unwrap();
    assert_eq!(w.step_simulation(0.125, 0, 0.03125, |_| {}), Ok(1));
    let first = w.collision().objects().bodies()[1].snapshot();
    assert_eq!(first.linear_velocity, Vec3([0.0, -1.0, 0.0]));
    assert_eq!(first.world.origin, Vec3([0.0, 9.875, 0.0]));
    let mut clock = None;
    assert_eq!(
        w.step_simulation(0.125, 4, 0.03125, |e| {
            if let DynamicsEvent::Clock(s) = e {
                clock = Some(s);
            }
        }),
        Ok(8)
    );
    assert_eq!(clock.unwrap().executed, 4);
    let body = w.collision().objects().bodies()[1].snapshot();
    assert_eq!(body.linear_velocity, Vec3([0.0, -2.0, 0.0]));
    assert_eq!(body.total_force, Vec3::ZERO);
    assert_eq!(body.total_torque, Vec3::ZERO);
    assert_eq!(body.interpolation_linear_velocity, body.linear_velocity);
    assert_eq!(body.interpolation_world, body.world);
}

#[test]
fn mmd_dynamics_genuine_zero_step_synchronizes_motion_without_moving_com() {
    let mut w = MmdDynamicsWorld::new();
    let a = w.create_body(sphere(0.0, 10.0), 1).unwrap();
    w.set_gravity(Vec3([0.0, -8.0, 0.0])).unwrap();
    w.step_simulation(0.125, 0, 1.0, |_| {}).unwrap();
    let before = w.collision().objects().bodies()[1].snapshot();
    w.set_motion_state(a, sphere(100.0, 100.0).pose.transform())
        .unwrap();
    let mut clock = None;
    assert_eq!(
        w.step_simulation(0.0, 1, 1.0, |e| {
            match e {
                DynamicsEvent::Clock(s) => clock = Some(s),
                _ => panic!("zero step must not dispatch a solver"),
            }
        }),
        Ok(0)
    );
    let clock = clock.unwrap();
    assert_eq!(clock.executed, 0);
    assert_eq!(clock.remainder, 0.125);
    assert_eq!(w.collision().objects().bodies()[1].snapshot(), before);
    assert_eq!(
        w.collision().objects().data()[1]
            .motion
            .get_world_transform()
            .origin,
        Vec3([0.0, 9.75, 0.0])
    );
    assert_eq!(w.step_simulation(0.0, 1, 1.0, |_| {}), Ok(0));
    assert_eq!(w.collision().objects().bodies()[1].snapshot(), before);
}

#[test]
fn mmd_dynamics_motion_reseat_and_stop_keep_distinct_state() {
    let mut w = MmdDynamicsWorld::new();
    let a = w.create_body(sphere(0.0, 10.0), 1).unwrap();
    w.set_gravity(Vec3([0.0, -8.0, 0.0])).unwrap();
    w.step_simulation(0.125, 0, 1.0, |_| {}).unwrap();
    let motion = sphere(20.0, 30.0).pose.transform();
    w.set_motion_state(a, motion).unwrap();
    let moving = w.collision().objects().bodies()[1].snapshot();
    assert_eq!(moving.world.origin, Vec3([0.0, 9.875, 0.0]));
    w.stop_at(a, Vec3([5.0, 6.0, 0.0])).unwrap();
    let stopped = w.collision().objects().bodies()[1].snapshot();
    assert_eq!(stopped.world.origin, Vec3([5.0, 6.0, 0.0]));
    assert_eq!(stopped.linear_velocity, Vec3::ZERO);
    assert_eq!(
        stopped.interpolation_linear_velocity,
        moving.interpolation_linear_velocity
    );
    assert_eq!(stopped.interpolation_world, moving.interpolation_world);
    w.reseat(a, sphere(7.0, 8.0).pose.transform()).unwrap();
    let reseated = w.collision().objects().bodies()[1].snapshot();
    assert_eq!(reseated.world.origin, Vec3([7.0, 8.0, 0.0]));
    assert_eq!(reseated.interpolation_linear_velocity, Vec3::ZERO);
    assert_eq!(reseated.interpolation_angular_velocity, Vec3::ZERO);
    assert_eq!(reseated.interpolation_world, moving.interpolation_world);
    assert_eq!(
        w.collision().objects().data()[1]
            .motion
            .get_world_transform(),
        motion
    );
}

#[test]
fn mmd_dynamics_nonzero_mass_modes_toggle_and_save_kinematic_fixed_velocity() {
    for mode in [1, 2] {
        let mut w = MmdDynamicsWorld::new();
        let a = w.create_body(sphere(0.0, 10.0), mode).unwrap();
        w.set_gravity(Vec3::ZERO).unwrap();
        w.set_kinematic(a, true).unwrap();
        let pose = sphere(2.0, 10.0).pose.transform();
        w.set_motion_state(a, pose).unwrap();
        assert_eq!(w.step_simulation(0.25, 1, 0.125, |_| {}), Ok(2));
        let body = w.collision().objects().bodies()[1].snapshot();
        assert_eq!(body.inverse_mass, 0.5);
        assert_eq!(body.world, pose);
        assert_eq!(body.interpolation_world, pose);
        assert_eq!(body.linear_velocity, Vec3([16.0, 0.0, 0.0]));
        assert_eq!(w.collision().objects().data()[1].collision_flags, 2);
        w.set_kinematic(a, false).unwrap();
        assert_eq!(w.step_simulation(0.125, 0, 1.0, |_| {}), Ok(1));
        let body = w.collision().objects().bodies()[1].snapshot();
        assert_eq!(body.inverse_mass, 0.5);
        assert_eq!(body.world.origin, Vec3([4.0, 10.0, 0.0]));
        assert_eq!(w.collision().objects().data()[1].collision_flags, 0);
        assert_eq!(
            w.collision().objects().objects()[1].activation.state,
            ActivationState::DisableDeactivation
        );
    }
}

#[test]
fn mmd_dynamics_floor_uid_and_contact_solver_preserve_manifolds() {
    let mut w = MmdDynamicsWorld::new();
    let a = w.create_body(sphere(0.0, 0.25), 1).unwrap();
    let b = w.create_body(sphere(0.0, 1.15), 2).unwrap();
    w.create_joint(joint(a, b), i32::MIN).unwrap();
    assert_eq!(
        w.collision().objects().joint_data()[0].mmd_uid,
        Some(i32::MIN)
    );
    assert!(!w.collision().objects().joint_data()[0].disable_collisions);
    w.set_floor(false).unwrap();
    w.step_simulation(0.0, 1, 1.0 / 60.0, |_| {}).unwrap();
    assert_eq!(w.collision().objects().data()[0].collision_flags, -1);
    assert!(w.collision().manifolds().iter().any(|m| m.bodies == [1, 2]));
    w.set_floor(true).unwrap();
    w.step_simulation(1.0 / 60.0, 1, 1.0 / 60.0, |_| {})
        .unwrap();
    assert_eq!(w.collision().objects().data()[0].collision_flags, 1);
    assert!(w.collision().manifolds().iter().any(|m| {
        m.bodies.contains(&0)
            && m.manifold
                .contacts()
                .iter()
                .any(|p| p.applied_impulse > 0.0)
    }));
    assert_eq!(w.solver_workspace().live_len(), 0);
    assert!(w.solver_workspace().native_capacity() >= 2);
}

#[test]
fn mmd_dynamics_rejects_invalid_steps_and_foreign_handles_without_clock_change() {
    let mut w = MmdDynamicsWorld::new();
    let mut other = MmdDynamicsWorld::new();
    let foreign = other.create_body(sphere(0.0, 10.0), 1).unwrap();
    assert_eq!(w.set_kinematic(foreign, true), Err(InvalidArgument));
    assert_eq!(
        w.set_motion_state(foreign, Transform::IDENTITY),
        Err(InvalidArgument)
    );
    assert_eq!(w.reseat(foreign, Transform::IDENTITY), Err(InvalidArgument));
    assert_eq!(w.stop_at(foreign, Vec3::ZERO), Err(InvalidArgument));
    assert_eq!(
        w.create_joint(joint(foreign, foreign), 0),
        Err(InvalidArgument)
    );
    let mut invalid = sphere(0.0, 10.0);
    invalid.shape_kind = 3;
    assert_eq!(w.create_body(invalid, 1), Err(InvalidArgument));
    for (dt, max, fixed) in [
        (f32::NAN, 1, 0.125),
        (f32::INFINITY, 1, 0.125),
        (-1.0, 1, 0.125),
        (0.0, -1, 0.125),
        (0.0, 1, 0.0),
        (0.0, 1, f32::NAN),
        (f32::MAX, 1, 0.125),
    ] {
        assert_eq!(
            w.step_simulation(dt, max, fixed, |_| panic!("invalid clock observed")),
            Err(StepError::InvalidArgument)
        );
    }
    assert_eq!(w.collision().objects().bodies().len(), 1);
    assert_eq!(w.step_simulation(0.0, 1, 1.0 / 60.0, |_| {}), Ok(1));
    assert_eq!(
        w.solver_workspace().slot(0).unwrap_err(),
        UninitializedSolverSlot(0)
    );
}

#[test]
fn mmd_dynamics_pair_iteration_uses_axis_sweep_owners_and_cache_order() {
    let mut collision = MmdCollisionWorld::new();
    collision.create_body(sphere(0.0, 10.0), 1).unwrap();
    collision.create_body(sphere(0.25, 10.0), 2).unwrap();
    collision.create_body(sphere(0.5, 10.0), 1).unwrap();
    let mut sweep = AxisSweep32::new_mmd();
    let objects = collision.objects();
    let mut proxies = Vec::new();
    for (i, data) in objects.data().iter().enumerate() {
        let (min, max) = data.shape.aabb(objects.bodies()[i].snapshot().world);
        proxies.push(sweep.add(min, max, i, data.filter[0], data.filter[1], 0));
    }
    for (i, data) in objects.data().iter().enumerate() {
        let (min, max) = data.shape.aabb(objects.bodies()[i].snapshot().world);
        sweep.update(
            proxies[i],
            min.sub(Vec3([0.02; 3])),
            max.add(Vec3([0.02; 3])),
            |_| {},
        );
    }
    let expected: Vec<_> = sweep
        .pairs()
        .iter()
        .map(|p| p.proxies.map(|key| sweep.handle(key).unwrap().owner))
        .collect();
    assert!(sweep
        .pairs()
        .iter()
        .any(|p| p
            .proxies
            .iter()
            .any(|key| sweep.handle(*key).unwrap().owner != key.0 as usize)));
    collision.perform_discrete_collision_detection();
    let (_, _, _, pairs, _) = collision.dynamics_parts();
    assert_eq!(pairs.collect::<Vec<_>>(), expected);
    assert_eq!(expected.len(), 6);
}

#[test]
fn mmd_dynamics_shared_kinematic_endpoints_retain_slots_across_islands_and_orders() {
    for reverse in [false, true] {
        for mode in [1, 2] {
            let mut w = MmdDynamicsWorld::new();
            w.set_gravity(Vec3::ZERO).unwrap();
            let mut desc = sphere(0.0, 10.0);
            desc.filter = Some([0, 0]);
            let mut handles = Vec::new();
            for _ in 0..4 {
                handles.push(w.create_body(desc, mode).unwrap());
            }
            if reverse {
                handles.reverse();
            }
            let [shared, a, b, c] = [handles[0], handles[1], handles[2], handles[3]];
            w.set_kinematic(shared, true).unwrap();
            w.create_joint(joint(a, shared), 7).unwrap();
            w.create_joint(joint(b, c), 8).unwrap();
            w.create_joint(joint(b, shared), 9).unwrap();
            for _ in 0..2 {
                let mut groups = Vec::new();
                let mut capacities = Vec::new();
                w.step_simulation(0.125, 0, 1.0, |e| match e {
                    DynamicsEvent::Solver(SolverEvent::SolveGroup {
                        island,
                        constraints,
                    }) => {
                        groups.push((island.bodies.to_vec(), constraints.to_vec()));
                    }
                    DynamicsEvent::Workspace { live, capacity } => {
                        assert_eq!(live, 0);
                        capacities.push(capacity);
                    }
                    _ => {}
                })
                .unwrap();
                assert_eq!(groups.len(), 2);
                let index = |h| w.collision().objects().index(h).unwrap();
                assert!(groups
                    .iter()
                    .any(|(bodies, joints)| bodies == &[index(a)] && joints == &[0]));
                assert!(groups.iter().any(|(bodies, joints)| {
                    bodies.len() == 2
                        && bodies.contains(&index(b))
                        && bodies.contains(&index(c))
                        && joints.len() == 2
                        && joints.contains(&1)
                        && joints.contains(&2)
                }));
                assert_eq!(capacities, vec![4, 4]);
                let shared_id = w.collision().objects().objects()[index(shared)].companion_id;
                assert!(shared_id > 0);
                assert!(w.solver_workspace().slot(shared_id as usize).is_ok());
                assert_eq!(
                    w.solver_workspace().slot(4).unwrap_err(),
                    UninitializedSolverSlot(4)
                );
                for body in &w.collision().objects().bodies()[1..] {
                    let body = body.snapshot();
                    assert_eq!(body.inverse_mass, 0.5);
                    assert_eq!(body.linear_velocity, Vec3::ZERO);
                    assert_eq!(body.angular_velocity, Vec3::ZERO);
                    assert_eq!(body.world.origin, Vec3([0.0, 10.0, 0.0]));
                }
            }
        }
    }
}
