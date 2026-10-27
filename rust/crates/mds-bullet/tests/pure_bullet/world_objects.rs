use crate::core::activation::ActivationState;
use crate::core::math::{Quat, Transform, Vec3};
use crate::core::world_objects::{BodyDesc, JointDesc, MotionState, Pose, WorldObjects};

fn pose(x: f32) -> Pose {
    Pose {
        position: Vec3([x, 0.0, 0.0]),
        rotation: Quat([0.0, 0.0, 0.0, 1.0]),
    }
}
fn desc(mass: f32) -> BodyDesc {
    BodyDesc {
        shape_kind: 0,
        shape_params: [0.5, 0.0, 0.0, 0.0],
        mass,
        pose: pose(0.0),
        kinematic: false,
        linear_damping: 0.0,
        angular_damping: 0.0,
        restitution: 0.0,
        friction: 0.5,
        filter: None,
    }
}
fn joint(
    a: crate::core::world_objects::BodyHandle,
    b: crate::core::world_objects::BodyHandle,
) -> JointDesc {
    JointDesc {
        bodies: [a, b],
        frames: [pose(0.0); 2],
        linear_lower: Vec3::ZERO,
        linear_upper: Vec3::ZERO,
        angular_lower: Vec3([-0.0; 3]),
        angular_upper: Vec3::ZERO,
        spring_enabled: [true; 6],
        spring_stiffness: [2.0; 6],
        use_linear_reference_frame_a: false,
        disable_collisions: true,
    }
}

#[test]
fn registration_rejections_do_not_consume_indices_or_accept_foreign_handles() {
    let mut a = WorldObjects::public();
    let mut b = WorldObjects::public();
    let foreign = b.create_public_body(desc(1.0)).unwrap();
    let mut invalid = desc(1.0);
    invalid.shape_params[0] = -1.0;
    assert!(a.create_public_body(invalid).is_err());
    let first = a.create_public_body(desc(1.0)).unwrap();
    assert_eq!(a.index(first), Ok(0));
    assert!(a.index(foreign).is_err());
    assert!(a.create_joint(joint(first, foreign), None).is_err());
    assert!(a.joints().is_empty());
}

#[test]
fn registration_history_and_active_state_control_gravity() {
    let mut w = WorldObjects::public();
    let dynamic = w.create_public_body(desc(1.0)).unwrap();
    let static_body = w.create_public_body(desc(0.0)).unwrap();
    let mut k = desc(1.0);
    k.kinematic = true;
    w.create_public_body(k).unwrap();
    assert_eq!(w.non_static(), &[0]);
    assert_eq!(w.data()[1].filter, [2, -3]);
    w.set_kinematic(dynamic, true).unwrap();
    w.set_kinematic(static_body, true).unwrap();
    w.set_gravity(Vec3([1.0, 2.0, 3.0])).unwrap();
    assert_eq!(
        w.bodies()[0].snapshot().gravity_acceleration,
        Vec3([1.0, 2.0, 3.0])
    );
    assert_eq!(w.bodies()[1].snapshot().gravity_acceleration, Vec3::ZERO);
    w.solver_parts().1[0]
        .activation
        .force_activation_state(ActivationState::IslandSleeping);
    w.set_gravity(Vec3([5.0; 3])).unwrap();
    assert_eq!(
        w.bodies()[0].snapshot().gravity_acceleration,
        Vec3([1.0, 2.0, 3.0])
    );
}

#[test]
fn public_transform_uses_registration_kinematic_state_after_classification_changes() {
    for initially_kinematic in [false, true] {
        let mut w = WorldObjects::public();
        let mut d = desc(1.0);
        d.kinematic = initially_kinematic;
        let h = w.create_public_body(d).unwrap();
        let initial = w.bodies()[0].snapshot();
        for (step, current_kinematic) in [initially_kinematic, !initially_kinematic]
            .into_iter()
            .enumerate()
        {
            w.set_kinematic(h, current_kinematic).unwrap();
            let target = Pose {
                position: Vec3([3.0 + step as f32, -2.0, 5.0]),
                rotation: Quat([0.0, 0.0, 1.0, 0.0]),
            };
            w.set_public_transform(h, target).unwrap();
            let expected = target.transform();
            assert_eq!(w.public_transform(h).unwrap(), expected);
            assert_eq!(w.data()[0].motion.graphics_world, expected);
            let body = w.bodies()[0].snapshot();
            assert_eq!(body.is_kinematic, current_kinematic);
            if initially_kinematic {
                assert_eq!(body.world, initial.world);
                assert_eq!(body.interpolation_world, initial.interpolation_world);
            } else {
                assert_eq!(body.world, expected);
                assert_eq!(body.interpolation_world, expected);
            }
        }
    }
}

