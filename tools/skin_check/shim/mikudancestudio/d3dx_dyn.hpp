// The D3DX facade, computed by mds-math through tools/skin_check/ffi.
// Only the entries the loaders and the skinning call exist; anything else is
// a compile error.
#pragma once
#include <Windows.h>
extern "C" {
void mds_d3dx_quat_from_matrix(float* out, const float* m);
void mds_d3dx_matrix_rotation_quaternion(float* out, const float* q);
void mds_d3dx_vec3_normalize(float* out, const float* v);
void mds_d3dx_matrix_multiply(float* out, const float* a, const float* b);
void mds_d3dx_matrix_translation(float* out, float x, float y, float z);
void mds_d3dx_matrix_rotation_x(float* out, float angle);
void mds_d3dx_matrix_rotation_y(float* out, float angle);
void mds_d3dx_matrix_rotation_z(float* out, float angle);
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
    static D3DXMATRIXF* translation(D3DXMATRIXF* out, float x, float y, float z) {
        mds_d3dx_matrix_translation(&out->m[0][0], x, y, z);
        return out;
    }
    static D3DXMATRIXF* rotX(D3DXMATRIXF* out, float angle) {
        mds_d3dx_matrix_rotation_x(&out->m[0][0], angle);
        return out;
    }
    static D3DXMATRIXF* rotY(D3DXMATRIXF* out, float angle) {
        mds_d3dx_matrix_rotation_y(&out->m[0][0], angle);
        return out;
    }
    static D3DXMATRIXF* rotZ(D3DXMATRIXF* out, float angle) {
        mds_d3dx_matrix_rotation_z(&out->m[0][0], angle);
        return out;
    }
};
inline Api& Get() {
    static Api api;
    return api;
}
} // namespace mikudancestudio::d3dx
