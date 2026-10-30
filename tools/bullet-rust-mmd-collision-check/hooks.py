"""Observation edits apply only to generated copies and have exact byte inverses."""
CORE = 'rust/crates/mds-bullet/src/core/'
OWNER = CORE + 'mmd_collision_world.rs'
SHIM = 'rust/crates/mds-bullet-sys/shim/mds_mmd.cpp'
NATIVE = 'recipes/bullet275/bullet-src/src/'
DISPATCHER = NATIVE + 'BulletCollision/CollisionDispatch/btCollisionDispatcher.cpp'
WORLD = NATIVE + 'BulletCollision/CollisionDispatch/btCollisionWorld.cpp'
SAP = NATIVE + 'BulletCollision/BroadphaseCollision/btAxisSweep3.h'
SPRING = NATIVE + 'BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h'
ALLOCATOR = NATIVE + 'LinearMath/btAlignedAllocator.cpp'
OBSERVATION_PATHS = (OWNER, CORE + 'dispatcher.rs', SHIM, DISPATCHER, WORLD, SAP, SPRING, ALLOCATOR)
NATIVE_OBSERVATIONS = (DISPATCHER, WORLD, ALLOCATOR)
DYNAMICS = CORE + 'mmd_dynamics_world.rs'
DYNAMIC_NATIVE = NATIVE + 'BulletDynamics/Dynamics/btDiscreteDynamicsWorld.cpp'
SOLVER_NATIVE = NATIVE + 'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp'


def observation_paths(dynamics=False):
    return OBSERVATION_PATHS + ((DYNAMICS, DYNAMIC_NATIVE, SOLVER_NATIVE) if dynamics else ())


def native_observations(dynamics=False):
    return NATIVE_OBSERVATIONS + ((DYNAMIC_NATIVE, SOLVER_NATIVE) if dynamics else ())


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


