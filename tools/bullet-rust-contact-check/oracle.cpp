// Test adapter for the actual vendored Bullet algorithms and manifold.
#include "BulletCollision/CollisionDispatch/btSphereSphereCollisionAlgorithm.h"
#include "BulletCollision/CollisionDispatch/btConvexPlaneCollisionAlgorithm.h"
#include "BulletCollision/CollisionDispatch/btCollisionObject.h"
#include "BulletCollision/CollisionDispatch/btManifoldResult.h"
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/CollisionShapes/btStaticPlaneShape.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <memory>

static float scalar() { unsigned u; if (std::scanf("%x", &u)!=1) std::abort(); float f; std::memcpy(&f,&u,4); return f; }
static btVector3 vector() { float x=scalar(),y=scalar(),z=scalar(); return btVector3(x,y,z); }
static btTransform transform() { auto o=vector(); float x=scalar(),y=scalar(),z=scalar(),w=scalar(); return btTransform(btQuaternion(x,y,z,w),o); }
static void word(float f) { unsigned u; std::memcpy(&u,&f,4); std::printf("\t%08x",u); }
static void output(const btVector3& v) { for(int i=0;i<3;i++) word(v[i]); }
static std::unique_ptr<btCollisionShape> shape() {
    int k; if(std::scanf("%d",&k)!=1) std::abort();
    float a=scalar(),b=scalar(),c=scalar(),d=scalar();
    switch(k) {
    case 0:return std::unique_ptr<btCollisionShape>(new btSphereShape(a));
    case 1:return std::unique_ptr<btCollisionShape>(new btBoxShape(btVector3(a,b,c)));
    case 2:return std::unique_ptr<btCollisionShape>(new btCapsuleShape(a,b));
    case 3:return std::unique_ptr<btCollisionShape>(new btStaticPlaneShape(btVector3(a,b,c),d));
    default:std::abort();
    }
}
struct Dispatcher final:btDispatcher {
    std::unique_ptr<btPersistentManifold> manifold;
    btPersistentManifold* getNewManifold(void* a,void* b) override {
        if(manifold) std::abort();
        auto x=static_cast<btCollisionObject*>(a),y=static_cast<btCollisionObject*>(b);
        float threshold=btMin(x->getCollisionShape()->getContactBreakingThreshold(),y->getCollisionShape()->getContactBreakingThreshold());
        manifold.reset(new btPersistentManifold(a,b,0,threshold,BT_LARGE_FLOAT)); return manifold.get();
    }
    void releaseManifold(btPersistentManifold* p) override { if(p!=manifold.get()) std::abort(); manifold.reset(); }
    bool needsCollision(btCollisionObject*,btCollisionObject*) override {return true;}
    btCollisionAlgorithm* findAlgorithm(btCollisionObject*,btCollisionObject*,btPersistentManifold*) override {std::abort();}
    void clearManifold(btPersistentManifold*) override {std::abort();}
    bool needsResponse(btCollisionObject*,btCollisionObject*) override {std::abort();}
    void dispatchAllCollisionPairs(btOverlappingPairCache*,const btDispatcherInfo&,btDispatcher*) override {std::abort();}
    int getNumManifolds()const override {std::abort();}
    btPersistentManifold* getManifoldByIndexInternal(int) override {std::abort();}
    btPersistentManifold** getInternalManifoldPointer() override {std::abort();}
    void* allocateCollisionAlgorithm(int) override {std::abort();}
    void freeCollisionAlgorithm(void*) override {std::abort();}
};
int main() {
    Dispatcher dispatcher;
    btCollisionObject bodies[2];
    std::unique_ptr<btCollisionShape> shapes[2];
    std::unique_ptr<btCollisionAlgorithm> algorithm;
    char op; int row=0; int perturbOnly[2]={0,0};
    while(std::scanf(" %c",&op)==1) {
        if(op=='N') {
            algorithm.reset(); dispatcher.manifold.reset();
            shapes[0]=shape();shapes[1]=shape();
            for(int i=0;i<2;i++) bodies[i].setCollisionShape(shapes[i].get());
            btCollisionAlgorithmConstructionInfo ci;ci.m_dispatcher1=&dispatcher;
            if(shapes[0]->getShapeType()==SPHERE_SHAPE_PROXYTYPE && shapes[1]->getShapeType()==SPHERE_SHAPE_PROXYTYPE)
                algorithm.reset(new btSphereSphereCollisionAlgorithm(nullptr,ci,&bodies[0],&bodies[1]));
            else algorithm.reset(new btConvexPlaneCollisionAlgorithm(nullptr,ci,&bodies[0],&bodies[1],shapes[0]->getShapeType()==STATIC_PLANE_PROXYTYPE,1,1));
        } else if(op=='T') {
            for(auto& b:bodies) {b.setWorldTransform(transform());b.setFriction(scalar());b.setRestitution(scalar());}
            btManifoldResult result(&bodies[0],&bodies[1]);
            result.setShapeIdentifiersA(-1,-1);result.setShapeIdentifiersB(-1,-1);
            bool swapped=shapes[0]->getShapeType()==STATIC_PLANE_PROXYTYPE;
            bool isPlane=swapped || shapes[1]->getShapeType()==STATIC_PLANE_PROXYTYPE;
            int identityCount=-1;
            if(isPlane && dispatcher.manifold->getNumContacts()==0) {
                btPersistentManifold probe(&bodies[swapped?1:0],&bodies[swapped?0:1],0,dispatcher.manifold->getContactBreakingThreshold(),BT_LARGE_FLOAT);
                btCollisionAlgorithmConstructionInfo ci;ci.m_dispatcher1=&dispatcher;
                btConvexPlaneCollisionAlgorithm query(&probe,ci,&bodies[0],&bodies[1],swapped,1,1);
                btManifoldResult probeResult(&bodies[0],&bodies[1]);
                probeResult.setShapeIdentifiersA(-1,-1);probeResult.setShapeIdentifiersB(-1,-1);
                query.collideSingleContact(btQuaternion(0,0,0,1),&bodies[0],&bodies[1],btDispatcherInfo(),&probeResult);
                identityCount=probe.getNumContacts();
            }
            algorithm->processCollision(&bodies[0],&bodies[1],btDispatcherInfo(),&result);
            if(identityCount==0 && dispatcher.manifold->getNumContacts()>0) ++perturbOnly[swapped?1:0];
        } else if(op=='C') {
            algorithm.reset();dispatcher.manifold.reset(new btPersistentManifold(nullptr,nullptr,0,scalar(),BT_LARGE_FLOAT));
        } else if(op=='I') {
            auto a=vector(),b=vector(),wa=vector(),wb=vector(),n=vector();
            float depth=scalar();btManifoldPoint p(a,b,n,depth);p.m_positionWorldOnA=wa;p.m_positionWorldOnB=wb;
            p.m_combinedFriction=scalar();p.m_combinedRestitution=scalar();p.m_appliedImpulse=scalar();
            p.m_appliedImpulseLateral1=scalar();p.m_appliedImpulseLateral2=scalar();
            if(std::scanf("%d",&p.m_lifeTime)!=1) std::abort();
            p.m_partId0=p.m_partId1=p.m_index0=p.m_index1=-1;
            int index=dispatcher.manifold->getCacheEntry(p);
            if(index>=0)dispatcher.manifold->replaceContactPoint(p,index);else dispatcher.manifold->addManifoldPoint(p);
        } else if(op=='D') {
            int index;if(std::scanf("%d",&index)!=1)std::abort();dispatcher.manifold->removeContactPoint(index);
        } else if(op=='R') {
            auto a=transform(),b=transform();dispatcher.manifold->refreshContactPoints(a,b);
        } else if(op=='S') {
            auto s=shape();auto dir=vector();
            std::printf("%d\tS",row++);word(s->getAngularMotionDisc());output(static_cast<btConvexShape*>(s.get())->localGetSupportingVertex(dir));std::putchar('\n');continue;
        } else std::abort();
        auto& m=*dispatcher.manifold;
        std::printf("%d\t%c\t%d",row++,op,m.getNumContacts());word(m.getContactBreakingThreshold());
        for(int i=0;i<m.getNumContacts();i++) {
            auto& p=m.getContactPoint(i);
            output(p.m_localPointA);output(p.m_localPointB);output(p.m_positionWorldOnA);output(p.m_positionWorldOnB);output(p.m_normalWorldOnB);
            word(p.m_distance1);word(p.m_combinedFriction);word(p.m_combinedRestitution);word(p.m_appliedImpulse);word(p.m_appliedImpulseLateral1);word(p.m_appliedImpulseLateral2);
            std::printf("\t%d",p.m_lifeTime);
        }
        std::putchar('\n');
    }
    std::fprintf(stderr,"Native perturb-only contacts: direct=%d swapped=%d\n",perturbOnly[0],perturbOnly[1]);
    if(!perturbOnly[0] || !perturbOnly[1]) return 5;
}
