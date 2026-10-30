//! Altered Rust translation of the locally modified Bullet 2.75 32-bit SAP.
//! Pair maintenance only. DBVT ray acceleration, queries and World are not ported.
//Bullet Continuous Collision Detection and Physics Library
//Copyright (c) 2003-2006 Erwin Coumans  http://continuousphysics.com/Bullet/

//
// btAxisSweep3.h
//
// Copyright (c) 2006 Simon Hobbs
//
// This software is provided 'as-is', without any express or implied warranty. In no event will the authors be held liable for any damages arising from the use of this software.
//
// Permission is granted to anyone to use this software for any purpose, including commercial applications, and to alter it and redistribute it freely, subject to the following restrictions:
//
// 1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
//
// 2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
//
// 3. This notice may not be removed or altered from any source distribution.

use super::math::Vec3;
use super::pair_cache::{AlgorithmKey, HashedPairCache, Pair, ProxyKey, ProxyState};

const SENTINEL: u32 = 0x7fff_ffff;
const MASK: u32 = 0xffff_fffe;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Edge {
    pub pos: u32,
    pub handle: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Handle {
    pub min_edges: [u32; 3],
    pub max_edges: [u32; 3],
    pub owner: usize,
    pub multi_sap_parent: usize,
}

/// Inputs are internal: finite ordered AABBs, live keys and available capacity.
/// Handle zero is reserved. UIDs are handle indices, including after LIFO reuse.
#[derive(Debug)]
pub struct AxisSweep32 {
    world_min: Vec3,
    quantize: Vec3,
    capacity: u32,
    handles: Vec<Handle>,
    states: Vec<ProxyState>,
    live: Vec<bool>,
    edges: [Vec<Edge>; 3],
    freed: Vec<u32>,
    next_unused: u32,
    active: u32,
    cache: HashedPairCache,
}

impl AxisSweep32 {
    pub fn new_mmd() -> Self {
        Self::with_bounds(Vec3([-10000.0; 3]), Vec3([10000.0; 3]), 1_500_000)
    }

    fn with_bounds(min: Vec3, max: Vec3, capacity: u32) -> Self {
        assert!(capacity > 1 && capacity < SENTINEL);
        let size = max.sub(min);
        Self {
            world_min: min,
            quantize: Vec3(size.0.map(|v| SENTINEL as f32 / v)),
            capacity,
            handles: vec![Handle {
                min_edges: [0; 3],
                max_edges: [1; 3],
                owner: 0,
                multi_sap_parent: 0,
            }],
            states: vec![ProxyState {
                uid: 0,
                group: 0,
                mask: 0,
            }],
            live: vec![false],
            edges: std::array::from_fn(|_| {
                vec![
                    Edge { pos: 0, handle: 0 },
                    Edge {
                        pos: SENTINEL,
                        handle: 0,
                    },
                ]
            }),
            freed: Vec::new(),
            next_unused: 1,
            active: 0,
            cache: HashedPairCache::new(),
        }
    }

    #[cfg(test)]
    pub fn for_test(min: Vec3, max: Vec3, capacity: u32) -> Self {
        Self::with_bounds(min, max, capacity)
    }

    pub fn capacity(&self) -> u32 {
        self.capacity
    }
    pub fn len(&self) -> u32 {
        self.active
    }
    pub fn is_empty(&self) -> bool {
        self.active == 0
    }
    pub fn pairs(&self) -> &[Pair] {
        self.cache.pairs()
    }
    pub fn cache(&self) -> &HashedPairCache {
        &self.cache
    }
    pub fn for_each_algorithm(
        &mut self,
        visit: impl FnMut([ProxyKey; 2], &mut Option<AlgorithmKey>),
    ) {
        self.cache.for_each_algorithm(visit);
    }
    pub fn states(&self) -> &[ProxyState] {
        &self.states
    }
    pub fn handle(&self, key: ProxyKey) -> Option<&Handle> {
        self.live
            .get(key.0 as usize)
            .copied()
            .unwrap_or(false)
            .then(|| &self.handles[key.0 as usize])
    }
    pub fn set_pair_algorithm(&mut self, index: usize, algorithm: AlgorithmKey) {
        self.cache.set_algorithm(index, algorithm);
    }
    pub fn set_pair_internal_info(&mut self, index: usize, value: usize) {
        self.cache.set_internal_info(index, value);
    }
    pub fn clean_pair(&mut self, index: usize, release: impl FnMut(AlgorithmKey)) {
        self.cache.clean(index, release);
    }

    fn quantize(&self, point: Vec3, is_max: u32) -> [u32; 3] {
        std::array::from_fn(|i| {
            let v = (point.0[i] - self.world_min.0[i]) * self.quantize.0[i];
            if v <= 0.0 {
                is_max
            } else if v >= SENTINEL as f32 {
                (SENTINEL & MASK) | is_max
            } else {
                ((v as u32) & MASK) | is_max
            }
        })
    }

    pub fn add(
        &mut self,
        min: Vec3,
        max: Vec3,
        owner: usize,
        group: i16,
        mask: i16,
        multi_sap_parent: usize,
    ) -> ProxyKey {
        assert!(self.active < self.capacity);
        let lo = self.quantize(min, 0);
        let hi = self.quantize(max, 1);
        let id = self.freed.pop().unwrap_or_else(|| {
            let id = self.next_unused;
            self.next_unused += 1;
            id
        });
        self.active += 1;
        let limit = self.active * 2;
        let handle = Handle {
            min_edges: [limit - 1; 3],
            max_edges: [limit; 3],
            owner,
            multi_sap_parent,
        };
        let state = ProxyState {
            uid: id as i32,
            group,
            mask,
        };
        if id as usize == self.handles.len() {
            self.handles.push(handle);
            self.states.push(state);
            self.live.push(true);
        } else {
            self.handles[id as usize] = handle;
            self.states[id as usize] = state;
            self.live[id as usize] = true;
        }
        for axis in 0..3 {
            self.handles[0].max_edges[axis] += 2;
            self.edges[axis].pop();
            self.edges[axis].extend([
                Edge {
                    pos: lo[axis],
                    handle: id,
                },
                Edge {
                    pos: hi[axis],
                    handle: id,
                },
                Edge {
                    pos: SENTINEL,
                    handle: 0,
                },
            ]);
        }
        for axis in 0..3 {
            self.sort(
                axis,
                self.handles[id as usize].min_edges[axis],
                false,
                false,
                axis == 2,
                &mut |_| {},
            );
            self.sort(
                axis,
                self.handles[id as usize].max_edges[axis],
                true,
                false,
                axis == 2,
                &mut |_| {},
            );
        }
        ProxyKey(id)
    }

    pub fn update(
        &mut self,
        key: ProxyKey,
        min: Vec3,
        max: Vec3,
        mut release: impl FnMut(AlgorithmKey),
    ) {
        let lo = self.quantize(min, 0);
        let hi = self.quantize(max, 1);
        for axis in 0..3 {
            let emin = self.handles[key.0 as usize].min_edges[axis];
            let emax = self.handles[key.0 as usize].max_edges[axis];
            let old_min = self.edges[axis][emin as usize].pos;
            let old_max = self.edges[axis][emax as usize].pos;
            self.edges[axis][emin as usize].pos = lo[axis];
            self.edges[axis][emax as usize].pos = hi[axis];
            if lo[axis] < old_min {
                self.sort(axis, emin, false, false, true, &mut release);
            }
            if hi[axis] > old_max {
                self.sort(axis, emax, true, true, true, &mut release);
            }
            if lo[axis] > old_min {
                self.sort(axis, emin, false, true, true, &mut release);
            }
            if hi[axis] < old_max {
                self.sort(axis, emax, true, false, true, &mut release);
            }
        }
    }

    pub fn remove(&mut self, key: ProxyKey, mut release: impl FnMut(AlgorithmKey)) {
        self.cache.remove_proxy(key, &self.states, &mut release);
        for axis in 0..3 {
            self.handles[0].max_edges[axis] -= 2;
        }
        for axis in 0..3 {
            let max = self.handles[key.0 as usize].max_edges[axis];
            self.edges[axis][max as usize].pos = SENTINEL;
            self.sort(axis, max, true, true, false, &mut release);
            let min = self.handles[key.0 as usize].min_edges[axis];
            self.edges[axis][min as usize].pos = SENTINEL;
            self.sort(axis, min, false, true, false, &mut release);
            let end = self.active as usize * 2 - 1;
            self.edges[axis][end] = Edge {
                pos: SENTINEL,
                handle: 0,
            };
            self.edges[axis].truncate(end + 1);
        }
        self.live[key.0 as usize] = false;
        self.freed.push(key.0);
        self.active -= 1;
    }

    pub fn reset_pool(&mut self) {
        if self.active == 0 {
            self.freed.clear();
            self.next_unused = 1;
        }
    }

    /// Hashed cache removal is immediate; Bullet's deferred maintenance is unused.
    pub fn calculate_overlapping_pairs(&mut self) {}

    pub fn test_overlap(&self, a: ProxyKey, b: ProxyKey) -> bool {
        (0..3).all(|axis| self.overlap_axis(a.0, b.0, axis))
    }

    fn overlap_axis(&self, a: u32, b: u32, axis: usize) -> bool {
        let a = &self.handles[a as usize];
        let b = &self.handles[b as usize];
        a.max_edges[axis] >= b.min_edges[axis] && b.max_edges[axis] >= a.min_edges[axis]
    }

    fn sort(
        &mut self,
        axis: usize,
        edge: u32,
        is_max: bool,
        up: bool,
        overlaps: bool,
        release: &mut impl FnMut(AlgorithmKey),
    ) {
        let mut i = edge as usize;
        loop {
            let j = if up { i + 1 } else { i - 1 };
            let moving = self.edges[axis][i];
            let other = self.edges[axis][j];
            if if up {
                other.handle == 0 || moving.pos < other.pos
            } else {
                moving.pos >= other.pos
            } {
                break;
            }
            let other_max = other.pos & 1 != 0;
            if overlaps && other_max != is_max {
                let axis1 = (1 << axis) & 3;
                let axis2 = (1 << axis1) & 3;
                if self.overlap_axis(moving.handle, other.handle, axis1)
                    && self.overlap_axis(moving.handle, other.handle, axis2)
                {
                    let a = ProxyKey(moving.handle);
                    let b = ProxyKey(other.handle);
                    if is_max == up {
                        self.cache.add(a, b, &self.states);
                    } else {
                        self.cache.remove(a, b, &self.states, &mut *release);
                    }
                }
            }
            let other_handle = &mut self.handles[other.handle as usize];
            let other_index = if other_max {
                &mut other_handle.max_edges[axis]
            } else {
                &mut other_handle.min_edges[axis]
            };
            if up {
                *other_index -= 1;
            } else {
                *other_index += 1;
            }
            let moving_handle = &mut self.handles[moving.handle as usize];
            let moving_index = if is_max {
                &mut moving_handle.max_edges[axis]
            } else {
                &mut moving_handle.min_edges[axis]
            };
            if up {
                *moving_index += 1;
            } else {
                *moving_index -= 1;
            }
            self.edges[axis].swap(i, j);
            i = j;
        }
    }

    #[cfg(test)]
    pub fn edges(&self) -> &[Vec<Edge>; 3] {
        &self.edges
    }

    #[cfg(test)]
    pub fn first_free(&self) -> u32 {
        self.freed
            .last()
            .copied()
            .unwrap_or(if self.next_unused <= self.capacity {
                self.next_unused
            } else {
                0
            })
    }
}
