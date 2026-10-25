// Stand-in for the D3DX facade with the arithmetic of rust/crates/mds-math,
// whose bit equality with d3dx9_43.dll its own fixtures check. run.sh
// generates rsqrt_table.inc from mds-math's RSQRT table. The check model is
// PMX, so the PMD axis normalize never runs; its null entry makes a stray
// call fail loudly.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
namespace mikudancestudio::d3dx {
namespace detail {
inline constexpr std::uint32_t kRsqrt[2048] = {
#include "rsqrt_table.inc"
};
// mds_math::rsqrt_estimate: rsqrtss as the reference CPU computes it.
inline float RsqrtEstimate(float x) {
    std::uint32_t b, r;
    std::memcpy(&b, &x, 4);
    const std::uint32_t exp = (b >> 23) & 0xff;
    if ((b & 0x7fffffff) > 0x7f800000) {
        r = b | 0x400000;
    } else if (b >> 31) {
        r = exp == 0 ? 0xff800000 : 0xffc00000;
    } else if (exp == 0) {
        r = 0x7f800000;
    } else if (exp == 255) {
        r = 0;
    } else {
        const std::int32_t shift = (static_cast<std::int32_t>(exp) - 126 - static_cast<std::int32_t>(exp & 1)) / 2;
        r = static_cast<std::uint32_t>(static_cast<std::int32_t>(kRsqrt[(b >> 13) & 0x7ff]) - shift * (1 << 23));
    }
    float f;
    std::memcpy(&f, &r, 4);
    return f;
}
inline float* QuatNormalize(float* out, const float* q) {
    const float dot = ((q[0] * q[0] + q[1] * q[1]) + q[2] * q[2]) + q[3] * q[3];
    if (dot == 0.0f) {
        for (int i = 0; i < 4; ++i) out[i] = 0.0f;
        return out;
    }
    const float e = RsqrtEstimate(dot);
    const float r = (0.5f * e) * (3.0f - (dot * e) * e);
    for (int i = 0; i < 4; ++i) out[i] = q[i] * r;
    return out;
}
// The axis is (x, y, z) unchanged; both registrars ignore the angle.
inline void QuatToAxisAngle(const float* q, float* axis, float* angle) {
    std::memcpy(axis, q, 12);
    *angle = 2.0f * std::acos(q[3]);
}
}  // namespace detail
struct Api {
    float* (*vec3Normalize)(float*, const float*) = nullptr;
    void (*quatToAxisAngle)(const float*, float*, float*) = detail::QuatToAxisAngle;
    float* (*quatNormalize)(float*, const float*) = detail::QuatNormalize;
};
inline Api& Get() { static Api api; return api; }
}  // namespace mikudancestudio::d3dx
