// Adapter calling the real vendored capsule collision algorithm.
#include "BulletCollision/CollisionDispatch/btConvexConvexAlgorithm.h"

#include "BulletCollision/CollisionDispatch/btCollisionObject.h"
#include "BulletCollision/CollisionDispatch/btManifoldResult.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h"
#include "BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <memory>
int capsuleOperation = 0;
static float scalar() { unsigned u; if (std::scanf("%x", &u)!=1) std::abort(); float f; std::memcpy(&f,&u,4); return f; }
static btVector3 vector() { float x=scalar(),y=scalar(),z=scalar(); return btVector3(x,y,z); }
static btTransform transform() { auto o=vector(); btMatrix3x3 b; for(int i=0;i<3;i++) for(int j=0;j<3;j++) b[i][j]=scalar(); return btTransform(b,o); }
static void word(float f) { unsigned u; std::memcpy(&u,&f,4); std::printf("\t%08x",u); }
static void output(const btVector3& v) { for(int i=0;i<3;i++) word(v[i]); }
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
 btVoronoiSimplexSolver simplex;
 btGjkEpaPenetrationDepthSolver penetration;
 btCollisionObject bodies[2];
 std::unique_ptr<btCapsuleShape> shapes[2];
 std::unique_ptr<btCollisionAlgorithm> algorithm;

 char op;
 while(std::scanf(" %c",&op)==1) {
  ++capsuleOperation;
  if(op=='N') {
   algorithm.reset();dispatcher.manifold.reset();
   int mode;if(std::scanf("%d",&mode)!=1)std::abort();if(mode!=0)std::abort();
   for(auto& s:shapes){float radius=scalar(),height=scalar();s.reset(new btCapsuleShape(radius,height));}
   for(int i=0;i<2;i++)bodies[i].setCollisionShape(shapes[i].get());
   btCollisionAlgorithmConstructionInfo ci;ci.m_dispatcher1=&dispatcher;
   algorithm.reset(new btConvexConvexAlgorithm(nullptr,ci,&bodies[0],&bodies[1],&simplex,&penetration,0,3));
   continue;
  } else if(op=='T') {
   for(auto& b:bodies){b.setWorldTransform(transform());b.setFriction(scalar());b.setRestitution(scalar());}
   btManifoldResult result(&bodies[0],&bodies[1]);result.setShapeIdentifiersA(-1,-1);result.setShapeIdentifiersB(-1,-1);
   algorithm->processCollision(&bodies[0],&bodies[1],btDispatcherInfo(),&result);
  } else if(op=='J') {
   for(int i=0;i<dispatcher.manifold->getNumContacts();i++) {
    auto& p=dispatcher.manifold->getContactPoint(i);
    p.m_appliedImpulse=2.0f+i;p.m_appliedImpulseLateral1=3.0f+i;p.m_appliedImpulseLateral2=4.0f+i;p.m_lifeTime=10+i;
    p.m_lateralFrictionInitialized=true;p.m_lateralFrictionDir1=btVector3(1,0,0);p.m_lateralFrictionDir2=btVector3(0,0,1);
   }
  } else if(op=='R') {
   dispatcher.manifold->refreshContactPoints(bodies[0].getWorldTransform(),bodies[1].getWorldTransform());
  } else std::abort();
  auto& m=*dispatcher.manifold;
  std::printf("M\t%c\t%d",op,m.getNumContacts());word(m.getContactBreakingThreshold());
  for(int i=0;i<m.getNumContacts();i++) {
   auto& p=m.getContactPoint(i);
   output(p.m_localPointA);output(p.m_localPointB);output(p.m_positionWorldOnA);output(p.m_positionWorldOnB);output(p.m_normalWorldOnB);
   word(p.m_distance1);word(p.m_combinedFriction);word(p.m_combinedRestitution);word(p.m_appliedImpulse);word(p.m_appliedImpulseLateral1);word(p.m_appliedImpulseLateral2);std::printf("\t%d\t%d",p.m_lifeTime,p.m_lateralFrictionInitialized?1:0);
   if(p.m_lateralFrictionInitialized){output(p.m_lateralFrictionDir1);output(p.m_lateralFrictionDir2);}else{output(btVector3(0,0,0));output(btVector3(0,0,0));}
  }
  std::putchar('\n');

 }
}
