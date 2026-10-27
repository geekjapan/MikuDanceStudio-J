#include "BulletCollision/BroadphaseCollision/btCollisionAlgorithm.h"
#include "BulletDynamics/ConstraintSolver/btContactSolverInfo.h"
#include "BulletCollision/CollisionDispatch/btDefaultCollisionConfiguration.h"
#include "BulletCollision/CollisionDispatch/btCollisionDispatcher.h"
#include "BulletCollision/BroadphaseCollision/btOverlappingPairCache.h"
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/CollisionShapes/btStaticPlaneShape.h"
#include "BulletDynamics/Dynamics/btRigidBody.h"
#include "BulletDynamics/ConstraintSolver/btPoint2PointConstraint.h"
#include "BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <map>
#include <memory>
#include <sstream>
#include <iostream>
#include <string>
#include <vector>

static void scalar(float f) { unsigned u; std::memcpy(&u,&f,4); std::printf(" %08x",u); }
static void vector(const btVector3& v) { for(int i=0;i<3;i++) scalar(v[i]); }
static int id(const void* b) { return *static_cast<const int*>(static_cast<const btCollisionObject*>(b)->getUserPointer()); }
static float read_float(std::istringstream& in) { std::string s; in>>s; unsigned u=std::stoul(s,nullptr,16); float f;std::memcpy(&f,&u,4);return f; }
int main() {
    btDefaultCollisionConfiguration configuration;
    btCollisionDispatcher dispatcher(&configuration);
    btHashedOverlappingPairCache cache;
    std::unique_ptr<btCollisionShape> shapes[8];
    std::unique_ptr<btRigidBody> bodies[8];
    std::unique_ptr<btBroadphaseProxy> proxies[8];
    std::unique_ptr<btPoint2PointConstraint> constraints[8][8];
    int ids[8]={0,1,2,3,4,5,6,7};
    std::map<const btCollisionAlgorithm*,int> lifetimes;
    int lifetime=0,row=0;
    btSequentialImpulseConstraintSolver solver;
    auto forget=[&](int a,int b) {
        auto* p=cache.findPair(proxies[a].get(),proxies[b].get());
        if(p && p->m_algorithm) lifetimes.erase(p->m_algorithm);
    };
    std::string line;
    while(std::getline(std::cin,line)) {
        std::istringstream in(line);char op;in>>op;if(!in) return 2;
        std::vector<bool> solver_alias;
        int a=0,b=0,k=0;in>>a;
        if(op=='F') {
            while(cache.getNumOverlappingPairs()) {
                auto& p=cache.getOverlappingPairArray()[0];
                cache.removeOverlappingPair(p.m_pProxy0,p.m_pProxy1,&dispatcher);
            }
            lifetimes.clear();
            for(int i=0;i<8;i++) for(int j=0;j<8;j++) if(constraints[i][j]) { bodies[i]->removeConstraintRef(constraints[i][j].get()); constraints[i][j].reset(); }
            for(int i=0;i<8;i++) {proxies[i].reset();bodies[i].reset();shapes[i].reset();}
            solver.reset();
        } else if(op=='N') {
            in>>k;
            if(bodies[a]) return 3;
            switch(k) {
            case 0: shapes[a].reset(new btSphereShape(.75f));break;
            case 1: shapes[a].reset(new btBoxShape(btVector3(.75f,.5f,.625f)));break;
            case 2: shapes[a].reset(new btCapsuleShape(.4f,1.f));break;
            case 3: shapes[a].reset(new btStaticPlaneShape(btVector3(0,1,0),0));break;
            default:return 4;
            }
            float x=read_float(in),y=read_float(in),z=read_float(in);int state,flags;in>>state>>flags;float threshold=read_float(in);
            bodies[a].reset(new btRigidBody((flags&3)?0.f:1.f,nullptr,shapes[a].get(),btVector3(1,1,1)));
            bodies[a]->setCollisionFlags(flags);bodies[a]->forceActivationState(state);bodies[a]->setContactProcessingThreshold(threshold);bodies[a]->setUserPointer(&ids[a]);
            btTransform world;world.setIdentity();world.setOrigin(btVector3(x,y,z));bodies[a]->setCenterOfMassTransform(world);
            proxies[a].reset(new btBroadphaseProxy(btVector3(-100,-100,-100),btVector3(100,100,100),bodies[a].get(),1,-1,nullptr));proxies[a]->m_uniqueId=a+1;
        } else if(op=='P') {in>>b;cache.addOverlappingPair(proxies[a].get(),proxies[b].get());}
        else if(op=='A') {in>>k;bodies[a]->forceActivationState(k);}
        else if(op=='T') {float x=read_float(in),y=read_float(in),z=read_float(in);auto t=bodies[a]->getWorldTransform();t.setOrigin(btVector3(x,y,z));bodies[a]->setCenterOfMassTransform(t);}
        else if(op=='E') {
            in>>b>>k;
            if(k) {constraints[a][b].reset(new btPoint2PointConstraint(*bodies[a],*bodies[b],btVector3(0,0,0),btVector3(0,0,0)));bodies[a]->addConstraintRef(constraints[a][b].get());}
            else {bodies[a]->removeConstraintRef(constraints[a][b].get());constraints[a][b].reset();}
        } else if(op=='D') {
            auto& pairs=cache.getOverlappingPairArray();
            for(int i=0;i<pairs.size();i++) {
                bool missing=!pairs[i].m_algorithm;
                btCollisionDispatcher::defaultNearCallback(pairs[i],dispatcher,btDispatcherInfo());
                if(missing && pairs[i].m_algorithm) lifetimes[pairs[i].m_algorithm]=++lifetime;
            }
        } else if(op=='C' || op=='X') {
            for(int i=0;i<cache.getNumOverlappingPairs();i++) {auto& p=cache.getOverlappingPairArray()[i];if(p.m_pProxy0==proxies[a].get() || p.m_pProxy1==proxies[a].get()) if(p.m_algorithm) lifetimes.erase(p.m_algorithm);}
            cache.cleanProxyFromPairs(proxies[a].get(),&dispatcher);
            if(op=='X') cache.removeOverlappingPairsContainingProxy(proxies[a].get(),&dispatcher);
        } else if(op=='R') {in>>b;forget(a,b);cache.removeOverlappingPair(proxies[a].get(),proxies[b].get(),&dispatcher);}
        else if(op=='W') {
            auto* m=dispatcher.getManifoldByIndexInternal(a);
            for(int i=0;i<m->getNumContacts();i++) {auto& p=m->getContactPoint(i);p.m_appliedImpulse=2.f;p.m_appliedImpulseLateral1=.125f;p.m_appliedImpulseLateral2=-.25f;}
        } else if(op=='S') {
            btCollisionObject* objects[8];int count=0;
            for(int i=0;i<8;i++) if(bodies[i]) {objects[count++]=bodies[i].get();bodies[i]->setCompanionId(-1);}
            btContactSolverInfo info;info.m_timeStep=1.f/60.f;
            auto** solver_manifolds=dispatcher.getInternalManifoldPointer();
            for(int i=0;i<dispatcher.getNumManifolds();i++) solver_alias.push_back(solver_manifolds[i]==dispatcher.getManifoldByIndexInternal(i));
            solver.solveGroup(objects,count,solver_manifolds,dispatcher.getNumManifolds(),nullptr,0,info,nullptr,nullptr,nullptr);
            for(int i=0;i<8;i++) if(bodies[i] && !bodies[i]->isStaticOrKinematicObject()) {
                btTransform t;bodies[i]->predictIntegratedTransform(info.m_timeStep,t);bodies[i]->setCenterOfMassTransform(t);
            }
        } else return 5;
        std::printf("O %d %c %d %d\n",row,op,cache.getNumOverlappingPairs(),dispatcher.getNumManifolds());
        std::map<const btPersistentManifold*,int> owners;
        for(int i=0;i<cache.getNumOverlappingPairs();i++) {
            auto& p=cache.getOverlappingPairArray()[i];int life=p.m_algorithm?lifetimes.at(p.m_algorithm):0;
            std::printf("P %d %d %d %d %d\n",row,i,id(p.m_pProxy0->m_clientObject),id(p.m_pProxy1->m_clientObject),life);
            if(p.m_algorithm) {btManifoldArray all;p.m_algorithm->getAllContactManifolds(all);for(int j=0;j<all.size();j++) owners[all[j]]=life;}
        }
        for(int i=0;i<dispatcher.getNumManifolds();i++) {
            auto* m=dispatcher.getManifoldByIndexInternal(i);
            std::printf("M %d %d %d %d %d",row,i,owners.at(m),id(m->getBody0()),id(m->getBody1()));scalar(m->getContactProcessingThreshold());scalar(m->getContactBreakingThreshold());std::printf(" %d\n",m->getNumContacts());
            for(int j=0;j<m->getNumContacts();j++) {
                auto& p=m->getContactPoint(j);std::printf("Q %d %d %d",row,i,j);
                vector(p.m_localPointA);vector(p.m_localPointB);vector(p.m_positionWorldOnA);vector(p.m_positionWorldOnB);vector(p.m_normalWorldOnB);
                scalar(p.m_distance1);scalar(p.m_combinedFriction);scalar(p.m_combinedRestitution);scalar(p.m_appliedImpulse);scalar(p.m_appliedImpulseLateral1);scalar(p.m_appliedImpulseLateral2);
                std::printf(" %d %d",p.m_lifeTime,p.m_lateralFrictionInitialized?1:0);
                if(p.m_lateralFrictionInitialized) {vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);}
                std::printf("\n");
            }
        }
        for(int i=0;i<8;i++) if(bodies[i]) {std::printf("B %d %d",row,i);vector(bodies[i]->getWorldTransform().getOrigin());vector(bodies[i]->getLinearVelocity());vector(bodies[i]->getAngularVelocity());std::printf("\n");}
        for(int i=0;i<int(solver_alias.size());i++) std::printf("L %d %d %d\n",row,i,solver_alias[i]?1:0);
        row++;
    }
    while(cache.getNumOverlappingPairs()) {auto& p=cache.getOverlappingPairArray()[0];cache.removeOverlappingPair(p.m_pProxy0,p.m_pProxy1,&dispatcher);}
    std::printf("Z %d\n",row);
}
