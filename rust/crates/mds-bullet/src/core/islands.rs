//! Altered Rust translation of Bullet 2.75 islands; see mod.rs for the zlib notice.
use super::activation::{ActivationState, BodyActivation, CollisionClassification};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Element {
    pub id: usize,
    /// Union size before sorting, original collision-object index afterwards.
    pub size_or_body_index: usize,
}

#[derive(Default, Debug)]
pub struct UnionFind {
    elements: Vec<Element>,
}

impl UnionFind {
    pub fn elements(&self) -> &[Element] {
        &self.elements
    }

    pub fn reset(&mut self, count: usize) {
        self.elements = (0..count)
            .map(|id| Element {
                id,
                size_or_body_index: 1,
            })
            .collect();
    }

    pub fn find(&mut self, mut x: usize) -> usize {
        while x != self.elements[x].id {
            self.elements[x].id = self.elements[self.elements[x].id].id;
            x = self.elements[x].id;
        }
        x
    }

    pub fn unite(&mut self, p: usize, q: usize) {
        let i = self.find(p);
        let j = self.find(q);
        if i != j {
            self.elements[i].id = j;
            self.elements[j].size_or_body_index += self.elements[i].size_or_body_index;
        }
    }

    /// Destroys the union-find representation, exactly as native sortIslands does.
    pub fn sort_islands(&mut self) {
        for i in 0..self.elements.len() {
            self.elements[i].id = self.find(i);
            self.elements[i].size_or_body_index = i;
        }
        quick_sort(&mut self.elements, |a, b| a.id < b.id);
    }
}

/// Native central-pivot quicksort, including swaps between equal keys.
pub fn quick_sort<T: Copy>(values: &mut [T], less: impl Fn(T, T) -> bool) {
    fn partition<T: Copy>(v: &mut [T], lo: isize, hi: isize, less: &impl Fn(T, T) -> bool) {
        let (mut i, mut j) = (lo, hi);
        let pivot = v[((lo + hi) / 2) as usize];
        loop {
            while less(v[i as usize], pivot) {
                i += 1;
            }
            while less(pivot, v[j as usize]) {
                j -= 1;
            }
            if i <= j {
                v.swap(i as usize, j as usize);
                i += 1;
                j -= 1;
            }
            if i > j {
                break;
            }
        }
        if lo < j {
            partition(v, lo, j, less);
        }
        if i < hi {
            partition(v, i, hi, less);
        }
    }
    if values.len() > 1 {
        partition(values, 0, values.len() as isize - 1, &less);
    }
}

/// The authoritative object state, in native collision_objects order.
#[derive(Clone, Copy, Debug)]
pub struct IslandObject {
    pub activation: BodyActivation,
    pub classification: CollisionClassification,
    pub contact_response: bool,
    pub island_tag: i32,
    pub companion_id: i32,
    pub hit_fraction: f32,
}

impl IslandObject {
    fn merges_simulation_islands(&self) -> bool {
        self.classification == CollisionClassification::Dynamic && self.contact_response
    }

    fn is_kinematic(&self) -> bool {
        matches!(
            self.classification,
            CollisionClassification::Kinematic | CollisionClassification::StaticAndKinematic
        )
    }
}

#[derive(Clone, Copy, Debug)]
pub struct IslandManifold {
    pub bodies: [usize; 2],
}

#[derive(Clone, Copy, Debug)]
pub struct IslandConstraint {
    pub bodies: [usize; 2],
}

fn island_key(objects: &[IslandObject], [a, b]: [usize; 2]) -> i32 {
    if objects[a].island_tag >= 0 {
        objects[a].island_tag
    } else {
        objects[b].island_tag
    }
}

/// Borrowed registration indices; these never reorder the object or endpoint arrays.
#[derive(Debug)]
pub struct IslandCallback<'a> {
    pub island_id: i32,
    pub bodies: &'a [usize],
    pub manifolds: &'a [usize],
}

