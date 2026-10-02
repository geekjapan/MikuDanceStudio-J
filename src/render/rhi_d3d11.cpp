#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "mikudancestudio/rhi_d3d11.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
using Microsoft::WRL::ComPtr;
namespace mikudancestudio::rhi {
namespace {
DXGI_FORMAT Depth(SurfaceDepth d) { return d==SurfaceDepth::Depth16 ? DXGI_FORMAT_D16_UNORM : DXGI_FORMAT_D24_UNORM_S8_UINT; }
struct Resource {
    std::uint32_t generation=1;
    bool alive=false,uploaded=false;
    BufferDesc description{}; TextureDesc textureDescription{};
    ComPtr<ID3D11Buffer> buffer;
    ComPtr<ID3D11Texture2D> texture;
    ComPtr<ID3D11ShaderResourceView> view;
};
class D3D11Device final : public Device {
public:
    ComPtr<ID3D11Device> native; ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain> chain;
    ComPtr<ID3D11RenderTargetView> target;
    ComPtr<ID3D11Texture2D> depth;
    ComPtr<ID3D11DepthStencilView> depthView;
    SwapchainDesc desc{};
    HRESULT lastError=S_OK;
    bool inFrame=false,pending=false,presentable=false,pipelineReady=false;
    std::uint64_t identity=detail::NextDeviceIdentity(),epoch=1;
    std::vector<Resource> resources;
    Handle boundTexture{};
    ComPtr<ID3D11VertexShader> vs; ComPtr<ID3D11PixelShader> ps;
    ComPtr<ID3D11InputLayout> layout; ComPtr<ID3D11Buffer> constants;
    ComPtr<ID3D11SamplerState> sampler; ComPtr<ID3D11BlendState> blend;
    ComPtr<ID3D11DepthStencilState> depthState; ComPtr<ID3D11RasterizerState> raster;
    ~D3D11Device() override { if(context) { context->ClearState(); context->Flush(); } }
    Backend BackendType() const override { return Backend::D3D11; }
    Capabilities Features() const override { return {true,false,false,true}; }
    DeviceStatus Status() const override { return {identity,epoch,pending ? DeviceState::ResetPending : DeviceState::Ready}; }
    ResourceLifecycleCapabilities ResourceLifecycleFeatures() const override { return {true,true,true,false,false}; }
    bool Live() const { return !pending && native->GetDeviceRemovedReason()==S_OK; }
    Resource* Find(Handle h) {
        if(h.device!=identity || h.index>=resources.size()) return nullptr;
        auto& r=resources[h.index]; return r.alive && h.generation==r.generation ? &r : nullptr;
    }
    Handle Insert(Resource r) {
        for(std::uint32_t i=0;i<resources.size();++i) if(!resources[i].alive) {
            r.generation=resources[i].generation; resources[i]=std::move(r); return {i,resources[i].generation,identity};
        }
        resources.push_back(std::move(r)); return {static_cast<std::uint32_t>(resources.size()-1),1,identity};
    }
    Handle CreateBuffer(BufferDesc d,const void* data) override {
        if(!Live() || d.usage!=BufferUsage::Vertex || !d.size || d.size>std::numeric_limits<UINT>::max()) return {};
        D3D11_BUFFER_DESC b{}; b.ByteWidth=static_cast<UINT>(d.size); b.BindFlags=D3D11_BIND_VERTEX_BUFFER;
        b.Usage=d.dynamic ? D3D11_USAGE_DYNAMIC : D3D11_USAGE_DEFAULT;
        b.CPUAccessFlags=d.dynamic ? D3D11_CPU_ACCESS_WRITE : 0;
        D3D11_SUBRESOURCE_DATA initial{}; initial.pSysMem=data;
        Resource r; r.description=d; r.alive=true;
        lastError=native->CreateBuffer(&b,data ? &initial : nullptr,&r.buffer);
        return SUCCEEDED(lastError) ? Insert(std::move(r)) : Handle{};
    }
    Handle CreateTexture(TextureDesc d) override {
        if(!Live() || !d.width || !d.height || d.width>16384 || d.height>16384 ||
           d.format!=TextureFormat::Rgba8 || d.mips!=TextureDesc::Mips::SingleLevel) return {};
        D3D11_TEXTURE2D_DESC t{}; t.Width=d.width; t.Height=d.height; t.ArraySize=t.MipLevels=1;
        t.Format=DXGI_FORMAT_R8G8B8A8_UNORM; t.SampleDesc.Count=1;
        t.Usage=D3D11_USAGE_DEFAULT; t.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        Resource r; r.alive=true; r.textureDescription=d;
        lastError=native->CreateTexture2D(&t,nullptr,&r.texture);
        if(SUCCEEDED(lastError)) lastError=native->CreateShaderResourceView(r.texture.Get(),nullptr,&r.view);
        return SUCCEEDED(lastError) ? Insert(std::move(r)) : Handle{};
    }
    bool UploadTexture(Handle h,TexturePixels pixels) override {
        auto* r=Find(h);
        if(!Live() || inFrame || !r || !r->texture || !pixels.data) return false;
        const auto width=static_cast<std::size_t>(r->textureDescription.width)*4;
        const auto height=r->textureDescription.height;
        if(pixels.rowPitch<width || pixels.rowPitch>std::numeric_limits<UINT>::max() ||
           pixels.rowPitch>std::numeric_limits<std::size_t>::max()/height || pixels.bytes<(height-1)*pixels.rowPitch+width) return false;
        context->UpdateSubresource(r->texture.Get(),0,nullptr,pixels.data,static_cast<UINT>(pixels.rowPitch),0);
        r->uploaded=true; return native->GetDeviceRemovedReason()==S_OK;
    }
    bool BindTexture(std::uint32_t slot,Handle h) override {
        auto* r=Find(h); if(!Live() || !inFrame || slot!=0 || !r || !r->view || !r->uploaded) return false;
        auto* view=r->view.Get(); context->PSSetShaderResources(0,1,&view); boundTexture=h; return true;
    }
    bool Upload(Handle h,std::size_t offset,const void* data,std::size_t size) override {
        auto* r=Find(h);
        if(!Live() || inFrame || !r || !r->buffer || (!data && size) || offset>r->description.size || size>r->description.size-offset) return false;
        if(!size) return true;
        if(r->description.dynamic) {
            // DISCARD is a whole-buffer replacement; partial writes unsupported.
            if(offset || size!=r->description.size) return false;
            D3D11_MAPPED_SUBRESOURCE mapped{};
            lastError=context->Map(r->buffer.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);
            if(FAILED(lastError)) return false;
            std::memcpy(mapped.pData,data,size); context->Unmap(r->buffer.Get(),0);
        } else {
            D3D11_BOX box{static_cast<UINT>(offset),0,0,static_cast<UINT>(offset+size),1,1};
            context->UpdateSubresource(r->buffer.Get(),0,&box,data,0,0);
        }
        return native->GetDeviceRemovedReason()==S_OK;
    }
    bool Destroy(Handle h) override {
        auto* r=Find(h); if(!Live() || inFrame || !r) return false;
        r->buffer.Reset(); r->texture.Reset(); r->view.Reset(); r->alive=false;
        if(++r->generation==0) ++r->generation; return true;
    }
    bool InitializeShaders() {
        const char* source=R"(
cbuffer Screen : register(b0) { float4 size; }
struct V { float4 p:POSITION; float4 c:COLOR; float2 uv:TEXCOORD; };
struct O { float4 p:SV_POSITION; float4 c:COLOR; float2 uv:TEXCOORD; };
O vs(V v) { O o; o.p=float4(v.p.x*2/size.x-1,1-v.p.y*2/size.y,v.p.z,1)/v.p.w;
 o.c=v.c.bgra; o.uv=v.uv; return o; }
Texture2D image:register(t0); SamplerState sampling:register(s0);
float4 ps(O o):SV_TARGET { return image.Sample(sampling,o.uv)*o.c; }
)";
        ComPtr<ID3DBlob> vertex,pixel,error;
        lastError=D3DCompile(source,std::strlen(source),nullptr,nullptr,nullptr,"vs","vs_4_0",0,0,&vertex,&error);
        if(SUCCEEDED(lastError)) lastError=D3DCompile(source,std::strlen(source),nullptr,nullptr,nullptr,"ps","ps_4_0",0,0,&pixel,&error);
        if(FAILED(lastError)) return false;
        lastError=native->CreateVertexShader(vertex->GetBufferPointer(),vertex->GetBufferSize(),nullptr,&vs);
        if(SUCCEEDED(lastError)) lastError=native->CreatePixelShader(pixel->GetBufferPointer(),pixel->GetBufferSize(),nullptr,&ps);
        const D3D11_INPUT_ELEMENT_DESC elements[]={
            {"POSITION",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
            {"COLOR",0,DXGI_FORMAT_R8G8B8A8_UNORM,0,16,D3D11_INPUT_PER_VERTEX_DATA,0},
            {"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,20,D3D11_INPUT_PER_VERTEX_DATA,0}};
        if(SUCCEEDED(lastError)) lastError=native->CreateInputLayout(elements,3,vertex->GetBufferPointer(),vertex->GetBufferSize(),&layout);
        D3D11_BUFFER_DESC b{}; b.ByteWidth=16; b.Usage=D3D11_USAGE_DEFAULT; b.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        if(SUCCEEDED(lastError)) lastError=native->CreateBuffer(&b,nullptr,&constants);
        return SUCCEEDED(lastError);
    }
    bool CreateTargets() {
        ComPtr<ID3D11Texture2D> back;
        lastError=chain->GetBuffer(0,IID_PPV_ARGS(&back));
        if(SUCCEEDED(lastError)) lastError=native->CreateRenderTargetView(back.Get(),nullptr,&target);
        if(SUCCEEDED(lastError) && desc.depth!=SurfaceDepth::None) {
            D3D11_TEXTURE2D_DESC d{}; d.Width=desc.width; d.Height=desc.height; d.ArraySize=d.MipLevels=1;
            d.Format=Depth(desc.depth); d.SampleDesc.Count=1; d.BindFlags=D3D11_BIND_DEPTH_STENCIL;
            lastError=native->CreateTexture2D(&d,nullptr,&depth);
            if(SUCCEEDED(lastError)) lastError=native->CreateDepthStencilView(depth.Get(),nullptr,&depthView);
        }
        return SUCCEEDED(lastError);
    }
    bool BeginFrame(ClearColor c) override {
        for(float value : {c.red,c.green,c.blue,c.alpha}) if(!std::isfinite(value) || value<0 || value>1) return false;
        if(!Live() || inFrame || !target || IsIconic(reinterpret_cast<HWND>(desc.window.handle))) return false;
        auto* t=target.Get(); context->OMSetRenderTargets(1,&t,depthView.Get());
        const float rgba[]={c.red,c.green,c.blue,c.alpha}; context->ClearRenderTargetView(t,rgba);
        if(depthView) context->ClearDepthStencilView(depthView.Get(),D3D11_CLEAR_DEPTH | (desc.depth==SurfaceDepth::Depth24Stencil8 ? D3D11_CLEAR_STENCIL : 0),1,0);
        D3D11_VIEWPORT viewport{0,0,static_cast<float>(desc.width),static_cast<float>(desc.height),0,1}; context->RSSetViewports(1,&viewport);
        inFrame=true; presentable=false; pipelineReady=false; boundTexture={}; return true;
    }
    bool SetFixedPipeline(FixedPipelineState p) override {
        pipelineReady=false;
        if(!Live() || !inFrame || p.topology!=PrimitiveTopology::TriangleList || p.layout!=VertexLayout::ScreenPositionColorUv ||
           p.lighting || p.alphaTest || p.stencilTest || p.cull!=RasterCull::None || p.colorStage!=FixedColorStage::TextureDiffuseModulate ||
           (p.depthCompare!=CompareOp::Always && p.depthCompare!=CompareOp::LessEqual) || (p.depthTest && !depthView) ||
           (p.sampler.min!=SamplerFilter::Point && p.sampler.min!=SamplerFilter::Linear) ||
           (p.sampler.mag!=SamplerFilter::Point && p.sampler.mag!=SamplerFilter::Linear) ||
           (p.sampler.mip!=SamplerFilter::Point && p.sampler.mip!=SamplerFilter::Linear) ||
           (p.sampler.u!=SamplerAddress::Wrap && p.sampler.u!=SamplerAddress::Clamp) ||
           (p.sampler.v!=SamplerAddress::Wrap && p.sampler.v!=SamplerAddress::Clamp)) return false;
        D3D11_SAMPLER_DESC s{};
        s.Filter=static_cast<D3D11_FILTER>((p.sampler.min==SamplerFilter::Linear ? 0x10 : 0) |
            (p.sampler.mag==SamplerFilter::Linear ? 0x4 : 0) | (p.sampler.mip==SamplerFilter::Linear ? 1 : 0));
        s.AddressU=p.sampler.u==SamplerAddress::Clamp ? D3D11_TEXTURE_ADDRESS_CLAMP : D3D11_TEXTURE_ADDRESS_WRAP;
        s.AddressV=p.sampler.v==SamplerAddress::Clamp ? D3D11_TEXTURE_ADDRESS_CLAMP : D3D11_TEXTURE_ADDRESS_WRAP;
        s.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP; s.MaxLOD=D3D11_FLOAT32_MAX; s.ComparisonFunc=D3D11_COMPARISON_NEVER; s.MaxAnisotropy=1;
        D3D11_BLEND_DESC b{}; auto& color=b.RenderTarget[0]; color.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
        color.BlendEnable=p.alphaBlend; color.SrcBlend=D3D11_BLEND_SRC_ALPHA; color.DestBlend=D3D11_BLEND_INV_SRC_ALPHA;
        color.BlendOp=color.BlendOpAlpha=D3D11_BLEND_OP_ADD; color.SrcBlendAlpha=D3D11_BLEND_SRC_ALPHA; color.DestBlendAlpha=D3D11_BLEND_INV_SRC_ALPHA;
        D3D11_DEPTH_STENCIL_DESC d{}; d.DepthEnable=p.depthTest; d.DepthWriteMask=p.depthWrite ? D3D11_DEPTH_WRITE_MASK_ALL : D3D11_DEPTH_WRITE_MASK_ZERO;
        d.DepthFunc=p.depthCompare==CompareOp::Always ? D3D11_COMPARISON_ALWAYS : D3D11_COMPARISON_LESS_EQUAL;
        D3D11_RASTERIZER_DESC r{}; r.FillMode=D3D11_FILL_SOLID; r.CullMode=D3D11_CULL_NONE; r.DepthClipEnable=TRUE;
        sampler.Reset(); blend.Reset(); depthState.Reset(); raster.Reset();
        lastError=native->CreateSamplerState(&s,&sampler);
        if(SUCCEEDED(lastError)) lastError=native->CreateBlendState(&b,&blend);
        if(SUCCEEDED(lastError)) lastError=native->CreateDepthStencilState(&d,&depthState);
        if(SUCCEEDED(lastError)) lastError=native->CreateRasterizerState(&r,&raster);
        if(FAILED(lastError)) return false;
        const float size[]={static_cast<float>(desc.width),static_cast<float>(desc.height),0,0};
        context->UpdateSubresource(constants.Get(),0,nullptr,size,0,0);
        auto* cb=constants.Get(); auto* sampling=sampler.Get(); context->VSSetConstantBuffers(0,1,&cb);
        context->VSSetShader(vs.Get(),nullptr,0); context->PSSetShader(ps.Get(),nullptr,0); context->GSSetShader(nullptr,nullptr,0);
        context->IASetInputLayout(layout.Get()); context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context->PSSetSamplers(0,1,&sampling); context->RSSetState(raster.Get()); context->OMSetDepthStencilState(depthState.Get(),0);
        context->OMSetBlendState(blend.Get(),nullptr,0xffffffff);
        pipelineReady=true; return true;
    }
    bool Draw(NonIndexedDraw command) override {
        auto* r=Find(command.vertices); auto* t=Find(boundTexture);
        if(!Live() || !inFrame || !pipelineReady || !IsCurrentSubmission(Status(),command.submission) || !r || !r->buffer ||
           !t || !t->uploaded || !command.vertexCount || command.vertexCount%3 ||
           command.firstVertex>r->description.size/28 || command.vertexCount>r->description.size/28-command.firstVertex) return false;
        auto* b=r->buffer.Get(); UINT stride=28,offset=0; context->IASetVertexBuffers(0,1,&b,&stride,&offset);
        context->Draw(command.vertexCount,command.firstVertex); return native->GetDeviceRemovedReason()==S_OK;
    }
    bool DrawIndexed(IndexedDraw) override { return false; }
    bool EndFrame() override { if(!inFrame) return false; inFrame=false; presentable=true; return true; }
    bool Present() override {
        if(!Live() || inFrame || !presentable || IsIconic(reinterpret_cast<HWND>(desc.window.handle))) return false;
        presentable=false; lastError=chain->Present(desc.present==PresentMode::VSync ? 1 : 0,0);
        if(FAILED(lastError)) pending=true;
        return SUCCEEDED(lastError);
    }
    bool PrepareForReset() override {
        if(inFrame || pending) return false;
        pending=true; presentable=false; pipelineReady=false; boundTexture={};
        // Unbind before releasing *all* swapchain views, including references
        // kept by the immediate context. CPU/GPU uploads remain retained.
        context->ClearState(); target.Reset(); depthView.Reset(); depth.Reset();
        context->Flush();
        D3D11_QUERY_DESC q{D3D11_QUERY_EVENT,0}; ComPtr<ID3D11Query> fence;
        lastError=native->CreateQuery(&q,&fence);
        if(FAILED(lastError)) return false;
        context->End(fence.Get()); context->Flush();
        const auto deadline=GetTickCount64()+5000;
        do { lastError=context->GetData(fence.Get(),nullptr,0,0); if(lastError!=S_FALSE) break; Sleep(1); } while(GetTickCount64()<deadline);
        if(lastError==S_FALSE) lastError=DXGI_ERROR_WAS_STILL_DRAWING;
        return lastError==S_OK;
    }
    bool RestoreAfterReset() override {
        if(!pending || !target || native->GetDeviceRemovedReason()!=S_OK) return false;
        pending=false; if(++epoch==0) ++epoch; return true;
    }
};
class D3D11Swapchain final : public Swapchain {
    D3D11Device& device; bool retired=false;
public:
    explicit D3D11Swapchain(D3D11Device& d):device(d) {}
    SwapchainDesc Description() const override { return device.desc; }
    std::int64_t LastNativeError() const override { return device.lastError; }
    SwapchainSupport Query(const SwapchainDesc& d) const override {
        SwapchainSupport out;
        if(!ValidSwapchainDesc(d) || d.window.system!=WindowSystem::Win32 || !IsWindow(reinterpret_cast<HWND>(d.window.handle)) ||
           d.window.handle!=device.desc.window.handle || !d.windowed || d.color!=SurfaceColor::Rgba8 || d.samples!=1 || d.quality ||
           d.swap!=SurfaceSwap::Discard || d.width>16384 || d.height>16384 || d.depth==SurfaceDepth::Depth24) return out;
        UINT color=0,depth=0;
        bool ok=SUCCEEDED(device.native->CheckFormatSupport(DXGI_FORMAT_R8G8B8A8_UNORM,&color)) && (color&D3D11_FORMAT_SUPPORT_RENDER_TARGET);
        if(d.depth!=SurfaceDepth::None) ok=ok && SUCCEEDED(device.native->CheckFormatSupport(Depth(d.depth),&depth)) && (depth&D3D11_FORMAT_SUPPORT_DEPTH_STENCIL);
        out.supported=out.resize=out.reset=out.controllerOwnsReset=ok; out.qualityLevels=ok ? 1 : 0; return out;
    }
    SurfaceHealth Health() const override {
        if(retired || device.native->GetDeviceRemovedReason()!=S_OK) return SurfaceHealth::Removed;
        if(IsIconic(reinterpret_cast<HWND>(device.desc.window.handle))) return SurfaceHealth::Suspended;
        return SurfaceHealth::Ready;
    }
    RebuildResult Rebuild(const SwapchainDesc& next,RebuildReason reason) override {
        if(retired) return RebuildResult::ReplacementRequired;
        if(reason==RebuildReason::DeviceReplacement) return Retire() ? RebuildResult::ReplacementRequired : RebuildResult::Busy;
        if(device.native->GetDeviceRemovedReason()!=S_OK) { device.pending=true; return RebuildResult::ReplacementRequired; }
        if(!ValidSwapchainDesc(next)) return RebuildResult::Invalid;
        if(!Query(next).supported) return RebuildResult::Unsupported;
        if(reason!=RebuildReason::Resize) return RebuildResult::Unsupported;
        if(Health()==SurfaceHealth::Suspended) return RebuildResult::RetryLater;
        if(device.inFrame) return RebuildResult::Busy;
        if(!device.pending && !device.PrepareForReset()) return RebuildResult::Failed;
        // Retry also releases partially restored views from a failed attempt.
        device.target.Reset(); device.depthView.Reset(); device.depth.Reset();
        device.lastError=device.chain->ResizeBuffers(1,next.width,next.height,DXGI_FORMAT_R8G8B8A8_UNORM,0);
        if(FAILED(device.lastError)) return device.native->GetDeviceRemovedReason()==S_OK ? RebuildResult::Failed : RebuildResult::ReplacementRequired;
        const auto previous=device.desc; device.desc=next;
        if(!device.CreateTargets() || !device.RestoreAfterReset()) { device.desc=previous; return RebuildResult::Failed; }
        return RebuildResult::Success;
    }
    bool Retire() override {
        if(retired) return true;
        if(device.inFrame) return false;
        if(device.native->GetDeviceRemovedReason()!=S_OK) {
            device.pending=true; device.context->ClearState();
            device.target.Reset(); device.depthView.Reset(); device.depth.Reset();
            retired=true; return true;
        }
        if(!device.pending && !device.PrepareForReset()) return false;
        retired=true; return true;
    }
};
}
D3D11Bundle CreateD3D11Device(const SwapchainDesc& d,D3D11Driver driver) {
    D3D11Bundle out;
    if(!ValidSwapchainDesc(d) || d.window.system!=WindowSystem::Win32 || !d.windowed || !IsWindow(reinterpret_cast<HWND>(d.window.handle)) ||
       d.color!=SurfaceColor::Rgba8 || d.samples!=1 || d.quality || d.swap!=SurfaceSwap::Discard || d.depth==SurfaceDepth::Depth24 ||
       d.width>16384 || d.height>16384 || (driver!=D3D11Driver::Hardware && driver!=D3D11Driver::Warp)) { out.creationError=E_INVALIDARG; return out; }
    auto device=std::make_unique<D3D11Device>(); device->desc=d;
    DXGI_SWAP_CHAIN_DESC swap{}; swap.BufferDesc.Width=d.width; swap.BufferDesc.Height=d.height; swap.BufferDesc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
    swap.SampleDesc.Count=1; swap.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT; swap.BufferCount=1;
    swap.OutputWindow=reinterpret_cast<HWND>(d.window.handle); swap.Windowed=TRUE; swap.SwapEffect=DXGI_SWAP_EFFECT_DISCARD;
    const D3D_FEATURE_LEVEL levels[]={D3D_FEATURE_LEVEL_11_0}; D3D_FEATURE_LEVEL obtained{};
    out.stage=D3D11CreationStage::NativeDevice;
    device->lastError=D3D11CreateDeviceAndSwapChain(nullptr,driver==D3D11Driver::Warp ? D3D_DRIVER_TYPE_WARP : D3D_DRIVER_TYPE_HARDWARE,
        nullptr,0,levels,1,D3D11_SDK_VERSION,&swap,&device->chain,&device->native,&obtained,&device->context);
    if(SUCCEEDED(device->lastError)) {
        ComPtr<IDXGIDevice> dxgi; ComPtr<IDXGIAdapter> adapter; ComPtr<IDXGIFactory> factory;
        if(SUCCEEDED(device->native.As(&dxgi)) && SUCCEEDED(dxgi->GetAdapter(&adapter))) {
            DXGI_ADAPTER_DESC info{};
            if(SUCCEEDED(adapter->GetDesc(&info))) {
                out.vendorId=info.VendorId; out.deviceId=info.DeviceId;
                char name[512]{}; WideCharToMultiByte(CP_UTF8,0,info.Description,-1,name,sizeof(name),nullptr,nullptr);
                out.adapterName=name;
            }
            if(SUCCEEDED(adapter->GetParent(IID_PPV_ARGS(&factory)))) factory->MakeWindowAssociation(swap.OutputWindow,DXGI_MWA_NO_ALT_ENTER);
        }
        out.stage=D3D11CreationStage::Shaders;
        if(device->InitializeShaders()) { out.stage=D3D11CreationStage::Targets; device->CreateTargets(); }
    }
    out.creationError=device->lastError;
    if(FAILED(device->lastError)) return out;
    auto controller=std::make_unique<D3D11Swapchain>(*device);
    if(!controller->Query(d).supported) { out.creationError=DXGI_ERROR_UNSUPPORTED; return out; }
    out.stage=D3D11CreationStage::Ready;
    out.device=std::move(device); out.swapchain=std::move(controller); return out;
}
bool AcquireD3D11Backbuffer(Device& base,ID3D11Texture2D** output) {
    if(!output) return false; *output=nullptr;
    auto* d=dynamic_cast<D3D11Device*>(&base);
    return d && d->Live() && !d->inFrame && SUCCEEDED(d->chain->GetBuffer(0,IID_PPV_ARGS(output)));
}
bool ReadD3D11Swapchain(Device& base,RgbaImage& image) {
    image={}; auto* d=dynamic_cast<D3D11Device*>(&base);
    if(!d || !d->Live() || d->inFrame) return false;
    ComPtr<ID3D11Texture2D> back,cpu;
    d->lastError=d->chain->GetBuffer(0,IID_PPV_ARGS(&back)); if(FAILED(d->lastError)) return false;
    D3D11_TEXTURE2D_DESC desc{}; back->GetDesc(&desc);
    if(desc.SampleDesc.Count!=1 || desc.Format!=DXGI_FORMAT_R8G8B8A8_UNORM) return false;
    desc.Usage=D3D11_USAGE_STAGING; desc.BindFlags=0; desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ; desc.MiscFlags=0;
    d->lastError=d->native->CreateTexture2D(&desc,nullptr,&cpu); if(FAILED(d->lastError)) return false;
    d->context->CopyResource(cpu.Get(),back.Get()); D3D11_MAPPED_SUBRESOURCE data{};
    d->lastError=d->context->Map(cpu.Get(),0,D3D11_MAP_READ,0,&data); if(FAILED(d->lastError)) return false;
    image.width=desc.Width; image.height=desc.Height; image.pixels.resize(static_cast<std::size_t>(desc.Width)*desc.Height*4);
    for(UINT y=0;y<desc.Height;++y) std::memcpy(image.pixels.data()+static_cast<std::size_t>(y)*desc.Width*4,
        static_cast<const std::uint8_t*>(data.pData)+static_cast<std::size_t>(y)*data.RowPitch,desc.Width*4);
    d->context->Unmap(cpu.Get(),0); return true;
}
}