#[test]
fn rejected_public_transforms_preserve_motion_body_and_interpolation() {
    let mut w = WorldObjects::public();
    let dynamic = w.create_public_body(desc(1.0)).unwrap();
    let static_body = w.create_public_body(desc(0.0)).unwrap();
    let mut other = WorldObjects::public();
    let foreign = other.create_public_body(desc(1.0)).unwrap();
    let mut mmd = WorldObjects::mmd();
    let mmd_body = mmd.create_mmd_body(desc(1.0), 1).unwrap();
    w.set_public_transform(dynamic, pose(4.0)).unwrap();
    let before: Vec<_> = w.bodies().iter().map(|b| b.snapshot()).collect();
    let motion: Vec<_> = w.data().iter().map(|d| d.motion.graphics_world).collect();
    let mut invalid_rotation = pose(8.0);
    invalid_rotation.rotation = Quat([0.0; 4]);
    let mut infinite_rotation = pose(8.0);
    infinite_rotation.rotation.0[1] = f32::INFINITY;
    for (handle, target) in [
        (dynamic, pose(f32::NAN)),
        (dynamic, pose(f32::INFINITY)),
        (dynamic, invalid_rotation),
        (dynamic, infinite_rotation),
        (static_body, pose(8.0)),
        (foreign, pose(8.0)),
        (mmd_body, pose(8.0)),
    ] {
        assert!(w.set_public_transform(handle, target).is_err());
        for (i, body) in w.bodies().iter().enumerate() {
            assert_eq!(body.snapshot(), before[i]);
            assert_eq!(w.data()[i].motion.graphics_world, motion[i]);
        }
    }
    assert_eq!(
        other.public_transform(foreign).unwrap(),
        pose(0.0).transform()
    );
    assert_eq!(
        mmd.public_transform(mmd_body).unwrap(),
        pose(0.0).transform()
    );
}

#[test]
fn public_gravity_getter_and_bodies_preserve_last_valid_change_on_rejection() {
    let mut w = WorldObjects::public();
    assert_eq!(w.gravity(), Vec3([0.0, -9.8, 0.0]));
    let h = w.create_public_body(desc(1.0)).unwrap();
    let gravity = Vec3([1.0, -4.0, 2.0]);
    w.set_gravity(gravity).unwrap();
    assert_eq!(w.gravity(), gravity);
    let before = w.bodies()[w.index(h).unwrap()].snapshot();
    assert_eq!(before.gravity_acceleration, gravity);
    for invalid in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
        assert!(w.set_gravity(Vec3([0.0, invalid, 0.0])).is_err());
        assert_eq!(w.gravity(), gravity);
        assert_eq!(w.bodies()[0].snapshot(), before);
    }
    let mut mmd = WorldObjects::mmd();
    assert_eq!(mmd.gravity(), Vec3([0.0, -98.0, 0.0]));
    mmd.set_gravity(gravity).unwrap();
    assert_eq!(mmd.gravity(), gravity);
}

#[test]
fn motion_body_and_interpolation_are_distinct_owned_state() {
    let mut w = WorldObjects::mmd();
    let h = w.create_mmd_body(desc(1.0), 1).unwrap();
    let old = w.bodies()[1].snapshot().world;
    w.set_motion_state(h, pose(3.0).transform()).unwrap();
    assert_eq!(w.bodies()[1].snapshot().world, old);
    let (b, _, _) = w.solver_parts();
    b[1].set_linear_velocity(Vec3([4.0; 3]));
    b[1].set_angular_velocity(Vec3([5.0; 3]));
    b[1].set_interpolation_velocities(Vec3([6.0; 3]), Vec3([7.0; 3]));
    w.stop_at(h, Vec3([9.0; 3])).unwrap();
    assert_eq!(
        w.bodies()[1].snapshot().interpolation_linear_velocity,
        Vec3([6.0; 3])
    );
    w.reseat(h, pose(8.0).transform()).unwrap();
    let s = w.bodies()[1].snapshot();
    assert_eq!(s.interpolation_world, old);
    assert_eq!(s.interpolation_linear_velocity, Vec3::ZERO);
    assert_eq!(w.public_transform(h).unwrap().origin, Vec3([3.0, 0.0, 0.0]));
    w.set_floor(false).unwrap();
    assert_eq!(w.data()[0].collision_flags, -1);
    w.set_floor(true).unwrap();
    assert_eq!(w.data()[0].collision_flags, 1);
}

