//! Altered Rust translation of Bullet 2.75 btDbvtBroadphase's default hashed-cache lifecycle.
//! See mod.rs for the retained Bullet zlib notice. Queries use an explicit immutable policy.

use super::dbvt::{Aabb, Dbvt, DbvtPolicy};
use super::math::Vec3;
use super::pair_cache::{AlgorithmKey, HashedPairCache, Pair, ProxyKey, ProxyState};

const FIXED: usize = 2;

#[derive(Debug)]
struct Proxy {
    requested: Aabb,
    owner: usize,
    stage: usize,
    links: [Option<ProxyKey>; 2],
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct Counters {
    stage_current: usize,
    fixed_left: usize,
    new_pairs: usize,
    updates_call: u32,
    updates_done: u32,
    updates_ratio: f32,
    gid: i32,
    pid: i32,
    cid: usize,
    need_cleanup: bool,
}

impl Default for Counters {
    fn default() -> Self {
        Self {
            stage_current: 0,
            fixed_left: 0,
            new_pairs: 1,
            updates_call: 0,
            updates_done: 0,
            updates_ratio: 0.0,
            gid: 0,
            pid: 0,
            cid: 0,
            need_cleanup: true,
        }
    }
}

/// Internal inputs require finite ordered AABBs and live keys, as for AxisSweep32.
/// Slots can be reused only after synchronous cache cleanup. UIDs increase until an empty reset.
#[derive(Debug)]
pub struct DbvtBroadphase {
    policy: DbvtPolicy,
    sets: [Dbvt; 2],
    proxies: Vec<Option<Box<Proxy>>>,
    states: Vec<ProxyState>,
    freed: Vec<ProxyKey>,
    stage_roots: [Option<ProxyKey>; 3],
    cache: HashedPairCache,
    prediction: f32,
    counters: Counters,
}

impl DbvtBroadphase {
    pub fn new(policy: DbvtPolicy) -> Self {
        Self {
            policy,
            sets: std::array::from_fn(|_| Dbvt::new(policy)),
            proxies: Vec::new(),
            states: Vec::new(),
            freed: Vec::new(),
            stage_roots: [None; 3],
            cache: HashedPairCache::new(),
            prediction: 0.0,
            counters: Counters::default(),
        }
    }

    fn proxy(&self, key: ProxyKey) -> &Proxy {
        self.proxies[key.0 as usize]
            .as_deref()
            .expect("proxy must be live")
    }

    fn proxy_mut(&mut self, key: ProxyKey) -> &mut Proxy {
        self.proxies[key.0 as usize]
            .as_deref_mut()
            .expect("proxy must be live")
    }

    fn list_append(&mut self, key: ProxyKey, stage: usize) {
        let root = self.stage_roots[stage];
        self.proxy_mut(key).links = [None, root];
        if let Some(root) = root {
            self.proxy_mut(root).links[0] = Some(key);
        }
        self.stage_roots[stage] = Some(key);
    }

    fn list_remove(&mut self, key: ProxyKey) {
        let proxy = self.proxy(key);
        let stage = proxy.stage;
        let [prev, next] = proxy.links;
        if let Some(prev) = prev {
            self.proxy_mut(prev).links[1] = next;
        } else {
            self.stage_roots[stage] = next;
        }
        if let Some(next) = next {
            self.proxy_mut(next).links[0] = prev;
        }
    }

    pub fn create_proxy(
        &mut self,
        requested: Aabb,
        owner: usize,
        group: i16,
        mask: i16,
    ) -> ProxyKey {
        self.counters.gid += 1;
        let key = self.freed.pop().unwrap_or(ProxyKey(
            u32::try_from(self.proxies.len()).expect("proxy slot exceeds u32"),
        ));
        let proxy = Some(Box::new(Proxy {
            requested,
            owner,
            stage: self.counters.stage_current,
            links: [None; 2],
        }));
        let state = ProxyState {
            uid: self.counters.gid,
            group,
            mask,
        };
        if key.0 as usize == self.proxies.len() {
            self.proxies.push(proxy);
            self.states.push(state);
        } else {
            self.proxies[key.0 as usize] = proxy;
            self.states[key.0 as usize] = state;
        }
        self.sets[0].insert(key, requested);
        self.list_append(key, self.counters.stage_current);
        let Self {
            sets,
            states,
            cache,
            counters,
            ..
        } = self;
        for tree in sets {
            tree.collide_volume(requested, |other| {
                add_pair(cache, states, counters, other, key)
            });
        }
        key
    }

