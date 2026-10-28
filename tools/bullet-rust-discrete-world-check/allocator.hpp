#include "LinearMath/btAlignedAllocator.h"
#include "BulletCollision/BroadphaseCollision/btDbvt.h"
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <ostream>
static const size_t SLOTS = 65536;
static const size_t STRIDE = 128;
static const size_t RAW_NODE_BYTES = sizeof(btDbvtNode) + sizeof(void*) + 15;
alignas(64) static unsigned char arena[SLOTS * STRIDE];
static_assert(sizeof(btDbvtNode) + 16 <= STRIDE && RAW_NODE_BYTES <= STRIDE, "controlled node and header fit slot");
static_assert(16 % alignof(btDbvtNode) == 0, "requested alignment supports native node");
static unsigned allocation_index;
static std::string allocation_mode;
static uint64_t raw_allocs, raw_frees, aligned_allocs, aligned_frees;
struct AllocationEvent {
    bool alloc;
    bool aligned;
    uint64_t ordinal;
    uint64_t node_call;
    uintptr_t pointer;
    size_t size;
    int alignment;
};
static uint64_t node_call;
static AllocationEvent events[65536];
static size_t event_count;
static void allocation_event(AllocationEvent event) {
    if(event_count==65536)std::abort();
    events[event_count++]=event;
}
static void node_receipt(std::ostream&);
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
        allocation_event({true, false, raw_allocs, node_call, reinterpret_cast<uintptr_t>(p), size, 0});
        return p;
    }
    void* p = std::malloc(size);
    if (!p) std::abort();
    return p;
}
static void deallocate_raw(void* pointer) {
    ++raw_frees;
    if (in_arena(pointer)) {
        allocation_event({false, false, raw_frees, node_call, reinterpret_cast<uintptr_t>(pointer), 0, 0});
    } else std::free(pointer);
}
static void* allocate(size_t size, int alignment) {
    ++aligned_allocs;
    if (size == sizeof(btDbvtNode) && alignment == 16) {
        void* p = arena_allocate();
        allocation_event({true, true, aligned_allocs, node_call, reinterpret_cast<uintptr_t>(p), size, alignment});
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
        allocation_event({false, true, aligned_frees, node_call, reinterpret_cast<uintptr_t>(pointer), 0, 0});
    } else if (pointer) std::free(reinterpret_cast<void**>(pointer)[-1]);
}
static void receipt(std::ostream& out, const std::string& identity) {
    out << "{\"kind\":" << identity << ",\"counters\":[" << raw_allocs << ',' << raw_frees << ','
        << aligned_allocs << ',' << aligned_frees << "],\"events\":[";
    for (size_t i=0;i<event_count;++i) {
        const auto& e = events[i];
        if (i) out << ',';
        out << "{\"op\":\"" << (e.alloc?"alloc":"free") << "\",\"route\":\"" << (e.aligned?"aligned":"raw")
            << "\",\"ordinal\":" << e.ordinal << ",\"node_call\":" << e.node_call << ",\"pointer\":" << e.pointer;
        if(e.alloc) out << ",\"size\":" << e.size << ",\"alignment\":" << e.alignment;
        out << '}';
    }
    out << "]";
    node_receipt(out);
    out << "}\n";
    out.flush();
    event_count=0;
}
