// Bounded real-World scenes; IDs are stable input identities, never addresses.
#include "btBulletDynamicsCommon.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>

static unsigned bits(btScalar v) { unsigned u; std::memcpy(&u, &v, 4); return u; }
static int id(const btCollisionObject* b) { return b ? *static_cast<int*>(b->getUserPointer()) : -1; }
class Recorder : public btSequentialImpulseConstraintSolver {
public:
    int step = 0, group = 0;
    btScalar solveGroup(btCollisionObject** bodies, int n, btPersistentManifold** manifolds, int m,
                       btTypedConstraint** constraints, int c, const btContactSolverInfo& info,
                       btIDebugDraw* debug, btStackAlloc* stack, btDispatcher* dispatcher) override {
        std::fprintf(stderr, "group step=%d call=%d bodies=", step, group++);
        for (int i=0;i<n;++i) std::fprintf(stderr, "%d:%d:%d,", id(bodies[i]), bodies[i]->getIslandTag(), bodies[i]->getCompanionId());
        std::fprintf(stderr, " manifolds=");
        for (int i=0;i<m;++i) std::fprintf(stderr, "%d:%d:%d,", id(static_cast<const btCollisionObject*>(manifolds[i]->getBody0())), id(static_cast<const btCollisionObject*>(manifolds[i]->getBody1())), manifolds[i]->getNumContacts());
        std::fprintf(stderr, " constraints=%d\n", c);
        return btSequentialImpulseConstraintSolver::solveGroup(bodies,n,manifolds,m,constraints,c,info,debug,stack,dispatcher);
    }
};
int main(int argc, char** argv) {
    if (argc != 4 || std::strlen(argv[2]) != 3) return 2;
    const int kind=std::atoi(argv[1]), count=std::atoi(argv[3]);
    if (kind<0 || kind>2 || count<1 || count>2) return 2;
    std::printf("input kind=%d order=%s count=%d steps=2 dt=%08x placement_new=%d scalar_bytes=%zu\n",kind,argv[2],count,bits(btScalar(1)/60),BT_USE_PLACEMENT_NEW,sizeof(btScalar));
    btDefaultCollisionConfiguration config;
    btCollisionDispatcher dispatcher(&config);
    btDbvtBroadphase broadphase;
    Recorder solver;
    btDiscreteDynamicsWorld world(&dispatcher,&broadphase,&solver,&config);
    world.setGravity(btVector3(0,-10,0));
    world.getSolverInfo().m_numIterations=10;
    btBoxShape platform(btVector3(5,btScalar(.5),1));
    btSphereShape sphere(btScalar(.5));
    int ids[3]={0,1,2};
    btRigidBody* body[3];
    btDefaultMotionState* motion[3];
    for (int i=0;i<3;++i) {
        btCollisionShape* shape=i==0 ? static_cast<btCollisionShape*>(&platform) : &sphere;
        btScalar mass=(i==0 && kind==1) ? 0 : 1;
        btVector3 inertia(0,0,0); if (mass) shape->calculateLocalInertia(mass,inertia);
        btTransform t; t.setIdentity(); t.setOrigin(i==0 ? btVector3(0,0,0) : btVector3(i==1 ? -2 : 2,btScalar(.9),0));
        motion[i]=new btDefaultMotionState(t);
        btRigidBody::btRigidBodyConstructionInfo info(mass,motion[i],shape,inertia);
        body[i]=new btRigidBody(info); body[i]->setUserPointer(&ids[i]);
        body[i]->setActivationState(DISABLE_DEACTIVATION);
        body[i]->setFriction(0);
        if (i==0 && kind!=2) body[i]->setCollisionFlags(body[i]->getCollisionFlags() | btCollisionObject::CF_KINEMATIC_OBJECT);
    }
    for(int i=0;i<=count;++i) {
        const btVector3& p=body[i]->getWorldTransform().getOrigin();
        const btVector3& inv=body[i]->getInvInertiaDiagLocal();
        std::printf("body_input id=%d mass=%08x flags=%d activation=%d position=%08x,%08x,%08x invinertia=%08x,%08x,%08x friction=%08x\n",i,bits((i==0 && kind==1)?btScalar(0):btScalar(1)),body[i]->getCollisionFlags(),body[i]->getActivationState(),bits(p.x()),bits(p.y()),bits(p.z()),bits(inv.x()),bits(inv.y()),bits(inv.z()),bits(body[i]->getFriction()));
    }
    bool registered[3]={false,false,false};
    for (int i=0;i<3;++i) {
        int j=argv[2][i]-'0'; if(j<0 || j>2 || registered[j]) return 2;
        registered[j]=true; if(j<=count) world.addRigidBody(body[j]);
    }
    for(int step=0;step<2;++step) {
        solver.step=step; solver.group=0;
        world.stepSimulation(btScalar(1)/60,0);
        for(int i=0;i<=count;++i) {
            const btVector3& v=body[i]->getLinearVelocity(); const btVector3& w=body[i]->getAngularVelocity();
            std::printf("state %d %d %d %d %08x %08x %08x %08x %08x %08x\n", step,i,body[i]->getIslandTag(),body[i]->getCompanionId(),bits(v.x()),bits(v.y()),bits(v.z()),bits(w.x()),bits(w.y()),bits(w.z()));
        }
        std::fflush(stdout);
    }
    for(int i=0;i<=count;++i) world.removeRigidBody(body[i]);
    for(int i=0;i<3;++i) { delete body[i]; delete motion[i]; }
}
