#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
static unsigned long long allocation_sequence;
extern "C" void dw_allocation(int alloc, const void* pointer, size_t bytes, int alignment) {
    std::fprintf(stderr, "ALLOC %zu %llu %d %llu %zu %d\n", row, ++allocation_sequence, alloc,
                 static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(pointer)), bytes, alignment);
}
#ifdef DW_DYNAMICS
#include <cstdlib>
#include <cstring>
alignas(4096) static unsigned char mmd_arena[256 * 1024 * 1024];
static size_t arena_low, arena_high=sizeof(mmd_arena), role_live, role_allocations;
static unsigned long long role_sequence;
static const char* allocator_role;
static void* mmd_allocate(size_t bytes) {
    const size_t alignment=alignof(std::max_align_t);
    size_t size=bytes?bytes:1,offset;
    bool descending=std::strcmp(allocator_role,"descending")==0 ||
        (std::strcmp(allocator_role,"alternating")==0 && (role_allocations & 1));
    if(descending) {
        if(size>arena_high)std::abort();
        offset=(arena_high-size) & ~size_t(alignment-1);
        if(offset<arena_low)std::abort();arena_high=offset;
    } else {
        offset=(arena_low+alignment-1) & ~size_t(alignment-1);
        if(offset>arena_high || size>arena_high-offset)std::abort();arena_low=offset+size;
    }
    void* pointer=mmd_arena+offset;++role_live;++role_allocations;
    std::fprintf(stderr,"ROLE %zu %llu A %llu %zu\n",row,++role_sequence,
        static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(pointer)),bytes);
    return pointer;
}
static void mmd_deallocate(void* pointer) {
    if(!role_live)std::abort();--role_live;
    std::fprintf(stderr,"ROLE %zu %llu F %llu 0\n",row,++role_sequence,
        static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(pointer)));
}
static bool dynamics_allocator(const char* role) {
    if(std::strcmp(role,"ordinary") && std::strcmp(role,"ascending") &&
       std::strcmp(role,"descending") && std::strcmp(role,"alternating"))return false;
    allocator_role=role;
    std::fprintf(stderr,"ROLE %zu START %s mmd-raw-request\n",row,role);
    if(std::strcmp(role,"ordinary"))btAlignedAllocSetCustom(mmd_allocate,mmd_deallocate);
    return true;
}
static void dynamics_allocator_closed() {
    if(role_live)std::abort();
    std::fprintf(stderr,"ROLE %zu END %zu\n",row,role_live);
    arena_low=0;arena_high=sizeof(mmd_arena);role_allocations=0;
}
#endif
