#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
static unsigned long long allocation_sequence;
extern "C" void dw_allocation(int alloc, const void* pointer, size_t bytes, int alignment) {
    std::fprintf(stderr, "ALLOC %zu %llu %d %llu %zu %d\n", row, ++allocation_sequence, alloc,
                 static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(pointer)), bytes, alignment);
}
