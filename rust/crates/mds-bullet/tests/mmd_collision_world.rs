#![allow(dead_code)]
#[path = "../src/core/mod.rs"]
mod core;

use core::activation::ActivationState;
use core::math::{Quat, Transform, Vec3};
use core::mmd_collision_world::MmdCollisionWorld;
use core::world_objects::{BodyDesc, JointDesc, Pose};
use core::InvalidArgument;

fn body(kind: i32, x: f32) -> BodyDesc {
    BodyDesc {
        shape_kind: kind,
        shape_params: match kind {
            0 => [0.75, 0.0, 0.0, 0.0],
            1 => [0.75, 0.5, 0.625, 0.0],
            _ => [0.4, 1.0, 0.0, 0.0],
        },
        mass: 2.0,
        pose: Pose {
            position: Vec3([x, 3.0, 0.0]),
            rotation: Quat([0.0, 0.0, 0.0, 1.0]),
        },
        kinematic: false,
        linear_damping: 0.0,
        angular_damping: 0.0,
        restitution: 0.25,
        friction: 0.5,
        filter: Some([1, -1]),
    }
}

fn at(x: f32) -> Transform {
    body(0, x).pose.transform()
}

#[test]
fn mmd_world_constructor_keeps_ground_first() {
    let mut w = MmdCollisionWorld::new();
    assert_eq!(w.objects().gravity(), Vec3([0.0, -98.0, 0.0]));
    assert_eq!(w.objects().bodies().len(), 1);
    assert_eq!(w.objects().data()[0].filter, [i16::MIN, -1]);
    assert_eq!(w.objects().bodies()[0].contact_body().restitution, 0.88);
    let b = w.create_body(body(0, 0.0), 1).unwrap();
    assert_eq!(w.objects().index(b).unwrap(), 1);
    w.perform_discrete_collision_detection();
    assert_eq!(w.manifolds().len(), 1);
    assert!(w.manifolds()[0].manifold.contacts().is_empty());
}

#[test]
fn mmd_world_ordered_shapes_persist_separate_and_recontact() {
    for a in 0..3 {
        for b in 0..3 {
            let mut w = MmdCollisionWorld::new();
            let moving = w.create_body(body(a, 0.0), 1).unwrap();
            w.create_body(body(b, 0.25), 2).unwrap();
            w.perform_discrete_collision_detection();
            let pair = w.manifolds().iter().find(|m| m.bodies == [1, 2]).unwrap();
            assert!(!pair.manifold.contacts().is_empty());
            let owner = pair.owner();
            w.perform_discrete_collision_detection();
            let pair = w.manifolds().iter().find(|m| m.bodies == [1, 2]).unwrap();
            assert_eq!(pair.owner(), owner);
            assert!(pair.manifold.contacts().iter().any(|p| p.lifetime > 0));
            w.reseat(moving, at(50.0)).unwrap();
            w.update_single_aabb(moving).unwrap();
            assert!(w.manifolds().iter().all(|m| m.bodies != [1, 2]));
            w.reseat(moving, at(0.0)).unwrap();
            w.perform_discrete_collision_detection();
            assert!(w.manifolds().iter().any(|m| m.bodies == [1, 2]));
        }
    }
}

#[test]
fn mmd_world_floor_off_preserves_proxy_contacts() {
    for kind in 0..3 {
        for initially_on in [false, true] {
            let mut w = MmdCollisionWorld::new();
            w.set_floor(initially_on).unwrap();
            let mut d = body(kind, 0.0);
            d.pose.position.0[1] = 0.0;
            w.create_body(d, 1).unwrap();
            w.perform_discrete_collision_detection();
            let owner = w.manifolds()[0].owner();
            assert!(!w.manifolds()[0].manifold.contacts().is_empty());
            w.set_floor(false).unwrap();
            w.perform_discrete_collision_detection();
            assert_eq!(w.objects().data()[0].collision_flags, -1);
            assert_eq!(w.manifolds()[0].owner(), owner);
            assert!(!w.manifolds()[0].manifold.contacts().is_empty());
            w.set_floor(true).unwrap();
            w.perform_discrete_collision_detection();
            assert_eq!(w.objects().data()[0].collision_flags, 1);
            assert_eq!(w.manifolds()[0].owner(), owner);
        }
    }
}

#[test]
fn mmd_world_signed_filters_are_bidirectional() {
    for (a, b, accepted) in [
        ([1, -1], [1, -1], true),
        ([i16::MIN, -1], [1, i16::MIN], true),
        ([-1, -1], [i16::MIN, -1], true),
        ([1, 0], [1, -1], false),
        ([0, -1], [1, -1], false),
        ([2, 1], [1, 2], true),
        ([2, 2], [1, -1], false),
        ([1, -1], [2, 2], false),
    ] {
        let mut w = MmdCollisionWorld::new();
        let mut d = body(0, 0.0);
        d.filter = Some(a);
        w.create_body(d, 1).unwrap();
        d.pose.position.0[0] = 0.25;
        d.filter = Some(b);
        w.create_body(d, 1).unwrap();
        w.perform_discrete_collision_detection();
        assert_eq!(w.manifolds().iter().any(|m| m.bodies == [1, 2]), accepted);
    }
}

