#pragma once
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <array>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
#include <map>
#include "mikudancestudio/rhi_d3d9_replay_conversion.hpp"
#include "mikudancestudio/rhi_model_shader_constants.hpp"
#include "rhi_model_shaders.hpp"
#include "../src/render/rhi_model_constants.hpp"
#include "d3d11_w_candidate_shader.hpp"
#include "d3d11_lighting_candidate_shader.hpp"
#include "d3d11_normal_candidate_shader.hpp"

// Production VS source/profile/flags; stream output exposes position before
// rasterization. It is a DX11 observation, never a DX9 fixed-function capture.
inline bool CaptureDepthVertexShader(const mikudancestudio::rhi::D3D9ReplaySnapshot& source,
    std::vector<std::array<float,4>>& positions,std::vector<std::array<float,4>>* cameras=nullptr,bool captureClipBeforeCenter=false,unsigned wCandidatePolicy=0,
    std::vector<std::array<float,4>>* diffuseColors=nullptr,const std::string* diagnosticSource=nullptr,
    const std::array<float,16>* normalMatrixOverride=nullptr,bool normalCandidate=false,
    std::vector<std::array<float,2>>* textureCoordinates=nullptr,unsigned coordinateStage=0,bool viewportCenter=false,bool fusedXY=false,bool productionMeasured=false,
    std::vector<std::array<float,3>>* specularColors=nullptr) {
    using Microsoft::WRL::ComPtr;using namespace mikudancestudio::rhi;
    positions.clear();if(cameras)cameras->clear();if(diffuseColors)diffuseColors->clear();
    if(textureCoordinates){textureCoordinates->clear();if(coordinateStage>2)return false;}
    if(specularColors)specularColors->clear();
    const bool positionColor=source.stride==16 && source.fvf==(D3DFVF_XYZ|D3DFVF_DIFFUSE);
    if((source.stride!=32 && !positionColor) || source.vertexBytes.empty() || source.vertexBytes.size()%source.stride)return false;
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;D3D_FEATURE_LEVEL feature;
    if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,&feature,&context)) || feature<D3D_FEATURE_LEVEL_11_0)return false;
    ComPtr<ID3DBlob> vertexCode,geometryCode,error;
    // A test-owned source override may use the same measured constants for
    // isolated arithmetic probes. It remains explicitly diagnostic source.
    if(productionMeasured && (wCandidatePolicy || normalCandidate || cameras))return false;
    std::string sourceText=productionMeasured?std::string("#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+modelDx9CompatibilitySource+modelVertexSource:modelVertexSource;
    if(diagnosticSource)sourceText=*diagnosticSource;
    if(wCandidatePolicy){D3D11_FEATURE_DATA_DOUBLES support{};if(FAILED(device->CheckFeatureSupport(D3D11_FEATURE_DOUBLES,&support,sizeof(support))) || !support.DoublePrecisionFloatShaderOps)return false;sourceText=w_shader_diagnostic::Source(modelVertexSource);if(sourceText.empty())return false;}
    if(normalCandidate) {
        if(wCandidatePolicy!=3 || diagnosticSource)return false;
        sourceText=normal_shader_diagnostic::Source(lighting_shader_diagnostic::Source(sourceText.c_str(),true).c_str());
        if(sourceText.empty())return false;
    }
    if(cameras) {
        auto at=sourceText.find("float3 specular:COLOR1;");if(at==std::string::npos)return false;
        sourceText.insert(at+std::strlen("float3 specular:COLOR1;")," float4 cameraCapture:TEXCOORD3;");
        if(captureClipBeforeCenter){at=sourceText.find("output.position.xy +=");if(at==std::string::npos)return false;sourceText.insert(at,"output.cameraCapture=output.position; ");}
        else{at=sourceText.find("output.position = mul(camera,projection);");if(at==std::string::npos)return false;sourceText.insert(at,"output.cameraCapture=camera; ");}
    }
    // Test-local bytecode reuse only. Every observation still creates native
    // shader objects, submits vertices and reads fresh GPU stream output.
    static std::map<std::string,ComPtr<ID3DBlob>> compiledVertices;
    const std::string cacheKey=std::string(positionColor?"color:":"normal:")+sourceText;
    const auto previous=compiledVertices.find(cacheKey);
    if(previous!=compiledVertices.end())vertexCode=previous->second;
    else {
        const D3D_SHADER_MACRO macros[]={{"MDS_MODEL_VERTEX_COLOR","1"},{nullptr,nullptr}};
        if(FAILED(D3DCompile(sourceText.data(),sourceText.size(),nullptr,positionColor?macros:nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vertexCode,&error))){if(error)std::fprintf(stderr,"W candidate VS=%s\n",static_cast<const char*>(error->GetBufferPointer()));return false;}
        compiledVertices.emplace(cacheKey,vertexCode);
    }
    std::string geometry=R"(
struct O {float4 p:SV_POSITION;float4 c:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 s:COLOR1;};
[maxvertexcount(1)] void main(point O input[1],inout PointStream<O> output){output.Append(input[0]);})";
    if(cameras)geometry.insert(geometry.find("float3 s:COLOR1;")+std::strlen("float3 s:COLOR1;")," float4 cameraCapture:TEXCOORD3;");
    if(FAILED(D3DCompile(geometry.data(),geometry.size(),nullptr,nullptr,nullptr,"main","gs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&geometryCode,&error)))return false;
    ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11GeometryShader> gs;ComPtr<ID3D11InputLayout> layout;
    std::vector<D3D11_SO_DECLARATION_ENTRY> output{{0,"SV_POSITION",0,0,4,0}};
    if(cameras)output.push_back({0,"TEXCOORD",3,0,4,0});
    if(diffuseColors)output.push_back({0,"COLOR",0,0,4,0});
    const UINT coordinateOffset=16*static_cast<UINT>(output.size());
    // Observe the existing VS semantic; do not encode UV in COLOR or alter the shader.
    if(textureCoordinates)output.push_back({0,"TEXCOORD",coordinateStage,0,2,0});
    const UINT specularOffset=coordinateOffset+(textureCoordinates?8:0);
    if(specularColors)output.push_back({0,"COLOR",1,0,3,0});
    const UINT outputStride=specularOffset+(specularColors?12:0);
    const D3D11_INPUT_ELEMENT_DESC elements[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
    const D3D11_INPUT_ELEMENT_DESC colored[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"COLOR",0,DXGI_FORMAT_R8G8B8A8_UNORM,0,12,D3D11_INPUT_PER_VERTEX_DATA,0}};
    if(FAILED(device->CreateVertexShader(vertexCode->GetBufferPointer(),vertexCode->GetBufferSize(),nullptr,&vs)) ||
       FAILED(device->CreateGeometryShaderWithStreamOutput(geometryCode->GetBufferPointer(),geometryCode->GetBufferSize(),output.data(),static_cast<UINT>(output.size()),&outputStride,1,D3D11_SO_NO_RASTERIZED_STREAM,nullptr,&gs)) ||
       FAILED(device->CreateInputLayout(positionColor?colored:elements,positionColor?2:3,vertexCode->GetBufferPointer(),vertexCode->GetBufferSize(),&layout)))return false;
    ModelVertexConstants constants{};std::memcpy(constants.w.data(),&source.world,64);std::memcpy(constants.v.data(),&source.view,64);std::memcpy(constants.p.data(),&source.projection,64);
    constants.n=constants.w;constants.diffuse={1,0,0,1};constants.parameters={0,float(source.viewport.Width),float(source.viewport.Height),0};
    if(diffuseColors || textureCoordinates || specularColors) {
        ModelReplayStream stream;stream.target.width=source.viewport.X+source.viewport.Width;stream.target.height=source.viewport.Y+source.viewport.Height;
        stream.events.push_back({1,ModelReplayOp::Clear});if(!AppendD3D9ReplaySnapshot(stream,source,positionColor))return false;
        const auto& s=stream.events.back().draw.pipeline.shader;
        constants.n=s.normalView;constants.transforms=s.textureTransforms;constants.diffuse=s.nativeDiffuse;constants.ambient=s.materialAmbient;
        constants.specular=s.materialSpecular;constants.emissive=s.emissive;constants.globalAmbient=s.globalAmbient;
        constants.flags={s.lighting,s.normalizeNormals,s.specularEnabled,s.localViewer};constants.parameters[0]=s.shininess;
        for(unsigned i=0;i<8;++i){const auto& l=s.lights[i];constants.direction[i]={l.direction[0],l.direction[1],l.direction[2],l.enabled?1.f:0.f};
            constants.lightDiffuse[i]=l.diffuse;constants.lightAmbient[i]=l.ambient;constants.lightSpecular[i]=l.specular;}
        for(unsigned i=0;i<3;++i)constants.coordinates[i]=static_cast<unsigned>(s.layout.stages[i].coordinates);
    }
    if(normalMatrixOverride)constants.n=*normalMatrixOverride;
    if(normalCandidate) {
        const auto rounded=depth_diagnostic::Multiply(constants.w,constants.v,depth_diagnostic::Rounding::Sequential);
        const std::array<float,16> identity{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
        if(!BuildShaderNormalMatrix(rounded,identity,constants.n))return false;
    }
    mikudancestudio::rhi::detail::ModelConstants measured;
    if(productionMeasured){ModelReplayStream stream;stream.target.width=source.viewport.X+source.viewport.Width;stream.target.height=source.viewport.Y+source.viewport.Height;
        stream.events.push_back({1,ModelReplayOp::Clear});if(!AppendD3D9ReplaySnapshot(stream,source,positionColor))return false;
        const auto& pipeline=stream.events.back().draw.pipeline;
        if(!mikudancestudio::rhi::detail::BuildModelConstants(pipeline,*pipeline.viewport,true,measured))return false;
        constants=measured.vertex;}
    const UINT count=static_cast<UINT>(source.vertexBytes.size()/source.stride);
    auto buffer=[&](UINT size,UINT bind,const void* data,ComPtr<ID3D11Buffer>& target){D3D11_BUFFER_DESC d{};d.ByteWidth=size;d.BindFlags=bind;D3D11_SUBRESOURCE_DATA initial{data,0,0};return SUCCEEDED(device->CreateBuffer(&d,data?&initial:nullptr,&target));};
    ComPtr<ID3D11Buffer> vb,cb,so,cpu,diagnostic;
    if(!buffer(static_cast<UINT>(source.vertexBytes.size()),D3D11_BIND_VERTEX_BUFFER,source.vertexBytes.data(),vb) || !buffer(sizeof(constants),D3D11_BIND_CONSTANT_BUFFER,&constants,cb) || !buffer(count*outputStride,D3D11_BIND_STREAM_OUTPUT,nullptr,so))return false;
    if(wCandidatePolicy){auto inputs=w_shader_diagnostic::Inputs(constants.w,constants.v,constants.p,wCandidatePolicy);if(normalCandidate){inputs.policy[1]=1;inputs.policy[2]=1;}inputs.policy[3]=(viewportCenter?1:0)|(fusedXY?2:0);
        if(!buffer(sizeof(inputs),D3D11_BIND_CONSTANT_BUFFER,&inputs,diagnostic))return false;auto* extra=diagnostic.Get();context->VSSetConstantBuffers(1,1,&extra);}
    if(productionMeasured){if(!buffer(sizeof(measured.compatibility),D3D11_BIND_CONSTANT_BUFFER,&measured.compatibility,diagnostic))return false;
        auto* extra=diagnostic.Get();context->VSSetConstantBuffers(1,1,&extra);}
    D3D11_BUFFER_DESC staging{};staging.ByteWidth=count*outputStride;staging.Usage=D3D11_USAGE_STAGING;staging.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    if(FAILED(device->CreateBuffer(&staging,nullptr,&cpu)))return false;
    UINT stride=source.stride,offset=0;auto* vertices=vb.Get();auto* uniforms=cb.Get();auto* target=so.Get();
    context->IASetInputLayout(layout.Get());context->IASetVertexBuffers(0,1,&vertices,&stride,&offset);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_POINTLIST);
    context->VSSetShader(vs.Get(),nullptr,0);context->VSSetConstantBuffers(0,1,&uniforms);context->GSSetShader(gs.Get(),nullptr,0);context->SOSetTargets(1,&target,&offset);context->Draw(count,0);
    context->SOSetTargets(0,nullptr,nullptr);context->CopyResource(cpu.Get(),so.Get());D3D11_MAPPED_SUBRESOURCE mapped{};
    if(FAILED(context->Map(cpu.Get(),0,D3D11_MAP_READ,0,&mapped)))return false;
    positions.resize(count);if(cameras)cameras->resize(count);if(diffuseColors)diffuseColors->resize(count);
    if(textureCoordinates)textureCoordinates->resize(count);
    if(specularColors)specularColors->resize(count);
    for(unsigned n=0;n<count;++n){const auto* bytes=static_cast<const unsigned char*>(mapped.pData)+n*outputStride;
        std::memcpy(positions[n].data(),bytes,16);if(cameras)std::memcpy((*cameras)[n].data(),bytes+16,16);
        if(diffuseColors)std::memcpy((*diffuseColors)[n].data(),bytes+(cameras?32:16),16);
        if(textureCoordinates)std::memcpy((*textureCoordinates)[n].data(),bytes+coordinateOffset,8);}
    if(specularColors)for(unsigned n=0;n<count;++n)std::memcpy((*specularColors)[n].data(),static_cast<const unsigned char*>(mapped.pData)+n*outputStride+specularOffset,12);
    context->Unmap(cpu.Get(),0);return true;
}
