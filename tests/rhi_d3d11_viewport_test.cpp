#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include "mikudancestudio/rhi_d3d11.hpp"
#include <array>
#include <cstdio>
#include <cstring>
#include <string>
using namespace mikudancestudio::rhi;
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
struct Vertex {float x,y,z,nx,ny,nz,u,v;};
ModelPipeline Pipeline(ModelViewport view,std::array<float,4> color) {
    ModelPipeline p;p.viewport=view;p.raster.cull=BatchCull::None;p.raster.alphaBlend=false;
    p.shader.nativeDiffuse=color;
    for(auto* m:{&p.shader.world,&p.shader.view,&p.shader.normalView})*m={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    p.shader.projection={2.f/view.width,0,0,0,0,-2.f/view.height,0,0,0,0,1,0,-1,1,0,1};
    return p;
}
int main(int argc,char** argv) {
    const bool hardware=argc>1 && std::string(argv[1])=="--hardware";
    struct Window {HWND h;~Window(){if(h)DestroyWindow(h);}} window{
        CreateWindowExW(0,L"STATIC",L"DX11 viewport",WS_POPUP,0,0,80,80,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};
    CHECK(window.h);SwapchainDesc surface;surface.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window.h)};surface.width=surface.height=64;
    const Vertex vertices[]={{3.75f,3.75f,.5f,0,0,1,0,0},{19.75f,3.75f,.5f,0,0,1,0,0},
        {3.75f,19.75f,.5f,0,0,1,0,0},{19.75f,19.75f,.5f,0,0,1,0,0}};
    const std::uint16_t indices[]={0,1,2,2,1,3};unsigned comparisons=0;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(surface,hardware?D3D11Driver::Hardware:D3D11Driver::Warp);CHECK(bundle);
        std::printf("driver=%s adapter=%s\n",hardware?"hardware":"warp",bundle.adapterName.c_str());
        auto& device=*bundle.device;
        for(unsigned size:{64u,80u,64u}) {
            ModelReplayStream stream;stream.complete=true;stream.target.width=stream.target.height=size;stream.events.push_back({1,ModelReplayOp::Clear});
            ModelReplayResource vb;vb.key={1,1};vb.bytes.resize(sizeof(vertices));std::memcpy(vb.bytes.data(),vertices,sizeof(vertices));
            ModelReplayResource ib;ib.key={2,1};ib.kind=ReplayResourceKind::Indices;ib.bytes.resize(sizeof(indices));std::memcpy(ib.bytes.data(),indices,sizeof(indices));
            stream.resources={vb,ib};
            for(auto key:{vb.key,ib.key}){ModelReplayEvent e;e.op=ModelReplayOp::PublishResource;e.sequence=stream.events.size()+1;e.resource=key;stream.events.push_back(e);}
            const std::array<ModelViewport,4> views={ModelViewport{8,6,32,40,.25f,.75f},{8,6,32,40,.75f,1},{16,10,32,32,0,.5f},{0,0,size,size,0,1}};
            const std::array<std::array<float,4>,4> colors={std::array<float,4>{1,0,0,1},{0,0,1,1},{0,1,0,1},{1,1,0,1}};
            for(unsigned n=0;n<4;++n) {
                ModelReplayEvent e;e.sequence=stream.events.size()+1;e.op=ModelReplayOp::Draw;e.draw.vertices=vb.key;e.draw.indices=ib.key;
                e.draw.vertexCount=4;e.draw.indexCount=6;e.draw.pipeline=Pipeline(views[n],colors[n]);
                if(n==3)e.draw.pipeline.viewport.reset(); // No inherited viewport/depth range.
                stream.events.push_back(e);
            }
            RgbaImage expected{size,size,std::vector<std::uint8_t>(size*size*4)};std::vector<float> depth(size*size,1);
            for(unsigned i=0;i<size*size;++i)expected.pixels[i*4+3]=255;
            RgbaImage cleared;const auto clearReplay=ReplayD3D11ModelPrefix(device,stream,0,cleared);
            CHECK(clearReplay && clearReplay.draws==0 && cleared.pixels==expected.pixels);
            for(unsigned n=0;n<4;++n) {
                const auto& v=views[n];const float z=(v.minDepth+v.maxDepth)*.5f;
                for(unsigned y=v.y+4;y<v.y+20;++y)for(unsigned x=v.x+4;x<v.x+20;++x)if(z<=depth[y*size+x]) {
                    depth[y*size+x]=z;for(unsigned c=0;c<4;++c)expected.pixels[(y*size+x)*4+c]=static_cast<unsigned char>(colors[n][c]*255);
                }
                RgbaImage image;const auto replay=ReplayD3D11ModelPrefix(device,stream,n+1,image);CHECK(replay);
                if(image.pixels!=expected.pixels)std::fprintf(stderr,"size=%u prefix=%u viewport image mismatch\n",size,n+1);
                CHECK(image.pixels==expected.pixels);++comparisons;
            }
            // Malformed viewport blocks before clearing/changing the epoch.
            auto invalid=stream;invalid.events.back().draw.pipeline.viewport=ModelViewport{size,0,1,1,0,1};
            const auto epoch=device.Status().epoch;RgbaImage image;
            CHECK(!ReplayD3D11ModelPrefix(device,invalid,1,image) && device.Status().epoch==epoch);
            CHECK(ReadD3D11Offscreen(device,image) && image.pixels==expected.pixels);
            // A regional clear permits only draws confined to its known pixels.
            auto regional=stream;regional.events.resize(5);regional.initializedRegion=views[0];
            CHECK(ValidateModelReplay(regional));CHECK(ReplayD3D11ModelPrefix(device,regional,2,image));
            CHECK(image.pixels[(12*size+14)*4]==255); // second, farther draw lost
            auto escapes=stream;escapes.initializedRegion=views[0];CHECK(!ValidateModelReplay(escapes));
        }
        // A HUD pipeline has an independent full-target viewport. Verify a
        // visible HUD pixel below the last model viewport, not a clipped no-op.
        CHECK(ResizeD3D11Offscreen(device,64,64));
        auto geometry=device.CreateBuffer({BufferUsage::Vertex,sizeof(vertices)},vertices);
        auto index=device.CreateBuffer({BufferUsage::Index,sizeof(indices)},indices);CHECK(geometry&&index);
        struct HudVertex {float x,y,z,w;std::uint32_t color;float u,v;};
        const HudVertex hudVertices[]={{4,48,.5f,1,0xffffffff,0,0},{4,62,.5f,1,0xffffffff,0,0},{18,48,.5f,1,0xffffffff,0,0}};
        auto hud=device.CreateBuffer({BufferUsage::Vertex,sizeof(hudVertices)},hudVertices);CHECK(hud);
        ModelTextureData yellow;yellow.levels.push_back({1,1,{255,255,0,255}});auto texture=CreateD3D11ModelTexture(device,yellow);CHECK(texture);
        CHECK(device.BeginFrame({0,0,0,1}) && device.SetModelPipeline(Pipeline({8,6,32,40,.25f,.75f},{1,0,0,1})));
        CHECK(device.DrawIndexed(device.Record(IndexedDraw{geometry,index,0,6,4,VertexLayout::PositionNormalUv})));
        auto hp=HudSpritePipeline();hp.lighting=hp.alphaTest=hp.stencilTest=hp.depthTest=hp.depthWrite=hp.alphaBlend=false;
        hp.cull=RasterCull::None;hp.sampler.min=hp.sampler.mag=hp.sampler.mip=SamplerFilter::Point;
        CHECK(device.SetFixedPipeline(hp) && device.BindTexture(0,texture) && device.Draw(device.Record(NonIndexedDraw{hud,0,3})) && device.EndFrame());
        RgbaImage hudImage;CHECK(ReadD3D11Offscreen(device,hudImage));
        CHECK(hudImage.pixels[(52*64+6)*4]==255 && hudImage.pixels[(52*64+6)*4+1]==255);
        CHECK(bundle.swapchain->Retire());
    }
    std::printf("viewport comparisons=%u differingPixels=0 invalid=PASS initializedRegion=PASS\n",comparisons);
    return 0;
}
