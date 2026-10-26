use crate::core::activation::{BodyActivation, CollisionClassification};
use crate::core::body::{BodyInit, RigidBody};
use crate::core::contact::ContactPoint;
use crate::core::contact_solver::ContactManifold;
use crate::core::islands::{IslandManifold, IslandObject, SimulationIslands, SolverEvent};
use crate::core::math::{Transform, Vec3};
use crate::core::solver::{
    GroupSelection, GroupSolver, SolverMode, SolverWorkspace, UninitializedSolverSlot,
};

fn body(mass: f32) -> RigidBody {
    RigidBody::new(BodyInit {
        mass,
        local_inertia: Vec3([1.0; 3]),
        center_of_mass: Transform::IDENTITY,
        linear_damping: 0.0,
        angular_damping: 0.0,
    })
}
fn object() -> IslandObject {
    IslandObject {
        activation: BodyActivation::default(),
        classification: CollisionClassification::Dynamic,
        contact_response: true,
        island_tag: -1,
        companion_id: -1,
        hit_fraction: 1.0,
    }
}
fn point() -> ContactPoint {
    ContactPoint {
        normal_on_b: Vec3([1.0, 0.0, 0.0]),
        distance: -0.1,
        applied_impulse: 2.0,
        ..ContactPoint::EMPTY
    }
}

#[test]
fn retained_slots_alias_and_append_overwrite_without_retired_writeback() {
    let mut w = SolverWorkspace::default();
    let mut objects = vec![object(); 4];
    let mut bodies = vec![body(1.0), body(2.0), body(3.0), body(4.0)];
    let mut points = [point()];
    let mut manifolds = [ContactManifold::new([0, 1], &mut points)];
    let selection = GroupSelection {
        bodies: &[0, 1],
        joints: &[],
        manifolds: &[0],
    };
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut manifolds,
        selection,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!((s.bodies.live_len(), s.bodies.native_capacity()), (3, 4));
    assert_eq!(s.bodies.companion_id(1), Some(2));
    s.writeback(&mut bodies, &mut manifolds);
    let retained_before = w.slot(2).unwrap().delta_linear;
    let retired_velocity = bodies[1].snapshot().linear_velocity;
    assert_eq!(w.live_len(), 0);
    // A new body takes slot 1; the old body's companion still selects retained slot 2.
    manifolds[0].bodies = [2, 1];
    let mut s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut manifolds,
        selection,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!(s.normals[0].numeric.bodies, [1, 2]);
    assert_eq!(s.bodies.live_len(), 2);
    assert_ne!(s.bodies.slot(2).unwrap().delta_linear, retained_before);
    s.iterate(&bodies, &[], |_, _| {}).unwrap();
    let retained_after = s.bodies.slot(2).unwrap().delta_linear;
    s.writeback(&mut bodies, &mut manifolds);
    assert_eq!(bodies[1].snapshot().linear_velocity, retired_velocity);
    assert_eq!(w.slot(2).unwrap().delta_linear, retained_after);
    // Registering two fresh endpoints overwrites both append slots, including slot 2.
    objects[0].companion_id = -1;
    manifolds[0].bodies = [3, 0];
    manifolds[0].processing_threshold = -1.0;
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut manifolds,
        selection,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!(s.bodies.slot(2).unwrap().original, Some(0));
    assert_eq!(s.bodies.slot(2).unwrap().delta_linear, Vec3::ZERO);
    s.writeback(&mut bodies, &mut manifolds);
    assert_eq!((w.live_len(), w.native_capacity()), (0, 4));
}

#[test]
fn live_alias_uses_original_endpoint_mass_and_sequential_writes() {
    let mut w = SolverWorkspace::default();
    let mut objects = vec![object(); 3];
    let bodies = vec![body(2.0), body(3.0), body(5.0)];
    let mut points = [point()];
    let mut manifolds = [ContactManifold::new([0, 1], &mut points)];
    let selection = GroupSelection {
        bodies: &[],
        joints: &[],
        manifolds: &[0],
    };
    drop(
        GroupSolver::setup(
            &mut w,
            &mut objects,
            &bodies,
            &mut [],
            &mut manifolds,
            selection,
            1.0 / 60.0,
            SolverMode::Simd,
        )
        .unwrap(),
    );
    manifolds[0].bodies = [2, 0];
    let mut s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut manifolds,
        selection,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!(s.normals[0].numeric.bodies, [1, 1]);
    let impulse = 2.0 * 0.85;
    let expected = 0.0_f32 + (1.0 / 5.0) * impulse - (1.0 / 2.0) * impulse;
    assert_eq!(
        s.bodies.slot(1).unwrap().delta_linear.0[0].to_bits(),
        expected.to_bits()
    );
    s.iterate(&bodies, &[], |_, _| {}).unwrap();
    assert!(s
        .bodies
        .slot(1)
        .unwrap()
        .delta_linear
        .0
        .iter()
        .all(|v| v.is_finite()));
}

