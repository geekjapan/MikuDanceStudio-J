// Force-included into morph_apply.cpp: its std::acos, std::sin and std::cos
// on floats become the MSVC x64 UCRT acosf, sinf and cosf of mds-crtmath.
// The rest of the checked code calls only sqrt, which is exact everywhere.
#pragma once
#include <cmath>
extern "C" {
float mds_crt_acosf(float);
float mds_crt_sinf(float);
float mds_crt_cosf(float);
}
namespace std {
inline float mds_crt_acos(float x) { return mds_crt_acosf(x); }
inline float mds_crt_sin(float x) { return mds_crt_sinf(x); }
inline float mds_crt_cos(float x) { return mds_crt_cosf(x); }
} // namespace std
#define acos mds_crt_acos
#define sin mds_crt_sin
#define cos mds_crt_cos
