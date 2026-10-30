"""Native diagnostic generation and full-TU rebuild API. GHA execution only."""
from pathlib import Path
import hashlib
import os
import re

from hooks import replace, inverse, require, NATIVE, DISPATCHER, WORLD, ALLOCATOR, SOLVER_NATIVE, DYNAMIC_NATIVE, SHIM

HERE = 'tools/bullet-rust-mmd-collision-check/'
POINT = NATIVE + 'BulletCollision/NarrowPhaseCollision/btManifoldPoint.h'
MANIFOLD = NATIVE + 'BulletCollision/NarrowPhaseCollision/btPersistentManifold.h'
MANIFOLD_CPP = NATIVE + 'BulletCollision/NarrowPhaseCollision/btPersistentManifold.cpp'
RESULT = NATIVE + 'BulletCollision/CollisionDispatch/btManifoldResult.cpp'
CONSUMER = HERE + 'oracle.cpp'
HEADER = HERE + 'friction_native.h'
FROZEN_LIBRARY_COUNT = 321
FROZEN_LIBRARY_SHA = '0577702285c69e3bf7ed9a3fcf4e53c83bceddfb692152d869065e717af05dc3'
FROZEN_CONSUMER_SHA = '048d203433db8a1506443d1818fbb6ca2b11e1ad26b83734a7e469612fb93b76'
CHANGED_HEADERS = (POINT, MANIFOLD, NATIVE + 'BulletCollision/BroadphaseCollision/btAxisSweep3.h',
                   NATIVE + 'BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h', HEADER)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def hosted():
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'native diagnostic generation/build is GHA-only')
    require(os.name == 'posix' and os.uname().sysname == 'Linux' and os.uname().machine == 'x86_64',
            'native diagnostic frozen Linux x64 host')


def library_paths(root):
    paths = sorted(p for base in (NATIVE.rstrip('/'), 'rust/crates/mds-bullet-sys/shim')
                   for p in (root / base).rglob('*') if p.is_file())
    require(all(not p.is_symlink() for p in paths), 'regular complete native source closure')
    return paths


def original_census(root):
    """Complete original-only bytes support the independent flag/Dir1 guarantee.

    Constructors set false; removal's vacated backing flag sets false; FI copies
    constructed false newPt; both solver true writers first define Dir1. W writes
    both before its immediate snapshot. No other conditional Dir2 is read.
    """
    paths = library_paths(root)
    digest = hashlib.sha256()
    for p in paths:
        digest.update(p.relative_to(root).as_posix().encode() + b'\0' + hashlib.sha256(p.read_bytes()).digest())
    require(len(paths) == FROZEN_LIBRARY_COUNT and digest.hexdigest() == FROZEN_LIBRARY_SHA,
            'complete original-only native/shim census bytes')
    require(sha((root / CONSUMER).read_bytes()) == FROZEN_CONSUMER_SHA, 'original consumer census bytes')
    tokens = re.compile(r'btManifoldPoint|m_lateralFriction(?:Dir[12]|Initialized)|'
                        r'm_userPersistentData|gContact(?:Added|Processed|Destroyed)Callback|'
                        r'addManifoldPoint|replaceContactPoint|setAnisotropicFriction|'
                        r'pthread_create|sigaction|CreateThread|m_solverMode')
    return [(p.relative_to(root).as_posix(), n, line)
            for p in [*paths, root / CONSUMER] if p.suffix in ('.h', '.hpp', '.cpp')
            for n, line in enumerate(p.read_text().splitlines(), 1) if tokens.search(line)]


