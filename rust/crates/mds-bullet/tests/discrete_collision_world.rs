#![allow(dead_code)]
#[path = "../src/core/mod.rs"]
mod core;

use core::activation::ActivationState;
use core::dbvt::DbvtPolicy;
use core::discrete_collision_world::DiscreteCollisionWorld;
use core::math::{Quat, Vec3};
use core::world_objects::{BodyDesc, Pose};
use core::InvalidArgument;

fn world() -> DiscreteCollisionWorld {
    DiscreteCollisionWorld::public(DbvtPolicy::GenericReference)
}

fn sphere(x: f32) -> BodyDesc {
    BodyDesc {
        shape_kind: 0,
        shape_params: [0.5, 0.0, 0.0, 0.0],
        mass: 1.0,
        pose: Pose {
            position: Vec3([x, 0.0, 0.0]),
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
fn discrete_world_registration_is_raw_and_update_expands_both_sides() {
    let mut w = world();
    let body = w.create_body(sphere(0.0)).unwrap();
    w.create_body(sphere(0.25)).unwrap();
    let key = w.broadphase().pairs()[0].proxies[0];
    let before = w.broadphase().aabb(key);
    assert_eq!(before.min, Vec3([-0.5; 3]));
    assert_eq!(before.max, Vec3([0.5; 3]));
    w.update_single_aabb(body).unwrap();
    assert_eq!(w.broadphase().aabb(key).min, Vec3([-0.52; 3]));
    assert_eq!(w.broadphase().aabb(key).max, Vec3([0.52; 3]));
}

#[test]
fn discrete_world_huge_dynamic_keeps_proxy_and_requests_disable() {
    let mut w = world();
    let mut desc = sphere(0.0);
    desc.shape_params[0] = 1e6;
    let body = w.create_body(desc).unwrap();
    w.create_body(sphere(0.0)).unwrap();
    let key = w.broadphase().pairs()[0].proxies[0];
    let raw = w.broadphase().aabb(key);
    w.update_single_aabb(body).unwrap();
    assert_eq!(w.broadphase().aabb(key), raw);
    assert_eq!(
        w.objects().objects()[0].activation.state,
        ActivationState::DisableSimulation
    );
}

#[test]
fn discrete_world_default_updates_sleeping_static_objects() {
    let mut w = world();
    let mut desc = sphere(0.0);
    desc.mass = 0.0;
    w.create_body(desc).unwrap();
    w.create_body(sphere(0.25)).unwrap();
    let key = w.broadphase().pairs()[0].proxies[0];
    w.set_force_update_all_aabbs(false);
    w.update_aabbs();
    assert_eq!(w.broadphase().aabb(key).min, Vec3([-0.5; 3]));
    w.set_force_update_all_aabbs(true);
    w.update_aabbs();
    assert_eq!(w.broadphase().aabb(key).min, Vec3([-0.52; 3]));
}

#[test]
fn discrete_world_kinematic_public_transform_preserves_current_body() {
    let mut w = world();
    let mut desc = sphere(0.0);
    desc.kinematic = true;
    let body = w.create_body(desc).unwrap();
    let pose = sphere(8.0).pose;
    w.set_public_transform(body, pose).unwrap();
    w.update_single_aabb(body).unwrap();
    assert_eq!(w.public_transform(body).unwrap().origin, pose.position);
    assert_eq!(w.objects().bodies()[0].snapshot().world.origin, Vec3::ZERO);
}

#[test]
fn discrete_world_dispatcher_persists_and_stale_pairs_release() {
    let mut w = world();
    let a = w.create_body(sphere(0.0)).unwrap();
    w.create_body(sphere(0.25)).unwrap();
    w.perform_discrete_collision_detection();
    assert_eq!(w.manifolds().len(), 1);
    let key = w.manifolds()[0].owner();
    w.perform_discrete_collision_detection();
    assert_eq!(w.manifolds()[0].owner(), key);
    assert!(w.manifolds()[0].manifold.contacts()[0].lifetime > 0);
    w.set_public_transform(a, sphere(100.0).pose).unwrap();
    for _ in 0..4 {
        w.perform_discrete_collision_detection();
    }
    assert!(w.broadphase().pairs().is_empty());
    assert!(w.manifolds().is_empty());
}

#[test]
fn discrete_world_rejects_foreign_handles_and_invalid_registration() {
    let mut w = world();
    let mut foreign = world();
    let body = foreign.create_body(sphere(0.0)).unwrap();
    assert_eq!(w.update_single_aabb(body), Err(InvalidArgument));
    assert_eq!(
        w.set_public_transform(body, sphere(1.0).pose),
        Err(InvalidArgument)
    );
    let mut desc = sphere(0.0);
    desc.shape_params[0] = -1.0;
    assert_eq!(w.create_body(desc), Err(InvalidArgument));
    assert!(w.objects().bodies().is_empty());
    assert!(w.broadphase().pairs().is_empty());
}