def instrument(root, here, dynamics=False):
    changes = []
    def edit(path, old, new):
        replace(root, path, old, new, changes)
    edit(SAP, '\tBP_FP_INT_TYPE getNumHandles() const',
         '\tconst Edge* mdsEdges(int axis) const { return m_pEdges[axis]; }\n'
         '\tbool mdsAcceleratorEnabled() const { return m_raycastAccelerator != 0 && m_nullPairCache != 0; }\n'
         '\tBP_FP_INT_TYPE getNumHandles() const')
    edit(SPRING, '    btGeneric6DofSpringConstraint(btRigidBody& rbA,',
         '    bool mdsEnabled(int i) const { return m_springEnabled[i]; }\n'
         '    btScalar mdsStiffness(int i) const { return m_springStiffness[i]; }\n'
         '    btScalar mdsEquilibrium(int i) const { return m_equilibriumPoint[i]; }\n'
         '    btGeneric6DofSpringConstraint(btRigidBody& rbA,')
    edit(DISPATCHER, 'return m_collisionAlgorithmPoolAllocator->allocate(size);',
         'return dw_algorithm_alloc(m_collisionAlgorithmPoolAllocator->allocate(size));')
    edit(DISPATCHER, 'return\tbtAlignedAlloc(static_cast<size_t>(size), 16);',
         'return dw_algorithm_alloc(btAlignedAlloc(static_cast<size_t>(size), 16));')
    edit(DISPATCHER, 'void btCollisionDispatcher::freeCollisionAlgorithm(void* ptr)\n{',
         'void btCollisionDispatcher::freeCollisionAlgorithm(void* ptr)\n{\n\tdw_algorithm_free(ptr);')
    edit(DISPATCHER, '\treturn manifold;', '\tdw_manifold_alloc(manifold, b0, b1);\n\treturn manifold;')
    edit(DISPATCHER, 'void btCollisionDispatcher::releaseManifold(btPersistentManifold* manifold)\n{',
         'void btCollisionDispatcher::releaseManifold(btPersistentManifold* manifold)\n{\n\tdw_manifold_free(manifold);')
    edit(WORLD, 'void\tbtCollisionWorld::removeCollisionObject(btCollisionObject* collisionObject)\n{',
         'void\tbtCollisionWorld::removeCollisionObject(btCollisionObject* collisionObject)\n{\n\tdw_unregister(collisionObject);')
    edit(WORLD, 'void\tbtCollisionWorld::updateSingleAabb(btCollisionObject* colObj)\n{',
         'void\tbtCollisionWorld::updateSingleAabb(btCollisionObject* colObj)\n{\n\tdw_update(colObj, 1);')
    edit(WORLD, '\n}\n\nvoid\tbtCollisionWorld::updateAabbs()',
         '\n\tdw_update(colObj, 0);\n}\n\nvoid\tbtCollisionWorld::updateAabbs()')
    edit(ALLOCATOR, '\treturn ptr;\n}', '\tdw_allocation(1, ptr, size, alignment);\n\treturn ptr;\n}')
    edit(ALLOCATOR, '\tgNumAlignedFree++;\n\t{', '\tdw_allocation(0, ptr, 0, 0);\n\tgNumAlignedFree++;\n\t{')
    edit(SHIM, '    delete (*it)->rb;', '    dw_physical("body", (*it)->rb);\n    delete (*it)->rb;')
    edit(SHIM, '    delete *it;\n  }\n  for (auto it = W->bodies.rbegin();',
         '    dw_physical("joint", *it);\n    delete *it;\n  }\n  for (auto it = W->bodies.rbegin();')
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
         '        if let Some(key) = self.proxy_by_body.pop() {\n            crate::observer::unregister(self.sweep.handle(key).unwrap().owner);')
    edit(OWNER, '    fn update_aabb_at(&mut self, objects: &mut WorldObjects, i: usize) {',
         '    fn update_aabb_at(&mut self, objects: &mut WorldObjects, i: usize) {\n        crate::observer::update(i, true);')
    edit(OWNER, '\n    }\n\n    fn detect(&mut self, objects: &WorldObjects) {',
         '\n        crate::observer::update(i, false);\n    }\n\n    fn detect(&mut self, objects: &WorldObjects) {')
    edit(OWNER, '    fn detect(&mut self, objects: &WorldObjects) {',
         '    fn detect(&mut self, objects: &WorldObjects) {\n        for key in crate::observer::drain() { self.dispatcher.release(super::pair_cache::AlgorithmKey(key)); }')
    before = (root / OWNER).read_bytes().decode()
    edit(OWNER, before, before + '\n' + (here / 'fixture.rs').read_text())
    if dynamics:
        before = (root / DYNAMICS).read_text()
        edit(DYNAMICS, before, before + '\n' + (here / 'dynamics_fixture.rs').read_text())
        edit(SHIM, '    W->w.stepSimulation(dt, max_sub_steps, fixed_step);',
             '    const int returned = W->w.stepSimulation(dt, max_sub_steps, fixed_step);\n    dw_return(returned);')
        edit(DYNAMIC_NATIVE, '//process some debugging flags',
             'dw_clock(numSimulationSubSteps, (numSimulationSubSteps > maxSubSteps ? maxSubSteps : numSimulationSubSteps), fixedTimeStep, m_localTime);\n\t//process some debugging flags')
        prepare = 'm_constraintSolver->prepareSolve(getCollisionWorld()->getNumCollisionObjects(), getCollisionWorld()->getDispatcher()->getNumManifolds());'
        edit(DYNAMIC_NATIVE, prepare, 'dw_prepare(getCollisionWorld()->getNumCollisionObjects(), getCollisionWorld()->getDispatcher()->getNumManifolds());\n\t' + prepare)
        complete = 'm_constraintSolver->allSolved(solverInfo, m_debugDrawer, m_stackAlloc);'
        edit(DYNAMIC_NATIVE, complete, complete + '\n\tdw_all_solved();')
        signature = 'btScalar btSequentialImpulseConstraintSolver::solveGroup(btCollisionObject** bodies,int numBodies,btPersistentManifold** manifoldPtr, int numManifolds,btTypedConstraint** constraints,int numConstraints,const btContactSolverInfo& infoGlobal,btIDebugDraw* debugDrawer,btStackAlloc* stackAlloc,btDispatcher* /*dispatcher*/)\n{'
        edit(SOLVER_NATIVE, signature, signature + '\n\tdw_group(bodies,numBodies,manifoldPtr,numManifolds,constraints,numConstraints);')
        finish = 'm_tmpSolverContactFrictionConstraintPool.resize(0);'
        edit(SOLVER_NATIVE, finish, finish + '\n\tdw_workspace(m_tmpSolverBodyPool.size(),m_tmpSolverBodyPool.capacity());')
    return changes


