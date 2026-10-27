#include "BulletCollision/BroadphaseCollision/btDbvtBroadphase.h"
#include "BulletCollision/CollisionDispatch/btCollisionDispatcher.h"
#include "BulletCollision/CollisionDispatch/btDefaultCollisionConfiguration.h"
#include "BulletCollision/CollisionDispatch/btCollisionObject.h"
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "LinearMath/btAlignedAllocator.h"
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <fstream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

static const size_t SLOTS = 65536;
static const size_t STRIDE = 128;
static const size_t RAW_NODE_BYTES = sizeof(btDbvtNode) + sizeof(void*) + 15;
alignas(64) static unsigned char arena[SLOTS * STRIDE];
static_assert(sizeof(btDbvtNode) + 16 <= STRIDE && RAW_NODE_BYTES <= STRIDE, "controlled node and header fit slot");
static unsigned allocation_index;
static std::string allocation_mode;
static uint64_t raw_allocs, raw_frees, aligned_allocs, aligned_frees;
struct AllocationEvent {
    bool alloc;
    bool aligned;
    uint64_t ordinal;
    uintptr_t pointer;
    size_t size;
    int alignment;
};
static std::vector<AllocationEvent> events;
static bool in_arena(void* pointer) {
    uintptr_t p = reinterpret_cast<uintptr_t>(pointer), start = reinterpret_cast<uintptr_t>(arena);
    return p >= start && p < start + sizeof(arena);
}
static void* arena_allocate() {
    if (allocation_index >= SLOTS) std::abort();
    size_t i = allocation_index++;
    if (allocation_mode == "descending") i = SLOTS - 1 - i;
    if (allocation_mode == "alternating") i = i % 2 ? SLOTS - 1 - i/2 : i/2;
    return arena + i * STRIDE;
}
static void* allocate_raw(size_t size) {
    ++raw_allocs;
    if (size == RAW_NODE_BYTES) {
        void* p = arena_allocate();
        events.push_back({true, false, raw_allocs, reinterpret_cast<uintptr_t>(p), size, 0});
        return p;
    }
    void* p = std::malloc(size);
    if (!p) std::abort();
    return p;
}
static void deallocate_raw(void* pointer) {
    ++raw_frees;
    if (in_arena(pointer)) {
        events.push_back({false, false, raw_frees, reinterpret_cast<uintptr_t>(pointer), 0, 0});
    } else std::free(pointer);
}
static void* allocate(size_t size, int alignment) {
    ++aligned_allocs;
    if (size == sizeof(btDbvtNode) && alignment == 16) {
        void* p = arena_allocate();
        events.push_back({true, true, aligned_allocs, reinterpret_cast<uintptr_t>(p), size, alignment});
        return p;
    }
    void* raw = std::malloc(size + alignment + sizeof(void*));
    if (!raw) std::abort();
    uintptr_t aligned = (reinterpret_cast<uintptr_t>(raw) + sizeof(void*) + alignment - 1) & ~(uintptr_t(alignment) - 1);
    reinterpret_cast<void**>(aligned)[-1] = raw;
    return reinterpret_cast<void*>(aligned);
}
static void deallocate(void* pointer) {
    ++aligned_frees;
    if (in_arena(pointer)) {
        events.push_back({false, true, aligned_frees, reinterpret_cast<uintptr_t>(pointer), 0, 0});
    } else if (pointer) std::free(reinterpret_cast<void**>(pointer)[-1]);
}
static void receipt(std::ostream& out, const std::string& identity) {
    out << "{\"kind\":" << identity << ",\"counters\":[" << raw_allocs << ',' << raw_frees << ','
        << aligned_allocs << ',' << aligned_frees << "],\"events\":[";
    for (size_t i=0;i<events.size();++i) {
        const auto& e = events[i];
        if (i) out << ',';
        out << "{\"op\":\"" << (e.alloc?"alloc":"free") << "\",\"route\":\"" << (e.aligned?"aligned":"raw")
            << "\",\"ordinal\":" << e.ordinal << ",\"pointer\":" << e.pointer;
        if(e.alloc) out << ",\"size\":" << e.size << ",\"alignment\":" << e.alignment;
        out << '}';
    }
    out << "]}\n";
    out.flush();
    events.clear();
}
static uint32_t bits(btScalar value) {
    static_assert(sizeof(value) == sizeof(uint32_t), "single precision required");
    uint32_t out; std::memcpy(&out, &value, sizeof(out)); return out;
}
static btScalar scalar(uint32_t value) {
    btScalar out; std::memcpy(&out, &value, sizeof(out)); return out;
}
static int id(const btBroadphaseProxy* proxy) {
    auto* object = static_cast<btCollisionObject*>(proxy->m_clientObject);
    return int(reinterpret_cast<intptr_t>(object->getUserPointer())) - 1;
}
struct Dispatcher : btCollisionDispatcher {
    unsigned created = 0;
    std::map<void*, unsigned> generations;
    std::vector<unsigned> releases;
    explicit Dispatcher(btCollisionConfiguration* config) : btCollisionDispatcher(config) {}
    void* allocateCollisionAlgorithm(int size) override {
        void* p = btCollisionDispatcher::allocateCollisionAlgorithm(size);
        if (!generations.emplace(p, ++created).second) std::abort();
        return p;
    }
    void freeCollisionAlgorithm(void* p) override {
        auto found = generations.find(p);
        if (found == generations.end() || size_t(getNumManifolds()) + 1 != generations.size()) std::abort();
        releases.push_back(found->second);
        generations.erase(found);
        btCollisionDispatcher::freeCollisionAlgorithm(p);
    }
};
static void volume(const btDbvtVolume& v) {
    std::cout << '[';
    for (int i=0;i<6;++i) { if(i) std::cout << ','; std::cout << bits(i<3?v.Mins()[i]:v.Maxs()[i-3]); }
    std::cout << ']';
}
static void ranks(const btDbvtNode* n, bool& first) {
    if (!n) return;
    if (!first) std::cout << ',';
    first = false;
    std::cout << '[' << (n->isleaf() ? id(static_cast<btDbvtProxy*>(n->data)) : -1) << ',' << reinterpret_cast<uintptr_t>(n);
    for(int j=0;j<6;++j) std::cout << ',' << bits(j<3?n->volume.Mins()[j]:n->volume.Maxs()[j-3]);
    std::cout << ']';
    if (n->isinternal()) { ranks(n->childs[0],first); ranks(n->childs[1],first); }
}
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    allocation_mode = argv[1];
    if (allocation_mode == "profile") {
        if (argc != 2) return 2;
        std::cout << "{\"pointer_bits\":" << sizeof(void*)*8 << ",\"prevent_false_update\":" << DBVT_BP_PREVENTFALSEUPDATE
            << ",\"accurate_sleeping\":" << DBVT_BP_ACCURATESLEEPING << ",\"margin_bits\":" << bits(DBVT_BP_MARGIN);
#ifdef BT_USE_SSE
        std::cout << ",\"bt_use_sse\":true";
#else
        std::cout << ",\"bt_use_sse\":false";
#endif
#ifdef WIN32
        std::cout << ",\"win32\":true";
#else
        std::cout << ",\"win32\":false";
#endif
        std::cout << "}\n";
        return 0;
    }
    if (allocation_mode != "ordinary" && allocation_mode != "ascending" && allocation_mode != "descending" && allocation_mode != "alternating") return 2;
    if (argc != 3) return 2;
    std::ofstream allocator_receipt(argv[2]);
    if (!allocator_receipt) return 2;
    allocator_receipt << "{\"schema\":1,\"mode\":\"" << allocation_mode << "\",\"hooks\":"
        << (allocation_mode == "ordinary" ? "false" : "true") << ",\"arena_base\":" << reinterpret_cast<uintptr_t>(arena)
        << ",\"slots\":" << SLOTS << ",\"stride\":" << STRIDE << ",\"arena_alignment\":64,\"pointer_bytes\":" << sizeof(void*)
        << ",\"node_bytes\":" << sizeof(btDbvtNode) << ",\"node_alignment\":16,\"bt_has_aligned_allocator\":"
