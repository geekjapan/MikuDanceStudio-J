// Frozen pre-refactor x86 oracle; see mmd_math_x87_reference.cpp.
#pragma once
namespace mmd_math_x87_reference {
float sinTimes(float angle, float factor);
float cosine(float angle);
void integrateRotation(const float* w, float dt, float* axis, float* pdw);
}