#[test]
fn unknown_slots_are_errors_and_empty_selection_preserves_capacity() {
    let mut w = SolverWorkspace::default();
    let mut objects = [object(); 2];
    let bodies = [body(1.0), body(1.0)];
    let mut p = [point()];
    let mut m = [ContactManifold::new([0, 1], &mut p)];
    let empty = GroupSelection {
        bodies: &[],
        joints: &[],
        manifolds: &[],
    };
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut m,
        empty,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!((s.bodies.live_len(), s.bodies.native_capacity()), (0, 0));
    drop(s);
    objects[0].companion_id = 9;
    assert!(matches!(
        GroupSolver::setup(
            &mut w,
            &mut objects,
            &bodies,
            &mut [],
            &mut m,
            GroupSelection {
                manifolds: &[0],
                ..empty
            },
            1.0 / 60.0,
            SolverMode::Simd
        ),
        Err(UninitializedSolverSlot(9))
    ));
    assert_eq!(w.live_len(), 0);
}

#[test]
fn islands_execute_solver_immediately_on_global_manifold_indices() {
    let mut w = SolverWorkspace::default();
    let mut objects = vec![object(); 3];
    objects[0].classification = CollisionClassification::Kinematic;
    let mut bodies = vec![body(2.0), body(3.0), body(5.0)];
    let mut points = [[point()], [point()], [point()]];
    let owners = [[0, 1], [0, 1], [0, 2]];
    let mut manifolds: Vec<_> = points
        .iter_mut()
        .enumerate()
        .map(|(i, p)| ContactManifold::new(owners[i], p))
        .collect();
    let island_manifolds: Vec<_> = owners
        .iter()
        .map(|&bodies| IslandManifold { bodies })
        .collect();
    let mut islands = SimulationIslands::default();
    for step in 0..2 {
        islands.calculate(&mut objects, owners, &[]);
        assert_eq!(objects[0].companion_id, -2);
        let mut calls = Vec::new();
        islands.solve_constraints(
            &mut objects,
            &island_manifolds,
            &[],
            true,
            |objects, event| {
                if let SolverEvent::SolveGroup {
                    island,
                    constraints,
                } = event
                {
                    if !calls.is_empty() {
                        assert!(objects[0].companion_id >= 0);
                    }
                    calls.push(island.manifolds.to_vec());
                    let mut s = GroupSolver::setup(
                        &mut w,
                        objects,
                        &bodies,
                        &mut [],
                        &mut manifolds,
                        GroupSelection {
                            bodies: island.bodies,
                            joints: constraints,
                            manifolds: island.manifolds,
                        },
                        1.0 / 60.0,
                        SolverMode::Simd,
                    )
                    .unwrap();
                    s.iterate(&bodies, &[], |_, _| {}).unwrap();
                    s.writeback(&mut bodies, &mut manifolds);
                }
            },
        );
        assert_eq!(calls, [vec![1, 0], vec![2]], "step {step}");
        assert_eq!((w.live_len(), w.native_capacity()), (0, 4));
    }
}

#[test]
fn capacity_growth_is_native_live_size_and_survives_step_reset() {
    let mut w = SolverWorkspace::default();
    let mut objects = vec![object(); 5];
    let mut bodies: Vec<_> = (0..5).map(|_| body(1.0)).collect();
    let mut points: [Vec<ContactPoint>; 4] = std::array::from_fn(|_| Vec::new());
    let mut manifolds: Vec<_> = points
        .iter_mut()
        .enumerate()
        .map(|(i, p)| ContactManifold::new([i, i + 1], p))
        .collect();
    let selection = GroupSelection {
        bodies: &[],
        joints: &[],
        manifolds: &[0, 1, 2, 3],
    };
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut manifolds,
        selection,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!((s.bodies.live_len(), s.bodies.native_capacity()), (1, 1));
    s.writeback(&mut bodies, &mut manifolds);
    // Nonempty but excluded points still register endpoints.
    drop(manifolds);
    for p in &mut points {
        p.push(point());
    }
    let mut manifolds: Vec<_> = points
        .iter_mut()
        .enumerate()
        .map(|(i, p)| ContactManifold {
            bodies: [i, i + 1],
            points: p,
            processing_threshold: -1.0,
        })
        .collect();
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut manifolds,
        selection,
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!((s.bodies.live_len(), s.bodies.native_capacity()), (6, 8));
    assert!(s.normals.is_empty());
    s.writeback(&mut bodies, &mut manifolds);
    let mut islands = SimulationIslands::default();
    islands.calculate(&mut objects, [], &[]);
    assert_eq!(w.native_capacity(), 8);
    assert!(objects.iter().all(|o| o.companion_id == -1));
    let mut zero_points = [point()];
    let mut zero_manifolds = [ContactManifold::new([0, 1], &mut zero_points)];
    bodies[0] = body(0.0);
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut zero_manifolds,
        GroupSelection {
            manifolds: &[0],
            ..selection
        },
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!((s.bodies.live_len(), s.bodies.native_capacity()), (2, 8));
    assert_eq!(s.normals[0].numeric.bodies, [0, 1]);
}

