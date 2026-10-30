use crate::core::{
    activation::BodyActivation,
    contact::ContactBody,
    dbvt::{Aabb, DbvtPolicy},
    dbvt_broadphase::DbvtBroadphase,
    dispatcher::{CollisionDispatcher, DispatchObject},
    math::{Transform, Vec3},
    shape::Shape,
};

fn bounds(min: f32, max: f32) -> Aabb {
    Aabb {
        min: Vec3([min; 3]),
        max: Vec3([max; 3]),
    }
}

fn policies() -> [DbvtPolicy; 2] {
    [DbvtPolicy::GenericReference, DbvtPolicy::MmdWin64Sse]
}

#[test]
fn real_queries_create_filtered_pairs_and_count_duplicate_attempts() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        let a = bp.create_proxy(bounds(0.0, 1.0), 20, 1, 1);
        let b = bp.create_proxy(bounds(1.0, 2.0), 30, 1, 1);
        assert_eq!(bp.pairs().len(), 1);
        assert_eq!(bp.pairs()[0].proxies, [a, b]);
        let rejected = bp.create_proxy(bounds(0.5, 1.5), 40, 2, 2);
        assert_eq!(bp.pairs().len(), 1);
        assert_eq!(bp.observation().new_pairs, 4);
        assert_eq!(bp.owner(rejected), 40);
        bp.set_aabb(b, bounds(0.75, 2.0));
        assert_eq!(bp.pairs().len(), 1);
        assert_eq!(bp.observation().new_pairs, 6);
    }
}

#[test]
fn unchanged_and_contained_updates_refresh_stage_without_querying() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        let a = bp.create_proxy(bounds(0.0, 2.0), 0, 1, 1);
        let b = bp.create_proxy(bounds(0.0, 2.0), 1, 1, 1);
        bp.calculate_overlapping_pairs(|_| panic!("no algorithm"));
        bp.set_aabb(a, bounds(0.0, 2.0));
        bp.set_aabb(b, bounds(0.5, 1.5));
        assert_eq!(bp.observation().stages[1], [b, a]);
        assert_eq!(bp.observation().new_pairs, 1);
        assert_eq!(bp.observation().updates_call, 2);
        assert_eq!(bp.observation().updates_done, 0);
        assert_eq!(bp.aabb(b), bounds(0.5, 1.5));
        assert_eq!(bp.observation().leaves[1].2, bounds(0.0, 2.0));
        bp.calculate_overlapping_pairs(|_| {});
        assert!(bp.observation().stages[2].is_empty());
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.observation().stages[2], [a, b]);
        assert_eq!(bp.observation().leaves[1].2, bounds(0.5, 1.5));
        assert_eq!(
            (bp.observation().updates_call, bp.observation().updates_done),
            (0, 0)
        );
    }
}

#[test]
fn prediction_uses_old_requested_extent_signed_delta_and_margin_then_teleports_exactly() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        bp.set_velocity_prediction(2.0);
        let a = bp.create_proxy(bounds(0.0, 2.0), 0, 1, 1);
        let next = Aabb {
            min: Vec3([-0.25, 0.25, 0.0]),
            max: Vec3([1.75, 3.0, 2.0]),
        };
        bp.set_aabb(a, next);
        let expected = Aabb {
            min: Vec3([(-0.25f32 - 0.05) - 2.0, 0.25 - 0.05, -0.05]),
            max: Vec3([1.75 + 0.05, (3.0 + 0.05) + 2.0, (2.0 + 0.05) + 2.0]),
        };
        assert_eq!(bp.observation().leaves[0].2, expected);
        assert_eq!(bp.aabb(a), next);
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.observation().updates_ratio, 1.0);
        assert_eq!(bp.observation().updates_call, 0);
        bp.set_aabb(a, bounds(20.0, 21.0));
        assert_eq!(bp.observation().leaves[0].2, bounds(20.0, 21.0));
        assert_eq!(bp.bounds(), bounds(20.0, 21.0));
    }
}