#[derive(Debug)]
pub enum SolverEvent<'a> {
    Prepare {
        num_bodies: usize,
        num_manifolds: usize,
    },
    SolveGroup {
        island: IslandCallback<'a>,
        constraints: &'a [usize],
    },
    AllSolved,
}

#[derive(Default, Debug)]
pub struct SimulationIslands {
    pub union_find: UnionFind,
    ordered_manifolds: Vec<usize>,
    ordered_bodies: Vec<usize>,
}

impl SimulationIslands {
    pub fn update_activation_state(
        &mut self,
        objects: &mut [IslandObject],
        pairs: impl IntoIterator<Item = [usize; 2]>,
    ) {
        self.union_find.reset(objects.len());
        for (index, object) in objects.iter_mut().enumerate() {
            object.island_tag = index as i32;
            object.companion_id = -1;
            object.hit_fraction = 1.0;
        }
        for [a, b] in pairs {
            if objects[a].merges_simulation_islands() && objects[b].merges_simulation_islands() {
                self.union_find.unite(a, b);
            }
        }
    }

    pub fn unite_constraints(
        &mut self,
        objects: &[IslandObject],
        constraints: &[IslandConstraint],
    ) {
        for constraint in constraints {
            let [a, b] = constraint.bodies;
            if objects[a].classification == CollisionClassification::Dynamic
                && objects[b].classification == CollisionClassification::Dynamic
                && (objects[a].activation.is_active() || objects[b].activation.is_active())
            {
                self.union_find.unite(a, b);
            }
        }
    }

    pub fn store_activation_state(&mut self, objects: &mut [IslandObject]) {
        for (i, object) in objects.iter_mut().enumerate() {
            if object.classification == CollisionClassification::Dynamic {
                object.island_tag = self.union_find.find(i) as i32;
                object.companion_id = -1;
            } else {
                object.island_tag = -1;
                object.companion_id = -2;
            }
        }
    }

    pub fn calculate(
        &mut self,
        objects: &mut [IslandObject],
        pairs: impl IntoIterator<Item = [usize; 2]>,
        constraints: &[IslandConstraint],
    ) {
        self.update_activation_state(objects, pairs);
        self.unite_constraints(objects, constraints);
        self.store_activation_state(objects);
    }

    fn build(&mut self, objects: &mut [IslandObject], manifolds: &[IslandManifold], split: bool) {
        self.ordered_manifolds.clear();
        self.union_find.sort_islands();
        let elements = self.union_find.elements();
        let mut start = 0;
        while start < elements.len() {
            let root = elements[start].id as i32;
            let mut end = start + 1;
            while end < elements.len() && elements[end].id as i32 == root {
                end += 1;
            }
            let all_sleeping = elements[start..end].iter().all(|e| {
                let o = &objects[e.size_or_body_index];
                o.island_tag != root
                    || !matches!(
                        o.activation.state,
                        ActivationState::Active | ActivationState::DisableDeactivation
                    )
            });
            for e in &elements[start..end] {
                let o = &mut objects[e.size_or_body_index];
                if o.island_tag == root {
                    if all_sleeping {
                        o.activation
                            .set_activation_state(ActivationState::IslandSleeping);
                    } else if o.activation.state == ActivationState::IslandSleeping {
                        o.activation
                            .set_activation_state(ActivationState::WantsDeactivation);
                        o.activation.deactivation_time = 0.0;
                    }
                }
            }
            start = end;
        }
        for (index, manifold) in manifolds.iter().enumerate() {
            let [a, b] = manifold.bodies;
            if objects[a].activation.state != ActivationState::IslandSleeping
                || objects[b].activation.state != ActivationState::IslandSleeping
            {
                if objects[a].is_kinematic()
                    && objects[a].activation.state != ActivationState::IslandSleeping
                {
                    objects[b]
                        .activation
                        .activate(false, objects[b].classification);
                }
                if objects[b].is_kinematic()
                    && objects[b].activation.state != ActivationState::IslandSleeping
                {
                    objects[a]
                        .activation
                        .activate(false, objects[a].classification);
                }
                if split
                    && objects[a].contact_response
                    && objects[b].contact_response
                    && (objects[a].classification == CollisionClassification::Dynamic
                        || objects[b].classification == CollisionClassification::Dynamic)
                {
                    self.ordered_manifolds.push(index);
                }
            }
        }
    }

