#pragma once
// Fixed arithmetic hypotheses on the existing three triangles. No coordinate
// search, fitted coefficients, native ProcessVertices or production changes.
namespace model_transform_diagnostic {
using model_sampling_diagnostic::Color;
using model_sampling_diagnostic::Vertex;
using model_sampling_diagnostic::Area;
using depth_diagnostic::Matrix;
using depth_diagnostic::Rounding;
inline std::vector<Color> Crop(const std::vector<Color>& pixels,unsigned width,const Area& area) {
    std::vector<Color> out(std::size_t(area.width)*area.height);
    for(unsigned y=0;y<area.height;++y)std::copy_n(pixels.begin()+(area.y+y)*width+area.x,area.width,out.begin()+y*area.width);return out;
}
inline bool Save(const std::filesystem::path& path,const void* bytes,std::size_t count) {
    std::ofstream file(path,std::ios::binary);file.write(static_cast<const char*>(bytes),count);return bool(file);
}
inline bool Read(const std::filesystem::path& path,void* bytes,std::size_t count) {
    std::ifstream file(path,std::ios::binary);return bool(file.read(static_cast<char*>(bytes),count)) && file.peek()==std::char_traits<char>::eof();
}
inline unsigned Changed(const std::vector<Color>& a,const std::vector<Color>& b) {
    if(a.size()!=b.size())return ~0u;unsigned count=0;for(unsigned n=0;n<a.size();++n)count+=std::memcmp(a[n].data(),b[n].data(),16)!=0;return count;
}
inline Color Transform(const Color& object,const Matrix& m,Rounding rule) {
    Color out{};for(unsigned col=0;col<4;++col){const float values[]={m[col],m[col+4],m[col+8],m[col+12]};out[col]=depth_diagnostic::Dot(object.data(),values,rule);}return out;
}
inline int Run(HWND window,const char* archivePath,const char* referencePath,const char* outputPath) {
    const std::filesystem::path reference(referencePath),output(outputPath);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    ground_history_isolation::Archive archive;CHECK(archive.Load(archivePath,42));const auto& source=archive.draws.back();
    const Area area{847,333,42,27};model_sampling_diagnostic::Renderer renderer;CHECK(renderer.Initialize(window,archive.width,archive.height,archive.region,area,source.preparedMips[1]));
    std::ofstream meta(output/"metadata.txt");meta<<"draw=42 width="<<archive.width<<" height="<<archive.height<<" roi="<<area.x<<","<<area.y<<","<<area.width<<","<<area.height<<" samples=1 center=viewport productionActivation=0 nativeVertexCapture=0 adapter="<<renderer.adapter<<"\n";
    std::ofstream table(output/"observations.csv");table<<"triangle,mode,channel,nativeVsReference,candidateVsReference,betweenApis\n";
    std::ofstream transforms(output/"matrices.csv");transforms<<"mode,k,bits,value\n"<<std::setprecision(17);
    Matrix world,view,projection;std::memcpy(world.data(),&source.world,64);std::memcpy(view.data(),&source.view,64);std::memcpy(projection.data(),&source.projection,64);
    std::array<Matrix,4> combined;
    const char* rules[]={"sequential","double","paired","fused"};
    for(unsigned m=0;m<4;++m){const auto r=static_cast<Rounding>(m);combined[m]=depth_diagnostic::Multiply(depth_diagnostic::Multiply(world,view,r),projection,r);
        for(unsigned k=0;k<16;++k)transforms<<rules[m]<<","<<k<<","<<accessory_color_diagnostic::Bits(combined[m][k])<<","<<combined[m][k]<<"\n";}
    unsigned observations=0;
    for(unsigned triangle:{1478u,1822u,1823u}) {
        auto original=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(source,triangle,1));const auto label="compact_"+std::to_string(triangle);
        std::array<Vertex,3> baseline{};CHECK(Read(reference/(label+".input"),baseline.data(),sizeof(baseline)));
        auto pure=model_color_isolation::Control(original,8);Stage(pure,0,D3DTSS_TEXCOORDINDEX,0);Stage(pure,0,D3DTSS_TEXTURETRANSFORMFLAGS,0);
        for(unsigned n=0;n<3;++n)std::memcpy(pure.vertexBytes.data()+n*32+24,baseline[n].uv.data(),8);
        for(unsigned key:{unsigned(D3DRS_LIGHTING),unsigned(D3DRS_SPECULARENABLE),unsigned(D3DRS_ALPHABLENDENABLE),unsigned(D3DRS_ALPHATESTENABLE),unsigned(D3DRS_ZENABLE),unsigned(D3DRS_ZWRITEENABLE),unsigned(D3DRS_STENCILENABLE)})ground_history_isolation::State(pure,key,0);
        ground_history_isolation::State(pure,D3DRS_CULLMODE,D3DCULL_NONE);CHECK(model_color_isolation::FreezeMips(pure,0));
        CHECK(Save(output/(label+".model.vertices"),pure.vertexBytes.data(),pure.vertexBytes.size()));CHECK(Save(output/(label+".baseline.input"),baseline.data(),sizeof(baseline)));
        std::array<std::vector<Color>,3> expected;for(auto& p:expected)p.resize(std::size_t(area.width)*area.height);
        const char* channels[]={"sample","uv","gradients"};
        for(unsigned c=0;c<3;++c)CHECK(Read(reference/(label+".native_vertex_"+channels[c]+".float"),expected[c].data(),expected[c].size()*16));
        auto native=[&](const std::string& mode,const D3D9ReplaySnapshot& draw){
            const std::array<D3DMATRIX,3> submitted{draw.world,draw.view,draw.projection};
            if(!Save(output/(label+"_"+mode+".submitted.vertices"),draw.vertexBytes.data(),draw.vertexBytes.size()) ||
               !Save(output/(label+"_"+mode+".submitted.transforms"),submitted.data(),sizeof(submitted)))return false;
            for(unsigned c=0;c<3;++c){const std::string expression=c==0?"tex2D(tex,uv)":c==1?"float4(uv,0,1)":"float4(ddx(uv),ddy(uv))";
                const std::string ps="sampler2D tex:register(s0);float4 main(float2 uv:TEXCOORD0):COLOR0{return "+expression+";}";
                std::vector<Color> all;RgbaImage unused;if(!NativeImage(window,{draw},1,unused,nullptr,archive.width,archive.height,archive.clear,&all,&ps))return false;
                const auto crop=Crop(all,archive.width,area);const auto different=Changed(crop,expected[c]);
                if(!Save(output/(label+"_"+mode+"_"+channels[c]+".native.float"),crop.data(),crop.size()*16))return false;
                table<<triangle<<","<<mode<<","<<channels[c]<<","<<different<<",-1,-1\n";table.flush();++observations;
                std::printf("transform triangle=%u mode=%s channel=%s nativeVsReference=%u\n",triangle,mode.c_str(),channels[c],different);std::fflush(stdout);
                if(mode=="original" && different)return false;
            }return true;
        };
        auto shared=[&](const std::string& mode,const std::array<Vertex,3>& vertices){
            if(!Save(output/(label+"_"+mode+".input"),vertices.data(),sizeof(vertices)))return false;
            for(unsigned c=0;c<3;++c){std::vector<Color> a,b;std::vector<unsigned char> aa,bb;if(!renderer.Render(vertices,c,1,0,a,b,aa,bb))return false;
                if(!Save(output/(label+"_"+mode+"_"+channels[c]+".native.float"),a.data(),a.size()*16) || !Save(output/(label+"_"+mode+"_"+channels[c]+".candidate.float"),b.data(),b.size()*16))return false;
                table<<triangle<<","<<mode<<","<<channels[c]<<","<<Changed(a,expected[c])<<","<<Changed(b,expected[c])<<","<<Changed(a,b)<<"\n";table.flush();++observations;
                std::printf("transform triangle=%u mode=%s channel=%s nativeVsReference=%u candidateVsReference=%u between=%u\n",triangle,mode.c_str(),channels[c],Changed(a,expected[c]),Changed(b,expected[c]),Changed(a,b));std::fflush(stdout);
            }return true;
        };
        CHECK(native("original",pure));CHECK(shared("baseline",baseline));
        for(unsigned n=1;n<=3;++n){CHECK(native("original_repeat"+std::to_string(n),pure));CHECK(shared("baseline_repeat"+std::to_string(n),baseline));}
        std::array<Vertex,3> fusedXY=baseline;
        for(unsigned m=0;m<4;++m)for(unsigned dot=0;dot<4;++dot){auto values=baseline;for(unsigned n=0;n<3;++n){Color object{0,0,0,1};std::memcpy(object.data(),original.vertexBytes.data()+n*32,12);values[n].clip=Transform(object,combined[m],static_cast<Rounding>(dot));}
            const auto mode="matrix_"+std::string(rules[m])+"_dot_"+rules[dot];CHECK(shared(mode,values));
            if(!m && dot==3){fusedXY=values;for(unsigned n=0;n<3;++n){fusedXY[n].clip[2]=baseline[n].clip[2];fusedXY[n].clip[3]=baseline[n].clip[3];}}
        }
        CHECK(shared("fused_xy_hold_zw",fusedXY));
        // Fresh SO observations prove GPU arithmetic matches the CPU hypothesis.
        for(unsigned repeat=0;repeat<4;++repeat){std::vector<Color> positions,colors;std::vector<std::array<float,2>> uv;
            CHECK(CaptureDepthVertexShader(original,positions,nullptr,false,3,&colors,nullptr,nullptr,true,&uv,1,true,true));CHECK(positions.size()==3 && uv.size()==3);
            std::array<Vertex,3> captured;for(unsigned n=0;n<3;++n){captured[n]={positions[n],uv[n]};CHECK(!std::memcmp(&captured[n],&fusedXY[n],sizeof(Vertex)));}
            CHECK(Save(output/(label+".gpu_fused_xy"+(repeat?".repeat"+std::to_string(repeat):"")+".input"),captured.data(),sizeof(captured)));}
        for(unsigned component=0;component<2;++component){auto values=baseline;for(unsigned n=0;n<3;++n)values[n].clip[component]=fusedXY[n].clip[component];CHECK(shared(component?"fused_y_only":"fused_x_only",values));}
        for(unsigned m=0;m<4;++m){auto draw=pure;draw.world=draw.view=Fixture().world;std::memcpy(&draw.projection,combined[m].data(),64);CHECK(native("native_precombined_"+std::string(rules[m]),draw));
            auto wv=pure;const auto combinedWV=depth_diagnostic::Multiply(world,view,static_cast<Rounding>(m));std::memcpy(&wv.world,combinedWV.data(),64);wv.view=Fixture().view;CHECK(native("native_worldview_"+std::string(rules[m]),wv));}
        for(unsigned input=0;input<2;++input)for(unsigned rule=0;rule<2;++rule){const auto& values=input?fusedXY:baseline;auto draw=pure;draw.fvf=D3DFVF_XYZRHW|D3DFVF_TEX1;draw.stride=24;draw.vertexBytes.resize(72);
            for(unsigned n=0;n<3;++n){const auto& v=values[n].clip;Color screen{};if(rule){screen={float(archive.region.X+(double(v[0])/v[3]+1)*archive.region.Width*.5),float(archive.region.Y+(1-double(v[1])/v[3])*archive.region.Height*.5),float(double(v[2])/v[3]),float(1./v[3])};}
                else screen=ground_endpoint_depth::Screen(v,archive.region,false);
                std::memcpy(draw.vertexBytes.data()+n*24,screen.data(),16);std::memcpy(draw.vertexBytes.data()+n*24+16,values[n].uv.data(),8);}
            const auto mode=std::string(input?"fused_xy":"baseline")+"_rhw_"+(rule?"double":"float");CHECK(Save(output/(label+"_"+mode+".vertices"),draw.vertexBytes.data(),draw.vertexBytes.size()));CHECK(native(mode,draw));}
        const unsigned permutations[][3]={{0,1,2},{1,2,0},{2,0,1},{0,2,1},{2,1,0},{1,0,2}};
        for(unsigned perm=1;perm<6;++perm){auto draw=pure;auto values=baseline,corrected=fusedXY;for(unsigned n=0;n<3;++n){const auto i=permutations[perm][n];std::memcpy(draw.vertexBytes.data()+n*32,pure.vertexBytes.data()+i*32,32);values[n]=baseline[i];corrected[n]=fusedXY[i];}
            CHECK(native("native_order"+std::to_string(perm),draw));CHECK(shared("baseline_order"+std::to_string(perm),values));CHECK(shared("fused_xy_order"+std::to_string(perm),corrected));}
    }
    model_color_isolation::Probe batch{window,archive};batch.output=output/"material42";CHECK(batch.Initialize());CHECK(batch.bundle.swapchain->Retire());
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    batch.bundle=CreateD3D11FusedXYCandidateDevice(desc,D3D11Driver::Hardware);CHECK(batch.bundle);CHECK(batch.Render("original",source));
    const auto n=batch.native,c=batch.candidate;
    for(unsigned repeat=1;repeat<=3;++repeat){CHECK(batch.Render("repeat"+std::to_string(repeat),source));CHECK(batch.native==n && batch.candidate==c);}
    CHECK(batch.bundle.swapchain->Retire());
    std::ofstream policy(batch.output/"xy_policy.txt");policy<<"fusedXY=1 GPUStreamOutputMatchesCPU=1 geometryUnchanged=1 productionActivation=0\n";CHECK(policy);
    CHECK(meta && table && transforms);std::ofstream summary(output/"summary.txt");summary<<"complete=1 triangles=3 observations="<<observations<<" repeats=3 gpuSoRepeats=3 materialRepeats=3 nativeVertexCapture=0 productionActivation=0 imageAcceptance=0\n";CHECK(summary);return 0;
}
} // namespace model_transform_diagnostic
