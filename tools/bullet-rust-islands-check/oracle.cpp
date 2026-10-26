#include <btBulletDynamicsCommon.h>
#include <BulletCollision/BroadphaseCollision/btSimpleBroadphase.h>
#include <BulletCollision/CollisionDispatch/btSimulationIslandManager.h>
#include <BulletDynamics/ConstraintSolver/btConstraintSolver.h>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <sstream>
#include <vector>
#include <memory>
#include <cstdlib>
static uint32_t bits(float x) { uint32_t u; std::memcpy(&u,&x,4); return u; }
static float scalar(uint32_t u) { float x; std::memcpy(&x,&u,4); return x; }
static std::ostringstream events;
static std::vector<btPersistentManifold*> ms;
static std::vector<btTypedConstraint*> cs;
static int event_count;
static std::vector<btRigidBody*> registered;
static size_t body_index(btCollisionObject* b) { size_t i=0; while(registered[i]!=b) ++i; return i; }
static void indices(btCollisionObject** b,int n) { events << ' ' << n; for(int i=0;i<n;++i) events << ' ' << body_index(b[i]); }
static void manifold_indices(btPersistentManifold** m,int n) { events << ' ' << n; for(int i=0;i<n;++i) { size_t j=0; while(ms[j]!=m[i]) ++j; events << ' ' << j; } }
struct Recorder:btConstraintSolver {
 void prepareSolve(int n,int m) override { ++event_count; events << " P " << n << ' ' << m; }
 btScalar solveGroup(btCollisionObject** b,int n,btPersistentManifold** m,int nm,btTypedConstraint** c,int nc,const btContactSolverInfo&,btIDebugDraw*,btStackAlloc*,btDispatcher*) override {
  ++event_count; events << " G"; indices(b,n); manifold_indices(m,nm); events << ' ' << nc;
  for(int i=0;i<nc;++i) { size_t j=0; while(cs[j]!=c[i]) ++j; events << ' ' << j; } return 0;
 }
 void allSolved(const btContactSolverInfo&,btIDebugDraw*,btStackAlloc*) override { ++event_count; events << " A"; }
 void reset() override {}
};
struct RowConstraint:btPoint2PointConstraint {
 int rows;
 RowConstraint(btRigidBody& a,btRigidBody& b,int n):btPoint2PointConstraint(a,b,btVector3(0,0,0),btVector3(0,0,0)),rows(n) {}
 void getInfo1(btConstraintInfo1* info) override { info->m_numConstraintRows=rows; info->nub=3; }
};
struct World:btDiscreteDynamicsWorld {
 World(btDispatcher* d,btBroadphaseInterface* b,btConstraintSolver* s,btCollisionConfiguration* c):btDiscreteDynamicsWorld(d,b,s,c) {}
 using btDiscreteDynamicsWorld::calculateSimulationIslands;
 using btDiscreteDynamicsWorld::solveConstraints;
};
struct Callback:btSimulationIslandManager::IslandCallback {
 void ProcessIsland(btCollisionObject** b,int n,btPersistentManifold** m,int nm,int id) override { ++event_count; events << " C " << id; indices(b,n); manifold_indices(m,nm); }
};
static void uf_dump(btUnionFind& uf) { std::cout << ' ' << uf.getNumElements(); for(int i=0;i<uf.getNumElements();++i) std::cout << ' ' << uf.getElement(i).m_id << ' ' << uf.getElement(i).m_sz; }
static void dump(int id,const char* phase,btSimulationIslandManager* im,const std::vector<btRigidBody*>& bs) {
 std::cout << id << ' ' << phase; uf_dump(im->getUnionFind()); std::cout << ' ' << bs.size();
 for(auto* b:bs) std::cout << ' ' << body_index(b) << ' ' << b->getActivationState() << ' ' << (b->getCollisionFlags()&3) << ' ' << int(b->hasContactResponse()) << ' ' << b->getIslandTag() << ' ' << b->getCompanionId() << ' ' << bits(b->getHitFraction()) << ' ' << bits(b->getDeactivationTime());
 std::cout << ' ' << event_count << events.str() << '\n'; events.str(""); event_count=0;
}
template<class... T> static void read(std::istringstream& in,T&... values) { if(!(in >> ... >> values)) std::exit(6); }
int main() {
 std::ios::sync_with_stdio(false); std::cerr.unsetf(std::ios::unitbuf);
 std::string line;
 while(std::getline(std::cin,line)) {
  if(line.empty()) continue;
  std::istringstream in(line); std::string op; int id,n; read(in,id,op,n);
  std::cerr << "I " << id << '\n';
  if(op=="U") {
   btUnionFind uf; uf.reset(n); std::cout << id << " reset"; uf_dump(uf); std::cout << '\n';
   int count; read(in,count); for(int k=0;k<count;++k) { char command; int a,b; read(in,command); int result=-1;
    if(command=='J') { read(in,a,b); uf.unite(a,b); }
    else if(command=='F') { read(in,a); result=uf.find(a); }
    else if(command=='S') uf.sortIslands(); else return 2;
    std::cout << id << ' ' << command << ' ' << result; uf_dump(uf); std::cout << '\n';
   }
  } else if(op=="W") {
   int split,mode; read(in,split,mode);
   btDefaultCollisionConfiguration config; btCollisionDispatcher dispatcher(&config); bt32BitAxisSweep3 broadphase(btVector3(-10000,-10000,-10000),btVector3(10000,10000,10000),n+2,nullptr,true); Recorder recorder; World world(&dispatcher,&broadphase,&recorder,&config);
   btBoxShape shape(btVector3(1,1,1)); std::vector<btRigidBody*> bodies; registered.clear();
   for(int i=0;i<n;++i) {
    int state,flags,response,tag,comp; uint32_t time,hit; read(in,state,flags,response,time,tag,comp,hit);
    auto* body=new btRigidBody(1,nullptr,&shape,btVector3(1,1,1)); btTransform t; t.setIdentity(); t.setOrigin(btVector3(i*8,0,0)); body->setWorldTransform(t);
    body->setCollisionFlags(flags | (response?0:btCollisionObject::CF_NO_CONTACT_RESPONSE)); body->forceActivationState(state); body->setDeactivationTime(scalar(time)); body->setIslandTag(tag); body->setCompanionId(comp); body->setHitFraction(scalar(hit));
    world.addCollisionObject(body,btBroadphaseProxy::DefaultFilter,btBroadphaseProxy::AllFilter); bodies.push_back(body); registered.push_back(body);
   }
   int count; read(in,count); for(int k=0;k<count;++k) { int a,b; read(in,a,b); broadphase.getOverlappingPairCache()->addOverlappingPair(bodies[a]->getBroadphaseHandle(),bodies[b]->getBroadphaseHandle()); }
   read(in,count); cs.clear(); for(int k=0;k<count;++k) { int a,b,rows,disable; read(in,a,b,rows,disable); auto* c=new RowConstraint(*bodies[a],*bodies[b],rows); world.addConstraint(c,disable!=0); cs.push_back(c); }
   read(in,count); ms.clear(); for(int k=0;k<count;++k) { int a,b,points; uint32_t distance; read(in,a,b,points,distance); auto* m=dispatcher.getNewManifold(bodies[a],bodies[b]); ms.push_back(m); for(int j=0;j<points;++j) { btManifoldPoint p(btVector3(j,0,0),btVector3(j,0,0),btVector3(0,1,0),scalar(distance)); m->addManifoldPoint(p); } }
   auto* im=world.getSimulationIslandManager(); im->setSplitIslands(split!=0);
   if(mode) { world.calculateSimulationIslands(); dump(id,"calculate",im,bodies); world.solveConstraints(world.getSolverInfo()); dump(id,"solve",im,bodies); }
   else {
    im->updateActivationState(&world,&dispatcher); dump(id,"update",im,bodies);
    for(auto* c:cs) { auto& a=c->getRigidBodyA(); auto& b=c->getRigidBodyB(); if(!a.isStaticOrKinematicObject()&&!b.isStaticOrKinematicObject()&&(a.isActive()||b.isActive())) im->getUnionFind().unite(a.getIslandTag(),b.getIslandTag()); }
    dump(id,"unite",im,bodies); im->storeIslandActivationState(&world); dump(id,"store",im,bodies);
    Callback callback; im->buildAndProcessIslands(&dispatcher,&world,&callback); dump(id,"build",im,bodies);
   }
   for(auto* m:ms) dispatcher.releaseManifold(m); for(auto* c:cs) { world.removeConstraint(c); delete c; } for(auto* b:bodies) { world.removeCollisionObject(b); delete b; }
  } else return 3;
  std::string extra; if(in>>extra) return 4; if(!in.eof()) return 5;
 }
}
void island_observe_uf(const char* label,int a,int b,const btUnionFind& uf) {
 std::cerr << "UF " << label << ' ' << a << ' ' << b << ' ' << uf.getNumElements();
 for(int i=0;i<uf.getNumElements();++i) std::cerr << ' ' << uf.getElement(i).m_id << ' ' << uf.getElement(i).m_sz;
 std::cerr << '\n';
}
void island_observe_objects(const char* label,int a,int b,int c,btCollisionWorld* world) {
 std::cerr << "O " << label << ' ' << a << ' ' << b << ' ' << c << ' ' << world->getNumCollisionObjects();
 for(int i=0;i<world->getNumCollisionObjects();++i) {
  auto* o=world->getCollisionObjectArray()[i]; std::cerr << ' ' << body_index(o) << ' ' << o->getActivationState() << ' ' << o->getIslandTag() << ' ' << o->getCompanionId() << ' ' << bits(o->getHitFraction()) << ' ' << bits(o->getDeactivationTime());
 }
 std::cerr << '\n';
}
void island_observe_constraints(const btAlignedObjectArray<btTypedConstraint*>& sorted) {
 std::cerr << "Q " << sorted.size(); for(int i=0;i<sorted.size();++i) { size_t j=0; while(cs[j]!=sorted[i]) ++j; std::cerr << ' ' << j; } std::cerr << '\n';
}

int body_index_observed(btCollisionObject* object,btCollisionWorld* world) {
 for(int i=0;i<world->getNumCollisionObjects();++i) if(world->getCollisionObjectArray()[i]==object) return i;
 std::abort();
}