#[test]
fn mmd_world_mode_toggle_preserves_static_bit_and_mass() {
    for a in 0..3 {
        for b in 0..3 {
            let mut w = MmdCollisionWorld::new();
            let first = w.create_body(body(0, 0.0), a).unwrap();
            w.create_body(body(1, 0.25), b).unwrap();
            let mass = w.objects().bodies()[1].snapshot().inverse_mass;
            assert_eq!(mass, if a == 0 { 0.0 } else { 0.5 });
            w.set_kinematic(first, true).unwrap();
            assert_eq!(w.objects().bodies()[1].snapshot().inverse_mass, mass);
            w.set_kinematic(first, false).unwrap();
            assert_eq!(
                w.objects().data()[1].collision_flags,
                if a == 0 { 1 } else { 0 }
            );
            assert_eq!(w.objects().bodies()[1].snapshot().inverse_mass, mass);
            assert_eq!(
                w.objects().objects()[1].activation.state,
                ActivationState::DisableDeactivation
            );
            w.perform_discrete_collision_detection();
        }
    }
}

#[test]
fn mmd_world_motion_reseat_and_stop_remain_distinct() {
    for kind in 0..3 {
        let mut w = MmdCollisionWorld::new();
        let a = w.create_body(body(kind, 0.0), 1).unwrap();
        w.create_body(body(0, 0.25), 1).unwrap();
        w.set_motion_state(a, at(100.0)).unwrap();
        w.perform_discrete_collision_detection();
        assert!(w.manifolds().iter().any(|m| m.bodies == [1, 2]));
        assert_eq!(
            w.objects().bodies()[1].snapshot().world.origin,
            at(0.0).origin
        );
        w.reseat(a, at(50.0)).unwrap();
        w.perform_discrete_collision_detection();
        assert!(w.manifolds().iter().all(|m| m.bodies != [1, 2]));
        assert_eq!(
            w.objects().data()[1].motion.get_world_transform().origin,
            at(100.0).origin
        );
        w.stop_at(a, at(0.0).origin).unwrap();
        w.perform_discrete_collision_detection();
        assert!(w.manifolds().iter().any(|m| m.bodies == [1, 2]));
        assert_eq!(
            w.objects().data()[1].motion.get_world_transform().origin,
            at(100.0).origin
        );
    }
}

#[test]
fn mmd_world_joint_uid_does_not_suppress_collision() {
    for uid in [i32::MIN, 0, i32::MAX] {
        for spring in [false, true] {
            let mut w = MmdCollisionWorld::new();
            let a = w.create_body(body(0, 0.0), 1).unwrap();
            let b = w.create_body(body(1, 0.25), 1).unwrap();
            let frame = Pose {
                position: Vec3::ZERO,
                rotation: Quat([0.0, 0.0, 0.0, 1.0]),
            };
            w.create_joint(
                JointDesc {
                    bodies: [a, b],
                    frames: [frame; 2],
                    linear_lower: Vec3::ZERO,
                    linear_upper: Vec3::ZERO,
                    angular_lower: Vec3::ZERO,
                    angular_upper: Vec3::ZERO,
                    spring_enabled: [spring; 6],
                    spring_stiffness: [if spring { 2.0 } else { 0.0 }; 6],
                    use_linear_reference_frame_a: false,
                    disable_collisions: true,
                },
                uid,
            )
            .unwrap();
            assert_eq!(w.objects().joint_data()[0].mmd_uid, Some(uid));
            assert!(!w.objects().joint_data()[0].disable_collisions);
            w.perform_discrete_collision_detection();
            assert!(w.manifolds().iter().any(|m| m.bodies == [1, 2]));
        }
    }
}

#[test]
fn mmd_world_rejects_foreign_handles_without_changing_ownership() {
    let mut w = MmdCollisionWorld::new();
    let mut foreign = MmdCollisionWorld::new();
    let a = foreign.create_body(body(0, 0.0), 1).unwrap();
    assert_eq!(w.update_single_aabb(a), Err(InvalidArgument));
    assert_eq!(w.set_motion_state(a, at(1.0)), Err(InvalidArgument));
    assert_eq!(w.reseat(a, at(1.0)), Err(InvalidArgument));
    assert_eq!(w.stop_at(a, Vec3::ZERO), Err(InvalidArgument));
    assert_eq!(w.set_kinematic(a, true), Err(InvalidArgument));
    let mut invalid = body(0, 0.0);
    invalid.shape_kind = 3;
    assert_eq!(w.create_body(invalid, 1), Err(InvalidArgument));
    assert_eq!(w.objects().bodies().len(), 1);
}
