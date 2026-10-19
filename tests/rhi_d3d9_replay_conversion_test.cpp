#include "mikudancestudio/rhi_d3d9_replay_conversion.hpp"
#include "mikudancestudio/rhi_d3d11.hpp"
#include "mikudancestudio/rhi_d3d9_mip_capture.hpp"
#include <string>
#include <cstdio>
#include <cstring>
#include <wrl/client.h>
#include <limits>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include "d3d9_reduction_fixture.hpp"
#include "depth_transform_arithmetic.hpp"
#ifdef MIKUDANCESTUDIO_RHI_D3D11
#include "d3d11_depth_transform_fixture.hpp"
#include "rhi_d3d11_w_candidate_backend.hpp"
#endif
using Microsoft::WRL::ComPtr;
using namespace mikudancestudio::rhi;
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
void Set(D3D9ReplaySnapshot& c,unsigned key,DWORD value){c.renderStates[key-1].value=value;}
D3D9ReplaySnapshot Fixture() {
    D3D9ReplaySnapshot c;c.type=D3DPT_TRIANGLELIST;c.indexed=true;c.count=1;c.vertices=3;c.stride=32;
    c.fvf=D3DFVF_XYZ|D3DFVF_NORMAL|D3DFVF_TEX1;c.indexFormat=D3DFMT_INDEX16;
    c.viewport={0,0,64,64,0,1};c.vertexBytes.resize(96);c.indexBytes={0,0,1,0,2,0};
    const float vertices[]={-.8f,-.8f,.5f,0,0,1,0,1, -.8f,.8f,.5f,0,0,1,0,0, .8f,-.8f,.5f,0,0,1,1,1};
    std::memcpy(c.vertexBytes.data(),vertices,sizeof(vertices));
    const float identity[]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    for(auto* matrix:{&c.world,&c.view,&c.projection})std::memcpy(matrix,identity,64);
    // Unlit FVF has no COLOR0, so native DX9 must ignore this non-white material.
    c.material.Diffuse={.125f,.25f,.5f,.25f};
    for(unsigned k=1;k<=209;++k)c.renderStates.push_back({0,k,0});
    Set(c,D3DRS_FILLMODE,D3DFILL_SOLID);Set(c,D3DRS_SHADEMODE,D3DSHADE_GOURAUD);Set(c,D3DRS_MULTISAMPLEMASK,0xffffffffu);
    Set(c,D3DRS_ZENABLE,1);Set(c,D3DRS_ZWRITEENABLE,1);Set(c,D3DRS_ZFUNC,D3DCMP_LESSEQUAL);Set(c,D3DRS_CULLMODE,D3DCULL_NONE);
    Set(c,D3DRS_SRCBLEND,D3DBLEND_ONE);Set(c,D3DRS_DESTBLEND,D3DBLEND_ZERO);Set(c,D3DRS_SRCBLENDALPHA,D3DBLEND_ONE);Set(c,D3DRS_DESTBLENDALPHA,D3DBLEND_ZERO);
    Set(c,D3DRS_BLENDOP,D3DBLENDOP_ADD);Set(c,D3DRS_BLENDOPALPHA,D3DBLENDOP_ADD);Set(c,D3DRS_COLORWRITEENABLE,15);
    Set(c,D3DRS_STENCILFUNC,D3DCMP_ALWAYS);Set(c,D3DRS_STENCILFAIL,D3DSTENCILOP_KEEP);Set(c,D3DRS_STENCILZFAIL,D3DSTENCILOP_KEEP);Set(c,D3DRS_STENCILPASS,D3DSTENCILOP_KEEP);
    Set(c,D3DRS_ALPHAFUNC,D3DCMP_ALWAYS);
    for(unsigned stage=0;stage<8;++stage)c.stageStates.push_back({stage,D3DTSS_COLOROP,static_cast<DWORD>(stage?D3DTOP_DISABLE:D3DTOP_MODULATE)});
    for(auto kv:{std::pair<unsigned,DWORD>{D3DTSS_COLORARG1,D3DTA_TEXTURE},{D3DTSS_COLORARG2,D3DTA_DIFFUSE},
        {D3DTSS_ALPHAOP,D3DTOP_MODULATE},{D3DTSS_ALPHAARG1,D3DTA_TEXTURE},{D3DTSS_ALPHAARG2,D3DTA_CURRENT},
        {D3DTSS_RESULTARG,D3DTA_CURRENT},{D3DTSS_TEXCOORDINDEX,0},{D3DTSS_TEXTURETRANSFORMFLAGS,0}})c.stageStates.push_back({0,kv.first,kv.second});
    for(auto kv:{std::pair<unsigned,DWORD>{D3DSAMP_MINFILTER,D3DTEXF_POINT},{D3DSAMP_MAGFILTER,D3DTEXF_POINT},
        {D3DSAMP_MIPFILTER,D3DTEXF_POINT},{D3DSAMP_ADDRESSU,D3DTADDRESS_WRAP},{D3DSAMP_ADDRESSV,D3DTADDRESS_CLAMP},
        {D3DSAMP_MIPMAPLODBIAS,0},{D3DSAMP_MAXMIPLEVEL,0},{D3DSAMP_MAXANISOTROPY,1},{D3DSAMP_SRGBTEXTURE,0}})c.samplerStates.push_back({0,kv.first,kv.second});
    c.textureInfo[0]={true,D3DFMT_A8R8G8B8,1,1,1,0,false};c.textureBytes[0]={7,13,211,255};return c;
}
int ReductionReaderControls() {
    const auto directory=std::filesystem::temp_directory_path()/("mds-replay-reader-"+std::to_string(GetCurrentProcessId()));
    CHECK(std::filesystem::create_directory(directory));
    struct Cleanup {std::filesystem::path path;~Cleanup(){std::error_code error;std::filesystem::remove_all(path,error);}} cleanup{directory};
    const auto stem=directory/"reader";auto fixture=Fixture();
    std::vector<unsigned char> top(16);for(unsigned n=0;n<16;++n)top[n]=static_cast<unsigned char>(n);
    const std::vector<unsigned char> lower{7,11,13,255};
    auto hash=[](const std::vector<unsigned char>& bytes){std::uint64_t h=14695981039346656037ull;for(auto b:bytes)h=(h^b)*1099511628211ull;return h;};
    auto write=[&](const char* suffix,const std::vector<unsigned char>& bytes){std::ofstream out(stem.string()+suffix,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());};
    write(".vertices",fixture.vertexBytes);write(".indices",fixture.indexBytes);write(".texture0",top);write(".prepared0.0.rgba",top);write(".prepared0.1.rgba",lower);
    {std::ofstream out(directory/"history_replay.dx9");out<<"BUFFER sequence=1 kind=index format=101\n";}
    {std::ofstream out(stem.string()+".state");
        out<<"DRAW sequence=1 type=4 fvf=274 indexed=1 base=0 minimum=0 vertices=3 start=0 count=1 offset=0 stride=32\n"
           <<"VIEWPORT x=0 y=0 width=64 height=64 minZ=0 maxZ=1\nSCISSOR left=1 top=2 right=3 bottom=4\n";
        const auto floats=[&](const char* name,const void* data,unsigned count){out<<name;const auto* f=static_cast<const float*>(data);out.precision(9);for(unsigned n=0;n<count;++n)out<<" f"<<n<<"="<<f[n];out<<"\n";};
        floats("WORLD",&fixture.world,16);floats("VIEW",&fixture.view,16);floats("PROJECTION",&fixture.projection,16);floats("MATERIAL",&fixture.material,17);
        for(const auto& s:fixture.renderStates)out<<"RS key="<<s.key<<" value="<<s.value<<"\n";
        for(const auto& s:fixture.stageStates)out<<"TSS stage="<<s.stage<<" key="<<s.key<<" value="<<s.value<<"\n";
        for(const auto& s:fixture.samplerStates)out<<"SAMPLER stage="<<s.stage<<" key="<<s.key<<" value="<<s.value<<"\n";
        out<<"TEXTURE stage=0 present=1 format=21 width=2 height=2 levels=1 lod=0 autogen=1 filter=2\n";
        for(const auto& matrix:fixture.textureMatrices)floats("TEXTURE_MATRIX",&matrix,16);
        out<<"PREPARED_MIP stage=0 level=0 width=2 height=2 hash="<<hash(top)<<"\nPREPARED_MIP stage=0 level=1 width=1 height=1 hash="<<hash(lower)<<"\n";
    }
    const auto path=stem.string()+".state";D3D9ReplaySnapshot captured;
    CHECK(ReadUntexturedReduction(path,captured,true) && captured.scissor.left==1 && captured.preparedMips[0].levels.size()==2);
    CHECK(captured.preparedMips[0].levels[1].pixels==lower);
    CHECK(!ReadUntexturedReduction(path,captured)); // Textures are never silently allowed.
    auto corrupt=lower;corrupt[0]^=1;write(".prepared0.1.rgba",corrupt);CHECK(!ReadUntexturedReduction(path,captured,true));
    write(".prepared0.1.rgba",lower);
    {std::ifstream in(path);std::string text(std::istreambuf_iterator<char>{in},{});in.close();
        const auto position=text.find("indexed=1");CHECK(position!=std::string::npos);text.replace(position,9,"indexed=0");
        std::ofstream out(path);out<<text;}
    write(".indices",{});CHECK(ReadUntexturedReduction(path,captured,true) && !captured.indexed && captured.indexBytes.empty());
    {std::ofstream out(stem.string()+".state",std::ios::app);out<<"PREPARED_MIP stage=0 level=1 width=1 height=1 hash="<<hash(lower)<<"\n";}
    CHECK(!ReadUntexturedReduction(path,captured,true)); // Duplicate/out-of-order level.
    return 0;
}
bool NativeImage(HWND window,const std::vector<D3D9ReplaySnapshot>& snapshots,unsigned prefix,RgbaImage& output,ModelTextureData* prepared=nullptr,unsigned width=64,unsigned height=64,DWORD clear=0xff000000,
    std::vector<std::array<float,4>>* floatPixels=nullptr,const std::string* diagnosticPixelSource=nullptr,IDirect3DDevice9* measurementDevice=nullptr,
    const std::vector<std::array<float,4>>* diagnosticConstants=nullptr) {
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return false;
    D3DPRESENT_PARAMETERS pp{};pp.BackBufferWidth=width;pp.BackBufferHeight=height;pp.BackBufferFormat=D3DFMT_A8R8G8B8;
    pp.BackBufferCount=1;pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.hDeviceWindow=window;
    pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
    ComPtr<IDirect3DDevice9> device;
    HRESULT creation=S_OK;
    if(measurementDevice)device=measurementDevice;
    else creation=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
    if(FAILED(creation)){std::fprintf(stderr,"DX9 creation HRESULT=%08lx\n",static_cast<unsigned long>(creation));return false;}
    // Optional test-owned device reuse: every observation still clears the
    // original backbuffer/depth target and submits/reads fresh output. Reset
    // the programmable pixel binding after a preceding diagnostic PS/float RT.
    if(measurementDevice){ComPtr<IDirect3DSurface9> backbuffer;
        if(FAILED(device->GetBackBuffer(0,0,D3DBACKBUFFER_TYPE_MONO,&backbuffer)) ||
           FAILED(device->SetRenderTarget(0,backbuffer.Get())) || FAILED(device->SetPixelShader(nullptr)))return false;}
    ComPtr<IDirect3DSurface9> floatTarget;
    if(floatPixels && (FAILED(device->CreateRenderTarget(width,height,D3DFMT_A32B32G32R32F,D3DMULTISAMPLE_NONE,0,FALSE,&floatTarget,nullptr)) ||
        FAILED(device->SetRenderTarget(0,floatTarget.Get()))))return false;
    if(prefix>snapshots.size())return false;
    // Test-only PS observation after native fixed-function vertex processing.
    // It is never presented as the untouched fixed-function pixel path.
    ComPtr<IDirect3DPixelShader9> diagnosticPixel;
    if(diagnosticPixelSource){
#ifdef MIKUDANCESTUDIO_RHI_D3D11
        ComPtr<ID3DBlob> code,error;
        // The native fixed-function VS uses the legacy TEXCOORD register
        // linkage. A ps_3_0 semantic declaration is not an equivalent link.
        const auto compiled=D3DCompile(diagnosticPixelSource->data(),diagnosticPixelSource->size(),nullptr,nullptr,nullptr,"main","ps_2_a",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error);
        if(FAILED(compiled)){if(error)std::fprintf(stderr,"native observation PS: %s\n",static_cast<const char*>(error->GetBufferPointer()));return false;}
        if(FAILED(device->CreatePixelShader(static_cast<const DWORD*>(code->GetBufferPointer()),&diagnosticPixel)) || FAILED(device->SetPixelShader(diagnosticPixel.Get())))return false;
        // Runtime constants for causal probes, separate from compiler-owned
        // immediate registers. Never used by native production replay.
        if(diagnosticConstants && (diagnosticConstants->empty() || diagnosticConstants->size()>16 ||
            FAILED(device->SetPixelShaderConstantF(16,diagnosticConstants->front().data(),static_cast<UINT>(diagnosticConstants->size())))))return false;
#else
        return false; // Default DX9-only helpers retain their original path.
#endif
    }
    const D3DVIEWPORT9 full{0,0,width,height,0,1};
    if(FAILED(device->SetViewport(&full)) || FAILED(device->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,clear,1,0)) || FAILED(device->BeginScene()))return false;
    for(unsigned i=0;i<prefix;++i) {
    const auto& c=snapshots[i];
    if(FAILED(device->SetFVF(c.fvf)) || FAILED(device->SetTransform(D3DTS_WORLD,&c.world)) ||
       FAILED(device->SetTransform(D3DTS_VIEW,&c.view)) || FAILED(device->SetTransform(D3DTS_PROJECTION,&c.projection)) ||
       FAILED(device->SetMaterial(&c.material)) || FAILED(device->SetViewport(&c.viewport)))return false;
    // Documented identifiers only (Fixture's zero-filled transport has enum holes).
    for(auto key:{D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_ZFUNC,D3DRS_CULLMODE,D3DRS_LIGHTING,D3DRS_SPECULARENABLE,
        D3DRS_ALPHABLENDENABLE,D3DRS_SRCBLEND,D3DRS_DESTBLEND,D3DRS_BLENDOP,D3DRS_SEPARATEALPHABLENDENABLE,
        D3DRS_SRCBLENDALPHA,D3DRS_DESTBLENDALPHA,D3DRS_BLENDOPALPHA,D3DRS_ALPHATESTENABLE,D3DRS_ALPHAFUNC,
        D3DRS_STENCILENABLE,D3DRS_STENCILFUNC,D3DRS_STENCILFAIL,D3DRS_STENCILZFAIL,D3DRS_STENCILPASS,
        D3DRS_COLORWRITEENABLE,D3DRS_FOGENABLE,D3DRS_DITHERENABLE,D3DRS_FILLMODE,D3DRS_SHADEMODE,
        D3DRS_AMBIENT,D3DRS_NORMALIZENORMALS,D3DRS_LOCALVIEWER,D3DRS_COLORVERTEX,
        D3DRS_DIFFUSEMATERIALSOURCE,D3DRS_AMBIENTMATERIALSOURCE,D3DRS_SPECULARMATERIALSOURCE,D3DRS_EMISSIVEMATERIALSOURCE,
        D3DRS_ALPHAREF,D3DRS_STENCILREF,D3DRS_STENCILMASK,D3DRS_STENCILWRITEMASK})
        {const auto found=std::find_if(c.renderStates.begin(),c.renderStates.end(),[&](const auto& state){return state.key==unsigned(key);});
        if(found==c.renderStates.end() || FAILED(device->SetRenderState(key,found->value)))return false;}
    for(unsigned stage=0;stage<8;++stage)if(FAILED(device->SetTransform(static_cast<D3DTRANSFORMSTATETYPE>(D3DTS_TEXTURE0+stage),&c.textureMatrices[stage])))return false;
    for(unsigned light=0;light<8;++light)if(FAILED(device->LightEnable(light,FALSE)))return false;
    for(const auto& light:c.lights)if(FAILED(device->SetLight(light.index,&light.value)) || FAILED(device->LightEnable(light.index,light.enabled)))return false;
    for(const auto& state:c.stageStates)if(FAILED(device->SetTextureStageState(state.stage,static_cast<D3DTEXTURESTAGESTATETYPE>(state.key),state.value)))return false;
    for(const auto& state:c.samplerStates)if(FAILED(device->SetSamplerState(state.stage,static_cast<D3DSAMPLERSTATETYPE>(state.key),state.value)))return false;
    ComPtr<IDirect3DTexture9> textures[8];
    for(unsigned stage=0;stage<8;++stage) {
        if(c.textureInfo[stage].present) {
            const auto& t=c.textureInfo[stage];
            const bool compressed=t.format==D3DFMT_DXT1 || t.format==D3DFMT_DXT3 || t.format==D3DFMT_DXT5;
            if(!t.width || !t.height || !t.levels || (!compressed && t.format!=D3DFMT_A8R8G8B8 && t.format!=D3DFMT_X8R8G8B8))return false;
            if(FAILED(device->CreateTexture(t.width,t.height,t.autogen?0:t.levels,t.autogen?D3DUSAGE_AUTOGENMIPMAP:0,t.format,D3DPOOL_MANAGED,&textures[stage],nullptr)))return false;
            unsigned w=t.width,h=t.height;std::size_t offset=0;
            for(unsigned level=0;level<t.levels;++level) {
                const unsigned rows=compressed?(h+3)/4:h,rowBytes=compressed?((w+3)/4)*(t.format==D3DFMT_DXT1?8:16):w*4;
                if(offset+std::size_t(rowBytes)*rows>c.textureBytes[stage].size())return false;
                D3DLOCKED_RECT lock{};if(FAILED(textures[stage]->LockRect(level,&lock,nullptr,0)))return false;
                for(unsigned row=0;row<rows;++row)std::memcpy(static_cast<char*>(lock.pBits)+row*lock.Pitch,c.textureBytes[stage].data()+offset+std::size_t(row)*rowBytes,rowBytes);
                if(FAILED(textures[stage]->UnlockRect(level)))return false;
                offset+=std::size_t(rowBytes)*rows;w=w>1?w/2:1;h=h>1?h/2:1;
            }
            if(offset!=c.textureBytes[stage].size())return false;
            if(t.autogen) {
                if(FAILED(textures[stage]->SetAutoGenFilterType(static_cast<D3DTEXTUREFILTERTYPE>(t.autogenFilter))))return false;
                textures[stage]->GenerateMipSubLevels();
            }
            if(t.lod)return false;
        }
        if(FAILED(device->SetTexture(stage,textures[stage].Get())))return false;
    }
    if(prepared) {
        const auto capture=CaptureD3D9GeneratedMips(device.Get(),textures[0].Get(),true,*prepared);
        if(FAILED(capture)){std::fprintf(stderr,"mipCapture HRESULT=%08lx\n",static_cast<unsigned long>(capture));return false;}
    }
    const auto indexStep=c.indexFormat==D3DFMT_INDEX16?2:4;
    const auto drawn=c.indexed?
        device->DrawIndexedPrimitiveUP(static_cast<D3DPRIMITIVETYPE>(c.type),c.minimum,c.vertices,c.count,
            c.indexBytes.data()+std::size_t(c.start)*indexStep,c.indexFormat,c.vertexBytes.data(),c.stride):
        device->DrawPrimitiveUP(static_cast<D3DPRIMITIVETYPE>(c.type),c.count,
            c.vertexBytes.data()+std::size_t(c.start)*c.stride,c.stride);
    if(FAILED(drawn))return false;
    }
    if(FAILED(device->EndScene()))return false;
    ComPtr<IDirect3DSurface9> target,cpu;
    if(FAILED(device->GetRenderTarget(0,&target)) || FAILED(device->CreateOffscreenPlainSurface(width,height,floatPixels?D3DFMT_A32B32G32R32F:D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&cpu,nullptr)) ||
       FAILED(device->GetRenderTargetData(target.Get(),cpu.Get())))return false;
    D3DLOCKED_RECT lock{};if(FAILED(cpu->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
    if(floatPixels){floatPixels->resize(std::size_t(width)*height);
        for(unsigned y=0;y<height;++y)std::memcpy(floatPixels->data()+std::size_t(y)*width,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,std::size_t(width)*16);
        return SUCCEEDED(cpu->UnlockRect());}
    output={width,height,std::vector<std::uint8_t>(std::size_t(width)*height*4)};
    for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x) {
        auto* src=static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;auto* dst=output.pixels.data()+(std::size_t(y)*width+x)*4;
        dst[0]=src[2];dst[1]=src[1];dst[2]=src[0];dst[3]=src[3];
    }
    return SUCCEEDED(cpu->UnlockRect());
}
void Stage(D3D9ReplaySnapshot& c,unsigned stage,unsigned key,DWORD value) {
    for(auto& state:c.stageStates)if(state.stage==stage && state.key==key){state.value=value;return;}
    c.stageStates.push_back({stage,key,value});
}
D3D9ReplaySnapshot NullTextureFixture(unsigned stage,bool add,bool lit,unsigned alphaMode) {
    auto c=Fixture();
    // Two earlier textures exercise CURRENT; the last stage is a magenta
    // sentinel, so accidentally resuming the cascade produces a visible error.
    for(unsigned slot=0;slot<4;++slot) {
        const auto base=Fixture();
        for(const auto& state:base.stageStates)if(state.stage==0)Stage(c,slot,state.key,state.value);
        Stage(c,slot,D3DTSS_COLORARG2,slot?D3DTA_CURRENT:D3DTA_DIFFUSE);
        if(slot)for(const auto& state:base.samplerStates)c.samplerStates.push_back({slot,state.key,state.value});
        c.textureInfo[slot]=base.textureInfo[0];
        c.textureBytes[slot]=slot==3?std::vector<unsigned char>{255,0,255,0}:std::vector<unsigned char>{0,255,255,255};
    }
    Stage(c,stage,D3DTSS_COLOROP,add?D3DTOP_ADD:D3DTOP_MODULATE);
    c.textureInfo[stage]={};c.textureBytes[stage].clear();
    if(lit) {
        Set(c,D3DRS_LIGHTING,TRUE);c.material.Emissive={1,.5f,.25f,0};
        c.material.Diffuse.a=.5f;
    }
    if(alphaMode==1) {Set(c,D3DRS_ALPHABLENDENABLE,TRUE);Set(c,D3DRS_SRCBLEND,D3DBLEND_SRCALPHA);Set(c,D3DRS_DESTBLEND,D3DBLEND_INVSRCALPHA);}
    if(alphaMode>=2) {Set(c,D3DRS_ALPHATESTENABLE,TRUE);Set(c,D3DRS_ALPHAFUNC,D3DCMP_GREATER);Set(c,D3DRS_ALPHAREF,alphaMode==2?64:192);}
    return c;
}
unsigned PixelDifferences(const RgbaImage& a,const RgbaImage& b) {
    if(a.width!=b.width || a.height!=b.height || a.pixels.size()!=b.pixels.size())return ~0u;
    unsigned differences=0;for(std::size_t i=0;i<a.pixels.size();i+=4)if(std::memcmp(a.pixels.data()+i,b.pixels.data()+i,4))++differences;
    return differences;
}
D3D9ReplaySnapshot MipFixture(unsigned width,unsigned height,unsigned lod,unsigned pattern,DWORD filter) {
    auto c=Fixture();const auto w=(std::max)(1u,width>>lod),h=(std::max)(1u,height>>lod);
    c.viewport={0,0,w,h,0,1};c.vertices=4;c.count=2;c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};
    // Texel-center aligned quad. Each viewport reduction selects another mip.
    const float x0=-1-1.f/w,x1=1-1.f/w,y0=1+1.f/h,y1=-1+1.f/h;
    const float vertices[]={x0,y0,.5f,0,0,1,0,0, x1,y0,.5f,0,0,1,1,0,
        x0,y1,.5f,0,0,1,0,1, x1,y1,.5f,0,0,1,1,1};
    c.vertexBytes.resize(sizeof(vertices));std::memcpy(c.vertexBytes.data(),vertices,sizeof(vertices));
    c.textureInfo[0]={true,D3DFMT_A8R8G8B8,width,height,1,0,true,filter};c.textureBytes[0].resize(std::size_t(width)*height*4);
    for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x) {
        auto* p=c.textureBytes[0].data()+(std::size_t(y)*width+x)*4;
        if(pattern==0) {const unsigned char v=(x+y)%2?255:0;p[0]=v;p[1]=255-v;p[2]=v;p[3]=255;}
        else {p[0]=(x*17+y*37+3)%256;p[1]=(x*71+y*13+19)%256;p[2]=(x*29+y*53+41)%256;p[3]=(x*43+y*7+67)%256;}
    }
    return c;
}
D3D9ReplaySnapshot ExplicitMips(D3D9ReplaySnapshot c,const ModelTextureData& data) {
    c.textureInfo[0].autogen=false;c.textureInfo[0].levels=static_cast<unsigned>(data.levels.size());c.textureBytes[0].clear();
    for(const auto& level:data.levels)for(std::size_t i=0;i<level.pixels.size();i+=4) {
        c.textureBytes[0].insert(c.textureBytes[0].end(),{level.pixels[i+2],level.pixels[i+1],level.pixels[i],level.pixels[i+3]});
    }
    return c;
}
int NativeMipControls(HWND window) {
    unsigned comparisons=0;
    for(unsigned shape=0;shape<2;++shape)for(unsigned pattern=0;pattern<2;++pattern)for(DWORD filter:{DWORD(D3DTEXF_POINT),DWORD(D3DTEXF_LINEAR)}) {
        const unsigned width=64,height=shape?16:64;auto c=MipFixture(width,height,0,pattern,filter);
        ModelTextureData prepared;RgbaImage captured,original;
        CHECK(NativeImage(window,{c},1,captured,&prepared) && NativeImage(window,{c},1,original));
        CHECK(prepared.levels.size()==7 && !prepared.generateMips && !prepared.srgb);
        CHECK(PixelDifferences(captured,original)==0); // helper restored caller's state and scene
        auto explicitTexture=ExplicitMips(c,prepared);
        CHECK(std::memcmp(explicitTexture.textureBytes[0].data(),c.textureBytes[0].data(),c.textureBytes[0].size())==0);
        for(unsigned lod=0;lod<7;++lod) {
            c=MipFixture(width,height,lod,pattern,filter);explicitTexture=ExplicitMips(c,prepared);
            RgbaImage native,copy;CHECK(NativeImage(window,{c},1,native) && NativeImage(window,{explicitTexture},1,copy));
            const auto differences=PixelDifferences(native,copy);
            std::printf("nativeMip shape=%u pattern=%u filter=%lu lod=%u differences=%u\n",shape,pattern,static_cast<unsigned long>(filter),lod,differences);
            CHECK(!differences);++comparisons;
            if(!pattern && filter==D3DTEXF_LINEAR && lod==1) {
                auto topOnly=c;topOnly.textureInfo[0].autogen=false;RgbaImage wrong;CHECK(NativeImage(window,{topOnly},1,wrong));
                CHECK(PixelDifferences(native,wrong)>0);
            }
        }
    }
    std::printf("nativeMipComparisons=%u differingPixels=0 stateRestore=PASS\n",comparisons);return 0;
}
int MipConversionControls() {
    auto c=Fixture();c.textureInfo[0]={true,D3DFMT_A8R8G8B8,2,2,1,0,true};
    c.textureBytes[0]={3,5,7,9, 11,13,17,19, 23,29,31,37, 41,43,47,53};
    c.preparedMips[0].levels={{2,2,{7,5,3,9, 17,13,11,19, 31,29,23,37, 47,43,41,53}},{1,1,{26,23,20,30}}};
    ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
    CHECK(AppendD3D9ReplaySnapshot(stream,c));
    auto reject=[&](D3D9ReplaySnapshot invalid,const char* reason){const auto events=stream.events.size(),resources=stream.resources.size();
        const auto result=AppendD3D9ReplaySnapshot(stream,invalid);return !result && result.reason==reason && events==stream.events.size() && resources==stream.resources.size();};
    auto bad=c;bad.preparedMips[0].levels.clear();CHECK(reject(bad,"autogen_mips_not_materialized"));
    bad=c;bad.preparedMips[0].levels.pop_back();CHECK(reject(bad,"incomplete_prepared_mips"));
    bad=c;bad.preparedMips[0].levels.push_back({1,1,{1,2,3,4}});CHECK(reject(bad,"incomplete_prepared_mips"));
    bad=c;bad.preparedMips[0].levels[1].width=2;CHECK(reject(bad,"invalid_prepared_mips"));
    bad=c;bad.preparedMips[0].levels[1].pixels.pop_back();CHECK(reject(bad,"invalid_prepared_mips"));
    bad=c;bad.preparedMips[0].levels[0].pixels[0]^=1;CHECK(reject(bad,"prepared_mip_top_mismatch"));
    bad=c;bad.preparedMips[0].generateMips=true;CHECK(reject(bad,"invalid_prepared_mips"));
    bad=c;bad.preparedMips[0].srgb=true;CHECK(reject(bad,"invalid_prepared_mips"));
    bad=c;bad.textureInfo[0].autogenFilter=D3DTEXF_ANISOTROPIC;CHECK(reject(bad,"unsupported_autogen_description"));
    bad=c;bad.textureInfo[0].autogen=false;CHECK(reject(bad,"unexpected_prepared_mips"));
    bad=c;bad.textureInfo[0].lod=1;CHECK(reject(bad,"unsupported_texture_format_mips_or_lod"));
    c.preparedMips[0].levels[1].pixels[0]=42;CHECK(AppendD3D9ReplaySnapshot(stream,c));
    CHECK(stream.resources[2].texture.levels[1].pixels[0]==26 && stream.resources[5].texture.levels[1].pixels[0]==42);
    CHECK(!stream.resources[5].texture.generateMips && stream.resources[5].key.version==2);
    stream.complete=true;CHECK(ValidateModelReplay(stream).draws==2);return 0;
}
int NativeNullTextureControls(HWND window) {
    unsigned comparisons=0;
    for(unsigned stage=0;stage<3;++stage)for(bool add:{false,true})for(bool lit:{false,true})for(unsigned alpha=0;alpha<4;++alpha) {
        const auto null=NullTextureFixture(stage,add,lit,alpha);auto disabled=null;
        Stage(disabled,stage,D3DTSS_COLOROP,D3DTOP_DISABLE);
        RgbaImage a,b;CHECK(NativeImage(window,{null},1,a) && NativeImage(window,{disabled},1,b));
        const auto differences=PixelDifferences(a,b);const auto pixel=(40*64+16)*4;
        std::printf("nativeNull stage=%u op=%s lit=%u alpha=%u rgba=%u,%u,%u,%u vsDisabled=%u\n",stage,add?"ADD":"MODULATE",lit,alpha,
            a.pixels[pixel],a.pixels[pixel+1],a.pixels[pixel+2],a.pixels[pixel+3],differences);
        CHECK(!differences);
        // Prevent an empty/failed draw from satisfying the equivalence oracle.
        if(!lit) {CHECK(a.pixels[pixel]==255 && a.pixels[pixel+1]==255 && a.pixels[pixel+2]==(stage?0:255) && a.pixels[pixel+3]==255);}
        if(!alpha) {
            auto bound=null;bound.textureInfo[stage]=Fixture().textureInfo[0];bound.textureBytes[stage]={255,255,255,255};
            RgbaImage sentinel;CHECK(NativeImage(window,{bound},1,sentinel));
            CHECK(PixelDifferences(a,sentinel)>0 && sentinel.pixels[pixel+3]==0);
        }
        ++comparisons;
    }
    std::printf("nativeNullTextureComparisons=%u differingPixels=0\n",comparisons);return 0;
}
int NullTextureConversionControls() {
    for(unsigned stage=0;stage<3;++stage)for(bool add:{false,true}) {
        auto c=NullTextureFixture(stage,add,true,0);
        ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
        CHECK(AppendD3D9ReplaySnapshot(stream,c));
        // Only real resources preceding the null stage are published.
        CHECK(stream.resources.size()==2+stage);
        const auto& draw=stream.events.back().draw;
        for(unsigned slot=0;slot<3;++slot) {
            CHECK((draw.pipeline.shader.layout.stages[slot].role==MaterialTextureRole::None)==(slot>=stage));
            CHECK((draw.textures[slot].id==0)==(slot>=stage));
        }
        // States and resources beyond the terminated cascade cannot affect it.
        Stage(c,stage+1,D3DTSS_COLOROP,D3DTOP_BUMPENVMAP);
        c.textureInfo[stage+1].autogen=true;c.textureBytes[stage+1].clear();
        CHECK(AppendD3D9ReplaySnapshot(stream,c));
        Stage(c,stage,D3DTSS_COLORARG1,D3DTA_DIFFUSE);
        CHECK(AppendD3D9ReplaySnapshot(stream,c).reason=="unsupported_texture_arguments");
    }
    // Null -> bound -> null leaves old immutable bytes intact, and the final
    // draw has no texture reference despite the published version still existing.
    auto c=Fixture();auto null=c;null.textureInfo[0]={};null.textureBytes[0].clear();
    ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
    CHECK(AppendD3D9ReplaySnapshot(stream,null));CHECK(AppendD3D9ReplaySnapshot(stream,c));CHECK(AppendD3D9ReplaySnapshot(stream,null));
    CHECK(stream.resources.size()==7 && stream.resources[4].key.id==10 && stream.resources[4].key.version==2);
    CHECK(stream.resources[4].texture.levels[0].pixels==std::vector<unsigned char>({211,13,7,255}));
    CHECK(!stream.events.back().draw.textures[0].id);stream.complete=true;CHECK(ValidateModelReplay(stream).draws==3);
    return 0;
}
D3D9ReplaySnapshot ShadowFixture(unsigned mode,bool texture) {
    auto c=Fixture();c.fvf=D3DFVF_XYZ|D3DFVF_DIFFUSE;c.stride=16;c.vertexBytes.resize(48);
    const float positions[]={-.8f,-.8f,.5f,-.8f,.8f,.5f,.8f,-.8f,.5f};
    const DWORD color=0x80ff4000; // native ARGB: RGBA=(255,64,0,128)
    for(unsigned vertex=0;vertex<3;++vertex){std::memcpy(c.vertexBytes.data()+vertex*16,positions+vertex*3,12);std::memcpy(c.vertexBytes.data()+vertex*16+12,&color,4);}
    c.material.Diffuse={.125f,.25f,.5f,64/255.f};c.material.Ambient={.25f,.5f,1,0};c.material.Emissive={0,0,0,0};
    Set(c,D3DRS_LIGHTING,mode!=0);Set(c,D3DRS_NORMALIZENORMALS,TRUE);Set(c,D3DRS_SPECULARENABLE,TRUE);
    Set(c,D3DRS_COLORVERTEX,mode>=2);Set(c,D3DRS_DIFFUSEMATERIALSOURCE,mode>=2?D3DMCS_COLOR1:D3DMCS_MATERIAL);
    Set(c,D3DRS_AMBIENT,0xffffffff);Set(c,D3DRS_AMBIENTMATERIALSOURCE,mode==2?D3DMCS_COLOR1:mode==5?D3DMCS_COLOR2:D3DMCS_MATERIAL);
    if(mode==3){Set(c,D3DRS_AMBIENT,0);Set(c,D3DRS_EMISSIVEMATERIALSOURCE,D3DMCS_COLOR1);}
    if(mode==4) {
        Set(c,D3DRS_AMBIENT,0);D3D9ReplaySnapshot::Light light{};light.enabled=TRUE;light.value.Type=D3DLIGHT_DIRECTIONAL;
        light.value.Direction={0,0,-1};light.value.Ambient={1,1,1,0};light.value.Diffuse={1,1,1,0};c.lights.push_back(light);
        Set(c,D3DRS_AMBIENTMATERIALSOURCE,D3DMCS_COLOR1);
    }
    // Rank-two projection: position is still valid, normal inverse does not exist.
    c.world._33=0;c.world._43=.5f;
    Set(c,D3DRS_ALPHABLENDENABLE,TRUE);Set(c,D3DRS_SRCBLEND,D3DBLEND_SRCALPHA);Set(c,D3DRS_DESTBLEND,D3DBLEND_INVSRCALPHA);
    Set(c,D3DRS_ZFUNC,D3DCMP_LESS);Set(c,D3DRS_STENCILENABLE,TRUE);Set(c,D3DRS_STENCILFUNC,D3DCMP_GREATER);
    Set(c,D3DRS_STENCILREF,2);Set(c,D3DRS_STENCILMASK,255);Set(c,D3DRS_STENCILWRITEMASK,255);Set(c,D3DRS_STENCILPASS,D3DSTENCILOP_REPLACE);
    if(texture) {c.textureInfo[0]={true,D3DFMT_A8R8G8B8,2,2,1,0,false};c.textureBytes[0]={255,255,255,255, 0,0,0,0, 0,0,0,0, 0,0,0,0};}
    else {c.textureInfo[0]={};c.textureBytes[0].clear();}
    return c;
}
int ShadowConversionControls() {
    auto c=ShadowFixture(0,false);ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
    CHECK(AppendD3D9ReplaySnapshot(stream,c).reason=="position_color_not_enabled");
    CHECK(AppendD3D9ReplaySnapshot(stream,c,true));
    CHECK(stream.resources[0].vertexLayout==VertexLayout::PositionColor && stream.resources[0].bytes.size()==48);
    CHECK(stream.resources[0].bytes[12]==255 && stream.resources[0].bytes[13]==64 && stream.resources[0].bytes[14]==0 && stream.resources[0].bytes[15]==128);
    stream.complete=true;CHECK(ValidateModelReplay(stream));
    auto bad=stream;bad.events.back().draw.pipeline.vertexLayout=VertexLayout::PositionNormalUv;CHECK(ValidateModelReplay(bad).reason=="vertex_layout_mismatch");
    bad=stream;bad.resources[0].bytes.pop_back();CHECK(ValidateModelReplay(bad).reason=="invalid_vertex_layout");
    c=ShadowFixture(1,true);Stage(c,0,D3DTSS_TEXCOORDINDEX,D3DTSS_TCI_CAMERASPACENORMAL);Stage(c,0,D3DTSS_TEXTURETRANSFORMFLAGS,D3DTTFF_COUNT2);
    CHECK(AppendD3D9ReplaySnapshot(stream,c,true).reason=="position_color_has_no_normal_coordinates");
    c=ShadowFixture(1,false);c.offset=16;CHECK(AppendD3D9ReplaySnapshot(stream,c,true).reason=="unsupported_geometry_layout_or_base");
    return 0;
}
#include "ground_replay_fixture.hpp"
#ifdef MIKUDANCESTUDIO_RHI_D3D11
int ShadowAdapterControls(HWND window,D3D11Driver driver) {
    const auto quad=[](D3D9ReplaySnapshot c,unsigned w,unsigned h,DWORD color) {
        const float x0=-1-1.f/w,x1=1-1.f/w,y0=1+1.f/h,y1=-1+1.f/h;
        const float positions[]={x0,y0,.5f,x1,y0,.5f,x0,y1,.5f,x1,y1,.5f};
        c.vertexBytes.resize(64);c.vertices=4;c.count=2;c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};
        for(unsigned i=0;i<4;++i){std::memcpy(c.vertexBytes.data()+i*16,positions+i*3,12);std::memcpy(c.vertexBytes.data()+i*16+12,&color,4);}return c;
    };
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    unsigned comparisons=0;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
        for(unsigned mode=0;mode<7;++mode)for(bool texture:{false,true}) {
            auto base=quad(ShadowFixture(0,false),64,64,0xff0000ff);
            Set(base,D3DRS_ALPHABLENDENABLE,FALSE);Set(base,D3DRS_STENCILENABLE,FALSE);base.world._43=.75f;
            auto shadow=quad(ShadowFixture(mode==6?0:mode,texture),40,48,0x80ff4000);shadow.viewport={8,6,40,48,0,1};
            if(mode==6)shadow.world._43=.9f;
            ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
            for(const auto& c:{base,shadow,shadow})CHECK(AppendD3D9ReplaySnapshot(stream,c,true));stream.complete=true;
            for(unsigned prefix:{1u,2u,3u,1u}) {
                RgbaImage actual;CHECK(ReplayD3D11ModelPrefix(*bundle.device,stream,prefix,actual));
                const bool material=mode==1 || mode==5;const float alpha=(mode==1?64.f:128.f)/255.f;
                const float rgb[]={material?.25f:1.f,material?.5f:64/255.f,material?1.f:0.f};
                const auto byte=[](float v){return static_cast<unsigned char>(std::floor(v*255+.5f));};
                const unsigned char expected[]={byte(rgb[0]*alpha),byte(rgb[1]*alpha),byte(rgb[2]*alpha+1-alpha),byte(alpha*alpha+1-alpha)};
                for(unsigned y=0;y<64;++y)for(unsigned x=0;x<64;++x) {
                    const auto* p=actual.pixels.data()+(y*64+x)*4;const unsigned char blue[]={0,0,255,255};
                    const auto* oracle=prefix>1 && mode!=6 && x>=8 && x<48 && y>=6 && y<54?expected:blue;
                    if(std::memcmp(p,oracle,4)) {
                        std::fprintf(stderr,"adapterShadow mode=%u texture=%u prefix=%u pixel=%u,%u actual=%u,%u,%u,%u expected=%u,%u,%u,%u\n",
                            mode,texture,prefix,x,y,p[0],p[1],p[2],p[3],oracle[0],oracle[1],oracle[2],oracle[3]);return 1;
                    }
                }
                ++comparisons;
            }
        }
        CHECK(bundle.swapchain->Retire());
    }
    std::printf("shadowAdapterOracleComparisons=%u differingPixels=0 depthOcclusionStencilRepeat=PASS deviceReplacement=PASS\n",comparisons);return 0;
}
int CapturedShadowControls(HWND window,D3D11Driver driver,const char* path) {
    D3D9ReplaySnapshot c;CHECK(ReadUntexturedReduction(path,c,true));CHECK(c.fvf==(D3DFVF_XYZ|D3DFVF_DIFFUSE));
    const unsigned width=c.viewport.X+c.viewport.Width,height=c.viewport.Y+c.viewport.Height;
    CHECK(width<=4096 && height<=4096);
    // A black projected shadow on the usual black fixture clear cannot prove
    // coverage. Keep the captured draw unchanged and use an explicit colored
    // background in both backends; this is an isolated-history control.
    constexpr DWORD clear=0xfff0e0d0;
    ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.clear={240/255.f,224/255.f,208/255.f,1};stream.events.push_back({1,ModelReplayOp::Clear});
    const auto converted=AppendD3D9ReplaySnapshot(stream,c,true);if(!converted)std::fprintf(stderr,"capturedShadow reason=%s\n",converted.reason.c_str());CHECK(converted);stream.complete=true;
    RgbaImage native;CHECK(NativeImage(window,{c},1,native,nullptr,width,height,clear));
    unsigned changed=0;for(std::size_t at=0;at<native.pixels.size();at+=4)if(native.pixels[at]!=240 || native.pixels[at+1]!=224 || native.pixels[at+2]!=208 || native.pixels[at+3]!=255)++changed;CHECK(changed);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    unsigned comparisons=0;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
        for(unsigned repeat=0;repeat<3;++repeat) {
            RgbaImage image;CHECK(ReplayD3D11ModelPrefix(*bundle.device,stream,1,image));
            const auto differences=PixelDifferences(image,native);std::printf("capturedShadow triangles=%u changed=%u differences=%u repeat=%u replacement=%u\n",c.count,changed,differences,repeat,replacement);
            CHECK(!differences);++comparisons;
        }
        CHECK(bundle.swapchain->Retire());
    }
    std::printf("capturedShadowComparisons=%u differingPixels=0\n",comparisons);return 0;
}
// Reconstruct two archived untextured draws; either compare saved evidence or
// capture fresh native controls. Candidate shaders remain diagnostic-only.
// Archive and reference provenance must be checked independently (including
// resource hashes); modifying states is a counterfactual, never acceptance.
int SavedAccessoryControls(HWND window,D3D11Driver driver,const char* archivePath,const char* referencePath,bool nativeCompare=false,unsigned wCandidatePolicy=0,bool lightingCandidate=false,bool normalCandidate=false) {
    CHECK(wCandidatePolicy<=5 && (!wCandidatePolicy || nativeCompare));
    CHECK(!normalCandidate || (lightingCandidate && wCandidatePolicy==3));
    const std::filesystem::path archive(archivePath),reference(referencePath);
    const bool frozen=std::filesystem::exists(archive/"history_replay.dx11_prefix.draw1.state");
    const std::string stem=frozen?"history_replay.dx11_prefix.draw":"history_replay.reduction.draw";
    std::vector<D3D9ReplaySnapshot> original(2);
    for(unsigned n=0;n<2;++n)CHECK(ReadUntexturedReduction(archive/(stem+std::to_string(n+1)+".state"),original[n],frozen));
    CHECK(original[0].fvf==274 && original[0].stride==32 && original[0].start==0 && original[0].count==2);
    CHECK(original[1].fvf==274 && original[1].stride==32 && original[1].start==6 && original[1].count==232);
    unsigned x=0,y=0,w=0,h=0;std::ifstream log(reference/"history_replay.dx9");std::string line;
    while(std::getline(log,line))if(std::sscanf(line.c_str(),"PORTABLE_REGION x=%u y=%u width=%u height=%u",&x,&y,&w,&h)==4)break;
    CHECK(w && h && x+w<=4096 && y+h<=4096);
    unsigned targetWidth=x+w,targetHeight=y+h;DWORD clear=0xffffffff;
    if(frozen) {
        std::ifstream file(archive/(stem+"1.state"));bool target=false,clearProof=false;
        while(std::getline(file,line)) {
            unsigned colorFormat=0,depthFormat=0,samples=0,quality=0,flags=0,stencil=0;float depth=0;
            if(std::sscanf(line.c_str(),"TARGET width=%u height=%u colorFormat=%u depthFormat=%u samples=%u quality=%u",&targetWidth,&targetHeight,&colorFormat,&depthFormat,&samples,&quality)==6)
                target=colorFormat==D3DFMT_A8R8G8B8 && depthFormat==D3DFMT_D24S8 && samples==0 && quality==0;
            if(std::sscanf(line.c_str(),"CLEAR flags=%u color=%lu depth=%f stencil=%u",&flags,&clear,&depth,&stencil)==4)
                clearProof=flags==7 && depth==1 && stencil==0;
        }
        CHECK(target && clearProof && targetWidth>=x+w && targetHeight>=y+h && targetWidth<=4096 && targetHeight<=4096);
        for(const auto& c:original)CHECK(c.viewport.X==x && c.viewport.Y==y && c.viewport.Width==w && c.viewport.Height==h);
    } else for(auto& snapshot:original)snapshot.viewport={x,y,w,h,0,1};
    std::ifstream nativeFile(reference/"history_replay.dx11_first_actual.bgra",std::ios::binary);
    const std::vector<unsigned char> native(std::istreambuf_iterator<char>{nativeFile},{});CHECK(native.size()==std::size_t(w)*h*4);
    const auto directory=reference/(normalCandidate?"accessory-normal-gpu":lightingCandidate?"accessory-lighting-gpu":wCandidatePolicy?"accessory-w-gpu-"+std::to_string(wCandidatePolicy):std::string(nativeCompare?"accessory-native-":"accessory-isolation-")+(driver==D3D11Driver::Hardware?"hardware":"warp"));std::filesystem::create_directories(directory);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=normalCandidate?CreateD3D11NormalCandidateDevice(desc,driver):lightingCandidate?CreateD3D11LightingCandidateDevice(desc,driver):wCandidatePolicy?CreateD3D11WCandidateDevice(desc,driver,wCandidatePolicy):CreateD3D11Device(desc,driver);CHECK(bundle);
    if(wCandidatePolicy) {
        unsigned vertices=0,wChanged=0,xyzChanged=0;
        for(unsigned draw=0;draw<original.size();++draw) {
            const auto& c=original[draw];std::vector<std::array<float,4>> before,beforeRaw,after,afterRaw,expectedXYZ,expectedRaw;
            CHECK(CaptureDepthVertexShader(c,before,&beforeRaw,true));CHECK(CaptureDepthVertexShader(c,after,&afterRaw,true,wCandidatePolicy));CHECK(before.size()==after.size());
            depth_diagnostic::Matrix world,view,projection;std::memcpy(world.data(),&c.world,64);std::memcpy(view.data(),&c.view,64);std::memcpy(projection.data(),&c.projection,64);
            const auto combined=w_shader_diagnostic::Inputs(world,view,projection,wCandidatePolicy).combined;const float column[]={combined[3],combined[7],combined[11],combined[15]};
            if(wCandidatePolicy>=2){auto combinedSource=c;combinedSource.world=combinedSource.view=Fixture().world;std::memcpy(&combinedSource.projection,combined.data(),64);CHECK(CaptureDepthVertexShader(combinedSource,expectedXYZ,&expectedRaw,true));}
            else expectedRaw=beforeRaw;
            CHECK(expectedRaw.size()==afterRaw.size());
            for(unsigned n=0;n<after.size();++n) {
                std::array<float,4> object{0,0,0,1};std::memcpy(object.data(),c.vertexBytes.data()+n*32,12);const float fused=depth_diagnostic::Dot(object.data(),column,depth_diagnostic::Rounding::Fused);
                if(wCandidatePolicy>=3){const float zColumn[]={combined[2],combined[6],combined[10],combined[14]};const float expectedZ=depth_diagnostic::Dot(object.data(),zColumn,w_shader_diagnostic::ZRounding(wCandidatePolicy));expectedRaw[n][2]=expectedZ;}
                CHECK(std::memcmp(&fused,&afterRaw[n][3],4)==0);CHECK(std::memcmp(afterRaw[n].data(),expectedRaw[n].data(),12)==0);
                wChanged+=std::memcmp(&beforeRaw[n][3],&afterRaw[n][3],4)!=0;xyzChanged+=std::memcmp(beforeRaw[n].data(),afterRaw[n].data(),12)!=0;
            }
            const auto saveClip=[&](const char* name,const std::vector<std::array<float,4>>& data){std::ofstream f(directory/("draw"+std::to_string(draw+1)+name),std::ios::binary);f.write(reinterpret_cast<const char*>(data.data()),data.size()*16);};
            saveClip(".original_raw.clip",beforeRaw);saveClip(".candidate_raw.clip",afterRaw);saveClip(".candidate_final.clip",after);saveClip(".expected_xyz.clip",expectedRaw);vertices+=static_cast<unsigned>(after.size());
            if(normalCandidate) {
                std::vector<std::array<float,4>> actualClip,actualRaw,colors,repeatedClip,repeatedColors;
                CHECK(CaptureDepthVertexShader(c,actualClip,&actualRaw,true,3,&colors,nullptr,nullptr,true));
                CHECK(CaptureDepthVertexShader(c,repeatedClip,nullptr,false,3,&repeatedColors,nullptr,nullptr,true));
                CHECK(actualClip==after && actualRaw==afterRaw && actualClip==repeatedClip && colors.size()==repeatedColors.size());
                CHECK(std::memcmp(colors.data(),repeatedColors.data(),colors.size()*16)==0);
                saveClip(".normal_candidate_lit.float4",colors);
                std::array<float,16> normalMatrix;const auto rounded=depth_diagnostic::Multiply(world,view,depth_diagnostic::Rounding::Sequential);
                const depth_diagnostic::Matrix identity{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};CHECK(BuildShaderNormalMatrix(rounded,identity,normalMatrix));
                std::ofstream matrixFile(directory/("draw"+std::to_string(draw+1)+".normal_candidate.matrix"),std::ios::binary);
                matrixFile.write(reinterpret_cast<const char*>(normalMatrix.data()),64);CHECK(matrixFile);
            }
        }
        std::printf("realWVerification policy=%u vertices=%u cpuFmaBits=EXACT expectedXYZBits=EXACT changedW=%u changedXYZ=%u nativeInputs=UNCHANGED\n",wCandidatePolicy,vertices,wChanged,xyzChanged);
    }
    std::printf("savedAccessory driver=%s adapter=%s nativeCapture=%s archive=%s clear=%08lx viewport=%u,%u,%u,%u\n",
        driver==D3D11Driver::Hardware?"hardware":"warp",bundle.adapterName.c_str(),nativeCompare?"NEW_PER_CONTROL":"PREVIOUS",frozen?"FROZEN_FIRST_DIFFERENCE":"OLDER_REDUCTION",static_cast<unsigned long>(clear),x,y,w,h);
    if(lightingCandidate)std::printf("lightingCandidate roundedMaterialFactor=1 diffuseThenAmbientFused=1 productionActivation=0\n");
    if(normalCandidate)std::printf("normalCandidate roundedWorldViewInverseTranspose=1 fusedXYZDot=1 hardwareNormalize=1 productionActivation=0\n");
    std::vector<unsigned char> baseline;unsigned baselineDifferences=0;
    const unsigned selectedTriangles[]={134,135,146,147,226,227};
    for(unsigned mode=0;mode<14;++mode) {
        auto snapshots=original;
        std::string name="original";
        if(mode==1){name="repeat";}
        if(mode==2){name="draw2_only";snapshots.erase(snapshots.begin());}
        if(mode==3){name="no_depth";for(auto& c:snapshots){for(auto& s:c.renderStates)if(s.key==D3DRS_ZENABLE || s.key==D3DRS_ZWRITEENABLE)s.value=0;}}
        if(mode==4){name="no_specular";for(auto& c:snapshots)for(auto& s:c.renderStates)if(s.key==D3DRS_SPECULARENABLE)s.value=0;}
        if(mode==5){name="no_normalize";for(auto& c:snapshots)for(auto& s:c.renderStates)if(s.key==D3DRS_NORMALIZENORMALS)s.value=0;}
        // Selected only from CPU projection of the high-delta row; these are
        // diagnostics on this known archive, not a general scene heuristic.
        if(mode>=6 && mode<12) {
            const unsigned triangle=selectedTriangles[mode-6];name="triangle"+std::to_string(triangle);
            snapshots.erase(snapshots.begin());CHECK(snapshots[0].count>triangle);
            snapshots[0].start+=triangle*3;snapshots[0].count=1;
        }
        if(mode==12) {
            name="reverse_triangles";auto& c=snapshots[1];const unsigned step=c.indexFormat==D3DFMT_INDEX16?2:4;
            for(unsigned n=0;n<c.count/2;++n)for(unsigned byte=0;byte<3*step;++byte)
                std::swap(c.indexBytes[(c.start+n*3)*step+byte],c.indexBytes[(c.start+(c.count-1-n)*3)*step+byte]);
        }
        if(mode==13){name="strict_less";for(auto& c:snapshots)for(auto& s:c.renderStates)if(s.key==D3DRS_ZFUNC)s.value=D3DCMP_LESS;}
        ModelReplayStream stream;stream.target.width=targetWidth;stream.target.height=targetHeight;
        stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& c:snapshots){const auto converted=AppendD3D9ReplaySnapshot(stream,c);if(!converted)std::fprintf(stderr,"savedAccessory conversion=%s\n",converted.reason.c_str());CHECK(converted);}stream.complete=true;
        std::vector<unsigned char> comparisonNative=native;
        if(nativeCompare) {
            RgbaImage fresh;CHECK(NativeImage(window,snapshots,static_cast<unsigned>(snapshots.size()),fresh,nullptr,targetWidth,targetHeight,clear));
            for(unsigned row=0;row<h;++row)for(unsigned col=0;col<w;++col) {
                const auto at=(std::size_t(row)*w+col)*4,src=(std::size_t(row+y)*fresh.width+col+x)*4;
                comparisonNative[at]=fresh.pixels[src+2];comparisonNative[at+1]=fresh.pixels[src+1];comparisonNative[at+2]=fresh.pixels[src];comparisonNative[at+3]=fresh.pixels[src+3];
            }
            std::ofstream output(directory/(name+"-native.bgra"),std::ios::binary);output.write(reinterpret_cast<const char*>(comparisonNative.data()),comparisonNative.size());
            if(wCandidatePolicy && mode<2)CHECK(comparisonNative==native);
        }
        RgbaImage image;CHECK(wCandidatePolicy?ReplayD3D11WCandidatePrefix(*bundle.device,stream,snapshots.size(),image):ReplayD3D11ModelPrefix(*bundle.device,stream,snapshots.size(),image));
        std::vector<unsigned char> crop(native.size());unsigned differences=0,large=0,maximum=0,baselineChanged=0;std::size_t first=0;
        for(unsigned row=0;row<h;++row)for(unsigned col=0;col<w;++col) {
            const auto at=(std::size_t(row)*w+col)*4,src=(std::size_t(row+y)*image.width+col+x)*4;
            crop[at]=image.pixels[src+2];crop[at+1]=image.pixels[src+1];crop[at+2]=image.pixels[src];crop[at+3]=image.pixels[src+3];
            unsigned delta=0;for(unsigned channel=0;channel<4;++channel)delta=(std::max)(delta,unsigned(std::abs(int(crop[at+channel])-comparisonNative[at+channel])));
            if(delta){if(!differences)first=at/4;++differences;}if(delta>1)++large;maximum=(std::max)(maximum,delta);
            if(!baseline.empty() && std::memcmp(crop.data()+at,baseline.data()+at,4))++baselineChanged;
        }
        if(!mode){baseline=crop;baselineDifferences=differences;}if(mode==1)CHECK(crop==baseline);
        std::printf("savedAccessory mode=%s comparison=%s differentPixels=%u deltaAboveOne=%u maxDelta=%u versusSelectedBaseline=%u first=%u,%u originalAcceptanceEligible=%u\n",
            name.c_str(),nativeCompare?"new_native":"saved_native",differences,large,maximum,baselineChanged,x+unsigned(first%w),y+unsigned(first/w),unsigned(nativeCompare && mode<2 && !wCandidatePolicy));
        std::ofstream output(directory/(name+".bgra"),std::ios::binary);output.write(reinterpret_cast<const char*>(crop.data()),crop.size());
    }
    CHECK(bundle.swapchain->Retire());
    std::printf("savedAccessory completed baselineDifferentPixels=%u repeatedDX11=EXACT nativeCapture=%s\n",baselineDifferences,nativeCompare?"NEW":"PREVIOUS");
    return baselineDifferences?32:0;
}
// Measured attachment comparisons rather than guessed depth-readback bits.
// ID colors remove lighting/interpolation from the observed surface choice.
int CoplanarDepthControls(HWND window,D3D11Driver driver,const char* archivePath,const char* referencePath,unsigned bake=0) {
    const std::filesystem::path archive(archivePath),reference(referencePath);
    D3D9ReplaySnapshot source;CHECK(ReadUntexturedReduction(archive/"history_replay.reduction.draw2.state",source));
    CHECK(source.fvf==274 && source.stride==32 && source.start==6 && source.count==232);
    unsigned x=0,y=0,w=0,h=0;std::ifstream nativeLog(reference/"history_replay.dx9");std::string line;
    while(std::getline(nativeLog,line))if(std::sscanf(line.c_str(),"PORTABLE_REGION x=%u y=%u width=%u height=%u",&x,&y,&w,&h)==4)break;
    CHECK(w && h && x+w<=4096 && y+h<=4096);source.viewport={x,y,w,h,0,1};
    const unsigned width=x+w,height=y+h;
    const auto originalSource=source;
    const char* bakeNames[]={"original","camera_float","camera_double","ndc_float","ndc_double","dx11_so_ndc","dx11_so_camera",
        "wv_float","wv_double","wvp_left_float","wvp_left_double","wvp_right_float","wvp_right_double",
        "wv_paired","wvp_left_paired","wvp_left_fused","wv_fused"};CHECK(bake<17);
    std::vector<std::array<float,4>> capturedPositions,capturedCameras,candidatePositions;
    if(bake>=5)CHECK(CaptureDepthVertexShader(source,capturedPositions));
    if(bake==6){std::vector<std::array<float,4>> instrumented;CHECK(CaptureDepthVertexShader(source,instrumented,&capturedCameras));
        CHECK(instrumented.size()==capturedPositions.size() && std::memcmp(instrumented.data(),capturedPositions.data(),instrumented.size()*16)==0);
        std::printf("instrumentedCameraCapture productionClipBits=EXACT vertices=%u\n",unsigned(instrumented.size()));}
    if(bake>=7) {
        using namespace depth_diagnostic;
        Matrix world,view,projection;std::memcpy(world.data(),&source.world,64);std::memcpy(view.data(),&source.view,64);std::memcpy(projection.data(),&source.projection,64);
        const auto rounding=(bake==8 || bake==10 || bake==12)?Rounding::Double:(bake==13 || bake==14)?Rounding::Paired:(bake==15 || bake==16)?Rounding::Fused:Rounding::Sequential;
        const bool cameraOnly=bake==7 || bake==8 || bake==13 || bake==16;
        const auto combined=cameraOnly?Multiply(world,view,rounding):(bake==11 || bake==12)?Multiply(world,Multiply(view,projection,rounding),rounding):Multiply(Multiply(world,view,rounding),projection,rounding);
        source.world=source.view=Fixture().world;
        std::memcpy(cameraOnly?&source.view:&source.projection,combined.data(),64);
        CHECK(CaptureDepthVertexShader(source,candidatePositions));CHECK(candidatePositions.size()==capturedPositions.size());
        unsigned changedVertices=0,changedComponents=0;
        for(std::size_t n=0;n<candidatePositions.size();++n){bool changed=false;for(unsigned k=0;k<4;++k)if(std::memcmp(&candidatePositions[n][k],&capturedPositions[n][k],4)){++changedComponents;changed=true;}if(changed)++changedVertices;}
        std::printf("matrixCombination mode=%s dx11ChangedClipVertices=%u dx11ChangedClipComponents=%u nativeOutputCaptured=0\n",bakeNames[bake],changedVertices,changedComponents);
    }
    if(bake>0 && bake<7) {
        for(std::size_t at=0;at<source.vertexBytes.size();at+=32) {
            float xyz[3];std::memcpy(xyz,source.vertexBytes.data()+at,12);std::array<double,4> value{xyz[0],xyz[1],xyz[2],1};
            for(const auto* matrix:{&source.world,&source.view,&source.projection}) {
                if(matrix==&source.projection && bake<3)break;
                std::array<double,4> next{};const auto* m=reinterpret_cast<const float*>(matrix);
                for(unsigned col=0;col<4;++col)for(unsigned k=0;k<4;++k) {
                    if(bake==1 || bake==3) {
                        volatile float product=static_cast<float>(value[k])*m[k*4+col];
                        volatile float sum=static_cast<float>(next[col])+product;next[col]=sum;
                    }else next[col]+=value[k]*m[k*4+col];
                }
                value=next;
            }
            for(unsigned col=0;col<3;++col)xyz[col]=bake<3?static_cast<float>(value[col]):bake==3?static_cast<float>(value[col])/static_cast<float>(value[3]):static_cast<float>(value[col]/value[3]);
            if(bake==5) {
                const auto& clip=capturedPositions[at/32];CHECK(std::isfinite(clip[3]));
                if(clip[3]!=0){xyz[0]=clip[0]/clip[3]-1.f/w;xyz[1]=clip[1]/clip[3]+1.f/h;xyz[2]=clip[2]/clip[3];}
                else xyz[0]=xyz[1]=xyz[2]=0; // Unreferenced/behind-camera vertices are not a clipped-geometry equivalence claim.
            }
            if(bake==6){CHECK(capturedCameras[at/32][3]==1);std::memcpy(xyz,capturedCameras[at/32].data(),12);}
            std::memcpy(source.vertexBytes.data()+at,xyz,12);
        }
        source.world=source.view=Fixture().world;if(bake>=3 && bake!=6)source.projection=Fixture().projection;
        if(bake==6){std::vector<std::array<float,4>> replayPositions;CHECK(CaptureDepthVertexShader(source,replayPositions));
            CHECK(replayPositions.size()==capturedPositions.size() && std::memcmp(replayPositions.data(),capturedPositions.data(),replayPositions.size()*16)==0);
            std::printf("cameraBypass productionClipBits=EXACT vertices=%u\n",unsigned(replayPositions.size()));}
    }
    const auto directory=reference/((driver==D3D11Driver::Hardware?"coplanar-depth-hardware":"coplanar-depth-warp")+std::string(bake?"-":"")+(bake?bakeNames[bake]:""));std::filesystem::create_directories(directory);
    if(bake) {
        std::ofstream file(directory/"baked_positions.bin",std::ios::binary);file.write(reinterpret_cast<const char*>(source.vertexBytes.data()),source.vertexBytes.size());
        if(bake>=5){std::ofstream clip(directory/"dx11_clip_xyzw.bin",std::ios::binary);clip.write(reinterpret_cast<const char*>(capturedPositions.data()),capturedPositions.size()*16);}
        if(!candidatePositions.empty()){std::ofstream clip(directory/"candidate_dx11_clip_xyzw.bin",std::ios::binary);clip.write(reinterpret_cast<const char*>(candidatePositions.data()),candidatePositions.size()*16);}
        std::ofstream matrices(directory/"candidate_matrices.bin",std::ios::binary);for(auto* matrix:{&source.world,&source.view,&source.projection})matrices.write(reinterpret_cast<const char*>(matrix),64);
    }
    std::ofstream report(directory/"measurements.csv");report<<"kind,pair,order,comparison,repeat,triangle,x,y,referenceFloat,referenceBits,offset,dx9,dx11,differentPixels\n";report<<std::setprecision(17);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
    std::printf("depthDevice driver=%s adapter=%s viewport=%u,%u,%u,%u transformInput=%s cpuBakeIsNativeCapture=0\n",driver==D3D11Driver::Hardware?"hardware":"warp",bundle.adapterName.c_str(),x,y,w,h,bakeNames[bake]);
    auto change=[](D3D9ReplaySnapshot& c,unsigned key,DWORD value){for(auto& entry:c.renderStates)if(entry.key==key){entry.value=value;return;}c.renderStates.push_back({0,key,value});};
    auto id=[&](D3D9ReplaySnapshot c,bool green) {
        // Retain position/normal layout and matrices: only shading/state
        // diagnostics change, not the geometry's vertex transform path.
        change(c,D3DRS_LIGHTING,TRUE);change(c,D3DRS_SPECULARENABLE,FALSE);
        change(c,D3DRS_ALPHABLENDENABLE,FALSE);change(c,D3DRS_ALPHATESTENABLE,FALSE);
        change(c,D3DRS_STENCILENABLE,FALSE);change(c,D3DRS_CULLMODE,D3DCULL_NONE);
        change(c,D3DRS_ZENABLE,TRUE);change(c,D3DRS_ZWRITEENABLE,TRUE);change(c,D3DRS_ZFUNC,D3DCMP_LESSEQUAL);
        change(c,D3DRS_AMBIENT,0);c.material={};c.material.Diffuse.a=1;
        c.material.Emissive=green?D3DCOLORVALUE{0,1,0,0}:D3DCOLORVALUE{1,0,0,0};c.lights.clear();
        Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);c.textureInfo={};c.textureBytes={};c.preparedMips={};return c;
    };
    auto triangle=[&](unsigned n,bool green){auto c=id(source,green);c.start+=n*3;c.count=1;return c;};
    auto render=[&](const std::vector<D3D9ReplaySnapshot>& draws,RgbaImage& native,RgbaImage& replay) {
        if(!NativeImage(window,draws,static_cast<unsigned>(draws.size()),native,nullptr,width,height))return false;
        ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& c:draws){const auto result=AppendD3D9ReplaySnapshot(stream,c);if(!result){std::fprintf(stderr,"depthConversion=%s\n",result.reason.c_str());return false;}}
        stream.complete=true;return bool(ReplayD3D11ModelPrefix(*bundle.device,stream,draws.size(),replay));
    };
    auto classify=[](const RgbaImage& image,std::size_t pixel){const auto* p=image.pixels.data()+pixel*4;
        if(p[0]==255 && !p[1] && !p[2] && p[3]==255)return 'R';
        if(!p[0] && p[1]==255 && !p[2] && p[3]==255)return 'G';
        return 'B';};
    auto save=[&](const std::string& name,const RgbaImage& image){std::ofstream file(directory/name,std::ios::binary);file.write(reinterpret_cast<const char*>(image.pixels.data()),image.pixels.size());};
    const unsigned pairs[][2]={{134,226},{135,227},{146,226},{147,227},{135,226}};
    unsigned comparisons=0,failed=0,probes=0,probeDifferences=0;
    for(const auto& pair:pairs) {
        const std::string label=std::to_string(pair[0])+"_"+std::to_string(pair[1]);
        std::vector<std::size_t> points;
        std::vector<unsigned char> previousNative,previousReplay;
        for(unsigned cycle=0;cycle<3;++cycle)for(unsigned comparison=0;comparison<(cycle?1u:3u);++comparison)for(unsigned order=0;order<2;++order)for(unsigned repeat=0;repeat<(!cycle && comparison==0?3u:1u);++repeat) {
            auto a=triangle(pair[0],false),b=triangle(pair[1],true);
            if(cycle)for(auto* c:{&a,&b}) {
                const unsigned step=c->indexFormat==D3DFMT_INDEX16?2:4;std::array<unsigned char,12> indices{};
                std::memcpy(indices.data(),c->indexBytes.data()+c->start*step,3*step);
                for(unsigned n=0;n<3;++n)std::memcpy(c->indexBytes.data()+(c->start+n)*step,indices.data()+((n+cycle)%3)*step,step);
            }
            for(auto* c:{&a,&b}){change(*c,D3DRS_ZFUNC,comparison==1?D3DCMP_LESS:D3DCMP_LESSEQUAL);if(comparison==2)change(*c,D3DRS_ZENABLE,FALSE);}
            std::vector<D3D9ReplaySnapshot> draws=order?std::vector<D3D9ReplaySnapshot>{b,a}:std::vector<D3D9ReplaySnapshot>{a,b};
            RgbaImage native,replay;CHECK(render(draws,native,replay));const auto difference=PixelDifferences(native,replay);
            if(bake && !cycle && !comparison && !order && !repeat){save(label+"-native.rgba",native);save(label+"-dx11.rgba",replay);}
            if(bake && !cycle && !comparison && !order && !repeat) {
                auto a=id(originalSource,false),b=id(originalSource,true);a.start+=pair[0]*3;b.start+=pair[1]*3;a.count=b.count=1;
                RgbaImage nativeOriginal,replayOriginal;CHECK(render({a,b},nativeOriginal,replayOriginal));
                const auto nativeChanged=PixelDifferences(native,nativeOriginal),replayChanged=PixelDifferences(replay,replayOriginal);
                report<<"bake_change,"<<label<<",0,Native,0,,,,,,,,,"<<nativeChanged<<"\n";
                report<<"bake_change,"<<label<<",0,DX11,0,,,,,,,,,"<<replayChanged<<"\n";
                std::printf("transformBake pair=%s mode=%s nativeChangedPixels=%u dx11ChangedPixels=%u nativeEquivalence=%u\n",label.c_str(),bakeNames[bake],nativeChanged,replayChanged,unsigned(!nativeChanged));
                for(std::size_t p=0;p<nativeOriginal.pixels.size()/4;++p)if(classify(nativeOriginal,p)!=classify(replayOriginal,p)) {
                    points.push_back(p);if(points.size()==16)break;
                }
            }
            if(comparison==2)CHECK(!difference); // Coverage/color prerequisite.
            if(!cycle && !comparison && !order){if(repeat){CHECK(native.pixels==previousNative && replay.pixels==previousReplay);}else{previousNative=native.pixels;previousReplay=replay.pixels;}}
            report<<(cycle?"pair_cycle"+std::to_string(cycle):"pair")<<","<<label<<","<<order<<","<<(comparison==0?"LessEqual":comparison==1?"Less":"DepthDisabled")<<","<<repeat<<",,,,,,,,,"<<difference<<"\n";report.flush();
            std::printf("depthPair=%s cycle=%u order=%u comparison=%u repeat=%u differentPixels=%u\n",label.c_str(),cycle,order,comparison,repeat,difference);
            if(cycle && !order) {
                RgbaImage previous{width,height,previousNative},priorReplay{width,height,previousReplay};
                const auto nativeChanges=PixelDifferences(native,previous),replayChanges=PixelDifferences(replay,priorReplay);
                report<<"cycle_delta"<<cycle<<","<<label<<",0,Native,0,,,,,,,,,"<<nativeChanges<<"\n";
                report<<"cycle_delta"<<cycle<<","<<label<<",0,DX11,0,,,,,,,,,"<<replayChanges<<"\n";
                std::printf("depthCyclic pair=%s cycle=%u nativeChangedPixels=%u dx11ChangedPixels=%u\n",label.c_str(),cycle,nativeChanges,replayChanges);
            }
            if(difference){++failed;if(!cycle && !comparison && !order && !repeat){
                save(label+"-native.rgba",native);save(label+"-dx11.rgba",replay);
                for(std::size_t p=0;p<native.pixels.size()/4;++p)if(classify(native,p)!=classify(replay,p)) {
                    if(std::find(points.begin(),points.end(),p)==points.end())points.push_back(p);if(points.size()==16)break;
                }
            }}++comparisons;
        }
        for(unsigned range=0;range<3;++range)for(unsigned order=0;order<2;++order) {
            auto a=triangle(pair[0],false),b=triangle(pair[1],true);
            for(auto* c:{&a,&b}) {
                c->viewport.MinZ=range==2?.5f:0;
                c->viewport.MaxZ=range==0?.5f:range==1?.125f:1;
            }
            RgbaImage native,replay;CHECK(render(order?std::vector<D3D9ReplaySnapshot>{b,a}:std::vector<D3D9ReplaySnapshot>{a,b},native,replay));
            const auto differences=PixelDifferences(native,replay);
            const char* name=range==0?"range_half":range==1?"range_eighth":"range_upper_half";
            report<<name<<","<<label<<","<<order<<",LessEqual,0,,,,,,,,,"<<differences<<"\n";
            std::printf("depthRange pair=%s range=%s order=%u differentPixels=%u\n",label.c_str(),name,order,differences);
            ++comparisons;if(differences)++failed;
        }
        if(bake) {
            // Holdout coordinates are chosen by coverage, never by depth
            // agreement or an observed fitting residual.
            RgbaImage coverage[2],unused;
            for(unsigned n=0;n<2;++n){auto c=id(originalSource,false);c.start+=pair[n]*3;c.count=1;CHECK(render({c},coverage[n],unused));}
            for(std::size_t p=0;p<coverage[0].pixels.size()/4;++p)if(classify(coverage[0],p)=='R' && classify(coverage[1],p)=='R' && std::find(points.begin(),points.end(),p)==points.end()) {
                points.push_back(p);report<<"holdout,"<<label<<",,CoverageSelected,0,,"<<p%width<<","<<p/width<<",,,,,,\n";break;
            }
        }
        if(points.empty())continue;
        for(unsigned selected:pair) {
            RgbaImage native,replay;CHECK(render({triangle(selected,false)},native,replay));CHECK(!PixelDifferences(native,replay));
            for(auto point:points)CHECK(classify(native,point)=='R' && classify(replay,point)=='R');
        }
        // Double CPU projection only centers a reference scan. Every reported
        // depth relation below is determined by native attachment comparisons.
        const auto screen=[&](unsigned index) {
            float xyz[3];std::memcpy(xyz,source.vertexBytes.data()+index*32,12);std::array<double,4> p{xyz[0],xyz[1],xyz[2],1};
            for(const auto* matrix:{&source.world,&source.view,&source.projection}) {
                std::array<double,4> next{};const auto* m=reinterpret_cast<const float*>(matrix);
                for(unsigned col=0;col<4;++col)for(unsigned k=0;k<4;++k)next[col]+=p[k]*m[k*4+col];p=next;
            }
            return std::array<double,3>{x+(p[0]/p[3]+1)*w/2,y+(1-p[1]/p[3])*h/2,p[2]/p[3]};
        };
        for(auto point:points) {
            const unsigned px=static_cast<unsigned>(point%width),py=static_cast<unsigned>(point/width);
            const auto c=triangle(pair[0],false);std::array<std::array<double,3>,3> vertices;
            for(unsigned n=0;n<3;++n){unsigned index=0;const auto step=c.indexFormat==D3DFMT_INDEX16?2:4;std::memcpy(&index,c.indexBytes.data()+(c.start+n)*step,step);vertices[n]=screen(index);}
            const auto& a=vertices[0];const auto& b=vertices[1];const auto& d=vertices[2];
            const double den=(b[1]-d[1])*(a[0]-d[0])+(d[0]-b[0])*(a[1]-d[1]);CHECK(den!=0);
            const double u=((b[1]-d[1])*(px-d[0])+(d[0]-b[0])*(py-d[1]))/den;
            const double v=((d[1]-a[1])*(px-d[0])+(a[0]-d[0])*(py-d[1]))/den;
            const float center=static_cast<float>(u*a[2]+v*b[2]+(1-u-v)*d[2]);std::uint32_t centerBits=0;std::memcpy(&centerBits,&center,4);
            for(unsigned selected:pair)for(unsigned comparison=0;comparison<2;++comparison)for(int offset=-4;offset<=4;++offset) {
                const std::uint32_t bits=static_cast<std::uint32_t>(static_cast<std::int64_t>(centerBits)+offset);float depth=0;std::memcpy(&depth,&bits,4);
                auto referenceDraw=id(Fixture(),true);referenceDraw.viewport=source.viewport;referenceDraw.textureMatrices=source.textureMatrices;
                const float full[]={-1,-1,depth,0,0,1,0,0,-1,1,depth,0,0,1,0,0,1,-1,depth,0,0,1,0,0,1,1,depth,0,0,1,0,0};
                referenceDraw.vertexBytes.resize(sizeof(full));std::memcpy(referenceDraw.vertexBytes.data(),full,sizeof(full));referenceDraw.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};referenceDraw.vertices=4;referenceDraw.count=2;
                change(referenceDraw,D3DRS_ZWRITEENABLE,FALSE);change(referenceDraw,D3DRS_ZFUNC,comparison?D3DCMP_EQUAL:D3DCMP_LESS);
                RgbaImage native,replay;CHECK(render({triangle(selected,false),referenceDraw},native,replay));
                const char n=classify(native,point),r=classify(replay,point);CHECK(n!='B' && r!='B');
                report<<"probe,"<<label<<",,"<<(comparison?"Equal":"Less")<<",0,"<<selected<<","<<px<<","<<py<<","<<depth<<","<<bits<<","<<offset<<","<<n<<","<<r<<",\n";
                ++probes;if(n!=r)++probeDifferences;
            }
            report.flush();
        }
    }
    // Calibrate the reference ruler independently of captured geometry.
    // Near this depth, float32 spacing is 2^-24; the D24 code spacing is
    // 1/(2^24-1). Do not equate them or claim raw attachment-bit readback.
    const float calibrationDepth=.99142f;std::uint32_t calibrationBits=0;std::memcpy(&calibrationBits,&calibrationDepth,4);
    unsigned calibrationComparisons=0;
    for(unsigned comparison=0;comparison<3;++comparison)for(int offset=-2;offset<=2;++offset) {
        const std::uint32_t bits=static_cast<std::uint32_t>(static_cast<std::int64_t>(calibrationBits)+offset);float depth=0;std::memcpy(&depth,&bits,4);
        auto first=id(Fixture(),false),second=id(Fixture(),true);
        for(auto* c:{&first,&second}) {
            c->viewport=source.viewport;const float z=c==&first?calibrationDepth:depth;
            const float vertices[]={-1,-1,z,0,0,1,0,0,-1,1,z,0,0,1,0,0,1,-1,z,0,0,1,0,0,1,1,z,0,0,1,0,0};
            c->vertexBytes.resize(sizeof(vertices));std::memcpy(c->vertexBytes.data(),vertices,sizeof(vertices));
            c->vertices=4;c->count=2;c->indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};
        }
        const unsigned func=comparison==0?D3DCMP_LESS:comparison==1?D3DCMP_EQUAL:D3DCMP_LESSEQUAL;
        change(second,D3DRS_ZFUNC,func);change(second,D3DRS_ZWRITEENABLE,FALSE);
        RgbaImage native,replay;CHECK(render({first,second},native,replay));CHECK(!PixelDifferences(native,replay));
        const auto point=std::size_t(y+h/2)*width+x+w/2;
        const bool pass=comparison==0?offset<0:comparison==1?offset==0:offset<=0;
        CHECK(classify(native,point)==(pass?'G':'R') && classify(replay,point)==(pass?'G':'R'));
        report<<"calibration,constant,,"<<(comparison==0?"Less":comparison==1?"Equal":"LessEqual")<<",0,,"<<point%width<<","<<point/width<<","<<depth<<","<<bits<<","<<offset<<","<<classify(native,point)<<","<<classify(replay,point)<<",0\n";
        ++calibrationComparisons;
    }
    CHECK(bundle.swapchain->Retire());std::printf("depthMeasurements pairs=%u mismatchingPairs=%u referenceProbes=%u mismatchingProbeResults=%u bias=0 singleSample=1 attachment=D24S8\n",comparisons,failed,probes,probeDifferences);
    std::printf("depthReferenceCalibration comparisons=%u differentPixels=0 expectedRelations=PASS float32Spacing=2^-24 rawDepthReadback=0\n",calibrationComparisons);
    return failed || probeDifferences?32:0;
}
#include "sensitive_depth_fixture.hpp"
#include "perspective_case10_fixture.hpp"
#include "w_overlap_depth_fixture.hpp"
#include "z_explicit_depth_fixture.hpp"
#include "accessory_color_fixture.hpp"
#include "lighting_rounding_fixture.hpp"
#include "normal_precision_fixture.hpp"
#include "normal_transform_fixture.hpp"
#include "scene_prefix_fixture.hpp"
#include "accessory_alpha_history_fixture.hpp"
#include "ground_history_isolation_fixture.hpp"
#include "ground_endpoint_depth_fixture.hpp"
#include "accessory_depth_threshold_fixture.hpp"
#include "ground_explicit_clip_fixture.hpp"
#include "model_color_isolation_fixture.hpp"
#include "model_batch_color_fixture.hpp"
#include "model_batch_stage_fixture.hpp"
#include "model_batch_causal_fixture.hpp"
#include "accessory_alpha_sampling_fixture.hpp"
#include "alpha_conversion_independent_fixture.hpp"
#include "model_final_modulate_fixture.hpp"
#include "model_sampling_fixture.hpp"
#include "model_transform_fixture.hpp"
#include "model_batch_uv_origin_fixture.hpp"
#include "model_specular_origin_fixture.hpp"
#include "model_specular_stages_fixture.hpp"
#include "model_specular_scope_fixture.hpp"
#include "model_toon_rounding_fixture.hpp"
#include "model_texture_fma_scope_fixture.hpp"
#include "independent_xy_fixture.hpp"
#include "dx11_compatibility_fixture.hpp"
#ifdef MIKUDANCESTUDIO_RHI_D3D12
#include "resident_pmm_fixture.hpp"
#include "alpha_history_diagnostic_fixture.hpp"
#endif
int ConvertedShadowControls(HWND window,D3D11Driver driver) {
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    unsigned comparisons=0;
    for(unsigned mode=0;mode<6;++mode)for(bool texture:{false,true}) {
        auto base=Fixture();base.textureBytes[0]={255,0,0,255};base.world._43=.25f;
        auto shadow=ShadowFixture(mode,texture);
        std::vector<D3D9ReplaySnapshot> snapshots{base,shadow,shadow};
        ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& c:snapshots){const auto result=AppendD3D9ReplaySnapshot(stream,c,true);if(!result)std::fprintf(stderr,"shadowConversion reason=%s\n",result.reason.c_str());CHECK(result);}stream.complete=true;
        std::array<RgbaImage,3> native;for(unsigned prefix=1;prefix<=3;++prefix)CHECK(NativeImage(window,snapshots,prefix,native[prefix-1]));
        CHECK(PixelDifferences(native[0],native[1])>0 && PixelDifferences(native[1],native[2])==0);
        for(unsigned replacement=0;replacement<2;++replacement) {
            auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
            for(unsigned prefix:{1u,2u,3u,1u}) {
                RgbaImage image;CHECK(ReplayD3D11ModelPrefix(*bundle.device,stream,prefix,image));
                const auto differences=PixelDifferences(image,native[prefix-1]);const auto at=(40*64+16)*4;
                if(differences)std::fprintf(stderr,"shadow mode=%u texture=%u prefix=%u differences=%u dx9=%u,%u,%u,%u dx11=%u,%u,%u,%u\n",
                    mode,texture,prefix,differences,native[prefix-1].pixels[at],native[prefix-1].pixels[at+1],native[prefix-1].pixels[at+2],native[prefix-1].pixels[at+3],
                    image.pixels[at],image.pixels[at+1],image.pixels[at+2],image.pixels[at+3]);
                CHECK(!differences);++comparisons;
            }
            CHECK(bundle.swapchain->Retire());
        }
    }
    std::printf("shadowComparisons=%u differingPixels=0 colorLightingStencilDepth=PASS deviceReplacement=PASS\n",comparisons);return 0;
}
int ConvertedMipControls(HWND window,D3D11Driver driver) {
    std::vector<ModelReplayStream> streams;std::vector<RgbaImage> native;
    for(unsigned shape=0;shape<2;++shape)for(unsigned pattern=0;pattern<2;++pattern)for(DWORD filter:{DWORD(D3DTEXF_POINT),DWORD(D3DTEXF_LINEAR)}) {
        const unsigned width=64,height=shape?16:64;auto c=MipFixture(width,height,0,pattern,filter);
        ModelTextureData prepared;RgbaImage image;CHECK(NativeImage(window,{c},1,image,&prepared));
        for(unsigned lod=0;lod<7;++lod) {
            c=MipFixture(width,height,lod,pattern,filter);c.preparedMips[0]=prepared;
            ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
            const auto converted=AppendD3D9ReplaySnapshot(stream,c);
            if(!converted)std::fprintf(stderr,"mipConversion reason=%s\n",converted.reason.c_str());
            CHECK(converted);stream.complete=true;streams.push_back(std::move(stream));
            CHECK(NativeImage(window,{c},1,image));native.push_back(image);
        }
    }
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    unsigned comparisons=0;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
        for(unsigned control=0;control<streams.size();++control) {
            RgbaImage image;CHECK(ReplayD3D11ModelPrefix(*bundle.device,streams[control],1,image));
            const auto differences=PixelDifferences(image,native[control]);
            if(differences)std::fprintf(stderr,"convertedMip case=%u lod=%u differences=%u\n",control,control%7,differences);
            CHECK(!differences);++comparisons;
        }
        CHECK(bundle.swapchain->Retire());
    }
    std::printf("convertedMipComparisons=%u differingPixels=0 deviceReplacement=PASS\n",comparisons);return 0;
}
int ConvertedNullTextureControls(HWND window,D3D11Driver driver) {
    std::vector<ModelReplayStream> streams;std::vector<RgbaImage> native;std::vector<unsigned> prefixes;
    for(unsigned stage=0;stage<3;++stage)for(bool add:{false,true})for(bool lit:{false,true})for(unsigned alpha=0;alpha<4;++alpha) {
        auto c=NullTextureFixture(stage,add,lit,alpha);
        ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
        CHECK(AppendD3D9ReplaySnapshot(stream,c));stream.complete=true;streams.push_back(std::move(stream));
        RgbaImage image;CHECK(NativeImage(window,{c},1,image));native.push_back(std::move(image));prefixes.push_back(1);
    }
    for(unsigned stage=0;stage<3;++stage)for(bool add:{false,true}) {
        auto null=NullTextureFixture(stage,add,true,0);Stage(null,3,D3DTSS_COLOROP,D3DTOP_DISABLE);
        auto bound=null;bound.textureInfo[stage]=Fixture().textureInfo[0];bound.textureBytes[stage]={255,0,0,128};
        const std::vector<D3D9ReplaySnapshot> snapshots{null,bound,null};
        ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& snapshot:snapshots)CHECK(AppendD3D9ReplaySnapshot(stream,snapshot));stream.complete=true;
        std::array<RgbaImage,3> images;
        for(unsigned prefix=1;prefix<=3;++prefix)CHECK(NativeImage(window,snapshots,prefix,images[prefix-1]));
        CHECK(PixelDifferences(images[0],images[1])>0 && PixelDifferences(images[0],images[2])==0);
        for(unsigned prefix:{1u,2u,3u,1u}) {streams.push_back(stream);native.push_back(images[prefix-1]);prefixes.push_back(prefix);}
    }
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    unsigned comparisons=0,failedComparisons=0,maximumChannelDifference=0;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
        for(unsigned control=0;control<streams.size();++control) {
            RgbaImage image;CHECK(ReplayD3D11ModelPrefix(*bundle.device,streams[control],prefixes[control],image));
            const auto differences=PixelDifferences(image,native[control]);
            if(differences) {
                ++failedComparisons;
                for(std::size_t byte=0;byte<image.pixels.size();++byte) {
                    const auto a=image.pixels[byte],b=native[control].pixels[byte];const unsigned delta=a>b?a-b:b-a;
                    if(delta>maximumChannelDifference)maximumChannelDifference=delta;
                }
                const auto pixel=(40*64+16)*4;
                std::fprintf(stderr,"convertedNull case=%u prefix=%u differences=%u dx9=%u,%u,%u,%u dx11=%u,%u,%u,%u\n",
                    control,prefixes[control],differences,
                    native[control].pixels[pixel],native[control].pixels[pixel+1],native[control].pixels[pixel+2],native[control].pixels[pixel+3],
                    image.pixels[pixel],image.pixels[pixel+1],image.pixels[pixel+2],image.pixels[pixel+3]);
                if(control<48) {
                    // An independently converted explicit DISABLE uses the
                    // previously supported path. Equal output isolates any
                    // cross-driver precision difference from null handling.
                    auto disabled=NullTextureFixture(control/16,(control/8)%2!=0,(control/4)%2!=0,control%4);
                    Stage(disabled,control/16,D3DTSS_COLOROP,D3DTOP_DISABLE);
                    ModelReplayStream baseline;baseline.target.width=baseline.target.height=64;baseline.events.push_back({1,ModelReplayOp::Clear});
                    CHECK(AppendD3D9ReplaySnapshot(baseline,disabled));baseline.complete=true;
                    RgbaImage baselineImage;CHECK(ReplayD3D11ModelPrefix(*bundle.device,baseline,1,baselineImage));
                    const auto baselineDifference=PixelDifferences(image,baselineImage);
                    std::printf("convertedNull case=%u vsExplicitDisable=%u\n",control,baselineDifference);CHECK(!baselineDifference);
                }
            }
            ++comparisons;
        }
        CHECK(bundle.swapchain->Retire());
    }
    std::printf("convertedNullTextureComparisons=%u failedComparisons=%u maxChannelDifference=%u deviceReplacement=PASS\n",
        comparisons,failedComparisons,maximumChannelDifference);
    CHECK(!failedComparisons);return 0;
}
#endif
int main(int argc,char** argv) {
    // Independent cancellation cases verify the diagnostic's actual rounding
    // boundaries, rather than assuming the optimizer honors their names.
    using depth_diagnostic::Rounding;
    const float cancellation[]={33554432.f,1,-33554432.f,1},ones[]={1,1,1,1};
    CHECK(depth_diagnostic::Dot(cancellation,ones,Rounding::Sequential)==1);
    CHECK(depth_diagnostic::Dot(cancellation,ones,Rounding::Paired)==0);
    CHECK(depth_diagnostic::Dot(cancellation,ones,Rounding::Double)==2);
    const float fusedA[]={-1,1+std::ldexp(1.f,-23),0,0},fusedB[]={1,1-std::ldexp(1.f,-23),0,0};
    CHECK(depth_diagnostic::Dot(fusedA,fusedB,Rounding::Sequential)==0);
    CHECK(depth_diagnostic::Dot(fusedA,fusedB,Rounding::Fused)==-std::ldexp(1.f,-46));
    if(argc==2 && std::string(argv[1])=="--native-mips") {
        const auto window=CreateWindowExW(0,L"STATIC",L"Native mip capture control",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
        CHECK(window);const auto result=NativeMipControls(window);DestroyWindow(window);return result;
    }
    if(argc==2 && std::string(argv[1])=="--native-null") {
        const auto window=CreateWindowExW(0,L"STATIC",L"Native null texture control",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
        CHECK(window);const auto result=NativeNullTextureControls(window);DestroyWindow(window);return result;
    }
    CHECK(NullTextureConversionControls()==0);
    CHECK(MipConversionControls()==0);
    CHECK(ShadowConversionControls()==0);
    CHECK(ground_replay_diagnostic::Conversion()==0);
    CHECK(ReductionReaderControls()==0);
    if(argc==3 && std::string(argv[1])=="--audit-reduction") {
        D3D9ReplaySnapshot captured;CHECK(ReadUntexturedReduction(argv[2],captured));
        ModelReplayStream audit;
        // Diagnostic local target bounds enclosing the original viewport.
        // This audits a single snapshot, never asserts a complete scene capture.
        audit.target.width=captured.viewport.X+captured.viewport.Width;audit.target.height=captured.viewport.Y+captured.viewport.Height;
        audit.events.push_back({1,ModelReplayOp::Clear});
        const auto result=AppendD3D9ReplaySnapshot(audit,captured);
        std::printf("archive=%s status=%s reason=%s viewport=%u,%u,%u,%u depth=%g,%g fvf=%u triangles=%u\n",argv[2],
            result?"CONVERTIBLE":"BLOCKED",result.reason.c_str(),captured.viewport.X,captured.viewport.Y,captured.viewport.Width,captured.viewport.Height,
            captured.viewport.MinZ,captured.viewport.MaxZ,captured.fvf,captured.count);
        return result?0:31;
    }
    ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
    auto c=Fixture();CHECK(AppendD3D9ReplaySnapshot(stream,c));
    {auto accessory=c;accessory.accessoryMaterial=true;ModelReplayStream input;input.target=stream.target;
        input.events.push_back({1,ModelReplayOp::Clear});CHECK(AppendD3D9ReplaySnapshot(input,accessory));
        CHECK(input.events.back().draw.pipeline.shader.layout.stages[0].role==MaterialTextureRole::Base);
        // Slot zero is not intrinsically Toon. Accessory Sphere uses the same
        // native camera-normal coordinates, with explicit scene-walk metadata.
        for(auto& state:accessory.stageStates)if(state.stage==0){
            if(state.key==D3DTSS_TEXCOORDINDEX)state.value=D3DTSS_TCI_CAMERASPACENORMAL;
            if(state.key==D3DTSS_TEXTURETRANSFORMFLAGS)state.value=D3DTTFF_COUNT2;}
        CHECK(AppendD3D9ReplaySnapshot(input,accessory));
        CHECK(input.events.back().draw.pipeline.shader.layout.stages[0].role==MaterialTextureRole::Sphere);
        CHECK(input.events.back().draw.pipeline.shader.layout.sphere==SphereOperation::Multiply);
    }
    CHECK(stream.resources[2].texture.levels[0].pixels==std::vector<unsigned char>({211,13,7,255}));
    // A promoted sphere in stage 1 is identified by camera-normal coordinates,
    // not by a generic stage-number-to-Base label. Its Add/Multiply contract
    // must survive the diagnostic transport for CPU-field comparison.
    for(const auto operation:{D3DTOP_MODULATE,D3DTOP_ADD}) {
        auto sphere=Fixture();sphere.textureInfo[1]=sphere.textureInfo[0];sphere.textureBytes[1]=sphere.textureBytes[0];
        for(auto state:Fixture().stageStates)if(state.stage==0){state.stage=1;sphere.stageStates.push_back(state);}
        for(auto state:Fixture().samplerStates){state.stage=1;sphere.samplerStates.push_back(state);}
        Stage(sphere,1,D3DTSS_COLOROP,operation);Stage(sphere,1,D3DTSS_COLORARG2,D3DTA_CURRENT);
        Stage(sphere,1,D3DTSS_TEXCOORDINDEX,D3DTSS_TCI_CAMERASPACENORMAL);Stage(sphere,1,D3DTSS_TEXTURETRANSFORMFLAGS,D3DTTFF_COUNT2);
        ModelReplayStream converted;converted.target=stream.target;converted.events.push_back({1,ModelReplayOp::Clear});
        CHECK(AppendD3D9ReplaySnapshot(converted,sphere));const auto& layout=converted.events.back().draw.pipeline.shader.layout;
        CHECK(layout.stages[1].role==MaterialTextureRole::Sphere && layout.sphere==(operation==D3DTOP_ADD?SphereOperation::Add:SphereOperation::Multiply));
    }
    c.textureBytes[0]={23,191,11,128};CHECK(AppendD3D9ReplaySnapshot(stream,c));stream.complete=true;
    CHECK(ValidateModelReplay(stream).draws==2 && stream.resources[5].key.version==2);
    CHECK(stream.resources[2].texture.levels[0].pixels[0]==211);
    auto reject=[&](D3D9ReplaySnapshot bad,const char* why){auto before=stream.events.size();auto resources=stream.resources.size();auto r=AppendD3D9ReplaySnapshot(stream,bad);
        return !r && r.reason==why && stream.events.size()==before && stream.resources.size()==resources;};
    auto bad=c;bad.fvf=D3DFVF_XYZ|D3DFVF_DIFFUSE;CHECK(reject(bad,"unsupported_geometry_layout_or_base"));
    bad=c;bad.base=1;CHECK(reject(bad,"unsupported_geometry_layout_or_base"));
    bad=c;Set(bad,D3DRS_FOGENABLE,1);CHECK(reject(bad,"unsupported_render_state"));
    bad=c;bad.viewport.Width=65;CHECK(reject(bad,"invalid_viewport"));
    bad=c;bad.viewport.X=0xffffffffu;CHECK(reject(bad,"invalid_viewport"));
    bad=c;bad.viewport.Height=0;CHECK(reject(bad,"invalid_viewport"));
    bad=c;bad.viewport.MinZ=.9f;bad.viewport.MaxZ=.2f;CHECK(reject(bad,"invalid_viewport"));
    bad=c;bad.viewport.MaxZ=(std::numeric_limits<float>::quiet_NaN)();CHECK(reject(bad,"invalid_viewport"));
    bad=c;bad.textureInfo[0].autogen=true;CHECK(reject(bad,"autogen_mips_not_materialized"));
    bad=c;bad.textureInfo[0].present=false;CHECK(reject(bad,"unbound_texture_has_bytes"));
    bad=c;bad.textureInfo[0].format=D3DFMT_DXT1;CHECK(reject(bad,"unsupported_texture_format_mips_or_lod"));
    bad=c;bad.textureBytes[0].pop_back();CHECK(reject(bad,"truncated_texture_bytes"));
    bad=c;bad.renderStates.erase(bad.renderStates.begin()+D3DRS_LIGHTING-1);CHECK(reject(bad,"missing_or_invalid_native_state"));
    bad=c;D3D9ReplaySnapshot::Light light{};light.enabled=TRUE;light.value.Type=D3DLIGHT_POINT;bad.lights.push_back(light);CHECK(reject(bad,"unsupported_light"));
    bad=c;bad.indexBytes[4]=3;CHECK(reject(bad,"index_out_of_range"));
    bad=c;bad.minimum=1;bad.vertices=2;CHECK(reject(bad,"index_out_of_range"));
    {auto exhausted=stream;exhausted.resources.back().key.version=~std::uint64_t(0);
     CHECK(AppendD3D9ReplaySnapshot(exhausted,c).reason=="resource_version_overflow");}
#ifdef MIKUDANCESTUDIO_RHI_D3D11
    if(argc>1) {
        struct Window {HWND h;~Window(){if(h)DestroyWindow(h);}} window{CreateWindowExW(0,L"STATIC",L"Converted DX9 stream",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};
        CHECK(window.h);SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window.h)};desc.width=desc.height=64;
        if(argc==2 && (std::string(argv[1])=="--ground-warp" || std::string(argv[1])=="--ground-hardware"))
            return ground_replay_diagnostic::Run(window.h,std::string(argv[1])=="--ground-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp);
        if(argc==4 && std::string(argv[1])=="--sensitive-depth-hardware")
            return SensitiveDepthControls(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--perspective-case10")
            return PerspectiveCase10(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--perspective-w-perturb")
            return PerspectiveCase10(window.h,argv[2],argv[3],true);
        if(argc==4 && std::string(argv[1])=="--w-independent-geometry")
            return PerspectiveCase10(window.h,argv[2],argv[3],false,true);
        if(argc==4 && std::string(argv[1])=="--w-gpu-geometry")
            return PerspectiveCase10(window.h,argv[2],argv[3],false,true,true);
        if(argc==4 && (std::string(argv[1])=="--accessory-saved-warp" || std::string(argv[1])=="--accessory-saved-hardware"))
            return SavedAccessoryControls(window.h,std::string(argv[1])=="--accessory-saved-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp,argv[2],argv[3]);
        if(argc==4 && (std::string(argv[1])=="--accessory-native-warp" || std::string(argv[1])=="--accessory-native-hardware"))
            return SavedAccessoryControls(window.h,std::string(argv[1])=="--accessory-native-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp,argv[2],argv[3],true);
        if(argc==5 && std::string(argv[1])=="--accessory-w-gpu") {
            CHECK(std::strlen(argv[4])==1 && argv[4][0]>='1' && argv[4][0]<='5');
            return SavedAccessoryControls(window.h,D3D11Driver::Hardware,argv[2],argv[3],true,static_cast<unsigned>(argv[4][0]-'0'));
        }
        if(argc==5 && std::string(argv[1])=="--w-overlap-depth")
            return WOverlapDepthControls(window.h,argv[2],argv[3],argv[4]);
        if(argc==2 && std::string(argv[1])=="--shared-clip-smoke")
            return SharedClipDepthSmoke(window.h);
        if(argc==4 && std::string(argv[1])=="--z-explicit-geometry")
            return ZExplicitDepth(window.h,argv[2],argv[3]);
        if(argc==2 && std::string(argv[1])=="--z-explicit-smoke")
            return ZExplicitShaderSmoke();
        if(argc==5 && std::string(argv[1])=="--z-explicit-pmm")
            return ZExplicitDepth(window.h,argv[2],argv[4],argv[3]);
        if(argc==5 && std::string(argv[1])=="--accessory-color")
            return AccessoryColorControls(window.h,argv[2],argv[3],argv[4]);
        if(argc==2 && std::string(argv[1])=="--shared-color-smoke")
            return SharedColorSmoke(window.h);
        if(argc==4 && std::string(argv[1])=="--lighting-rounding")
            return lighting_rounding_diagnostic::Run(window.h,argv[2],argv[3]);
        if(argc==2 && std::string(argv[1])=="--lighting-order-smoke")
            return lighting_rounding_diagnostic::Smoke(window.h);
        if(argc==4 && std::string(argv[1])=="--lighting-matrix-axes")
            return lighting_rounding_diagnostic::MatrixAxes(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--normal-precision")
            return normal_precision_diagnostic::Run(window.h,argv[2],argv[3]);
        if(argc==3 && std::string(argv[1])=="--normal-precision-smoke")
            return normal_precision_diagnostic::Smoke(window.h,argv[2]);
        if(argc==3 && std::string(argv[1])=="--normal-transforms")
            return normal_transform_diagnostic::Run(window.h,argv[2]);
        if(argc==4 && std::string(argv[1])=="--accessory-lighting-gpu")
            return SavedAccessoryControls(window.h,D3D11Driver::Hardware,argv[2],argv[3],true,3,true);
        if(argc==4 && std::string(argv[1])=="--accessory-normal-gpu")
            return SavedAccessoryControls(window.h,D3D11Driver::Hardware,argv[2],argv[3],true,3,true,true);
        if(argc==4 && std::string(argv[1])=="--scene-prefix-normal")
            return scene_prefix_diagnostic::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--scene-prefix-viewport-center")
            return scene_prefix_diagnostic::Run(window.h,argv[2],argv[3],true);
        if(argc==5 && std::string(argv[1])=="--model-color-isolation")
            return model_color_isolation::Run(window.h,argv[2],argv[3],argv[4]);
        if(argc==4 && std::string(argv[1])=="--model-batch23-isolation")
            return model_batch_color::Run(window.h,argv[2],argv[3]);
        if(argc==6 && std::string(argv[1])=="--model-batch23-isolation")
            return model_batch_color::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])));
        if(argc==6 && std::string(argv[1])=="--model-batch23-isolation-texture")
            return model_batch_color::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),true);
        if(argc==4 && std::string(argv[1])=="--model-batch23-stages")
            return model_batch_color::Stages(window.h,argv[2],argv[3]);
        if(argc==6 && std::string(argv[1])=="--model-batch23-stages")
            return model_batch_color::Stages(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])));
        if(argc==7 && std::string(argv[1])=="--model-batch23-stages")
            return model_batch_color::Stages(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])));
        if(argc==7 && std::string(argv[1])=="--model-batch23-stages-texture")
            return model_batch_color::Stages(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])),true);
        if(argc==7 && std::string(argv[1])=="--model-batch23-causal")
            return model_batch_causal::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])));
        if(argc==7 && std::string(argv[1])=="--model-batch23-spec-causal")
            return model_batch_causal::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])),true,true);
        if(argc==7 && std::string(argv[1])=="--model-batch23-spec-origin")
            return model_specular_origin::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])));
        if(argc==5 && std::string(argv[1])=="--model-specular-stages")
            return model_specular_stages::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])));
        if(argc==3 && std::string(argv[1])=="--model-specular-scope")
            return model_specular_scope::Run(window.h,argv[2]);
        if(argc==7 && std::string(argv[1])=="--model-batch23-uv-origin")
            return model_batch_uv_origin::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])));
        if(argc==7 && std::string(argv[1])=="--model-batch23-toon-rounding")
            return model_toon_rounding::Run(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])),static_cast<unsigned>(std::stoul(argv[5])),static_cast<unsigned>(std::stoul(argv[6])));
        if(argc==3 && std::string(argv[1])=="--texture-fma-scope")
            return model_texture_fma_scope::Run(window.h,argv[2]);
        if(argc==3 && std::string(argv[1])=="--final-modulate-controls")
            return model_final_modulate::Run(window.h,argv[2]);
        if(argc==3 && std::string(argv[1])=="--final-modulate-smoke")
            return model_final_modulate::Run(window.h,argv[2],true);
        if(argc==5 && std::string(argv[1])=="--model-sampling")
            return model_sampling_diagnostic::Run(window.h,argv[2],argv[3],argv[4]);
        if(argc==5 && std::string(argv[1])=="--model-transform")
            return model_transform_diagnostic::Run(window.h,argv[2],argv[3],argv[4]);
        if(argc==3 && (std::string(argv[1])=="--xy-independent" || std::string(argv[1])=="--xy-independent-controls"))
            return independent_xy_diagnostic::Run(window.h,argv[2],std::string(argv[1])=="--xy-independent-controls");
        if(argc==4 && std::string(argv[1])=="--dx11-compatibility-lifecycle")
            return dx11_compatibility_test::Run(window.h,argv[2],argv[3]);