def _legacy_native(edit):
    """Only native generated-copy anchors from hooks.instrument."""
    edit(CHANGED_HEADERS[2], '\tBP_FP_INT_TYPE getNumHandles() const',
         '\tconst Edge* mdsEdges(int axis) const { return m_pEdges[axis]; }\n'
         '\tbool mdsAcceleratorEnabled() const { return m_raycastAccelerator != 0 && m_nullPairCache != 0; }\n'
         '\tBP_FP_INT_TYPE getNumHandles() const')
    edit(CHANGED_HEADERS[3], '    btGeneric6DofSpringConstraint(btRigidBody& rbA,',
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
    edit(DISPATCHER, '\treturn manifold;', '\tdw_manifold_alloc(manifold, b0, b1);\n\tfn_allocate(manifold,b0,b1);\n\treturn manifold;')
    edit(DISPATCHER, 'void btCollisionDispatcher::releaseManifold(btPersistentManifold* manifold)\n{',
         'void btCollisionDispatcher::releaseManifold(btPersistentManifold* manifold)\n{\n\tfn_guard("RELEASE_ENTER");')
    edit(DISPATCHER, '\tmanifold->~btPersistentManifold();',
         '\tfn_release(manifold);\n\tdw_manifold_free(manifold);\n\tmanifold->~btPersistentManifold();')
    tail = '\n}\n\n\t\n\nbtCollisionAlgorithm* btCollisionDispatcher::findAlgorithm'
    edit(DISPATCHER, tail, '\n\tfn_guard("RELEASE_EXIT");' + tail)
    edit(WORLD, 'void\tbtCollisionWorld::removeCollisionObject(btCollisionObject* collisionObject)\n{',
         'void\tbtCollisionWorld::removeCollisionObject(btCollisionObject* collisionObject)\n{\n\tdw_unregister(collisionObject);')
    edit(WORLD, 'void\tbtCollisionWorld::updateSingleAabb(btCollisionObject* colObj)\n{',
         'void\tbtCollisionWorld::updateSingleAabb(btCollisionObject* colObj)\n{\n\tdw_update(colObj, 1);')
    edit(WORLD, '\n}\n\nvoid\tbtCollisionWorld::updateAabbs()', '\n\tdw_update(colObj, 0);\n}\n\nvoid\tbtCollisionWorld::updateAabbs()')
    edit(ALLOCATOR, '\treturn ptr;\n}', '\tdw_allocation(1, ptr, size, alignment);\n\treturn ptr;\n}')
    edit(ALLOCATOR, '\tgNumAlignedFree++;\n\t{', '\tdw_allocation(0, ptr, 0, 0);\n\tgNumAlignedFree++;\n\t{')
    edit(SHIM, '    delete (*it)->rb;', '    dw_physical("body", (*it)->rb);\n    delete (*it)->rb;')
    edit(SHIM, '    delete *it;\n  }\n  for (auto it = W->bodies.rbegin();',
         '    dw_physical("joint", *it);\n    delete *it;\n  }\n  for (auto it = W->bodies.rbegin();')
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


def _lifecycle(edit):
    edit(POINT, '\t\t\t{\n\t\t\t}', '\t\t\t{\n\t\t\t\tfn_ctor(this);\n\t\t\t}')
    edit(POINT, '\t\t\t{\n\t\t\t\t\n\t\t\t\t\t\n\t\t\t}', '\t\t\t{\n\t\t\t\tfn_ctor(this);\n\t\t\t}')
    signature = 'void btManifoldResult::addContactPoint(const btVector3& normalOnBInWorld,const btVector3& pointInWorld,btScalar depth)\n{'
    edit(RESULT, signature, signature + '\n\tfn_guard("RESULT_ENTER");')
    edit(RESULT, '\tif (depth > m_manifoldPtr->getContactBreakingThreshold())\n\t\treturn;',
         '\tif (depth > m_manifoldPtr->getContactBreakingThreshold()) {\n\t\tfn_guard("RESULT_EXIT");\n\t\treturn;\n\t}')
    incoming = '\tbtManifoldPoint newPt(localA,localB,normalOnBInWorld,depth);'
    edit(RESULT, incoming, incoming + '\n\tfn_incoming(&newPt);')
    edit(RESULT, '\t//User can override friction and/or restitution',
         '\tfn_added(m_manifoldPtr,insertIndex);\n\t//User can override friction and/or restitution')
    tail = '\t\t(*gContactAddedCallback)(m_manifoldPtr->getContactPoint(insertIndex),obj0,newPt.m_partId0,newPt.m_index0,obj1,newPt.m_partId1,newPt.m_index1);\n\t}\n\n}'
    edit(RESULT, tail, tail[:-1] + '\tfn_guard("RESULT_EXIT");\n}')
    add = 'int btPersistentManifold::addManifoldPoint(const btManifoldPoint& newPoint)\n{'
    edit(MANIFOLD_CPP, add, add + '\n\tfn_guard("ADD_ENTER",&newPoint);')
    edit(MANIFOLD_CPP, '\tm_pointCache[insertIndex] = newPoint;\n\treturn insertIndex;',
         '\tm_pointCache[insertIndex] = newPoint;\n\tfn_insert(this,insertIndex,&newPoint,false);\n\tfn_guard("ADD_EXIT");\n\treturn insertIndex;')
    user = 'void btPersistentManifold::clearUserCache(btManifoldPoint& pt)\n{'
    edit(MANIFOLD_CPP, user, user + '\n\tfn_guard("USERCACHE_ENTER",&pt);')
    destroyed = '\t\tif (pt.m_userPersistentData && gContactDestroyedCallback)'
    edit(MANIFOLD_CPP, destroyed, '\t\tfn_guard("DESTROYED_PRECALL",&pt);\n' + destroyed)
    edit(MANIFOLD_CPP, '\n\t\n}\n\n\nint btPersistentManifold::sortCachedPoints',
         '\n\tfn_guard("USERCACHE_EXIT",&pt);\n}\n\n\nint btPersistentManifold::sortCachedPoints')
    edit(MANIFOLD, '\tvoid removeContactPoint (int index)\n\t{',
         '\tvoid removeContactPoint (int index)\n\t{\n\t\tfn_guard("REMOVE_ENTER",&m_pointCache[index]);')
    edit(MANIFOLD, '\t\tm_cachedPoints--;\n\t}',
         '\t\tm_cachedPoints--;\n\t\tfn_remove(this,index);\n\t\tfn_guard("REMOVE_EXIT");\n\t}')
    edit(MANIFOLD, '\tvoid replaceContactPoint(const btManifoldPoint& newPoint,int insertIndex)\n\t{',
         '\tvoid replaceContactPoint(const btManifoldPoint& newPoint,int insertIndex)\n\t{\n\t\tfn_guard("REPLACE_ENTER",&newPoint);')
    edit(MANIFOLD, '\n#endif\n\t}\n\n\tbool validContactDistance',
         '\n#endif\n\t\tfn_insert(this,insertIndex,&newPoint,true);\n\t\tfn_guard("REPLACE_EXIT");\n\t}\n\n\tbool validContactDistance')
    edit(MANIFOLD, '\tSIMD_FORCE_INLINE\tvoid\tclearManifold()\n\t{',
         '\tSIMD_FORCE_INLINE\tvoid\tclearManifold()\n\t{\n\t\tfn_guard("CLEAR_ENTER");\n\t\tfn_clear_begin(this);')
    edit(MANIFOLD, '\t\t\tclearUserCache(m_pointCache[i]);',
         '\t\t\tclearUserCache(m_pointCache[i]);\n\t\t\tfn_clear_point(this,i);')
    edit(MANIFOLD, '\t\tm_cachedPoints = 0;\n\t}',
         '\t\tm_cachedPoints = 0;\n\t\tfn_clear_end(this);\n\t\tfn_guard("CLEAR_EXIT");\n\t}')


def _solver(edit):
    begin = '\t\t\t\t\tsolverConstraint.m_frictionIndex = m_tmpSolverContactFrictionConstraintPool.size();'
    edit(SOLVER_NATIVE, begin, begin + '\n\t\t\t\t\tfn_solver_begin(&cp,infoGlobal.m_solverMode);')
    recompute = '\t\t\t\t\tif (!(infoGlobal.m_solverMode & SOLVER_ENABLE_FRICTION_DIRECTION_CACHING) || !cp.m_lateralFrictionInitialized)'
    edit(SOLVER_NATIVE, recompute,
         '\t\t\t\t\tconst bool fn_recompute = !(infoGlobal.m_solverMode & SOLVER_ENABLE_FRICTION_DIRECTION_CACHING) || !cp.m_lateralFrictionInitialized;\n'
         '\t\t\t\t\tconst bool fn_two = bool(infoGlobal.m_solverMode & SOLVER_USE_2_FRICTION_DIRECTIONS);\n\t\t\t\t\tif (fn_recompute)')
    raw = '\t\t\t\t\t\tcp.m_lateralFrictionDir1 = vel - cp.m_normalWorldOnB * rel_vel;'
    edit(SOLVER_NATIVE, raw, raw + '\n\t\t\t\t\t\tfn_write(&cp,"DIR1_RAW",1);')
    cond = '\t\t\t\t\t\tif (!(infoGlobal.m_solverMode & SOLVER_DISABLE_VELOCITY_DEPENDENT_FRICTION_DIRECTION) && lat_rel_vel > SIMD_EPSILON)'
    edit(SOLVER_NATIVE, cond, '\t\t\t\t\t\tconst bool fn_velocity = !(infoGlobal.m_solverMode & SOLVER_DISABLE_VELOCITY_DEPENDENT_FRICTION_DIRECTION) && lat_rel_vel > SIMD_EPSILON;\n'
         '\t\t\t\t\t\tfn_choice(&cp,fn_recompute,fn_velocity,fn_two);\n\t\t\t\t\t\tif (fn_velocity)')
    edit(SOLVER_NATIVE, '\t\t\t\t\t\t\tcp.m_lateralFrictionDir1 /= btSqrt(lat_rel_vel);\n#endif',
         '\t\t\t\t\t\t\tcp.m_lateralFrictionDir1 /= btSqrt(lat_rel_vel);\n#endif\n\t\t\t\t\t\t\tfn_write(&cp,"VELOCITY_DIR1",1);')
    second = '\t\t\t\t\t\t\t\tcp.m_lateralFrictionDir2.normalize();//??'
    edit(SOLVER_NATIVE, second, second + '\n\t\t\t\t\t\t\t\tfn_write(&cp,"VELOCITY_DIR2",2);')
    plane = '\t\t\t\t\t\t\tbtPlaneSpace1(cp.m_normalWorldOnB,cp.m_lateralFrictionDir1,cp.m_lateralFrictionDir2);'
    edit(SOLVER_NATIVE, plane, plane + '\n\t\t\t\t\t\t\tfn_write(&cp,"PLANE_BOTH",3);')
    cached = '\t\t\t\t\t} else\n\t\t\t\t\t{\n\t\t\t\t\t\taddFrictionConstraint(cp.m_lateralFrictionDir1'
    edit(SOLVER_NATIVE, cached, '\t\t\t\t\t} else\n\t\t\t\t\t{\n\t\t\t\t\t\tfn_choice(&cp,fn_recompute,false,fn_two);\n\t\t\t\t\t\taddFrictionConstraint(cp.m_lateralFrictionDir1')
    warm = '\t\t\t\t\tif (infoGlobal.m_solverMode & SOLVER_USE_FRICTION_WARMSTARTING)'
    edit(SOLVER_NATIVE, warm, '\t\t\t\t\tfn_solver_end(&cp);\n\n' + warm)
    aniso = '\tif (colObj && colObj->hasAnisotropicFriction())\n\t{'
    edit(SOLVER_NATIVE, aniso, '\tfn_no_anisotropy(colObj && colObj->hasAnisotropicFriction());\n' + aniso)


def _consumer(edit, observed, corpus):
    require(type(corpus) is bytes and corpus and len(corpus) <= 64 * 1024 * 1024 and corpus.endswith(b'\n'), 'bounded exact command bytes')
    corpus.decode('ascii')
    require(b'\r' not in corpus and b'\0' not in corpus, 'LF ASCII corpus')
    count = corpus.count(b'\n')
    require(count <= 2147483647, 'bounded actual command count')
    owner = 'static int owner(const void* p) {return int(reinterpret_cast<intptr_t>(static_cast<const btCollisionObject*>(p)->getUserPointer()))-1;}'
    edit(CONSUMER, owner, owner + '\n#define MDS_FRICTION_NATIVE_IMPLEMENTATION\n#include "friction_native.h"')
    snapshot = '    auto& pairs=w->bp.getOverlappingPairCache()->getOverlappingPairArray();'
    edit(CONSUMER, snapshot,
         '    friction_native::need(w->w.getSolverInfo().m_solverMode==260);\n'
         '    for(auto* body:w->bodies)friction_native::need(!body->rb->hasAnisotropicFriction());\n' + snapshot)
    identities = '    std::map<const void*,unsigned> manifold_owners;'
    edit(CONSUMER, identities, identities + '\n    std::map<const void*,unsigned> algorithm_snapshot_ids, manifold_snapshot_ids;')
    original_algorithm = '#else\n            generation=1;\n#endif\n            btManifoldArray all;'
    edit(CONSUMER, original_algorithm,
         '#else\n            friction_native::need(algorithm_snapshot_ids.size()<2147483647u);\n'
         '            auto actual_algorithm=algorithm_snapshot_ids.emplace(p.m_algorithm,unsigned(algorithm_snapshot_ids.size()+1));\n'
         '            friction_native::need(actual_algorithm.second);generation=actual_algorithm.first->second;\n'
         '#endif\n            btManifoldArray all;')
    owner_join = 'btManifoldArray all;p.m_algorithm->getAllContactManifolds(all);for(int j=0;j<all.size();++j)manifold_owners[all[j]]=generation;'
    edit(CONSUMER, owner_join,
         'btManifoldArray all;p.m_algorithm->getAllContactManifolds(all);for(int j=0;j<all.size();++j){auto bound=manifold_owners.emplace(all[j],generation);friction_native::need(bound.second || bound.first->second==generation);}')
    original_manifold = '        auto* m=w->disp.getManifoldByIndexInternal(i);unsigned generation=1;'
    edit(CONSUMER, original_manifold,
         '        auto* m=w->disp.getManifoldByIndexInternal(i);unsigned generation=unsigned(i)+1;\n'
         '        friction_native::need(generation<=2147483647u && manifold_snapshot_ids.emplace(m,generation).second);')
    manifold_loop = '\n    for(int i=0;i<w->disp.getNumManifolds();++i) {'
    edit(CONSUMER, manifold_loop,
         '\n    friction_native::need(manifold_owners.size()==size_t(w->disp.getNumManifolds()));' + manifold_loop)
    flag = 'std::cout<<\' \'<<p.m_lifeTime<<\' \'<<int(p.m_lateralFrictionInitialized);if(p.m_lateralFrictionInitialized){vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);}std::cout<<\'\\n\';'
    edit(CONSUMER, flag, 'std::cout<<\' \'<<p.m_lifeTime<<\' \'<<friction_native::boolean(p.m_lateralFrictionInitialized)<<\'\\n\';\n'
         '            friction_native::directions(m,i,j,op=="W");')
    contact = '            auto& p=m->getContactPoint(j);std::cout<<"Q "'
    edit(CONSUMER, contact, '            friction_native::snapshot_point(m,i,j);\n' + contact)
    loop = '        for(int j=0;j<m->getNumContacts();++j) {'
    edit(CONSUMER, loop, '        friction_native::snapshot_manifold(m,i);\n' + loop)
    start = '    mds_mmd_world* w=nullptr;std::string line;'
    edit(CONSUMER, start, '    friction_native::start(' + ('true' if observed else 'false') + ',argv[1],"' + sha(corpus) + '",' + str(count) + ');\n' + start)
    command = '        std::istringstream in(line);std::string op;in>>op;'
    edit(CONSUMER, command, '        friction_native::command_begin(unsigned(row));\n' + command)
    edit(CONSUMER, 'if(!in || (in>>std::ws,!in.eof()))return 2;snapshot(w,op);++row;',
         'if(!in || (in>>std::ws,!in.eof()))return 2;fn_guard("SNAPSHOT");snapshot(w,op);friction_native::command_end();++row;')
    edit(CONSUMER, 'if(w)return 3;std::cout<<"Z "<<row<<\'\\n\';',
         'if(w)return 3;std::cout<<"Z "<<row<<\'\\n\';friction_native::finish(unsigned(row));')
    if observed:
        w = 'p.m_lateralFrictionDir2=btVector3(0,0,1);'
        edit(CONSUMER, w, w + 'fn_write(&p,"FIXTURE_W",3);')
        edit(CONSUMER, '        else if(op=="W") {', '        else if(op=="W") {\n            fn_guard("FIXTURE_BEGIN");')
        edit(CONSUMER, '        } else if(op=="J")', '            fn_guard("FIXTURE_END");\n        } else if(op=="J")')


def _refresh(edit):
    signature = 'void btPersistentManifold::refreshContactPoints(const btTransform& trA,const btTransform& trB)\n{'
    edit(MANIFOLD_CPP, signature, signature + '\n\tfn_guard("REFRESH_ENTER");\n\tfn_refresh_begin(this);')
    distance = '\t\tif (!validContactDistance(manifoldPoint))\n\t\t{\n\t\t\tremoveContactPoint(i);'
    edit(MANIFOLD_CPP, distance, '\t\tif (!validContactDistance(manifoldPoint))\n\t\t{\n\t\t\tfn_refresh_point(this,i,true,false);\n\t\t\tremoveContactPoint(i);')
    lateral = '\t\t\tif (distance2d  > getContactBreakingThreshold()*getContactBreakingThreshold() )\n\t\t\t{\n\t\t\t\tremoveContactPoint(i);'
    edit(MANIFOLD_CPP, lateral, '\t\t\tif (distance2d  > getContactBreakingThreshold()*getContactBreakingThreshold() )\n\t\t\t{\n\t\t\t\tfn_refresh_point(this,i,false,true);\n\t\t\t\tremoveContactPoint(i);')
    kept = '\t\t\t\t//contact point processed callback\n\t\t\t\tif (gContactProcessedCallback)'
    edit(MANIFOLD_CPP, kept, '\t\t\t\t//contact point processed callback\n\t\t\t\tfn_refresh_point(this,i,false,false);\n\t\t\t\tfn_guard("PROCESSED_PRECALL",&manifoldPoint);\n\t\t\t\tif (gContactProcessedCallback)')
    end = '#ifdef DEBUG_PERSISTENCY\n\tDebugPersistency();\n#endif //\n}'
    edit(MANIFOLD_CPP, end, end[:-1] + '\tfn_refresh_end(this);\n\tfn_guard("REFRESH_EXIT");\n}')


def generate(root, *, observed, corpus):
    """Mutate a fresh generated shadow only and return full inverse custody.

    m_pointCache[4] backing constructors receive guards only. The only actual
    incoming is standalone geometric newPt. FI accounts for add/replace copies;
    FV accounts for remove's move. No incoming FPY exists in this frozen source.
    Solver/read-only references and pointers are not incoming copies.
    """
    hosted()
    require(type(observed) is bool, 'exact native variant selector')
    require(not (root / '.git').exists(), 'generation requires a disjoint source copy, never a Git worktree')
    census = original_census(root)
    originals, edits = {}, []
    def edit(path, old, new):
        if path not in originals:
            originals[path] = (root / path).read_bytes()
        replace(root, path, old, new, edits)
    if observed:
        _legacy_native(edit)
        _lifecycle(edit)
        _refresh(edit)
        _solver(edit)
    _consumer(edit, observed, corpus)
    inverse(root, edits, originals)
    return edits, originals, census


def native_sources(root):
    return sorted(p for folder in ('BulletCollision', 'BulletDynamics', 'LinearMath')
                  for p in (root / NATIVE / folder).rglob('*.cpp'))


def rebuild_all(root, out, *, compile_object, observed):
    """Compile every native TU, with complete actual include paths from driver.

    Callback(source, object, label, root, flags) must retain measured discovery/
    compile include equality and source/object CAS; return all resolved targets.
    Original archives are distinct and never used to satisfy observed includers.
    """
    hosted()
    sources = native_sources(root)
    require(sources and type(observed) is bool, 'complete native TU plan')
    objects, includers = [], {path: [] for path in CHANGED_HEADERS}
    for index, source in enumerate(sources):
        label = 'friction-' + ('observed-' if observed else 'original-') + str(index).zfill(3)
        obj = out / (source.stem + '.o')
        require(obj not in objects, 'unique exact archive member name for every native TU')
        flags = ['-include', root / HEADER, '-include', root / (HERE + 'observer.h'), '-DDW_OBSERVED=1'] if observed else []
        dependencies = compile_object(source, obj, label, root, flags)
        require(type(dependencies) in (list, tuple) and dependencies, 'actual measured include paths returned by driver')
        targets = {Path(p).resolve(strict=True) for p in dependencies}
        for header in CHANGED_HEADERS:
            if (root / header).resolve() in targets:
                includers[header].append(source.relative_to(root).as_posix())
        require(obj.is_file(), 'actual rebuilt object')
        objects.append(obj)
    if observed:
        require(all(includers[path] for path in CHANGED_HEADERS), 'every changed header has measured rebuilt includers')
        require(len(includers[HEADER]) == len(sources), 'forced observation header in every observed TU')
    return objects, includers


def selected_link_objects(linkmap, objects, *, archive, selected_members, forbidden_archives):
    """Existing archive parser must prove actual selected rebuilt objects.

    The driver creates separate archives, retaining exact member/source/object
    identities, and links the observed consumer exclusively to its observed one.
    """
    hosted()
    require(type(linkmap) is bytes and linkmap and len(linkmap) <= 64 * 1024 * 1024, 'bounded actual link map')
    require(type(forbidden_archives) in (list, tuple), 'explicit opposite-variant archive exclusion')
    for forbidden in forbidden_archives:
        require(Path(forbidden).name.encode() not in linkmap, 'opposite-variant native archive absent from actual link map')
    selected = selected_members(linkmap, 'Linux', str(archive))
    names = {p.name for p in objects}
    require(len(names) == len(objects) and selected and selected <= names, 'selected actual rebuilt archive objects')
    return selected
