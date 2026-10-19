#pragma once
// Generated, redistributable ground geometry: indexed grid lines followed by
// a nonindexed plane. Prefix and suffix sentinels prove range interpretation.
namespace ground_replay_diagnostic {
inline D3D9ReplaySnapshot Geometry(bool lines,unsigned size,bool indexed,bool textured=false) {
    auto c=ShadowFixture(0,textured);c.viewport={0,0,size,size,0,1};
    c.type=lines?D3DPT_LINELIST:D3DPT_TRIANGLELIST;c.indexed=indexed;
    Set(c,D3DRS_LIGHTING,FALSE);Set(c,D3DRS_STENCILENABLE,FALSE);Set(c,D3DRS_ALPHABLENDENABLE,FALSE);
    Set(c,D3DRS_ALPHATESTENABLE,FALSE);Set(c,D3DRS_CULLMODE,D3DCULL_NONE);
    Set(c,D3DRS_ZFUNC,D3DCMP_LESSEQUAL);c.world=Fixture().world;
    struct V {float x,y,z;DWORD color;};std::vector<V> v;
    auto at=[&](float x,float y,float z,DWORD color){return V{x*2/size-1,1-y*2/size,z,color};};
    if(lines) {
        v={at(8,32,.25f,0xffff0000),at(56,32,.25f,0xffff0000),at(32,8,.25f,0xff00ff00),at(32,56,.25f,0xff00ff00)};
        c.count=2;
    } else {
        v={at(12,12,.5f,0xff0000ff),at(52,12,.5f,0xff0000ff),at(12,52,.5f,0xff0000ff),
           at(12,52,.5f,0xff0000ff),at(52,12,.5f,0xff0000ff),at(52,52,.5f,0xff0000ff)};
        c.count=2;
    }
    c.minimum=0;c.vertices=indexed?static_cast<unsigned>(v.size()):0;c.start=indexed?2:3;
    if(indexed) {
        c.indexFormat=D3DFMT_INDEX16;c.indexBytes={0,0,0,0};
        for(unsigned n=0;n<v.size();++n){c.indexBytes.push_back(static_cast<unsigned char>(n));c.indexBytes.push_back(0);}
        c.indexBytes.insert(c.indexBytes.end(),{255,255,255,255}); // Outside the requested range.
    } else {
        c.indexFormat=D3DFMT_UNKNOWN;c.indexBytes.clear();
        const auto sentinel=at(0,0,0,0xffff00ff);v.insert(v.begin(),3,sentinel);v.push_back(sentinel);
    }
    c.vertexBytes.resize(v.size()*sizeof(V));std::memcpy(c.vertexBytes.data(),v.data(),c.vertexBytes.size());
    if(textured){c.textureInfo[0]={true,D3DFMT_A8R8G8B8,1,1,1,0,false};c.textureBytes[0]={255,255,255,255};}return c;
}
inline int Conversion() {
    ModelReplayStream s;s.target.width=s.target.height=64;s.events.push_back({1,ModelReplayOp::Clear});
    const auto line=Geometry(true,64,true),plane=Geometry(false,64,false);
    CHECK(AppendD3D9ReplaySnapshot(s,line,true));CHECK(AppendD3D9ReplaySnapshot(s,plane,true));s.complete=true;
    CHECK(ValidateModelReplay(s).draws==2 && s.resources.size()==3 && s.events.size()==6);
    const auto& d=s.events.back().draw;CHECK(!d.indexed && !d.indices.id && !d.indexCount && !d.vertexCount && d.firstVertex==3 && d.drawVertexCount==6);
    CHECK(s.events[3].draw.pipeline.topology==PrimitiveTopology::LineList && s.events[3].draw.indexCount==4);
    auto reject=[&](D3D9ReplaySnapshot bad,const char* why){auto before=s;auto r=AppendD3D9ReplaySnapshot(s,bad,true);
        return !r && r.reason==why && s.events.size()==before.events.size() && s.resources.size()==before.resources.size();};
    auto bad=line;bad.type=D3DPT_LINESTRIP;CHECK(reject(bad,"unsupported_geometry_layout_or_base"));
    bad=line;bad.count=0x80000000u;CHECK(reject(bad,"invalid_native_draw_range"));
    bad=plane;bad.start=0xffffffffu;CHECK(reject(bad,"invalid_native_draw_range"));
    bad=plane;bad.count=3;CHECK(reject(bad,"invalid_native_draw_range"));
    bad=line;bad.indexBytes[4]=4;CHECK(reject(bad,"index_out_of_range"));
    return 0;
}
#ifdef MIKUDANCESTUDIO_RHI_D3D11
inline int Run(HWND window,D3D11Driver driver) {
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    unsigned comparisons=0;NonIndexedDraw retiredCommand;
    for(unsigned replacement=0;replacement<2;++replacement) {
        auto bundle=CreateD3D11Device(desc,driver);CHECK(bundle);auto& device=*bundle.device;
        std::printf("ground driver=%s adapter=%s replacement=%u\n",driver==D3D11Driver::Hardware?"hardware":"warp",bundle.adapterName.c_str(),replacement);
        for(unsigned size:{64u,80u,64u})for(bool textured:{false,true}) {
            std::vector<D3D9ReplaySnapshot> snapshots={Geometry(true,size,true),Geometry(false,size,false,textured),Geometry(true,size,false),Geometry(false,size,true)};
            ModelReplayStream s;s.target.width=s.target.height=size;s.events.push_back({1,ModelReplayOp::Clear});
            for(const auto& c:snapshots)CHECK(AppendD3D9ReplaySnapshot(s,c,true));s.complete=true;
            for(unsigned prefix:{1u,2u,3u,4u,2u}) {
                RgbaImage native,image;CHECK(NativeImage(window,snapshots,prefix,native,nullptr,size,size));
                CHECK(ReplayD3D11ModelPrefix(device,s,prefix,image));const auto differences=PixelDifferences(native,image);
                if(differences)std::fprintf(stderr,"ground size=%u textured=%u prefix=%u differingPixels=%u\n",size,textured,prefix,differences);
                CHECK(!differences);
                const unsigned char green[]={0,255,0,255},blue[]={0,0,255,255};
                CHECK(std::memcmp(image.pixels.data()+(32*size+32)*4,green,4)==0);
                if(prefix>1)CHECK(std::memcmp(image.pixels.data()+(20*size+20)*4,blue,4)==0);
                ++comparisons;
            }
        }
        auto geometry=Geometry(false,64,false);auto vb=device.CreateBuffer({BufferUsage::Vertex,geometry.vertexBytes.size()},geometry.vertexBytes.data());CHECK(vb);
        // Direct submissions use portable RGBA, not the native snapshot's BGRA.
        auto bytes=geometry.vertexBytes;for(std::size_t n=12;n<bytes.size();n+=16)std::swap(bytes[n],bytes[n+2]);CHECK(device.Upload(vb,0,bytes.data(),bytes.size()));
        ModelReplayStream s;s.target.width=s.target.height=64;s.events.push_back({1,ModelReplayOp::Clear});CHECK(AppendD3D9ReplaySnapshot(s,geometry,true));
        const auto pipeline=s.events.back().draw.pipeline;
        NonIndexedDraw command{vb,3,6};command.layout=VertexLayout::PositionColor;command=device.Record(command);
        CHECK(ResizeD3D11Offscreen(device,64,64));CHECK(device.BeginFrame({0,0,0,1}) && device.SetModelPipeline(pipeline));
        CHECK(!device.Draw(command)); // Target rebuild advanced epoch.
        if(replacement)CHECK(!device.Draw(device.Record(retiredCommand))); // Old device buffer cannot be restamped.
        command=device.Record(command);auto missing=command;missing.layout.reset();CHECK(!device.Draw(missing));
        auto wrong=command;wrong.layout=VertexLayout::ScreenPositionColor;CHECK(!device.Draw(wrong));
        wrong=command;wrong.firstVertex=0xffffffffu;CHECK(!device.Draw(wrong));
        CHECK(device.Draw(command) && device.EndFrame());retiredCommand=command;CHECK(bundle.swapchain->Retire());
    }
    std::printf("ground comparisons=%u differingPixels=0 rangeSentinels=PASS topologyTransitions=PASS nonindexedEpoch=PASS deviceReplacement=PASS\n",comparisons);return 0;
}
#endif
}
