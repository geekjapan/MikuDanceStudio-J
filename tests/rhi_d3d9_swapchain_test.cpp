#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include "mikudancestudio/rhi_d3d9.hpp"
#include <cstdio>
#include <map>
#include <vector>
using namespace mikudancestudio::rhi;
#define CHECK(x) do { if(!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); return 1; } } while(0)
static bool Image(IDirect3DDevice9* native, unsigned size, std::vector<unsigned>& pixels) {
    IDirect3DSurface9 *target=nullptr,*cpu=nullptr;
    if(FAILED(native->GetRenderTarget(0,&target))) return false;
    D3DSURFACE_DESC desc{}; target->GetDesc(&desc);
    bool ok=desc.Width==size && desc.Height==size && desc.MultiSampleType==D3DMULTISAMPLE_NONE &&
        SUCCEEDED(native->CreateOffscreenPlainSurface(size,size,desc.Format,D3DPOOL_SYSTEMMEM,&cpu,nullptr)) &&
        SUCCEEDED(native->GetRenderTargetData(target,cpu));
    D3DLOCKED_RECT lock{};
    if(ok && SUCCEEDED(cpu->LockRect(&lock,nullptr,D3DLOCK_READONLY))) {
        pixels.resize(size*size);
        for(unsigned y=0;y<size;++y) for(unsigned x=0;x<size;++x)
            pixels[y*size+x]=reinterpret_cast<const unsigned*>(static_cast<const char*>(lock.pBits)+y*lock.Pitch)[x];
        cpu->UnlockRect();
    } else ok=false;
    if(cpu) cpu->Release(); target->Release(); return ok;
}
int main() {
    auto* api=Direct3DCreate9(D3D_SDK_VERSION); if(!api) return 77;
    HWND window=CreateWindowExW(0,L"STATIC",L"swapchain test",WS_POPUP,0,0,128,128,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window) { api->Release(); return 77; }
    D3DPRESENT_PARAMETERS p{};
    p.BackBufferWidth=p.BackBufferHeight=64; p.BackBufferFormat=D3DFMT_A8R8G8B8;
    p.BackBufferCount=1; p.Windowed=TRUE; p.hDeviceWindow=window;
    p.SwapEffect=D3DSWAPEFFECT_DISCARD; p.EnableAutoDepthStencil=TRUE;
    p.AutoDepthStencilFormat=D3DFMT_D16; p.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* native=nullptr;
    auto hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_SOFTWARE_VERTEXPROCESSING,&p,&native);
    if(FAILED(hr)) { std::fprintf(stderr,"CreateDevice HRESULT=0x%08lx\n",static_cast<unsigned long>(hr)); DestroyWindow(window); api->Release(); return 77; }
    auto device=CreateD3D9Device(native);
    auto surface=CreateD3D9Swapchain(*device,native); CHECK(surface);
    auto desc=surface->Description(); CHECK(desc.width==64 && desc.depth==SurfaceDepth::Depth16);
    auto support=surface->Query(desc); CHECK(support.supported && support.controllerOwnsReset && support.applicationOwnsDeviceReplacement);
    auto bad=desc; bad.width=0;
    CHECK(surface->Rebuild(bad,RebuildReason::Resize)==RebuildResult::Invalid);
    bad=desc; bad.quality=1; CHECK(!surface->Query(bad).supported);
    bad=desc; bad.window.system=WindowSystem::Cocoa; CHECK(!surface->Query(bad).supported);
    struct Vertex { float x,y,z,w; unsigned color; float u,v; };
    const Vertex vertices[]={{8,8,0,1,0xffffffff,0,0},{8,48,0,1,0xffffffff,0,1},{48,8,0,1,0xffffffff,1,0}};
    auto buffer=device->CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices); CHECK(buffer);
    auto cache=std::make_unique<AtlasTextureCache>(*device);
    AtlasAsset cpu; cpu.image={2,2,std::vector<std::uint8_t>(16,255)}; cpu.revision=1;
    const auto texture=cache->Get(AssetId::HudSprites,cpu); CHECK(texture);
    auto pipeline=HudSpritePipeline();
    // Lifecycle control batch: no inherited lights, culling or stencil.
    pipeline.lighting=false; pipeline.cull=RasterCull::None;
    pipeline.stencilTest=false; pipeline.depthTest=false; pipeline.depthWrite=false;
    auto original=device->Record(NonIndexedDraw{buffer,0,3});
    CHECK(device->BeginFrame({}));
    CHECK(surface->Rebuild(desc,RebuildReason::Resize)==RebuildResult::Busy);
    CHECK(device->EndFrame());
    std::map<unsigned,std::vector<unsigned>> reference;
    for(unsigned size : {64u,96u,80u,64u,96u,80u,64u}) {
        const auto stale=device->Record(NonIndexedDraw{buffer,0,3});
        const auto epoch=device->Status().epoch;
        RECT client{0,0,static_cast<LONG>(size),static_cast<LONG>(size)};
        CHECK(AdjustWindowRect(&client,WS_POPUP,FALSE));
        CHECK(SetWindowPos(window,nullptr,0,0,client.right-client.left,client.bottom-client.top,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE));
        RECT actual{}; CHECK(GetClientRect(window,&actual) && actual.right==size && actual.bottom==size);
        desc.width=desc.height=size;
        CHECK(surface->Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success);
        CHECK(device->Status().epoch==epoch+1 && surface->Health()==SurfaceHealth::Ready);
        CHECK(cache->Get(AssetId::HudSprites,cpu).generation==texture.generation && cache->Uploads()==1);
        CHECK(device->BeginFrame({0,0,0,1}));
        CHECK(device->SetFixedPipeline(pipeline));
        CHECK(device->BindTexture(0,texture));
        CHECK(!device->Draw(stale) && !device->Draw(original));
        CHECK(device->Draw(device->Record(NonIndexedDraw{buffer,0,3})));
        CHECK(device->EndFrame());
        std::vector<unsigned> image; CHECK(Image(native,size,image));
        CHECK((image[16*size+16]&0xffffff)==0xffffff && (image[60*size+60]&0xffffff)==0);
        if(reference.count(size)) CHECK(reference[size]==image); else reference[size]=image;
        CHECK(device->Present());
    }
    // An application-held backbuffer blocks Reset. Failure must not publish
    // a new epoch, permit draws, or prevent recovery after release.
    IDirect3DSurface9* held=nullptr;
    CHECK(SUCCEEDED(native->GetRenderTarget(0,&held)));
    const auto failureEpoch=device->Status().epoch;
    CHECK(surface->Rebuild(desc,RebuildReason::Resize)==RebuildResult::Failed);
    CHECK(surface->LastNativeError()!=0 && device->Status().epoch==failureEpoch);
    CHECK(device->Status().state==DeviceState::ResetPending && !device->BeginFrame({}));
    CHECK(!cache->Get(AssetId::HudSprites,cpu));
    held->Release();
    CHECK(surface->Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success);
    CHECK(surface->LastNativeError()==0 && device->Status().epoch==failureEpoch+1);
    // TemporaryLoss recovery is exercised while cooperative; genuine driver
    // loss cannot safely be forced here and is reported separately.
    CHECK(surface->Rebuild(desc,RebuildReason::TemporaryLoss)==RebuildResult::Success);
    IDirect3DDevice9* second=nullptr; p.BackBufferWidth=p.BackBufferHeight=64;
    hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_SOFTWARE_VERTEXPROCESSING,&p,&second);
    CHECK(SUCCEEDED(hr));
    auto next=CreateD3D9Device(second); auto nextSurface=CreateD3D9Swapchain(*next,second); CHECK(nextSurface);
    CHECK(cache->Rebind(*next));
    CHECK(surface->Rebuild(desc,RebuildReason::DeviceReplacement)==RebuildResult::ReplacementRequired);
    CHECK(surface->Health()==SurfaceHealth::Removed && !device->BeginFrame({}));
    CHECK(surface->Rebuild(desc,RebuildReason::Resize)==RebuildResult::ReplacementRequired);
    auto uploaded=cache->Get(AssetId::HudSprites,cpu); CHECK(uploaded && cache->Uploads()==2);
    auto newBuffer=next->CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices); CHECK(newBuffer);
    CHECK(next->BeginFrame({0,0,0,1}) && next->SetFixedPipeline(pipeline) && next->BindTexture(0,uploaded));
    CHECK(!next->Draw(original) && next->Draw(next->Record(NonIndexedDraw{newBuffer,0,3})) && next->EndFrame());
    std::vector<unsigned> image; CHECK(Image(second,64,image) && image==reference[64]);
    CHECK(next->Present());
    cache.reset(); nextSurface.reset(); next.reset(); second->Release();
    surface.reset(); device.reset(); native->Release(); DestroyWindow(window); api->Release();
    std::puts("resize/reset x7, epoch rejection, retained upload, native replacement, recovered image: passed");
    return 0;
}
