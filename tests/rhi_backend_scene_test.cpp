#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <dxgi.h>
#include "mikudancestudio/rhi_d3d11.hpp"
#include "mikudancestudio/rhi_d3d12.hpp"
#include "mikudancestudio/rhi_scene_renderer.hpp"
#include "mikudancestudio/render_model_geometry.hpp"
#include "mikudancestudio/render_model_inputs.hpp"
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <map>
using namespace mikudancestudio::rhi;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
struct Window {HWND value=CreateWindowExW(0,L"STATIC",L"RHI backend scene",WS_OVERLAPPEDWINDOW,0,0,128,128,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);~Window(){if(value)DestroyWindow(value);}};
struct Vertex {float x,y,z,nx,ny,nz,u,v;};
const Vertex vertices[]={{-.8f,.8f,.3f,0,0,-1,0,0},{.8f,.8f,.3f,0,0,-1,1,0},{-.8f,-.8f,.3f,0,0,-1,0,1}};
ModelPipeline Pipeline() {
    ModelPipeline p;p.raster.alphaBlend=false;p.raster.cull=BatchCull::None;
    for(auto* m:{&p.shader.world,&p.shader.view,&p.shader.projection,&p.shader.normalView})*m={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    p.shader.nativeDiffuse={1,1,1,1};p.shader.diffuse={1,1,1,1};
    auto& stage=p.shader.layout.stages[0];stage.role=MaterialTextureRole::Base;stage.color=MaterialCombine::Modulate;stage.colorArg2=MaterialColorSource::LitDiffuse;
    p.shader.samplers[0]={SamplerFilter::Point,SamplerFilter::Point,SamplerFilter::Point,SamplerAddress::Clamp,SamplerAddress::Clamp,1};return p;
}
ModelReplayStream Fixture(unsigned version=1) {
    ModelReplayStream s;s.complete=true;s.target.width=s.target.height=64;s.clear={0,0,0,1};
    ModelReplayResource v;v.key={1,1};v.bytes.resize(sizeof(vertices));std::memcpy(v.bytes.data(),vertices,sizeof(vertices));s.resources.push_back(v);
    ModelReplayResource i;i.key={3,1};i.kind=ReplayResourceKind::Indices;i.bytes={0,0,1,0,2,0};s.resources.push_back(i);
    ModelReplayResource t;t.key={4,version};t.kind=ReplayResourceKind::Texture;
    RgbaImage top{2,2,{}};for(unsigned n=0;n<4;++n)top.pixels.insert(top.pixels.end(),{static_cast<unsigned char>(version==1?41:73),151,223,255});
    PreparedMipChain chain;PreparePortableMipChain(top,MipPreparationPolicy::BoxLinear,chain);t.texture.levels=std::move(chain.levels);s.resources.push_back(t);
    s.events.push_back({1,ModelReplayOp::Clear});for(const auto& r:s.resources){ModelReplayEvent e;e.sequence=s.events.size()+1;e.op=ModelReplayOp::PublishResource;e.resource=r.key;s.events.push_back(e);}
    ModelReplayEvent e;e.sequence=5;e.op=ModelReplayOp::Draw;e.draw.pipeline=Pipeline();e.draw.vertices={1,1};e.draw.indices={3,1};e.draw.textures[0]=t.key;e.draw.vertexCount=e.draw.indexCount=3;s.events.push_back(e);return s;
}
ModelReplayStream CpuFixture(const mikudancestudio::render::ModelGeometry& geometry,bool specular=false) {
    auto s=Fixture(2);const auto texture=s.resources.back();s.resources={texture};s.events.resize(1);
    ModelReplayEvent publish;publish.sequence=2;publish.op=ModelReplayOp::PublishResource;publish.resource=texture.key;s.events.push_back(publish);
    ModelReplayDraw draw;draw.textures[0]=texture.key;draw.indexCount=3;
    // This path builds every shader input from a portable scene + CPU material,
    // unlike the simple identity baseline above. The same inputs survive
    // repeated offscreen resize, cache reuse, replacement and device removal.
    using namespace mikudancestudio::render;
    ModelFrameInputs frame;frame.scene.camera.parentModel=-1;frame.scene.camera.distance=-3;frame.scene.camera.fov=60;
    frame.scene.lightState={.4f,.5f,.6f,0,-1,0};frame.view.viewport={0,0,64,64,0,1};
    frame.world=frame.lightRotation={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    ModelMaterialInputs material;material.diffuse=material.ambient={1,1,1,1};
    if(!BuildModelInputs(frame,material,{},draw.pipeline))return {};
    if(specular){auto& shader=draw.pipeline.shader;shader.specularEnabled=true;shader.localViewer=true;
        shader.materialSpecular={.2f,.3f,.4f,1};shader.shininess=1.7f;shader.lights[0].direction={.27f,-.43f,.61f};}
    if(!mikudancestudio::render::AppendModelGeometry(s,geometry.Snapshot(),draw))return {};
    return s;
}
// Independent native submission is the reference, with the same CPU packets
// but no replay builder or SceneRenderer commands. Every prefix is checked.
int VerifyMaterialSwitches(Device& device) {
    using namespace mikudancestudio::render;
    ModelGeometry geometry(100,3);std::memcpy(geometry.MainData(),vertices,sizeof(vertices));
    const std::uint16_t index[]={0,1,2,0,1,2,0,1,2,0,1,2};
    CHECK(geometry.SetIndices(IndexFormat::UInt16,index,sizeof(index)) && geometry.Publish());
    ModelMaterialPacket a;a.material=1;a.indexCount=3;a.pipeline=Pipeline();
    a.pipeline.raster.depthTest=a.pipeline.raster.depthWrite=true;a.pipeline.raster.depthCompare=DepthComparison::LessEqual;
    a.textures[0].identity="control-a";a.textures[0].content={RgbaImage{1,1,{41,151,223,255}},1};
    auto b=a;b.material=2;b.firstIndex=3;b.textures[0].identity="control-b";b.textures[0].content.image.pixels={201,51,23,255};
    b.pipeline.shader.nativeDiffuse[3]=b.pipeline.shader.diffuse[3]=.5f;
    b.pipeline.raster.alphaBlend=true;b.pipeline.raster.sourceBlend=BlendFactor::SourceAlpha;b.pipeline.raster.destinationBlend=BlendFactor::InvSourceAlpha;
    b.pipeline.raster.depthWrite=false;
    auto c=a;c.material=3;c.firstIndex=6;c.pipeline.raster.depthCompare=DepthComparison::Less;
    auto d=a;d.material=4;d.firstIndex=9;d.pipeline.raster.depthTest=d.pipeline.raster.depthWrite=false;d.pipeline.shader.layout={};d.textures={};
    const std::vector<ModelMaterialPacket> packets={a,b,c,d};HistoryDesc target;target.width=target.height=64;
    ModelSubmissionBuilder builder;ModelReplayStream stream;CHECK(builder.Build(geometry.Snapshot(),target,{0,0,0,1},packets,stream));
    CHECK(stream.resources.size()==4);std::map<std::uint64_t,Handle> handles;
    for(const auto& resource:stream.resources){Handle handle;
        if(resource.kind==ReplayResourceKind::Texture)handle=device.CreateModelTexture(resource.texture);
        else {BufferDesc desc{resource.kind==ReplayResourceKind::Vertices?BufferUsage::Vertex:BufferUsage::Index,resource.bytes.size()};desc.indexFormat=resource.indexFormat;handle=device.CreateBuffer(desc,resource.bytes.data());}
        CHECK(handle);handles.emplace(resource.key.id,handle);
    }
    SceneRenderer renderer(device);RgbaImage previous;unsigned boundary=0;
    for(std::size_t e=0;e<stream.events.size();++e)if(stream.events[e].op==ModelReplayOp::Draw){
        auto prefix=stream;prefix.events.resize(e+1);PreparedModelFrame prepared;CompletionToken token;
        CHECK(renderer.Prepare(77,prefix,prepared) && renderer.Submit(prepared,token));RgbaImage image;CHECK(device.ReadModelTarget(image));
        CHECK(device.EnsureModelTarget(target) && device.BeginFrame({0,0,0,1}));
        for(unsigned draw=0;draw<=boundary;++draw){const auto& packet=packets[draw];CHECK(device.SetModelPipeline(packet.pipeline));
            // Resource bindings are read from immutable CPU versions, never
            // from native device state. Inactive stages deliberately stay bound.
            unsigned ordinal=0;const ModelReplayDraw* contract=nullptr;
            for(const auto& event:stream.events)if(event.op==ModelReplayOp::Draw && ordinal++==draw){contract=&event.draw;break;}
            CHECK(contract);for(unsigned stage=0;stage<3;++stage)if(contract->textures[stage].id)CHECK(device.BindTexture(stage,handles.at(contract->textures[stage].id)));
            IndexedDraw command;command.vertices=handles.at(geometry.Snapshot().main.key.id);command.indices=handles.at(geometry.Snapshot().indices.key.id);
            command.firstIndex=packet.firstIndex;command.indexCount=packet.indexCount;command.vertexCount=3;command.layout=VertexLayout::PositionNormalUv;
            CHECK(device.DrawIndexed(device.Record(command)));
        }
        CHECK(device.EndFrame());const auto completion=device.SignalCompletion();CHECK(completion && device.WaitCompletion(completion,5000));
        RgbaImage manual;CHECK(device.ReadModelTarget(manual) && manual.pixels==image.pixels);
        const auto pixel=image.pixels.data()+(16*64+16)*4;
        if(boundary==0)CHECK(pixel[0]==41 && pixel[1]==151 && pixel[2]==223);
        if(boundary==1)CHECK(image.pixels!=previous.pixels && pixel[0]>41 && pixel[0]<201 && pixel[1]<151);
        if(boundary==2)CHECK(image.pixels==previous.pixels); // equal depth must fail Less
        if(boundary==3)CHECK(pixel[0]==255 && pixel[1]==255 && pixel[2]==255); // disabled sampling ignores stale SRV
        previous=std::move(image);++boundary;
    }
    CHECK(boundary==4 && renderer.Stats().textureUploads==2);
    CHECK(renderer.Detach());for(const auto& handle:handles)CHECK(device.Destroy(handle.second));
    std::puts("CPU ordered materials: shared uploads, opaque/blended/depth-rejected/untextured prefixes match independent native commands");return 0;
}
bool SolidPixel(const RgbaImage& image,unsigned x,unsigned y,unsigned char red) {
    const auto* pixel=image.pixels.data()+(SIZE_T(y)*image.width+x)*4;return pixel[0]==red && pixel[1]==151 && pixel[2]==223 && pixel[3]==255;
}
int main(int argc,char** argv) {
    std::setvbuf(stdout,nullptr,_IONBF,0);
    const bool dx12=argc>1 && std::string(argv[1]).find("dx12")!=std::string::npos;
    const bool warp=argc>1 && std::string(argv[1]).find("warp")!=std::string::npos;
    const bool debug=argc>1 && std::string(argv[1]).find("debug")!=std::string::npos;
    const bool specular=argc>1 && std::string(argv[1]).find("specular")!=std::string::npos;
    const ModelOptions options=specular?ModelOptions{ModelCompatibility::Dx9Measured,true,true,true}:ModelOptions{};
    Window window;CHECK(window.value);SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window.value)};desc.width=desc.height=64;desc.present=PresentMode::Immediate;
    D3D11Bundle eleven;D3D12Bundle twelve;
    if(dx12)twelve=CreateD3D12Device(desc,warp?D3D12Driver::Warp:D3D12Driver::Hardware,{options,debug});
    else eleven=CreateD3D11Device(desc,warp?D3D11Driver::Warp:D3D11Driver::Hardware,options);
    if(!(dx12?bool(twelve):bool(eleven))){const auto hr=static_cast<HRESULT>(dx12?twelve.creationError:eleven.creationError);
        const bool nativeStage=dx12?twelve.stage==D3D12CreationStage::NativeDevice:eleven.stage==D3D11CreationStage::NativeDevice;
        const bool unavailable=(debug && twelve.creationReason=="debug_layer_unavailable") || (nativeStage && (hr==DXGI_ERROR_UNSUPPORTED || hr==DXGI_ERROR_NOT_CURRENTLY_AVAILABLE || hr==DXGI_ERROR_DEVICE_REMOVED || hr==DXGI_ERROR_DEVICE_RESET));
        std::fprintf(stderr,"%s hr=%llx reason=%s\n",unavailable?"UNAVAILABLE":"FAIL",static_cast<unsigned long long>(dx12?twelve.creationError:eleven.creationError),(dx12?twelve.creationReason:eleven.creationReason).c_str());return unavailable?77:1;}
    auto& device=dx12?*twelve.device:*eleven.device;auto& chain=dx12?*twelve.swapchain:*eleven.swapchain;
    CHECK(device.ModelFeatures().presentation && device.ModelFeatures().offscreen && device.ModelFeatures().explicitMips);
    std::printf("backend=%s driver=%s adapter=%s debug=%d\n",dx12?"dx12":"dx11",warp?"warp":"hardware",(dx12?twelve.adapterName:eleven.adapterName).c_str(),debug);
    CHECK(chain.Query(desc).supported && device.Status().state==DeviceState::Ready);
    auto unsupported=desc;unsupported.samples=8;CHECK(!chain.Query(unsupported).supported && chain.Rebuild(unsupported,RebuildReason::Resize)==RebuildResult::Unsupported);
    CHECK(VerifyMaterialSwitches(device)==0);
    const auto cancelled=device.CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices);CHECK(cancelled && device.Destroy(cancelled));
    const auto vb=device.CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices);CHECK(vb);
    ModelTextureData texture;texture.levels.push_back({1,1,{41,151,223,255}});const auto th=device.CreateModelTexture(texture);CHECK(th);
    NonIndexedDraw command{vb,0,3};command.layout=VertexLayout::PositionNormalUv;
    for(unsigned n=0;n<12;++n) {
        auto stale=device.Record(command);desc.width=64+(n%4)*8;desc.height=64+(n%3)*8;const auto epoch=device.Status().epoch;
        CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success && device.Status().epoch==epoch+1);
        CHECK(device.BeginFrame({0,0,0,1}) && device.SetModelPipeline(Pipeline()) && device.BindTexture(0,th));
        auto dead=command;dead.vertices=cancelled;CHECK(!device.Draw(device.Record(dead)) && !device.Draw(stale));CHECK(device.Draw(device.Record(command)) && device.EndFrame());
        RgbaImage image;CHECK(dx12?ReadD3D12Swapchain(device,image):ReadD3D11Swapchain(device,image));CHECK(SolidPixel(image,16,16,41));CHECK(device.Present());
    }
    std::puts("swapchain resize done");
    ShowWindow(window.value,SW_MINIMIZE);CHECK(chain.Health()==SurfaceHealth::Suspended && !device.BeginFrame({}));CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::RetryLater);
    ShowWindow(window.value,SW_RESTORE);CHECK(chain.Health()==SurfaceHealth::Ready && chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success);ShowWindow(window.value,SW_HIDE);
    struct ScreenVertex {float x,y,z,rhw;unsigned color;float u,v;};
    const ScreenVertex quad[]={{8,8,.5f,1,0xffff8040,0,0},{8,32,.5f,1,0xffff8040,0,1},{32,8,.5f,1,0xffff8040,1,0},
        {32,8,.5f,1,0xffff8040,1,0},{8,32,.5f,1,0xffff8040,0,1},{32,32,.5f,1,0xffff8040,1,1}};
    const auto screenBuffer=device.CreateBuffer({BufferUsage::Vertex,sizeof(quad)},quad);CHECK(screenBuffer);
    FixedPipelineState hud;hud.layout=VertexLayout::ScreenPositionColorUv;hud.topology=PrimitiveTopology::TriangleList;hud.colorStage=FixedColorStage::TextureDiffuseModulate;
    hud.alphaBlend=false;hud.sampler={SamplerFilter::Point,SamplerFilter::Point,SamplerFilter::Point,SamplerAddress::Clamp,SamplerAddress::Clamp,1};
    NonIndexedDraw screenDraw{screenBuffer,0,6};screenDraw.layout=VertexLayout::ScreenPositionColorUv;
    CHECK(device.BeginFrame({0,0,0,1}) && device.SetModelPipeline(Pipeline()) && device.BindTexture(0,th) && device.Draw(device.Record(command)));
    CHECK(device.SetFixedPipeline(hud) && !device.Draw(device.Record(screenDraw)) && !device.BindTexture(1,th));CHECK(device.BindTexture(0,th) && device.Draw(device.Record(screenDraw)) && device.EndFrame());
    RgbaImage hudImage;CHECK(dx12?ReadD3D12Swapchain(device,hudImage):ReadD3D11Swapchain(device,hudImage));const unsigned char color[]={41,76,56,255};CHECK(std::memcmp(hudImage.pixels.data()+(SIZE_T(16)*hudImage.width+16)*4,color,4)==0);CHECK(device.Present());
    CHECK(device.BeginFrame({0,0,0,1}) && device.SetFixedPipeline(hud) && device.BindTexture(0,th) && device.Draw(device.Record(screenDraw)));
    CHECK(device.SetModelPipeline(Pipeline()) && !device.Draw(device.Record(command)) && device.BindTexture(0,th) && device.Draw(device.Record(command)) && device.EndFrame());
    CHECK(dx12?ReadD3D12Swapchain(device,hudImage):ReadD3D11Swapchain(device,hudImage));CHECK(SolidPixel(hudImage,16,16,41) && device.Present());CHECK(device.Destroy(screenBuffer));
    CHECK(device.Destroy(vb) && device.Destroy(th));
    if(specular){const auto support=dx12?twelve.modelSupport:QueryD3D11ModelSupport(device,ModelCompatibility::Dx9Measured);
        CHECK(support.diagnosticSpecularFma && support.diagnosticAlpha12 && support.diagnosticTextureFma);}
    Window replacementWindow,recoveryWindow;D3D11Bundle newEleven;D3D12Bundle newTwelve,recovery;
    std::puts("minimize done");SceneRenderer renderer(device);PreparedModelFrame frame;const auto stream=Fixture();
    if(dx12){auto unsupportedStream=stream;unsupportedStream.resources[2].texture.levels.resize(1);unsupportedStream.resources[2].texture.generateMips=true;const auto before=device.Status().epoch;
        CHECK(renderer.Prepare(1,unsupportedStream,frame).reason=="unsupported_texture_contract" && device.Status().epoch==before && renderer.Stats().uploads==0);}
    desc.width=desc.height=64;CHECK(chain.Rebuild(desc,RebuildReason::Resize)==RebuildResult::Success);
    CHECK(renderer.Prepare(1,stream,frame,FrameOutput::Presentation));CompletionToken completion;CHECK(renderer.Submit(frame,completion));
    RgbaImage presented;CHECK(dx12?ReadD3D12Swapchain(device,presented):ReadD3D11Swapchain(device,presented));CHECK(SolidPixel(presented,16,16,41) && device.Present());
    CHECK(renderer.Prepare(1,stream,frame));for(unsigned n=0;n<1000;++n)CHECK(renderer.Submit(frame,completion));CHECK(device.WaitCompletion(completion,5000));
    CHECK(renderer.Stats().uploads==3 && renderer.Stats().submissions==1001);
    std::puts("1000 submissions done");RgbaImage reference;CHECK(device.ReadModelTarget(reference) && SolidPixel(reference,16,16,41));
    PreparedModelFrame changed;CHECK(renderer.Prepare(1,Fixture(2),changed));CHECK(renderer.Stats().uploads==4);CHECK(!renderer.Submit(frame,completion));
    CHECK(renderer.Submit(changed,completion));RgbaImage edited;CHECK(device.ReadModelTarget(edited) && SolidPixel(edited,16,16,73));
    for(unsigned n=0;n<8;++n){auto resized=Fixture(2);resized.target.width=64+(n%2)*16;PreparedModelFrame larger;CHECK(renderer.Prepare(1,resized,larger));
        CHECK(!renderer.Submit(changed,completion));CHECK(renderer.Submit(larger,completion));RgbaImage image;CHECK(device.ReadModelTarget(image) && SolidPixel(image,16,16,73));}
    CHECK(renderer.Stats().uploads==4);
    mikudancestudio::render::ModelGeometry geometry(1,3);
    const std::uint16_t cpuIndices[]={0,1,2};
    CHECK(geometry.SetIndices(IndexFormat::UInt16,cpuIndices,sizeof(cpuIndices)));
    std::memcpy(geometry.MainData(),vertices,sizeof(vertices));CHECK(geometry.Publish());
    std::size_t peakRetired=0;
    for(unsigned n=0;n<1000;++n){auto moved=vertices[0];moved.x+=((n+1)&1)*.02f;
        std::memcpy(geometry.MainData(),&moved,sizeof(moved));CHECK(geometry.Publish());
        CHECK(geometry.Snapshot().main.key.version==n+2);
        auto animated=CpuFixture(geometry,specular);PreparedModelFrame pose;
        CHECK(renderer.Prepare(1,animated,pose) && renderer.Submit(pose,completion));peakRetired=std::max(peakRetired,renderer.Stats().retiringResources);}
    CHECK(device.WaitCompletion(completion,5000) && renderer.Collect());CHECK(renderer.Stats().residentResources==3 && renderer.Stats().retiringResources==0);
    CHECK(renderer.Stats().uploads==1004 && renderer.Stats().textureUploads==2 && peakRetired<=4);
    CHECK(renderer.Prepare(1,CpuFixture(geometry,specular),changed) && renderer.Submit(changed,completion));
    // Rebuild targets with generated camera/light/material inputs as well.
    for(unsigned n=0;n<8;++n){auto resize=CpuFixture(geometry,specular);resize.target.width=64+(n%2)*16;
        resize.events.back().draw.pipeline.viewport->width=resize.target.width;
        PreparedModelFrame resized;CHECK(renderer.Prepare(1,resize,resized) && renderer.Submit(resized,completion));
        CHECK(!renderer.Submit(changed,completion));changed=std::move(resized);}
    CHECK(renderer.Prepare(1,CpuFixture(geometry,specular),changed) && renderer.Submit(changed,completion));
    CHECK(renderer.Stats().uploads==1004);
    RgbaImage finalImage;CHECK(device.ReadModelTarget(finalImage));
    std::size_t visible=0;for(std::size_t i=0;i<finalImage.pixels.size();i+=4)visible+=finalImage.pixels[i] || finalImage.pixels[i+1] || finalImage.pixels[i+2];CHECK(visible>0);
    std::printf("1000 geometry versions: peak retiring=%zu textureUploads=2\n",peakRetired);
    // Device identity differs while the CPU scene and version keys stay intact.
    CHECK(replacementWindow.value);auto replacementDesc=desc;replacementDesc.window.handle=reinterpret_cast<std::uintptr_t>(replacementWindow.value);
    newEleven=dx12?D3D11Bundle{}:CreateD3D11Device(replacementDesc,warp?D3D11Driver::Warp:D3D11Driver::Hardware,options);
    newTwelve=dx12?CreateD3D12Device(replacementDesc,warp?D3D12Driver::Warp:D3D12Driver::Hardware,{options,debug}):D3D12Bundle{};
    CHECK(dx12?bool(newTwelve):bool(newEleven));auto& newDevice=dx12?*newTwelve.device:*newEleven.device;
    CHECK(newDevice.Status().identity!=device.Status().identity && renderer.Rebind(newDevice));CHECK(chain.Retire() && !device.BeginFrame({}));
    CHECK(!renderer.Submit(changed,completion));
    auto finalPose=CpuFixture(geometry,specular);
    if(specular)CHECK((dx12?newTwelve.modelSupport:newEleven.modelSupport).diagnosticSpecularFma);
    CHECK(renderer.Prepare(1,finalPose,changed) && renderer.Stats().uploads==1007);CHECK(renderer.Submit(changed,completion));RgbaImage restored;CHECK(newDevice.ReadModelTarget(restored) && restored.pixels==finalImage.pixels);
    CHECK(newDevice.WaitCompletion(completion,5000));CHECK(renderer.Unload(1) && renderer.Stats().residentResources==0 && renderer.Stats().retiringResources==0);
    if(dx12){CHECK(QueryD3D12Stats(device).debugErrors==0 && QueryD3D12Stats(newDevice).debugErrors==0);
        const auto stats=QueryD3D12Stats(device);std::printf("submissions=%llu pipelines=%llu uploads=%llu errors=%u\n",stats.submissions,stats.pipelineCreations,stats.resourceUploads,stats.debugErrors);}
    if(dx12){CHECK(renderer.Prepare(1,finalPose,changed));for(unsigned n=0;n<3;++n)CHECK(renderer.Submit(changed,completion));
        CHECK(RemoveD3D12DeviceForTest(newDevice) && newDevice.Status().state==DeviceState::Removed && !newDevice.BeginFrame({}));
        CHECK(newDevice.PollCompletion(completion)==CompletionState::DeviceLost);
        CHECK(renderer.Detach() && renderer.Submit(changed,completion).reason=="device_not_bound");CHECK(newTwelve.swapchain->Retire());
        // D3D12CreateDevice reuses the existing native device on an adapter.
        // Release every reference to that removed object before recreation.
        newTwelve.swapchain.reset();newTwelve.device.reset();twelve.swapchain.reset();twelve.device.reset();
        CHECK(recoveryWindow.value);auto recoveryDesc=desc;recoveryDesc.window.handle=reinterpret_cast<std::uintptr_t>(recoveryWindow.value);
        recovery=CreateD3D12Device(recoveryDesc,warp?D3D12Driver::Warp:D3D12Driver::Hardware,{options,debug});
        if(!recovery)std::fprintf(stderr,"recovery failed stage=%u hr=%llx reason=%s\n",unsigned(recovery.stage),recovery.creationError,recovery.creationReason.c_str());CHECK(recovery);
        if(specular)CHECK(recovery.modelSupport.diagnosticSpecularFma);
        CHECK(renderer.Rebind(*recovery.device));CHECK(!renderer.Submit(changed,completion));
        CHECK(renderer.Prepare(1,finalPose,changed) && renderer.Submit(changed,completion));RgbaImage image;CHECK(recovery.device->ReadModelTarget(image) && image.pixels==finalImage.pixels);
        CHECK(renderer.Unload(1) && renderer.Detach());CHECK(QueryD3D12Stats(*recovery.device).debugErrors==0);std::puts("native isolated device removal and CPU scene recovery passed");}
    std::puts("12 swapchain rebuilds, minimize, 1000 resident frames, version update, 8 targets, device replacement: passed");
    // renderer must die before its rebound device, which was created later.
    CHECK(renderer.Detach());return 0;
}