    pub fn build_and_process(
        &mut self,
        objects: &mut [IslandObject],
        manifolds: &[IslandManifold],
        split: bool,
        mut callback: impl FnMut(&mut [IslandObject], IslandCallback<'_>),
    ) {
        self.build(objects, manifolds, split);
        if !split {
            self.ordered_bodies = (0..objects.len()).collect();
            self.ordered_manifolds = (0..manifolds.len()).collect();
            callback(
                objects,
                IslandCallback {
                    island_id: -1,
                    bodies: &self.ordered_bodies,
                    manifolds: &self.ordered_manifolds,
                },
            );
            return;
        }
        quick_sort(&mut self.ordered_manifolds, |a, b| {
            island_key(objects, manifolds[a].bodies) < island_key(objects, manifolds[b].bodies)
        });
        let elements = self.union_find.elements();
        let mut start = 0;
        let mut cursor = 0;
        while start < elements.len() {
            let root = elements[start].id as i32;
            let mut end = start;
            let mut sleeping = false;
            self.ordered_bodies.clear();
            while end < elements.len() && elements[end].id as i32 == root {
                let body = elements[end].size_or_body_index;
                self.ordered_bodies.push(body);
                if !objects[body].activation.is_active() {
                    sleeping = true;
                }
                end += 1;
            }
            let mut next = cursor;
            if cursor < self.ordered_manifolds.len()
                && island_key(objects, manifolds[self.ordered_manifolds[cursor]].bodies) == root
            {
                next += 1;
                while next < self.ordered_manifolds.len()
                    && island_key(objects, manifolds[self.ordered_manifolds[next]].bodies) == root
                {
                    next += 1;
                }
            }
            if !sleeping {
                callback(
                    objects,
                    IslandCallback {
                        island_id: root,
                        bodies: &self.ordered_bodies,
                        manifolds: &self.ordered_manifolds[cursor..next],
                    },
                );
            }
            cursor = next;
            start = end;
        }
        self.ordered_bodies.clear();
    }

    /// The scheduling portion of native solveConstraints, without a numeric solver.
    pub fn solve_constraints(
        &mut self,
        objects: &mut [IslandObject],
        manifolds: &[IslandManifold],
        constraints: &[IslandConstraint],
        split: bool,
        mut callback: impl FnMut(&mut [IslandObject], SolverEvent<'_>),
    ) {
        let mut sorted: Vec<usize> = (0..constraints.len()).collect();
        quick_sort(&mut sorted, |a, b| {
            island_key(objects, constraints[a].bodies) < island_key(objects, constraints[b].bodies)
        });
        let keys: Vec<i32> = constraints
            .iter()
            .map(|c| island_key(objects, c.bodies))
            .collect();
        callback(
            objects,
            SolverEvent::Prepare {
                num_bodies: objects.len(),
                num_manifolds: manifolds.len(),
            },
        );
        self.build_and_process(objects, manifolds, split, |objects, island| {
            let (start, count) = if island.island_id < 0 {
                (0, sorted.len())
            } else {
                let start = sorted
                    .iter()
                    .position(|&i| keys[i] == island.island_id)
                    .unwrap_or(sorted.len());
                let count = sorted[start..]
                    .iter()
                    .filter(|&&i| keys[i] == island.island_id)
                    .count();
                (start, count)
            };
            if !island.manifolds.is_empty() || count != 0 {
                callback(
                    objects,
                    SolverEvent::SolveGroup {
                        island,
                        constraints: &sorted[start..start + count],
                    },
                );
            }
        });
        callback(objects, SolverEvent::AllSolved);
    }
}
