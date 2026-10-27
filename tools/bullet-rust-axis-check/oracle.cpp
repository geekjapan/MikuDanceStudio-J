// Test driver of the real, unmodified vendored Bullet cache.
#include "BulletCollision/BroadphaseCollision/btAxisSweep3.h"
#include "BulletCollision/BroadphaseCollision/btDispatcher.h"
#include "BulletCollision/BroadphaseCollision/btCollisionAlgorithm.h"
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <cstdlib>
#include <memory>
#include <set>
#include <cstring>
std::string events;
std::map<void*, int> tokens;
struct Algorithm : btCollisionAlgorithm {
    int token;
    explicit Algorithm(int t): token(t) {}
    ~Algorithm() override { events += "d" + std::to_string(token) + ","; }
    void processCollision(btCollisionObject*,btCollisionObject*,const btDispatcherInfo&,btManifoldResult*) override {}
    btScalar calculateTimeOfImpact(btCollisionObject*,btCollisionObject*,const btDispatcherInfo&,btManifoldResult*) override { return 0; }
    void getAllContactManifolds(btManifoldArray&) override {}
};
struct Dispatcher : btDispatcher {
    btCollisionAlgorithm* findAlgorithm(btCollisionObject*,btCollisionObject*,btPersistentManifold*) override { std::abort(); }
    btPersistentManifold* getNewManifold(void*,void*) override { std::abort(); }
    void releaseManifold(btPersistentManifold*) override { std::abort(); }
    void clearManifold(btPersistentManifold*) override { std::abort(); }
    bool needsCollision(btCollisionObject*,btCollisionObject*) override { std::abort(); }
    bool needsResponse(btCollisionObject*,btCollisionObject*) override { std::abort(); }
    void dispatchAllCollisionPairs(btOverlappingPairCache*,const btDispatcherInfo&,btDispatcher*) override { std::abort(); }
    int getNumManifolds() const override { return 0; }
    btPersistentManifold* getManifoldByIndexInternal(int) override { std::abort(); }
    btPersistentManifold** getInternalManifoldPointer() override { std::abort(); }
    void* allocateCollisionAlgorithm(int size) override { return std::malloc(size); }
    void freeCollisionAlgorithm(void* p) override { events += "f" + std::to_string(tokens.at(p)) + ","; tokens.erase(p); std::free(p); }
};
struct Sweep : bt32BitAxisSweep3 {
    Sweep(btVector3 min, btVector3 max, unsigned capacity, btOverlappingPairCache* cache)
        : bt32BitAxisSweep3(min,max,capacity,cache,true) {}
    void dump(const std::set<unsigned>& live) {
        std::cout << "|" << m_numHandles << ":" << m_firstFreeHandle;
        for(int axis=0;axis<3;++axis) {
            std::cout << '|';
            for(unsigned i=0;i<=m_numHandles*2+1;++i) std::cout << i << ':' << m_pEdges[axis][i].m_pos << ':' << m_pEdges[axis][i].m_handle << ',';
        }
        std::cout << '|';
        for(unsigned id:live) {
            auto h=getHandle(id);
            std::cout << id << ':' << h->getUid() << ':' << h->m_collisionFilterGroup << ':' << h->m_collisionFilterMask << ':' << reinterpret_cast<size_t>(h->m_clientObject) << ':' << reinterpret_cast<size_t>(h->m_multiSapParentProxy) << ':';
            for(int axis=0;axis<3;++axis) std::cout << h->m_minEdges[axis] << ':' << h->m_maxEdges[axis] << ':';
            std::cout << ',';
        }
    }
};
float scalar(std::istream& in) { unsigned bits; in>>bits; float f; std::memcpy(&f,&bits,4); return f; }
btVector3 vector(std::istream& in) { float x=scalar(in),y=scalar(in),z=scalar(in); return btVector3(x,y,z); }
int main() {
    btHashedOverlappingPairCache cache; Dispatcher dispatcher;
    std::unique_ptr<Sweep> sweep;
    std::set<unsigned> live;
    std::string line;
    while(std::getline(std::cin,line)) {
        std::istringstream in(line); char op; in>>op;
        events.clear(); std::string result="-";
        if(op=='n') {
            for(int i=0;i<cache.getNumOverlappingPairs();++i) cache.cleanOverlappingPair(cache.getOverlappingPairArray()[i],&dispatcher);
            if(sweep) for(auto id:live) sweep->removeHandle(id,&dispatcher);
            live.clear(); unsigned capacity; in>>capacity; auto min=vector(in); auto max=vector(in);
            sweep.reset(new Sweep(min,max,capacity,&cache));
        }
        if(op=='a') {
            size_t owner,parent; int group,mask; in>>owner>>group>>mask>>parent;
            auto min=vector(in); auto max=vector(in);
            unsigned id=sweep->addHandle(min,max,reinterpret_cast<void*>(owner),short(group),short(mask),&dispatcher,reinterpret_cast<void*>(parent));
            live.insert(id); result=std::to_string(id);
        }
        if(op=='u') { unsigned id; in>>id; auto min=vector(in); auto max=vector(in); sweep->setAabb(sweep->getHandle(id),min,max,&dispatcher); }
        if(op=='r') { unsigned id; in>>id; sweep->removeHandle(id,&dispatcher); live.erase(id); }
        if(op=='z') sweep->resetPool(&dispatcher);
        if(op=='p') sweep->calculateOverlappingPairs(&dispatcher);
        if(op=='q') { unsigned a,b; in>>a>>b; result=std::to_string(sweep->testAabbOverlap(sweep->getHandle(a),sweep->getHandle(b))); }
        if(op=='t') {
            int index,token; size_t data; in>>index>>token>>data; auto &p=cache.getOverlappingPairArray()[index];
            if(!p.m_algorithm) { void* memory=dispatcher.allocateCollisionAlgorithm(sizeof(Algorithm)); tokens[memory]=token; p.m_algorithm=new(memory) Algorithm(token); }
            p.m_internalInfo1=reinterpret_cast<void*>(data);
        }
        if(op=='b') {
            int base; in>>base;
            for(int i=0;i<cache.getNumOverlappingPairs();++i) {
                auto &p=cache.getOverlappingPairArray()[i];
                if(!p.m_algorithm) { void* memory=dispatcher.allocateCollisionAlgorithm(sizeof(Algorithm)); tokens[memory]=base+i; p.m_algorithm=new(memory) Algorithm(base+i); }
                p.m_internalInfo1=reinterpret_cast<void*>(size_t(base+i+100));
            }
        }
        if(op=='c') { int index; in>>index; cache.cleanOverlappingPair(cache.getOverlappingPairArray()[index],&dispatcher); }
        std::cout << result; sweep->dump(live); std::cout << '|';
        for(int i=0;i<cache.getNumOverlappingPairs();++i) { auto &p=cache.getOverlappingPairArray()[i]; std::cout << p.m_pProxy0->getUid() << ':' << p.m_pProxy1->getUid() << ':' << (p.m_algorithm?tokens.at(p.m_algorithm):0) << ':' << reinterpret_cast<size_t>(p.m_internalInfo1) << ','; }
        std::cout << '|' << events << '\n';
    }
    for(int i=0;i<cache.getNumOverlappingPairs();++i) cache.cleanOverlappingPair(cache.getOverlappingPairArray()[i],&dispatcher);
}
