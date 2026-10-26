//! Altered Rust translation of Bullet 2.75's joint-only sequential impulse solver.
//! Contacts, friction, islands and transform integration are outside this kernel.
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

use super::body::RigidBody;
use super::joint_coordinates::calculate_coordinates;
use super::joint_rows::{generate_rows, JointBodySnapshot, JointRow, JointState, JointStep};
use super::math::{Transform, Vec3};

/// Body indices refer to the slice passed to setup. Frames are body-local.
#[derive(Clone, Debug)]
pub struct Joint {
    pub bodies: [usize; 2],
    pub frames: [Transform; 2],
    pub state: JointState,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SolverMode {
    Simd,
    Scalar,
}

#[derive(Clone, Copy, Debug)]
pub struct SolverBody {
    pub original: Option<usize>,
    pub inverse_mass: Vec3,
    pub angular_factor: Vec3,
    pub delta_linear: Vec3,
    pub delta_angular: Vec3,
}

#[derive(Clone, Copy, Debug)]
pub struct SolverRow {
    pub bodies: [usize; 2],
    pub joint_row: JointRow,
    pub angular_components: [Vec3; 2],
    pub diagonal_inverse: f32,
    pub rhs: f32,
    pub applied_impulse: f32,
}

pub struct JointSolver {
    pub bodies: Vec<SolverBody>,
    pub rows: Vec<SolverRow>,
    mode: SolverMode,
    callback_bodies: Vec<SolverBody>,
}

fn product(a: Vec3, b: Vec3) -> Vec3 {
    Vec3(std::array::from_fn(|i| a.0[i] * b.0[i]))
}

impl JointSolver {
    /// Requires valid body indices, finite joint inputs and positive timestep.
    /// Every solve starts fresh: no joint warmstarting or retained companion IDs.
    pub fn setup(bodies: &[RigidBody], joints: &mut [Joint], dt: f32, mode: SolverMode) -> Self {
        let fixed = SolverBody {
            original: None,
            inverse_mass: Vec3::ZERO,
            angular_factor: Vec3([1.0; 3]),
            delta_linear: Vec3::ZERO,
            delta_angular: Vec3::ZERO,
        };
        let mut solver = Self {
            bodies: vec![fixed],
            rows: Vec::new(),
            mode,
            callback_bodies: Vec::new(),
        };
        let mut slots = vec![None; bodies.len()];
        for joint in joints.iter_mut() {
            let [a, b] = joint.bodies.map(|i| bodies[i].snapshot());
            let coordinates =
                calculate_coordinates(a.world, b.world, joint.frames[0], joint.frames[1]);
            let rows = generate_rows(
                coordinates.coordinates,
                [a, b].map(|body| JointBodySnapshot {
                    origin: body.world.origin,
                    linear_velocity: body.linear_velocity,
                    angular_velocity: body.angular_velocity,
                }),
                JointStep {
                    fps: 1.0 / dt,
                    erp: 0.2,
                    iterations: 10,
                },
                &mut joint.state,
            );
            if rows.as_slice().is_empty() {
                continue;
            }
            let ids = joint.bodies.map(|i| {
                if bodies[i].snapshot().inverse_mass == 0.0 {
                    return 0;
                }
                *slots[i].get_or_insert_with(|| {
                    let slot = solver.bodies.len();
                    solver.bodies.push(SolverBody {
                        original: Some(i),
                        inverse_mass: bodies[i]
                            .linear_factor()
                            .scale(bodies[i].snapshot().inverse_mass),
                        angular_factor: bodies[i].angular_factor(),
                        ..fixed
                    });
                    slot
                })
            });
            for &row in rows.as_slice() {
                let n = row.j1_linear;
                let ia = a.inverse_inertia_world.apply(row.j1_angular);
                let ib = b.inverse_inertia_world.apply(row.j2_angular);
                let mut diagonal = n.scale(a.inverse_mass).dot(n);
                diagonal += ia.dot(row.j1_angular);
                diagonal += n.scale(b.inverse_mass).dot(n);
                diagonal += ib.dot(row.j2_angular);
                let diagonal_inverse = 1.0 / diagonal;
                let velocity_a = n.dot(a.linear_velocity) + row.j1_angular.dot(a.angular_velocity);
                let velocity_b = -n.dot(b.linear_velocity) + row.j2_angular.dot(b.angular_velocity);
                let velocity_error = 0.0 - (velocity_a + velocity_b);
                solver.rows.push(SolverRow {
                    bodies: ids,
                    joint_row: row,
                    angular_components: [
                        product(ia, bodies[joint.bodies[0]].angular_factor()),
                        product(ib, bodies[joint.bodies[1]].angular_factor()),
                    ],
                    diagonal_inverse,
                    rhs: row.positional_rhs * diagonal_inverse + velocity_error * diagonal_inverse,
                    applied_impulse: 0.0,
                });
            }
        }
        // Obsolete callbacks are no-ops, but native allocates their bodies even
        // for zero-row joints after the first iteration.
        for joint in joints {
            for i in joint.bodies {
                if bodies[i].snapshot().inverse_mass != 0.0 && slots[i].is_none() {
                    slots[i] = Some(solver.bodies.len() + solver.callback_bodies.len());
                    solver.callback_bodies.push(SolverBody {
                        original: Some(i),
                        inverse_mass: bodies[i]
                            .linear_factor()
                            .scale(bodies[i].snapshot().inverse_mass),
                        angular_factor: bodies[i].angular_factor(),
                        ..fixed
                    });
                }
            }
        }
        solver
    }

