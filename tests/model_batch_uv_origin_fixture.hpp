#pragma once
// Diagnose vertex UV generation vs position/raster interpolation. DX11 SO is
// actual pre-raster output. DX9 FF controls are raster observations, not SO.
namespace model_batch_uv_origin {
using model_batch_color::Color;
using model_sampling_diagnostic::Vertex;
using model_sampling_diagnostic::Area;
using model_transform_diagnostic::Crop;
using model_transform_diagnostic::Save;
struct Images {std::vector<Color> n,c;};
inline bool Observe(HWND window,const D3D9ReplaySnapshot& c,unsigned width,unsigned height,IDirect3DDevice9* device,Images& out) {
    const auto a=model_batch_color::PixelStage(2,false),b=model_batch_color::PixelStage(2,true);RgbaImage unused;
    return NativeImage(window,{c},1,unused,nullptr,width,height,0xffffffff,&out.n,&a,device) &&
        model_batch_color::Stage11(c,width,height,b,true,unused,out.c);
}
inline D3D9ReplaySnapshot MeshUV(D3D9ReplaySnapshot c,const std::vector<std::array<float,2>>& uv) {
    for(unsigned n=0;n<uv.size();++n)std::memcpy(c.vertexBytes.data()+n*c.stride+24,uv[n].data(),8);
    Stage(c,0,D3DTSS_TEXCOORDINDEX,0);Stage(c,0,D3DTSS_TEXTURETRANSFORMFLAGS,0);return c;
}
inline int Run(HWND window,const char* root,const char* destination,unsigned x,unsigned y,unsigned triangle) {
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,24));CHECK(triangle<archive.draws[22].count);
    CHECK(x>=2 && y>=2 && x+2<archive.width && y+2<archive.height);
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    auto source=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(archive.draws[22],triangle,1));
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})ground_history_isolation::State(source,key,0);
    ground_history_isolation::State(source,D3DRS_CULLMODE,D3DCULL_NONE);
    std::ofstream vertices(output/"vertices.csv"),table(output/"pixels.csv"),gates(output/"gates.csv");
    vertices<<"geometry,repeat,vertex,clipX,clipY,clipZ,clipW,u,v,bitsU,bitsV\n"<<std::setprecision(17);
    table<<"geometry,mode,repeat,x,y,nativeU,nativeV,nativeB,nativeA,candidateU,candidateV,candidateB,candidateA\n"<<std::setprecision(17);
    gates<<"geometry,mode,repeat,knownPixels,betweenApis,nativeVsBaseline,candidateVsBaseline,nativeCovered,candidateCovered\n";
    const auto bits=[](float value){unsigned v;std::memcpy(&v,&value,4);return v;};
    unsigned controls=0;
    for(unsigned geometry=0;geometry<2;++geometry) {
        const auto c=geometry?model_batch_causal::Independent(source):source;
        const std::string label=geometry?"independent":"saved";const unsigned width=geometry?64:archive.width,height=geometry?64:archive.height;
        const unsigned fx=geometry?24:x,fy=geometry?32:y;const auto& v=c.viewport;
        const Area area{v.X,v.Y,v.Width,v.Height};const Area focusArea{fx-2,fy-2,5,5};
        ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=width;pp.BackBufferHeight=height;pp.BackBufferCount=1;
        pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        ComPtr<IDirect3DDevice9> device;const auto created=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
        if(FAILED(created))std::fprintf(stderr,"UV origin DX9 CreateDevice=%08lx\n",static_cast<unsigned long>(created));CHECK(SUCCEEDED(created));
        Images original;CHECK(Observe(window,c,width,height,device.Get(),original));
        Images baseline{Crop(original.n,width,area),Crop(original.c,width,area)};
        const auto report=[&](const std::string& mode,unsigned repeat,const Images& value) {
            if(value.n.size()!=baseline.n.size() || value.c.size()!=baseline.c.size())return false;
            unsigned between=0,nativeDelta=0,candidateDelta=0,nativeCovered=0,candidateCovered=0;
            for(unsigned p=0;p<value.n.size();++p) {
                between+=value.n[p]!=value.c[p];nativeDelta+=value.n[p]!=baseline.n[p];candidateDelta+=value.c[p]!=baseline.c[p];
                nativeCovered+=value.n[p][2]==0 && value.n[p][3]==1;candidateCovered+=value.c[p][2]==0 && value.c[p][3]==1;
            }
            gates<<label<<","<<mode<<","<<repeat<<","<<value.n.size()<<","<<between<<","<<nativeDelta<<","<<candidateDelta<<","<<nativeCovered<<","<<candidateCovered<<"\n";
            for(unsigned py=focusArea.y;py<focusArea.y+5;++py)for(unsigned px=focusArea.x;px<focusArea.x+5;++px) {
                const auto p=std::size_t(py-area.y)*area.width+px-area.x;
                table<<label<<","<<mode<<","<<repeat<<","<<px<<","<<py;for(float f:value.n[p])table<<","<<f;for(float f:value.c[p])table<<","<<f;table<<"\n";
            }
            const auto stem=label+"_"+mode+".repeat"+std::to_string(repeat);
            if(!Save(output/(stem+".dx9.float"),value.n.data(),value.n.size()*16) || !Save(output/(stem+".dx11.float"),value.c.data(),value.c.size()*16))return false;
            table.flush();gates.flush();++controls;
            std::printf("uvOrigin geometry=%s mode=%s repeat=%u between=%u nativeDelta=%u candidateDelta=%u\n",label.c_str(),mode.c_str(),repeat,between,nativeDelta,candidateDelta);std::fflush(stdout);return bool(table && gates);
        };
        std::array<Vertex,3> shared{};
        std::vector<std::array<float,2>> uv;std::vector<Color> positions;
        for(unsigned repeat=0;repeat<3;++repeat) {
            std::vector<Color> p;std::vector<std::array<float,2>> u;
            CHECK(CaptureDepthVertexShader(c,p,nullptr,false,0,nullptr,nullptr,nullptr,false,&u,0,false,false,true));CHECK(p.size()==3 && u.size()==3);
            if(repeat)CHECK(p==positions && u==uv);else {positions=p;uv=u;}
            for(unsigned n=0;n<3;++n){shared[n]={p[n],u[n]};vertices<<label<<","<<repeat<<","<<n;for(float f:p[n])vertices<<","<<f;for(float f:u[n])vertices<<","<<f;vertices<<","<<bits(u[n][0])<<","<<bits(u[n][1])<<"\n";}
            CHECK(Save(output/(label+".so.repeat"+std::to_string(repeat)+".input"),shared.data(),sizeof(shared)));
            Images full;CHECK(Observe(window,c,width,height,device.Get(),full));CHECK(full.n==original.n && full.c==original.c);CHECK(report("original",repeat,baseline));
            CHECK(Observe(window,MeshUV(c,uv),width,height,device.Get(),full));CHECK(report("mesh_uv_from_so",repeat,{Crop(full.n,width,area),Crop(full.c,width,area)}));
        }
        // Identical normals eliminate the UV plane's slope while preserving
        // actual position transforms. This is a raster control, not a native
        // capture of FF vertex registers.
        for(unsigned vertex=0;vertex<3;++vertex) {
            auto uniform=c;for(unsigned n=0;n<3;++n)std::memcpy(uniform.vertexBytes.data()+n*c.stride+12,c.vertexBytes.data()+vertex*c.stride+12,12);
            std::vector<std::array<float,2>> u;std::vector<Color> p;
            CHECK(CaptureDepthVertexShader(uniform,p,nullptr,false,0,nullptr,nullptr,nullptr,false,&u,0,false,false,true));
            CHECK(u.size()==3 && u[0]==uv[vertex] && u[1]==uv[vertex] && u[2]==uv[vertex]);
            for(unsigned repeat=0;repeat<3;++repeat){Images full;CHECK(Observe(window,uniform,width,height,device.Get(),full));CHECK(report("uniform_normal"+std::to_string(vertex),repeat,{Crop(full.n,width,area),Crop(full.c,width,area)}));
                CHECK(Observe(window,MeshUV(uniform,u),width,height,device.Get(),full));CHECK(report("uniform_mesh_uv"+std::to_string(vertex),repeat,{Crop(full.n,width,area),Crop(full.c,width,area)}));}
        }
        ModelReplayStream converted;converted.target.width=width;converted.target.height=height;converted.events.push_back({1,ModelReplayOp::Clear});
        const auto conversion=AppendD3D9ReplaySnapshot(converted,c);if(!conversion)std::fprintf(stderr,"UV origin conversion: %s\n",conversion.reason.c_str());CHECK(conversion);
        const auto id=converted.events.back().draw.textures[0].id;
        const auto found=std::find_if(converted.resources.begin(),converted.resources.end(),[&](const auto& r){return r.key.id==id;});CHECK(found!=converted.resources.end());
        model_sampling_diagnostic::Renderer renderer;CHECK(renderer.Initialize(window,width,height,c.viewport,area,found->texture));
        for(unsigned linkage=0;linkage<2;++linkage)for(unsigned repeat=0;repeat<3;++repeat) {
            Images value;std::vector<unsigned char> n,candidate;CHECK(renderer.Render(shared,1,1,0,value.n,value.c,n,candidate,{},{},linkage!=0));
            CHECK(report(linkage?"shared_clip_uv_ps2":"shared_clip_uv_ps3",repeat,value));
        }
        // Same UV at every vertex isolates interpolation of a constant plane.
        for(unsigned vertex=0;vertex<3;++vertex) {
            auto uniform=shared;for(auto& s:uniform)s.uv=uv[vertex];
            for(unsigned repeat=0;repeat<3;++repeat){Images value;std::vector<unsigned char> n,candidate;CHECK(renderer.Render(uniform,1,1,0,value.n,value.c,n,candidate,{},{},true));CHECK(report("shared_uniform_uv"+std::to_string(vertex),repeat,value));}
        }
    }
    CHECK(vertices && table && gates);std::ofstream metadata(output/"metadata.txt");metadata<<"x="<<x<<" y="<<y<<" triangle="<<triangle<<" dx11PreRasterSO=1 dx9NativePreRasterCapture=0 productionActivation=0 imageAcceptance=0\n";
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 controls="<<controls<<" geometries=2 repeats=3 productionActivation=0 imageAcceptance=0\n";CHECK(metadata && summary);return 0;
}
}
