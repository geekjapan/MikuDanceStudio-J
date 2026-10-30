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
class btCollisionObject;
class btPersistentManifold;
class btTypedConstraint;
extern "C" void dw_clock(int, int, float, float);
extern "C" void dw_prepare(int, int);
extern "C" void dw_all_solved();
extern "C" void dw_group(btCollisionObject**, int, btPersistentManifold**, int, btTypedConstraint**, int);
extern "C" void dw_workspace(int, int);
