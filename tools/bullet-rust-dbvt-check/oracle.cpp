#include "BulletCollision/BroadphaseCollision/btDbvt.h"
#include "LinearMath/btAlignedAllocator.h"
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <cstring>
#include <cstdlib>
#include <cstdint>

static unsigned char* arena;
static size_t cursor;
static int order;
static constexpr size_t slots=65536, stride=4096;
static void* allocate(size_t size,int alignment) {
    if(size>stride || alignment>16 || cursor>=slots) { std::cerr<<"allocator bound "<<size<<" "<<alignment<<" "<<cursor<<std::endl; std::abort(); }
    size_t i=cursor++;
    size_t rank=order==0 ? i : order==1 ? slots-1-i : (i%2 ? slots-1-i/2 : i/2);
    return arena+rank*stride;
}
static void* allocate_raw(size_t size) { return allocate(size,16); }
static void release(void*) {}
static size_t rank(const btDbvtNode* n) { return (reinterpret_cast<uintptr_t>(n)-reinterpret_cast<uintptr_t>(arena))/stride; }
static void volume(std::ostream& out,const btDbvtVolume& v) {
    for(int k=0;k<2;++k) for(int i=0;i<3;++i) { float f=(k?v.Maxs():v.Mins())[i]; uint32_t bits; std::memcpy(&bits,&f,4); out<<','<<bits; }
}
static void node(std::ostream& out,const btDbvtNode* n,std::ostream& ranks) {
    if(!n) { out<<"_"; return; }
    ranks<<rank(n)<<',';
    if(n->isleaf()) out<<reinterpret_cast<intptr_t>(n->data); else out<<'B';
    volume(out,n->volume);
    if(n->isinternal()) { out<<'('; node(out,n->childs[0],ranks); out<<';'; node(out,n->childs[1],ranks); out<<')'; }
}
struct Policy : btDbvt::ICollide {
    std::ostringstream events;
    void Process(const btDbvtNode* n) override { events<<reinterpret_cast<intptr_t>(n->data)<<','; }
    void Process(const btDbvtNode* a,const btDbvtNode* b) override { events<<reinterpret_cast<intptr_t>(a->data)<<':'<<reinterpret_cast<intptr_t>(b->data)<<','; }
};
static btVector3 vector(std::istream& in) { float x,y,z; in>>x>>y>>z; return btVector3(x,y,z); }
static btDbvtVolume box(std::istream& in) { auto a=vector(in); auto b=vector(in); return btDbvtVolume::FromMM(a,b); }
int main(int argc,char** argv) {
    std::cout.setf(std::ios::unitbuf);
    order=argc>1?std::atoi(argv[1]):0;
    arena=static_cast<unsigned char*>(std::aligned_alloc(16,slots*stride));
    btAlignedAllocSetCustomAligned(allocate,release);
    btAlignedAllocSetCustom(allocate_raw,release);
    {
        btDbvt tree; std::vector<btDbvtNode*> leaves(128,nullptr); std::string line;
        while(std::getline(std::cin,line)) {
            std::istringstream in(line); char op; unsigned key; in>>op; Policy policy;
            if(op=='i') { in>>key; auto v=box(in); leaves[key]=tree.insert(v,reinterpret_cast<void*>(static_cast<intptr_t>(key))); }
            if(op=='u') { in>>key; auto v=box(in); tree.update(leaves[key],v); }
            if(op=='p') { in>>key; auto v=box(in); auto vel=vector(in); float margin; in>>margin; policy.events<<tree.update(leaves[key],v,vel,margin); volume(policy.events,v); }
            if(op=='r') { in>>key; tree.remove(leaves[key]); leaves[key]=nullptr; }
            if(op=='e') { in>>key; int look; in>>look; tree.update(leaves[key],look); }
            if(op=='l') in>>tree.m_lkhd;
            if(op=='n') { int n; in>>n; tree.optimizeIncremental(n); }
            if(op=='t') { int n; in>>n; tree.optimizeTopDown(n); }
            if(op=='b') tree.optimizeBottomUp();
            if(op=='v') { auto v=box(in); tree.collideTV(tree.m_root,v,policy); }
            if(op=='s') tree.collideTT(tree.m_root,tree.m_root,policy);
            if(op=='q') { auto from=vector(in); auto inv=vector(in); unsigned signs[3]={unsigned(inv.x()<0),unsigned(inv.y()<0),unsigned(inv.z()<0)}; float lambda; in>>lambda; auto aabb=box(in); tree.rayTestInternal(tree.m_root,from,from,inv,signs,lambda,aabb.Mins(),aabb.Maxs(),policy); }
            if(op=='c') { tree.clear(); for(auto& n:leaves) n=nullptr; }
            std::ostringstream ranks;
            std::cout<<tree.m_leaves<<','<<tree.m_lkhd<<','<<tree.m_opath<<','<<(tree.m_free?1:0)<<'|';
            node(std::cout,tree.m_root,ranks);
            std::cout<<'|'<<ranks.str(); if(tree.m_free) std::cout<<rank(tree.m_free)<<',';
            std::cout<<'|'<<policy.events.str()<<'\n';
        }
    }
    std::free(arena);
}
