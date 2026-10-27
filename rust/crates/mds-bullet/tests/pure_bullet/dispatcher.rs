use super::*;
use crate::core::activation::ActivationState;
use crate::core::math::{Transform, Vec3};
use crate::core::pair_cache::{HashedPairCache, ProxyKey, ProxyState};

fn object<'a>(
    shape: Shape,
    activation: &'a BodyActivation,
    constraints: &'a [IslandConstraint],
) -> DispatchObject<'a> {
    DispatchObject {
        shape,
        contact: ContactBody {
            world: Transform::IDENTITY,
            friction: 0.5,
            restitution: 0.0,
        },
        activation,
        constraints,
        processing_threshold: 1e18,
    }
}

#[test]
fn cached_contacts_skip_inactive_and_body0_exclusion_without_refresh() {
    let active = BodyActivation::default();
    let sleeping = BodyActivation {
        state: ActivationState::IslandSleeping,
        ..active
    };
    let exclusions = [IslandConstraint { bodies: [0, 1] }];
    let sphere = Shape::Sphere { radius: 1.0 };
    let mut objects = [
        object(sphere, &active, &[]),
        object(sphere, &active, &exclusions),
    ];
    let mut dispatcher = CollisionDispatcher::new();
    let mut key = None;
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    let original = key;
    dispatcher.manifolds_mut()[0].manifold.contacts_mut()[0].applied_impulse = 3.0;
    let before = dispatcher.manifolds()[0].manifold.contacts()[0];
    objects[0].activation = &sleeping;
    objects[1].activation = &sleeping;
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert_eq!(dispatcher.manifolds()[0].manifold.contacts()[0], before);
    objects[0].activation = &active;
    objects[0].constraints = &exclusions;
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert_eq!(dispatcher.manifolds()[0].manifold.contacts()[0], before);
    objects[0].constraints = &[];
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    let after = dispatcher.manifolds()[0].manifold.contacts()[0];
    assert_eq!(key, original);
    assert_eq!(after.applied_impulse, 3.0);
    assert_eq!(after.lifetime, before.lifetime + 1);
}

#[test]
fn reversed_plane_constructor_can_cache_an_algorithm_without_a_manifold() {
    let active = BodyActivation::default();
    let exclusions = [IslandConstraint { bodies: [0, 1] }];
    let mut objects = [
        object(
            Shape::StaticPlane {
                normal: Vec3([0.0, 1.0, 0.0]),
                constant: 0.0,
            },
            &active,
            &[],
        ),
        object(Shape::Sphere { radius: 1.0 }, &active, &exclusions),
    ];
    let mut dispatcher = CollisionDispatcher::new();
    let mut key = None;
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert!(key.is_some());
    assert!(dispatcher.manifolds().is_empty());
    objects[1].constraints = &[];
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert!(dispatcher.manifolds().is_empty());
    dispatcher.release(key.take().unwrap());
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert_eq!(dispatcher.manifolds()[0].bodies, [1, 0]);
    assert_eq!(dispatcher.manifolds()[0].island_view().bodies, [1, 0]);
}

#[test]
fn dense_registry_swap_updates_owner_and_keeps_empty_manifolds() {
    let active = BodyActivation::default();
    let mut objects = (0..4)
        .map(|_| object(Shape::Sphere { radius: 1.0 }, &active, &[]))
        .collect::<Vec<_>>();
    for (i, object) in objects.iter_mut().enumerate() {
        object.contact.world.origin = Vec3([i as f32 * 10.0, 0.0, 0.0]);
        object.processing_threshold = (4 - i) as f32;
    }
    let mut dispatcher = CollisionDispatcher::new();
    let mut keys = [None; 3];
    for (i, key) in keys.iter_mut().enumerate() {
        dispatcher.near_pair(key, [0, i + 1], &objects);
    }
    assert_eq!(dispatcher.manifolds().len(), 3);
    assert!(dispatcher
        .manifolds()
        .iter()
        .all(|m| m.manifold.contacts().is_empty()));
    assert_eq!(dispatcher.manifolds()[2].processing_threshold, 1.0);
    dispatcher.release(keys[1].take().unwrap());
    assert_eq!(dispatcher.manifolds()[1].owner(), keys[2].unwrap());
    dispatcher.release(keys[2].take().unwrap());
    assert_eq!(dispatcher.manifolds().len(), 1);
    dispatcher.near_pair(&mut keys[1], [0, 2], &objects);
    assert_eq!(dispatcher.manifolds()[1].owner(), keys[1].unwrap());
}

