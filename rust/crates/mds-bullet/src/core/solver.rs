//! Altered Rust translation of Bullet 2.75 shared joint/contact solve groups.
//! Contact row setup lives in contact_solver; world scheduling remains external.
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
use super::contact_solver::{build_rows, ContactManifold, FrictionRow, NormalRow};
use super::islands::IslandObject;
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

/// Initialized backing slots outlive each group's native live prefix.
#[derive(Default, Debug)]
pub struct SolverWorkspace {
    slots: Vec<SolverBody>,
    live_len: usize,
    native_capacity: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct UninitializedSolverSlot(pub usize);

impl SolverWorkspace {
    pub fn live_entries(&self) -> &[SolverBody] {
        &self.slots[..self.live_len]
    }
    pub fn live_len(&self) -> usize {
        self.live_len
    }
    pub fn native_capacity(&self) -> usize {
        self.native_capacity
    }
    pub fn slot(&self, index: usize) -> Result<&SolverBody, UninitializedSolverSlot> {
        self.slots.get(index).ok_or(UninitializedSolverSlot(index))
    }
    fn append(&mut self, body: SolverBody) -> usize {
        let index = self.live_len;
        if index == self.native_capacity {
            self.slots.truncate(self.live_len);
            self.native_capacity = if index == 0 { 1 } else { 2 * index };
        }
        if index < self.slots.len() {
            self.slots[index] = body;
        } else {
            self.slots.push(body);
        }
        self.live_len += 1;
        index
    }
}

/// Ordered global registry indices, borrowed directly from island scheduling.
#[derive(Clone, Copy, Debug)]
pub struct GroupSelection<'a> {
    pub bodies: &'a [usize],
    pub joints: &'a [usize],
    pub manifolds: &'a [usize],
}

pub struct SolverBodies<'a> {
    workspace: &'a mut SolverWorkspace,
    objects: &'a mut [IslandObject],
}

impl SolverBodies<'_> {
    pub fn live_entries(&self) -> &[SolverBody] {
        self.workspace.live_entries()
    }
    pub fn live_len(&self) -> usize {
        self.workspace.live_len()
    }
    pub fn native_capacity(&self) -> usize {
        self.workspace.native_capacity()
    }
    pub fn slot(&self, index: usize) -> Result<&SolverBody, UninitializedSolverSlot> {
        self.workspace.slot(index)
    }
    pub fn companion_id(&self, original: usize) -> Option<usize> {
        usize::try_from(self.objects[original].companion_id).ok()
    }
    pub(crate) fn slot_mut(&mut self, index: usize) -> &mut SolverBody {
        self.workspace
            .slots
            .get_mut(index)
            .expect("unsupported uninitialized solver slot")
    }
    pub(crate) fn get_or_init(
        &mut self,
        bodies: &[RigidBody],
        original: usize,
    ) -> Result<usize, UninitializedSolverSlot> {
        if let Some(id) = self.companion_id(original) {
            self.workspace.slot(id)?;
            return Ok(id);
        }
        let state = bodies[original].snapshot();
        if state.inverse_mass == 0.0 {
            return Ok(0);
        }
        let id = self.workspace.append(SolverBody {
            original: Some(original),
            inverse_mass: bodies[original].linear_factor().scale(state.inverse_mass),
            angular_factor: bodies[original].angular_factor(),
            ..SolverBody::FIXED
        });
        self.objects[original].companion_id =
            i32::try_from(id).expect("solver slot exceeds native int");
        Ok(id)
    }
}

impl Drop for SolverBodies<'_> {
    fn drop(&mut self) {
        self.workspace.live_len = 0;
    }
}