#[test]
fn migration_rebuilds_exact_requested_leaf_and_fixed_reactivation_queries_both_sets() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        let a = bp.create_proxy(bounds(0.0, 1.0), 0, 1, 1);
        bp.set_aabb(a, bounds(0.25, 1.25));
        bp.calculate_overlapping_pairs(|_| {});
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.observation().stages[2], [a]);
        assert_eq!(bp.observation().leaves[0].2, bp.aabb(a));
        let b = bp.create_proxy(bounds(4.0, 5.0), 1, 1, 1);
        let c = bp.create_proxy(bounds(8.0, 9.0), 2, 1, 1);
        bp.calculate_overlapping_pairs(|_| {});
        bp.calculate_overlapping_pairs(|_| {});
        bp.set_aabb(c, bounds(4.0, 5.0));
        assert_eq!(bp.pairs().len(), 1);
        assert_eq!(bp.pairs()[0].proxies, [b, c]);
        assert_eq!(bp.observation().updates_call, 0);
        bp.set_aabb(a, bounds(4.0, 5.0));
        assert_eq!(bp.pairs().len(), 3);
        assert_eq!(bp.pairs()[1].proxies, [a, b]);
        assert_eq!(bp.pairs()[2].proxies, [a, c]);
    }
}

#[test]
fn stale_pairs_survive_until_cleanup_and_use_leaf_instead_of_requested_overlap() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        let a = bp.create_proxy(bounds(0.0, 1.0), 0, 1, 1);
        let b = bp.create_proxy(bounds(0.5, 1.5), 1, 1, 1);
        bp.set_aabb(a, bounds(0.75, 1.75));
        bp.set_aabb(b, bounds(0.5, 0.74));
        assert!(!policy.intersects(bp.aabb(a), bp.aabb(b)));
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.pairs().len(), 1);
        bp.set_aabb(a, bounds(100.0, 101.0));
        assert_eq!(bp.pairs().len(), 1);
        bp.calculate_overlapping_pairs(|_| {});
        assert!(bp.pairs().is_empty());
        assert_eq!(bp.observation().cid, 0);
    }
}

#[test]
fn live_reset_is_noop_and_empty_reset_preserves_prediction_but_restarts_uids() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        bp.set_velocity_prediction(3.0);
        assert_eq!(bp.bounds(), bounds(0.0, 0.0));
        let a = bp.create_proxy(bounds(2.0, 3.0), 0, 1, 1);
        bp.calculate_overlapping_pairs(|_| {});
        let before = bp.observation();
        bp.reset_pool();
        assert_eq!(bp.observation(), before);
        bp.destroy_proxy(a, |_| {});
        assert_eq!(bp.bounds(), bounds(0.0, 0.0));
        let b = bp.create_proxy(bounds(0.0, 1.0), 1, 1, 1);
        assert_eq!(a, b);
        assert_eq!(bp.states()[b.0 as usize].uid, 2);
        bp.destroy_proxy(b, |_| {});
        bp.reset_pool();
        assert_eq!(bp.velocity_prediction(), 3.0);
        assert_eq!(
            (
                bp.observation().gid,
                bp.observation().pid,
                bp.observation().cid
            ),
            (0, 0, 0)
        );
        let c = bp.create_proxy(bounds(0.0, 1.0), 2, 1, 1);
        assert_eq!(bp.states()[c.0 as usize].uid, 1);
    }
}

#[test]
fn fixed_optimization_crosses_the_one_percent_hundred_leaf_boundary() {
    for (leaves, passes) in [(99, 1), (100, 2), (101, 2), (200, 3)] {
        let mut bp = DbvtBroadphase::new(DbvtPolicy::GenericReference);
        for i in 0..leaves {
            bp.create_proxy(bounds(i as f32 * 3.0, i as f32 * 3.0 + 1.0), i, 1, 1);
        }
        bp.calculate_overlapping_pairs(|_| {});
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.observation().fixed_left, leaves);
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.observation().fixed_left, leaves - passes);
        assert_eq!(
            bp.observation().tree_counters,
            [(0, -1, 2), (leaves, -1, passes as u32)]
        );
        assert_eq!(bp.observation().stages[2].len(), leaves);
        assert!(bp.pairs().is_empty());
    }
}

