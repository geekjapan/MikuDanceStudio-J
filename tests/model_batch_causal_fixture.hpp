#pragma once
// Test-only cross-feeds after the unchanged FF/measured vertex paths. Runtime
// constants preserve float32 bits and prevent constant-folding the color math.
namespace model_batch_causal {
using model_batch_color::Color;
using model_batch_color::Stage11;
using model_batch_color::PixelStage;
struct Point { unsigned x,y; };
struct Result { std::vector<Color> n,c;RgbaImage nb,cb; };
inline std::string Shader(const std::string& mode,bool eleven) {
    const std::string declaration=eleven?
        "Texture2D t0:register(t0),t1:register(t1);SamplerState s0:register(s0),s1:register(s1);cbuffer Diagnostic:register(b1){float4 q[7];};":
        "sampler2D t0:register(s0),t1:register(s1);float4 q[7]:register(c16);";
    const std::string input=eleven?
        "float4 position:SV_POSITION;float4 diffuse:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 specular:COLOR1;":
        "float4 diffuse:COLOR0;float4 specular:COLOR1;float2 a:TEXCOORD0;float2 b:TEXCOORD1;";
    const std::string sampled=eleven?"t0.Sample(s0,input.a)":"tex2D(t0,input.a)";
    // PS2 texldd requires a temp/texcoord source, not a constant register.
    // q[6] is a runtime zero; this exact add preserves q[0] while forcing
    // a temp without changing the native FF varying linkage to PS3.
    const std::string gradient=eleven?"t0.SampleGrad(s0,constantUv,q[1].xy,q[1].zw)":"tex2Dgrad(t0,constantUv,q[1].xy,q[1].zw)";
    const std::string base=eleven?"t1.Sample(s1,input.b)":"tex2D(t1,input.b)";
    std::string body;
    if(mode=="sample")body="return "+gradient+";";
    else {
        const auto diffuse=mode=="all"?"q[2].rgb":"input.diffuse.rgb";
        const auto toon=mode=="uv"?gradient:(mode=="sample_final" || mode=="sample_spec" || mode=="all")?"q[4]":sampled;
        const auto second=mode=="all"?"q[5]":base;
        const auto spec=(mode=="spec" || mode=="sample_spec" || mode=="all")?"q[3].rgb":"input.specular.rgb";
        body=std::string(eleven?"precise ":"")+"float3 previous="+diffuse+"*"+toon+".rgb;float3 second="+second+".rgb;float3 highlight="+spec+";";
        // Same expression as the opt-in measured backend. The native FF PS
        // control is gated below, so this is not assumed to be native MAD.
        if(eleven)body+="precise double3 product=double3(previous)*double3(second);precise double3 combined=product+double3(highlight);return float4(saturate(float3(combined)),1);";
        else body+="return float4(saturate(previous*second+highlight),1);";
    }
    return declaration+"struct Input{"+input+"};float4 main(Input input):"+(eleven?"SV_TARGET":"COLOR0")+"{float2 constantUv=q[0].xy+input.a*q[6].xy;"+body+"}";
}
inline bool Render(HWND window,const D3D9ReplaySnapshot& draw,unsigned width,unsigned height,
                   const std::string* ps9,const std::string& ps11,const std::vector<Color>* values,Result& out,IDirect3DDevice9* device,const std::string* vertex=nullptr) {
    if(!NativeImage(window,{draw},1,out.nb,nullptr,width,height,0,&out.n,ps9,device,values) ||
       !Stage11(draw,width,height,ps11,true,out.cb,out.c,{},.5f,values,vertex))return false;
    // RGBA8 is measured on actual UNORM targets, never reconstructed on CPU.
    std::vector<Color> unused;
    return NativeImage(window,{draw},1,out.nb,nullptr,width,height,0,nullptr,ps9,device,values) &&
        Stage11(draw,width,height,ps11,false,out.cb,unused,{},.5f,values,vertex);
}
inline D3D9ReplaySnapshot Independent(const D3D9ReplaySnapshot& source) {
    auto c=source;c.viewport={0,0,64,64,0,1};c.count=1;c.vertices=3;c.minimum=c.start=c.offset=c.base=0;
    c.indexFormat=D3DFMT_INDEX16;c.indexBytes={0,0,1,0,2,0};
    // New geometry and normals, rather than archived/rounded clip vertices.
    const float vertices[]={-.875f,-.75f,.35f,-.62f,.19f,-.76f,0,0,
        -.625f,.875f,.55f,-.81f,.12f,-.57f,0,1,
        .875f,-.625f,.45f,-.71f,.24f,-.66f,1,0};
    c.vertexBytes.resize(sizeof(vertices));std::memcpy(c.vertexBytes.data(),vertices,sizeof(vertices));
    const float identity[]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    for(auto* matrix:{&c.world,&c.view,&c.projection})std::memcpy(matrix,identity,sizeof(identity));
    return c;
}
inline std::uint64_t TextureHash(const D3D9ReplaySnapshot& c) {
    ModelReplayStream stream;stream.target.width=c.viewport.X+c.viewport.Width;stream.target.height=c.viewport.Y+c.viewport.Height;
    if(!AppendD3D9ReplaySnapshot(stream,c))return 0;
    std::uint64_t hash=14695981039346656037ull;
    for(const auto& resource:stream.resources)for(const auto& level:resource.texture.levels) {
        for(unsigned dimension:{level.width,level.height})for(unsigned b=0;b<4;++b)hash=(hash^((dimension>>(b*8))&255))*1099511628211ull;
        for(auto byte:level.pixels)hash=(hash^byte)*1099511628211ull;
    }
    return hash;
}
inline int Run(HWND window,const char* root,const char* destination,unsigned focusX,unsigned focusY,unsigned triangle,bool textureFma=false,bool focusedSpec=false) {
    const auto vertex=std::string(textureFma?"#define MDS_MODEL_TEXTURE_FMA_DIAGNOSTIC 1\n":"")+modelDx9CompatibilitySource+modelVertexSource;
    const auto Render=[&](HWND w,const D3D9ReplaySnapshot& draw,unsigned width,unsigned height,const std::string* ps9,const std::string& ps11,
                          const std::vector<Color>* values,Result& out,IDirect3DDevice9* device) {
        return model_batch_causal::Render(w,draw,width,height,ps9,ps11,values,out,device,&vertex);
    };
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,24));CHECK(triangle<archive.draws[22].count);
    CHECK(focusX>=2 && focusY>=2 && focusX+2<archive.width && focusY+2<archive.height);
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    auto compact=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(archive.draws[22],triangle,1));
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})ground_history_isolation::State(compact,key,0);
    ground_history_isolation::State(compact,D3DRS_CULLMODE,D3DCULL_NONE);
    auto frozen=compact;for(unsigned stage=0;stage<3;++stage)CHECK(model_color_isolation::FreezeMips(frozen,stage));
    CHECK(TextureHash(compact)==TextureHash(frozen));
    std::ofstream metadata(output/"metadata.txt");metadata<<"archive="<<root<<"\ndraw=23 triangle="<<triangle<<" x="<<focusX<<" y="<<focusY<<" repeats=3 textureHash="<<TextureHash(frozen)<<" diagnosticTextureFma="<<textureFma<<" focusedSpec="<<focusedSpec<<" productionActivation=0 imageAcceptance=0\n";CHECK(metadata);
    std::ofstream observations(output/"observations.csv"),report(output/"controls.csv"),gates(output/"gates.csv");
    observations<<"geometry,mode,x,y,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA\n"<<std::setprecision(17);
    report<<"geometry,queryX,queryY,mode,repeat,x,y,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA,nativeByteR,nativeByteG,nativeByteB,nativeByteA,candidateByteR,candidateByteG,candidateByteB,candidateByteA\n"<<std::setprecision(17);
    gates<<"geometry,x,y,nativeExplicitByteExact,candidateExplicitByteExact,nativeExplicitFloatExact,candidateExplicitFloatExact\n";
    const auto production=std::string("#define MDS_MODEL_SPECULAR 1\n#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+modelPixelSource;
    unsigned controls=0,rows=0;std::array<std::array<Color,7>,2> archivedValues{};
    for(unsigned geometry=0;geometry<2;++geometry) {
        const auto c=geometry?Independent(frozen):frozen;const unsigned width=geometry?64:archive.width,height=geometry?64:archive.height;
        const Point center=geometry?Point{24,32}:Point{focusX,focusY};const std::string label=geometry?"independent":"saved";
        // One test-owned native device per target size. Every observation
        // still clears, rebinds all captured state, draws and reads fresh GPU
        // output. Avoid thousands of unrelated device creation cycles.
        ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=width;pp.BackBufferHeight=height;pp.BackBufferFormat=D3DFMT_A8R8G8B8;
        pp.BackBufferCount=1;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        ComPtr<IDirect3DDevice9> device;const auto created=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
        if(FAILED(created))std::fprintf(stderr,"causal DX9 creation HRESULT=%08lx\n",static_cast<unsigned long>(created));CHECK(SUCCEEDED(created));
        Result original;CHECK(Render(window,c,width,height,nullptr,production,nullptr,original,device.Get()));
        if(!geometry){Result before;CHECK(Render(window,compact,width,height,nullptr,production,nullptr,before,device.Get()));CHECK(before.n==original.n && before.c==original.c && before.nb.pixels==original.nb.pixels && before.cb.pixels==original.cb.pixels);}
        std::vector<Point> neighborhood;
        for(unsigned y=center.y-2;y<=center.y+2;++y)for(unsigned x=center.x-2;x<=center.x+2;++x) {
            const auto p=std::size_t(y)*width+x;
            if(original.n[p][3]==1 && original.c[p][3]==1)neighborhood.push_back({x,y});
        }
        CHECK(neighborhood.size()>=3);
        std::vector<Point> queries{center};
        for(const auto p:neighborhood)if(!focusedSpec && (p.x!=center.x || p.y!=center.y) && queries.size()<3)queries.push_back(p);
        const auto focus=std::size_t(center.y)*width+center.x;CHECK(original.n[focus][3]==1 && original.c[focus][3]==1);
        std::array<Result,7> measured;
        const char* names[]={"diffuse","specular","uv0","uv1","gradients0","sample0","sample1"};
        for(unsigned mode=0;mode<7;++mode) {
            const unsigned stage[]={0,1,2,3,2,4,5};auto ps9=PixelStage(stage[mode],false),ps11=PixelStage(stage[mode],true);
            if(mode==4){const auto change=[](std::string& text){const std::string expression="float4(input.a,0,1)";const auto at=text.find(expression);text.replace(at,expression.size(),"float4(ddx(input.a),ddy(input.a))");};change(ps9);change(ps11);}
            CHECK(Render(window,c,width,height,&ps9,ps11,nullptr,measured[mode],device.Get()));
            for(const auto point:neighborhood){const auto p=std::size_t(point.y)*width+point.x;observations<<label<<","<<names[mode]<<","<<point.x<<","<<point.y;for(float v:measured[mode].n[p])observations<<","<<v;for(float v:measured[mode].c[p])observations<<","<<v;observations<<"\n";}
            if(!geometry){archivedValues[0][mode]=measured[mode].n[focus];archivedValues[1][mode]=measured[mode].c[focus];}
        }
        for(const auto point:queries) {
            const auto at=std::size_t(point.y)*width+point.x;
            const auto constants=[&](unsigned uvSide,unsigned gradientSide,unsigned sampleSide,unsigned specSide,bool archived) {
                const auto value=[&](unsigned mode,unsigned side){return archived?archivedValues[side][mode]:side?measured[mode].c[at]:measured[mode].n[at];};
                std::vector<Color> q{value(2,uvSide),gradientSide<2?value(4,gradientSide):Color{},value(0,sampleSide),value(1,specSide),value(5,sampleSide),value(6,sampleSide),Color{}};return q;
            };
            struct Case {const char* name;const char* shader;unsigned uv,gradient,sample,spec;};
            std::vector<Case> cases{
                {"live","live",0,0,0,0},
                {"uv9_grad9","sample",0,0,0,0},{"uv11_grad9","sample",1,0,0,0},
                {"uv9_grad11","sample",0,1,0,0},{"uv11_grad11","sample",1,1,0,0},
                {"uv9_zero","sample",0,2,0,0},{"uv11_zero","sample",1,2,0,0},
                {"final_uv9","uv",0,0,0,0},{"final_uv11","uv",1,1,0,0},
                {"final_sample9","sample_final",0,0,0,0},{"final_sample11","sample_final",0,0,1,0},
                {"final_spec9","spec",0,0,0,0},{"final_spec11","spec",0,0,0,1},
                {"final_sample9_spec9","sample_spec",0,0,0,0},{"final_sample9_spec11","sample_spec",0,0,0,1},
                {"final_sample11_spec9","sample_spec",0,0,1,0},{"final_sample11_spec11","sample_spec",0,0,1,1},
                {"final_all9","all",0,0,0,0},{"final_all11","all",1,1,1,1}};
            if(geometry)for(const auto& item:std::array<Case,6>{{
                {"archived_uv9_grad9","sample",0,0,0,0},{"archived_uv11_grad9","sample",1,0,0,0},
                {"archived_uv9_grad11","sample",0,1,0,0},{"archived_uv11_grad11","sample",1,1,0,0},
                {"archived_uv9_zero","sample",0,2,0,0},{"archived_uv11_zero","sample",1,2,0,0}}})cases.push_back(item);
            if(focusedSpec)cases.erase(std::remove_if(cases.begin(),cases.end(),[](const Case& c){
                const std::string name=c.name;return name!="live" && name!="final_spec9" && name!="final_spec11" &&
                    name!="final_sample9" && name!="final_sample11" && name!="final_all9" && name!="final_all11";
            }),cases.end());
            for(const auto& item:cases) {
                const auto ps9=Shader(item.shader,false),ps11=Shader(item.shader,true);const auto q=constants(item.uv,item.gradient,item.sample,item.spec,std::string(item.name).find("archived_")==0);
                Result baseline;
                for(unsigned repeat=0;repeat<3;++repeat) {
                    Result result;CHECK(Render(window,c,width,height,&ps9,ps11,&q,result,device.Get()));
                    if(repeat)CHECK(result.n==baseline.n && result.c==baseline.c && result.nb.pixels==baseline.nb.pixels && result.cb.pixels==baseline.cb.pixels);
                    else baseline=result;
                    if(std::string(item.name)=="live" && !repeat) {
                        const bool nb=std::memcmp(result.nb.pixels.data()+at*4,original.nb.pixels.data()+at*4,4)==0,cb=std::memcmp(result.cb.pixels.data()+at*4,original.cb.pixels.data()+at*4,4)==0;
                        gates<<label<<","<<point.x<<","<<point.y<<","<<nb<<","<<cb<<","<<(result.n[at]==original.n[at])<<","<<(result.c[at]==original.c[at])<<"\n";
                        CHECK(nb && cb && result.n[at]==original.n[at] && result.c[at]==original.c[at]);
                    }
                    // Always include the query and every covered neighbor.
                    // Statistics never compare uninitialized/background pixels.
                    for(const auto pixel:neighborhood){const auto p=std::size_t(pixel.y)*width+pixel.x;
                        report<<label<<","<<point.x<<","<<point.y<<","<<item.name<<","<<repeat<<","<<pixel.x<<","<<pixel.y;
                        for(float v:result.n[p])report<<","<<v;for(float v:result.c[p])report<<","<<v;
                        for(unsigned k=0;k<4;++k)report<<","<<unsigned(result.nb.pixels[p*4+k]);for(unsigned k=0;k<4;++k)report<<","<<unsigned(result.cb.pixels[p*4+k]);report<<"\n";++rows;
                    }
                    report.flush();++controls;
                }
                std::printf("causal geometry=%s query=%u,%u mode=%s repeats=3\n",label.c_str(),point.x,point.y,item.name);std::fflush(stdout);
            }
        }
    }
    CHECK(observations && report && gates);std::ofstream summary(output/"summary.txt");summary<<"complete=1 controls="<<controls<<" rows="<<rows<<" repeats=3 geometries=2 frozenMipsExact=1 runtimeConstants=1 productionActivation=0 imageAcceptance=0\n";CHECK(summary);return 0;
}
}