#ifdef MIKUDANCESTUDIO_RHI_D3D12
        if(argc==4 && std::string(argv[1])=="--resident-pmm")
            return resident_pmm_test::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--alpha-history-diagnostic")
            return alpha_history_diagnostic::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--specular-history-diagnostic")
            return alpha_history_diagnostic::Run(window.h,argv[2],argv[3],true,true);
        if(argc==4 && std::string(argv[1])=="--texture-history-diagnostic")
            return alpha_history_diagnostic::Run(window.h,argv[2],argv[3],true);
#endif
        if(argc==3 && std::string(argv[1])=="--dx11-compatibility-generated")
            return independent_xy_diagnostic::Run(window.h,argv[2],true,true);
        if(argc==4 && std::string(argv[1])=="--accessory-depth-thresholds")
            return accessory_depth_threshold::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-depth-controls")
            return accessory_depth_threshold::AlphaControls(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-sampling")
            return accessory_alpha_sampling::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-references")
            return accessory_alpha_sampling::References(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--alpha-conversion-independent")
            return alpha_conversion_independent::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-reference-fine")
            return accessory_alpha_sampling::References(window.h,argv[2],argv[3],true);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-references-reuse")
            return accessory_alpha_sampling::References(window.h,argv[2],argv[3],false,true);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-reference-fine-reuse")
            return accessory_alpha_sampling::References(window.h,argv[2],argv[3],true,true);
        if(argc==4 && std::string(argv[1])=="--accessory-alpha-history")
            return accessory_alpha_history::Run(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--scene-prefix-fused-xy")
            return scene_prefix_diagnostic::Run(window.h,argv[2],argv[3],true,true);
        if(argc==4 && std::string(argv[1])=="--ground-lines-isolation")
            return ground_history_isolation::Lines(window.h,argv[2],argv[3]);
        if(argc==5 && std::string(argv[1])=="--ground-history-isolation")
            return ground_history_isolation::History(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])));
        if(argc==5 && std::string(argv[1])=="--ground-depth-reduction")
            return ground_history_isolation::DepthReduction(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])));
        if(argc==4 && std::string(argv[1])=="--ground-endpoints")
            return ground_endpoint_depth::Endpoints(window.h,argv[2],argv[3]);
        if(argc==4 && std::string(argv[1])=="--ground-depth-thresholds")
            return ground_endpoint_depth::Depth(window.h,argv[2],argv[3]);
        if(argc==5 && std::string(argv[1])=="--ground-explicit-lines")
            return ground_explicit_clip::Lines(window.h,argv[2],argv[3],argv[4]);
        if(argc==5 && std::string(argv[1])=="--ground-explicit-depth")
            return ground_explicit_clip::Depth(window.h,argv[2],argv[3],argv[4]);
        if(argc==6 && std::string(argv[1])=="--ground-clip-rounding-lines")
            return ground_explicit_clip::Lines(window.h,argv[2],argv[3],argv[5],argv[4]);
        if(argc==6 && std::string(argv[1])=="--ground-clip-rounding-depth")
            return ground_explicit_clip::Depth(window.h,argv[2],argv[3],argv[5],argv[4]);
        if(argc==6 && std::string(argv[1])=="--ground-center-stage-lines")
            return ground_explicit_clip::Lines(window.h,argv[2],argv[3],argv[5],nullptr,argv[4]);
        if(argc==6 && std::string(argv[1])=="--ground-center-stage-depth")
            return ground_explicit_clip::Depth(window.h,argv[2],argv[3],argv[5],nullptr,argv[4]);
        if(argc==5 && std::string(argv[1])=="--ground-process-vertices")
            return ground_endpoint_depth::ProcessChild(window.h,argv[2],argv[3],std::string(argv[4])=="software");
        if(argc==5 && std::string(argv[1])=="--scene-prefix-first-controls")
            return scene_prefix_diagnostic::FirstDrawControls(window.h,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])));
        if(argc==4 && (std::string(argv[1])=="--coplanar-depth-warp" || std::string(argv[1])=="--coplanar-depth-hardware"))
            return CoplanarDepthControls(window.h,std::string(argv[1])=="--coplanar-depth-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp,argv[2],argv[3]);
        if(argc==5 && std::string(argv[1])=="--transform-depth-hardware")
            return CoplanarDepthControls(window.h,D3D11Driver::Hardware,argv[2],argv[3],static_cast<unsigned>(std::stoul(argv[4])));
        if(std::string(argv[1])=="--shadow-adapter-warp" || std::string(argv[1])=="--shadow-adapter-hardware")
            return ShadowAdapterControls(window.h,std::string(argv[1])=="--shadow-adapter-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp);
        if(argc==3 && (std::string(argv[1])=="--shadow-archive-warp" || std::string(argv[1])=="--shadow-archive-hardware"))
            return CapturedShadowControls(window.h,std::string(argv[1])=="--shadow-archive-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp,argv[2]);
        if(std::string(argv[1])=="--shadow-warp" || std::string(argv[1])=="--shadow-hardware")
            return ConvertedShadowControls(window.h,std::string(argv[1])=="--shadow-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp);
        if(std::string(argv[1])=="--mips-warp" || std::string(argv[1])=="--mips-hardware")
            return ConvertedMipControls(window.h,std::string(argv[1])=="--mips-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp);
        if(std::string(argv[1])=="--null-warp" || std::string(argv[1])=="--null-hardware")
            return ConvertedNullTextureControls(window.h,std::string(argv[1])=="--null-hardware"?D3D11Driver::Hardware:D3D11Driver::Warp);
        const auto driver=std::string(argv[1])=="--hardware"?D3D11Driver::Hardware:D3D11Driver::Warp;
        unsigned comparisons=0;
        for(unsigned scenario=0;scenario<5;++scenario) {
            std::vector<D3D9ReplaySnapshot> snapshots{Fixture(),Fixture()};snapshots[1].textureBytes[0]={23,191,11,128};
            if(scenario)for(auto& snapshot:snapshots)snapshot.viewport={8,6,40,48,.125f,.875f};
            if(scenario==2)snapshots[1].viewport={8,6,40,48,.625f,.875f}; // .75 loses to .5
            if(scenario==3)snapshots[1].viewport={22,14,32,32,0,.5f}; // changes offset/size and wins overlap
            if(scenario==4)snapshots[1].viewport={0,0,64,64,.5f,.5f}; // equal range, return to full target
            ModelReplayStream converted;converted.target.width=converted.target.height=64;converted.events.push_back({1,ModelReplayOp::Clear});
            for(const auto& snapshot:snapshots)CHECK(AppendD3D9ReplaySnapshot(converted,snapshot));converted.complete=true;
            std::array<RgbaImage,2> native;CHECK(NativeImage(window.h,snapshots,1,native[0]) && NativeImage(window.h,snapshots,2,native[1]));
            for(unsigned replacement=0;replacement<2;++replacement) {
                auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);
                for(unsigned prefix:{1u,2u,1u}) {
                    RgbaImage image;const auto replay=ReplayD3D11ModelPrefix(*bundle.device,converted,prefix,image);CHECK(replay);
                    if(scenario==0) {
                        const auto pixel=(40*64+16)*4;const std::vector<unsigned char> expected=prefix==1?std::vector<unsigned char>{211,13,7,255}:std::vector<unsigned char>{11,191,23,128};
                        CHECK(std::memcmp(image.pixels.data()+pixel,expected.data(),4)==0);
                    }
                    if(scenario==2 && prefix==2)CHECK(image.pixels==native[0].pixels);
                    CHECK(image.pixels[0]==0 && image.pixels[3]==255);
                    unsigned differences=0;for(std::size_t i=0;i<image.pixels.size();i+=4)if(std::memcmp(image.pixels.data()+i,native[prefix-1].pixels.data()+i,4))++differences;
                    if(differences)std::fprintf(stderr,"viewport scenario=%u prefix=%u differences=%u\n",scenario,prefix,differences);
                    CHECK(!differences);++comparisons;
                }
                CHECK(bundle.swapchain->Retire());
            }
        }
        std::printf("driver=%s nativeDX9Comparisons=%u differingPixels=0 viewportScenarios=5 deviceReplacement=PASS\n",argv[1],comparisons);
    }
#endif
    std::puts("DX9 owned snapshot conversion passed");return 0;
}
