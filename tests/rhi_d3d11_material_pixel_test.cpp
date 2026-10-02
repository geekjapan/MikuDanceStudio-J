#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi_material_textures.hpp"
#include <array>
#include <algorithm>
#include <cmath>
#include <vector>
#include <fstream>
#include <filesystem>
#include <cstdio>
#include <cstring>
using Microsoft::WRL::ComPtr;
using namespace mikudancestudio::rhi;
constexpr unsigned Size=32;
struct Vertex9 {float x,y,z,w;DWORD color;float u,v;};
struct Vertex11 {float x,y;};
struct Constants {std::array<std::array<unsigned,4>,3> stages{};std::array<unsigned,4> alpha{};};
int main(int argc,char** argv) {
    const bool hardware=argc>=2 && std::strcmp(argv[1],"--hardware")==0;
    if(hardware){--argc;++argv;}
    const bool precision=argc>=2 && std::strcmp(argv[1],"--precision")==0;
    const bool measureLinear=argc>=2 && std::strcmp(argv[1],"--linear")==0;
    const char* pattern=precision && argc>=3?argv[2]:nullptr;
    const char* evidence=precision?(argc==4?argv[3]:nullptr):measureLinear?(argc==3?argv[2]:nullptr):(argc==2?argv[1]:nullptr);
    if(precision) {
        if(argc<3 || argc>4 || (std::strcmp(pattern,"constant") && std::strcmp(pattern,"translucent") && std::strcmp(pattern,"gradient")))return 1;
    } else if(argc>3 || (argc==3 && !measureLinear))return 1;
    ComPtr<ID3D11Device> d11;ComPtr<ID3D11DeviceContext> c11;D3D_FEATURE_LEVEL level;
    if(FAILED(D3D11CreateDevice(nullptr,hardware?D3D_DRIVER_TYPE_HARDWARE:D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&d11,&level,&c11)) || level<D3D_FEATURE_LEVEL_11_0)return 77;
    HWND window=CreateWindowW(L"STATIC",L"offscreen material probe",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    struct Window {HWND h;~Window(){if(h)DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));ComPtr<IDirect3DDevice9> d9;
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferFormat=D3DFMT_A8R8G8B8;
    pp.BackBufferWidth=pp.BackBufferHeight=Size;pp.hDeviceWindow=window;
    if(!window || !api || FAILED(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_SOFTWARE_VERTEXPROCESSING,&pp,&d9)))return 77;
    D3DADAPTER_IDENTIFIER9 identifier{};
    if(FAILED(api->GetAdapterIdentifier(0,0,&identifier)))return 1;
    ComPtr<IDXGIDevice> dxgiDevice;ComPtr<IDXGIAdapter> adapter;DXGI_ADAPTER_DESC adapterDesc{};
    if(FAILED(d11.As(&dxgiDevice)) || FAILED(dxgiDevice->GetAdapter(&adapter)) ||
       FAILED(adapter->GetDesc(&adapterDesc)))return 1;
    // A hardware comparison must use the same adapter, not a second GPU.
    if(hardware && (adapterDesc.VendorId!=identifier.VendorId || adapterDesc.DeviceId!=identifier.DeviceId))return 77;
    std::printf("DX9 adapter=%s; DX11 driver=%s; pattern=%s\n",identifier.Description,hardware?"hardware":"WARP",precision?pattern:"baseline");
    std::printf("Adapter IDs: DX9=%04x:%04x DX11=%04x:%04x\n",identifier.VendorId,identifier.DeviceId,adapterDesc.VendorId,adapterDesc.DeviceId);
    ComPtr<IDirect3DSurface9> target9,read9;
    if(FAILED(d9->CreateRenderTarget(Size,Size,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&target9,nullptr)) ||
       FAILED(d9->CreateOffscreenPlainSurface(Size,Size,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&read9,nullptr)) || FAILED(d9->SetRenderTarget(0,target9.Get())))return 1;
    D3D11_TEXTURE2D_DESC td{};td.Width=td.Height=Size;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
    td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> target11,read11;ComPtr<ID3D11RenderTargetView> rtv;
    if(FAILED(d11->CreateTexture2D(&td,nullptr,&target11)) || FAILED(d11->CreateRenderTargetView(target11.Get(),nullptr,&rtv)))return 1;
    td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    if(FAILED(d11->CreateTexture2D(&td,nullptr,&read11)))return 1;
    const char* vertexCode=R"(
    struct O {float4 position:SV_POSITION;float4 color:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 c:TEXCOORD2;};
    O main(float2 p:POSITION) {O o;o.position=float4(p,0,1);o.color=1;o.a=o.b=o.c=float2((p.x+1)*.5,(1-p.y)*.5);return o;})";
    ComPtr<ID3DBlob> vbCode,pbCode,errors;
    if(FAILED(D3DCompile(vertexCode,std::strlen(vertexCode),nullptr,nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vbCode,&errors)))return 1;
    const std::filesystem::path shader=std::filesystem::path(MDS_SHADER_DIR)/"model_material_pixel.hlsl";
    if(FAILED(D3DCompileFromFile(shader.c_str(),nullptr,nullptr,"main","ps_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&pbCode,&errors))) {
        if(errors)std::fwrite(errors->GetBufferPointer(),1,errors->GetBufferSize(),stderr);return 1;}
    ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11PixelShader> ps;ComPtr<ID3D11InputLayout> il;
    D3D11_INPUT_ELEMENT_DESC element{"POSITION",0,DXGI_FORMAT_R32G32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0};
    if(FAILED(d11->CreateVertexShader(vbCode->GetBufferPointer(),vbCode->GetBufferSize(),nullptr,&vs)) ||
       FAILED(d11->CreatePixelShader(pbCode->GetBufferPointer(),pbCode->GetBufferSize(),nullptr,&ps)) ||
       FAILED(d11->CreateInputLayout(&element,1,vbCode->GetBufferPointer(),vbCode->GetBufferSize(),&il)))return 1;
    const Vertex11 quad11[]={{-1,1},{1,1},{-1,-1},{1,-1}};
    const Vertex9 quad9[]={{-.5f,-.5f,0,1,0xffffffff,0,0},{Size-.5f,-.5f,0,1,0xffffffff,1,0},
        {-.5f,Size-.5f,0,1,0xffffffff,0,1},{Size-.5f,Size-.5f,0,1,0xffffffff,1,1}};
    ComPtr<ID3D11Buffer> vertices,constants;D3D11_BUFFER_DESC bd{};bd.ByteWidth=sizeof(quad11);bd.BindFlags=D3D11_BIND_VERTEX_BUFFER;
    D3D11_SUBRESOURCE_DATA init{};init.pSysMem=quad11;
    if(FAILED(d11->CreateBuffer(&bd,&init,&vertices)))return 1;
    bd.ByteWidth=sizeof(Constants);bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    if(FAILED(d11->CreateBuffer(&bd,nullptr,&constants)))return 1;
    D3D11_RASTERIZER_DESC rd{};rd.FillMode=D3D11_FILL_SOLID;rd.CullMode=D3D11_CULL_NONE;rd.DepthClipEnable=TRUE;
    ComPtr<ID3D11RasterizerState> raster;if(FAILED(d11->CreateRasterizerState(&rd,&raster)))return 1;
    D3D11_DEPTH_STENCIL_DESC depth{};depth.DepthEnable=FALSE;ComPtr<ID3D11DepthStencilState> depthState;
    if(FAILED(d11->CreateDepthStencilState(&depth,&depthState)))return 1;
    std::array<std::array<std::uint8_t,16>,3> pixels{{
        {{255,255,255,0,255,0,0,64,0,255,0,128,0,0,255,255}},
        {{255,255,255,255,0,255,255,255,255,0,255,255,255,255,0,255}},
        {{0,0,0,255,255,255,255,255,255,0,0,255,0,255,0,255}}}};
    if(precision)for(auto& texture:pixels)for(unsigned t=0;t<4;++t) {
        if(!std::strcmp(pattern,"gradient")) {
            const unsigned char values[4][4]={{31,73,127,255},{97,143,211,255},{193,59,101,255},{239,181,17,255}};
            std::copy(values[t],values[t]+4,texture.begin()+t*4);
        } else {
            texture[t*4]=97;texture[t*4+1]=143;texture[t*4+2]=211;
            texture[t*4+3]=!std::strcmp(pattern,"translucent")?128:255;
        }
    }
    std::array<ComPtr<IDirect3DTexture9>,3> texture9;
    std::array<ComPtr<ID3D11Texture2D>,3> texture11;std::array<ComPtr<ID3D11ShaderResourceView>,3> srv;
    for(unsigned s=0;s<3;++s) {
        if(FAILED(d9->CreateTexture(2,2,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&texture9[s],nullptr)))return 1;
        D3DLOCKED_RECT lock{};if(FAILED(texture9[s]->LockRect(0,&lock,nullptr,0)))return 1;
        for(unsigned y=0;y<2;++y)for(unsigned x=0;x<2;++x){auto* dst=static_cast<unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;
            const auto* src=pixels[s].data()+(y*2+x)*4;dst[0]=src[2];dst[1]=src[1];dst[2]=src[0];dst[3]=src[3];}
        if(FAILED(texture9[s]->UnlockRect(0)))return 1;
        td={};td.Width=td.Height=2;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        init={};init.pSysMem=pixels[s].data();init.SysMemPitch=8;
        if(FAILED(d11->CreateTexture2D(&td,&init,&texture11[s])) || FAILED(d11->CreateShaderResourceView(texture11[s].Get(),nullptr,&srv[s])))return 1;
    }
    struct Case {const char* name;const wchar_t* base;const wchar_t* sphere;unsigned mode;};
    const Case cases[]={{"toon",L"",L"",0},{"base",L"base.bmp",L"",0},
        {"sphere_multiply",L"",L"sphere.sph",1},{"sphere_add",L"",L"sphere.spa",2},
        {"base_sphere_multiply",L"base.bmp",L"sphere.sph",1},{"base_sphere_add",L"base.bmp",L"sphere.spa",2}};
    bool exact=true;
    for(const auto& item:cases) {
        MaterialTextureLayout layout;if(!BuildMaterialTextureLayout(false,item.base,item.sphere,item.mode,layout))return 1;
        for(unsigned test=0;test<(measureLinear || precision?2u:1u);++test) {
            const bool linear=test==1;
          for(unsigned variant=0;variant<3;++variant) {
            const bool alphaDiscard=variant==1,blend=variant==2;
            D3D11_SAMPLER_DESC sd{};sd.Filter=linear?D3D11_FILTER_MIN_MAG_MIP_LINEAR:D3D11_FILTER_MIN_MAG_MIP_POINT;
            sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;
            ComPtr<ID3D11SamplerState> sampler;if(FAILED(d11->CreateSamplerState(&sd,&sampler)))return 1;
            Constants cb;cb.alpha={alphaDiscard?1u:0u,6u,128u,0};std::array<ID3D11ShaderResourceView*,3> views{};std::array<ID3D11SamplerState*,3> samplers{};
            auto set9=[&](D3DRENDERSTATETYPE key,DWORD v){return SUCCEEDED(d9->SetRenderState(key,v));};
            if(!set9(D3DRS_ZENABLE,FALSE)||!set9(D3DRS_ZWRITEENABLE,FALSE)||!set9(D3DRS_LIGHTING,FALSE)||
               !set9(D3DRS_ALPHABLENDENABLE,blend)||!set9(D3DRS_ALPHATESTENABLE,alphaDiscard)||
               !set9(D3DRS_ALPHAFUNC,D3DCMP_GREATEREQUAL)||!set9(D3DRS_ALPHAREF,128)||
               !set9(D3DRS_SRCBLEND,D3DBLEND_SRCALPHA)||!set9(D3DRS_DESTBLEND,D3DBLEND_INVSRCALPHA)||
               !set9(D3DRS_BLENDOP,D3DBLENDOP_ADD)||!set9(D3DRS_SEPARATEALPHABLENDENABLE,FALSE)||!set9(D3DRS_CULLMODE,D3DCULL_NONE)||
               !set9(D3DRS_FOGENABLE,FALSE)||!set9(D3DRS_SRGBWRITEENABLE,FALSE))return 1;
            for(unsigned s=0;s<3;++s) {
                const auto& st=layout.stages[s];const bool enabled=st.role!=MaterialTextureRole::None;
                const unsigned resource=st.role==MaterialTextureRole::Toon?0:st.role==MaterialTextureRole::Base?1:2;
                cb.stages[s]={enabled?1u:0u,static_cast<unsigned>(st.color),0,0};views[s]=enabled?srv[resource].Get():nullptr;samplers[s]=sampler.Get();
                if(FAILED(d9->SetTexture(s,enabled?texture9[resource].Get():nullptr)))return 1;
                for(auto pair:{std::pair<D3DTEXTURESTAGESTATETYPE,DWORD>{D3DTSS_COLOROP,enabled?(st.color==MaterialCombine::Add?D3DTOP_ADD:D3DTOP_MODULATE):D3DTOP_DISABLE},
                    {D3DTSS_COLORARG1,D3DTA_TEXTURE},{D3DTSS_COLORARG2,s==0?D3DTA_DIFFUSE:D3DTA_CURRENT},
                    {D3DTSS_ALPHAOP,D3DTOP_MODULATE},{D3DTSS_ALPHAARG1,D3DTA_TEXTURE},{D3DTSS_ALPHAARG2,s==0?D3DTA_DIFFUSE:D3DTA_CURRENT},
                    {D3DTSS_TEXCOORDINDEX,0},{D3DTSS_TEXTURETRANSFORMFLAGS,0}})
                    if(FAILED(d9->SetTextureStageState(s,pair.first,pair.second)))return 1;
                for(auto pair:{std::pair<D3DSAMPLERSTATETYPE,DWORD>{D3DSAMP_MINFILTER,linear?D3DTEXF_LINEAR:D3DTEXF_POINT},
                    {D3DSAMP_MAGFILTER,linear?D3DTEXF_LINEAR:D3DTEXF_POINT},{D3DSAMP_MIPFILTER,D3DTEXF_NONE},
                    {D3DSAMP_ADDRESSU,D3DTADDRESS_CLAMP},{D3DSAMP_ADDRESSV,D3DTADDRESS_CLAMP},{D3DSAMP_SRGBTEXTURE,0}})
                    if(FAILED(d9->SetSamplerState(s,pair.first,pair.second)))return 1;
            }
            if(FAILED(d9->SetTextureStageState(3,D3DTSS_COLOROP,D3DTOP_DISABLE))||FAILED(d9->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE|D3DFVF_TEX1)) ||
               FAILED(d9->Clear(0,nullptr,D3DCLEAR_TARGET,0,1,0))||FAILED(d9->BeginScene()))return 1;
            const auto drawn=d9->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,quad9,sizeof(Vertex9));const auto ended=d9->EndScene();
            if(FAILED(drawn)||FAILED(ended)||FAILED(d9->GetRenderTargetData(target9.Get(),read9.Get())))return 1;
            auto* target=rtv.Get();c11->OMSetRenderTargets(1,&target,nullptr);c11->OMSetDepthStencilState(depthState.Get(),0);
            D3D11_BLEND_DESC blendDesc{};auto& rt=blendDesc.RenderTarget[0];rt.BlendEnable=blend;
            rt.SrcBlend=rt.SrcBlendAlpha=D3D11_BLEND_SRC_ALPHA;rt.DestBlend=rt.DestBlendAlpha=D3D11_BLEND_INV_SRC_ALPHA;
            rt.BlendOp=rt.BlendOpAlpha=D3D11_BLEND_OP_ADD;rt.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
            ComPtr<ID3D11BlendState> blendState;if(FAILED(d11->CreateBlendState(&blendDesc,&blendState)))return 1;
            c11->OMSetBlendState(blendState.Get(),nullptr,0xffffffff);c11->RSSetState(raster.Get());
            D3D11_VIEWPORT vp{0,0,Size,Size,0,1};c11->RSSetViewports(1,&vp);
            UINT stride=sizeof(Vertex11),offset=0;auto* vb=vertices.Get();auto* constant=constants.Get();
            c11->UpdateSubresource(constant,0,nullptr,&cb,0,0);c11->IASetVertexBuffers(0,1,&vb,&stride,&offset);
            c11->IASetInputLayout(il.Get());c11->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
            c11->VSSetShader(vs.Get(),nullptr,0);c11->PSSetShader(ps.Get(),nullptr,0);
            c11->PSSetConstantBuffers(0,1,&constant);c11->PSSetShaderResources(0,3,views.data());c11->PSSetSamplers(0,3,samplers.data());
            const float clear[4]={};c11->ClearRenderTargetView(rtv.Get(),clear);c11->Draw(4,0);c11->CopyResource(read11.Get(),target11.Get());
            D3D11_MAPPED_SUBRESOURCE map{};D3DLOCKED_RECT lock{};
            if(FAILED(c11->Map(read11.Get(),0,D3D11_MAP_READ,0,&map))||FAILED(read9->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;
            unsigned channels=0,differentPixels=0,maximum=0;std::vector<unsigned char> a(Size*Size*4),b(a.size());
            for(unsigned y=0;y<Size;++y)for(unsigned x=0;x<Size;++x) {
                const auto* dx9=static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;
                const auto* dx11=static_cast<const unsigned char*>(map.pData)+y*map.RowPitch+x*4;
                const unsigned order[]={2,1,0,3};bool different=false;
                for(unsigned c=0;c<4;++c){const auto i=(y*Size+x)*4+c;a[i]=dx9[order[c]];b[i]=dx11[c];
                    if(a[i]!=b[i]){++channels;different=true;maximum=std::max(maximum,static_cast<unsigned>(std::abs(int(a[i])-int(b[i]))));}}
                differentPixels+=different;
            }
            read9->UnlockRect();c11->Unmap(read11.Get(),0);
            // Independently check point sampling against the portable cascade.
            // This also rejects an accidentally blank target on both backends.
            if(!linear && !precision)for(unsigned y=0;y<Size;++y)for(unsigned x=0;x<Size;++x) {
                const unsigned texel=(y>=Size/2?2:0)+(x>=Size/2?1:0);
                std::array<std::array<float,4>,3> sampled{};
                for(unsigned s=0;s<3;++s) {
                    const auto role=layout.stages[s].role;
                    const unsigned resource=role==MaterialTextureRole::Toon?0:role==MaterialTextureRole::Base?1:2;
                    for(unsigned c=0;c<4;++c)sampled[s][c]=pixels[resource][texel*4+c]/255.f;
                }
                std::array<float,4> expected;
                if(!EvaluateMaterialTextureCascade(layout,{1,1,1,1},sampled,expected))return 1;
                if(!MaterialAlphaTest(expected[3],alphaDiscard,DepthComparison::GreaterEqual,128))expected={};
                else if(blend) {const float alpha=expected[3];for(float& value:expected)value*=alpha;}
                for(unsigned c=0;c<4;++c) {
                    const auto value=static_cast<unsigned>(std::floor(expected[c]*255.f+.5f));
                    const auto i=(y*Size+x)*4+c;
                    if(a[i]!=value || b[i]!=value) {
                        std::fprintf(stderr,"Point oracle mismatch: %s variant=%u x=%u y=%u channel=%u expected=%u dx9=%u dx11=%u\n",item.name,variant,x,y,c,value,a[i],b[i]);return 1;
                    }
                }
            }
            exact=exact&&!channels;
            char report[256];std::snprintf(report,sizeof(report),"case=%s filter=%s variant=%s status=%s pixels=%u differingPixels=%u differingChannels=%u maxError=%u\n",
                item.name,linear?"linear":"point",alphaDiscard?"alpha-test":blend?"blend":"unblended",channels?"BLOCKED":"PASS",Size*Size,differentPixels,channels,maximum);std::fputs(report,stdout);
            if(evidence){const auto root=std::filesystem::u8path(evidence);std::filesystem::create_directories(root);
                const std::string stem=(precision?std::string(pattern)+"-":"")+item.name+(linear?"-linear":"-point")+(alphaDiscard?"-alpha-test":blend?"-blend":"-unblended");
                std::ofstream reportFile(root/(stem+".report"));reportFile<<report;if(!reportFile)return 1;
                std::ofstream f9(root/(stem+"-dx9.rgba"),std::ios::binary),f11(root/(stem+"-dx11.rgba"),std::ios::binary);
                f9.write(reinterpret_cast<const char*>(a.data()),a.size());f11.write(reinterpret_cast<const char*>(b.data()),b.size());if(!f9 || !f11)return 1;}
          }
        }
    }
    return exact?0:2;
}
