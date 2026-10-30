// Calls the real vendored API. Failure results never read unwritten fields.
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/NarrowPhaseCollision/btGjkEpa2.h"
#include "BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h"
#include "BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h"
#include <cstdio>
#include <cstring>
#include <memory>
#include <initializer_list>
static float scalar(unsigned word){float v;std::memcpy(&v,&word,4);return v;}
static void word(float v){unsigned w;std::memcpy(&w,&v,4);std::printf("\t%08x",w);}
static void vector(const btVector3& v){for(int i=0;i<3;++i)word(v[i]);}
static std::unique_ptr<btConvexShape> shape(int kind,const float* v){switch(kind){case 0:return std::unique_ptr<btConvexShape>(new btSphereShape(v[0]));case 1:return std::unique_ptr<btConvexShape>(new btBoxShape(btVector3(v[0],v[1],v[2])));case 2:return std::unique_ptr<btConvexShape>(new btCapsuleShape(v[0],v[1]));}return {};}
#include "BulletCollision/NarrowPhaseCollision/btGjkPairDetector.h"
#include "BulletCollision/CollisionDispatch/btDefaultCollisionConfiguration.h"
#include "BulletCollision/CollisionDispatch/btConvexConvexAlgorithm.h"
#include "BulletCollision/CollisionDispatch/btCollisionObject.h"
#include "BulletCollision/CollisionDispatch/btManifoldResult.h"
#include <cassert>
#include <cstdlib>
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
    void* allocateCollisionAlgorithm(int n) override {return btAlignedAlloc(n,16);}
    void freeCollisionAlgorithm(void* p) override {btAlignedFree(p);}
};

struct Result:btDiscreteCollisionDetectorInterface::Result {
    bool valid=false; btVector3 normal,point;float depth;
    void setShapeIdentifiersA(int,int) override {} void setShapeIdentifiersB(int,int) override {}
    void addContactPoint(const btVector3& n,const btVector3& p,btScalar d) override {valid=true;normal=n;point=p;depth=d;}
};
int main(){
 btDefaultCollisionConfiguration configuration; Dispatcher dispatcher;
 auto* factory=static_cast<btConvexConvexAlgorithm::CreateFunc*>(configuration.getCollisionAlgorithmCreateFunc(SPHERE_SHAPE_PROXYTYPE,BOX_SHAPE_PROXYTYPE));
 for(int a: {SPHERE_SHAPE_PROXYTYPE,BOX_SHAPE_PROXYTYPE,CAPSULE_SHAPE_PROXYTYPE})for(int b: {SPHERE_SHAPE_PROXYTYPE,BOX_SHAPE_PROXYTYPE,CAPSULE_SHAPE_PROXYTYPE})if(a!=b)assert(configuration.getCollisionAlgorithmCreateFunc(a,b)==factory);
 assert(factory->m_numPerturbationIterations==0);
 auto* simplex=static_cast<btVoronoiSimplexSolver*>(factory->m_simplexSolver);
 simplex->reset();simplex->addVertex(btVector3(1,2,3),btVector3(4,5,6),btVector3(3,3,3));btVector3 seed;simplex->closest(seed);
 btCollisionObject bodies[2];std::unique_ptr<btConvexShape> a,b;std::unique_ptr<btCollisionAlgorithm> algorithm;
 int id,ka,kb,reset;unsigned bits;
 while(std::scanf("%d%d%d%d",&id,&ka,&kb,&reset)==4){float v[35];for(float& x:v){if(std::scanf("%x",&bits)!=1)return 2;x=scalar(bits);}
 if(reset){algorithm.reset();a=shape(ka,v);b=shape(kb,v+3);bodies[0].setCollisionShape(a.get());bodies[1].setCollisionShape(b.get());btCollisionAlgorithmConstructionInfo ci;ci.m_dispatcher1=&dispatcher;algorithm.reset(new btConvexConvexAlgorithm(nullptr,ci,&bodies[0],&bodies[1],simplex,factory->m_pdSolver,factory->m_numPerturbationIterations,factory->m_minimumPointsPerturbationThreshold));}
 btTransform t[2];for(int i=0;i<2;++i){const float* p=v+6+12*i;t[i].setBasis(btMatrix3x3(p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8]));t[i].setOrigin(btVector3(p[9],p[10],p[11]));bodies[i].setWorldTransform(t[i]);bodies[i].setFriction(v[31+i]);bodies[i].setRestitution(v[33+i]);}
 btGjkPairDetector detector(a.get(),b.get(),simplex,factory->m_pdSolver);btDiscreteCollisionDetectorInterface::ClosestPointInput input;input.m_transformA=t[0];input.m_transformB=t[1];input.m_maximumDistanceSquared=v[30];Result r;detector.getClosestPoints(input,r,0);
 if(id==0){assert(simplex->numVertices()==0);assert(detector.m_curIter==0 && detector.m_degenerateSimplex==0);assert(r.valid && r.normal==btVector3(1,2,3));}
 std::printf("%d\t%d\t%d\t%d\t%d",id,r.valid,detector.m_lastUsedMethod,detector.m_curIter,detector.m_degenerateSimplex);vector(detector.getCachedSeparatingAxis());word(detector.getCachedSeparatingDistance());if(r.valid){vector(r.normal);vector(r.point);word(r.depth);}
 btManifoldResult result(&bodies[0],&bodies[1]);result.setShapeIdentifiersA(-1,-1);result.setShapeIdentifiersB(-1,-1);algorithm->processCollision(&bodies[0],&bodies[1],btDispatcherInfo(),&result);
 auto& m=*dispatcher.manifold;std::printf("\t%d",m.getNumContacts());word(m.getContactBreakingThreshold());for(int i=0;i<m.getNumContacts();++i){auto& p=m.getContactPoint(i);vector(p.m_localPointA);vector(p.m_localPointB);vector(p.m_positionWorldOnA);vector(p.m_positionWorldOnB);vector(p.m_normalWorldOnB);word(p.m_distance1);word(p.m_combinedFriction);word(p.m_combinedRestitution);word(p.m_appliedImpulse);word(p.m_appliedImpulseLateral1);word(p.m_appliedImpulseLateral2);std::printf("\t%d\t%d",p.m_lifeTime,p.m_lateralFrictionInitialized);if(p.m_lateralFrictionInitialized){vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);}p.m_lateralFrictionInitialized=true;p.m_lateralFrictionDir1=btVector3(1,2,3);p.m_lateralFrictionDir2=btVector3(4,5,6);p.m_appliedImpulse=3.25f+i;p.m_appliedImpulseLateral1=.75f;p.m_appliedImpulseLateral2=-.5f;}
 std::putchar('\n');
 }
 algorithm.reset();return 0;
}
