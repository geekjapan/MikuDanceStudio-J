// Bounded real-World scenes; IDs are stable input identities, never addresses.
#include "btBulletDynamicsCommon.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>

static unsigned bits(btScalar v) { unsigned u; std::memcpy(&u, &v, 4); return u; }
static int id(const btCollisionObject* b) { return b ? *static_cast<int*>(b->getUserPointer()) : -1; }
static FILE* replay;
static btDiscreteDynamicsWorld* current_world;
static int index_of(const btCollisionObject* b) {
    for (int i=0;i<current_world->getNumCollisionObjects();++i)
        if(current_world->getCollisionObjectArray()[i]==b) return i;
    std::abort();
}
static void vec(FILE* f,const btVector3& v) { for(int i=0;i<3;++i) std::fprintf(f," %08x",bits(v[i])); }
class CapturedWorld : public btDiscreteDynamicsWorld {
public:
    using btDiscreteDynamicsWorld::btDiscreteDynamicsWorld;
    void solveConstraints(btContactSolverInfo& info) override {
        int n=getNumCollisionObjects(), m=getDispatcher()->getNumManifolds();
        auto& pairs=getPairCache()->getOverlappingPairArray();
        std::fprintf(replay,"STEP %d %d %d\n",n,m,pairs.size());
        for(int i=0;i<n;++i) {
            auto* b=btRigidBody::upcast(getCollisionObjectArray()[i]);
            std::fprintf(replay,"B %d %d %08x",id(b),b->getCollisionFlags(),bits(b->getInvMass()));
            vec(replay,b->getInvInertiaDiagLocal());
            for(int j=0;j<3;++j) vec(replay,b->getWorldTransform().getBasis()[j]);
            vec(replay,b->getWorldTransform().getOrigin());
            vec(replay,b->getLinearVelocity());vec(replay,b->getAngularVelocity());
            std::fprintf(replay,"\n");
        }
        for(int i=0;i<m;++i) {
            auto* p=getDispatcher()->getManifoldByIndexInternal(i);
            std::fprintf(replay,"M %d %d %d %08x\n",index_of(static_cast<const btCollisionObject*>(p->getBody0())),index_of(static_cast<const btCollisionObject*>(p->getBody1())),p->getNumContacts(),bits(p->getContactProcessingThreshold()));
            for(int j=0;j<p->getNumContacts();++j) {
                const auto& q=p->getContactPoint(j);
                std::fprintf(replay,"P");
                vec(replay,q.m_localPointA);vec(replay,q.m_localPointB);vec(replay,q.getPositionWorldOnA());vec(replay,q.getPositionWorldOnB());vec(replay,q.m_normalWorldOnB);
                std::fprintf(replay," %08x %08x %08x %08x %d\n",bits(q.getDistance()),bits(q.m_combinedFriction),bits(q.m_combinedRestitution),bits(q.m_appliedImpulse),q.getLifeTime());
            }
        }
        for(int i=0;i<pairs.size();++i) std::fprintf(replay,"PAIR %d %d\n",index_of(static_cast<btCollisionObject*>(pairs[i].m_pProxy0->m_clientObject)),index_of(static_cast<btCollisionObject*>(pairs[i].m_pProxy1->m_clientObject)));
        std::fflush(replay);
        btDiscreteDynamicsWorld::solveConstraints(info);
    }
};
class Recorder : public btSequentialImpulseConstraintSolver {
public:
    int step = 0, group = 0;
    btScalar solveGroup(btCollisionObject** bodies, int n, btPersistentManifold** manifolds, int m,
                       btTypedConstraint** constraints, int c, const btContactSolverInfo& info,
                       btIDebugDraw* debug, btStackAlloc* stack, btDispatcher* dispatcher) override {
        std::fprintf(stderr,"G %d",n);
        for(int i=0;i<n;++i) std::fprintf(stderr," %d",index_of(bodies[i]));
        std::fprintf(stderr," %d",m);
        for(int i=0;i<m;++i) {
            int mi=0; while(current_world->getDispatcher()->getManifoldByIndexInternal(mi)!=manifolds[i]) ++mi;
            std::fprintf(stderr," %d",mi);
        }
        std::fprintf(stderr," %d\n",c);
        std::fprintf(stderr, "group step=%d call=%d bodies=", step, group++);
        for (int i=0;i<n;++i) std::fprintf(stderr, "%d:%d:%d,", id(bodies[i]), bodies[i]->getIslandTag(), bodies[i]->getCompanionId());
        std::fprintf(stderr, " manifolds=");
        for (int i=0;i<m;++i) std::fprintf(stderr, "%d:%d:%d,", id(static_cast<const btCollisionObject*>(manifolds[i]->getBody0())), id(static_cast<const btCollisionObject*>(manifolds[i]->getBody1())), manifolds[i]->getNumContacts());
        std::fprintf(stderr, " constraints=%d\n", c);
        return btSequentialImpulseConstraintSolver::solveGroup(bodies,n,manifolds,m,constraints,c,info,debug,stack,dispatcher);
    }
};
int main(int argc, char** argv) {
    if (argc != 5 || std::strlen(argv[2]) != 3) return 2;
    const int kind=std::atoi(argv[1]), count=std::atoi(argv[3]);
    if (kind<0 || kind>2 || count<1 || count>2) return 2;
    std::printf("input kind=%d order=%s count=%d steps=2 dt=%08x placement_new=%d scalar_bytes=%zu\n",kind,argv[2],count,bits(btScalar(1)/60),BT_USE_PLACEMENT_NEW,sizeof(btScalar));
    replay=std::fopen(argv[4],"w"); if(!replay) return 3;
    btDefaultCollisionConfiguration config;
    btCollisionDispatcher dispatcher(&config);
    btDbvtBroadphase broadphase;
    Recorder solver;
    CapturedWorld world(&dispatcher,&broadphase,&solver,&config);
    current_world=&world;
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
    std::fclose(replay);
    for(int i=0;i<=count;++i) world.removeRigidBody(body[i]);
    for(int i=0;i<3;++i) { delete body[i]; delete motion[i]; }
}
