//! Altered translation of Bullet 2.75's default-DBVT collision-world ownership.
//! Solver stepping and the public FFI remain external. See mod.rs for the zlib notice.

use std::collections::BTreeMap;

use super::activation::{ActivationState, DeactivationSettings};
use super::body::RigidBody;
use super::dbvt::{Aabb, DbvtPolicy};
use super::dbvt_broadphase::DbvtBroadphase;
use super::dispatcher::{CollisionDispatcher, DispatcherManifold};
use super::islands::IslandObject;
use super::math::{Transform, Vec3};
use super::pair_cache::ProxyKey;
use super::solver::Joint;
use super::world_objects::{BodyDesc, BodyHandle, JointDesc, Pose, WorldObjects};
use super::InvalidArgument;

pub struct DiscreteCollisionWorld {
    objects: WorldObjects,
    broadphase: DbvtBroadphase,
    proxy_by_body: Vec<ProxyKey>,
    dispatcher: CollisionDispatcher,
    force_update_all_aabbs: bool,
}

impl DiscreteCollisionWorld {
    pub fn public(policy: DbvtPolicy) -> Self {
        Self {
            objects: WorldObjects::public(),
            broadphase: DbvtBroadphase::new(policy),
            proxy_by_body: Vec::new(),
            dispatcher: CollisionDispatcher::new(),
            force_update_all_aabbs: true,
        }
    }

    pub fn objects(&self) -> &WorldObjects {
        &self.objects
    }

    pub fn broadphase(&self) -> &DbvtBroadphase {
        &self.broadphase
    }

    pub fn manifolds(&self) -> &[DispatcherManifold] {
        self.dispatcher.manifolds()
    }

    pub(crate) fn dynamics_parts(
        &mut self,
    ) -> (
        &mut [RigidBody],
        &mut [IslandObject],
        &mut [Joint],
        impl Iterator<Item = [usize; 2]> + '_,
        &mut [DispatcherManifold],
    ) {
        let (bodies, objects, joints) = self.objects.solver_parts();
        let broadphase = &self.broadphase;
        (
            bodies,
            objects,
            joints,
            broadphase
                .pairs()
                .iter()
                .map(move |pair| pair.proxies.map(|key| broadphase.owner(key))),
            self.dispatcher.manifolds_mut(),
        )
    }

    pub(crate) fn prepare_dynamics_step(&mut self, dt: f32) {
        self.objects.save_kinematic_state(dt);
        self.objects.apply_gravity();
    }

    pub(crate) fn predict_dynamics_motion(&mut self, dt: f32) {
        self.objects.predict_unconstraint_motion(dt);
    }

    pub(crate) fn finish_dynamics_substep(&mut self, dt: f32, remainder: f32) {
        self.objects.integrate_transforms(dt);
        self.objects
            .update_activation_state(dt, DeactivationSettings::default());
        self.objects.synchronize_motion_states(remainder, false);
    }

    pub(crate) fn finish_dynamics_step(&mut self, remainder: f32, synchronize: bool) {
        if synchronize {
            self.objects.synchronize_motion_states(remainder, false);
        }
        self.objects.clear_forces();
    }

    pub(crate) fn set_dynamics_gravity(&mut self, gravity: Vec3) -> Result<(), InvalidArgument> {
        self.objects.set_gravity(gravity)
    }

    pub fn create_body(&mut self, desc: BodyDesc) -> Result<BodyHandle, InvalidArgument> {
        let handle = self.objects.create_public_body(desc)?;
        let i = self.objects.index(handle)?;
        let (min, max) = self.objects.data()[i]
            .shape
            .aabb(self.objects.bodies()[i].snapshot().world);
        let [group, mask] = self.objects.data()[i].filter;
        self.proxy_by_body.push(
            self.broadphase
                .create_proxy(Aabb { min, max }, i, group, mask),
        );
        Ok(handle)
    }

    pub fn create_joint(&mut self, desc: JointDesc) -> Result<usize, InvalidArgument> {
        self.objects.create_joint(desc, None)
    }

    pub fn public_transform(&self, body: BodyHandle) -> Result<Transform, InvalidArgument> {
        self.objects.public_transform(body)
    }

    pub fn set_public_transform(
        &mut self,
        body: BodyHandle,
        pose: Pose,
    ) -> Result<(), InvalidArgument> {
        self.objects.set_public_transform(body, pose)
    }

    pub fn set_force_update_all_aabbs(&mut self, force: bool) {
        self.force_update_all_aabbs = force;
    }

    pub fn update_single_aabb(&mut self, body: BodyHandle) -> Result<(), InvalidArgument> {
        let i = self.objects.index(body)?;
        self.update_aabb_at(i);
        Ok(())
    }

    fn update_aabb_at(&mut self, i: usize) {
        let (min, max) = self.objects.data()[i]
            .shape
            .aabb(self.objects.bodies()[i].snapshot().world);
        let threshold = Vec3([0.02; 3]);
        let min = min.sub(threshold);
        let max = max.add(threshold);
        if self.objects.data()[i].collision_flags & 1 != 0 || max.sub(min).length2() < 1e12 {
            self.broadphase
                .set_aabb(self.proxy_by_body[i], Aabb { min, max });
        } else {
            self.objects.solver_parts().1[i]
                .activation
                .set_activation_state(ActivationState::DisableSimulation);
        }
    }

    pub fn update_aabbs(&mut self) {
        for i in 0..self.proxy_by_body.len() {
            if self.force_update_all_aabbs || self.objects.objects()[i].activation.is_active() {
                self.update_aabb_at(i);
            }
        }
    }

    pub fn perform_discrete_collision_detection(&mut self) {
        self.update_aabbs();
        let Self {
            objects,
            broadphase,
            dispatcher,
            ..
        } = self;
        broadphase.calculate_overlapping_pairs(|key| dispatcher.release(key));
        let owners: BTreeMap<_, _> = broadphase
            .pairs()
            .iter()
            .flat_map(|pair| pair.proxies)
            .map(|key| (key.0, broadphase.owner(key)))
            .collect();
        let views = objects.dispatch_objects();
        broadphase.for_each_algorithm(|keys, algorithm| {
            dispatcher.near_pair(algorithm, keys.map(|key| owners[&key.0]), &views);
        });
    }

    fn unregister_last_proxy(&mut self) {
        if let Some(key) = self.proxy_by_body.pop() {
            // Native cleanProxyFromPairs releases in cache order before swap-removal.
            self.broadphase.for_each_algorithm(|keys, algorithm| {
                if keys.contains(&key) {
                    if let Some(live) = *algorithm {
                        self.dispatcher.release(live);
                        *algorithm = None;
                    }
                }
            });
            self.broadphase
                .destroy_proxy(key, |live| self.dispatcher.release(live));
        }
    }
}

impl Drop for DiscreteCollisionWorld {
    fn drop(&mut self) {
        while !self.proxy_by_body.is_empty() {
            self.unregister_last_proxy();
        }
    }
}
