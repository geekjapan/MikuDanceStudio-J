impl WorldObjects {
    pub(crate) fn fixture_flags(&mut self, i: usize, flags: i32) { self.set_flags(i, flags); }
    pub(crate) fn fixture_motion(&mut self, i: usize, world: Transform) { self.data[i].motion.set_world_transform(world); }
}