def inverse(root, changes, originals):
    copies = {path: (root / path).read_bytes() for path in originals}
    for change in reversed(changes):
        path, old, new = change['path'], change['old'].encode(), change['new'].encode()
        offset = change['offset']
        require(copies[path][offset:offset + len(new)] == new, 'exact inverse hook range')
        copies[path] = copies[path][:offset] + old + copies[path][offset + len(new):]
    require(copies == originals, 'full original-source inverse equality')


# These are definitions, not compiled or accepted controls.
MUTANTS = {
    'expanded-registration': (OWNER, 'self.sweep.add(min, max, i, group, mask, 0)', 'self.sweep.add(min.sub(Vec3([0.02; 3])), max.add(Vec3([0.02; 3])), i, group, mask, 0)', 'sap'),
    'zero-margin': (OWNER, 'let threshold = Vec3([0.02; 3]);', 'let threshold = Vec3([0.0; 3]);', 'sap'),
    'motion-bound': (OWNER, 'let threshold = Vec3([0.02; 3]);', 'let (min, max) = objects.data()[i].shape.aabb(objects.data()[i].motion.get_world_transform());\n        let threshold = Vec3([0.02; 3]);', 'sap'),
    'inclusive-huge-boundary': (OWNER, 'max.sub(min).length2() < 1e12', 'max.sub(min).length2() <= 1e12', 'sap'),
    'kinematic-huge-exemption': (OWNER, 'collision_flags & 1 != 0', 'collision_flags & 3 != 0', 'sap'),
    'force-disable': (OWNER, '.set_activation_state(ActivationState::DisableSimulation)', '.force_activation_state(ActivationState::DisableSimulation)', 'activation'),
    'reverse-owner-order': (OWNER, 'keys.map(|key| owners[&key.0])', '[owners[&keys[1].0], owners[&keys[0].0]]', 'manifold-bodies'),
    'omit-preclean': (OWNER, 'if keys.contains(&key) {', 'if false && keys.contains(&key) {', 'events'),
    'ground-filter': (OWNER, 'let [group, mask] = objects.data()[i].filter;', 'let [group, mask] = if i == 0 { [1, -1] } else { objects.data()[i].filter };', 'filter'),
    'deferred-release': (OWNER, 'dispatcher.release(key);', 'crate::observer::defer(key.0);', 'events'),
    'ground-restitution': (OWNER, '        collision.register(&objects, 0);', '        let mut objects = objects;\n        objects.solver_parts().0[0].set_restitution(0.0);\n        collision.register(&objects, 0);', 'restitution'),
    'mode-zero-dynamic': (OWNER, 'self.objects.create_mmd_body(desc, mode)?', 'self.objects.create_mmd_body(desc, mode.max(1))?', 'mass-flags'),
    'motion-moves-current': (OWNER, 'self.objects.set_motion_state(body, world)', '{ self.objects.set_motion_state(body, world)?; self.objects.reseat(body, world) }', 'current-transform'),
    'reseat-keeps-interpolation-velocity': (OWNER, 'self.objects.reseat(body, world)', '''{
            let i = self.objects.index(body)?;
            let before = self.objects.bodies()[i].snapshot();
            self.objects.reseat(body, world)?;
            self.objects.solver_parts().0[i].set_interpolation_velocities(before.interpolation_linear_velocity, before.interpolation_angular_velocity);
            Ok(())
        }''', 'interpolation-velocity'),
    'stop-clears-interpolation-velocity': (OWNER, 'self.objects.stop_at(body, origin)', '''{
            self.objects.stop_at(body, origin)?;
            let i = self.objects.index(body)?;
            self.objects.solver_parts().0[i].set_interpolation_velocities(Vec3::ZERO, Vec3::ZERO);
            Ok(())
        }''', 'interpolation-velocity'),
    'joint-collision-suppression': (OWNER, 'self.objects.create_joint(desc, Some(uid))', '{ let _ = uid; self.objects.create_joint(desc, None) }', 'manifold-bodies'),
    'recreate-dispatcher': (OWNER, '        self.sweep.calculate_overlapping_pairs();', '        self.sweep.for_each_algorithm(|_, slot| { if let Some(key) = slot.take() { self.dispatcher.release(key); } });\n        self.dispatcher = CollisionDispatcher::new();\n        self.sweep.calculate_overlapping_pairs();', 'events'),
    'reverse-dispatch-order': (OWNER, '''        self.sweep.for_each_algorithm(|keys, algorithm| {
            dispatcher.near_pair(algorithm, keys.map(|key| owners[&key.0]), &views);
        });''', '''        let mut ordered = Vec::new();
        self.sweep.for_each_algorithm(|keys, slot| ordered.push((keys, slot.take())));
        ordered.reverse();
        for (keys, slot) in &mut ordered {
            dispatcher.near_pair(slot, keys.map(|key| owners[&key.0]), &views);
        }
        self.sweep.for_each_algorithm(|keys, slot| {
            *slot = ordered.iter().find(|entry| entry.0 == keys).unwrap().1;
        });''', 'dispatch-order'),
}


