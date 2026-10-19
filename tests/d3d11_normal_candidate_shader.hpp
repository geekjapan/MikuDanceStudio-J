#pragma once
#include <string>
#include <cstring>

namespace normal_shader_diagnostic {
inline std::string Functions() {
    return R"(
float NormalFusedStep(float a,float b,float c) {
    precise double product=double(a)*double(b);precise double sum=product+double(c);return float(sum);
}
float NormalFusedDot(float3 a,float3 b) {
    float v=NormalFusedStep(a.x,b.x,0);v=NormalFusedStep(a.y,b.y,v);return NormalFusedStep(a.z,b.z,v);
}
float3 NormalFusedTransform(float3 n,row_major float4x4 m) {
    return float3(NormalFusedDot(n,float3(m[0][0],m[1][0],m[2][0])),
        NormalFusedDot(n,float3(m[0][1],m[1][1],m[2][1])),NormalFusedDot(n,float3(m[0][2],m[1][2],m[2][2])));
}
)";
}
// Shares the tested fused dot source with the fixed-matrix probes. Keep the
// existing hardware normalize/rsqrt and light direction expressions intact.
inline std::string Source(const char* production) {
    std::string text=production;
    const char* anchor="float3 normal = mul(float4(input.normal,0),normalView).xyz;";
    const auto at=text.find(anchor);if(at==std::string::npos)return {};
    text.replace(at,std::strlen(anchor),
        "float3 normal;if(diagnosticPolicy.z)normal=NormalFusedTransform(input.normal,normalView);else normal=mul(float4(input.normal,0),normalView).xyz;");
    return Functions()+text;
}
}
