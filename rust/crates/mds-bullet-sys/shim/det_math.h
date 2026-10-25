/* Force-included into every Bullet and shim translation unit.
 *
 * 1. The float math functions are the MSVC x64 UCRT ones, through the
 *    bit-exact Rust ports in mds-crtmath (its mds_crt_* C entry points).
 *    MDS_BT_SYSTEM_MATH leaves the platform libm in place.
 * 2. BT_USE_SSE, as the reference build gets it: btScalar.h defines it for
 *    WIN32 && _MSC_VER >= 1400, and CMake's MSVC flags carry /DWIN32. It
 *    selects the SSE rows of the constraint solver (USE_SIMD), whose dot
 *    products sum (z + y) + x. With clang, sse_emu/emmintrin.h computes
 *    the same lanes with scalar float operations on every target. */
#pragma once
#include <math.h>
#ifdef __cplusplus
#include <cmath>
#endif

/* With clang, build.rs puts shim/sse_emu first on the include path, so this
 * and the solver's own #include <emmintrin.h> get the scalar emulation. */
#include <emmintrin.h>
#define BT_USE_SSE

#ifndef MDS_BT_SYSTEM_MATH
#ifdef __cplusplus
extern "C" {
#endif
float mds_crt_sinf(float);
float mds_crt_cosf(float);
float mds_crt_tanf(float);
float mds_crt_asinf(float);
float mds_crt_acosf(float);
float mds_crt_atanf(float);
float mds_crt_atan2f(float, float);
float mds_crt_expf(float);
float mds_crt_logf(float);
float mds_crt_powf(float, float);
#ifdef __cplusplus
}
#endif
#define sinf mds_crt_sinf
#define cosf mds_crt_cosf
#define tanf mds_crt_tanf
#define asinf mds_crt_asinf
#define acosf mds_crt_acosf
#define atanf mds_crt_atanf
#define atan2f mds_crt_atan2f
#define expf mds_crt_expf
#define logf mds_crt_logf
#define powf mds_crt_powf
#endif