    /// Resolve one row in native input order. Exposed for exact event comparison.
    pub fn resolve_row(&mut self, index: usize) {
        let row = &mut self.rows[index];
        let [a, b] = row.bodies.map(|i| self.bodies[i]);
        let j = row.joint_row;
        let (va, vb) = match self.mode {
            SolverMode::Simd => (
                j.j1_linear.dot_sse(a.delta_linear) + j.j1_angular.dot_sse(a.delta_angular),
                j.j2_angular.dot_sse(b.delta_angular) - j.j1_linear.dot_sse(b.delta_linear),
            ),
            SolverMode::Scalar => (
                j.j1_linear.dot(a.delta_linear) + j.j1_angular.dot(a.delta_angular),
                -j.j1_linear.dot(b.delta_linear) + j.j2_angular.dot(b.delta_angular),
            ),
        };
        let mut impulse = row.rhs - row.applied_impulse * j.cfm;
        impulse -= va * row.diagonal_inverse;
        impulse -= vb * row.diagonal_inverse;
        let sum = row.applied_impulse + impulse;
        if sum < j.lower_impulse {
            impulse = j.lower_impulse - row.applied_impulse;
            row.applied_impulse = j.lower_impulse;
        } else if (self.mode == SolverMode::Simd && sum >= j.upper_impulse)
            || (self.mode == SolverMode::Scalar && sum > j.upper_impulse)
        {
            impulse = j.upper_impulse - row.applied_impulse;
            row.applied_impulse = j.upper_impulse;
        } else {
            row.applied_impulse = sum;
        }
        let [ia, ib] = row.bodies;
        let linear_a = product(j.j1_linear, a.inverse_mass);
        let linear_b = product(j.j1_linear, b.inverse_mass);
        self.bodies[ia].delta_linear = self.bodies[ia].delta_linear.add(linear_a.scale(impulse));
        let angular_a = match self.mode {
            SolverMode::Simd => row.angular_components[0].scale(impulse),
            SolverMode::Scalar => {
                product(row.angular_components[0], a.angular_factor.scale(impulse))
            }
        };
        self.bodies[ia].delta_angular = self.bodies[ia].delta_angular.add(angular_a);
        self.bodies[ib].delta_linear = match self.mode {
            SolverMode::Simd => self.bodies[ib].delta_linear.sub(linear_b.scale(impulse)),
            SolverMode::Scalar => self.bodies[ib]
                .delta_linear
                .add(product(j.j1_linear.negate(), b.inverse_mass).scale(impulse)),
        };
        let angular_b = match self.mode {
            SolverMode::Simd => row.angular_components[1].scale(impulse),
            SolverMode::Scalar => {
                product(row.angular_components[1], b.angular_factor.scale(impulse))
            }
        };
        self.bodies[ib].delta_angular = self.bodies[ib].delta_angular.add(angular_b);
    }

    pub fn iterate(&mut self) {
        self.iterate_with_observer(|_, _, _| {});
    }

    /// Observe completed row events without changing the fixed iteration count.
    pub fn iterate_with_observer(&mut self, mut observe: impl FnMut(&Self, usize, usize)) {
        for iteration in 0..10 {
            for index in 0..self.rows.len() {
                self.resolve_row(index);
                observe(self, iteration, index);
            }
            self.bodies.append(&mut self.callback_bodies);
        }
    }

    pub fn writeback(&self, bodies: &mut [RigidBody]) {
        for solver_body in &self.bodies {
            if let Some(i) = solver_body.original {
                let state = bodies[i].snapshot();
                bodies[i].set_linear_velocity(state.linear_velocity.add(solver_body.delta_linear));
                bodies[i]
                    .set_angular_velocity(state.angular_velocity.add(solver_body.delta_angular));
            }
        }
    }
}
