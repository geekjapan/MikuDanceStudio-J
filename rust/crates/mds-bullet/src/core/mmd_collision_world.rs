//! Altered translation of the MMD shim's Bullet 2.75 collision ownership.
//! Dynamics stepping and public adoption remain external. See mod.rs for the zlib notice.

use std::collections::BTreeMap;

use super::activation::ActivationState;
use super::axis_sweep::AxisSweep32;
use super::dispatcher::{CollisionDispatcher, DispatcherManifold};
use super::math::{Transform, Vec3};
use super::pair_cache::ProxyKey;
use super::world_objects::{BodyDesc, BodyHandle, JointDesc, WorldObjects};
use super::InvalidArgument;

pub(crate) struct MmdCollisionWorld {
    objects: WorldObjects,
    collision: MmdCollisionState,
}

struct MmdCollisionState {
    sweep: AxisSweep32,
    proxy_by_body: Vec<ProxyKey>,
    dispatcher: CollisionDispatcher,
}

impl MmdCollisionWorld {
    pub(crate) fn new() -> Self {
        let objects = WorldObjects::mmd();
        let mut collision = MmdCollisionState {
            sweep: AxisSweep32::new_mmd(),
            proxy_by_body: Vec::new(),
            dispatcher: CollisionDispatcher::new(),
        };
        collision.register(&objects, 0);
        Self { objects, collision }
    }

    pub(crate) fn objects(&self) -> &WorldObjects {
        &self.objects
    }

    pub(crate) fn manifolds(&self) -> &[DispatcherManifold] {
        self.collision.dispatcher.manifolds()
    }

    pub(crate) fn create_body(
        &mut self,
        desc: BodyDesc,
        mode: i32,
    ) -> Result<BodyHandle, InvalidArgument> {
        let body = self.objects.create_mmd_body(desc, mode)?;
        let i = self.objects.index(body)?;
        self.collision.register(&self.objects, i);
        Ok(body)
    }

    pub(crate) fn create_joint(
        &mut self,
        desc: JointDesc,
        uid: i32,
    ) -> Result<usize, InvalidArgument> {
        self.objects.create_joint(desc, Some(uid))
    }

    pub(crate) fn set_floor(&mut self, on: bool) -> Result<(), InvalidArgument> {
        self.objects.set_floor(on)
    }

    pub(crate) fn set_kinematic(
        &mut self,
        body: BodyHandle,
        on: bool,
    ) -> Result<(), InvalidArgument> {
        self.objects.set_kinematic(body, on)
    }

    pub(crate) fn set_motion_state(
        &mut self,
        body: BodyHandle,
        world: Transform,
    ) -> Result<(), InvalidArgument> {
        self.objects.set_motion_state(body, world)
    }

    pub(crate) fn reseat(
        &mut self,
        body: BodyHandle,
        world: Transform,
    ) -> Result<(), InvalidArgument> {
        self.objects.reseat(body, world)
    }

    pub(crate) fn stop_at(
        &mut self,
        body: BodyHandle,
        origin: Vec3,
    ) -> Result<(), InvalidArgument> {
        self.objects.stop_at(body, origin)
    }

    pub(crate) fn update_single_aabb(&mut self, body: BodyHandle) -> Result<(), InvalidArgument> {
        let i = self.objects.index(body)?;
        self.collision.update_aabb_at(&mut self.objects, i);
        Ok(())
    }

    pub(crate) fn update_aabbs(&mut self) {
        for i in 0..self.collision.proxy_by_body.len() {
            self.collision.update_aabb_at(&mut self.objects, i);
        }
    }

    pub(crate) fn perform_discrete_collision_detection(&mut self) {
        self.update_aabbs();
        self.collision.detect(&self.objects);
    }
}

impl MmdCollisionState {
    fn register(&mut self, objects: &WorldObjects, i: usize) {
        let (min, max) = objects.data()[i]
            .shape
            .aabb(objects.bodies()[i].snapshot().world);
        let [group, mask] = objects.data()[i].filter;
        self.proxy_by_body
            .push(self.sweep.add(min, max, i, group, mask, 0));
    }

    fn update_aabb_at(&mut self, objects: &mut WorldObjects, i: usize) {
        let (min, max) = objects.data()[i]
            .shape
            .aabb(objects.bodies()[i].snapshot().world);
        let threshold = Vec3([0.02; 3]);
        let min = min.sub(threshold);
        let max = max.add(threshold);
        if objects.data()[i].collision_flags & 1 != 0 || max.sub(min).length2() < 1e12 {
            let dispatcher = &mut self.dispatcher;
            self.sweep.update(self.proxy_by_body[i], min, max, |key| {
                dispatcher.release(key);
            });
        } else {
            objects.solver_parts().1[i]
                .activation
                .set_activation_state(ActivationState::DisableSimulation);
        }
    }

    fn detect(&mut self, objects: &WorldObjects) {
        self.sweep.calculate_overlapping_pairs();
        let owners: BTreeMap<_, _> = self
            .sweep
            .pairs()
            .iter()
            .flat_map(|pair| pair.proxies)
            .map(|key| (key.0, self.sweep.handle(key).unwrap().owner))
            .collect();
        let views = objects.dispatch_objects();
        let dispatcher = &mut self.dispatcher;
        self.sweep.for_each_algorithm(|keys, algorithm| {
            dispatcher.near_pair(algorithm, keys.map(|key| owners[&key.0]), &views);
        });
    }

    fn unregister_last_proxy(&mut self) {
        if let Some(key) = self.proxy_by_body.pop() {
            let dispatcher = &mut self.dispatcher;
            // Native cleanProxyFromPairs releases in cache order before swap-removal.
            self.sweep.for_each_algorithm(|keys, algorithm| {
                if keys.contains(&key) {
                    if let Some(live) = algorithm.take() {
                        dispatcher.release(live);
                    }
                }
            });
            self.sweep.remove(key, |live| dispatcher.release(live));
        }
    }
}

impl Drop for MmdCollisionWorld {
    fn drop(&mut self) {
        while !self.collision.proxy_by_body.is_empty() {
            self.collision.unregister_last_proxy();
        }
    }
}
