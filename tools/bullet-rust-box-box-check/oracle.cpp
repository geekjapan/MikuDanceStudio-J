// Adapter calling the real vendored detector and collision algorithm.
#include "BulletCollision/CollisionDispatch/btBoxBoxCollisionAlgorithm.h"
#include "BulletCollision/CollisionDispatch/btBoxBoxDetector.h"
#include "BulletCollision/CollisionDispatch/btCollisionObject.h"
#include "BulletCollision/CollisionDispatch/btManifoldResult.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <memory>
#include <set>
static float scalar() { unsigned u; if (std::scanf("%x", &u)!=1) std::abort(); float f; std::memcpy(&f,&u,4); return f; }
static btVector3 vector() { float x=scalar(),y=scalar(),z=scalar(); return btVector3(x,y,z); }
static btTransform transform() { auto o=vector(); btMatrix3x3 b; for(int i=0;i<3;i++) for(int j=0;j<3;j++) b[i][j]=scalar(); return btTransform(b,o); }
static void word(float f) { unsigned u; std::memcpy(&u,&f,4); std::printf("\t%08x",u); }
static void output(const btVector3& v) { for(int i=0;i<3;i++) word(v[i]); }
static std::set<int> codes, polygons, candidates;
void boxCoverage(int code,int n,int cnum) { codes.insert(code);polygons.insert(n);candidates.insert(cnum); }
struct Sink: btDiscreteCollisionDetectorInterface::Result {
 struct Point {btVector3 normal,point;float depth;};
 Point points[4];int count=0;
 void setShapeIdentifiersA(int,int) override {}
 void setShapeIdentifiersB(int,int) override {}
 void addContactPoint(const btVector3& n,const btVector3& p,btScalar d) override {if(count==4)std::abort();points[count++]={n,p,d};}
 void print() {std::printf("C\t%d",count);for(int i=0;i<count;i++){output(points[i].normal);output(points[i].point);word(points[i].depth);}std::putchar('\n');}
};
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
 std::unique_ptr<btBoxShape> shapes[2];
 std::unique_ptr<btCollisionAlgorithm> algorithm;
 bool borrowed=false;
 char op;
 while(std::scanf(" %c",&op)==1) {
  if(op=='N') {
   algorithm.reset();dispatcher.manifold.reset();
   int mode;if(std::scanf("%d",&mode)!=1)std::abort();borrowed=mode!=0;
   shapes[0].reset(new btBoxShape(vector()));shapes[1].reset(new btBoxShape(vector()));
   for(int i=0;i<2;i++)bodies[i].setCollisionShape(shapes[i].get());
   btCollisionAlgorithmConstructionInfo ci;ci.m_dispatcher1=&dispatcher;
   if(borrowed)dispatcher.getNewManifold(&bodies[0],&bodies[1]);
   algorithm.reset(new btBoxBoxCollisionAlgorithm(borrowed?dispatcher.manifold.get():nullptr,ci,&bodies[0],&bodies[1]));
  } else if(op=='T') {
   for(auto& b:bodies){b.setWorldTransform(transform());b.setFriction(scalar());b.setRestitution(scalar());}
   Sink sink;btBoxBoxDetector detector(shapes[0].get(),shapes[1].get());
   btDiscreteCollisionDetectorInterface::ClosestPointInput input;input.m_transformA=bodies[0].getWorldTransform();input.m_transformB=bodies[1].getWorldTransform();
   detector.getClosestPoints(input,sink,nullptr);sink.print();
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
 for(auto pair:{std::make_pair("codes",&codes),std::make_pair("polygon",&polygons),std::make_pair("candidates",&candidates)}){std::fprintf(stderr,"%s",pair.first);for(int v:*pair.second)std::fprintf(stderr," %d",v);std::fputc('\n',stderr);}
}
