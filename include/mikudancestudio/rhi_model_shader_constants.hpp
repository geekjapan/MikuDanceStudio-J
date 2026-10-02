#pragma once
#include "rhi_material_textures.hpp"
namespace mikudancestudio::rhi {
// Constant-buffer transport for the optional shader probe, matching HLSL b0.
// The semantic scene contract remains MaterialShaderInputs.
struct ModelVertexConstants {
    std::array<float,16> w,v,p,n;
    std::array<std::array<float,16>,3> transforms;
    std::array<float,4> diffuse,ambient,specular,emissive,globalAmbient;
    std::array<std::array<float,4>,8> direction,lightDiffuse,lightAmbient,lightSpecular;
    std::array<unsigned,4> flags,coordinates;
    std::array<float,4> parameters;
};
static_assert(sizeof(ModelVertexConstants)==1088,"HLSL constant buffer layout");
}
