//! Altered translation of the MMD shim's Bullet 2.75 dynamics orchestration.
//! Native dynamics parity and public adoption remain external. See mod.rs for the zlib notice.

use super::discrete_dynamics_world::{DynamicsEvent, StepError};
use super::islands::{IslandConstraint, SimulationIslands, SolverEvent};
use super::math::{Transform, Vec3};
use super::mmd_collision_world::MmdCollisionWorld;
use super::solver::{solve_group, GroupSelection, SolverWorkspace, UninitializedSolverSlot};
use super::time::StepClock;
use super::world_objects::{BodyDesc, BodyHandle, JointDesc};
use super::InvalidArgument;

pub(crate) struct MmdDynamicsWorld {
    collision: MmdCollisionWorld,
    clock: StepClock,
    islands: SimulationIslands,
    solver: SolverWorkspace,
}

impl MmdDynamicsWorld {
    pub(crate) fn new() -> Self {
        Self {
            collision: MmdCollisionWorld::new(),
            clock: StepClock::new(),
            islands: SimulationIslands::default(),
            solver: SolverWorkspace::default(),
        }
    }

    pub(crate) fn collision(&self) -> &MmdCollisionWorld {
        &self.collision
    }

    pub(crate) fn solver_workspace(&self) -> &SolverWorkspace {
        &self.solver
    }

    pub(crate) fn create_body(
        &mut self,
        desc: BodyDesc,
        mode: i32,
    ) -> Result<BodyHandle, InvalidArgument> {
        self.collision.create_body(desc, mode)
    }

    pub(crate) fn create_joint(
        &mut self,
        desc: JointDesc,
        uid: i32,
    ) -> Result<usize, InvalidArgument> {
        self.collision.create_joint(desc, uid)
    }

    pub(crate) fn set_floor(&mut self, on: bool) -> Result<(), InvalidArgument> {
        self.collision.set_floor(on)
    }

    pub(crate) fn set_kinematic(
        &mut self,
        body: BodyHandle,
        on: bool,
    ) -> Result<(), InvalidArgument> {
        self.collision.set_kinematic(body, on)
    }

    pub(crate) fn set_motion_state(
        &mut self,
        body: BodyHandle,
        world: Transform,
    ) -> Result<(), InvalidArgument> {
        self.collision.set_motion_state(body, world)
    }

    pub(crate) fn reseat(
        &mut self,
        body: BodyHandle,
        world: Transform,
    ) -> Result<(), InvalidArgument> {
        self.collision.reseat(body, world)
    }

    pub(crate) fn stop_at(
        &mut self,
        body: BodyHandle,
        origin: Vec3,
    ) -> Result<(), InvalidArgument> {
        self.collision.stop_at(body, origin)
    }

    pub(crate) fn set_gravity(&mut self, gravity: Vec3) -> Result<(), InvalidArgument> {
        self.collision.set_dynamics_gravity(gravity)
    }

    pub(crate) fn step_simulation(
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