#ifdef BT_HAS_ALIGNED_ALLOCATOR
        << "true"
#else
        << "false"
#endif
        << ",\"bt_debug_memory_allocations\":"
#ifdef BT_DEBUG_MEMORY_ALLOCATIONS
        << "true"
#else
        << "false"
#endif
        << ",\"cellos_lv2\":"
#ifdef __CELLOS_LV2__
        << "true"
#else
        << "false"
#endif
        << "}\n";
    if (sizeof(void*) != 8 || sizeof(btDbvtNode) != 64) return 5;
#if defined(BT_HAS_ALIGNED_ALLOCATOR) || defined(BT_DEBUG_MEMORY_ALLOCATIONS) || defined(__CELLOS_LV2__)
    return 5;
#endif
    if (allocation_mode != "ordinary") {
        btAlignedAllocSetCustomAligned(allocate,deallocate);
        btAlignedAllocSetCustom(allocate_raw,deallocate_raw);
    }
    {
    btDefaultCollisionConfiguration config;
    auto dispatcher = std::unique_ptr<Dispatcher>(new Dispatcher(&config));
    auto bp = std::unique_ptr<btDbvtBroadphase>(new btDbvtBroadphase());
    btSphereShape sphere(1);
    std::array<btCollisionObject,512> objects;
    std::array<btDbvtProxy*,512> proxies{};
    for (int i=0;i<512;++i) {
        objects[i].setCollisionShape(&sphere);
        objects[i].setUserPointer(reinterpret_cast<void*>(intptr_t(i+1)));
        objects[i].setWorldTransform(btTransform::getIdentity());
    }
    std::string line;
    unsigned history=0,checkpoint=0;
    while (std::getline(std::cin,line)) {
        std::istringstream input(line);
        std::string op; input >> op;
        unsigned index=0;
        if (op == "H") {
            input >> history;
            for (auto* p:proxies) if(p) return 3;
            bp.reset(new btDbvtBroadphase()); dispatcher.reset(new Dispatcher(&config));
        } else if (op == "c" || op == "s") {
            input >> index;
            short group=0,mask=0;
            if(op=="c") input >> group >> mask;
            uint32_t raw[6]; for(auto& w:raw) input >> w;
            btVector3 lo(scalar(raw[0]),scalar(raw[1]),scalar(raw[2])),hi(scalar(raw[3]),scalar(raw[4]),scalar(raw[5]));
            if(op=="c") {
                if(proxies[index]) return 3;
                proxies[index]=static_cast<btDbvtProxy*>(bp->createProxy(lo,hi,SPHERE_SHAPE_PROXYTYPE,&objects[index],group,mask,dispatcher.get(),nullptr));
                objects[index].setBroadphaseHandle(proxies[index]);
            } else { if(!proxies[index]) return 3; bp->setAabb(proxies[index],lo,hi,dispatcher.get()); }
        } else if(op=="d") {
            input >> index; if(!proxies[index]) return 3;
            bp->destroyProxy(proxies[index],dispatcher.get()); proxies[index]=nullptr; objects[index].setBroadphaseHandle(nullptr);
        } else if(op=="p") bp->calculateOverlappingPairs(dispatcher.get());
        else if(op=="r") bp->resetPool(dispatcher.get());
        else if(op=="v") { uint32_t raw; input >> raw; bp->setVelocityPrediction(scalar(raw)); }
        else if(op=="n") { btDispatcherInfo info; dispatcher->dispatchAllCollisionPairs(bp->getOverlappingPairCache(),info,dispatcher.get()); }
        else return 2;
        if(!input || (input >> std::ws,!input.eof())) return 4;
        std::cout << '[' << history << ',' << checkpoint++ << ",\"" << op << "\",["
            << bp->m_stageCurrent << ',' << bp->m_fixedleft << ',' << bp->m_newpairs << ','
            << bp->m_updates_call << ',' << bp->m_updates_done << ',' << bits(bp->m_updates_ratio) << ','
            << bp->m_gid << ',' << bp->m_pid << ',' << bp->m_cid << ',' << bp->m_needcleanup << ',' << bits(bp->m_prediction) << ',' << bp->m_fupdates << ',' << bp->m_dupdates << ',' << bp->m_cupdates << ',' << bp->m_releasepaircache << ',' << bp->m_deferedcollide << "],[";
        for(int t=0;t<2;++t) { if(t) std::cout << ','; if(bp->m_sets[t].m_root) volume(bp->m_sets[t].m_root->volume); else std::cout << "null"; }
        std::cout << "],[";
        for(int stage=0;stage<3;++stage) {
            if(stage) std::cout << ','; std::cout << '['; bool first=true;
            for(auto* p=bp->m_stageRoots[stage];p;p=p->links[1]) { if(!first) std::cout << ','; first=false; std::cout << id(p); }
            std::cout << ']';
        }
        std::cout << "],["; bool first=true;
        for(int i=0;i<512;++i) if(auto* p=proxies[i]) {
            if(!first) std::cout << ','; first=false;
            std::cout << '[' << i << ',' << p->m_uniqueId << ',' << p->m_collisionFilterGroup << ',' << p->m_collisionFilterMask << ',' << p->stage;
            for(int j=0;j<6;++j) std::cout << ',' << bits(j<3?p->m_aabbMin[j]:p->m_aabbMax[j-3]);
            for(int j=0;j<6;++j) std::cout << ',' << bits(j<3?p->leaf->volume.Mins()[j]:p->leaf->volume.Maxs()[j-3]);
            std::cout << ']';
        }
        std::cout << "],[";
        const auto& pairs=bp->getOverlappingPairCache()->getOverlappingPairArray();
        for(int i=0;i<pairs.size();++i) {
            if(i) std::cout << ','; auto& p=pairs[i];
            std::cout << '[' << id(p.m_pProxy0) << ',' << id(p.m_pProxy1) << ',' << (p.m_algorithm?dispatcher->generations.at(p.m_algorithm):0) << ']';
        }
        std::cout << "]," << dispatcher->created << ",[";
        for(size_t i=0;i<dispatcher->releases.size();++i) { if(i) std::cout << ','; std::cout << dispatcher->releases[i]; }
        std::cout << "],[";
        for(int i=0;i<dispatcher->getNumManifolds();++i) {
            if(i) std::cout << ','; auto* m=dispatcher->getManifoldByIndexInternal(i);
            auto* a=static_cast<const btCollisionObject*>(m->getBody0()); auto* b=static_cast<const btCollisionObject*>(m->getBody1());
            std::cout << '[' << reinterpret_cast<intptr_t>(a->getUserPointer())-1 << ',' << reinterpret_cast<intptr_t>(b->getUserPointer())-1 << ',' << m->getNumContacts() << ']';
        }
        std::cout << "],[";
        for(int t=0;t<2;++t) {
            if(t) std::cout << ',';
            std::cout << '[' << bp->m_sets[t].m_leaves << ',' << bp->m_sets[t].m_lkhd << ',' << bp->m_sets[t].m_opath << ']';
        }
        std::cout << "],[";
        for(int t=0;t<2;++t) {
            if(t) std::cout << ','; std::cout << "[["; first=true; ranks(bp->m_sets[t].m_root,first); std::cout << "],";
            if(bp->m_sets[t].m_free) std::cout << reinterpret_cast<uintptr_t>(bp->m_sets[t].m_free); else std::cout << "null";
            std::cout << ']';
        }
        std::cout << "]]\n";
        receipt(allocator_receipt, "\"checkpoint\",\"identity\":[" + std::to_string(history) + ','
            + std::to_string(checkpoint-1) + ",\"" + op + "\"]");
    }
    for(auto* p:proxies) if(p) return 3;
    if(!dispatcher->generations.empty() || dispatcher->getNumManifolds()) return 3;
    }
    receipt(allocator_receipt, "\"trailer\"");
    if (!allocator_receipt) return 6;
}