#[test]
fn actual_dispatcher_manifolds_release_synchronously_before_key_reuse() {
    for cleanup in [false, true] {
        let mut bp = DbvtBroadphase::new(DbvtPolicy::MmdWin64Sse);
        let mut dispatcher = CollisionDispatcher::new();
        let active = [BodyActivation::default(), BodyActivation::default()];
        let shape = Shape::Sphere { radius: 1.0 };
        let objects: [_; 2] = std::array::from_fn(|i| DispatchObject {
            shape,
            contact: ContactBody {
                world: Transform::IDENTITY,
                friction: 0.5,
                restitution: 0.0,
            },
            activation: &active[i],
            constraints: &[],
            processing_threshold: f32::MAX,
        });
        let a = bp.create_proxy(bounds(-1.0, 1.0), 0, 1, 1);
        let b = bp.create_proxy(bounds(-1.0, 1.0), 1, 1, 1);
        bp.for_each_algorithm(|[a, b], algorithm| {
            dispatcher.near_pair(algorithm, [a.0 as usize, b.0 as usize], &objects);
        });
        assert_eq!(dispatcher.manifolds().len(), 1);
        assert!(!dispatcher.manifolds()[0].manifold.contacts().is_empty());
        let mut releases = 0;
        let mut release = |key| {
            dispatcher.release(key);
            assert!(dispatcher.manifolds().is_empty());
            releases += 1;
        };
        if cleanup {
            bp.set_aabb(b, bounds(10.0, 11.0));
            bp.calculate_overlapping_pairs(&mut release);
            bp.destroy_proxy(b, &mut release);
        } else {
            bp.destroy_proxy(b, &mut release);
        }
        bp.destroy_proxy(a, &mut release);
        assert_eq!(releases, 1);
        assert_eq!(bp.create_proxy(bounds(0.0, 1.0), 3, 1, 1), a);
        assert!(bp.pairs().is_empty());
    }
}

#[test]
fn cleanup_budget_revisits_swapped_slot_and_stops_after_the_native_removal_budget() {
    for policy in policies() {
        let mut bp = DbvtBroadphase::new(policy);
        let keys: Vec<_> = (0..6)
            .map(|i| bp.create_proxy(bounds(0.0, 1.0), i, 1, 1))
            .collect();
        assert_eq!(bp.pairs().len(), 15);
        bp.calculate_overlapping_pairs(|_| {});
        bp.calculate_overlapping_pairs(|_| {});
        let before = bp.pairs().to_vec();
        for (i, key) in keys.into_iter().enumerate() {
            bp.set_aabb(key, bounds(100.0 + i as f32 * 3.0, 101.0 + i as f32 * 3.0));
        }
        bp.create_proxy(bounds(0.0, 200.0), 6, 2, 2);
        assert_eq!(bp.observation().new_pairs, 7);
        bp.calculate_overlapping_pairs(|_| {});
        assert_eq!(bp.pairs().len(), 8);
        assert_eq!(bp.pairs()[0], before[0]);
        assert_eq!(bp.pairs()[1], before[8]);
        assert_eq!(&bp.pairs()[2..], &before[2..8]);
        assert_eq!(bp.observation().cid, 1);
        assert!(!bp.observation().need_cleanup);
    }
}

#[test]
fn fresh_nodes_can_create_and_query_before_binding_their_next_checkpoint_ranks() {
    let mut bp = DbvtBroadphase::new(DbvtPolicy::GenericReference);
    bp.bind_native_address_ranks([(&[], None), (&[], None)]);
    let a = bp.create_proxy(bounds(0.0, 1.0), 0, 1, 1);
    bp.create_proxy(bounds(0.0, 1.0), 1, 1, 1);
    bp.set_aabb(a, bounds(0.1, 1.1));
    assert_eq!(bp.pairs().len(), 1);
    let malformed = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        bp.bind_native_address_ranks([(&[], None), (&[], None)]);
    }));
    assert!(malformed.is_err());
}

#[test]
fn malformed_native_topology_bits_ranks_and_cached_free_are_rejected() {
    use crate::core::pair_cache::ProxyKey;
    let mut bp = DbvtBroadphase::new(DbvtPolicy::GenericReference);
    bp.create_proxy(bounds(0.0, 1.0), 0, 1, 1);
    for nodes in [
        vec![(Some(999), bounds(0.0, 1.0), 1)],
        vec![(Some(0), bounds(0.0, 2.0), 1)],
        vec![(Some(0), bounds(0.0, 1.0), 0)],
    ] {
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            bp.bind_native_address_ranks([(&nodes, None), (&[], None)]);
        }))
        .is_err());
    }
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        bp.bind_native_address_ranks([(&[(Some(0), bounds(0.0, 1.0), 1)], Some(2)), (&[], None)]);
    }))
    .is_err());
    assert_eq!(bp.aabb(ProxyKey(0)), bounds(0.0, 1.0));
}
