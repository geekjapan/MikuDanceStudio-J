// The D3DX facade, computed by mds-math and mds-kinect through ffi/. Only
// the entries the checked sources call exist; anything else is a compile
// error.
#pragma once
#include <Windows.h>
extern "C" {
void mds_d3dx_quat_from_matrix(float* out, const float* m);
void mds_d3dx_matrix_rotation_quaternion(float* out, const float* q);
void mds_d3dx_vec3_normalize(float* out, const float* v);
void mds_d3dx_matrix_multiply(float* out, const float* a, const float* b);
void mds_d3dx_matrix_rotation_y(float* out, float angle);
void mds_d3dx_quat_multiply(float* out, const float* a, const float* b);
void mds_d3dx_quat_inverse(float* out, const float* q);
void mds_d3dx_quat_rotation_axis(float* out, const float* axis, float angle);
void mds_d3dx_vec3_transform(float* out, const float* v, const float* m);
}
namespace mikudancestudio::d3dx {
struct D3DXMATRIXF {
    float m[4][4];
};
struct Api {
    static float* quatFromMatrix(float* out, const D3DXMATRIXF* m) {
        mds_d3dx_quat_from_matrix(out, &m->m[0][0]);
        return out;
    }
    static D3DXMATRIXF* matrixRotationQuaternion(D3DXMATRIXF* out, const float* q) {
        mds_d3dx_matrix_rotation_quaternion(&out->m[0][0], q);
        return out;
    }
    static float* vec3Normalize(float* out, const float* v) {
        mds_d3dx_vec3_normalize(out, v);
        return out;
    }
    static D3DXMATRIXF* multiply(D3DXMATRIXF* out, const D3DXMATRIXF* a, const D3DXMATRIXF* b) {
        mds_d3dx_matrix_multiply(&out->m[0][0], &a->m[0][0], &b->m[0][0]);
        return out;
    }
    static D3DXMATRIXF* rotY(D3DXMATRIXF* out, float angle) {
        mds_d3dx_matrix_rotation_y(&out->m[0][0], angle);
        return out;
    }
    static float* quatMultiply(float* out, const float* a, const float* b) {
        mds_d3dx_quat_multiply(out, a, b);
        return out;
    }
    static float* quatInverse(float* out, const float* q) {
        mds_d3dx_quat_inverse(out, q);
        return out;
    }
    static float* quatRotationAxis(float* out, const float* axis, float angle) {
        mds_d3dx_quat_rotation_axis(out, axis, angle);
        return out;
    }
    static float* vec3Transform(float* out, const float* v, const D3DXMATRIXF* m) {
        mds_d3dx_vec3_transform(out, v, &m->m[0][0]);
        return out;
    }
};
inline Api& Get() {
    static Api api;
    return api;
}
} // namespace mikudancestudio::d3dx
