from pathlib import Path

CORE = 'rust/crates/mds-bullet/src/core/'
NATIVE = 'recipes/bullet275/bullet-src/src/BulletCollision/CollisionDispatch/'
SHIM = 'rust/crates/mds-bullet-sys/shim/mds_bt.cpp'
OWNER = CORE + 'discrete_collision_world.rs'
DYNAMICS = CORE + 'discrete_dynamics_world.rs'
DYNAMIC_NATIVE = 'recipes/bullet275/bullet-src/src/BulletDynamics/Dynamics/btDiscreteDynamicsWorld.cpp'
SOLVER_NATIVE = 'recipes/bullet275/bullet-src/src/BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp'
DBVT = 'recipes/bullet275/bullet-src/src/BulletCollision/BroadphaseCollision/btDbvt.cpp'
NATIVE_OBSERVATIONS = (('btCollisionDispatcher', NATIVE+'btCollisionDispatcher.cpp'),
                       ('btCollisionWorld', NATIVE+'btCollisionWorld.cpp'), ('btDbvt', DBVT),
                       ('btDiscreteDynamicsWorld', DYNAMIC_NATIVE), ('btSequentialImpulseConstraintSolver', SOLVER_NATIVE))
OBSERVATION_PATHS = (DYNAMICS, OWNER, CORE+'dispatcher.rs', CORE+'world_objects.rs', CORE+'solver.rs',
                     *(path for _,path in NATIVE_OBSERVATIONS), SHIM)


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
    edit(DBVT, 'btAlignedAlloc(sizeof(btDbvtNode),16)', 'dw_node_alloc(pdbvt)')
    edit(DBVT, '{ node=pdbvt->m_free;pdbvt->m_free=0; }',
         '{ node=pdbvt->m_free;pdbvt->m_free=0; dw_node_reuse(pdbvt,node); }')
    edit(DBVT, 'btAlignedFree(pdbvt->m_free);', 'dw_node_free(pdbvt,pdbvt->m_free);')
    edit(DBVT, 'pdbvt->m_free=node;', 'pdbvt->m_free=node; dw_node_cache(pdbvt,node);')
    edit(DBVT, 'btAlignedFree(m_free);', 'dw_node_free(this,m_free);')
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
    for path, extra in [(OWNER, 'fixture.rs'), (CORE + 'world_objects.rs', 'world_objects_fixture.rs'), (DYNAMICS, 'dynamics_fixture.rs')]:
        text = (here / extra).read_text()
        edit(path, (root / path).read_text(), (root / path).read_text() + '\n' + text)
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


MUTANTS = {
    'executed-return': (DYNAMICS, 'Ok(step.requested)', 'Ok(step.executed)'),
    'substep-gravity': (DYNAMICS, 'for _ in 0..step.executed {', 'for _ in 0..step.executed {\n                self.collision.prepare_dynamics_step(step.dt);'),
    'pair-owner': (OWNER, 'pair.proxies.map(|key| broadphase.owner(key))', 'pair.proxies.map(|_| 0)'),
    'contact-only-union': (DYNAMICS, 'self.islands.calculate(objects, pairs, &constraints);', 'self.islands.calculate(objects, pairs.filter(|pair| manifolds.iter().any(|m| !m.manifold.contacts().is_empty() && (m.bodies == *pair || m.bodies == [pair[1], pair[0]]))), &constraints);'),
    'workspace-group-reset': (DYNAMICS, 'result = solve_group(', 'if island.manifolds.iter().all(|&index| island_manifolds[index].bodies.iter().all(|&body| !bodies[body].snapshot().is_kinematic)) && constraints.iter().all(|&index| joints[index].bodies.iter().all(|&body| !bodies[body].snapshot().is_kinematic)) { *workspace = SolverWorkspace::default(); }\n                        result = solve_group('),
    'workspace-step-reset': (DYNAMICS, 'let workspace = &mut self.solver;', 'self.solver = SolverWorkspace::default();\n        let workspace = &mut self.solver;'),
    'missing-impulse-writeback': (CORE+'solver.rs', 'solver.writeback(bodies, manifolds);', 'let saved: Vec<_> = manifolds.iter().map(|m| m.points.iter().map(|p| p.applied_impulse).collect::<Vec<_>>()).collect();\n    solver.writeback(bodies, manifolds);\n    for (m, saved) in manifolds.iter_mut().zip(saved) { for (p, value) in m.points.iter_mut().zip(saved) { p.applied_impulse = value; } }'),
    'wrong-com': (CORE+'world_objects.rs', 'self.bodies[i].set_center_of_mass_transform(predicted);', 'self.bodies[i].set_world_transform(predicted);'),
    'zero-step-sync': (OWNER, 'if synchronize {', 'if synchronize && remainder < 0.0 {'),
    'force-clear': (OWNER, 'self.objects.clear_forces();', 'let _ = &self.objects;'),
}


def mutate(root, name):
    changes = []
    path, old, new = MUTANTS[name]
    replace(root, path, old, new, changes)
    return changes