    pub fn set_aabb(&mut self, key: ProxyKey, requested: Aabb) {
        let old = self.proxy(key).requested;
        let mut collide = false;
        if self.proxy(key).stage == FIXED {
            self.sets[1].remove(key);
            self.sets[0].insert(key, requested);
            collide = true;
        } else {
            self.counters.updates_call += 1;
            if self.policy.intersects(self.sets[0].volume(key), requested) {
                let delta = requested.min.sub(old.min);
                let mut velocity = old.max.sub(old.min).scale(0.5).scale(self.prediction);
                for i in 0..3 {
                    if delta.0[i] < 0.0 {
                        velocity.0[i] = -velocity.0[i];
                    }
                }
                let mut volume = requested;
                if self.sets[0].update_predicted(key, &mut volume, Some(velocity), Some(0.05)) {
                    self.counters.updates_done += 1;
                    collide = true;
                }
            } else {
                self.sets[0].update(key, requested);
                self.counters.updates_done += 1;
                collide = true;
            }
        }
        self.list_remove(key);
        let stage = self.counters.stage_current;
        let proxy = self.proxy_mut(key);
        proxy.requested = requested;
        proxy.stage = stage;
        self.list_append(key, stage);
        if collide {
            self.counters.need_cleanup = true;
            let Self {
                sets,
                states,
                cache,
                counters,
                ..
            } = self;
            sets[1].collide_leaf(&sets[0], key, |a, b| {
                add_pair(cache, states, counters, a, b)
            });
            sets[0].collide_leaf(&sets[0], key, |a, b| {
                add_pair(cache, states, counters, a, b)
            });
        }
    }

    pub fn calculate_overlapping_pairs(&mut self, mut release: impl FnMut(AlgorithmKey)) {
        self.sets[0].optimize_incremental(1);
        if self.counters.fixed_left > 0 {
            let count = 1 + self.sets[1].leaf_count() / 100;
            self.sets[1].optimize_incremental(count as i32);
            self.counters.fixed_left = self.counters.fixed_left.saturating_sub(count);
        }
        self.counters.stage_current = (self.counters.stage_current + 1) % FIXED;
        let mut current = self.stage_roots[self.counters.stage_current];
        if current.is_some() {
            while let Some(key) = current {
                let next = self.proxy(key).links[1];
                self.list_remove(key);
                self.list_append(key, FIXED);
                self.sets[0].remove(key);
                self.sets[1].insert(key, self.proxy(key).requested);
                self.proxy_mut(key).stage = FIXED;
                current = next;
            }
            self.counters.fixed_left = self.sets[1].leaf_count();
            self.counters.need_cleanup = true;
        }
        if self.counters.need_cleanup && !self.cache.pairs().is_empty() {
            let mut count = self.cache.pairs().len().min(
                self.counters
                    .new_pairs
                    .max(self.cache.pairs().len() * 10 / 100),
            );
            let mut i = 0;
            while i < count {
                let index = (self.counters.cid + i) % self.cache.pairs().len();
                let [a, b] = self.cache.pairs()[index].proxies;
                let volume =
                    |key| self.sets[usize::from(self.proxy(key).stage == FIXED)].volume(key);
                if !self.policy.intersects(volume(a), volume(b)) {
                    self.cache.remove(a, b, &self.states, &mut release);
                    count -= 1;
                } else {
                    i += 1;
                }
            }
            self.counters.cid = if self.cache.pairs().is_empty() {
                0
            } else {
                (self.counters.cid + count) % self.cache.pairs().len()
            };
        }
        self.counters.pid += 1;
        self.counters.new_pairs = 1;
        self.counters.need_cleanup = false;
        self.counters.updates_ratio = if self.counters.updates_call > 0 {
            self.counters.updates_done as f32 / self.counters.updates_call as f32
        } else {
            0.0
        };
        self.counters.updates_done /= 2;
        self.counters.updates_call /= 2;
    }

    pub fn destroy_proxy(&mut self, key: ProxyKey, release: impl FnMut(AlgorithmKey)) {
        let set = usize::from(self.proxy(key).stage == FIXED);
        self.sets[set].remove(key);
        self.list_remove(key);
        self.cache.remove_proxy(key, &self.states, release);
        self.proxies[key.0 as usize] = None;
        self.freed.push(key);
        self.counters.need_cleanup = true;
    }

    pub fn aabb(&self, key: ProxyKey) -> Aabb {
        self.proxy(key).requested
    }

