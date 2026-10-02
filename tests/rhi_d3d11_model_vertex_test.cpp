#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi_model_shader_constants.hpp"
#include <filesystem>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <algorithm>
using Microsoft::WRL::ComPtr;
using namespace mikudancestudio::rhi;
int main(int argc,char** argv) {
 const bool vertexByte=argc==2 && !std::strcmp(argv[1],"--vertex-byte");
 if(argc>2 || (argc==2 && !vertexByte))return 1;
 ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;D3D_FEATURE_LEVEL level;
 if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,&level,&context))||level<D3D_FEATURE_LEVEL_11_0)return 77;
 ComPtr<ID3DBlob> vsCode,gsCode,errors;auto path=std::filesystem::path(MDS_SHADER_DIR)/"model_material_vertex.hlsl";
 D3D_SHADER_MACRO macros[]={{"MDS_MODEL_VERTEX_BYTE",vertexByte?"1":"0"},{nullptr,nullptr}};
 if(FAILED(D3DCompileFromFile(path.c_str(),macros,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vsCode,&errors)))return 1;
 const char* gsSource=R"(
 struct O {float4 position:SV_POSITION;float4 diffuse:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 c:TEXCOORD2;float3 specular:COLOR1;};
 [maxvertexcount(3)] void main(triangle O v[3],inout TriangleStream<O> output){output.Append(v[0]);output.Append(v[1]);output.Append(v[2]);})";
 if(FAILED(D3DCompile(gsSource,std::strlen(gsSource),nullptr,nullptr,nullptr,"main","gs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&gsCode,&errors)))return 1;
 D3D11_SO_DECLARATION_ENTRY entries[]={{0,"SV_POSITION",0,0,4,0},{0,"COLOR",0,0,4,0},{0,"TEXCOORD",0,0,2,0},{0,"TEXCOORD",1,0,2,0},{0,"TEXCOORD",2,0,2,0},{0,"COLOR",1,0,3,0}};UINT outStride=17*4;
 ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11GeometryShader> gs;
 if(FAILED(device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs)) || FAILED(device->CreateGeometryShaderWithStreamOutput(gsCode->GetBufferPointer(),gsCode->GetBufferSize(),entries,6,&outStride,1,D3D11_SO_NO_RASTERIZED_STREAM,nullptr,&gs)))return 1;
 D3D11_INPUT_ELEMENT_DESC elements[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},{"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
 ComPtr<ID3D11InputLayout> layout;if(FAILED(device->CreateInputLayout(elements,3,vsCode->GetBufferPointer(),vsCode->GetBufferSize(),&layout)))return 1;
 const std::array<float,16> identity={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
 ModelVertexConstants c{};c.w=c.v=c.p=c.n=identity;c.w[12]=3;c.w[13]=-2;c.w[14]=5;
 c.v[0]=0;c.v[2]=-1;c.v[8]=1;c.v[10]=0;c.p={2,0,0,0,0,3,0,0,0,0,2,1,0,0,-2,0};
 if(!BuildShaderNormalMatrix(c.w,c.v,c.n))return 1;
 c.diffuse={.8f,.6f,.4f,.5f};c.ambient={.2f,.3f,.4f,1};c.specular={.2f,.3f,.4f,0};c.emissive={.05f,.05f,.05f,0};c.globalAmbient={.1f,.1f,.1f,0};
 c.direction[0]={0,-2,0,1};c.lightDiffuse[0]={.4f,.5f,.6f,0};c.lightAmbient[0]={.5f,.5f,.5f,0};c.lightSpecular[0]={.5f,.5f,.5f,0};c.flags={1,1,1,0};c.coordinates={2,0,2,0};c.parameters={2,64,32,0};
 c.transforms[0]=c.transforms[2]=identity;c.transforms[0][0]=.5f;c.transforms[0][5]=.5f;c.transforms[0][12]=c.transforms[0][13]=.5f;
 c.transforms[2]={.25f,0,0,0,0,0,0,0,0,.25f,0,0,.5f,.5f,0,1};
 const float vertices[][8]={{1,2,3,0,2,0,.25f,.75f},{2,3,4,0,-2,0,.5f,.125f},{-1,0,2,2,0,0,.75f,.5f}};
 auto buffer=[&](UINT size,UINT bind,const void* data,ComPtr<ID3D11Buffer>& target){D3D11_BUFFER_DESC d{};d.ByteWidth=size;d.BindFlags=bind;D3D11_SUBRESOURCE_DATA initial{data,0,0};return SUCCEEDED(device->CreateBuffer(&d,data?&initial:nullptr,&target));};
 ComPtr<ID3D11Buffer> vb,cb,so,readback;if(!buffer(sizeof(vertices),D3D11_BIND_VERTEX_BUFFER,vertices,vb)||!buffer(sizeof(c),D3D11_BIND_CONSTANT_BUFFER,&c,cb)||!buffer(3*outStride,D3D11_BIND_STREAM_OUTPUT,nullptr,so))return 1;
 D3D11_BUFFER_DESC staging{};staging.ByteWidth=3*outStride;staging.Usage=D3D11_USAGE_STAGING;staging.CPUAccessFlags=D3D11_CPU_ACCESS_READ;if(FAILED(device->CreateBuffer(&staging,nullptr,&readback)))return 1;
 UINT stride=32,offset=0;auto* vertex=vb.Get();auto* constant=cb.Get();auto* output=so.Get();context->IASetInputLayout(layout.Get());context->IASetVertexBuffers(0,1,&vertex,&stride,&offset);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context->VSSetShader(vs.Get(),nullptr,0);context->VSSetConstantBuffers(0,1,&constant);context->GSSetShader(gs.Get(),nullptr,0);context->SOSetTargets(1,&output,&offset);context->Draw(3,0);context->SOSetTargets(0,nullptr,nullptr);context->CopyResource(readback.Get(),so.Get());
 D3D11_MAPPED_SUBRESOURCE mapped{};if(FAILED(context->Map(readback.Get(),0,D3D11_MAP_READ,0,&mapped)))return 1;
 const float* actual=static_cast<const float*>(mapped.pData);bool pass=true;
 for(unsigned i=0;i<3;++i){std::array<float,17> expected{};auto position=TransformShaderVector({vertices[i][0],vertices[i][1],vertices[i][2],1},c.w);position=TransformShaderVector(position,c.v);position=TransformShaderVector(position,c.p);position[0]+=position[3]/64;position[1]-=position[3]/32;std::copy(position.begin(),position.end(),expected.begin());
  const std::array<float,4> lit=i==0?std::array<float,4>{.49f,.53f,.53f,.5f}:std::array<float,4>{.17f,.23f,.29f,.5f};std::copy(lit.begin(),lit.end(),expected.begin()+4);
  if(vertexByte)for(unsigned j=4;j<8;++j)expected[j]=std::floor(expected[j]*255+.5f)/255;
  expected[8]=.5f;expected[9]=i==0?1.f:i==1?0.f:.5f;expected[10]=vertices[i][6];expected[11]=vertices[i][7];expected[12]=.5f;expected[13]=i==2?.25f:.5f;
  if(i==0){expected[14]=.05f;expected[15]=.075f;expected[16]=.1f;}
  for(unsigned j=0;j<17;++j)if(!std::isfinite(actual[i*17+j])||std::abs(actual[i*17+j]-expected[j])>1e-6f){std::printf("vertex=%u field=%u actual=%g expected=%g\n",i,j,actual[i*17+j],expected[j]);pass=false;}
 }
 context->Unmap(readback.Get(),0);std::puts(pass?"Production model VS: matrices, normal normalization, ambient/diffuse/specular, UV and camera-normal coordinates PASS":"Production model VS FAIL");return pass?0:1;
}
