from pathlib import Path

CORE = 'rust/crates/mds-bullet/src/core/'
NATIVE = 'recipes/bullet275/bullet-src/src/BulletCollision/CollisionDispatch/'
SHIM = 'rust/crates/mds-bullet-sys/shim/mds_bt.cpp'
OWNER = CORE + 'discrete_collision_world.rs'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def replace(root, path, old, new, changes):
    target = root / path
    before = target.read_bytes()
    ending = '\r\n' if b'\r\n' in before else '\n'
    a = old.replace('\r\n', '\n').replace('\n', ending).encode()
    b = new.replace('\r\n', '\n').replace('\n', ending).encode()
    require(before.count(a) == 1, 'one exact hook anchor: ' + path + ' ' + old[:60])
    offset = before.index(a)
    after = before[:offset] + b + before[offset + len(a):]
    require(after[:offset] + a + after[offset + len(b):] == before, 'exact hook inverse: ' + path)
    target.write_bytes(after)
    changes.append({'path': path, 'offset': offset, 'old': a.decode(), 'new': b.decode()})


def instrument(root, here):
    changes = []
    def edit(path, old, new):
        replace(root, path, old, new, changes)
    dispatcher = NATIVE + 'btCollisionDispatcher.cpp'
    edit(dispatcher, 'return m_collisionAlgorithmPoolAllocator->allocate(size);',
         'return dw_algorithm_alloc(m_collisionAlgorithmPoolAllocator->allocate(size));')
    edit(dispatcher, 'return\tbtAlignedAlloc(static_cast<size_t>(size), 16);',
         'return dw_algorithm_alloc(btAlignedAlloc(static_cast<size_t>(size), 16));')
    edit(dispatcher, 'void btCollisionDispatcher::freeCollisionAlgorithm(void* ptr)\n{',
         'void btCollisionDispatcher::freeCollisionAlgorithm(void* ptr)\n{\n\tdw_algorithm_free(ptr);')
    edit(dispatcher, '\treturn manifold;', '\tdw_manifold_alloc(manifold, b0, b1);\n\treturn manifold;')
    edit(dispatcher, 'void btCollisionDispatcher::releaseManifold(btPersistentManifold* manifold)\n{',
         'void btCollisionDispatcher::releaseManifold(btPersistentManifold* manifold)\n{\n\tdw_manifold_free(manifold);')
    edit(NATIVE + 'btCollisionWorld.cpp', 'void\tbtCollisionWorld::removeCollisionObject(btCollisionObject* collisionObject)\n{',
         'void\tbtCollisionWorld::removeCollisionObject(btCollisionObject* collisionObject)\n{\n\tdw_unregister(collisionObject);')
    edit(SHIM, '  delete b->rb;', '  dw_physical("body", b->rb);\n  delete b->rb;')
    edit(SHIM, '    delete (*it)->c;', '    dw_physical("joint", (*it)->c);\n    delete (*it)->c;')
    dispatcher = CORE + 'dispatcher.rs'
    old = 'let key = AlgorithmKey(u32::try_from(slot).expect("algorithm slot exceeds u32"));'
    edit(dispatcher, old, old + '\n            crate::observer::algorithm_alloc(key.0);')
    edit(dispatcher, '        self.manifolds.push(DispatcherManifold {',
         '        crate::observer::manifold_alloc(key.0, bodies);\n        self.manifolds.push(DispatcherManifold {')
    edit(dispatcher, '            self.manifolds[index].manifold.clear_contacts();',
         '            crate::observer::manifold_free(key.0);\n            self.manifolds[index].manifold.clear_contacts();')
    edit(dispatcher, '        self.algorithms[key.0 as usize] = None;',
         '        self.algorithms[key.0 as usize] = None;\n        crate::observer::algorithm_free(key.0);')
    edit(OWNER, '        if let Some(key) = self.proxy_by_body.pop() {',
         '        if let Some(key) = self.proxy_by_body.pop() {\n            crate::observer::unregister(self.broadphase.owner(key));')
    for path, extra in [(OWNER, 'fixture.rs'), (CORE + 'world_objects.rs', 'world_objects_fixture.rs')]:
        text = (here / extra).read_text()
        edit(path, (root / path).read_text(), (root / path).read_text() + '\n' + text)
    return changes


