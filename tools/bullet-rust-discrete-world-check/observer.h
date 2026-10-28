#pragma once
extern "C" void* dw_algorithm_alloc(void*);
extern "C" void dw_algorithm_free(void*);
extern "C" void dw_manifold_alloc(void*, const void*, const void*);
extern "C" void dw_manifold_free(void*);
extern "C" void dw_unregister(const void*);
extern "C" void dw_physical(const char*, const void*);
extern "C" void* dw_node_alloc(const void*);
extern "C" void dw_node_free(const void*, void*);
extern "C" void dw_node_reuse(const void*, const void*);
extern "C" void dw_node_cache(const void*, const void*);