    pub fn owner(&self, key: ProxyKey) -> usize {
        self.proxy(key).owner
    }

    pub fn bounds(&self) -> Aabb {
        match (self.sets[0].bounds(), self.sets[1].bounds()) {
            (Some(a), Some(b)) => a.merge(b),
            (Some(a), None) | (None, Some(a)) => a,
            (None, None) => Aabb {
                min: Vec3::ZERO,
                max: Vec3::ZERO,
            },
        }
    }

    pub fn reset_pool(&mut self) {
        if self.sets.iter().all(|tree| tree.leaf_count() == 0) {
            for tree in &mut self.sets {
                tree.clear();
            }
            self.counters = Counters::default();
            self.stage_roots = [None; 3];
        }
    }

    pub fn set_velocity_prediction(&mut self, prediction: f32) {
        self.prediction = prediction;
    }

    pub fn velocity_prediction(&self) -> f32 {
        self.prediction
    }

    pub fn pairs(&self) -> &[Pair] {
        self.cache.pairs()
    }

    pub fn states(&self) -> &[ProxyState] {
        &self.states
    }

    pub fn for_each_algorithm(
        &mut self,
        visit: impl FnMut([ProxyKey; 2], &mut Option<AlgorithmKey>),
    ) {
        self.cache.for_each_algorithm(visit);
    }
}

fn add_pair(
    cache: &mut HashedPairCache,
    states: &[ProxyState],
    counters: &mut Counters,
    a: ProxyKey,
    b: ProxyKey,
) {
    if a != b {
        cache.add(a, b, states);
        counters.new_pairs += 1;
    }
}

#[cfg(test)]
#[derive(Clone, Debug, PartialEq)]
pub struct Observation {
    pub stage_current: usize,
    pub fixed_left: usize,
    pub new_pairs: usize,
    pub updates_call: u32,
    pub updates_done: u32,
    pub updates_ratio: f32,
    pub gid: i32,
    pub pid: i32,
    pub cid: usize,
    pub need_cleanup: bool,
    pub stages: [Vec<ProxyKey>; 3],
    pub roots: [Option<Aabb>; 2],
    pub tree_counters: [(usize, i32, u32); 2],
    pub leaves: Vec<(ProxyKey, usize, Aabb)>,
}

#[cfg(test)]
impl DbvtBroadphase {
    pub fn observation(&self) -> Observation {
        let c = self.counters;
        Observation {
            stage_current: c.stage_current,
            fixed_left: c.fixed_left,
            new_pairs: c.new_pairs,
            updates_call: c.updates_call,
            updates_done: c.updates_done,
            updates_ratio: c.updates_ratio,
            gid: c.gid,
            pid: c.pid,
            cid: c.cid,
            need_cleanup: c.need_cleanup,
            stages: self.stage_roots.map(|mut root| {
                let mut keys = Vec::new();
                while let Some(key) = root {
                    keys.push(key);
                    root = self.proxy(key).links[1];
                }
                keys
            }),
            roots: self.sets.each_ref().map(Dbvt::bounds),
            tree_counters: self.sets.each_ref().map(Dbvt::test_counters),
            leaves: self
                .proxies
                .iter()
                .enumerate()
                .filter_map(|(i, proxy)| {
                    proxy.as_ref().map(|proxy| {
                        let key = ProxyKey(i as u32);
                        (
                            key,
                            proxy.stage,
                            self.sets[usize::from(proxy.stage == FIXED)].volume(key),
                        )
                    })
                })
                .collect(),
        }
    }
}

#[cfg(test)]
impl DbvtBroadphase {
    pub(crate) fn bind_native_address_ranks(
        &mut self,
        ranks: [(&[(Option<usize>, Aabb, usize)], Option<usize>); 2],
    ) {
        let mapped = ranks.map(|(nodes, free)| {
            let nodes: Vec<_> = nodes
                .iter()
                .map(|&(owner, volume, rank)| {
                    let key = owner.map(|owner| {
                        let i = self
                            .proxies
                            .iter()
                            .position(|p| p.as_ref().is_some_and(|p| p.owner == owner))
                            .expect("native owner is live");
                        ProxyKey(i as u32)
                    });
                    (key, volume, rank)
                })
                .collect();
            (nodes, free)
        });
        for (tree, (nodes, free)) in self.sets.iter_mut().zip(mapped) {
            tree.bind_native_address_ranks(&nodes, free);
        }
    }
}
