use crate::core::activation::ActivationState;
use crate::core::math::{Basis, Quat, Transform, Vec3};
use crate::core::world_objects::{BodyDesc, Pose, WorldObjects};
fn desc(mass: f32, kinematic: bool) -> BodyDesc {
    BodyDesc {
        shape_kind: 0,
        shape_params: [0.5, 0.0, 0.0, 0.0],
        mass,
        pose: Pose {
            position: Vec3::ZERO,
            rotation: Quat::IDENTITY,
        },
        kinematic,
        linear_damping: 0.0,
        angular_damping: 0.0,
        restitution: 0.0,
        friction: 0.5,
        filter: None,
    }
}
#[test]
fn kinematic_save_uses_motion_even_outside_nonstatic_and_when_disabled() {
    let mut w = WorldObjects::public();
    let h = w.create_public_body(desc(2.0, true)).unwrap();
    assert!(w.non_static().is_empty());
    w.solver_parts().1[0]
        .activation
        .force_activation_state(ActivationState::DisableSimulation);
    let t = Transform {
        origin: Vec3([2.0, 0.0, 0.0]),
        ..Transform::IDENTITY
    };
    w.set_motion_state(h, t).unwrap();
    w.save_kinematic_state(0.0);
    assert_eq!(w.bodies()[0].snapshot().world.origin, Vec3::ZERO);
    w.save_kinematic_state(0.5);
    let s = w.bodies()[0].snapshot();
    assert_eq!(s.world, t);
    assert_eq!(s.interpolation_world, t);
    assert_eq!(s.linear_velocity, Vec3([4.0, 0.0, 0.0]));
    assert_eq!(s.interpolation_linear_velocity, s.linear_velocity);
    w.solver_parts().1[0]
        .activation
        .force_activation_state(ActivationState::IslandSleeping);
    w.set_motion_state(h, Transform::IDENTITY).unwrap();
    w.save_kinematic_state(0.5);
    assert_eq!(w.bodies()[0].snapshot().world, t);
}
#[test]
fn prediction_updates_sleeping_interpolation_without_advancing_body_or_motion() {
    let mut w = WorldObjects::public();
    w.create_public_body(desc(2.0, false)).unwrap();
    let (b, o, _) = w.solver_parts();
    b[0].set_linear_velocity(Vec3([2.0, 0.0, 0.0]));
    o[0].activation
        .force_activation_state(ActivationState::IslandSleeping);
    w.predict_unconstraint_motion(0.5);
    let s = w.bodies()[0].snapshot();
    assert_eq!(s.interpolation_world.origin, Vec3([1.0, 0.0, 0.0]));
    assert_eq!(s.world, Transform::IDENTITY);
    assert_eq!(s.interpolation_linear_velocity, Vec3::ZERO);
    assert_eq!(w.data()[0].motion.graphics_world, Transform::IDENTITY);
}
#[test]
fn gravity_and_clear_keep_registration_membership_and_activation_rules() {
    let mut w = WorldObjects::public();
    w.create_public_body(desc(2.0, false)).unwrap();
    w.create_public_body(desc(0.0, false)).unwrap();
    w.solver_parts().0[1].add_force(Vec3([1.0, 2.0, 3.0]));
    w.apply_gravity();
    assert_eq!(
        w.bodies()[0].snapshot().total_force,
        Vec3([0.0, -19.6, 0.0])
    );
    w.solver_parts().1[0]
        .activation
        .force_activation_state(ActivationState::IslandSleeping);
    w.apply_gravity();
    assert_eq!(
        w.bodies()[0].snapshot().total_force,
        Vec3([0.0, -19.6, 0.0])
    );
    w.clear_forces();
    assert_eq!(w.bodies()[0].snapshot().total_force, Vec3::ZERO);
    assert_eq!(w.bodies()[1].snapshot().total_force, Vec3([1.0, 2.0, 3.0]));
}
#[test]
fn synchronization_uses_interpolation_velocity_hit_fraction_and_all_mode() {
    let mut w = WorldObjects::public();
    w.create_public_body(desc(2.0, false)).unwrap();
    let (b, o, _) = w.solver_parts();
    b[0].set_interpolation_world_transform(Transform {
        origin: Vec3([3.0, 0.0, 0.0]),
        ..Transform::IDENTITY
    });
    b[0].set_interpolation_velocities(Vec3([4.0, 0.0, 0.0]), Vec3::ZERO);
    o[0].hit_fraction = 0.25;
    o[0].activation
        .force_activation_state(ActivationState::DisableSimulation);
    w.synchronize_motion_states(0.5, false);
    assert_eq!(w.data()[0].motion.graphics_world, Transform::IDENTITY);
    w.synchronize_motion_states(0.5, true);
    assert_eq!(
        w.data()[0].motion.graphics_world.origin,
        Vec3([3.5, 0.0, 0.0])
    );
    assert_eq!(w.bodies()[0].snapshot().world, Transform::IDENTITY);
}
#[test]
fn calculate_velocity_uses_matrix_inverse_for_nonorthogonal_basis() {
    let old = Transform {
        basis: Basis([[2.0, 0.25, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
        ..Transform::IDENTITY
    };
    let (linear, angular) = old.calculate_velocity(old, 0.5);
    assert_eq!(linear, Vec3::ZERO);
    assert_eq!(angular, Vec3::ZERO);
}

#[test]
fn activation_uses_captured_membership_and_the_shared_activation_owner() {
    use crate::core::activation::DeactivationSettings;
    let mut w = WorldObjects::public();
    let dynamic = w.create_public_body(desc(2.0, false)).unwrap();
    w.create_public_body(desc(0.0, true)).unwrap();
    w.set_kinematic(dynamic, true).unwrap();
    for o in w.solver_parts().1 {
        o.activation.force_activation_state(ActivationState::Active);
        o.activation.deactivation_time = 3.0;
    }
    w.update_activation_state(0.0, DeactivationSettings::default());
    assert_eq!(
        w.objects()[0].activation.state,
        ActivationState::IslandSleeping
    );
    assert_eq!(w.objects()[1].activation.state, ActivationState::Active);
    w.set_kinematic(dynamic, false).unwrap();
    w.solver_parts().0[0].set_linear_velocity(Vec3([0.25, 0.0, 0.0]));
    w.update_activation_state(0.25, DeactivationSettings::default());
    assert_eq!(w.bodies()[0].snapshot().linear_velocity, Vec3::ZERO);
    assert_eq!(
        w.dispatch_objects()[0].activation.state,
        ActivationState::IslandSleeping
    );
}

#[test]
fn activation_sleeping_zeros_both_velocities_and_wants_deactivation_keeps_them() {
    use crate::core::activation::DeactivationSettings;
    let mut w = WorldObjects::public();
    for state in [
        ActivationState::IslandSleeping,
        ActivationState::WantsDeactivation,
    ] {
        let h = w.create_public_body(desc(2.0, false)).unwrap();
        let i = w.index(h).unwrap();
        let (b, o, _) = w.solver_parts();
        b[i].set_linear_velocity(Vec3([0.25, 0.0, 0.0]));
        b[i].set_angular_velocity(Vec3([0.5, 0.0, 0.0]));
        b[i].set_interpolation_velocities(Vec3([3.0, 0.0, 0.0]), Vec3([4.0, 0.0, 0.0]));
        o[i].activation.force_activation_state(state);
    }
    w.update_activation_state(0.25, DeactivationSettings::default());
    let sleeping = w.bodies()[0].snapshot();
    assert_eq!(sleeping.linear_velocity, Vec3::ZERO);
    assert_eq!(sleeping.angular_velocity, Vec3::ZERO);
    assert_eq!(
        sleeping.interpolation_linear_velocity,
        Vec3([3.0, 0.0, 0.0])
    );
    assert_eq!(
        sleeping.interpolation_angular_velocity,
        Vec3([4.0, 0.0, 0.0])
    );
    let wants = w.bodies()[1].snapshot();
    assert_eq!(wants.linear_velocity, Vec3([0.25, 0.0, 0.0]));
    assert_eq!(wants.angular_velocity, Vec3([0.5, 0.0, 0.0]));
}

#[test]
fn activation_obeys_supplied_settings_strict_threshold_and_protected_states() {
    use crate::core::activation::DeactivationSettings;
    let mut w = WorldObjects::public();
    for state in [
        ActivationState::Active,
        ActivationState::DisableDeactivation,
        ActivationState::DisableSimulation,
    ] {
        let h = w.create_public_body(desc(2.0, false)).unwrap();
        let i = w.index(h).unwrap();
        w.solver_parts().1[i]
            .activation
            .force_activation_state(state);
    }
    let settings = DeactivationSettings {
        time: 0.5,
        disabled: false,
    };
    w.update_activation_state(0.5, settings);
    assert_eq!(w.objects()[0].activation.state, ActivationState::Active);
    w.update_activation_state(0.25, settings);
    assert_eq!(
        w.objects()[0].activation.state,
        ActivationState::WantsDeactivation
    );
    assert_eq!(w.objects()[0].activation.deactivation_time, 0.75);
    assert_eq!(
        w.objects()[1].activation.state,
        ActivationState::DisableDeactivation
    );
    assert_eq!(
        w.objects()[2].activation.state,
        ActivationState::DisableSimulation
    );
    w.update_activation_state(
        0.25,
        DeactivationSettings {
            disabled: true,
            ..settings
        },
    );
    assert_eq!(w.objects()[0].activation.state, ActivationState::Active);
}
