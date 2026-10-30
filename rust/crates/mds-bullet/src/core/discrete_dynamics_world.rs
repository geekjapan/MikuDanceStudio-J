//! Altered translation of Bullet 2.75's default-DBVT dynamics orchestration.
//! Public FFI adoption and CCD sweeps remain external. See mod.rs for the zlib notice.

use super::dbvt::DbvtPolicy;
use super::discrete_collision_world::DiscreteCollisionWorld;
use super::islands::{IslandConstraint, SimulationIslands, SolverEvent};
use super::math::{Transform, Vec3};
use super::solver::{solve_group, GroupSelection, SolverWorkspace, UninitializedSolverSlot};
use super::time::{Step, StepClock};
use super::world_objects::{BodyDesc, BodyHandle, JointDesc, Pose};
use super::InvalidArgument;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StepError {
    InvalidArgument,
    UninitializedSolverSlot(usize),
}

pub enum DynamicsEvent<'a> {
    Clock(Step),
    Solver(SolverEvent<'a>),
    Workspace { live: usize, capacity: usize },
}

pub struct DiscreteDynamicsWorld {
    collision: DiscreteCollisionWorld,
    clock: StepClock,
    islands: SimulationIslands,
    solver: SolverWorkspace,
}

impl DiscreteDynamicsWorld {
    pub fn public(policy: DbvtPolicy) -> Self {
        Self {
            collision: DiscreteCollisionWorld::public(policy),
            clock: StepClock::new(),
            islands: SimulationIslands::default(),
            solver: SolverWorkspace::default(),
        }
    }

    pub fn collision(&self) -> &DiscreteCollisionWorld {
        &self.collision
    }

    pub fn solver_workspace(&self) -> &SolverWorkspace {
        &self.solver
    }

    pub fn create_body(&mut self, desc: BodyDesc) -> Result<BodyHandle, InvalidArgument> {
        self.collision.create_body(desc)
    }

    pub fn create_joint(&mut self, desc: JointDesc) -> Result<usize, InvalidArgument> {
        self.collision.create_joint(desc)
    }

    pub fn public_transform(&self, body: BodyHandle) -> Result<Transform, InvalidArgument> {
        self.collision.public_transform(body)
    }

    pub fn set_public_transform(
        &mut self,
        body: BodyHandle,
        pose: Pose,
    ) -> Result<(), InvalidArgument> {
        self.collision.set_public_transform(body, pose)
    }

    pub fn set_gravity(&mut self, gravity: Vec3) -> Result<(), InvalidArgument> {
        self.collision.set_dynamics_gravity(gravity)
    }

    pub fn state_hash(&self) -> u64 {
        self.collision.objects().public_state_hash()
    }

    pub fn step_simulation(
        &mut self,
        dt: f32,
        max_substeps: i32,
        fixed: f32,
        mut observe: impl FnMut(DynamicsEvent<'_>),
    ) -> Result<i32, StepError> {
        let step = self
            .clock
            .advance(dt, max_substeps, fixed)
            .map_err(|_| StepError::InvalidArgument)?;
        observe(DynamicsEvent::Clock(step));
        if step.requested != 0 {
            self.collision.prepare_dynamics_step(step.dt);
            for _ in 0..step.executed {
                self.collision.predict_dynamics_motion(step.dt);
                self.collision.perform_discrete_collision_detection();
                self.solve_constraints(step.dt, &mut observe)?;
                self.collision
                    .finish_dynamics_substep(step.dt, step.remainder);
            }
        }
        self.collision
            .finish_dynamics_step(step.remainder, step.executed == 0);
        Ok(step.requested)
    }

    fn solve_constraints(
        &mut self,
        dt: f32,
        observe: &mut impl FnMut(DynamicsEvent<'_>),
    ) -> Result<(), StepError> {
        let (bodies, objects, joints, pairs, manifolds) = self.collision.dynamics_parts();
        let constraints: Vec<_> = joints
            .iter()
            .map(|joint| IslandConstraint {
                bodies: joint.bodies,
            })
            .collect();
        let island_manifolds: Vec<_> = manifolds.iter().map(|m| m.island_view()).collect();
        self.islands.calculate(objects, pairs, &constraints);
        let mut contacts: Vec<_> = manifolds.iter_mut().map(|m| m.contact_view()).collect();
        let workspace = &mut self.solver;
        let mut result = Ok(());
        self.islands.solve_constraints(
            objects,
            &island_manifolds,
            &constraints,
            true,
            |objects, event| {
                let group = matches!(&event, SolverEvent::SolveGroup { .. });
                if !group {
                    observe(DynamicsEvent::Solver(event));
                    return;
                }
                if let SolverEvent::SolveGroup {
                    island,
                    constraints,
                } = &event
                {
                    observe(DynamicsEvent::Solver(SolverEvent::SolveGroup {
                        island: super::islands::IslandCallback {
                            island_id: island.island_id,
                            bodies: island.bodies,
                            manifolds: island.manifolds,
                        },
                        constraints,
                    }));
                    if result.is_ok() {
                        result = solve_group(
                            workspace,
                            objects,
                            bodies,
                            joints,
                            &mut contacts,
                            GroupSelection {
                                bodies: island.bodies,
                                joints: constraints,
                                manifolds: island.manifolds,
                            },
                            dt,
                        );
                    }
                }
                observe(DynamicsEvent::Workspace {
                    live: workspace.live_len(),
                    capacity: workspace.native_capacity(),
                });
            },
        );
        result.map_err(|UninitializedSolverSlot(slot)| StepError::UninitializedSolverSlot(slot))
    }
}
