#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <dxgi.h>
#include "mikudancestudio/rhi_d3d11.hpp"
#include <algorithm>
#include <array>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <cstring>
using namespace mikudancestudio::rhi;
#define CHECK(x) do { if(!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); return 1; } } while(0)
using Color=std::array<unsigned char,4>;
struct Vertex { float x,y,z,nx,ny,nz,u,v; };
struct Batch {
    const char* name; int left,top,right,bottom; float z;
    ModelPipeline pipeline;
    std::array<int,3> textures{{-1,-1,-1}};
    Color expected; // Independently specified flat shader output, not evaluated via RHI code.
    float u=.5f;
};
ModelPipeline Base() {
    ModelPipeline p; p.raster.alphaBlend=false; p.raster.cull=BatchCull::None;
    for(auto* m:{&p.shader.world,&p.shader.view,&p.shader.projection,&p.shader.normalView})
        *m={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    p.shader.nativeDiffuse={1,1,1,1};
    for(auto& s:p.shader.samplers) s.min=s.mag=s.mip=SamplerFilter::Point;
    return p;
}
void Stage(Batch& b,unsigned slot,MaterialTextureRole role,int texture,MaterialCombine op=MaterialCombine::Modulate) {
    auto& s=b.pipeline.shader.layout.stages[slot]; s.role=role; s.color=op;
    s.colorArg2=slot?MaterialColorSource::Previous:MaterialColorSource::LitDiffuse;
    b.textures[slot]=texture;
}
// CPU oracle only implements this fixture's axis-aligned, flat-color operations.
// Pixel coverage is deliberately away from edges; no GPU interpolation model is fitted.
RgbaImage Expected(unsigned size,const std::vector<Batch>& batches,unsigned count) {
    RgbaImage image{size,size,std::vector<std::uint8_t>(size*size*4,0)};
    std::vector<float> depth(size*size,1); std::vector<unsigned> stencil(size*size,0);
    for(unsigned i=0;i<size*size;++i) image.pixels[i*4+3]=255;
    for(unsigned n=0;n<count;++n) {
        const auto& b=batches[n]; const auto& p=b.pipeline;
        for(int y=b.top;y<b.bottom;++y) for(int x=b.left;x<b.right;++x) {
            const auto i=y*size+x;
            if(p.shader.alphaTest && b.expected[3]<=p.shader.alphaReference) continue;
            if(p.stencil && p.stencilCompare==DepthComparison::Equal && stencil[i]!=p.stencilReference) continue;
            if(p.raster.depthTest && b.z>depth[i]) continue;
            if(p.stencil && p.stencilPass==ModelStencilOp::Replace) stencil[i]=p.stencilReference;
            if(p.raster.depthTest && p.raster.depthWrite) depth[i]=b.z;
            for(unsigned c=0;c<4;++c) if(p.colorWriteMask&(1u<<c)) {
                auto& dst=image.pixels[i*4+c];
                if(!p.raster.alphaBlend) dst=b.expected[c];
                else if(c<3) dst=static_cast<unsigned char>((b.expected[c]*b.expected[3]+dst*(255-b.expected[3])+127)/255);
                // Separate alpha preserves the destination in this fixture.
            }
        }
    }
    return image;
}
int main(int argc,char** argv) {
    const bool hardware=argc>1 && std::string(argv[1])=="--hardware";
    const std::filesystem::path directory=argc>2?argv[2]:"dx11-multimaterial-evidence";
    std::filesystem::create_directories(directory);
    std::ofstream report(directory/(hardware?"hardware.log":"warp.log"));
    struct Window { HWND h; ~Window(){if(h)DestroyWindow(h);} } window{
        CreateWindowExW(0,L"STATIC",L"DX11 multiple materials",WS_POPUP,0,0,80,80,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};
    CHECK(window.h);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window.h)};
    desc.width=desc.height=64;desc.present=PresentMode::Immediate;
    const std::vector<Color> colors={{255,0,0,255},{0,255,0,255},{0,0,255,128},
        {255,255,0,255},{0,255,255,255},{255,255,255,255},{0,0,255,255},{0,0,0,255}};
    std::vector<Batch> batches;
    auto add=[&](const char* name,int l,int t,int r,int b,float z,int texture) -> Batch& {
        batches.push_back({name,l,t,r,b,z,Base(),{{-1,-1,-1}},colors[texture]});
        Stage(batches.back(),0,MaterialTextureRole::Base,texture);return batches.back();
    };
    add("opaque-base",8,8,56,56,.6f,0);
    add("occluded-green",12,12,52,52,.8f,1);
    auto& transparent=add("transparent-no-depth-write",8,8,32,56,.4f,2);
    transparent.pipeline.raster.alphaBlend=true;transparent.pipeline.raster.depthWrite=false;
    transparent.pipeline.separateAlpha=true;transparent.pipeline.sourceAlpha=BlendFactor::Zero;
    transparent.pipeline.destinationAlpha=BlendFactor::One;
    add("opaque-after-transparent",20,16,28,48,.5f,3);
    auto& rejected=add("alpha-discard",8,8,56,56,.1f,2);
    rejected.pipeline.shader.alphaTest=true;rejected.pipeline.shader.alphaCompare=DepthComparison::Greater;
    rejected.pipeline.shader.alphaReference=200;
    auto& noDepth=add("depth-disabled",36,12,52,28,.9f,4);noDepth.pipeline.raster.depthTest=false;
    auto& masked=add("green-write-mask",36,32,52,48,.3f,1);masked.pipeline.colorWriteMask=2;
    auto& mark=add("stencil-mark",12,36,20,44,.2f,5);mark.pipeline.colorWriteMask=0;
    mark.pipeline.raster.depthWrite=false;mark.pipeline.stencil=true;mark.pipeline.stencilReference=3;
    mark.pipeline.stencilPass=ModelStencilOp::Replace;
    auto& stencil=add("stencil-equal",8,32,32,52,.2f,4);stencil.pipeline.stencil=true;
    stencil.pipeline.stencilCompare=DepthComparison::Equal;stencil.pipeline.stencilReference=3;
    auto& cascade=add("toon-base-sphere-add",40,40,56,56,.1f,5);
    Stage(cascade,0,MaterialTextureRole::Toon,5);Stage(cascade,1,MaterialTextureRole::Base,0);
    Stage(cascade,2,MaterialTextureRole::Sphere,6,MaterialCombine::Add);cascade.expected={255,0,255,255};
    auto& untextured=add("untextured-after-three-stages",44,44,52,52,.05f,1);
    untextured.pipeline.shader.layout={};untextured.textures={{-1,-1,-1}};untextured.pipeline.shader.nativeDiffuse={0,1,0,1};
    auto& returning=add("three-stages-return",8,8,16,16,.05f,5);
    Stage(returning,0,MaterialTextureRole::Toon,5);Stage(returning,1,MaterialTextureRole::Base,6);
    Stage(returning,2,MaterialTextureRole::Sphere,5);returning.expected={0,0,255,255};
    auto& wrap=add("point-wrap",4,58,12,62,.1f,0);wrap.u=1.25f;wrap.textures[0]=static_cast<int>(colors.size());
    wrap.pipeline.shader.samplers[0].u=SamplerAddress::Wrap;
    wrap.expected={254,0,0,255};
    auto& clamp=add("point-clamp",16,58,24,62,.1f,6);clamp.u=1.25f;clamp.textures[0]=static_cast<int>(colors.size());
    clamp.pipeline.shader.samplers[0].u=SamplerAddress::Clamp;
    clamp.expected={0,0,254,255};
    auto& linear=add("linear-filter",28,58,36,62,.1f,0);linear.textures[0]=static_cast<int>(colors.size());
    linear.pipeline.shader.samplers[0].min=linear.pipeline.shader.samplers[0].mag=SamplerFilter::Linear;
    linear.expected={127,0,127,255};
    std::vector<Vertex> vertices;std::vector<std::uint16_t> indices;
    for(const auto& b:batches) {
        auto start=static_cast<std::uint16_t>(vertices.size());
        for(auto xy: {std::array<int,2>{b.left,b.top},{b.right,b.top},{b.left,b.bottom},{b.right,b.bottom}})
            vertices.push_back({xy[0]-.25f,xy[1]-.25f,b.z,0,0,1,b.u,.5f});
        for(unsigned i:{0u,1u,2u,2u,1u,3u})indices.push_back(start+i);
    }
    SubmissionIdentity oldDevice{};std::vector<std::uint8_t> first;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(desc,hardware?D3D11Driver::Hardware:D3D11Driver::Warp);
        if(!bundle && !replacement && bundle.stage==D3D11CreationStage::NativeDevice &&
           (bundle.creationError==DXGI_ERROR_UNSUPPORTED || bundle.creationError==DXGI_ERROR_NOT_CURRENTLY_AVAILABLE))return 77;
        CHECK(bundle);report<<"device="<<bundle.adapterName<<" replacement="<<replacement<<"\n";
        auto& device=*bundle.device;
        auto vb=device.CreateBuffer({BufferUsage::Vertex,vertices.size()*sizeof(Vertex)},vertices.data());
        auto ib=device.CreateBuffer({BufferUsage::Index,indices.size()*2},indices.data());CHECK(vb&&ib);
        std::vector<Handle> textures;
        for(auto c:colors){ModelTextureData data;data.levels.push_back({1,1,{c[0],c[1],c[2],c[3]}});
            textures.push_back(CreateD3D11ModelTexture(device,data));CHECK(textures.back());}
        // Even endpoints keep the midpoint off UNORM half-byte rounding ties.
        // Hardware/WARP precision at ties is a separate diagnostic gate.
        ModelTextureData pattern;pattern.levels.push_back({2,1,{254,0,0,255,0,0,254,255}});
        textures.push_back(CreateD3D11ModelTexture(device,pattern));CHECK(textures.back());
        // Fully clipped HUD draw switches shaders/layout/samplers without changing history.
        struct HudVertex {float x,y,z,w;std::uint32_t color;float u,v;};
        const HudVertex hudVertices[]={{-20,-20,.5f,1,0xffffffff,0,0},{-10,-20,.5f,1,0xffffffff,0,0},{-20,-10,.5f,1,0xffffffff,0,0}};
        auto hud=device.CreateBuffer({BufferUsage::Vertex,sizeof(hudVertices)},hudVertices);CHECK(hud);
        auto hudPipeline=HudSpritePipeline();hudPipeline.lighting=false;hudPipeline.cull=RasterCull::None;
        hudPipeline.stencilTest=hudPipeline.alphaTest=hudPipeline.alphaBlend=false;hudPipeline.depthTest=hudPipeline.depthWrite=false;
        hudPipeline.sampler.min=hudPipeline.sampler.mag=hudPipeline.sampler.mip=SamplerFilter::Point;
        auto stale=device.Record(IndexedDraw{vb,ib,0,6,static_cast<unsigned>(vertices.size()),VertexLayout::PositionNormalUv});
        for(unsigned size:{64u,80u,64u}) {
            CHECK(ResizeD3D11Offscreen(device,size,size));
            ModelReplayStream stream;stream.complete=true;stream.target.width=stream.target.height=size;
            stream.events.push_back({1,ModelReplayOp::Clear});
            auto publish=[&](ModelReplayResource resource) {
                const auto key=resource.key;stream.resources.push_back(std::move(resource));
                ModelReplayEvent event;event.sequence=stream.events.size()+1;event.op=ModelReplayOp::PublishResource;
                event.resource=key;stream.events.push_back(event);
            };
            ModelReplayResource savedVertices;savedVertices.key={1,1};savedVertices.bytes.resize(vertices.size()*sizeof(Vertex));
            std::memcpy(savedVertices.bytes.data(),vertices.data(),savedVertices.bytes.size());publish(savedVertices);
            ModelReplayResource savedIndices;savedIndices.key={2,1};savedIndices.kind=ReplayResourceKind::Indices;
            savedIndices.bytes.resize(indices.size()*2);std::memcpy(savedIndices.bytes.data(),indices.data(),savedIndices.bytes.size());publish(savedIndices);
            for(unsigned n=0;n<batches.size();++n) {
                const auto& b=batches[n];ModelReplayEvent event;event.op=ModelReplayOp::Draw;event.label=b.name;
                auto& draw=event.draw;draw.vertices={1,1};draw.indices={2,1};draw.firstIndex=n*6;draw.indexCount=6;draw.vertexCount=static_cast<unsigned>(vertices.size());
                draw.pipeline=b.pipeline;draw.pipeline.shader.projection={2.f/size,0,0,0,0,-2.f/size,0,0,0,0,1,0,-1,1,0,1};
                for(unsigned slot=0;slot<3;++slot)if(b.textures[slot]>=0) {
                    ModelReplayResource resource;resource.key={10+slot,n+1};resource.kind=ReplayResourceKind::Texture;
                    if(b.textures[slot]==colors.size())resource.texture=pattern;
                    else {const auto c=colors[b.textures[slot]];resource.texture.levels.push_back({1,1,{c[0],c[1],c[2],c[3]}});}
                    draw.textures[slot]=resource.key;publish(std::move(resource));
                }
                event.sequence=stream.events.size()+1;stream.events.push_back(event);
            }
            CHECK(ValidateModelReplay(stream));
            for(unsigned prefix=1;prefix<=batches.size();++prefix) {
                CHECK(device.BeginFrame({0,0,0,1}));
                for(unsigned n=0;n<prefix;++n) {
                    CHECK(device.SetFixedPipeline(hudPipeline));
                    const auto hudCommand=device.Record(NonIndexedDraw{hud,0,3});
                    CHECK(!device.Draw(hudCommand));
                    CHECK(device.BindTexture(0,textures[5]) && device.Draw(hudCommand));
                    const auto& b=batches[n];auto p=b.pipeline;
                    p.shader.projection={2.f/size,0,0,0,0,-2.f/size,0,0,0,0,1,0,-1,1,0,1};
                    CHECK(device.SetModelPipeline(p));
                    auto cmd=device.Record(IndexedDraw{vb,ib,n*6,6,static_cast<unsigned>(vertices.size()),VertexLayout::PositionNormalUv});
                    if(b.textures[0]>=0)CHECK(!device.DrawIndexed(cmd)); // Binding is per material.
                    for(unsigned slot=0;slot<3;++slot)if(b.textures[slot]>=0)CHECK(device.BindTexture(slot,textures[b.textures[slot]]));
                    CHECK(!device.DrawIndexed(stale));
                    if(oldDevice.device){auto foreign=cmd;foreign.submission=oldDevice;CHECK(!device.DrawIndexed(foreign));}
                    CHECK(device.DrawIndexed(cmd));
                }
                CHECK(device.EndFrame());RgbaImage actual;CHECK(ReadD3D11Offscreen(device,actual));
                auto expected=Expected(size,batches,prefix);unsigned differences=0;
                for(unsigned i=0;i<actual.pixels.size();i+=4)if(!std::equal(actual.pixels.begin()+i,actual.pixels.begin()+i+4,expected.pixels.begin()+i)) {
                    if(!differences)std::fprintf(stderr,"%s size=%u first=(%u,%u) got=%u,%u,%u,%u expected=%u,%u,%u,%u\n",batches[prefix-1].name,size,(i/4)%size,(i/4)/size,
                        actual.pixels[i],actual.pixels[i+1],actual.pixels[i+2],actual.pixels[i+3],expected.pixels[i],expected.pixels[i+1],expected.pixels[i+2],expected.pixels[i+3]);
                    ++differences;
                }
                report<<"size="<<size<<" prefix="<<prefix<<" batch="<<batches[prefix-1].name<<" differingPixels="<<differences<<"\n";CHECK(!differences);
                // Reconstruct this exact boundary from immutable versioned CPU snapshots.
                RgbaImage replay;const auto replayResult=ReplayD3D11ModelPrefix(device,stream,prefix,replay);
                if(!replayResult)std::fprintf(stderr,"replay sequence=%llu reason=%s\n",static_cast<unsigned long long>(replayResult.sequence),replayResult.reason.c_str());
                CHECK(replayResult && replayResult.draws==prefix && replay.pixels.size()==actual.pixels.size());
                unsigned replayDifferences=0;
                for(std::size_t pixel=0;pixel<actual.pixels.size();pixel+=4)if(std::memcmp(replay.pixels.data()+pixel,actual.pixels.data()+pixel,4)) {
                    if(!replayDifferences)report<<"firstReplayDifference x="<<(pixel/4)%size<<" y="<<(pixel/4)/size<<"\n";
                    ++replayDifferences;
                }
                report<<"replay sequence="<<replayResult.sequence<<" draw="<<prefix<<" label="<<batches[prefix-1].name<<" differingPixels="<<replayDifferences<<"\n";
                if(replayDifferences) {
                    for(auto entry:{std::make_pair("failed-direct.rgba",&actual),std::make_pair("failed-replay.rgba",&replay)}) {
                        std::ofstream file(directory/entry.first,std::ios::binary);file.write(reinterpret_cast<const char*>(entry.second->pixels.data()),entry.second->pixels.size());
                    }
                }
                CHECK(!replayDifferences);
                // An unsupported event beyond the requested boundary must block
                // before clearing or advancing the target epoch.
                if(prefix==1) {
                    auto bad=stream;bad.events.back().op=ModelReplayOp::Unsupported;
                    const auto epoch=device.Status().epoch;RgbaImage rejected;
                    const auto failure=ReplayD3D11ModelPrefix(device,bad,1,rejected);
                    CHECK(!failure && failure.reason=="unsupported_event" && failure.sequence==bad.events.size());
                    CHECK(device.Status().epoch==epoch && ReadD3D11Offscreen(device,rejected) && rejected.pixels==actual.pixels);
                }
                if(prefix==batches.size()) {
                    std::ofstream image(directory/((hardware?"hardware-":"warp-")+std::to_string(replacement)+"-"+std::to_string(size)+".rgba"),std::ios::binary);
                    image.write(reinterpret_cast<const char*>(actual.pixels.data()),actual.pixels.size());
                    if(size==64){if(first.empty())first=actual.pixels;else CHECK(first==actual.pixels);}
                }
            }
        }
        oldDevice={device.Status().identity,device.Status().epoch};CHECK(bundle.swapchain->Retire());
    }
    report<<"status=PASS prefixes="<<batches.size()*6<<" batches="<<batches.size()<<" stale=PASS replacement=PASS\n";
    return 0;
}