def inverse(root, changes, originals):
    copies = {path: (root / path).read_bytes() for path in originals}
    for change in reversed(changes):
        path, old, new = change['path'], change['old'].encode(), change['new'].encode()
        offset = change['offset']
        require(copies[path][offset:offset + len(new)] == new, 'exact inverse hook range')
        copies[path] = copies[path][:offset] + old + copies[path][offset + len(new):]
    require(copies == originals, 'full original-source inverse equality')


MUTANTS = {
    'expanded-registration': ('create_proxy(Aabb { min, max }, i, group, mask)', 'create_proxy(Aabb { min: min.sub(Vec3([0.02; 3])), max: max.add(Vec3([0.02; 3])) }, i, group, mask)'),
    'zero-margin': ('let threshold = Vec3([0.02; 3]);', 'let threshold = Vec3([0.0; 3]);'),
    'one-sided-margin': ('let min = min.sub(threshold);', 'let min = min;'),
    'interpolation-bound': ('let threshold = Vec3([0.02; 3]);', 'let (min, max) = self.objects.data()[i].shape.aabb(self.objects.bodies()[i].snapshot().interpolation_world);\n        let threshold = Vec3([0.02; 3]);'),
    'motion-bound': ('let threshold = Vec3([0.02; 3]);', 'let (min, max) = self.objects.data()[i].shape.aabb(self.objects.data()[i].motion.get_world_transform());\n        let threshold = Vec3([0.02; 3]);'),
    'default-force': ('force_update_all_aabbs: true,', 'force_update_all_aabbs: false,'),
    'ignore-inactive': ('self.force_update_all_aabbs || self.objects.objects()[i].activation.is_active()', 'true'),
    'non-static-only': ('for i in 0..self.proxy_by_body.len() {', 'for i in self.objects.non_static().to_vec() {'),
    'inclusive-huge-boundary': ('max.sub(min).length2() < 1e12', 'max.sub(min).length2() <= 1e12'),
    'kinematic-huge-exemption': ('collision_flags & 1 != 0', 'collision_flags & 3 != 0'),
    'force-disable': ('.set_activation_state(ActivationState::DisableSimulation)', '.force_activation_state(ActivationState::DisableSimulation)'),
    'omit-pair-calculation': ('broadphase.calculate_overlapping_pairs(|key| dispatcher.release(key));', ''),
    'omit-dispatch': ('dispatcher.near_pair(algorithm, keys.map(|key| owners[&key.0]), &views);', 'let _ = (algorithm, keys, &owners, &views);'),
    'recreate-dispatcher': ('broadphase.calculate_overlapping_pairs(|key| dispatcher.release(key));', 'broadphase.for_each_algorithm(|_, slot| { if let Some(key) = slot.take() { dispatcher.release(key); } });\n        *dispatcher = CollisionDispatcher::new();\n        broadphase.calculate_overlapping_pairs(|key| dispatcher.release(key));'),
    'reverse-owner-order': ('dispatcher.near_pair(algorithm, keys.map(|key| owners[&key.0]), &views);', 'dispatcher.near_pair(algorithm, [owners[&keys[1].0], owners[&keys[0].0]], &views);'),
    'reverse-dispatch-order': ('''        broadphase.for_each_algorithm(|keys, algorithm| {
            dispatcher.near_pair(algorithm, keys.map(|key| owners[&key.0]), &views);
        });''', '''        let mut ordered = Vec::new();
        broadphase.for_each_algorithm(|keys, slot| ordered.push((keys, slot.take())));
        ordered.reverse();
        for (keys, slot) in &mut ordered {
            dispatcher.near_pair(slot, keys.map(|key| owners[&key.0]), &views);
        }
        broadphase.for_each_algorithm(|keys, slot| {
            *slot = ordered.iter().find(|entry| entry.0 == keys).unwrap().1;
        });'''),
    'omit-linear-preclean': ('''            self.broadphase.for_each_algorithm(|keys, algorithm| {
                if keys.contains(&key) {
                    if let Some(live) = *algorithm {
                        self.dispatcher.release(live);
                        *algorithm = None;
                    }
                }
            });''', ''),
}


def mutate(root, name):
    changes = []
    old, new = MUTANTS[name]
    replace(root, OWNER, old, new, changes)
    return changes
