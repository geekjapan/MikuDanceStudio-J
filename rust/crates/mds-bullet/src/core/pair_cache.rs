//! Altered Rust translation of Bullet 2.75 btHashedOverlappingPairCache.
//! Translated from this repository's locally modified distribution, not stock upstream.
//! Proxy identities and algorithm lifetimes are caller-owned; no native world is used.
/*
Bullet Continuous Collision Detection and Physics Library
Copyright (c) 2003-2006 Erwin Coumans  http://continuousphysics.com/Bullet/

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
*/

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ProxyKey(pub u32);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct AlgorithmKey(pub u32);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ProxyState {
    pub uid: i32,
    pub group: i16,
    pub mask: i16,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Pair {
    pub proxies: [ProxyKey; 2],
    pub algorithm: Option<AlgorithmKey>,
    pub internal_info: usize,
}

impl Pair {
    pub fn new(a: ProxyKey, b: ProxyKey, states: &[ProxyState]) -> Self {
        Self {
            proxies: if states[a.0 as usize].uid < states[b.0 as usize].uid {
                [a, b]
            } else {
                [b, a]
            },
            algorithm: None,
            internal_info: 0,
        }
    }
}

#[derive(Debug)]
pub struct HashedPairCache {
    pairs: Vec<Pair>,
    buckets: Vec<Option<usize>>,
    next: Vec<Option<usize>>,
    capacity: usize,
}

impl Default for HashedPairCache {
    fn default() -> Self {
        Self::new()
    }
}

impl HashedPairCache {
    pub fn new() -> Self {
        Self {
            pairs: Vec::new(),
            buckets: vec![None; 2],
            next: vec![None; 2],
            capacity: 2,
        }
    }

    pub fn pairs(&self) -> &[Pair] {
        &self.pairs
    }

    pub fn for_each_algorithm(
        &mut self,
        mut visit: impl FnMut([ProxyKey; 2], &mut Option<AlgorithmKey>),
    ) {
        for pair in &mut self.pairs {
            visit(pair.proxies, &mut pair.algorithm);
        }
    }

    /// Indices are transient: any removal can move the last pair into another slot.
    /// Keys must index states; live UIDs must be unique and stable until removal.
    pub fn find(&self, mut a: ProxyKey, mut b: ProxyKey, states: &[ProxyState]) -> Option<usize> {
        if states[a.0 as usize].uid > states[b.0 as usize].uid {
            std::mem::swap(&mut a, &mut b);
        }
        let uids = [states[a.0 as usize].uid, states[b.0 as usize].uid];
        let mut index = self.buckets[self.bucket(uids)];
        while let Some(i) = index {
            if self.uids(i, states) == uids {
                return Some(i);
            }
            index = self.next[i];
        }
        None
    }

    pub fn add(&mut self, a: ProxyKey, b: ProxyKey, states: &[ProxyState]) -> Option<usize> {
        let pa = states[a.0 as usize];
        let pb = states[b.0 as usize];
        if pa.group & pb.mask == 0 || pb.group & pa.mask == 0 {
            return None;
        }
        if let Some(index) = self.find(a, b, states) {
            return Some(index);
        }
        if self.pairs.len() == self.capacity {
            self.capacity *= 2;
            self.buckets = vec![None; self.capacity];
            self.next = vec![None; self.capacity];
            for i in 0..self.pairs.len() {
                let bucket = self.bucket(self.uids(i, states));
                self.next[i] = self.buckets[bucket];
                self.buckets[bucket] = Some(i);
            }
        }
        let index = self.pairs.len();
        self.pairs.push(Pair::new(a, b, states));
        let bucket = self.bucket(self.uids(index, states));
        self.next[index] = self.buckets[bucket];
        self.buckets[bucket] = Some(index);
        Some(index)
    }

    /// Replacing an existing algorithm requires an explicit clean first.
    pub fn set_algorithm(&mut self, index: usize, algorithm: AlgorithmKey) {
        assert!(self.pairs[index].algorithm.is_none());
        self.pairs[index].algorithm = Some(algorithm);
    }

    pub fn set_internal_info(&mut self, index: usize, value: usize) {
        self.pairs[index].internal_info = value;
    }

    /// Release performs the algorithm destructor followed by dispatcher free synchronously.
    pub fn clean(&mut self, index: usize, mut release: impl FnMut(AlgorithmKey)) {
        if let Some(algorithm) = self.pairs[index].algorithm {
            release(algorithm);
            self.pairs[index].algorithm = None;
        }
    }

    pub fn remove(
        &mut self,
        a: ProxyKey,
        b: ProxyKey,
        states: &[ProxyState],
        mut release: impl FnMut(AlgorithmKey),
    ) -> Option<usize> {
        let index = self.find(a, b, states)?;
        self.clean(index, &mut release);
        let data = self.pairs[index].internal_info;
        let bucket = self.bucket(self.uids(index, states));
        self.unlink(index, bucket);
        let last = self.pairs.len() - 1;
        if index != last {
            let last_bucket = self.bucket(self.uids(last, states));
            self.unlink(last, last_bucket);
            self.pairs[index] = self.pairs[last];
            self.next[index] = self.buckets[last_bucket];
            self.buckets[last_bucket] = Some(index);
        }
        self.pairs.pop();
        Some(data)
    }

    pub fn process_all(
        &mut self,
        states: &[ProxyState],
        mut visit: impl FnMut(&Pair) -> bool,
        mut release: impl FnMut(AlgorithmKey),
    ) {
        let mut index = 0;
        while index < self.pairs.len() {
            if visit(&self.pairs[index]) {
                let [a, b] = self.pairs[index].proxies;
                self.remove(a, b, states, &mut release);
            } else {
                index += 1;
            }
        }
    }

    pub fn clean_proxy(&mut self, proxy: ProxyKey, mut release: impl FnMut(AlgorithmKey)) {
        for index in 0..self.pairs.len() {
            if self.pairs[index].proxies.contains(&proxy) {
                self.clean(index, &mut release);
            }
        }
    }

    pub fn remove_proxy(
        &mut self,
        proxy: ProxyKey,
        states: &[ProxyState],
        release: impl FnMut(AlgorithmKey),
    ) {
        self.process_all(states, |pair| pair.proxies.contains(&proxy), release);
    }

    fn uids(&self, index: usize, states: &[ProxyState]) -> [i32; 2] {
        self.pairs[index]
            .proxies
            .map(|key| states[key.0 as usize].uid)
    }

    fn bucket(&self, uids: [i32; 2]) -> usize {
        (hash(uids[0], uids[1]) as usize) & (self.capacity - 1)
    }

    fn unlink(&mut self, target: usize, bucket: usize) {
        let mut index = self.buckets[bucket];
        let mut previous = None;
        while let Some(i) = index {
            if i == target {
                if let Some(p) = previous {
                    self.next[p] = self.next[i];
                } else {
                    self.buckets[bucket] = self.next[i];
                }
                return;
            }
            previous = index;
            index = self.next[i];
        }
        unreachable!("live pair is missing from its hash chain");
    }

    #[cfg(test)]
    pub fn tables(&self) -> (usize, &[Option<usize>], &[Option<usize>]) {
        (self.capacity, &self.buckets, &self.next[..self.pairs.len()])
    }
}

fn hash(a: i32, b: i32) -> u32 {
    let mut key = (a as u32 | (b as u32).wrapping_shl(16)) as i32;
    key = key.wrapping_add(!key.wrapping_shl(15));
    key ^= key >> 10;
    key = key.wrapping_add(key.wrapping_shl(3));
    key ^= key >> 6;
    key = key.wrapping_add(!key.wrapping_shl(11));
    key ^= key >> 16;
    key as u32
}
