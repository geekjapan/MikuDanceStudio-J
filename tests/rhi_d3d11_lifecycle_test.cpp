#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi_d3d11.hpp"
#include "mikudancestudio/rhi_assets.hpp"
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
using namespace mikudancestudio::rhi;
using Microsoft::WRL::ComPtr;
#define CHECK(x) do { if(!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); return 1; } } while(0)
struct WindowOwner { HWND value; ~WindowOwner() { if(value) DestroyWindow(value); } };
struct Vertex { float x,y,z,w; std::uint32_t color; float u,v; };
const Vertex vertices[]={{8,8,.5f,1,0xffffffff,0,0},{8,48,.5f,1,0xffffffff,0,1},{48,8,.5f,1,0xffffffff,1,0}};
std::uint64_t Hash(const RgbaImage& image) { std::uint64_t h=14695981039346656037ull; for(auto b:image.pixels) h=(h^b)*1099511628211ull; return h; }
int main(int argc,char** argv) {
    const bool compatible=argc>1 && (std::string(argv[1])=="--compatibility-hardware" || std::string(argv[1])=="--compatibility-warp");
    const bool hardware=argc>1 && (std::string(argv[1])=="--hardware" || std::string(argv[1])=="--compatibility-hardware");
    const D3D11ModelOptions options{compatible?D3D11ModelCompatibility::Dx9Measured:D3D11ModelCompatibility::Default};
    const std::filesystem::path evidence=argc>2 ? argv[2] : "dx11-lifecycle-evidence";
    std::filesystem::create_directories(evidence);
    std::ofstream report(evidence/(hardware ? "hardware.log" : "warp.log"));
    report<<"driver="<<(hardware ? "hardware" : "warp")<<" samples=1\n";
    WindowOwner window{CreateWindowExW(0,L"STATIC",L"DX11 lifecycle test",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};
    CHECK(window.value);
    SwapchainDesc desc; desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window.value)};
    desc.width=desc.height=64; desc.present=PresentMode::Immediate;
    auto bundle=CreateD3D11Device(desc,hardware ? D3D11Driver::Hardware : D3D11Driver::Warp,options);
    if(!bundle) {
        const auto hr=static_cast<HRESULT>(bundle.creationError);
        const bool unavailable=(bundle.stage==D3D11CreationStage::Compatibility && bundle.creationReason=="shader_doubles_required") || (bundle.stage==D3D11CreationStage::NativeDevice &&
            (hr==DXGI_ERROR_UNSUPPORTED || hr==DXGI_ERROR_NOT_CURRENTLY_AVAILABLE ||
             hr==DXGI_ERROR_DEVICE_REMOVED || hr==DXGI_ERROR_DEVICE_RESET || hr==DXGI_ERROR_DRIVER_INTERNAL_ERROR));
        report<<"status="<<(unavailable ? "UNAVAILABLE" : "FAIL")<<" stage="<<static_cast<unsigned>(bundle.stage)
            <<" creationHR="<<std::hex<<static_cast<std::uint32_t>(hr)<<" reason="<<bundle.creationReason<<"\n";
        return unavailable ? 77 : 1;
    }
    report<<"adapter="<<bundle.adapterName<<" vendor="<<std::hex<<bundle.vendorId<<" device="<<bundle.deviceId<<std::dec<<"\n";
    auto& device=*bundle.device; auto& chain=*bundle.swapchain;
    const auto support=QueryD3D11ModelSupport(device,options.compatibility);
    CHECK(support.selected==options.compatibility && support.requestedSupport==D3D11CompatibilityResult::Supported);
    report<<"compatibility="<<(compatible?"dx9_measured":"default")<<" doubles="<<support.shaderDoubles<<"\n";
    CHECK(device.BackendType()==Backend::D3D11 && chain.Query(desc).supported && chain.Query(desc).controllerOwnsReset);
    auto bad=desc; bad.samples=8; CHECK(!chain.Query(bad).supported && chain.Rebuild(bad,RebuildReason::Resize)==RebuildResult::Unsupported);
    bad=desc; bad.width=0; CHECK(chain.Rebuild(bad,RebuildReason::Resize)==RebuildResult::Invalid);
    CHECK(chain.Rebuild(desc,RebuildReason::TemporaryLoss)==RebuildResult::Unsupported);
    FixedPipelineState pipeline=HudSpritePipeline();
    pipeline.lighting=false; pipeline.cull=RasterCull::None; pipeline.stencilTest=false; pipeline.alphaTest=false; pipeline.alphaBlend=false;
    pipeline.sampler.min=pipeline.sampler.mag=pipeline.sampler.mip=SamplerFilter::Point;
    pipeline.sampler.u=pipeline.sampler.v=SamplerAddress::Clamp;
    auto buffer=device.CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices); CHECK(buffer);
    auto dynamic=device.CreateBuffer({BufferUsage::Vertex,sizeof(vertices),true},vertices); CHECK(dynamic);
    CHECK(!device.Upload(dynamic,4,vertices,sizeof(vertices)-4) && device.Upload(dynamic,0,vertices,sizeof(vertices)));
    AtlasAsset cpu; cpu.image.width=cpu.image.height=2; cpu.revision=1;
    for(int i=0;i<4;++i) cpu.image.pixels.insert(cpu.image.pixels.end(),{81,37,203,255});
    D3D11Bundle next; // outlives the cache after rebinding
    AtlasTextureCache cache(device);
    auto texture=cache.Get(AssetId::HudSprites,cpu); CHECK(texture && cache.Uploads()==1);
    auto original=device.Record(NonIndexedDraw{buffer,0,3});
    auto render=[&](Device& d,Handle mesh,Handle image,NonIndexedDraw stale,RgbaImage& output) {
        if(!d.BeginFrame({0,0,0,1}) || !d.SetFixedPipeline(pipeline) || !d.BindTexture(0,image)) return false;
        if(stale.submission.device && d.Draw(stale)) return false;
        if(!d.Draw(d.Record(NonIndexedDraw{mesh,0,3})) || !d.EndFrame() || !ReadD3D11Swapchain(d,output)) return false;
        return d.Present();
    };
    CHECK(device.BeginFrame({}) && chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Busy && device.EndFrame());
    std::map<unsigned,RgbaImage> references;
    for(unsigned size : {64u,96u,80u,64u,96u,80u,64u}) {
        CHECK(SetWindowPos(window.value,nullptr,0,0,size,size,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE));
        const auto epoch=device.Status().epoch; const auto stale=device.Record(NonIndexedDraw{buffer,0,3});
        desc.width=desc.height=size;
        CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success && device.Status().epoch==epoch+1);
        CHECK(cache.Get(AssetId::HudSprites,cpu).generation==texture.generation && cache.Uploads()==1);
        RgbaImage image; CHECK(render(device,buffer,texture,stale,image));
        CHECK(image.width==size && image.height==size);
        const auto pixel=(16*size+16)*4; CHECK(image.pixels[pixel]==81 && image.pixels[pixel+1]==37 && image.pixels[pixel+2]==203 && image.pixels[pixel+3]==255);
        CHECK(image.pixels[(60*size+60)*4]==0);
        if(references.count(size)) CHECK(references[size].pixels==image.pixels); else references[size]=image;
        std::ofstream bytes(evidence/((hardware ? "hardware-" : "warp-")+std::to_string(size)+".rgba"),std::ios::binary);
        bytes.write(reinterpret_cast<const char*>(image.pixels.data()),image.pixels.size());
        report<<"resize="<<size<<" epoch="<<device.Status().epoch<<" retainedUploads="<<cache.Uploads()<<" hash="<<Hash(image)<<"\n";
    }
    CHECK(device.BeginFrame({}) && device.SetFixedPipeline(pipeline) && device.BindTexture(0,texture));
    CHECK(!device.Draw(original) && device.Draw(device.Record(NonIndexedDraw{dynamic,0,3})) && device.EndFrame() && device.Present());
    const auto minimizeEpoch=device.Status().epoch;
    ShowWindow(window.value,SW_SHOWNOACTIVATE); ShowWindow(window.value,SW_MINIMIZE);
    MSG message{}; while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)) DispatchMessageW(&message);
    CHECK(IsIconic(window.value) && chain.Health()==SurfaceHealth::Suspended);
    CHECK(!device.BeginFrame({}) && chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::RetryLater && device.Status().epoch==minimizeEpoch);
    ShowWindow(window.value,SW_RESTORE);
    while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)) DispatchMessageW(&message);
    CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success);
    // An external reference must prevent ResizeBuffers; no epoch publication.
    ComPtr<ID3D11Texture2D> held; CHECK(AcquireD3D11Backbuffer(device,&held));
    const auto failureEpoch=device.Status().epoch; desc.width=desc.height=80;
    CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Failed);
    CHECK(chain.LastNativeError()==static_cast<std::int64_t>(DXGI_ERROR_INVALID_CALL));
    CHECK(device.Status().state==DeviceState::ResetPending && device.Status().epoch==failureEpoch && !device.BeginFrame({}) && !cache.Get(AssetId::HudSprites,cpu));
    report<<"heldBackbufferHR="<<std::hex<<static_cast<std::uint32_t>(chain.LastNativeError())<<std::dec<<" blocked=1\n";
    held.Reset(); CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success && device.Status().epoch==failureEpoch+1);
    RgbaImage recovered; CHECK(render(device,buffer,texture,original,recovered) && recovered.pixels==references[80].pixels);
    // Generated model batch always runs, including when external PMM is absent.
    CHECK(ResizeD3D11Offscreen(device,64,64));
    struct ModelVertex {float x,y,z,nx,ny,nz,u,v;};
    const ModelVertex modelVertices[]={{-.8f,-.8f,.5f,0,0,1,0,1},{-.8f,.8f,.5f,0,0,1,0,0},{.8f,-.8f,.5f,0,0,1,1,1}};
    const std::uint16_t modelIndices[]={0,1,2};
    auto modelVb=device.CreateBuffer({BufferUsage::Vertex,sizeof(modelVertices)},modelVertices);
    auto modelIb=device.CreateBuffer({BufferUsage::Index,sizeof(modelIndices)},modelIndices);CHECK(modelVb && modelIb);
    ModelPipeline model; model.raster.alphaBlend=false;model.raster.cull=BatchCull::None;
    for(auto* matrix:{&model.shader.world,&model.shader.view,&model.shader.projection,&model.shader.normalView})
        *matrix={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    model.shader.nativeDiffuse={1,1,1,1};
    for(unsigned stage=0;stage<3;++stage) {
        auto& t=model.shader.layout.stages[stage];t.role=stage==0?MaterialTextureRole::Toon:stage==1?MaterialTextureRole::Base:MaterialTextureRole::Sphere;
        t.color=MaterialCombine::Modulate;t.colorArg2=stage==0?MaterialColorSource::LitDiffuse:MaterialColorSource::Previous;
        model.shader.samplers[stage].min=model.shader.samplers[stage].mag=model.shader.samplers[stage].mip=SamplerFilter::Point;
    }
    ModelTextureData white;white.levels.push_back({1,1,{255,255,255,255}});
    auto whiteTexture=CreateD3D11ModelTexture(device,white);CHECK(whiteTexture);
    const auto modelCommand=device.Record(IndexedDraw{modelVb,modelIb,0,3,3,VertexLayout::PositionNormalUv});
    CHECK(device.BeginFrame({0,0,0,1}));
    auto unsupported=model;unsupported.shader.layout.stages[0].coordinates=MaterialCoordinates::MeshUv1;
    CHECK(!device.SetModelPipeline(unsupported) && !device.DrawIndexed(modelCommand));
    CHECK(device.SetModelPipeline(model) && !device.DrawIndexed(modelCommand));
    CHECK(device.BindTexture(0,whiteTexture) && device.BindTexture(1,whiteTexture) && !device.DrawIndexed(modelCommand));
    CHECK(device.BindTexture(2,whiteTexture) && device.DrawIndexed(modelCommand) && device.EndFrame());
    RgbaImage modelImage;CHECK(ReadD3D11Offscreen(device,modelImage) && modelImage.pixels[(40*64+16)*4]==255);
    CHECK(ResizeD3D11Offscreen(device,80,80) && ResizeD3D11Offscreen(device,64,64));
    CHECK(device.BeginFrame({0,0,0,1}) && device.SetModelPipeline(model));
    for(unsigned stage=0;stage<3;++stage)CHECK(device.BindTexture(stage,whiteTexture));
    CHECK(!device.DrawIndexed(modelCommand) && device.DrawIndexed(device.Record(modelCommand)) && device.EndFrame());
    RgbaImage modelRestored;CHECK(ReadD3D11Offscreen(device,modelRestored) && modelRestored.pixels==modelImage.pixels);
    // Restore the presentation target for the original lifecycle controls.
    CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success);
    // Explicit device replacement; use the same CPU asset, no old GPU handles.
    next=CreateD3D11Device(desc,hardware ? D3D11Driver::Hardware : D3D11Driver::Warp,options); CHECK(next);
    CHECK(next.device->Status().identity!=device.Status().identity && cache.Rebind(*next.device));
    CHECK(chain.Rebuild(desc,RebuildReason::DeviceReplacement)==RebuildResult::ReplacementRequired && chain.Health()==SurfaceHealth::Removed);
    CHECK(!device.BeginFrame({}) && chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::ReplacementRequired);
    auto replacement=cache.Get(AssetId::HudSprites,cpu); CHECK(replacement && cache.Uploads()==2);
    auto mesh=next.device->CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices); CHECK(mesh);
    CHECK(!next.device->Destroy(buffer));
    NonIndexedDraw obsolete{mesh,0,3}; obsolete.submission=original.submission;
    RgbaImage replaced; CHECK(render(*next.device,mesh,replacement,obsolete,replaced) && replaced.pixels==references[80].pixels);
    cache.Invalidate();
    report<<"minimizeRestore=PASS staleSubmission=PASS failureRecovery=PASS replacement=PASS uploads=2 status=PASS\n";
    std::puts(hardware ? "DX11 hardware lifecycle passed" : "DX11 WARP lifecycle passed");
    return 0;
}