#[test]
fn same_index_resolve_keeps_both_sequential_updates() {
    use crate::core::solver::{resolve, ImpulseRow, SolverBody};
    let mut b = [SolverBody {
        original: Some(0),
        inverse_mass: Vec3([1.0, 0.0, 0.0]),
        angular_factor: Vec3([1.0; 3]),
        delta_linear: Vec3([5.0, 0.0, 0.0]),
        delta_angular: Vec3::ZERO,
    }];
    let mut row = ImpulseRow {
        bodies: [0, 0],
        normal: Vec3([1.0, 0.0, 0.0]),
        angular: [Vec3::ZERO; 2],
        angular_components: [Vec3([2.0, 0.0, 0.0]), Vec3([3.0, 0.0, 0.0])],
        diagonal_inverse: 0.0,
        rhs: 3.0,
        cfm: 0.0,
        lower_impulse: 0.0,
        upper_impulse: 100.0,
        applied_impulse: 0.0,
    };
    resolve(&mut b, &mut row, SolverMode::Simd, false);
    assert_eq!(b[0].delta_linear, Vec3([5.0, 0.0, 0.0]));
    assert_eq!(b[0].delta_angular, Vec3([15.0, 0.0, 0.0]));
}

#[test]
fn selection_mutates_original_global_joint_and_point_registries_in_order() {
    use crate::core::joint_rows::{AngularMotor, AxisMotor, JointState, Spring};
    use crate::core::solver::{Joint, SolveEvent};
    let axis = AxisMotor {
        lower: 1.0,
        upper: -1.0,
        enabled: false,
        target_velocity: 0.0,
        max_motor_force: 0.0,
        current_position: 99.0,
        current_limit: 0,
        current_limit_error: 0.0,
    };
    let joint = Joint {
        bodies: [0, 1],
        frames: [Transform::IDENTITY; 2],
        state: JointState {
            linear: [axis; 3],
            angular: [AngularMotor {
                motor: axis,
                erp: 0.2,
                bounce: 0.0,
            }; 3],
            linear_erp: 0.2,
            springs: [Spring {
                enabled: false,
                equilibrium: 0.0,
                stiffness: 0.0,
                damping: 0.0,
            }; 6],
        },
    };
    let mut joints = vec![joint.clone(), joint.clone(), joint];
    for i in [0, 2] {
        joints[i].state.linear[0].enabled = true;
        joints[i].state.linear[0].max_motor_force = 1.0;
        joints[i].state.linear[0].target_velocity = if i == 2 { 9.0 } else { 4.0 };
    }
    let mut bodies = [body(1.0), body(2.0)];
    let mut objects = [object(); 2];
    let mut w = SolverWorkspace::default();
    let mut p = [[point()], [point()], [point()]];
    let mut m: Vec<_> = p
        .iter_mut()
        .map(|p| ContactManifold::new([0, 1], p))
        .collect();
    let mut s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut joints,
        &mut m,
        GroupSelection {
            bodies: &[],
            joints: &[2, 0],
            manifolds: &[2, 0],
        },
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!(s.joint_rows.len(), 2);
    assert!(s.joint_rows[0].rhs > s.joint_rows[1].rhs);
    assert_eq!(joints[1].state.linear[0].current_position, 99.0);
    assert_eq!(joints[0].state.linear[0].current_position, 0.0);
    assert_eq!(joints[2].state.linear[0].current_position, 0.0);
    assert_eq!(
        s.normals.iter().map(|r| r.point).collect::<Vec<_>>(),
        [[2, 0], [0, 0]]
    );
    let mut callbacks = Vec::new();
    s.iterate(&bodies, &joints, |_, event| {
        if let SolveEvent::Obsolete { joint, .. } = event {
            callbacks.push(joint)
        }
    })
    .unwrap();
    assert_eq!(callbacks, [2, 2, 0, 0].repeat(10));
    let expected = [
        s.normals[0].numeric.applied_impulse,
        s.normals[1].numeric.applied_impulse,
    ];
    s.writeback(&mut bodies, &mut m);
    assert_eq!(m[2].points[0].applied_impulse, expected[0]);
    assert_eq!(m[0].points[0].applied_impulse, expected[1]);
    assert_eq!(m[1].points[0].applied_impulse, 2.0);
}

#[test]
fn fixed_and_one_dynamic_slot_grow_capacity_to_two() {
    let mut w = SolverWorkspace::default();
    let mut objects = [object(); 2];
    let bodies = [body(0.0), body(1.0)];
    let mut p = [point()];
    let mut m = [ContactManifold::new([0, 1], &mut p)];
    let s = GroupSolver::setup(
        &mut w,
        &mut objects,
        &bodies,
        &mut [],
        &mut m,
        GroupSelection {
            bodies: &[],
            joints: &[],
            manifolds: &[0],
        },
        1.0 / 60.0,
        SolverMode::Simd,
    )
    .unwrap();
    assert_eq!((s.bodies.live_len(), s.bodies.native_capacity()), (2, 2));
    assert_eq!(s.bodies.companion_id(0), None);
}
