#pragma once
extern "C" void* dw_algorithm_alloc(void*);
extern "C" void dw_algorithm_free(void*);
extern "C" void dw_manifold_alloc(void*, const void*, const void*);
extern "C" void dw_manifold_free(void*);
extern "C" void dw_unregister(const void*);
extern "C" void dw_physical(const char*, const void*);
extern "C" void dw_update(const void*, int);
#include <cstddef>
extern "C" void dw_allocation(int, const void*, size_t, int);
