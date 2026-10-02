#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi_material_textures.hpp"
#include <cmath>
#include <cstdio>
#include <cstring>
using Microsoft::WRL::ComPtr;
using namespace mikudancestudio::rhi;
// Minimal shader-batch validation, not a DX11 renderer or pixel-parity claim.
// VS/GS stream output makes matrix orientation and lighting observable before
// rasterization; WARP permits validation without a window or external assets.
int main() {
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;
    D3D_FEATURE_LEVEL level{};
    if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,
        D3D11_SDK_VERSION,&device,&level,&context)))return 77;
    if(level<D3D_FEATURE_LEVEL_11_0)return 77;
    const char* source=R"(
cbuffer Inputs:register(b0) {
 row_major float4x4 world;row_major float4x4 view;row_major float4x4 projection;
 row_major float4x4 normalView;float4 direction;float4 diffuse;
};
struct V {float3 position:POSITION;float3 normal:NORMAL;};
struct O {float4 position:SV_POSITION;float4 color:COLOR;};
O vs(V v) {O o;o.position=mul(mul(mul(float4(v.position,1),world),view),projection);
 o.color=float4(diffuse.rgb*saturate(dot(normalize(mul(float4(v.normal,0),normalView).xyz),-normalize(direction.xyz))),diffuse.a);return o;}
[maxvertexcount(3)] void gs(triangle O v[3],inout TriangleStream<O> output) {
 output.Append(v[0]);output.Append(v[1]);output.Append(v[2]);}
)";
    ComPtr<ID3DBlob> vsCode,gsCode,errors;
    if(FAILED(D3DCompile(source,std::strlen(source),nullptr,nullptr,nullptr,"vs","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vsCode,&errors)) ||
       FAILED(D3DCompile(source,std::strlen(source),nullptr,nullptr,nullptr,"gs","gs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&gsCode,&errors)))return 1;
    ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11GeometryShader> gs;
    D3D11_SO_DECLARATION_ENTRY output[]={{0,"SV_POSITION",0,0,4,0},{0,"COLOR",0,0,4,0}};
    UINT stride=32;
    if(FAILED(device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs)) ||
       FAILED(device->CreateGeometryShaderWithStreamOutput(gsCode->GetBufferPointer(),gsCode->GetBufferSize(),output,2,&stride,1,
           D3D11_SO_NO_RASTERIZED_STREAM,nullptr,&gs)))return 1;
    D3D11_INPUT_ELEMENT_DESC layout[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0}};
    ComPtr<ID3D11InputLayout> inputLayout;
    if(FAILED(device->CreateInputLayout(layout,2,vsCode->GetBufferPointer(),vsCode->GetBufferSize(),&inputLayout)))return 1;
    MaterialShaderInputs s;const std::array<float,16> identity{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    s.world=s.view=s.projection=identity;s.world[12]=3;s.world[13]=-2;s.world[14]=5;
    s.view[0]=0;s.view[2]=-1;s.view[8]=1;s.view[10]=0;
    s.projection={2,0,0,0,0,3,0,0,0,0,2,1,0,0,-2,0};
    s.nativeDiffuse={.8f,.6f,.4f,.5f};s.lights[0].enabled=true;s.lights[0].direction={0,-2,0};
    if(!BuildShaderNormalMatrix(s.world,s.view,s.normalView))return 1;
    if(!ValidateMaterialShaderInputs(s))return 1;
    struct Constants {std::array<float,16> w,v,p,n;std::array<float,4> direction,diffuse;} constants{
        s.world,s.view,s.projection,s.normalView,{0,-2,0,0},s.nativeDiffuse};
    const float vertices[][6]={{1,2,3,0,1,0},{2,3,4,0,-1,0},{-1,0,2,1,0,0}};
    auto buffer=[&](UINT size,UINT bind,const void* data,ComPtr<ID3D11Buffer>& target) {
        D3D11_BUFFER_DESC d{};d.ByteWidth=size;d.Usage=D3D11_USAGE_DEFAULT;d.BindFlags=bind;
        D3D11_SUBRESOURCE_DATA initial{};initial.pSysMem=data;
        return SUCCEEDED(device->CreateBuffer(&d,data?&initial:nullptr,&target));
    };
    ComPtr<ID3D11Buffer> vb,cb,so,readback;
    if(!buffer(sizeof(vertices),D3D11_BIND_VERTEX_BUFFER,vertices,vb)||
       !buffer(sizeof(constants),D3D11_BIND_CONSTANT_BUFFER,&constants,cb)||
       !buffer(96,D3D11_BIND_STREAM_OUTPUT,nullptr,so))return 1;
    D3D11_BUFFER_DESC staging{};staging.ByteWidth=96;staging.Usage=D3D11_USAGE_STAGING;staging.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    if(FAILED(device->CreateBuffer(&staging,nullptr,&readback)))return 1;
    UINT offset=0,vertexStride=24;auto* vertexBuffer=vb.Get();auto* constantBuffer=cb.Get();auto* outputBuffer=so.Get();
    context->IASetInputLayout(inputLayout.Get());context->IASetVertexBuffers(0,1,&vertexBuffer,&vertexStride,&offset);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(vs.Get(),nullptr,0);context->VSSetConstantBuffers(0,1,&constantBuffer);
    context->GSSetShader(gs.Get(),nullptr,0);context->SOSetTargets(1,&outputBuffer,&offset);context->Draw(3,0);
    context->SOSetTargets(0,nullptr,nullptr);context->CopyResource(readback.Get(),so.Get());
    D3D11_MAPPED_SUBRESOURCE mapped{};
    if(FAILED(context->Map(readback.Get(),0,D3D11_MAP_READ,0,&mapped)))return 1;
    const auto* actual=static_cast<const float*>(mapped.pData);bool match=true;
    for(unsigned i=0;i<3;++i) {
        auto position=TransformShaderVector({vertices[i][0],vertices[i][1],vertices[i][2],1},s.world);
        position=TransformShaderVector(position,s.view);position=TransformShaderVector(position,s.projection);
        for(unsigned j=0;j<4;++j) {
            const float expectedColor=j==3?s.nativeDiffuse[3]:i==0?s.nativeDiffuse[j]:0;
            for(auto pair:{std::pair{actual[i*8+j],position[j]},std::pair{actual[i*8+4+j],expectedColor}})
                if(!std::isfinite(pair.first) || std::abs(pair.first-pair.second)>1e-6f) {std::printf("vertex=%u component=%u actual=%g expected=%g\n",i,j,pair.first,pair.second);match=false;}
        }
    }
    context->Unmap(readback.Get(),0);
    std::puts(match?"DX11 WARP VS/GS triangle: matrix/lighting inputs PASS":"DX11 inputs FAIL");
    return match?0:1;
}
