#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi.hpp"
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <cstring>
#include <vector>
using Microsoft::WRL::ComPtr;
int CreationMatrix(const std::filesystem::path& root){
    std::filesystem::create_directories(root);std::ofstream log(root/"device_creation.matrix",std::ios::trunc);
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DADAPTER_IDENTIFIER9 id{};api->GetAdapterIdentifier(0,0,&id);
    log<<"ADAPTER vendor="<<id.VendorId<<" device="<<id.DeviceId<<" description="<<id.Description<<"\n";
    unsigned failures=0,total=0;
    for(unsigned repeat=0;repeat<3;++repeat)for(unsigned variant=0;variant<10;++variant){
        HWND hwnd=CreateWindowW(L"STATIC",L"DX9 application parameter reproduction",WS_OVERLAPPEDWINDOW,0,0,1920,1050,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
        if(!hwnd)return 1;
        const bool visible=variant==7;if(visible){ShowWindow(hwnd,SW_SHOWNOACTIVATE);UpdateWindow(hwnd);}
        D3DPRESENT_PARAMETERS requested{};requested.Windowed=TRUE;requested.hDeviceWindow=hwnd;
        requested.BackBufferWidth=variant==0?64:GetSystemMetrics(SM_CXSCREEN);
        requested.BackBufferHeight=variant==0?64:GetSystemMetrics(SM_CYSCREEN);
        requested.BackBufferFormat=variant==8?D3DFMT_X8R8G8B8:D3DFMT_A8R8G8B8;
        requested.BackBufferCount=1;requested.SwapEffect=variant==9?D3DSWAPEFFECT_COPY:D3DSWAPEFFECT_DISCARD;
        requested.EnableAutoDepthStencil=variant>=2;requested.AutoDepthStencilFormat=variant==5?D3DFMT_D24X8:variant==6?D3DFMT_D16:D3DFMT_D24S8;
        requested.MultiSampleType=(variant>=3&&variant!=9)?D3DMULTISAMPLE_8_SAMPLES:D3DMULTISAMPLE_NONE;
        requested.PresentationInterval=variant>=4?D3DPRESENT_INTERVAL_IMMEDIATE:D3DPRESENT_INTERVAL_DEFAULT;
        requested.Flags=variant==9?D3DPRESENTFLAG_LOCKABLE_BACKBUFFER:0;
        DWORD colorQuality=0,depthQuality=0;
        const HRESULT colorSupport=api->CheckDeviceMultiSampleType(0,D3DDEVTYPE_HAL,requested.BackBufferFormat,TRUE,requested.MultiSampleType,&colorQuality);
        const HRESULT depthSupport=api->CheckDeviceMultiSampleType(0,D3DDEVTYPE_HAL,requested.AutoDepthStencilFormat,TRUE,requested.MultiSampleType,&depthQuality);
        auto actual=requested;ComPtr<IDirect3DDevice9> device;
        const HRESULT hr=api->CreateDevice(0,D3DDEVTYPE_HAL,hwnd,D3DCREATE_HARDWARE_VERTEXPROCESSING,&actual,&device);
        char row[900];std::snprintf(row,sizeof(row),"CREATE repeat=%u variant=%u visible=%d width=%u height=%u format=%u count=%u swap=%u autoDepth=%d depth=%u samples=%u quality=%u flags=%u interval=%u colorSupport=%08lx colorQuality=%lu depthSupport=%08lx depthQuality=%lu hr=%08lx\n",repeat+1,variant,visible,requested.BackBufferWidth,requested.BackBufferHeight,requested.BackBufferFormat,requested.BackBufferCount,requested.SwapEffect,requested.EnableAutoDepthStencil,requested.AutoDepthStencilFormat,requested.MultiSampleType,requested.MultiSampleQuality,requested.Flags,requested.PresentationInterval,(unsigned long)colorSupport,colorQuality,(unsigned long)depthSupport,depthQuality,(unsigned long)hr);
        log<<row;std::fputs(row,stdout);++total;if(FAILED(hr))++failures;
        device.Reset();DestroyWindow(hwnd);
    }
    log<<"SUMMARY attempts="<<total<<" failures="<<failures<<"\n";
    return failures?2:0;
}
int CoverageProbe(const std::filesystem::path& root){
    std::filesystem::create_directories(root);std::ofstream log(root/"sample_coverage.log");
    HWND hwnd=CreateWindowW(L"STATIC",L"MSAA coverage",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!hwnd)return 77;
    struct Cleanup {HWND h;~Cleanup(){DestroyWindow(h);}} cleanup{hwnd};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=hwnd;pp.BackBufferWidth=pp.BackBufferHeight=64;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.MultiSampleType=D3DMULTISAMPLE_8_SAMPLES;
    ComPtr<IDirect3DDevice9> d;if(FAILED(api->CreateDevice(0,D3DDEVTYPE_HAL,hwnd,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d)))return 77;
    ComPtr<IDirect3DSurface9> back,target,resolved,system;d->GetRenderTarget(0,&back);
    if(FAILED(d->CreateRenderTarget(64,64,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_8_SAMPLES,0,FALSE,&target,nullptr))||FAILED(d->CreateRenderTarget(64,64,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&resolved,nullptr))||FAILED(d->CreateOffscreenPlainSurface(64,64,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
    struct Vertex{float x,y,z,w;DWORD color;};
    D3DADAPTER_IDENTIFIER9 adapter{};api->GetAdapterIdentifier(0,0,&adapter);
    log<<"ADAPTER vendor="<<adapter.VendorId<<" device="<<adapter.DeviceId<<" description="<<adapter.Description<<" samples=8 quality=0 edgeStart=30.5 edgeStep=0.0625 pixel=31,31\n";
    unsigned failures=0;
    for(unsigned attachment=0;attachment<2;++attachment){
        if(FAILED(d->SetRenderTarget(0,attachment?target.Get():back.Get()))||FAILED(d->SetDepthStencilSurface(nullptr)))return 1;
        for(auto state:{D3DRS_ZENABLE,D3DRS_LIGHTING,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_STENCILENABLE})d->SetRenderState(state,FALSE);
        d->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE);d->SetRenderState(D3DRS_MULTISAMPLEANTIALIAS,TRUE);d->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE);
        d->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1);d->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_DIFFUSE);d->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1);d->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_DIFFUSE);d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE);
        for(unsigned sample=0;sample<8;++sample)for(unsigned axis=0;axis<2;++axis){
            std::vector<unsigned> baseline;
            for(unsigned repeat=0;repeat<3;++repeat){
                std::vector<unsigned> coverage;
                for(unsigned step=0;step<=16;++step){
                    float edge=30.5f+step/16.0f;
                    Vertex vertices[6]={{-.5f,-.5f,0,1,0xffffffff},{axis?63.5f:edge,-.5f,0,1,0xffffffff},{-.5f,axis?edge:63.5f,0,1,0xffffffff},{axis?63.5f:edge,-.5f,0,1,0xffffffff},{axis?63.5f:edge,axis?edge:63.5f,0,1,0xffffffff},{-.5f,axis?edge:63.5f,0,1,0xffffffff}};
                    if(FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET,0xff000000,1,0))||FAILED(d->BeginScene()))return 1;
                    d->SetRenderState(D3DRS_MULTISAMPLEMASK,1u<<sample);
                    HRESULT draw=d->DrawPrimitiveUP(D3DPT_TRIANGLELIST,2,vertices,sizeof(Vertex));HRESULT end=d->EndScene();
                    if(FAILED(draw)||FAILED(end)||FAILED(d->StretchRect(attachment?target.Get():back.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return 1;
                    D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;
                    const auto* pixel=static_cast<const unsigned char*>(lock.pBits)+31*lock.Pitch+31*4;coverage.push_back(pixel[0]);system->UnlockRect();
                }
                unsigned differences=0;
                if(repeat){for(unsigned j=0;j<coverage.size();++j)if(coverage[j]!=baseline[j])++differences;}
                else baseline=coverage;
                log<<"COVERAGE target="<<(attachment?"offscreen":"backbuffer")<<" sample="<<sample<<" axis="<<axis<<" repeat="<<repeat<<" differentSteps="<<differences<<" values=";for(auto value:coverage)log<<value<<",";log<<"\n";
                failures+=differences;
            }
        }
    }
    log<<"SUMMARY differentSteps="<<failures<<" positionInference=coverage_threshold_only samples=8 quality=0\n";
    return failures?2:0;
}
#include "msaa_attachment_history.hpp"
#include "fixed_lighting_reproduction.hpp"
#include "prelit_interpolation_probe.hpp"
#include "edge_quantization_probe.hpp"
#include "float_interpolation_probe.hpp"
int main(int argc,char** argv) {
    if(argc==3&&std::strcmp(argv[2],"--geometry-targeted")==0)return FloatInterpolationProbe(std::filesystem::u8path(argv[1]),true,false,true,true);
    if(argc==3&&std::strcmp(argv[2],"--geometry-planes")==0)return FloatInterpolationProbe(std::filesystem::u8path(argv[1]),true,false,true);
    if(argc==3&&std::strcmp(argv[2],"--triangle-orders")==0)return FloatInterpolationProbe(std::filesystem::u8path(argv[1]),true,true);
    if(argc==3&&std::strcmp(argv[2],"--float-sweep")==0)return FloatInterpolationProbe(std::filesystem::u8path(argv[1]),true);
    if(argc==3&&std::strcmp(argv[2],"--float-interpolation")==0)return FloatInterpolationProbe(std::filesystem::u8path(argv[1]));
    if(argc==3&&std::strcmp(argv[2],"--edge-quantization")==0)return EdgeQuantizationProbe(std::filesystem::u8path(argv[1]));
    if(argc==3&&std::strcmp(argv[2],"--prelit-interpolation")==0)return PrelitInterpolationProbe(std::filesystem::u8path(argv[1]));
    if(argc==3&&std::strcmp(argv[2],"--lighting-triangle")==0)return FixedLightingReproduction(std::filesystem::u8path(argv[1]),1);
    if(argc==3&&std::strcmp(argv[2],"--lighting-pair")==0)return FixedLightingReproduction(std::filesystem::u8path(argv[1]),2);
    if(argc==3&&std::strcmp(argv[2],"--fixed-lighting")==0)return FixedLightingReproduction(std::filesystem::u8path(argv[1]));
    if(argc==3&&std::strcmp(argv[2],"--attachment-history")==0)return AttachmentHistoryProbe(std::filesystem::u8path(argv[1]));
    if(argc==3&&std::strcmp(argv[2],"--sample-coverage")==0)return CoverageProbe(std::filesystem::u8path(argv[1]));
    if(argc==3&&std::strcmp(argv[2],"--creation-matrix")==0)return CreationMatrix(std::filesystem::u8path(argv[1]));
    if(argc!=2)return 1;
    const std::filesystem::path evidence=std::filesystem::u8path(argv[1]);
    std::filesystem::create_directories(evidence);
    const auto unavailable=[&](const char* stage,HRESULT hr,const D3DADAPTER_IDENTIFIER9* adapter,DWORD quality=0){
        char text[700];std::snprintf(text,sizeof(text),"probe=UNAVAILABLE msaaSceneAcceptance=BLOCKED stage=%s adapter=%04x:%04x description=%s hr=%08lx quality=%lu\n",stage,adapter?adapter->VendorId:0,adapter?adapter->DeviceId:0,adapter?adapter->Description:"unknown",(unsigned long)hr,quality);
        std::fputs(text,stdout);std::ofstream(evidence/"msaa_history.capabilities",std::ios::trunc)<<text;return 77;
    };
    HWND window=CreateWindowW(L"STATIC",L"MSAA history capability probe",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    struct Window {HWND h;~Window(){if(h)DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));
    if(!window || !api)return unavailable("window_or_Direct3DCreate9",E_FAIL,nullptr);
    D3DADAPTER_IDENTIFIER9 diagnosticAdapter{};api->GetAdapterIdentifier(0,0,&diagnosticAdapter);
    DWORD quality=0;const HRESULT sampleSupport=api->CheckDeviceMultiSampleType(0,D3DDEVTYPE_HAL,D3DFMT_A8R8G8B8,TRUE,D3DMULTISAMPLE_8_SAMPLES,&quality);
    if(FAILED(sampleSupport)||!quality)return unavailable("CheckDeviceMultiSampleType",sampleSupport,&diagnosticAdapter,quality);
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferFormat=D3DFMT_A8R8G8B8;
    pp.BackBufferWidth=pp.BackBufferHeight=64;pp.hDeviceWindow=window;
    ComPtr<IDirect3DDevice9> device;
    const HRESULT creation=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
    if(FAILED(creation))return unavailable("CreateDevice",creation,&diagnosticAdapter);
    ComPtr<IDirect3DSurface9> color,depth,resolved,system,depthSystem;
    if(FAILED(device->CreateRenderTarget(64,64,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_8_SAMPLES,0,FALSE,&color,nullptr)) ||
       FAILED(device->CreateDepthStencilSurface(64,64,D3DFMT_D24S8,D3DMULTISAMPLE_8_SAMPLES,0,FALSE,&depth,nullptr)) ||
       FAILED(device->CreateRenderTarget(64,64,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&resolved,nullptr)) ||
       FAILED(device->CreateOffscreenPlainSurface(64,64,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
    if(FAILED(device->SetRenderTarget(0,color.Get())) || FAILED(device->SetDepthStencilSurface(depth.Get())) ||
       FAILED(device->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff123456,.375f,7)))return 1;
    const HRESULT colorRead=device->GetRenderTargetData(color.Get(),system.Get());
    const HRESULT depthSystemCreate=device->CreateOffscreenPlainSurface(64,64,D3DFMT_D24S8,D3DPOOL_SYSTEMMEM,&depthSystem,nullptr);
    const HRESULT depthRead=device->GetRenderTargetData(depth.Get(),system.Get());
    D3DLOCKED_RECT lock{};const HRESULT colorLock=color->LockRect(&lock,nullptr,D3DLOCK_READONLY);if(SUCCEEDED(colorLock))color->UnlockRect();
    const HRESULT depthLock=depth->LockRect(&lock,nullptr,D3DLOCK_READONLY);if(SUCCEEDED(depthLock))depth->UnlockRect();
    ComPtr<IDirect3DTexture9> container;
    const HRESULT depthContainer=depth->GetContainer(__uuidof(IDirect3DTexture9),reinterpret_cast<void**>(container.GetAddressOf()));
    const HRESULT resolve=device->StretchRect(color.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE);
    const HRESULT resolvedRead=SUCCEEDED(resolve)?device->GetRenderTargetData(resolved.Get(),system.Get()):resolve;
    const char* shader="Texture2DMS<float4,8> history:register(t0);float4 main(float4 p:VPOS):COLOR0{return history.Load(int2(p.xy),3);}";
    ComPtr<ID3DBlob> code,errors;const HRESULT sampleShader=D3DCompile(shader,std::strlen(shader),nullptr,nullptr,nullptr,"main","ps_3_0",0,0,&code,&errors);
    const bool noDirect=FAILED(colorRead)&&FAILED(depthRead)&&FAILED(colorLock)&&FAILED(depthLock)&&FAILED(depthContainer)&&FAILED(sampleShader);
    const bool resolvedOnly=SUCCEEDED(resolve)&&SUCCEEDED(resolvedRead);
    using namespace mikudancestudio::rhi;
    // Readback availability does not establish which color resolve curve the
    // driver uses. That needs a separate numerical calibration/profile.
    HistoryCapabilities native;native.resolvedColorCapture=resolvedOnly;native.maxSamples=8;
    HistoryDesc request;request.width=request.height=64;request.samples=8;request.representation=HistoryRepresentation::PerSample;request.samplePattern=1;
    if(CanCaptureHistory(native,request))return 1;
    D3DADAPTER_IDENTIFIER9 id{};if(FAILED(api->GetAdapterIdentifier(0,0,&id)))return 1;
    std::filesystem::path root=std::filesystem::u8path(argv[1]);std::filesystem::create_directories(root);
    char report[1200];std::snprintf(report,sizeof(report),
        "probe=%s msaaSceneAcceptance=BLOCKED adapter=%04x:%04x samples=8 quality=0 colorRead=%08lx depthSystemCreate=%08lx depthRead=%08lx colorLock=%08lx depthLock=%08lx depthTextureContainer=%08lx resolve=%08lx resolvedRead=%08lx sampleIndexShader=%08lx perSampleCapture=0 perSampleRestore=0 completeDrawReplay=0 requiredPath=orderedDrawReplay\n",
        noDirect&&resolvedOnly?"PASS":"UNEXPECTED",id.VendorId,id.DeviceId,(unsigned long)colorRead,(unsigned long)depthSystemCreate,(unsigned long)depthRead,(unsigned long)colorLock,(unsigned long)depthLock,(unsigned long)depthContainer,(unsigned long)resolve,(unsigned long)resolvedRead,(unsigned long)sampleShader);
    std::fputs(report,stdout);std::ofstream out(root/"msaa_history.capabilities");out<<report;
    if(errors){std::ofstream errorFile(root/"sample-index-shader.error");errorFile.write(static_cast<const char*>(errors->GetBufferPointer()),errors->GetBufferSize());}
    return out && noDirect && resolvedOnly?0:1;
}
