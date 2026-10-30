impl MmdCollisionWorld {
    pub(crate) fn fixture_dynamics(&mut self, i: usize, op: &str, a: Vec3, b: Vec3) {
        let bodies = self.objects.solver_parts().0;
        if op == "L" { bodies[i].set_linear_velocity(a); bodies[i].set_angular_velocity(b); }
        else { bodies[i].add_force(a); bodies[i].add_torque(b); }
    }
    pub(crate) fn fixture_sweep(&self) -> &AxisSweep32 { &self.collision.sweep }
    pub(crate) fn fixture_proxy(&self, i: usize) -> ProxyKey { self.collision.proxy_by_body[i] }
    pub(crate) fn fixture_activation(&mut self, i: usize, state: ActivationState) {
        self.objects.solver_parts().1[i].activation.force_activation_state(state);
    }
    pub(crate) fn fixture_velocities(&mut self, i: usize, linear: Vec3, angular: Vec3) {
        self.objects.solver_parts().0[i].set_interpolation_velocities(linear, angular);
    }
    pub(crate) fn fixture_warmstart(&mut self) {
        for m in self.collision.dispatcher.manifolds_mut() {
            for p in m.manifold.contacts_mut() {
                p.applied_impulse = 1.25;
                p.lateral_impulses = [0.5, -0.25];
                p.lateral_initialized = true;
                p.lateral_directions = [Vec3([1.0, 0.0, 0.0]), Vec3([0.0, 0.0, 1.0])];
            }
        }
    }
}
