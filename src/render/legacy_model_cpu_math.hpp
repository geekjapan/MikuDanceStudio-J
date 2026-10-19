#pragma once
#include "mikudancestudio/d3dx_dyn.hpp"
#include "mikudancestudio/render_model_inputs.hpp"
#include <cstring>
// Measured CPU arithmetic shared by the original renderer and the input
// producer. No graphics device or GPU state is involved.
namespace mikudancestudio {
inline void LegacyModelCross3(float out[3], const float left[3], const float right[3]) {
#if defined(_M_IX86)
    // 0x491BB0..0x491C1A / 0x491C31..0x491C8D keep each
    // multiply-subtract in the x87 register stack until the float store.
    // A double-based equivalent differs by a few ULP after normalization.
    float* destination = out;
    const float* lhs = left;
    const float* rhs = right;
    __asm {
        mov eax, lhs
        mov ecx, rhs
        mov edx, destination

        fld dword ptr [eax + 4]
        fmul dword ptr [ecx + 8]
        fld dword ptr [eax + 8]
        fmul dword ptr [ecx + 4]
        fsubp st(1), st(0)
        fstp dword ptr [edx]

        fld dword ptr [eax + 8]
        fmul dword ptr [ecx]
        fld dword ptr [eax]
        fmul dword ptr [ecx + 8]
        fsubp st(1), st(0)
        fstp dword ptr [edx + 4]

        fld dword ptr [eax]
        fmul dword ptr [ecx + 4]
        fld dword ptr [eax + 4]
        fmul dword ptr [ecx]
        fsubp st(1), st(0)
        fstp dword ptr [edx + 8]
    }
#else
    out[0] = static_cast<float>(
        static_cast<double>(left[1]) * right[2] -
        static_cast<double>(left[2]) * right[1]);
    out[1] = static_cast<float>(
        static_cast<double>(left[2]) * right[0] -
        static_cast<double>(left[0]) * right[2]);
    out[2] = static_cast<float>(
        static_cast<double>(left[0]) * right[1] -
        static_cast<double>(left[1]) * right[0]);
#endif
}

inline render::ModelInputMath LegacyCpuRenderMath() {
    using Matrix=d3dx::D3DXMATRIXF;render::ModelInputMath math;
    math.multiply=[](render::ModelMatrix& out,const render::ModelMatrix& a,const render::ModelMatrix& b){
        Matrix x,y,z;std::memcpy(&x,a.data(),64);std::memcpy(&y,b.data(),64);d3dx::Get().multiply(&z,&x,&y);std::memcpy(out.data(),&z,64);};
    math.cross=[](const std::array<float,3>& a,const std::array<float,3>& b){std::array<float,3> out;LegacyModelCross3(out.data(),a.data(),b.data());return out;};
    math.normalize=[](std::array<float,3>& a){d3dx::Get().vec3Normalize(a.data(),a.data());};
    math.rotateX=[](render::ModelMatrix& out,float angle){Matrix m;d3dx::Get().rotX(&m,angle);std::memcpy(out.data(),&m,64);};
    math.lookAt=[](render::ModelMatrix& out,const std::array<float,3>& eye){const float at[]={eye[0],eye[1],eye[2]+80};const float up[]={0,1,0};
        Matrix m;d3dx::Get().lookAtLH(&m,eye.data(),at,up);std::memcpy(out.data(),&m,64);};
    math.perspective=[](render::ModelMatrix& out,float fov,float aspect,float nearPlane,float farPlane){Matrix m;
        d3dx::Get().perspectiveFovLH(&m,fov,aspect,nearPlane,farPlane);std::memcpy(out.data(),&m,64);};return math;
}

}
