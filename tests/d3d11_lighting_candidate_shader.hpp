#pragma once
#include <string>
#include <cstring>

namespace lighting_shader_diagnostic {
// Tested float product followed by two fused-like material/color additions.
// Geometry and normal/light computations are deliberately held unchanged.
inline std::string Source(const char* production,bool conditional=false) {
    std::string text=production;
    const char* anchor="color += ambient.rgb*lightAmbient[i].rgb + diffuse.rgb*lightDiffuse[i].rgb*facing;";
    const auto at=text.find(anchor);if(at==std::string::npos)return {};
    const std::string candidate=R"(
        precise float3 scaledMaterial=diffuse.rgb*facing;
        float3 diffuseWithBase=LightingFused(lightDiffuse[i].rgb,scaledMaterial,color);
        color=LightingFused(ambient.rgb,lightAmbient[i].rgb,diffuseWithBase);
)";
    text.replace(at,std::strlen(anchor),conditional?"if(diagnosticPolicy.y){"+candidate+"}else{"+anchor+"}":candidate);
    return R"(
float LightingFusedScalar(float a,float b,float c) {
    precise double product=double(a)*double(b);
    precise double sum=product+double(c);
    return float(sum);
}
float3 LightingFused(float3 a,float3 b,float3 c) {
    return float3(LightingFusedScalar(a.x,b.x,c.x),LightingFusedScalar(a.y,b.y,c.y),LightingFusedScalar(a.z,b.z,c.z));
}
)"+text;
}
}
