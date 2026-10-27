//! Altered Rust translation of Bullet 2.75 default contact SI solving.
//! See mod.rs for the zlib notice. World scheduling remains external.

use super::body::RigidBody;
use super::contact::{plane_space, ContactPoint};
use super::math::Vec3;
use super::solver::{product, resolve, ImpulseRow, SolverBody, SolverMode};

/// Body order must match the manifold's normal and world contact positions.
pub struct ContactManifold<'a> {
    pub bodies: [usize; 2],
    pub points: &'a mut [ContactPoint],
    pub processing_threshold: f32,
}

impl<'a> ContactManifold<'a> {
    pub fn new(bodies: [usize; 2], points: &'a mut [ContactPoint]) -> Self {
        Self {
            bodies,
            points,
            processing_threshold: 1e18,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct NormalRow {
    pub numeric: ImpulseRow,
    pub point: [usize; 2],
    pub friction: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct FrictionRow {
    pub numeric: ImpulseRow,
    pub normal_index: usize,
}

/// Default mode 260 only. No split impulses, direction caching or friction warmstart.
pub struct ContactSolver {
    pub bodies: Vec<SolverBody>,
    pub normals: Vec<NormalRow>,
    pub frictions: Vec<FrictionRow>,
}

impl ContactSolver {
    /// Requires valid indices and positive timestep, as does the joint kernel.
    pub fn setup(bodies: &[RigidBody], manifolds: &mut [ContactManifold<'_>], dt: f32) -> Self {
        let fixed = SolverBody {
            original: None,
            inverse_mass: Vec3::ZERO,
            angular_factor: Vec3([1.0; 3]),
            delta_linear: Vec3::ZERO,
            delta_angular: Vec3::ZERO,
        };
        let mut solver = Self {
            bodies: vec![fixed],
            normals: Vec::new(),
            frictions: Vec::new(),
        };
        let mut slots = vec![None; bodies.len()];
        for (mi, manifold) in manifolds.iter_mut().enumerate() {
            if manifold.points.is_empty() {
                continue;
            }
            let ids = manifold.bodies.map(|i| {
                let state = bodies[i].snapshot();
                if state.inverse_mass == 0.0 {
                    return 0;
                }
                *slots[i].get_or_insert_with(|| {
                    let index = solver.bodies.len();
                    solver.bodies.push(SolverBody {
                        original: Some(i),
                        inverse_mass: bodies[i].linear_factor().scale(state.inverse_mass),
                        angular_factor: bodies[i].angular_factor(),
                        ..fixed
                    });
                    index
                })
            });
            if ids == [0, 0] {
                continue;
            }
            let [a, b] = manifold.bodies.map(|i| bodies[i].snapshot());
            for (pi, point) in manifold.points.iter_mut().enumerate() {
                if point
                    .distance
                    .partial_cmp(&manifold.processing_threshold)
                    .is_none_or(|o| o == std::cmp::Ordering::Greater)
                {
                    continue;
                }
                let rel = [
                    point.world_a.sub(a.world.origin),
                    point.world_b.sub(b.world.origin),
                ];
                let velocity = a
                    .angular_velocity
                    .cross(rel[0])
                    .add(a.linear_velocity)
                    .sub(b.angular_velocity.cross(rel[1]).add(b.linear_velocity));
                let relative_velocity = point.normal_on_b.dot(velocity);
                let mut restitution = if point.lifetime > 2 {
                    0.0
                } else {
                    point.combined_restitution * -relative_velocity
                };
                if restitution <= 0.0 {
                    restitution = 0.0;
                }
                let mut normal =
                    make_row(bodies, manifold.bodies, ids, rel, point.normal_on_b, false);
                let positional_error = -(point.distance + 0.0) * 0.2 / dt;
                normal.rhs = positional_error * normal.diagonal_inverse
                    + (restitution
                        - row_velocity(
                            normal,
                            a.linear_velocity,
                            a.angular_velocity,
                            b.linear_velocity,
                            b.angular_velocity,
                        ))
                        * normal.diagonal_inverse;
                normal.applied_impulse = point.applied_impulse * 0.85;
                for (side, &id) in ids.iter().enumerate() {
                    let original = manifold.bodies[side];
                    let state = bodies[original].snapshot();
                    let impulse = if side == 0 {
                        normal.applied_impulse
                    } else {
                        -normal.applied_impulse
                    };
                    let linear = product(
                        normal.normal.scale(state.inverse_mass),
                        bodies[original].linear_factor(),
                    );
                    let angular = if side == 0 {
                        normal.angular_components[side]
                    } else {
                        normal.angular_components[side].negate()
                    };
                    let target = &mut solver.bodies[id];
                    target.delta_linear = target.delta_linear.add(linear.scale(impulse));
                    target.delta_angular = target
                        .delta_angular
                        .add(product(angular, target.angular_factor.scale(impulse)));
                }
                let lateral = velocity.sub(point.normal_on_b.scale(relative_velocity));
                if lateral.length2() > f32::EPSILON {
                    point.lateral_directions[0] = lateral.normalize();
                } else {
                    let p = plane_space(point.normal_on_b);
                    let [x, y, z] = point.normal_on_b.0;
                    let q = if z.abs() > std::f32::consts::FRAC_1_SQRT_2 {
                        let a = y * y + z * z;
                        Vec3([a * (1.0 / a.sqrt()), -x * p.0[2], x * p.0[1]])
                    } else {
                        let a = x * x + y * y;
                        Vec3([-z * p.0[1], z * p.0[0], a * (1.0 / a.sqrt())])
                    };
                    point.lateral_directions = [p, q];
                }
                point.lateral_initialized = true;
                let friction = make_row(
                    bodies,
                    manifold.bodies,
                    ids,
                    rel,
                    point.lateral_directions[0],
                    true,
                );
                solver.frictions.push(FrictionRow {
                    numeric: friction,
                    normal_index: solver.normals.len(),
                });
                solver.normals.push(NormalRow {
                    numeric: normal,
                    point: [mi, pi],
                    friction: point.combined_friction,
                });
            }
        }
        solver
    }

    pub fn iterate(&mut self) {
        self.iterate_with_observer(|_, _, _, _| {});
    }

    /// Events follow native order, all normals then all active friction rows per iteration.
    pub fn iterate_with_observer(&mut self, mut observe: impl FnMut(&Self, usize, bool, usize)) {
        for iteration in 0..10 {
            for index in 0..self.normals.len() {
                resolve(
                    &mut self.bodies,
                    &mut self.normals[index].numeric,
                    SolverMode::Simd,
                    true,
                );
                observe(self, iteration, false, index);
            }
            for index in 0..self.frictions.len() {
                let normal = self.normals[self.frictions[index].normal_index];
                if normal.numeric.applied_impulse > 0.0 {
                    let limit = normal.friction * normal.numeric.applied_impulse;
                    self.frictions[index].numeric.lower_impulse = -limit;
                    self.frictions[index].numeric.upper_impulse = limit;
                    resolve(
                        &mut self.bodies,
                        &mut self.frictions[index].numeric,
                        SolverMode::Simd,
                        false,
                    );
                    observe(self, iteration, true, index);
                }
            }
        }
    }

    pub fn writeback(&self, bodies: &mut [RigidBody], manifolds: &mut [ContactManifold<'_>]) {
        for row in &self.normals {
            let [mi, pi] = row.point;
            manifolds[mi].points[pi].applied_impulse = row.numeric.applied_impulse;
        }
        for body in &self.bodies {
            if let Some(i) = body.original {
                let state = bodies[i].snapshot();
                bodies[i].set_linear_velocity(state.linear_velocity.add(body.delta_linear));
                bodies[i].set_angular_velocity(state.angular_velocity.add(body.delta_angular));
            }
        }
    }
}

fn make_row(
    bodies: &[RigidBody],
    originals: [usize; 2],
    ids: [usize; 2],
    rel: [Vec3; 2],
    normal: Vec3,
    friction: bool,
) -> ImpulseRow {
    let [a, b] = originals.map(|i| bodies[i].snapshot());
    let angular = [rel[0].cross(normal), rel[1].cross(normal.negate())];
    let components = [
        product(
            a.inverse_inertia_world.apply(angular[0]),
            bodies[originals[0]].angular_factor(),
        ),
        product(
            b.inverse_inertia_world.apply(if friction {
                angular[1]
            } else {
                rel[1].cross(normal).negate()
            }),
            bodies[originals[1]].angular_factor(),
        ),
    ];
    let da = a.inverse_mass + normal.dot(components[0].cross(rel[0]));
    let db = b.inverse_mass + normal.dot(components[1].negate().cross(rel[1]));
    let mut row = ImpulseRow {
        bodies: ids,
        normal,
        angular,
        angular_components: components,
        diagonal_inverse: 1.0 / (da + db),
        rhs: 0.0,
        cfm: 0.0,
        lower_impulse: 0.0,
        upper_impulse: 1e10,
        applied_impulse: 0.0,
    };
    if friction {
        row.rhs = -row_velocity(
            row,
            a.linear_velocity,
            a.angular_velocity,
            b.linear_velocity,
            b.angular_velocity,
        ) * row.diagonal_inverse;
    }
    row
}

fn row_velocity(
    row: ImpulseRow,
    linear_a: Vec3,
    angular_a: Vec3,
    linear_b: Vec3,
    angular_b: Vec3,
) -> f32 {
    let va = row.normal.dot(linear_a) + row.angular[0].dot(angular_a);
    let vb = -row.normal.dot(linear_b) + row.angular[1].dot(angular_b);
    va + vb
}
