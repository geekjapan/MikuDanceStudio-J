#pragma once
#include <string>
#include <cstring>
#include "depth_transform_arithmetic.hpp"

namespace w_shader_diagnostic {
struct Constants {depth_diagnostic::Matrix combined;std::array<unsigned,4> policy{};};
static_assert(sizeof(Constants)==80,"diagnostic b1 layout");
inline Constants Inputs(const depth_diagnostic::Matrix& world,const depth_diagnostic::Matrix& view,
    const depth_diagnostic::Matrix& projection,unsigned policy) {
    return {depth_diagnostic::Multiply(depth_diagnostic::Multiply(world,view,depth_diagnostic::Rounding::Sequential),projection,depth_diagnostic::Rounding::Sequential),{policy,0,0,0}};
}
inline std::string Source(const char* production) {
    std::string source=production;
    const char* anchor="output.position = mul(camera,projection);";const auto at=source.find(anchor);
    if(at==std::string::npos)return {};
    source.insert(at+std::strlen(anchor),R"(
    if(diagnosticPolicy.x) {
        if(diagnosticPolicy.x>=2) output.position=mul(float4(input.position,1),diagnosticCombined);
        output.position.w=DiagnosticFusedW(float4(input.position,1));
        if(diagnosticPolicy.x>=3) output.position.z=DiagnosticZ(float4(input.position,1));
        if(diagnosticPolicy.w & 2) {
            output.position.x=DiagnosticFusedAxis(float4(input.position,1),0);
            output.position.y=DiagnosticFusedAxis(float4(input.position,1),1);
        }
    }
)");
    const char* center="output.position.xy += float2(1/parameters.y,-1/parameters.z)*output.position.w;";
    const auto centerAt=source.find(center);if(centerAt==std::string::npos)return {};
    source.replace(centerAt,std::strlen(center),std::string("if(!(diagnosticPolicy.w & 1)) ")+center);
    return R"(
cbuffer DiagnosticWInputs:register(b1) {row_major float4x4 diagnosticCombined;uint4 diagnosticPolicy;};
// Float operands multiply exactly in double; round each product+accumulator
// back to float. GPU output is validated against CPU std::fma for tested inputs.
float DiagnosticFusedStep(float a,float b,float accumulator) {
    precise double product=double(a)*double(b);
    precise double sum=product+double(accumulator);
    return float(sum);
}
float DiagnosticFusedW(float4 p) {
    float value=DiagnosticFusedStep(p.x,diagnosticCombined[0][3],0);
    value=DiagnosticFusedStep(p.y,diagnosticCombined[1][3],value);
    value=DiagnosticFusedStep(p.z,diagnosticCombined[2][3],value);
    return DiagnosticFusedStep(p.w,diagnosticCombined[3][3],value);
}
float DiagnosticFusedAxis(float4 p,uint axis) {
    float value=DiagnosticFusedStep(p.x,diagnosticCombined[0][axis],0);
    value=DiagnosticFusedStep(p.y,diagnosticCombined[1][axis],value);
    value=DiagnosticFusedStep(p.z,diagnosticCombined[2][axis],value);
    return DiagnosticFusedStep(p.w,diagnosticCombined[3][axis],value);
}
// Policies 3/4/5 hold combined X/Y and fused W fixed, varying only Z.
float DiagnosticZ(float4 p) {
    float4 column=float4(diagnosticCombined[0][2],diagnosticCombined[1][2],diagnosticCombined[2][2],diagnosticCombined[3][2]);
    if(diagnosticPolicy.x==3) {
        float value=DiagnosticFusedStep(p.x,column.x,0);
        value=DiagnosticFusedStep(p.y,column.y,value);
        value=DiagnosticFusedStep(p.z,column.z,value);
        return DiagnosticFusedStep(p.w,column.w,value);
    }
    if(diagnosticPolicy.x==4) {
        precise double a=double(p.x)*double(column.x),b=double(p.y)*double(column.y);
        precise double c=double(p.z)*double(column.z),d=double(p.w)*double(column.w);
        precise double ab=a+b;precise double abc=ab+c;precise double sum=abc+d;
        return float(sum);
    }
    precise float a=p.x*column.x,b=p.y*column.y,c=p.z*column.z,d=p.w*column.w;
    precise float ab=a+b;precise float abc=ab+c;precise float sum=abc+d;
    return sum;
}
)"+source;
}
inline depth_diagnostic::Rounding ZRounding(unsigned policy) {
    return policy==3?depth_diagnostic::Rounding::Fused:policy==4?depth_diagnostic::Rounding::Double:depth_diagnostic::Rounding::Sequential;
}
}
