//! Altered Rust translation of Bullet 2.75 collision dispatcher ownership.
//! See mod.rs for the retained Bullet zlib notice.

use super::activation::BodyActivation;
use super::contact::{ContactBody, PairManifold};
use super::contact_solver::ContactManifold;
use super::islands::{IslandConstraint, IslandManifold};
use super::pair_cache::AlgorithmKey;
use super::shape::Shape;
use super::simplex::VoronoiSimplexSolver;

pub struct DispatchObject<'a> {
    pub shape: Shape,
    pub contact: ContactBody,
    pub activation: &'a BodyActivation,
    /// The body's actual disabled-collision constraint references.
    pub constraints: &'a [IslandConstraint],
    pub processing_threshold: f32,
}

struct Algorithm {
    input_bodies: [usize; 2],
    manifold_index: Option<usize>,
}

pub struct DispatcherManifold {
    owner: AlgorithmKey,
    pub bodies: [usize; 2],
    pub manifold: PairManifold,
    pub processing_threshold: f32,
}

impl DispatcherManifold {
    pub fn owner(&self) -> AlgorithmKey {
        self.owner
    }

    pub fn island_view(&self) -> IslandManifold {
        IslandManifold {
            bodies: self.bodies,
        }
    }

    pub fn contact_view(&mut self) -> ContactManifold<'_> {
        ContactManifold {
            bodies: self.bodies,
            points: self.manifold.contacts_mut(),
            processing_threshold: self.processing_threshold,
        }
    }
}

#[derive(Default)]
pub struct CollisionDispatcher {
    simplex: VoronoiSimplexSolver,
    algorithms: Vec<Option<Algorithm>>,
    manifolds: Vec<DispatcherManifold>,
}

impl CollisionDispatcher {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn manifolds(&self) -> &[DispatcherManifold] {
        &self.manifolds
    }

    pub fn manifolds_mut(&mut self) -> &mut [DispatcherManifold] {
        &mut self.manifolds
    }

    pub fn near_pair(
        &mut self,
        pair_algorithm: &mut Option<AlgorithmKey>,
        input_bodies: [usize; 2],
        objects: &[DispatchObject<'_>],
    ) {
        if !needs_collision(input_bodies, objects) {
            return;
        }
        let [a, b] = input_bodies;
        let shapes = [objects[a].shape, objects[b].shape];
        let key = if let Some(key) = *pair_algorithm {
            assert_eq!(
                self.algorithms[key.0 as usize]
                    .as_ref()
                    .unwrap()
                    .input_bodies,
                input_bodies
            );
            key
        } else {
            let slot = self
                .algorithms
                .iter()
                .position(Option::is_none)
                .unwrap_or(self.algorithms.len());
            let key = AlgorithmKey(u32::try_from(slot).expect("algorithm slot exceeds u32"));
            let algorithm = Some(Algorithm {
                input_bodies,
                manifold_index: None,
            });
            if slot == self.algorithms.len() {
                self.algorithms.push(algorithm);
            } else {
                self.algorithms[slot] = algorithm;
            }
            match shapes {
                [Shape::Sphere { .. }, Shape::Sphere { .. }] => {
                    self.allocate_manifold(key, objects)
                }
                [Shape::Box { .. }, Shape::Box { .. }]
                    if needs_collision(input_bodies, objects) =>
                {
                    self.allocate_manifold(key, objects);
                }
                [Shape::StaticPlane { .. }, Shape::StaticPlane { .. }] => (),
                [Shape::StaticPlane { .. }, _] if needs_collision([b, a], objects) => {
                    self.allocate_manifold(key, objects);
                }
                [_, Shape::StaticPlane { .. }] if needs_collision(input_bodies, objects) => {
                    self.allocate_manifold(key, objects);
                }
                _ => (),
            }
            *pair_algorithm = Some(key);
            key
        };
        // Only generic convex algorithms allocate on process; a rejected plane constructor stays empty.
        if self.algorithms[key.0 as usize]
            .as_ref()
            .unwrap()
            .manifold_index
            .is_none()
            && !shapes
                .iter()
                .any(|shape| matches!(shape, Shape::StaticPlane { .. }))
            && !matches!(
                shapes,
                [Shape::Sphere { .. }, Shape::Sphere { .. }]
                    | [Shape::Box { .. }, Shape::Box { .. }]
            )
        {
            self.allocate_manifold(key, objects);
        }
        if let Some(index) = self.algorithms[key.0 as usize]
            .as_ref()
            .unwrap()
            .manifold_index
        {
            self.manifolds[index].manifold.process(
                objects[a].contact,
                objects[b].contact,
                &mut self.simplex,
            );
        }
    }

    fn allocate_manifold(&mut self, key: AlgorithmKey, objects: &[DispatchObject<'_>]) {
        let algorithm = self.algorithms[key.0 as usize].as_mut().unwrap();
        let [a, b] = algorithm.input_bodies;
        let bodies = if matches!(objects[a].shape, Shape::StaticPlane { .. }) {
            [b, a]
        } else {
            [a, b]
        };
        let [body0, body1] = bodies.map(|i| &objects[i]);
        algorithm.manifold_index = Some(self.manifolds.len());
        self.manifolds.push(DispatcherManifold {
            owner: key,
            bodies,
            manifold: PairManifold::new(objects[a].shape, objects[b].shape).unwrap(),
            processing_threshold: if body0.processing_threshold < body1.processing_threshold {
                body0.processing_threshold
            } else {
                body1.processing_threshold
            },
        });
    }

    /// The pair cache calls this synchronously before clearing its algorithm key.
    pub fn release(&mut self, key: AlgorithmKey) {
        let index = self.algorithms[key.0 as usize]
            .as_ref()
            .expect("algorithm released twice")
            .manifold_index;
        if let Some(index) = index {
            self.manifolds[index].manifold.clear_contacts();
            self.manifolds.swap_remove(index);
            if let Some(moved) = self.manifolds.get(index) {
                self.algorithms[moved.owner.0 as usize]
                    .as_mut()
                    .unwrap()
                    .manifold_index = Some(index);
            }
        }
        self.algorithms[key.0 as usize] = None;
    }
}

fn needs_collision([a, b]: [usize; 2], objects: &[DispatchObject<'_>]) -> bool {
    (objects[a].activation.is_active() || objects[b].activation.is_active())
        && !objects[a]
            .constraints
            .iter()
            .any(|constraint| constraint.bodies.contains(&b))
}

#[cfg(test)]
#[path = "../../tests/pure_bullet/dispatcher.rs"]
mod tests;
