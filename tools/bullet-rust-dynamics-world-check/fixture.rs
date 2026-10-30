impl DiscreteCollisionWorld {
    pub(crate) fn fixture_activation(&mut self, i: usize, state: super::activation::ActivationState) {
        self.objects.solver_parts().1[i].activation.force_activation_state(state);
    }
    pub(crate) fn fixture_flags(&mut self, i: usize, flags: i32) {
        self.objects.fixture_flags(i, flags);
    }
    pub(crate) fn fixture_transform(&mut self, i: usize, which: &str, world: Transform) {
        if which == "current" { self.objects.solver_parts().0[i].set_world_transform(world); }
        else if which == "interpolation" { self.objects.solver_parts().0[i].set_interpolation_world_transform(world); }
        else { self.objects.fixture_motion(i, world); }
    }
    pub(crate) fn fixture_proxy(&self, i: usize) -> ProxyKey { self.proxy_by_body[i] }
    pub(crate) fn fixture_bind(&mut self, ranks: [(&[(Option<usize>, Aabb, usize)], Option<usize>); 2]) {
        self.broadphase.bind_native_address_ranks(ranks);
    }
}
impl DiscreteCollisionWorld {
    pub(crate) fn fixture_force_all(&self) -> bool { self.force_update_all_aabbs }
}
