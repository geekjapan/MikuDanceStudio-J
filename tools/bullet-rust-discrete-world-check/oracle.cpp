#include "../../rust/crates/mds-bullet-sys/shim/mds_bt.cpp"
#include "BulletCollision/BroadphaseCollision/btCollisionAlgorithm.h"
#include "allocator.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

static size_t row;
static unsigned next_algorithm, next_manifold;
struct LifetimeLedger {
    struct Entry { const void* pointer; unsigned generation; bool live; } entries[8192]{};
    unsigned count=0;
    unsigned at(const void* p) const { for(unsigned i=0;i<count;++i)if(entries[i].live && entries[i].pointer==p)return entries[i].generation;std::abort(); }
    void add(const void* p,unsigned generation) { if(count==8192)std::abort();for(unsigned i=0;i<count;++i)if(entries[i].live && entries[i].pointer==p)std::abort();entries[count++]={p,generation,true}; }
    void erase(const void* p) { for(unsigned i=0;i<count;++i)if(entries[i].live && entries[i].pointer==p){entries[i].live=false;return;}std::abort(); }
    bool empty() const {for(unsigned i=0;i<count;++i)if(entries[i].live)return false;return true;}
};
static LifetimeLedger algorithms, manifolds;
struct NodeEvent {
    const char* op;
    uint64_t sequence, call, world, generation;
    unsigned tree;
    uintptr_t pointer;
};
struct NodeEntry { uintptr_t pointer; uint64_t generation; unsigned tree; bool cached, live; };
static NodeEvent node_events[65536];
static NodeEntry node_entries[65536];
static size_t node_event_count, node_entry_count;
static uint64_t node_sequence, next_node_call, next_node_generation, world_generation;
static uint64_t node_counters[4];
static const void* node_trees[2];
static unsigned node_tree(const void* tree) {
    for(unsigned i=0;i<2;++i)if(tree==node_trees[i])return i;
    std::abort();
}
static NodeEntry& node_entry(uintptr_t pointer) {
    for(size_t i=0;i<node_entry_count;++i)if(node_entries[i].live && node_entries[i].pointer==pointer)return node_entries[i];
    std::abort();
}
static void node_event(const char* op, unsigned counter, const void* tree, uintptr_t pointer, uint64_t generation, uint64_t call) {
    if(node_event_count==65536)std::abort();
    ++node_counters[counter];
    node_events[node_event_count++]={op,++node_sequence,call,world_generation,generation,node_tree(tree),pointer};
}
extern "C" void* dw_node_alloc(const void* tree) {
    if(node_call || node_entry_count==65536)std::abort();
    const unsigned t=node_tree(tree);
    const uint64_t call=++next_node_call;
    node_call=call;
    void* pointer=btAlignedAlloc(sizeof(btDbvtNode),16);
    node_call=0;
    if(!pointer)std::abort();
    uintptr_t p=reinterpret_cast<uintptr_t>(pointer);
    for(size_t i=0;i<node_entry_count;++i)if(node_entries[i].live && node_entries[i].pointer==p)std::abort();
    node_entries[node_entry_count++]={p,++next_node_generation,t,false,true};
    node_event("alloc",0,tree,p,next_node_generation,call);
    return pointer;
}
extern "C" void dw_node_free(const void* tree, void* pointer) {
    if(node_call)std::abort();
    unsigned t=node_tree(tree);
    uintptr_t p=reinterpret_cast<uintptr_t>(pointer);
    uint64_t generation=0;
    if(pointer) {
        auto& entry=node_entry(p);
        if(entry.tree!=t || !entry.cached)std::abort();
        generation=entry.generation;entry.live=false;
    }
    const uint64_t call=++next_node_call;
    node_call=call;
    btAlignedFree(pointer);
    node_call=0;
    node_event("free",1,tree,p,generation,call);
}
extern "C" void dw_node_reuse(const void* tree, const void* pointer) {
    auto& entry=node_entry(reinterpret_cast<uintptr_t>(pointer));
    if(entry.tree!=node_tree(tree) || !entry.cached)std::abort();
    entry.cached=false;node_event("reuse",2,tree,entry.pointer,entry.generation,0);
}
extern "C" void dw_node_cache(const void* tree, const void* pointer) {
    auto& entry=node_entry(reinterpret_cast<uintptr_t>(pointer));
    if(entry.tree!=node_tree(tree) || entry.cached)std::abort();
    for(size_t i=0;i<node_entry_count;++i)if(node_entries[i].live && node_entries[i].tree==entry.tree && node_entries[i].cached)std::abort();
    entry.cached=true;node_event("cache",3,tree,entry.pointer,entry.generation,0);
}
static void node_receipt(std::ostream& out) {
    out << ",\"world\":" << world_generation << ",\"trees\":[" << reinterpret_cast<uintptr_t>(node_trees[0]) << ',' << reinterpret_cast<uintptr_t>(node_trees[1])
        << "],\"node_counters\":[" << node_counters[0] << ',' << node_counters[1] << ',' << node_counters[2] << ',' << node_counters[3] << "],\"nodes\":[";
    for(size_t i=0;i<node_event_count;++i) {
        const auto& e=node_events[i];if(i)out << ',';
        out << "{\"op\":\"" << e.op << "\",\"sequence\":" << e.sequence << ",\"call\":" << e.call << ",\"world\":" << e.world
            << ",\"tree\":" << e.tree << ",\"pointer\":" << e.pointer << ",\"generation\":" << e.generation << '}';
    }
    out << ']';node_event_count=0;
}
static int owner(const void* p) {
    return int(reinterpret_cast<intptr_t>(static_cast<const btCollisionObject*>(p)->getUserPointer())) - 1;
}
extern "C" void* dw_algorithm_alloc(void* p) {
    algorithms.add(p, ++next_algorithm);
    std::cout << "E " << row << " A+ " << next_algorithm << '\n'; return p;
}
extern "C" void dw_algorithm_free(void* p) {
    std::cout << "E " << row << " A- " << algorithms.at(p) << '\n'; algorithms.erase(p);
}
extern "C" void dw_manifold_alloc(void* p, const void* a, const void* b) {
    manifolds.add(p, ++next_manifold);
    std::cout << "E " << row << " M+ " << next_manifold << ' ' << owner(a) << ' ' << owner(b) << '\n';
}
extern "C" void dw_manifold_free(void* p) {
    std::cout << "E " << row << " M- " << manifolds.at(p) << '\n'; manifolds.erase(p);
}
extern "C" void dw_unregister(const void* p) { std::cout << "E " << row << " U " << owner(p) << '\n'; }
extern "C" void dw_physical(const char* kind, const void* p) {
    std::cerr << "PHYSICAL " << row << ' ' << kind << ' ' << reinterpret_cast<uintptr_t>(p) << ' ' << (std::string(kind)=="body"?owner(p):-1) << '\n';
}
static unsigned bits(float f) { unsigned u; std::memcpy(&u, &f, 4); return u; }
static void scalar(float f) { char text[10]; std::snprintf(text, sizeof(text), "%08x", bits(f)); std::cout << ' ' << text; }
static void vector(const btVector3& v) { for (int i=0; i<3; ++i) scalar(v[i]); }
static void transform(const btTransform& t) { for (int i=0; i<3; ++i) vector(t.getBasis()[i]); vector(t.getOrigin()); }
static float number(std::istringstream& in) { std::string s; in >> s; unsigned u=std::stoul(s,nullptr,16); float f; std::memcpy(&f,&u,4); return f; }
static btTransform pose(std::istringstream& in) {
    float p[3], q[4]; for(auto& f:p) f=number(in); for(auto& f:q) f=number(in); return make_transform(p,q);
}
static void nodes(const btDbvtNode* n) {
    if (!n) return;
    std::cout << ' ' << (n->isleaf()?owner(static_cast<btDbvtProxy*>(n->data)->m_clientObject):-1)
              << ' ' << reinterpret_cast<uintptr_t>(n);
    vector(n->volume.Mins()); vector(n->volume.Maxs());
    if (n->isinternal()) { nodes(n->childs[0]); nodes(n->childs[1]); }
}
static void snapshot(mds_bt_world* w, const std::string& op) {
    if (!w) { std::cout << "O " << row << ' ' << op << " 0 0 0 1\n"; return; }
    auto& pairs=w->bp.getOverlappingPairCache()->getOverlappingPairArray();
    std::cout << "O " << row << ' ' << op << ' ' << w->bodies.size() << ' ' << pairs.size()
              << ' ' << w->disp.getNumManifolds() << ' ' << w->w.getForceUpdateAllAabbs() << '\n';
    for(size_t i=0;i<w->bodies.size();++i) {
        auto* b=w->bodies[i]; auto* proxy=static_cast<btDbvtProxy*>(b->rb->getBroadphaseHandle());
        std::cout << "B " << row << ' ' << i << ' ' << b->rb->getCollisionFlags() << ' ' << b->rb->getActivationState()
                  << ' ' << proxy->m_uniqueId << ' ' << proxy->m_collisionFilterGroup << ' ' << proxy->m_collisionFilterMask
                  << ' ' << owner(proxy->m_clientObject);
        transform(b->rb->getWorldTransform()); transform(b->rb->getInterpolationWorldTransform());
        btTransform motion; b->ms->getWorldTransform(motion); transform(motion);
        vector(proxy->m_aabbMin); vector(proxy->m_aabbMax); vector(proxy->leaf->volume.Mins()); vector(proxy->leaf->volume.Maxs()); std::cout << '\n';
    }
    std::map<const void*,unsigned> manifold_owners;
    for(int i=0;i<pairs.size();++i) {
        auto& p=pairs[i]; unsigned generation=0;
        if(p.m_algorithm) {
#ifdef DW_OBSERVED
            generation=algorithms.at(p.m_algorithm);
#else
            generation=1;
#endif
            btManifoldArray all; p.m_algorithm->getAllContactManifolds(all);
            for(int j=0;j<all.size();++j) manifold_owners[all[j]]=generation;
        }
        std::cout << "P " << row << ' ' << i << ' ' << owner(p.m_pProxy0->m_clientObject) << ' ' << owner(p.m_pProxy1->m_clientObject) << ' ' << generation << '\n';
    }
    for(int i=0;i<w->disp.getNumManifolds();++i) {
        auto* m=w->disp.getManifoldByIndexInternal(i);
        unsigned generation=1;
#ifdef DW_OBSERVED
        generation=manifolds.at(m);
#endif
        std::cout << "M " << row << ' ' << i << ' ' << generation << ' ' << manifold_owners.at(m) << ' ' << owner(m->getBody0()) << ' ' << owner(m->getBody1());
        scalar(m->getContactProcessingThreshold()); scalar(m->getContactBreakingThreshold()); std::cout << ' ' << m->getNumContacts() << '\n';
        for(int j=0;j<m->getNumContacts();++j) {
            auto& p=m->getContactPoint(j); std::cout << "Q " << row << ' ' << i << ' ' << j;
            vector(p.m_localPointA); vector(p.m_localPointB); vector(p.m_positionWorldOnA); vector(p.m_positionWorldOnB); vector(p.m_normalWorldOnB);
            scalar(p.m_distance1); scalar(p.m_combinedFriction); scalar(p.m_combinedRestitution); scalar(p.m_appliedImpulse);
            scalar(p.m_appliedImpulseLateral1); scalar(p.m_appliedImpulseLateral2);
            std::cout << ' ' << p.m_lifeTime << ' ' << int(p.m_lateralFrictionInitialized);
            if(p.m_lateralFrictionInitialized) {vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);} std::cout << '\n';
        }
    }
    for(int t=0;t<2;++t) {
        auto& tree=w->bp.m_sets[t]; std::cout << "T " << row << ' ' << t << ' ' << (tree.m_leaves?2*tree.m_leaves-1:0);
        nodes(tree.m_root); std::cout << ' ' << reinterpret_cast<uintptr_t>(tree.m_free) << '\n';
    }
}
int main(int argc,char** argv) {
#ifdef _WIN32
    _setmode(_fileno(stdout),_O_BINARY);
#endif
    if(argc!=3) return 2; allocation_mode=argv[1];
    if(allocation_mode!="ordinary" && allocation_mode!="ascending" && allocation_mode!="descending" && allocation_mode!="alternating") return 2;
    std::ofstream allocations(argv[2]); if(!allocations) return 2;
    const char* domain=
#ifdef DW_OBSERVED
        "generated-dbvt-node-sites";
#else
        "unmodified-control";
#endif
    allocations << "{\"schema\":2,\"domain\":\"" << domain << "\",\"mode\":\"" << allocation_mode << "\",\"arena_base\":" << reinterpret_cast<uintptr_t>(arena)
                << ",\"slots\":" << SLOTS << ",\"stride\":" << STRIDE << ",\"node_bytes\":" << sizeof(btDbvtNode)
                << ",\"raw_node_bytes\":" << RAW_NODE_BYTES << ",\"node_type_alignment\":" << alignof(btDbvtNode) << "}\n";
    if(allocation_mode!="ordinary") {btAlignedAllocSetCustomAligned(allocate,deallocate);btAlignedAllocSetCustom(allocate_raw,deallocate_raw);}
    mds_bt_world* w=nullptr; std::string line;
    while(std::getline(std::cin,line)) {
        std::istringstream in(line); std::string op; in>>op;
        if(op=="H") {if(w) return 3; std::string name,scope;in>>name>>scope;w=mds_bt_world_create();if(!w)return 3;++world_generation;node_trees[0]=&w->bp.m_sets[0];node_trees[1]=&w->bp.m_sets[1];}
        else if(!w)return 3;
        else if(op=="C") {
            mds_bt_body_desc d{}; in>>d.shape_kind; d.mass=number(in); in>>d.kinematic;
            int group,mask;in>>group>>mask;d.has_filter=1;d.collision_group=static_cast<uint16_t>(group);d.collision_mask=static_cast<uint16_t>(mask);
            for(auto& f:d.shape_params)f=number(in);for(auto& f:d.position)f=number(in);for(auto& f:d.rotation)f=number(in);d.friction=.5f;
            mds_bt_body* b=nullptr;if(mds_bt_body_create(w,&d,&b)!=0)return 4;
            b->rb->setUserPointer(reinterpret_cast<void*>(intptr_t(w->bodies.size())));
        } else if(op=="D")w->w.performDiscreteCollisionDetection();
        else if(op=="U")w->w.updateAabbs();
        else if(op=="F") {int on;in>>on;w->w.setForceUpdateAllAabbs(on!=0);}
        else if(op=="S") {size_t i;in>>i;w->w.updateSingleAabb(w->bodies.at(i)->rb);}
        else if(op=="A") {size_t i;int state;in>>i>>state;w->bodies.at(i)->rb->forceActivationState(state);}
        else if(op=="I") {size_t i;int flags;in>>i>>flags;w->bodies.at(i)->rb->setCollisionFlags(flags);}
        else if(op=="T" || op=="V") {
            size_t i;in>>i;std::string which="public";if(op=="V")in>>which;float position[3],rotation[4];for(auto& f:position)f=number(in);for(auto& f:rotation)f=number(in);auto t=make_transform(position,rotation);auto* b=w->bodies.at(i);
            if(which=="current")b->rb->setWorldTransform(t);
            else if(which=="interpolation")b->rb->setInterpolationWorldTransform(t);
            else if(which=="motion")b->ms->setWorldTransform(t);
            else {if(mds_bt_body_set_transform(w,b,position,rotation)!=0)return 4;}
        } else if(op=="J") {
            size_t a,b;int disabled;in>>a>>b>>disabled;mds_bt_joint_desc d{};d.body_a=w->bodies.at(a);d.body_b=w->bodies.at(b);
            d.frame_a_rotation[3]=d.frame_b_rotation[3]=1;d.disable_collision_between_bodies=disabled;
            mds_bt_joint* joint=nullptr;if(mds_bt_joint_create(w,&d,&joint)!=0)return 4;std::cerr<<"JOINT_CREATE "<<row<<' '<<w->joints.size()-1<<' '<<reinterpret_cast<uintptr_t>(joint->c)<<'\n';
        } else if(op=="X") {mds_bt_world_destroy(w);w=nullptr;
#ifdef DW_OBSERVED
            if(!algorithms.empty() || !manifolds.empty())return 5;
#endif
            int64_t counts[3];if(mds_bt_live_counts(counts)!=0 || counts[0] || counts[1] || counts[2])return 5;
        } else return 2;
        if(!in || (in>>std::ws,!in.eof()))return 2;
        snapshot(w,op);receipt(allocations,std::to_string(row));++row;
    }
    if(w)return 3;std::cout<<"Z "<<row<<'\n';receipt(allocations,"\"final\"");
}