impl SolverBody {
    const FIXED: Self = Self {
        original: None,
        inverse_mass: Vec3::ZERO,
        angular_factor: Vec3([1.0; 3]),
        delta_linear: Vec3::ZERO,
        delta_angular: Vec3::ZERO,
    };
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RowKind {
    Joint,
    Normal,
    Friction,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    Before,
    After,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SolveEvent {
    Row {
        kind: RowKind,
        phase: Phase,
        iteration: usize,
        index: usize,
    },
    Obsolete {
        phase: Phase,
        iteration: usize,
        joint: usize,
        bodies: [Option<usize>; 2],
    },
    FrictionSkipped {
        iteration: usize,
        index: usize,
    },
}

pub struct GroupSolver<'a, 's> {
    pub bodies: SolverBodies<'a>,
    selection: GroupSelection<'s>,
    pub joint_rows: Vec<SolverRow>,
    pub normals: Vec<NormalRow>,
    pub frictions: Vec<FrictionRow>,
    pub mode: SolverMode,
}

/// Default native mode 260, ten iterations, no transform integration.
pub fn solve_group(
    workspace: &mut SolverWorkspace,
    objects: &mut [IslandObject],
    bodies: &mut [RigidBody],
    joints: &mut [Joint],
    manifolds: &mut [ContactManifold<'_>],
    selection: GroupSelection<'_>,
    dt: f32,
) -> Result<(), UninitializedSolverSlot> {
    let mut solver = GroupSolver::setup(
        workspace,
        objects,
        bodies,
        joints,
        manifolds,
        selection,
        dt,
        SolverMode::Simd,
    )?;
    solver.iterate(bodies, joints, |_, _| {})?;
    solver.writeback(bodies, manifolds);
    Ok(())
}

pub(crate) fn product(a: Vec3, b: Vec3) -> Vec3 {
    Vec3(std::array::from_fn(|i| a.0[i] * b.0[i]))
}

impl<'a, 's> GroupSolver<'a, 's> {
    /// Requires valid body indices, finite joint inputs and positive timestep.
    /// Companion reset belongs to the native island step boundary, never a group.
    #[allow(clippy::too_many_arguments)]
    pub fn setup(
        workspace: &'a mut SolverWorkspace,
        objects: &'a mut [IslandObject],
        bodies: &[RigidBody],
        joints: &mut [Joint],
        manifolds: &mut [ContactManifold<'_>],
        selection: GroupSelection<'s>,
        dt: f32,
        mode: SolverMode,
    ) -> Result<Self, UninitializedSolverSlot> {
        assert_eq!(workspace.live_len, 0, "unfinished solver group");
        if !selection.joints.is_empty() || !selection.manifolds.is_empty() {
            workspace.append(SolverBody::FIXED);
        }
        let mut solver = Self {
            bodies: SolverBodies { workspace, objects },
            selection,
            joint_rows: Vec::new(),
            normals: Vec::new(),
            frictions: Vec::new(),
            mode,
        };
        for &index in selection.joints {
            let joint = &mut joints[index];
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
            let [a_id, b_id] = joint.bodies.map(|i| solver.bodies.get_or_init(bodies, i));
            let ids = [a_id?, b_id?];
            for id in ids {
                let body = solver.bodies.slot_mut(id);
                body.delta_linear = Vec3::ZERO;
                body.delta_angular = Vec3::ZERO;
            }
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
                solver.joint_rows.push(SolverRow {
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
        build_rows(
            bodies,
            manifolds,
            selection.manifolds,
            dt,
            &mut solver.bodies,
            &mut solver.normals,
            &mut solver.frictions,
        )?;
        Ok(solver)
    }

    /// Resolve one row in native input order. Exposed for exact event comparison.
    pub fn resolve_joint_row(&mut self, index: usize) {
        let row = &mut self.joint_rows[index];
        let mut numeric = ImpulseRow {
            bodies: row.bodies,
            normal: row.joint_row.j1_linear,
            angular: [row.joint_row.j1_angular, row.joint_row.j2_angular],
            angular_components: row.angular_components,
            diagonal_inverse: row.diagonal_inverse,
            rhs: row.rhs,
            cfm: row.joint_row.cfm,
            lower_impulse: row.joint_row.lower_impulse,
            upper_impulse: row.joint_row.upper_impulse,
            applied_impulse: row.applied_impulse,
        };
        resolve(
            &mut self.bodies.workspace.slots,
            &mut numeric,
            self.mode,
            false,
        );
        row.applied_impulse = numeric.applied_impulse;
    }

    pub fn iterate(
        &mut self,
        bodies: &[RigidBody],
        joints: &[Joint],
        mut observe: impl FnMut(&Self, SolveEvent),
    ) -> Result<(), UninitializedSolverSlot> {
        for iteration in 0..10 {
            for index in 0..self.joint_rows.len() {
                observe(
                    self,
                    SolveEvent::Row {
                        kind: RowKind::Joint,
                        phase: Phase::Before,
                        iteration,
                        index,
                    },
                );
                self.resolve_joint_row(index);
                observe(
                    self,
                    SolveEvent::Row {
                        kind: RowKind::Joint,
                        phase: Phase::After,
                        iteration,
                        index,
                    },
                );
            }
            for &joint in self.selection.joints {
                let constraint = &joints[joint];
                let ids = constraint.bodies.map(|i| {
                    self.bodies
                        .companion_id(i)
                        .or_else(|| (bodies[i].snapshot().inverse_mass == 0.0).then_some(0))
                });
                observe(
                    self,
                    SolveEvent::Obsolete {
                        phase: Phase::Before,
                        iteration,
                        joint,
                        bodies: ids,
                    },
                );
                let [a_id, b_id] = constraint
                    .bodies
                    .map(|i| self.bodies.get_or_init(bodies, i));
                let ids = [Some(a_id?), Some(b_id?)];
                observe(
                    self,
                    SolveEvent::Obsolete {
                        phase: Phase::After,
                        iteration,
                        joint,
                        bodies: ids,
                    },
                );
            }
            for index in 0..self.normals.len() {
                observe(
                    self,
                    SolveEvent::Row {
                        kind: RowKind::Normal,
                        phase: Phase::Before,
                        iteration,
                        index,
                    },
                );
                resolve(
                    &mut self.bodies.workspace.slots,
                    &mut self.normals[index].numeric,
                    self.mode,
                    true,
                );
                observe(
                    self,
                    SolveEvent::Row {
                        kind: RowKind::Normal,
                        phase: Phase::After,
                        iteration,
                        index,
                    },
                );
            }
            for index in 0..self.frictions.len() {
                let normal = self.normals[self.frictions[index].normal_index];
                if normal.numeric.applied_impulse > 0.0 {
                    let limit = normal.friction * normal.numeric.applied_impulse;
                    self.frictions[index].numeric.lower_impulse = -limit;
                    self.frictions[index].numeric.upper_impulse = limit;
                    observe(
                        self,
                        SolveEvent::Row {
                            kind: RowKind::Friction,
                            phase: Phase::Before,
                            iteration,
                            index,
                        },
                    );
                    resolve(
                        &mut self.bodies.workspace.slots,
                        &mut self.frictions[index].numeric,
                        self.mode,
                        false,
                    );
                    observe(
                        self,
                        SolveEvent::Row {
                            kind: RowKind::Friction,
                            phase: Phase::After,
                            iteration,
                            index,
                        },
                    );
                } else {
                    observe(self, SolveEvent::FrictionSkipped { iteration, index });
                }
            }
        }
        Ok(())
    }

    pub fn writeback(self, bodies: &mut [RigidBody], manifolds: &mut [ContactManifold<'_>]) {
        for row in &self.normals {
            let [mi, pi] = row.point;
            manifolds[mi].points[pi].applied_impulse = row.numeric.applied_impulse;
        }
        for solver_body in self.bodies.live_entries() {
            if let Some(i) = solver_body.original {
                let state = bodies[i].snapshot();
                bodies[i].set_linear_velocity(state.linear_velocity.add(solver_body.delta_linear));
                bodies[i]
                    .set_angular_velocity(state.angular_velocity.add(solver_body.delta_angular));
            }
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ImpulseRow {
    pub bodies: [usize; 2],
    pub normal: Vec3,
    pub angular: [Vec3; 2],
    pub angular_components: [Vec3; 2],
    pub diagonal_inverse: f32,
    pub rhs: f32,
    pub cfm: f32,
    pub lower_impulse: f32,
    pub upper_impulse: f32,
    pub applied_impulse: f32,
}

pub(crate) fn resolve(
    bodies: &mut [SolverBody],
    row: &mut ImpulseRow,
    mode: SolverMode,
    lower_only: bool,
) {
    let [a, b] = row.bodies.map(|i| bodies[i]);
    let j = *row;
    let (va, vb) = match mode {
        SolverMode::Simd => (
            j.normal.dot_sse(a.delta_linear) + j.angular[0].dot_sse(a.delta_angular),
            j.angular[1].dot_sse(b.delta_angular) - j.normal.dot_sse(b.delta_linear),
        ),
        SolverMode::Scalar => (
            j.normal.dot(a.delta_linear) + j.angular[0].dot(a.delta_angular),
            -j.normal.dot(b.delta_linear) + j.angular[1].dot(b.delta_angular),
        ),
    };
    let mut impulse = row.rhs - row.applied_impulse * j.cfm;
    impulse -= va * row.diagonal_inverse;
    impulse -= vb * row.diagonal_inverse;
    let old_impulse = row.applied_impulse;
    let sum = old_impulse + impulse;
    if sum < j.lower_impulse {
        impulse = j.lower_impulse - row.applied_impulse;
        row.applied_impulse = j.lower_impulse;
    } else if !lower_only && mode == SolverMode::Scalar && sum > j.upper_impulse {
        impulse = j.upper_impulse - row.applied_impulse;
        row.applied_impulse = j.upper_impulse;
    } else {
        row.applied_impulse = sum;
    }
    // Native SIMD applies both masks to the original sum; the upper mask wins.
    if !lower_only
        && mode == SolverMode::Simd
        && sum.partial_cmp(&j.upper_impulse) != Some(std::cmp::Ordering::Less)
    {
        impulse = j.upper_impulse - old_impulse;
        row.applied_impulse = j.upper_impulse;
    }
    let [ia, ib] = row.bodies;
    let linear_a = product(j.normal, a.inverse_mass);
    let linear_b = product(j.normal, b.inverse_mass);
    bodies[ia].delta_linear = bodies[ia].delta_linear.add(linear_a.scale(impulse));
    let angular_a = match mode {
        SolverMode::Simd => row.angular_components[0].scale(impulse),
        SolverMode::Scalar => product(row.angular_components[0], a.angular_factor.scale(impulse)),
    };
    bodies[ia].delta_angular = bodies[ia].delta_angular.add(angular_a);
    bodies[ib].delta_linear = match mode {
        SolverMode::Simd => bodies[ib].delta_linear.sub(linear_b.scale(impulse)),
        SolverMode::Scalar => bodies[ib]
            .delta_linear
            .add(product(j.normal.negate(), b.inverse_mass).scale(impulse)),
    };
    let angular_b = match mode {
        SolverMode::Simd => row.angular_components[1].scale(impulse),
        SolverMode::Scalar => product(row.angular_components[1], b.angular_factor.scale(impulse)),
    };
    bodies[ib].delta_angular = bodies[ib].delta_angular.add(angular_b);
}
