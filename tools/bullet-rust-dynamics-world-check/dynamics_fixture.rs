impl DiscreteDynamicsWorld {
    pub(crate) fn fixture_activation(&mut self, i: usize, state: super::activation::ActivationState) {
        self.collision.fixture_activation(i, state);
    }
    pub(crate) fn fixture_flags(&mut self, i: usize, flags: i32) {
        self.collision.fixture_flags(i, flags);
    }
    pub(crate) fn fixture_transform(&mut self, i: usize, which: &str, transform: Transform) {
        self.collision.fixture_transform(i, which, transform);
    }
    pub(crate) fn fixture_proxy(&self, i: usize) -> super::pair_cache::ProxyKey {
        self.collision.fixture_proxy(i)
    }
    pub(crate) fn fixture_bind(&mut self, ranks: [(&[(Option<usize>, super::dbvt::Aabb, usize)], Option<usize>); 2]) {
        self.collision.fixture_bind(ranks);
    }
    pub(crate) fn fixture_force_all(&self) -> bool { self.collision.fixture_force_all() }
    pub(crate) fn fixture_force_all_set(&mut self, value: bool) { self.collision.set_force_update_all_aabbs(value); }
    pub(crate) fn fixture_detect(&mut self) { self.collision.perform_discrete_collision_detection(); }
    pub(crate) fn fixture_update(&mut self) { self.collision.update_aabbs(); }
    pub(crate) fn fixture_single(&mut self, body: BodyHandle) -> Result<(), InvalidArgument> { self.collision.update_single_aabb(body) }
    pub(crate) fn fixture_dynamics(&mut self, i: usize, op: &str, a: Vec3, b: Vec3) {
        let (bodies, ..) = self.collision.dynamics_parts();
        if op == "L" { bodies[i].set_linear_velocity(a); bodies[i].set_angular_velocity(b); }
        else { bodies[i].add_force(a); bodies[i].add_torque(b); }
    }
}