DYNAMICS_MUTANTS = {
    'executed-return': (DYNAMICS, 'Ok(step.requested)', 'Ok(step.executed)', 'step-return'),
    'substep-gravity': (DYNAMICS, 'for _ in 0..step.executed {', 'for _ in 0..step.executed {\n                self.collision.prepare_dynamics_step(step.dt);', 'dynamics'),
    'pair-owner': (OWNER, 'pair.proxies.map(|key| sweep.handle(key).unwrap().owner)', 'pair.proxies.map(|_| 0)', 'schedule'),
    'contact-only-union': (DYNAMICS, 'self.islands.calculate(objects, pairs, &constraints);', 'self.islands.calculate(objects, pairs.filter(|pair| manifolds.iter().any(|m| !m.manifold.contacts().is_empty() && (m.bodies == *pair || m.bodies == [pair[1], pair[0]]))), &constraints);', 'schedule'),
    'workspace-group-reset': (DYNAMICS, 'result = solve_group(', 'if island.manifolds.iter().all(|&index| island_manifolds[index].bodies.iter().all(|&body| !bodies[body].snapshot().is_kinematic)) && constraints.iter().all(|&index| joints[index].bodies.iter().all(|&body| !bodies[body].snapshot().is_kinematic)) { *workspace = SolverWorkspace::default(); }\n                        result = solve_group(', 'workspace'),
    'workspace-step-reset': (DYNAMICS, 'let workspace = &mut self.solver;', 'self.solver = SolverWorkspace::default();\n        let workspace = &mut self.solver;', 'workspace'),
    'missing-impulse-writeback': (CORE + 'solver.rs', 'solver.writeback(bodies, manifolds);', 'let saved: Vec<_> = manifolds.iter().map(|m| m.points.iter().map(|p| p.applied_impulse).collect::<Vec<_>>()).collect();\n    solver.writeback(bodies, manifolds);\n    for (m, saved) in manifolds.iter_mut().zip(saved) { for (p, value) in m.points.iter_mut().zip(saved) { p.applied_impulse = value; } }', 'manifolds'),
    'wrong-com': (CORE + 'world_objects.rs', 'self.bodies[i].set_center_of_mass_transform(predicted);', 'self.bodies[i].set_world_transform(predicted);', 'current-transform'),
    'zero-step-sync': (OWNER, 'if synchronize {', 'if synchronize && remainder < 0.0 {', 'motion-state'),
    'force-clear': (OWNER, 'self.objects.clear_forces();', 'let _ = &self.objects;', 'forces'),
    'mass-zero-on-toggle': (CORE + 'world_objects.rs', 'self.set_flags(i, if on { flags | 2 } else { flags & !2 });', 'self.set_flags(i, if on { flags | 2 } else { flags & !2 });\n        if on { self.bodies[i].set_mass_properties(0.0, Vec3::ZERO); }', 'mass-flags'),
    'sap-order': MUTANTS['reverse-dispatch-order'],
}


def mutants(dynamics=False):
    return DYNAMICS_MUTANTS if dynamics else MUTANTS


def mutate(root, name, dynamics=False):
    changes = []
    path, old, new, _ = mutants(dynamics)[name]
    replace(root, path, old, new, changes)
    return changes
