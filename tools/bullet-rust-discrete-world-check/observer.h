#pragma once
extern "C" void* dw_algorithm_alloc(void*);
extern "C" void dw_algorithm_free(void*);
extern "C" void dw_manifold_alloc(void*, const void*, const void*);
extern "C" void dw_manifold_free(void*);
extern "C" void dw_unregister(const void*);
extern "C" void dw_physical(const char*, const void*);
