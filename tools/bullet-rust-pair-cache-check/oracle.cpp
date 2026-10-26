// Test driver of the real, unmodified vendored Bullet cache.
#include "BulletCollision/BroadphaseCollision/btOverlappingPairCache.h"
#include "BulletCollision/BroadphaseCollision/btDispatcher.h"
#include "BulletCollision/BroadphaseCollision/btCollisionAlgorithm.h"
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <cstdlib>
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
struct Cache : btHashedOverlappingPairCache {
    void tables() {
        std::cout << "|" << getOverlappingPairArray().capacity() << "|";
        for (int i=0;i<m_hashTable.size();++i) std::cout << m_hashTable[i] << ',';
        std::cout << '|';
        for (int i=0;i<getNumOverlappingPairs();++i) std::cout << m_next[i] << ',';
    }
};
struct Visit : btOverlapCallback {
    btBroadphaseProxy* base; int modulus;
    bool processOverlap(btBroadphasePair& p) override {
        events += "v" + std::to_string(p.m_pProxy0-base) + ":" + std::to_string(p.m_pProxy1-base) + ",";
        return ((p.m_pProxy0-base)+(p.m_pProxy1-base)) % modulus == 0;
    }
};
int main() {
    Cache cache; Dispatcher dispatcher;
    btBroadphaseProxy proxies[48];
    for (int i=0;i<48;++i) { proxies[i].m_uniqueId=i+1; proxies[i].m_collisionFilterGroup=1; proxies[i].m_collisionFilterMask=-1; }
    std::string line;
    while (std::getline(std::cin,line)) {
        std::istringstream in(line); char op; long long a=0,b=0,c=0,d=0; in>>op>>a>>b>>c>>d;
        events.clear(); std::string result="-";
        auto index=[&](btBroadphasePair* p) { return p ? std::to_string(p-&cache.getOverlappingPairArray()[0]) : "-"; };
        if (op=='s') { proxies[a].m_uniqueId=int(b); proxies[a].m_collisionFilterGroup=short(c); proxies[a].m_collisionFilterMask=short(d); }
        if (op=='a') result=index(cache.addOverlappingPair(&proxies[a],&proxies[b]));
        if (op=='f') result=index(cache.findPair(&proxies[a],&proxies[b]));
        if (op=='r') { bool present=cache.findPair(&proxies[a],&proxies[b]); void* data=cache.removeOverlappingPair(&proxies[a],&proxies[b],&dispatcher); if(present) result=std::to_string(reinterpret_cast<size_t>(data)); }
        if (op=='t') { auto &p=cache.getOverlappingPairArray()[a]; if(!p.m_algorithm) { void* memory=dispatcher.allocateCollisionAlgorithm(sizeof(Algorithm)); tokens[memory]=int(b); p.m_algorithm=new(memory) Algorithm(int(b)); } p.m_internalInfo1=reinterpret_cast<void*>(size_t(c)); }
        if (op=='c') cache.cleanOverlappingPair(cache.getOverlappingPairArray()[a],&dispatcher);
        if (op=='x') cache.cleanProxyFromPairs(&proxies[a],&dispatcher);
        if (op=='p') cache.removeOverlappingPairsContainingProxy(&proxies[a],&dispatcher);
        if (op=='v') { Visit visit; visit.base=proxies; visit.modulus=int(a); cache.processAllOverlappingPairs(&visit,&dispatcher); }
        if (op=='q') { btBroadphasePair p(proxies[a],proxies[b]); result=std::to_string(p.m_pProxy0-proxies)+":"+std::to_string(p.m_pProxy1-proxies); }
        std::cout << result << '|';
        for(int i=0;i<cache.getNumOverlappingPairs();++i) { auto &p=cache.getOverlappingPairArray()[i]; std::cout << p.m_pProxy0-proxies << ':' << p.m_pProxy1-proxies << ':' << p.m_pProxy0->getUid() << ':' << p.m_pProxy1->getUid() << ':' << (p.m_algorithm?tokens.at(p.m_algorithm):0) << ':' << reinterpret_cast<size_t>(p.m_internalInfo1) << ','; }
        cache.tables(); std::cout << '|' << events << '\n';
    }
    for(int i=0;i<cache.getNumOverlappingPairs();++i) cache.cleanOverlappingPair(cache.getOverlappingPairArray()[i],&dispatcher);
}
