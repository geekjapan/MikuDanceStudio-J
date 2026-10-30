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
#ifdef DW_DYNAMICS
class btCollisionObject;
class btPersistentManifold;
class btTypedConstraint;
extern "C" void dw_return(int);
extern "C" void dw_clock(int, int, float, float);
extern "C" void dw_prepare(int, int);
extern "C" void dw_all_solved();
extern "C" void dw_workspace(int, int);
extern "C" void dw_group(btCollisionObject**, int, btPersistentManifold**, int, btTypedConstraint**, int);
#endif
