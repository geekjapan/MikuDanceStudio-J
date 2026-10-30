#![allow(dead_code, unused_imports)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;

use core::{
    activation::BodyActivation,
    contact::ContactBody,
    dbvt::{Aabb, DbvtPolicy},
    dbvt_broadphase::DbvtBroadphase,
    dispatcher::{CollisionDispatcher, DispatchObject},
    math::{Transform, Vec3},
    pair_cache::ProxyKey,
    shape::Shape,
};
use std::{
    collections::BTreeMap,
    fmt::Write,
    io::{self, BufRead},
};

fn aabb(words: &[&str]) -> Aabb {
    let values: Vec<_> = words
        .iter()
        .map(|s| f32::from_bits(s.parse().unwrap()))
        .collect();
    Aabb {
        min: Vec3(values[..3].try_into().unwrap()),
        max: Vec3(values[3..].try_into().unwrap()),
    }
}
fn bits(a: Aabb) -> Vec<u32> {
    a.min
        .0
        .into_iter()
        .chain(a.max.0)
        .map(f32::to_bits)
        .collect()
}
fn main() {
    let policy = match std::env::args().nth(1).as_deref() {
        Some("generic-reference") => DbvtPolicy::GenericReference,
        Some("mmd-win64-sse") => DbvtPolicy::MmdWin64Sse,
        _ => panic!("explicit policy required"),
    };
    let mut bp = DbvtBroadphase::new(policy);
    let mut dispatcher = CollisionDispatcher::new();
    let mut keys = [None; 512];
    let mut history = 0;
    let mut checkpoint = 0;
    let mut created = 0u32;
    let mut generations = BTreeMap::new();
    let mut releases = Vec::new();
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let words: Vec<_> = line.split_whitespace().collect();
        let op = words[0];
        if op == "B" {
            let mut fields = words[1..].iter();
            let mut ranks = [Vec::new(), Vec::new()];
            let mut frees = [None; 2];
            for i in 0..2 {
                let len: usize = fields.next().unwrap().parse().unwrap();
                for _ in 0..len {
                    let id: i64 = fields.next().unwrap().parse().unwrap();
                    let rank: usize = fields.next().unwrap().parse().unwrap();
                    let words: Vec<_> = fields.by_ref().take(6).copied().collect();
                    ranks[i].push((
                        if id < 0 { None } else { Some(id as usize) },
                        aabb(&words),
                        rank,
                    ));
                }
                let free = fields.next().unwrap();
                frees[i] = if *free == "-" {
                    None
                } else {
                    Some(free.parse().unwrap())
                };
            }
            assert!(fields.next().is_none());
            bp.bind_native_address_ranks([(&ranks[0], frees[0]), (&ranks[1], frees[1])]);
            continue;
        }
        let id: usize = words.get(1).map(|s| s.parse().unwrap()).unwrap_or(0);
        let mut release = |key: core::pair_cache::AlgorithmKey| {
            dispatcher.release(key);
            assert_eq!(dispatcher.manifolds().len() + 1, generations.len());
            releases.push(generations.remove(&key.0).expect("live generation"));
        };
        match op {
            "H" => {
                assert!(keys.iter().all(Option::is_none));
                bp = DbvtBroadphase::new(policy);
                dispatcher = CollisionDispatcher::new();
                generations.clear();
                releases.clear();
                created = 0;
                history = id;
            }
            "c" => {
                assert!(keys[id].is_none());
                keys[id] = Some(bp.create_proxy(
                    aabb(&words[4..]),
                    id,
                    words[2].parse().unwrap(),
                    words[3].parse().unwrap(),
                ));
            }
            "s" => bp.set_aabb(keys[id].unwrap(), aabb(&words[2..])),
            "d" => {
                bp.destroy_proxy(keys[id].take().unwrap(), &mut release);
            }
            "p" => bp.calculate_overlapping_pairs(&mut release),
            "r" => bp.reset_pool(),
            "v" => bp.set_velocity_prediction(f32::from_bits(words[1].parse().unwrap())),
            "n" => {
                let active = [BodyActivation::default(); 512];
                let objects: Vec<_> = (0..512)
                    .map(|i| DispatchObject {
                        shape: Shape::Sphere { radius: 1.0 },
                        contact: ContactBody {
                            world: Transform::IDENTITY,
                            friction: 0.5,
                            restitution: 0.0,
                        },
                        activation: &active[i],
                        constraints: &[],
                        processing_threshold: f32::MAX,
                    })
                    .collect();
                let owners: BTreeMap<_, _> = keys
                    .iter()
                    .enumerate()
                    .filter_map(|(i, k)| k.map(|k| (k.0, i)))
                    .collect();
                bp.for_each_algorithm(|pair, algorithm| {
                    let absent = algorithm.is_none();
                    dispatcher.near_pair(algorithm, pair.map(|k| owners[&k.0]), &objects);
                    if absent {
                        created += 1;
                        assert!(generations.insert(algorithm.unwrap().0, created).is_none());
                    }
                });
            }
            _ => panic!("unknown operation"),
        }
        let o = bp.observation();
        let owner = |key: ProxyKey| bp.owner(key);
        let mut out = format!("[{history},{checkpoint},\"{op}\",[{:?},{:?},{:?},{:?},{:?},{:?},{:?},{:?},{:?},{:?},{:?},1,0,10,1,0],",
            o.stage_current, o.fixed_left, o.new_pairs, o.updates_call, o.updates_done,
            o.updates_ratio.to_bits(), o.gid, o.pid, o.cid, u8::from(o.need_cleanup), bp.velocity_prediction().to_bits());
        out.push('[');
        for (i, root) in o.roots.into_iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            if let Some(root) = root {
                write!(out, "{:?}", bits(root)).unwrap();
            } else {
                out.push_str("null");
            }
        }
        write!(
            out,
            "],{:?},[",
            o.stages
                .map(|s| s.into_iter().map(owner).collect::<Vec<_>>())
        )
        .unwrap();
        let mut separator = "";
        for (id, key) in keys.iter().enumerate() {
            if let Some(key) = key {
                let state = bp.states()[key.0 as usize];
                let (_, stage, leaf) = o.leaves.iter().find(|(k, _, _)| k == key).unwrap();
                let mut proxy = vec![
                    id as i64,
                    state.uid as i64,
                    state.group as i64,
                    state.mask as i64,
                    *stage as i64,
                ];
                proxy.extend(bits(bp.aabb(*key)).into_iter().map(i64::from));
                proxy.extend(bits(*leaf).into_iter().map(i64::from));
                write!(out, "{separator}{proxy:?}").unwrap();
                separator = ",";
            }
        }
        let pairs: Vec<_> = bp
            .pairs()
            .iter()
            .map(|p| {
                [
                    owner(p.proxies[0]) as u32,
                    owner(p.proxies[1]) as u32,
                    p.algorithm.map(|k| generations[&k.0]).unwrap_or(0),
                ]
            })
            .collect();
        let manifolds: Vec<_> = dispatcher
            .manifolds()
            .iter()
            .map(|m| [m.bodies[0], m.bodies[1], m.manifold.contacts().len()])
            .collect();
        let tree_counters = o
            .tree_counters
            .map(|(leaves, lookahead, path)| [leaves as i64, lookahead as i64, path as i64]);
        write!(
            out,
            "],{pairs:?},{created},{releases:?},{manifolds:?},{tree_counters:?},null]"
        )
        .unwrap();
        println!("{out}");
        checkpoint += 1;
    }
}
