impl MmdDynamicsWorld {
    pub(crate) fn objects(&self) -> &super::world_objects::WorldObjects { self.collision.objects() }
    pub(crate) fn manifolds(&self) -> &[super::dispatcher::DispatcherManifold] { self.collision.manifolds() }
    pub(crate) fn fixture_sweep(&self) -> &super::axis_sweep::AxisSweep32 { self.collision.fixture_sweep() }
    pub(crate) fn fixture_proxy(&self, i: usize) -> super::pair_cache::ProxyKey { self.collision.fixture_proxy(i) }
    pub(crate) fn perform_discrete_collision_detection(&mut self) { self.collision.perform_discrete_collision_detection(); }
    pub(crate) fn update_aabbs(&mut self) { self.collision.update_aabbs(); }
    pub(crate) fn update_single_aabb(&mut self, body: BodyHandle) -> Result<(), InvalidArgument> { self.collision.update_single_aabb(body) }
    pub(crate) fn fixture_activation(&mut self, i: usize, state: super::activation::ActivationState) { self.collision.fixture_activation(i, state); }
    pub(crate) fn fixture_velocities(&mut self, i: usize, linear: Vec3, angular: Vec3) { self.collision.fixture_velocities(i, linear, angular); }
    pub(crate) fn fixture_warmstart(&mut self) { self.collision.fixture_warmstart(); }
    pub(crate) fn fixture_dynamics(&mut self, i: usize, op: &str, a: Vec3, b: Vec3) { self.collision.fixture_dynamics(i, op, a, b); }
}