#[test]
fn joints_keep_collision_refs_and_shim_specific_equilibrium_and_zero_bits() {
    let mut w = WorldObjects::public();
    let a = w.create_public_body(desc(1.0)).unwrap();
    let mut d = desc(1.0);
    d.pose = pose(2.0);
    let b = w.create_public_body(d).unwrap();
    let j = joint(a, b);
    w.create_joint(j, None).unwrap();
    assert!(!w.joint_data()[0].use_linear_reference_frame_a);
    assert!(w.joint_data()[0].disable_collisions);
    assert_eq!(w.joint_data()[0].mmd_uid, None);
    assert_eq!(w.joints()[0].state.springs[0].equilibrium, 0.0);
    assert_eq!(
        w.joints()[0].state.angular[0].motor.lower.to_bits(),
        (-0.0f32).to_bits()
    );
    assert_eq!(w.data()[0].disabled_collision_refs.len(), 1);
    let mut enabled = j;
    enabled.disable_collisions = false;
    enabled.use_linear_reference_frame_a = true;
    w.create_joint(enabled, None).unwrap();
    assert!(w.joint_data()[1].use_linear_reference_frame_a);
    assert!(!w.joint_data()[1].disable_collisions);
    assert_eq!(w.data()[0].disabled_collision_refs.len(), 1);
    w.create_joint(j, Some(17)).unwrap();
    assert_eq!(w.joints()[2].state.springs[0].equilibrium, 2.0);
    assert_eq!(w.joints()[2].state.angular[0].motor.lower.to_bits(), 0);
    assert_eq!(w.data()[0].disabled_collision_refs.len(), 1);
    assert_eq!(w.joint_data()[2].mmd_uid, Some(17));
    assert!(w.joint_data()[2].use_linear_reference_frame_a);
    assert!(!w.joint_data()[2].disable_collisions);
    for data in w.data() {
        assert_eq!(data.disabled_collision_refs.len(), 1);
        assert_eq!(data.disabled_collision_refs[0].bodies, [0, 1]);
    }
}

#[test]
fn motion_state_always_executes_offset_products() {
    let offset = pose(2.0).transform();
    let mut m = MotionState::new(pose(5.0).transform(), offset);
    assert_eq!(m.get_world_transform().origin, Vec3([3.0, 0.0, 0.0]));
    m.set_world_transform(pose(9.0).transform());
    assert_eq!(m.graphics_world.origin, Vec3([11.0, 0.0, 0.0]));
    assert_eq!(m.start_world.origin, Vec3([5.0, 0.0, 0.0]));
    assert_eq!(m.center_of_mass_offset, offset);
    assert_eq!(Transform::IDENTITY.basis, m.graphics_world.basis);
}

#[test]
fn dispatcher_and_solver_mutate_the_registered_arrays_directly() {
    use crate::core::dispatcher::CollisionDispatcher;
    use crate::core::solver::{solve_group, GroupSelection, SolverWorkspace};
    let mut w = WorldObjects::public();
    let a = w.create_public_body(desc(1.0)).unwrap();
    let mut d = desc(1.0);
    d.pose = pose(0.75);
    let b = w.create_public_body(d).unwrap();
    let mut j = joint(a, b);
    j.disable_collisions = false;
    j.spring_enabled = [false; 6];
    w.create_joint(j, None).unwrap();
    let mut dispatcher = CollisionDispatcher::new();
    let mut algorithm = None;
    dispatcher.near_pair(&mut algorithm, [0, 1], &w.dispatch_objects());
    assert_eq!(dispatcher.manifolds().len(), 1);
    assert!(!dispatcher.manifolds()[0].manifold.contacts().is_empty());
    let mut manifolds: Vec<_> = dispatcher
        .manifolds_mut()
        .iter_mut()
        .map(|m| m.contact_view())
        .collect();
    let mut workspace = SolverWorkspace::default();
    let (bodies, objects, joints) = w.solver_parts();
    solve_group(
        &mut workspace,
        objects,
        bodies,
        joints,
        &mut manifolds,
        GroupSelection {
            bodies: &[0, 1],
            joints: &[0],
            manifolds: &[0],
        },
        1.0 / 60.0,
    )
    .unwrap();
    assert_ne!(w.bodies()[0].snapshot().linear_velocity, Vec3::ZERO);
    assert_ne!(w.objects()[0].companion_id, -1);
    assert_ne!(w.joints()[0].state.linear[0].current_position, 0.0);
}
