#pragma once
#include <cmath>

// Deterministic float transcendentals. The platform libm may round float
// sinf/acosf differently on macOS arm64, macOS x86_64, and Linux, so the
// portable evaluator computes in double and rounds once to float. Add a
// function here before using any other libm call on the trace path.
namespace mikudancestudio::det {
inline float Acos(float x) {
    return static_cast<float>(std::acos(static_cast<double>(x)));
}
inline float Sin(float x) {
    return static_cast<float>(std::sin(static_cast<double>(x)));
}
}
