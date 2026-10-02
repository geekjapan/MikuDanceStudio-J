#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi_real_batch_capture.hpp"
#include "mikudancestudio/rhi_model_shader_constants.hpp"
#include <filesystem>
#include <fstream>
#include <vector>
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
using Microsoft::WRL::ComPtr;
using namespace mikudancestudio::rhi;
struct PixelConstants {std::array<std::array<unsigned,4>,3> stages{};std::array<unsigned,4> alpha{};};
struct Texture {RealBatchTexture desc;std::vector<std::vector<unsigned char>> mips;};
int Fail(unsigned line){std::fprintf(stderr,"Real-batch replay failed at line %u\n",line);return 1;}
int main(int argc,char** argv) {
 if(argc==2 && !std::strcmp(argv[1],"--history-support")) {
  ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));
  if(!api || FAILED(api->CheckDeviceFormat(0,D3DDEVTYPE_HAL,D3DFMT_X8R8G8B8,D3DUSAGE_DEPTHSTENCIL,D3DRTYPE_TEXTURE,static_cast<D3DFORMAT>(MAKEFOURCC('I','N','T','Z')))) ||
     FAILED(api->CheckDeviceFormat(0,D3DDEVTYPE_HAL,D3DFMT_X8R8G8B8,D3DUSAGE_RENDERTARGET,D3DRTYPE_SURFACE,D3DFMT_R32F)))return 77;
  std::puts("DX9 diagnostic INTZ / R32F history capture supported");return 0;
 }
 bool msaa=false,centroid=false,flat=false,srgbResolve=false,vertexByte=false,noDepth=false,noBlend=false,hardwareVertex=false;
 while(argc>1 && argv[1][0]=='-') {
  if(!std::strcmp(argv[1],"--msaa"))msaa=true;
  else if(!std::strcmp(argv[1],"--centroid"))centroid=true;
  else if(!std::strcmp(argv[1],"--flat"))flat=true;
  else if(!std::strcmp(argv[1],"--srgb-resolve"))srgbResolve=true;
  else if(!std::strcmp(argv[1],"--vertex-byte"))vertexByte=true;
  else if(!std::strcmp(argv[1],"--no-depth"))noDepth=true;
  else if(!std::strcmp(argv[1],"--no-blend"))noBlend=true;
  else if(!std::strcmp(argv[1],"--hardware-vertex"))hardwareVertex=true;
  else return Fail(__LINE__);
  --argc;++argv;
 }
 if(argc!=3)return Fail(__LINE__);
 if(srgbResolve && !msaa)return Fail(__LINE__);
 std::ifstream in(std::filesystem::u8path(argv[1]),std::ios::binary);
 auto read=[&](auto& value){in.read(reinterpret_cast<char*>(&value),sizeof(value));};
 RealBatchCapture h;MaterialShaderInputs s;read(h);
 if(!in || h.magic!=0x3142444d || h.version!=5 || h.inputSize!=sizeof(s) || !h.width || !h.height || h.width>4096 || h.height>4096 || h.vertexBytes%32 || h.indexBytes%2 || h.vertexBytes>32000000 || h.indexBytes>12000000 || !h.count || h.count%3 || h.first>h.indexBytes/2 || h.count>h.indexBytes/2-h.first || h.history>1 || h.vertexProcessing>1)return Fail(__LINE__);
 read(s);if(!ValidateMaterialShaderInputs(s))return Fail(__LINE__);
 std::vector<unsigned char> vbBytes(h.vertexBytes),ibBytes(h.indexBytes);
 in.read(reinterpret_cast<char*>(vbBytes.data()),vbBytes.size());in.read(reinterpret_cast<char*>(ibBytes.data()),ibBytes.size());
 for(unsigned i=0;i<vbBytes.size();i+=4){float value;std::memcpy(&value,vbBytes.data()+i,4);if(!std::isfinite(value))return Fail(__LINE__);}
 for(unsigned i=h.first;i<h.first+h.count;++i){std::uint16_t index;std::memcpy(&index,ibBytes.data()+i*2,2);if(index>=h.vertexBytes/32)return Fail(__LINE__);}
 std::array<Texture,3> textures;
 for(auto& t:textures) {
  read(t.desc);if(!t.desc.levels)continue;
  if(!t.desc.width || !t.desc.height || t.desc.width>4096 || t.desc.height>4096 || t.desc.levels>13)return Fail(__LINE__);
  for(unsigned l=0;l<t.desc.levels;++l){t.mips.emplace_back(std::max(1u,t.desc.width>>l)*std::max(1u,t.desc.height>>l)*4);in.read(reinterpret_cast<char*>(t.mips.back().data()),t.mips.back().size());}
 }
 std::vector<unsigned char> historyColor(h.width*h.height*4,48);
 for(unsigned i=3;i<historyColor.size();i+=4)historyColor[i]=255;
 std::vector<std::uint32_t> historyDepth(h.width*h.height,0x00ffffff);
 if(h.history){if(msaa)return Fail(__LINE__);in.read(reinterpret_cast<char*>(historyColor.data()),historyColor.size());in.read(reinterpret_cast<char*>(historyDepth.data()),historyDepth.size()*4);}
 if(!in || in.peek()!=std::ifstream::traits_type::eof())return Fail(__LINE__);
 // Fixed FVF has no vertex color/UV1; only directional fixed-function lighting.
 if(h.render[D3DRS_FOGENABLE] || h.render[D3DRS_SRGBWRITEENABLE] || h.render[D3DRS_ZENABLE]!=D3DZB_TRUE || h.render[D3DRS_CLIPPLANEENABLE] || h.render[D3DRS_DEPTHBIAS] || h.render[D3DRS_SLOPESCALEDEPTHBIAS] || h.render[D3DRS_TWOSIDEDSTENCILMODE] || h.render[D3DRS_SCISSORTESTENABLE] || h.render[D3DRS_FILLMODE]!=D3DFILL_SOLID)return Fail(__LINE__);
 for(auto& st:s.layout.stages)if(st.role!=MaterialTextureRole::None && st.coordinates==MaterialCoordinates::MeshUv1)return Fail(__LINE__);
 const auto cascadeSupported=[](const MaterialShaderInputs& inputs) {
  std::array<float,4> output;std::array<std::array<float,4>,3> samples{};
  return EvaluateMaterialTextureCascade(inputs.layout,{1,1,1,1},samples,output);
 };
 if(!cascadeSupported(s))return Fail(__LINE__);
 HWND window=CreateWindowW(L"STATIC",L"real batch replay",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
 struct Window {HWND h;~Window(){if(h)DestroyWindow(h);}} cleanup{window};
 ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));ComPtr<IDirect3DDevice9> d9;
 D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.BackBufferWidth=h.width;pp.BackBufferHeight=h.height;pp.hDeviceWindow=window;
 if(!window || !api || FAILED(api->CreateDevice(0,D3DDEVTYPE_HAL,window,hardwareVertex || !h.vertexProcessing?D3DCREATE_HARDWARE_VERTEXPROCESSING:D3DCREATE_SOFTWARE_VERTEXPROCESSING,&pp,&d9)))return 77;
 ComPtr<ID3D11Device> d11;ComPtr<ID3D11DeviceContext> c11;D3D_FEATURE_LEVEL feature;
 if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&d11,&feature,&c11)) || feature<D3D_FEATURE_LEVEL_11_0)return 77;
 D3DADAPTER_IDENTIFIER9 id{};ComPtr<IDXGIDevice> dxgi;ComPtr<IDXGIAdapter> adapter;DXGI_ADAPTER_DESC adapterDesc{};
 if(FAILED(api->GetAdapterIdentifier(0,0,&id)) || FAILED(d11.As(&dxgi)) || FAILED(dxgi->GetAdapter(&adapter)) || FAILED(adapter->GetDesc(&adapterDesc)))return Fail(__LINE__);
 if(id.VendorId!=adapterDesc.VendorId || id.DeviceId!=adapterDesc.DeviceId)return 77;
 const auto sampleType=msaa?static_cast<D3DMULTISAMPLE_TYPE>(h.multisample):D3DMULTISAMPLE_NONE;
 const unsigned sampleCount=msaa?h.multisample:1,quality=msaa?h.multisampleQuality:0;
 if(msaa && (sampleCount<2 || sampleCount>16))return Fail(__LINE__);
 const bool xrgb=h.history && h.colorFormat==D3DFMT_X8R8G8B8;
 const D3DFORMAT targetFormat9=xrgb?D3DFMT_X8R8G8B8:D3DFMT_A8R8G8B8;
 const auto targetFormat11=xrgb?DXGI_FORMAT_B8G8R8X8_UNORM:DXGI_FORMAT_R8G8B8A8_UNORM;
 ComPtr<IDirect3DSurface9> target9,depth9,read9,resolved9;
 if(FAILED(d9->CreateRenderTarget(h.width,h.height,targetFormat9,sampleType,quality,FALSE,&target9,nullptr)) || FAILED(d9->CreateDepthStencilSurface(h.width,h.height,D3DFMT_D24S8,sampleType,quality,TRUE,&depth9,nullptr)) || FAILED(d9->CreateOffscreenPlainSurface(h.width,h.height,targetFormat9,D3DPOOL_SYSTEMMEM,&read9,nullptr)) || FAILED(d9->SetRenderTarget(0,target9.Get())) || FAILED(d9->SetDepthStencilSurface(depth9.Get())))return Fail(__LINE__);
 if(msaa && FAILED(d9->CreateRenderTarget(h.width,h.height,targetFormat9,D3DMULTISAMPLE_NONE,0,FALSE,&resolved9,nullptr)))return Fail(__LINE__);
 if(h.history) {
  // Seed actual color/depth/stencil rather than replaying preceding models.
  // Prior IK/physics/MME evaluation is not moved into the new backend.
  const char* seed=R"(
   sampler2D source:register(s0);float4 reference:register(c0);
   float4 color(float2 uv:TEXCOORD0):COLOR0{return tex2D(source,uv);}
   struct DepthOutput{float4 color:COLOR0;float depth:DEPTH;};
   DepthOutput depth(float2 uv:TEXCOORD0){DepthOutput o;o.color=0;o.depth=tex2D(source,uv).r;return o;}
   float4 stencil(float2 uv:TEXCOORD0):COLOR0{clip(.1-abs(tex2D(source,uv).r*255-reference.x));return 0;})";
  const auto compileSeed=[&](const char* entry,ComPtr<IDirect3DPixelShader9>& shader){ComPtr<ID3DBlob> code,errors;if(FAILED(D3DCompile(seed,std::strlen(seed),nullptr,nullptr,nullptr,entry,"ps_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&errors))){if(errors)std::fwrite(errors->GetBufferPointer(),1,errors->GetBufferSize(),stderr);return false;}return SUCCEEDED(d9->CreatePixelShader(static_cast<const DWORD*>(code->GetBufferPointer()),&shader));};
  ComPtr<IDirect3DPixelShader9> colorShader,depthShader,stencilShader;
  if(!compileSeed("color",colorShader)||!compileSeed("depth",depthShader)||!compileSeed("stencil",stencilShader))return Fail(__LINE__);
  ComPtr<IDirect3DTexture9> colorTexture,depthTexture,stencilTexture;
  if(FAILED(d9->CreateTexture(h.width,h.height,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&colorTexture,nullptr)) ||
     FAILED(d9->CreateTexture(h.width,h.height,1,0,D3DFMT_R32F,D3DPOOL_MANAGED,&depthTexture,nullptr)) ||
     FAILED(d9->CreateTexture(h.width,h.height,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&stencilTexture,nullptr)))return Fail(__LINE__);
  D3DLOCKED_RECT colorLock{},depthLock{},stencilLock{};
  if(FAILED(colorTexture->LockRect(0,&colorLock,nullptr,0))||FAILED(depthTexture->LockRect(0,&depthLock,nullptr,0))||FAILED(stencilTexture->LockRect(0,&stencilLock,nullptr,0)))return Fail(__LINE__);
  std::array<bool,256> refs{};
  for(unsigned y=0;y<h.height;++y)for(unsigned x=0;x<h.width;++x){auto i=y*h.width+x;auto* p=static_cast<unsigned char*>(colorLock.pBits)+y*colorLock.Pitch+x*4;const auto* q=historyColor.data()+i*4;p[0]=q[2];p[1]=q[1];p[2]=q[0];p[3]=q[3];float value=(historyDepth[i]&0xffffff)/16777215.f;std::memcpy(static_cast<unsigned char*>(depthLock.pBits)+y*depthLock.Pitch+x*4,&value,4);std::uint32_t ref=historyDepth[i]>>24;refs[ref]=true;std::uint32_t packed=0xff000000|(ref<<16);std::memcpy(static_cast<unsigned char*>(stencilLock.pBits)+y*stencilLock.Pitch+x*4,&packed,4);}
  if(FAILED(colorTexture->UnlockRect(0))||FAILED(depthTexture->UnlockRect(0))||FAILED(stencilTexture->UnlockRect(0)))return Fail(__LINE__);
  struct ScreenVertex {float x,y,z,w,u,v;};const ScreenVertex quad[]={{-.5f,-.5f,0,1,0,0},{h.width-.5f,-.5f,0,1,1,0},{-.5f,h.height-.5f,0,1,0,1},{h.width-.5f,h.height-.5f,0,1,1,1}};
  const auto state=[&](D3DRENDERSTATETYPE key,DWORD value){return SUCCEEDED(d9->SetRenderState(key,value));};
  if(FAILED(d9->SetFVF(D3DFVF_XYZRHW|D3DFVF_TEX1))||!state(D3DRS_ZENABLE,FALSE)||!state(D3DRS_ZWRITEENABLE,FALSE)||!state(D3DRS_STENCILENABLE,FALSE)||!state(D3DRS_ALPHABLENDENABLE,FALSE)||!state(D3DRS_ALPHATESTENABLE,FALSE)||!state(D3DRS_CULLMODE,D3DCULL_NONE)||!state(D3DRS_COLORWRITEENABLE,15)||!state(D3DRS_SRGBWRITEENABLE,FALSE)||FAILED(d9->BeginScene()))return Fail(__LINE__);
  for(auto key:{D3DSAMP_MINFILTER,D3DSAMP_MAGFILTER})if(FAILED(d9->SetSamplerState(0,key,D3DTEXF_POINT)))return Fail(__LINE__);
  if(FAILED(d9->SetSamplerState(0,D3DSAMP_MIPFILTER,D3DTEXF_NONE))||FAILED(d9->SetPixelShader(colorShader.Get()))||FAILED(d9->SetTexture(0,colorTexture.Get()))||FAILED(d9->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,quad,sizeof(ScreenVertex))))return Fail(__LINE__);
  if(!state(D3DRS_ZENABLE,TRUE)||!state(D3DRS_ZWRITEENABLE,TRUE)||!state(D3DRS_ZFUNC,D3DCMP_ALWAYS)||!state(D3DRS_COLORWRITEENABLE,0)||FAILED(d9->SetPixelShader(depthShader.Get()))||FAILED(d9->SetTexture(0,depthTexture.Get()))||FAILED(d9->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,quad,sizeof(ScreenVertex))))return Fail(__LINE__);
  if(FAILED(d9->Clear(0,nullptr,D3DCLEAR_STENCIL,0,1,0))||!state(D3DRS_ZENABLE,FALSE)||!state(D3DRS_ZWRITEENABLE,FALSE)||!state(D3DRS_STENCILENABLE,TRUE)||!state(D3DRS_STENCILFUNC,D3DCMP_ALWAYS)||!state(D3DRS_STENCILPASS,D3DSTENCILOP_REPLACE)||!state(D3DRS_STENCILMASK,255)||!state(D3DRS_STENCILWRITEMASK,255)||FAILED(d9->SetPixelShader(stencilShader.Get()))||FAILED(d9->SetTexture(0,stencilTexture.Get())))return Fail(__LINE__);
  for(unsigned ref=1;ref<256;++ref)if(refs[ref]){const float constant[]={float(ref),0,0,0};if(!state(D3DRS_STENCILREF,ref)||FAILED(d9->SetPixelShaderConstantF(0,constant,1))||FAILED(d9->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,quad,sizeof(ScreenVertex))))return Fail(__LINE__);}
  if(FAILED(d9->EndScene())||FAILED(d9->SetPixelShader(nullptr))||FAILED(d9->SetTexture(0,nullptr)))return Fail(__LINE__);
 }
 for(unsigned i=1;i<h.render.size();++i)if(h.render[i]!=0xffffffff && FAILED(d9->SetRenderState(static_cast<D3DRENDERSTATETYPE>(i),h.render[i])))return Fail(__LINE__);
 if(noDepth && FAILED(d9->SetRenderState(D3DRS_ZENABLE,FALSE)))return Fail(__LINE__);
 if(noBlend && FAILED(d9->SetRenderState(D3DRS_ALPHABLENDENABLE,FALSE)))return Fail(__LINE__);
 D3DMATERIAL9 material{};auto color=[](const auto& a){return D3DCOLORVALUE{a[0],a[1],a[2],a[3]};};
 material.Diffuse=color(s.nativeDiffuse);material.Ambient=color(s.materialAmbient);material.Specular=color(s.materialSpecular);material.Emissive=color(s.emissive);material.Power=s.shininess;
 if(FAILED(d9->SetMaterial(&material)))return Fail(__LINE__);
 for(auto pair:{std::pair{D3DTS_WORLD,&s.world},std::pair{D3DTS_VIEW,&s.view},std::pair{D3DTS_PROJECTION,&s.projection}})if(FAILED(d9->SetTransform(pair.first,reinterpret_cast<const D3DMATRIX*>(pair.second->data()))))return Fail(__LINE__);
 for(unsigned i=0;i<8;++i)if(s.lights[i].enabled){auto& l=s.lights[i];D3DLIGHT9 light{};light.Type=D3DLIGHT_DIRECTIONAL;light.Direction={l.direction[0],l.direction[1],l.direction[2]};light.Diffuse=color(l.diffuse);light.Ambient=color(l.ambient);light.Specular=color(l.specular);if(FAILED(d9->SetLight(i,&light)) || FAILED(d9->LightEnable(i,TRUE)))return Fail(__LINE__);}
 ComPtr<IDirect3DVertexBuffer9> vb9;ComPtr<IDirect3DIndexBuffer9> ib9;void* data=nullptr;
 if(FAILED(d9->CreateVertexBuffer(h.vertexBytes,0,D3DFVF_XYZ|D3DFVF_NORMAL|D3DFVF_TEX1,D3DPOOL_MANAGED,&vb9,nullptr)) || FAILED(vb9->Lock(0,0,&data,0)))return Fail(__LINE__);std::memcpy(data,vbBytes.data(),vbBytes.size());if(FAILED(vb9->Unlock()))return Fail(__LINE__);
 if(FAILED(d9->CreateIndexBuffer(h.indexBytes,0,D3DFMT_INDEX16,D3DPOOL_MANAGED,&ib9,nullptr)) || FAILED(ib9->Lock(0,0,&data,0)))return Fail(__LINE__);std::memcpy(data,ibBytes.data(),ibBytes.size());if(FAILED(ib9->Unlock()))return Fail(__LINE__);
 if(FAILED(d9->SetFVF(D3DFVF_XYZ|D3DFVF_NORMAL|D3DFVF_TEX1)) || FAILED(d9->SetStreamSource(0,vb9.Get(),0,32)) || FAILED(d9->SetIndices(ib9.Get())))return Fail(__LINE__);
 std::array<ComPtr<IDirect3DTexture9>,3> texture9;std::array<ComPtr<ID3D11Texture2D>,3> texture11;std::array<ComPtr<ID3D11ShaderResourceView>,3> srv;std::array<ComPtr<ID3D11SamplerState>,3> samplers;
 for(unsigned stage=0;stage<3;++stage){auto& t=textures[stage];
  for(unsigned key=1;key<33;++key)if(h.stages[stage][key]!=0xffffffff && FAILED(d9->SetTextureStageState(stage,static_cast<D3DTEXTURESTAGESTATETYPE>(key),h.stages[stage][key])))return Fail(__LINE__);
  for(unsigned key=1;key<14;++key)if(h.samplers[stage][key]!=0xffffffff && FAILED(d9->SetSamplerState(stage,static_cast<D3DSAMPLERSTATETYPE>(key),h.samplers[stage][key])))return Fail(__LINE__);
  if(FAILED(d9->SetTransform(static_cast<D3DTRANSFORMSTATETYPE>(D3DTS_TEXTURE0+stage),reinterpret_cast<const D3DMATRIX*>(s.textureTransforms[stage].data()))))return Fail(__LINE__);
  if(!t.desc.levels)continue;
  if(FAILED(d9->CreateTexture(t.desc.width,t.desc.height,t.desc.autogen?0:t.desc.levels,t.desc.autogen?D3DUSAGE_AUTOGENMIPMAP:0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&texture9[stage],nullptr)))return Fail(__LINE__);
  std::vector<D3D11_SUBRESOURCE_DATA> initial;
  for(unsigned l=0;l<t.desc.levels;++l){unsigned w=std::max(1u,t.desc.width>>l),height=std::max(1u,t.desc.height>>l);D3DLOCKED_RECT lock{};if(FAILED(texture9[stage]->LockRect(l,&lock,nullptr,0)))return Fail(__LINE__);
   for(unsigned y=0;y<height;++y)for(unsigned x=0;x<w;++x){auto* dst=static_cast<unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;const auto* src=t.mips[l].data()+(y*w+x)*4;dst[0]=src[2];dst[1]=src[1];dst[2]=src[0];dst[3]=src[3];}
   if(FAILED(texture9[stage]->UnlockRect(l)))return Fail(__LINE__);initial.push_back({t.mips[l].data(),w*4,0});
  }
  if(t.desc.autogen){if(FAILED(texture9[stage]->SetAutoGenFilterType(D3DTEXF_LINEAR)))return Fail(__LINE__);texture9[stage]->GenerateMipSubLevels();}
  if(FAILED(d9->SetTexture(stage,texture9[stage].Get())))return Fail(__LINE__);
  D3D11_TEXTURE2D_DESC td{};td.Width=t.desc.width;td.Height=t.desc.height;td.ArraySize=1;td.MipLevels=t.desc.autogen?0:t.desc.levels;td.Format=s.srgbSample[stage]?DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_SHADER_RESOURCE|(t.desc.autogen?D3D11_BIND_RENDER_TARGET:0);td.MiscFlags=t.desc.autogen?D3D11_RESOURCE_MISC_GENERATE_MIPS:0;
  if(FAILED(d11->CreateTexture2D(&td,t.desc.autogen?nullptr:initial.data(),&texture11[stage])) || FAILED(d11->CreateShaderResourceView(texture11[stage].Get(),nullptr,&srv[stage])))return Fail(__LINE__);
  if(t.desc.autogen){c11->UpdateSubresource(texture11[stage].Get(),0,nullptr,t.mips[0].data(),t.desc.width*4,0);c11->GenerateMips(srv[stage].Get());}
  const auto& sampler=s.samplers[stage];D3D11_SAMPLER_DESC sd{};
  sd.Filter=sampler.min==SamplerFilter::Anisotropic || sampler.mag==SamplerFilter::Anisotropic?D3D11_FILTER_ANISOTROPIC:static_cast<D3D11_FILTER>((sampler.min==SamplerFilter::Linear?16:0)|(sampler.mag==SamplerFilter::Linear?4:0)|(sampler.mip==SamplerFilter::Linear?1:0));
  sd.AddressU=sampler.u==SamplerAddress::Wrap?D3D11_TEXTURE_ADDRESS_WRAP:D3D11_TEXTURE_ADDRESS_CLAMP;sd.AddressV=sampler.v==SamplerAddress::Wrap?D3D11_TEXTURE_ADDRESS_WRAP:D3D11_TEXTURE_ADDRESS_CLAMP;sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxAnisotropy=sampler.maxAnisotropy;sd.MaxLOD=D3D11_FLOAT32_MAX;
  if(FAILED(d11->CreateSamplerState(&sd,&samplers[stage])))return Fail(__LINE__);
 }
 if(flat) {
  if(FAILED(d9->SetRenderState(D3DRS_TEXTUREFACTOR,0xff000000)) || FAILED(d9->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1)) || FAILED(d9->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_TFACTOR)) || FAILED(d9->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1)) || FAILED(d9->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_TFACTOR)) || FAILED(d9->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE)))return Fail(__LINE__);
 }
 if(FAILED(d9->SetTextureStageState(3,D3DTSS_COLOROP,D3DTOP_DISABLE)) || (!h.history && FAILED(d9->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff303030,1,0))) || FAILED(d9->BeginScene()))return Fail(__LINE__);
 auto draw=d9->DrawIndexedPrimitive(D3DPT_TRIANGLELIST,0,0,h.vertexBytes/32,h.first,h.count/3);auto ended=d9->EndScene();if(FAILED(draw)||FAILED(ended))return Fail(__LINE__);
 if(msaa && FAILED(d9->StretchRect(target9.Get(),nullptr,resolved9.Get(),nullptr,D3DTEXF_NONE)))return Fail(__LINE__);
 if(FAILED(d9->GetRenderTargetData(msaa?resolved9.Get():target9.Get(),read9.Get())))return Fail(__LINE__);
 auto compile=[&](const wchar_t* file,const char* profile,const D3D_SHADER_MACRO* macros,ComPtr<ID3DBlob>& code){ComPtr<ID3DBlob> errors;auto path=std::filesystem::path(MDS_SHADER_DIR)/file;auto result=D3DCompileFromFile(path.c_str(),macros,D3D_COMPILE_STANDARD_FILE_INCLUDE,"main",profile,D3DCOMPILE_IEEE_STRICTNESS,0,&code,&errors);if(errors)std::fwrite(errors->GetBufferPointer(),1,errors->GetBufferSize(),stderr);return SUCCEEDED(result);};
 ComPtr<ID3DBlob> vsCode,psCode;D3D_SHADER_MACRO macros[]={{"MDS_MODEL_SPECULAR","1"},{"MDS_MODEL_CENTROID",centroid?"1":"0"},{"MDS_MODEL_FLAT",flat?"1":"0"},{nullptr,nullptr}};
 D3D_SHADER_MACRO vertexMacros[]={{"MDS_MODEL_VERTEX_BYTE",vertexByte?"1":"0"},{nullptr,nullptr}};
 if(!compile(L"model_material_vertex.hlsl","vs_5_0",vertexMacros,vsCode) || !compile(L"model_material_pixel.hlsl","ps_5_0",macros,psCode))return Fail(__LINE__);
 ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11PixelShader> ps;ComPtr<ID3D11InputLayout> layout;
 D3D11_INPUT_ELEMENT_DESC elements[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},{"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
 if(FAILED(d11->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs)) || FAILED(d11->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&ps)) || FAILED(d11->CreateInputLayout(elements,3,vsCode->GetBufferPointer(),vsCode->GetBufferSize(),&layout)))return Fail(__LINE__);
 ModelVertexConstants vc{};vc.w=s.world;vc.v=s.view;vc.p=s.projection;vc.n=s.normalView;vc.transforms=s.textureTransforms;vc.diffuse=s.nativeDiffuse;vc.ambient=s.materialAmbient;vc.specular=s.materialSpecular;vc.emissive=s.emissive;vc.globalAmbient=s.globalAmbient;vc.flags={s.lighting,s.normalizeNormals,s.specularEnabled,s.localViewer};vc.parameters={s.shininess,float(h.width),float(h.height),0};
 for(unsigned i=0;i<8;++i){const auto& l=s.lights[i];vc.direction[i]={l.direction[0],l.direction[1],l.direction[2],l.enabled?1.f:0.f};vc.lightDiffuse[i]=l.diffuse;vc.lightAmbient[i]=l.ambient;vc.lightSpecular[i]=l.specular;}
 PixelConstants pc;pc.alpha={s.alphaTest,static_cast<unsigned>(s.alphaCompare),s.alphaReference,0};
 for(unsigned i=0;i<3;++i){vc.coordinates[i]=static_cast<unsigned>(s.layout.stages[i].coordinates);pc.stages[i]={s.layout.stages[i].role!=MaterialTextureRole::None,static_cast<unsigned>(s.layout.stages[i].color),0,0};}
 auto buffer=[&](UINT size,UINT bind,const void* data,ComPtr<ID3D11Buffer>& out){D3D11_BUFFER_DESC desc{};desc.ByteWidth=size;desc.BindFlags=bind;D3D11_SUBRESOURCE_DATA initial{data,0,0};return SUCCEEDED(d11->CreateBuffer(&desc,&initial,&out));};
 ComPtr<ID3D11Buffer> vb11,ib11,vcb,pcb;if(!buffer(h.vertexBytes,D3D11_BIND_VERTEX_BUFFER,vbBytes.data(),vb11)||!buffer(h.indexBytes,D3D11_BIND_INDEX_BUFFER,ibBytes.data(),ib11)||!buffer(sizeof(vc),D3D11_BIND_CONSTANT_BUFFER,&vc,vcb)||!buffer(sizeof(pc),D3D11_BIND_CONSTANT_BUFFER,&pc,pcb))return Fail(__LINE__);
 D3D11_TEXTURE2D_DESC td{};td.Width=h.width;td.Height=h.height;td.ArraySize=td.MipLevels=1;td.SampleDesc.Count=sampleCount;td.SampleDesc.Quality=quality;td.Format=srgbResolve?DXGI_FORMAT_R8G8B8A8_TYPELESS:targetFormat11;td.BindFlags=D3D11_BIND_RENDER_TARGET;
 ComPtr<ID3D11Texture2D> target11,depth11,read11,resolved11;ComPtr<ID3D11RenderTargetView> rtv;ComPtr<ID3D11DepthStencilView> dsv;
 D3D11_RENDER_TARGET_VIEW_DESC viewDesc{};viewDesc.Format=targetFormat11;viewDesc.ViewDimension=msaa?D3D11_RTV_DIMENSION_TEXTURE2DMS:D3D11_RTV_DIMENSION_TEXTURE2D;
 auto uploadColor=historyColor;if(xrgb)for(unsigned i=0;i<uploadColor.size();i+=4)std::swap(uploadColor[i],uploadColor[i+2]);
 D3D11_SUBRESOURCE_DATA colorInitial{uploadColor.data(),h.width*4,0},depthInitial{historyDepth.data(),h.width*4,0};
 if(FAILED(d11->CreateTexture2D(&td,h.history?&colorInitial:nullptr,&target11))||FAILED(d11->CreateRenderTargetView(target11.Get(),&viewDesc,&rtv)))return Fail(__LINE__);
 td.Format=DXGI_FORMAT_D24_UNORM_S8_UINT;td.BindFlags=D3D11_BIND_DEPTH_STENCIL;if(FAILED(d11->CreateTexture2D(&td,h.history?&depthInitial:nullptr,&depth11))||FAILED(d11->CreateDepthStencilView(depth11.Get(),nullptr,&dsv)))return Fail(__LINE__);
 td.Format=srgbResolve?DXGI_FORMAT_R8G8B8A8_TYPELESS:targetFormat11;td.SampleDesc.Count=1;td.SampleDesc.Quality=0;td.BindFlags=0;
 if(msaa && FAILED(d11->CreateTexture2D(&td,nullptr,&resolved11)))return Fail(__LINE__);
 td.Format=targetFormat11;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;if(FAILED(d11->CreateTexture2D(&td,nullptr,&read11)))return Fail(__LINE__);
 D3D11_DEPTH_STENCIL_DESC ds{};ds.DepthEnable=!noDepth;ds.DepthWriteMask=h.render[D3DRS_ZWRITEENABLE]?D3D11_DEPTH_WRITE_MASK_ALL:D3D11_DEPTH_WRITE_MASK_ZERO;ds.DepthFunc=static_cast<D3D11_COMPARISON_FUNC>(h.render[D3DRS_ZFUNC]);ds.StencilEnable=h.render[D3DRS_STENCILENABLE]!=0;ds.StencilReadMask=static_cast<UINT8>(h.render[D3DRS_STENCILMASK]);ds.StencilWriteMask=static_cast<UINT8>(h.render[D3DRS_STENCILWRITEMASK]);
 ds.FrontFace={static_cast<D3D11_STENCIL_OP>(h.render[D3DRS_STENCILFAIL]),static_cast<D3D11_STENCIL_OP>(h.render[D3DRS_STENCILZFAIL]),static_cast<D3D11_STENCIL_OP>(h.render[D3DRS_STENCILPASS]),static_cast<D3D11_COMPARISON_FUNC>(h.render[D3DRS_STENCILFUNC])};ds.BackFace=ds.FrontFace;
 ComPtr<ID3D11DepthStencilState> depthState;if(FAILED(d11->CreateDepthStencilState(&ds,&depthState)))return Fail(__LINE__);
 D3D11_RASTERIZER_DESC raster{};raster.FillMode=D3D11_FILL_SOLID;raster.CullMode=h.render[D3DRS_CULLMODE]==D3DCULL_NONE?D3D11_CULL_NONE:D3D11_CULL_BACK;raster.FrontCounterClockwise=h.render[D3DRS_CULLMODE]==D3DCULL_CW;raster.DepthClipEnable=TRUE;raster.MultisampleEnable=msaa && h.render[D3DRS_MULTISAMPLEANTIALIAS];ComPtr<ID3D11RasterizerState> rasterState;if(FAILED(d11->CreateRasterizerState(&raster,&rasterState)))return Fail(__LINE__);
 D3D11_BLEND_DESC bd{};auto& blend=bd.RenderTarget[0];blend.BlendEnable=!noBlend && h.render[D3DRS_ALPHABLENDENABLE];blend.SrcBlend=static_cast<D3D11_BLEND>(h.render[D3DRS_SRCBLEND]);blend.DestBlend=static_cast<D3D11_BLEND>(h.render[D3DRS_DESTBLEND]);blend.BlendOp=static_cast<D3D11_BLEND_OP>(h.render[D3DRS_BLENDOP]);blend.SrcBlendAlpha=static_cast<D3D11_BLEND>(h.render[h.render[D3DRS_SEPARATEALPHABLENDENABLE]?D3DRS_SRCBLENDALPHA:D3DRS_SRCBLEND]);blend.DestBlendAlpha=static_cast<D3D11_BLEND>(h.render[h.render[D3DRS_SEPARATEALPHABLENDENABLE]?D3DRS_DESTBLENDALPHA:D3DRS_DESTBLEND]);blend.BlendOpAlpha=static_cast<D3D11_BLEND_OP>(h.render[h.render[D3DRS_SEPARATEALPHABLENDENABLE]?D3DRS_BLENDOPALPHA:D3DRS_BLENDOP]);blend.RenderTargetWriteMask=static_cast<UINT8>(h.render[D3DRS_COLORWRITEENABLE]);ComPtr<ID3D11BlendState> blendState;if(FAILED(d11->CreateBlendState(&bd,&blendState)))return Fail(__LINE__);
 auto* rt=rtv.Get();c11->OMSetRenderTargets(1,&rt,dsv.Get());c11->OMSetDepthStencilState(depthState.Get(),h.render[D3DRS_STENCILREF]);c11->OMSetBlendState(blendState.Get(),nullptr,0xffffffff);c11->RSSetState(rasterState.Get());D3D11_VIEWPORT viewport{0,0,float(h.width),float(h.height),0,1};c11->RSSetViewports(1,&viewport);
 UINT stride=32,offset=0;auto* vertexBuffer=vb11.Get();auto* vertexConstant=vcb.Get();auto* pixelConstant=pcb.Get();c11->IASetInputLayout(layout.Get());c11->IASetVertexBuffers(0,1,&vertexBuffer,&stride,&offset);c11->IASetIndexBuffer(ib11.Get(),DXGI_FORMAT_R16_UINT,0);c11->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);c11->VSSetShader(vs.Get(),nullptr,0);c11->VSSetConstantBuffers(0,1,&vertexConstant);c11->PSSetShader(ps.Get(),nullptr,0);c11->PSSetConstantBuffers(0,1,&pixelConstant);
 std::array<ID3D11ShaderResourceView*,3> views{};std::array<ID3D11SamplerState*,3> samplerPointers{};for(unsigned i=0;i<3;++i){views[i]=srv[i].Get();samplerPointers[i]=samplers[i].Get();}c11->PSSetShaderResources(0,3,views.data());c11->PSSetSamplers(0,3,samplerPointers.data());
 const float clear[4]={48/255.f,48/255.f,48/255.f,1};if(!h.history){c11->ClearRenderTargetView(rtv.Get(),clear);c11->ClearDepthStencilView(dsv.Get(),D3D11_CLEAR_DEPTH|D3D11_CLEAR_STENCIL,1,0);}c11->DrawIndexed(h.count,h.first,0);
 if(msaa)c11->ResolveSubresource(resolved11.Get(),0,target11.Get(),0,srgbResolve?DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:DXGI_FORMAT_R8G8B8A8_UNORM);
 c11->CopyResource(read11.Get(),msaa?resolved11.Get():target11.Get());
 D3DLOCKED_RECT lock{};D3D11_MAPPED_SUBRESOURCE map{};if(FAILED(read9->LockRect(&lock,nullptr,D3DLOCK_READONLY))||FAILED(c11->Map(read11.Get(),0,D3D11_MAP_READ,0,&map)))return Fail(__LINE__);
 std::vector<unsigned char> a(h.width*h.height*4),b(a.size());unsigned pixels=0,channels=0,maximum=0,changed9=0,changed11=0;
 for(unsigned y=0;y<h.height;++y)for(unsigned x=0;x<h.width;++x){const auto* p=static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;const auto* q=static_cast<const unsigned char*>(map.pData)+y*map.RowPitch+x*4;unsigned order[]={2,1,0,3};bool different=false,c9=false,c11changed=false;
  for(unsigned c=0;c<4;++c){auto i=(y*h.width+x)*4+c;a[i]=xrgb && c==3?255:p[order[c]];b[i]=xrgb?(c==3?255:q[order[c]]):q[c];different|=a[i]!=b[i];channels+=a[i]!=b[i];maximum=std::max(maximum,unsigned(std::abs(int(a[i])-int(b[i]))));c9|=a[i]!=historyColor[i];c11changed|=b[i]!=historyColor[i];}pixels+=different;changed9+=c9;changed11+=c11changed;
 }
 read9->UnlockRect();c11->Unmap(read11.Get(),0);
 std::filesystem::path out=std::filesystem::u8path(argv[2]);std::filesystem::create_directories(out);
 for(auto pair:{std::pair{"dx9.rgba",&a},std::pair{"dx11.rgba",&b},std::pair{"before.rgba",&historyColor}}){std::ofstream file(out/pair.first,std::ios::binary);file.write(reinterpret_cast<const char*>(pair.second->data()),pair.second->size());if(!file)return Fail(__LINE__);}
 unsigned live9=0,live11=0;
 const bool checkLive=h.history && !noDepth && !noBlend && !flat;
 if(checkLive) {
  const auto path=std::filesystem::u8path(argv[1]).parent_path()/"history_live.rgba";
  std::ifstream liveFile(path,std::ios::binary);std::vector<unsigned char> live(std::istreambuf_iterator<char>{liveFile},{});
  if(live.size()!=a.size())return Fail(__LINE__);
  for(unsigned i=0;i<a.size();i+=4){live9+=std::memcmp(a.data()+i,live.data()+i,4)!=0;live11+=std::memcmp(b.data()+i,live.data()+i,4)!=0;}
 }
 const bool pass=!pixels && changed9 && changed11 && !live9 && !live11;char report[900];std::snprintf(report,sizeof(report),"status=%s frame=%u slot=%u material=%u first=%u count=%u width=%u height=%u differingPixels=%u differingChannels=%u maxError=%u changedDX9=%u changedDX11=%u originalMSAA=%u replaySamples=%u quality=%u centroid=%u flat=%u srgbResolve=%u vertexByte=%u history=%u noDepth=%u noBlend=%u softwareVertex=%u liveChecked=%u liveDX9Differences=%u liveDX11Differences=%u adapter=%04x:%04x\n",pass?"PASS":"BLOCKED",h.frame,h.slot,h.material,h.first,h.count,h.width,h.height,pixels,channels,maximum,changed9,changed11,h.multisample,sampleCount,quality,centroid,flat,srgbResolve,vertexByte,h.history,noDepth,noBlend,hardwareVertex?0:h.vertexProcessing,checkLive,live9,live11,id.VendorId,id.DeviceId);std::fputs(report,stdout);std::ofstream reportFile(out/"comparison.report");reportFile<<report;if(!reportFile)return Fail(__LINE__);
 return pass?0:2;
}