#[test]
fn cache_visitor_retains_pair_order_and_clean_releases_exactly_once() {
    let states = (0..4)
        .map(|uid| ProxyState {
            uid,
            group: 1,
            mask: -1,
        })
        .collect::<Vec<_>>();
    let mut cache = HashedPairCache::new();
    let active = BodyActivation::default();
    let objects = (0..4)
        .map(|_| object(Shape::Sphere { radius: 1.0 }, &active, &[]))
        .collect::<Vec<_>>();
    let mut dispatcher = CollisionDispatcher::new();
    for b in 1..4 {
        cache.add(ProxyKey(0), ProxyKey(b), &states);
    }
    cache.for_each_algorithm(|pair, key| {
        dispatcher.near_pair(key, pair.map(|p| p.0 as usize), &objects)
    });
    let mut released = Vec::new();
    cache.clean_proxy(ProxyKey(2), |key| {
        released.push(key);
        dispatcher.release(key);
    });
    cache.clean_proxy(ProxyKey(2), |key| {
        released.push(key);
        dispatcher.release(key);
    });
    assert_eq!(released.len(), 1);
    assert_eq!(cache.pairs().len(), 3);
    cache.remove_proxy(ProxyKey(2), &states, |key| {
        released.push(key);
        dispatcher.release(key);
    });
    assert_eq!(released.len(), 1);
    assert_eq!(cache.pairs()[1].proxies, [ProxyKey(0), ProxyKey(3)]);
    assert_eq!(dispatcher.manifolds()[1].bodies, [0, 3]);
}

#[test]
fn contact_view_borrows_the_owned_warmstart_storage() {
    let active = BodyActivation::default();
    let objects = [
        object(Shape::Sphere { radius: 1.0 }, &active, &[]),
        object(Shape::Sphere { radius: 1.0 }, &active, &[]),
    ];
    let mut dispatcher = CollisionDispatcher::new();
    dispatcher.near_pair(&mut None, [0, 1], &objects);
    let original = dispatcher.manifolds()[0].manifold.contacts().as_ptr();
    let view = dispatcher.manifolds_mut()[0].contact_view();
    assert_eq!(original, view.points.as_ptr());
    view.points[0].applied_impulse = 7.0;
    assert_eq!(
        dispatcher.manifolds()[0].manifold.contacts()[0].applied_impulse,
        7.0
    );
}

#[test]
fn processing_threshold_uses_manifold_order_and_allocation_time() {
    let active = BodyActivation::default();
    let mut objects = [
        object(
            Shape::StaticPlane {
                normal: Vec3([0.0, 1.0, 0.0]),
                constant: 0.0,
            },
            &active,
            &[],
        ),
        object(Shape::Sphere { radius: 1.0 }, &active, &[]),
    ];
    objects[0].processing_threshold = -0.0;
    objects[1].processing_threshold = 0.0;
    let mut dispatcher = CollisionDispatcher::new();
    let mut key = None;
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert_eq!(
        dispatcher.manifolds()[0].processing_threshold.to_bits(),
        (-0.0_f32).to_bits()
    );
    objects[0].processing_threshold = 2.0;
    objects[1].processing_threshold = 3.0;
    dispatcher.near_pair(&mut key, [0, 1], &objects);
    assert_eq!(
        dispatcher.manifolds()[0].processing_threshold.to_bits(),
        (-0.0_f32).to_bits()
    );
}

#[test]
fn axis_sweep_dispatch_uses_external_owner_mapping_and_clean_before_remove() {
    use crate::core::axis_sweep::AxisSweep32;
    let active = BodyActivation::default();
    let objects = [
        object(Shape::Sphere { radius: 1.0 }, &active, &[]),
        object(Shape::Sphere { radius: 1.0 }, &active, &[]),
    ];
    let mut sweep = AxisSweep32::for_test(Vec3([-10.0; 3]), Vec3([10.0; 3]), 8);
    let a = sweep.add(Vec3([-1.0; 3]), Vec3([1.0; 3]), 1, 1, -1, 0);
    let b = sweep.add(Vec3([-1.0; 3]), Vec3([1.0; 3]), 0, 1, -1, 0);
    let mut owners = [0; 3];
    owners[a.0 as usize] = sweep.handle(a).unwrap().owner;
    owners[b.0 as usize] = sweep.handle(b).unwrap().owner;
    let mut dispatcher = CollisionDispatcher::new();
    sweep.for_each_algorithm(|proxies, key| {
        dispatcher.near_pair(key, proxies.map(|p| owners[p.0 as usize]), &objects);
    });
    assert_eq!(dispatcher.manifolds()[0].bodies, [1, 0]);
    let mut released = 0;
    sweep.clean_pair(0, |key| {
        released += 1;
        dispatcher.release(key);
    });
    sweep.remove(a, |key| {
        released += 1;
        dispatcher.release(key);
    });
    assert_eq!(released, 1);
    assert!(dispatcher.manifolds().is_empty());
}
