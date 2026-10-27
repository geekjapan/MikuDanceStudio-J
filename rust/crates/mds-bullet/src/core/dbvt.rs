//! Altered Rust translation of the locally modified Bullet 2.75 btDbvt.
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

use super::{math::Vec3, pair_cache::ProxyKey};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DbvtPolicy {
    MmdWin64Sse,
    GenericReference,
}

impl DbvtPolicy {
    pub fn intersects(self, a: Aabb, b: Aabb) -> bool {
        match self {
            Self::MmdWin64Sse => {
                !(0..3).any(|i| b.max.0[i] < a.min.0[i] || a.max.0[i] < b.min.0[i])
            }
            Self::GenericReference => {
                (0..3).all(|i| a.min.0[i] <= b.max.0[i] && a.max.0[i] >= b.min.0[i])
            }
        }
    }
    fn select(self, volume: Aabb, a: Aabb, b: Aabb) -> usize {
        let a = volume.proximity(a, self);
        let b = volume.proximity(b, self);
        match self {
            Self::MmdWin64Sse => usize::from(b <= a),
            Self::GenericReference => {
                if a < b {
                    0
                } else {
                    1
                }
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Aabb {
    pub min: Vec3,
    pub max: Vec3,
}

impl Aabb {
    pub fn merge(self, rhs: Self) -> Self {
        Self {
            min: Vec3(std::array::from_fn(|i| {
                if self.min.0[i] < rhs.min.0[i] {
                    self.min.0[i]
                } else {
                    rhs.min.0[i]
                }
            })),
            max: Vec3(std::array::from_fn(|i| {
                if self.max.0[i] > rhs.max.0[i] {
                    self.max.0[i]
                } else {
                    rhs.max.0[i]
                }
            })),
        }
    }
    pub fn contains(self, rhs: Self) -> bool {
        (0..3).all(|i| self.min.0[i] <= rhs.min.0[i] && self.max.0[i] >= rhs.max.0[i])
    }
    fn center(self) -> Vec3 {
        self.min.add(self.max).scale(0.5)
    }
    fn proximity(self, rhs: Self, policy: DbvtPolicy) -> f32 {
        let d = self
            .min
            .add(self.max)
            .sub(rhs.min.add(rhs.max))
            .0
            .map(f32::abs);
        if policy == DbvtPolicy::MmdWin64Sse {
            (d[0] + d[2]) + (d[1] + 0.0)
        } else {
            (d[0] + d[1]) + d[2]
        }
    }
    fn size(self) -> f32 {
        let [x, y, z] = self.max.sub(self.min).0;
        (((x * y) * z + x) + y) + z
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct NodeId(usize);
#[derive(Clone, Copy, Debug)]
enum Kind {
    Leaf(ProxyKey),
    Branch([NodeId; 2]),
}
#[derive(Debug)]
#[repr(align(16))]
struct Node {
    volume: Aabb,
    parent: Option<NodeId>,
    kind: Kind,
}

#[derive(Debug)]
pub struct Dbvt {
    policy: DbvtPolicy,
    nodes: Vec<Option<Box<Node>>>,
    root: Option<NodeId>,
    free: Option<NodeId>,
    leaves: usize,
    pub lookahead: i32,
    opath: u32,
    #[cfg(test)]
    address_ranks: Option<Vec<usize>>,
}
impl Drop for Dbvt {
    fn drop(&mut self) {
        self.clear();
    }
}
impl Dbvt {
    pub fn new(policy: DbvtPolicy) -> Self {
        Self {
            policy,
            nodes: Vec::new(),
            root: None,
            free: None,
            leaves: 0,
            lookahead: -1,
            opath: 0,
            #[cfg(test)]
            address_ranks: None,
        }
    }
    fn node(&self, n: NodeId) -> &Node {
        self.nodes[n.0].as_deref().unwrap()
    }
    fn node_mut(&mut self, n: NodeId) -> &mut Node {
        self.nodes[n.0].as_deref_mut().unwrap()
    }
    fn children(&self, n: NodeId) -> Option<[NodeId; 2]> {
        match self.node(n).kind {
            Kind::Branch(c) => Some(c),
            Kind::Leaf(_) => None,
        }
    }
    fn create(&mut self, volume: Aabb, parent: Option<NodeId>, kind: Kind) -> NodeId {
        let node = Node {
            volume,
            parent,
            kind,
        };
        if let Some(id) = self.free.take() {
            *self.node_mut(id) = node;
            id
        } else if let Some(index) = self.nodes.iter().position(Option::is_none) {
            self.nodes[index] = Some(Box::new(node));
            NodeId(index)
        } else {
            let id = NodeId(self.nodes.len());
            self.nodes.push(Some(Box::new(node)));
            id
        }
    }
    fn delete(&mut self, n: NodeId) {
        if let Some(old) = self.free.replace(n) {
            self.nodes[old.0] = None;
        }
    }
    fn find(&self, key: ProxyKey) -> NodeId {
        self.nodes
            .iter()
            .enumerate()
            .find_map(|(i, n)| {
                if self.free == Some(NodeId(i)) {
                    return None;
                }
                match n.as_deref().map(|n| n.kind) {
                    Some(Kind::Leaf(k)) if k == key => Some(NodeId(i)),
                    _ => None,
                }
            })
            .expect("proxy must be live in this tree")
    }
    fn index(&self, n: NodeId) -> usize {
        usize::from(self.children(self.node(n).parent.unwrap()).unwrap()[1] == n)
    }
    fn merge_children(&mut self, n: NodeId) {
        let [a, b] = self.children(n).unwrap();
        self.node_mut(n).volume = self.node(a).volume.merge(self.node(b).volume);
    }
    fn insert_leaf(&mut self, root: Option<NodeId>, leaf: NodeId) {
        let Some(mut root) = root else {
            self.root = Some(leaf);
            self.node_mut(leaf).parent = None;
            return;
        };
        let volume = self.node(leaf).volume;
        while let Some(c) = self.children(root) {
            let side = self
                .policy
                .select(volume, self.node(c[0]).volume, self.node(c[1]).volume);
            root = c[side];
        }
        let mut prev = self.node(root).parent;
        let mut node = self.create(
            volume.merge(self.node(root).volume),
            prev,
            Kind::Branch([root, leaf]),
        );
        if let Some(p) = prev {
            let i = self.index(root);
            if let Kind::Branch(c) = &mut self.node_mut(p).kind {
                c[i] = node;
            }
        } else {
            self.root = Some(node);
        }
        self.node_mut(root).parent = Some(node);
        self.node_mut(leaf).parent = Some(node);
        while let Some(p) = prev {
            if self.node(p).volume.contains(self.node(node).volume) {
                break;
            }
            self.merge_children(p);
            node = p;
            prev = self.node(node).parent;
        }
    }
    fn remove_leaf(&mut self, leaf: NodeId) -> Option<NodeId> {
        if self.root == Some(leaf) {
            self.root = None;
            return None;
        }
        let parent = self.node(leaf).parent.unwrap();
        let mut prev = self.node(parent).parent;
        let sibling = self.children(parent).unwrap()[1 - self.index(leaf)];
        if let Some(p) = prev {
            let i = self.index(parent);
            if let Kind::Branch(c) = &mut self.node_mut(p).kind {
                c[i] = sibling;
            }
            self.node_mut(sibling).parent = Some(p);
            self.delete(parent);
            while let Some(p) = prev {
                let old = self.node(p).volume;
                self.merge_children(p);
                if old == self.node(p).volume {
                    break;
                }
                prev = self.node(p).parent;
            }
            prev.or(self.root)
        } else {
            self.root = Some(sibling);
            self.node_mut(sibling).parent = None;
            self.delete(parent);
            self.root
        }
    }
    pub fn insert(&mut self, key: ProxyKey, volume: Aabb) {
        assert!(
            !self
                .nodes
                .iter()
                .enumerate()
                .any(|(i, n)| self.free != Some(NodeId(i))
                    && matches!(n.as_deref().map(|n| n.kind),Some(Kind::Leaf(k)) if k == key)),
            "proxy already live"
        );
        let leaf = self.create(volume, None, Kind::Leaf(key));
        self.insert_leaf(self.root, leaf);
        self.leaves += 1;
    }
    pub fn remove(&mut self, key: ProxyKey) {
        let leaf = self.find(key);
        self.remove_leaf(leaf);
        self.delete(leaf);
        self.leaves -= 1;
    }
    fn update_leaf(&mut self, leaf: NodeId, volume: Aabb, lookahead: i32) {
        let mut root = self.remove_leaf(leaf);
        if lookahead < 0 {
            root = self.root;
        } else {
            for _ in 0..lookahead {
                if let Some(parent) = root.and_then(|r| self.node(r).parent) {
                    root = Some(parent);
                } else {
                    break;
                }
            }
        }
        self.node_mut(leaf).volume = volume;
        self.insert_leaf(root, leaf);
    }
    pub fn update(&mut self, key: ProxyKey, volume: Aabb) {
        self.update_leaf(self.find(key), volume, self.lookahead);
    }
    pub fn reinsert(&mut self, key: ProxyKey, lookahead: i32) {
        let n = self.find(key);
        self.update_leaf(n, self.node(n).volume, lookahead);
    }
    pub fn update_predicted(
        &mut self,
        key: ProxyKey,
        volume: &mut Aabb,
        velocity: Option<Vec3>,
        margin: Option<f32>,
    ) -> bool {
        let n = self.find(key);
        if self.node(n).volume.contains(*volume) {
            return false;
        }
        if let Some(m) = margin {
            volume.min = volume.min.sub(Vec3([m; 3]));
            volume.max = volume.max.add(Vec3([m; 3]));
        }
        if let Some(v) = velocity {
            for i in 0..3 {
                if v.0[i] > 0.0 {
                    volume.max.0[i] += v.0[i];
                } else {
                    volume.min.0[i] += v.0[i];
                }
            }
        }
        self.update_leaf(n, *volume, self.lookahead);
        true
    }
    pub fn volume(&self, key: ProxyKey) -> Aabb {
        self.node(self.find(key)).volume
    }
    pub fn bounds(&self) -> Option<Aabb> {
        self.root.map(|root| self.node(root).volume)
    }
    pub fn leaf_count(&self) -> usize {
        self.leaves
    }
    fn fetch(&mut self, n: NodeId, leaves: &mut Vec<NodeId>) {
        if let Some([a, b]) = self.children(n) {
            self.fetch(a, leaves);
            self.fetch(b, leaves);
            self.delete(n);
        } else {
            leaves.push(n);
        }
    }
    fn bottom_up(&mut self, mut leaves: Vec<NodeId>) -> NodeId {
        while leaves.len() > 1 {
            let mut best = f32::MAX;
            // Native leaves its pair invalid when every size overflows.
            let mut pair = (0, 1);
            for i in 0..leaves.len() {
                for j in i + 1..leaves.len() {
                    let size = self
                        .node(leaves[i])
                        .volume
                        .merge(self.node(leaves[j]).volume)
                        .size();
                    if size < best {
                        best = size;
                        pair = (i, j);
                    }
                }
            }
            let (i, j) = pair;
            let a = leaves[i];
            let b = leaves[j];
            let p = self.create(
                self.node(a).volume.merge(self.node(b).volume),
                None,
                Kind::Branch([a, b]),
            );
            self.node_mut(a).parent = Some(p);
            self.node_mut(b).parent = Some(p);
            leaves[i] = p;
            leaves.swap_remove(j);
        }
        leaves[0]
    }
    fn top_down(&mut self, leaves: Vec<NodeId>, threshold: usize) -> NodeId {
        if leaves.len() == 1 {
            return leaves[0];
        }
        if leaves.len() <= threshold {
            return self.bottom_up(leaves);
        }
        let mut volume = self.node(leaves[0]).volume;
        for &n in &leaves[1..] {
            volume = volume.merge(self.node(n).volume);
        }
        let org = volume.center();
        let mut counts = [[0usize; 2]; 3];
        for &n in &leaves {
            let x = self.node(n).volume.center().sub(org);
            for (j, c) in counts.iter_mut().enumerate() {
                let mut axis = [0.0; 3];
                axis[j] = 1.0;
                c[usize::from(x.dot(Vec3(axis)) > 0.0)] += 1;
            }
        }
        let mut best = None;
        let mut mid = leaves.len();
        for (i, c) in counts.iter().enumerate() {
            let m = c[0].abs_diff(c[1]);
            if c[0] > 0 && c[1] > 0 && m < mid {
                mid = m;
                best = Some(i);
            }
        }
        let mut sets = [Vec::new(), Vec::new()];
        for (i, n) in leaves.into_iter().enumerate() {
            let side = if let Some(j) = best {
                let mut axis = [0.0; 3];
                axis[j] = 1.0;
                if Vec3(axis).dot(self.node(n).volume.center().sub(org)) < 0.0 {
                    0
                } else {
                    1
                }
            } else {
                i & 1
            };
            sets[side].push(n);
        }
        if sets.iter().any(Vec::is_empty) {
            // Native counts >0 but partitions <0; zero centers can otherwise recurse forever.
            return self.bottom_up(sets.into_iter().flatten().collect());
        }
        let placeholder = sets[0][0];
        let p = self.create(volume, None, Kind::Branch([placeholder; 2]));
        let [left, right] = sets;
        let a = self.top_down(left, threshold);
        let b = self.top_down(right, threshold);
        self.node_mut(p).kind = Kind::Branch([a, b]);
        self.node_mut(a).parent = Some(p);
        self.node_mut(b).parent = Some(p);
        p
    }
    pub fn optimize_bottom_up(&mut self) {
        if let Some(root) = self.root.take() {
            let mut leaves = Vec::new();
            self.fetch(root, &mut leaves);
            #[cfg(test)]
            tests::after_destructive_fetch(self);
            self.root = Some(self.bottom_up(leaves));
        }
    }
    pub fn optimize_top_down(&mut self, threshold: usize) {
        if let Some(root) = self.root.take() {
            let mut leaves = Vec::new();
            self.fetch(root, &mut leaves);
            #[cfg(test)]
            tests::after_destructive_fetch(self);
            self.root = Some(self.top_down(leaves, threshold));
        }
    }
    fn address(&self, n: NodeId) -> usize {
        self.node(n) as *const Node as usize
    }
    fn parent_after(&self, parent: NodeId, n: NodeId) -> bool {
        #[cfg(test)]
        if let Some(ranks) = &self.address_ranks {
            return ranks[parent.0] > ranks[n.0];
        }
        self.address(parent) > self.address(n)
    }
    fn sort(&mut self, n: NodeId) -> NodeId {
        let Some(p) = self.node(n).parent else {
            return n;
        };
        if !self.parent_after(p, n) {
            return n;
        }
        let i = self.index(n);
        let j = 1 - i;
        let sibling = self.children(p).unwrap()[j];
        let q = self.node(p).parent;
        if let Some(q) = q {
            let k = self.index(p);
            if let Kind::Branch(c) = &mut self.node_mut(q).kind {
                c[k] = n;
            }
        } else {
            self.root = Some(n);
        }
        self.node_mut(sibling).parent = Some(n);
        self.node_mut(p).parent = Some(n);
        self.node_mut(n).parent = q;
        let children = self.children(n).unwrap();
        self.node_mut(p).kind = Kind::Branch(children);
        for c in children {
            self.node_mut(c).parent = Some(p);
        }
        let mut c = [n; 2];
        c[i] = p;
        c[j] = sibling;
        self.node_mut(n).kind = Kind::Branch(c);
        let pv = self.node(p).volume;
        self.node_mut(p).volume = self.node(n).volume;
        self.node_mut(n).volume = pv;
        p
    }
    pub fn optimize_incremental(&mut self, passes: i32) {
        let passes = if passes < 0 {
            self.leaves
        } else {
            passes as usize
        };
        if self.root.is_none() {
            return;
        }
        for _ in 0..passes {
            let mut n = self.root.unwrap();
            let mut bit = 0;
            while self.children(n).is_some() {
                let s = self.sort(n);
                n = self.children(s).unwrap()[((self.opath >> bit) & 1) as usize];
                bit = (bit + 1) & 31;
            }
            self.update_leaf(n, self.node(n).volume, -1);
            self.opath = self.opath.wrapping_add(1);
        }
    }
    pub fn clear(&mut self) {
        fn delete_tree(tree: &mut Dbvt, n: NodeId) {
            if let Some(c) = tree.children(n) {
                for n in c {
                    delete_tree(tree, n);
                }
            }
            tree.delete(n);
        }
        if let Some(root) = self.root {
            delete_tree(self, root);
        }
        if let Some(free) = self.free.take() {
            self.nodes[free.0] = None;
        }
        self.root = None;
        self.lookahead = -1;
        self.opath = 0;
        // Bullet 2.75 clear leaves m_leaves unchanged.
    }
    pub fn collide_volume(&self, volume: Aabb, mut process: impl FnMut(ProxyKey)) {
        self.query(|v| self.policy.intersects(v, volume), &mut process);
    }
    fn query(&self, test: impl Fn(Aabb) -> bool, process: &mut impl FnMut(ProxyKey)) {
        let mut stack: Vec<_> = self.root.into_iter().collect();
        while let Some(n) = stack.pop() {
            if test(self.node(n).volume) {
                match self.node(n).kind {
                    Kind::Leaf(key) => process(key),
                    Kind::Branch(c) => stack.extend(c),
                }
            }
        }
    }
    pub fn collide_tree(&self, other: &Self, mut process: impl FnMut(ProxyKey, ProxyKey)) {
        self.collide_roots(other, other.root, &mut process);
    }
    pub fn collide_leaf(
        &self,
        other: &Self,
        key: ProxyKey,
        mut process: impl FnMut(ProxyKey, ProxyKey),
    ) {
        self.collide_roots(other, Some(other.find(key)), &mut process);
    }
    fn collide_roots(
        &self,
        other: &Self,
        root: Option<NodeId>,
        process: &mut impl FnMut(ProxyKey, ProxyKey),
    ) {
        assert_eq!(
            self.policy, other.policy,
            "cross-tree DBVT policies must match"
        );
        let mut stack = Vec::new();
        if let (Some(a), Some(b)) = (self.root, root) {
            stack.push((a, b));
        }
        while let Some((a, b)) = stack.pop() {
            let ca = self.children(a);
            let cb = other.children(b);
            if std::ptr::eq(self, other) && a == b {
                if let Some([x, y]) = ca {
                    stack.extend([(x, x), (y, y), (x, y)]);
                }
            } else if self
                .policy
                .intersects(self.node(a).volume, other.node(b).volume)
            {
                match (ca, cb) {
                    (Some([a0, a1]), Some([b0, b1])) => {
                        stack.extend([(a0, b0), (a1, b0), (a0, b1), (a1, b1)])
                    }
                    (Some(c), None) => stack.extend(c.map(|a| (a, b))),
                    (None, Some(c)) => stack.extend(c.map(|b| (a, b))),
                    (None, None) => {
                        if let (Kind::Leaf(a), Kind::Leaf(b)) =
                            (self.node(a).kind, other.node(b).kind)
                        {
                            process(a, b);
                        }
                    }
                }
            }
        }
    }
    pub fn ray_test(
        &self,
        from: Vec3,
        inverse: Vec3,
        signs: [usize; 3],
        lambda_max: f32,
        aabb: Aabb,
        mut process: impl FnMut(ProxyKey) -> bool,
    ) {
        self.query(
            |v| {
                let bounds = [v.min.add(aabb.min), v.max.add(aabb.max)];
                let mut lo = (bounds[signs[0]].0[0] - from.0[0]) * inverse.0[0];
                let mut hi = (bounds[1 - signs[0]].0[0] - from.0[0]) * inverse.0[0];
                for i in 1..3 {
                    let l = (bounds[signs[i]].0[i] - from.0[i]) * inverse.0[i];
                    let h = (bounds[1 - signs[i]].0[i] - from.0[i]) * inverse.0[i];
                    if lo > h || l > hi {
                        return false;
                    }
                    if l > lo {
                        lo = l;
                    }
                    if h < hi {
                        hi = h;
                    }
                }
                lo < lambda_max && hi > 0.0
            },
            &mut |key| {
                process(key);
            },
        );
    }
}

#[cfg(test)]
#[path = "../../../../../tools/bullet-rust-dbvt-check/fixtures.rs"]
pub(crate) mod tests;
