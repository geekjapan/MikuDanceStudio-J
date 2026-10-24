// Stand-in for the D3DX facade. The check uses no fixed-axis bones, so the
// twist-correction branch that calls these never runs; null entries make a
// stray call fail loudly.
#pragma once
namespace mikudancestudio::d3dx {
struct Api {
    float* (*vec3Normalize)(float*, const float*) = nullptr;
    void (*quatToAxisAngle)(const float*, float*, float*) = nullptr;
    float* (*quatNormalize)(float*, const float*) = nullptr;
};
inline Api& Get() { static Api api; return api; }
}  // namespace mikudancestudio::d3dx
