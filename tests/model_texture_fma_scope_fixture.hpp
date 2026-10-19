#pragma once
// Predetermined, archive-free coverage. No observations select coefficients.
// The last matrix and second normal set are independent validation inputs.
namespace model_texture_fma_scope {
inline int Run(HWND window,const char* destination) {
    using model_batch_color::Color;
    const std::filesystem::path output(destination);std::filesystem::create_directories(output);
    std::ofstream report(output/"scope.csv");
    report<<"matrix,normalSet,normalize,stage,holdout,repeat,baselineFloatPixels,candidateFloatPixels,regressedFloatPixels,rgbaPixels\n";
    const float matrices[][16]={
        {1,0,0,0, 0,-1,0,0, 0,0,1,0, .5f,.25f,0,1},
        {.317f,-.219f,0,0, -.137f,.473f,0,0, .591f,-.283f,1,0, .431f,.613f,0,1},
        {-.731f,.419f,0,0, .257f,-.167f,0,0, -.311f,.683f,1,0, -.293f,.157f,0,1},
        {.193f,-.827f,0,0, -.619f,.359f,0,0, .443f,.271f,1,0, .709f,-.337f,0,1}};
    const float normals[][9]={
        {.13f,.37f,-.91f, -.83f,.11f,-.47f, .007f,-.015f,.019f},
        {-1.33f,-.27f,.51f, .61f,.73f,-.89f, .25f,1.75f,-2.5f}};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=64;
    pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.BackBufferCount=1;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
    ComPtr<IDirect3DDevice9> native;const auto hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&native);
    if(FAILED(hr))std::fprintf(stderr,"texture FMA DX9 creation=%08lx\n",static_cast<unsigned long>(hr));CHECK(SUCCEEDED(hr));
    const auto baseline=model_toon_rounding::VertexSource(0),candidate=model_toon_rounding::VertexSource(1);
    const auto pixel=std::string("#define MDS_MODEL_SPECULAR 1\n#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+modelPixelSource;
    unsigned observations=0,candidateFailures=0,regressions=0,baselineFailures=0;
    for(unsigned matrix=0;matrix<4;++matrix)for(unsigned set=0;set<2;++set)for(unsigned normalize=0;normalize<2;++normalize)for(unsigned stage=0;stage<3;++stage) {
        auto c=Fixture();Set(c,D3DRS_NORMALIZENORMALS,normalize);Set(c,D3DRS_ZENABLE,0);Set(c,D3DRS_ZWRITEENABLE,0);
        Set(c,D3DRS_LIGHTING,1);Set(c,D3DRS_AMBIENT,0xffffffff);c.material={};
        c.material.Diffuse={1,1,1,1};c.material.Ambient={1,1,1,1};
        for(unsigned v=0;v<3;++v)std::memcpy(c.vertexBytes.data()+v*32+12,normals[set]+v*3,12);
        c.stageStates.clear();c.samplerStates.clear();
        for(unsigned s=0;s<3;++s) {
            for(auto kv:{std::pair<unsigned,DWORD>{D3DTSS_COLOROP,D3DTOP_MODULATE},{D3DTSS_COLORARG1,D3DTA_TEXTURE},{D3DTSS_COLORARG2,s?D3DTA_CURRENT:D3DTA_DIFFUSE},
                {D3DTSS_ALPHAOP,D3DTOP_MODULATE},{D3DTSS_ALPHAARG1,D3DTA_TEXTURE},{D3DTSS_ALPHAARG2,D3DTA_CURRENT},{D3DTSS_RESULTARG,D3DTA_CURRENT},
                {D3DTSS_TEXCOORDINDEX,s==stage?D3DTSS_TCI_CAMERASPACENORMAL:0},{D3DTSS_TEXTURETRANSFORMFLAGS,s==stage?D3DTTFF_COUNT2:0}})c.stageStates.push_back({s,kv.first,kv.second});
            for(auto kv:{std::pair<unsigned,DWORD>{D3DSAMP_MINFILTER,D3DTEXF_POINT},{D3DSAMP_MAGFILTER,D3DTEXF_POINT},{D3DSAMP_MIPFILTER,D3DTEXF_POINT},
                {D3DSAMP_ADDRESSU,D3DTADDRESS_CLAMP},{D3DSAMP_ADDRESSV,D3DTADDRESS_CLAMP},{D3DSAMP_MAXANISOTROPY,1},
                {D3DSAMP_MIPMAPLODBIAS,0},{D3DSAMP_MAXMIPLEVEL,0},{D3DSAMP_SRGBTEXTURE,0}})c.samplerStates.push_back({s,kv.first,kv.second});
            c.textureInfo[s]={true,D3DFMT_A8R8G8B8,2,2,1,0,false};
            c.textureBytes[s]={17,39,71,255, 53,97,131,255, 163,191,211,255, 227,239,251,255};
            std::memcpy(&c.textureMatrices[s],matrices[matrix],64);
        }
        c.stageStates.push_back({3,D3DTSS_COLOROP,D3DTOP_DISABLE});
        ModelReplayStream validation;validation.target.width=validation.target.height=64;
        validation.events.push_back({1,ModelReplayOp::Clear});
        const auto converted=AppendD3D9ReplaySnapshot(validation,c);
        if(!converted)std::fprintf(stderr,"scope conversion: %s\n",converted.reason.c_str());CHECK(converted);
        detail::ModelConstants constants;const auto& pipeline=validation.events.back().draw.pipeline;
        CHECK(detail::BuildModelConstants(pipeline,*pipeline.viewport,true,constants));
        // Select the requested varying on both APIs, including TEXCOORD2.
        const auto inputs9="float4 diffuse:COLOR0;float4 specular:COLOR1;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;";
        const auto inputs11="float4 position:SV_POSITION;float4 diffuse:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 specular:COLOR1;";
        const auto selected=stage==0?"a":stage==1?"b":"d";
        const auto ps9=std::string("struct Input{")+inputs9+"};float4 main(Input i):COLOR0{return float4(i."+selected+",0,1);}";
        const auto ps11=std::string("struct Input{")+inputs11+"};float4 main(Input i):SV_TARGET{return float4(i."+selected+",0,1);}";
        std::vector<Color> previousNative,previousCandidate,previousBaseline;std::vector<unsigned char> previousRgba;
        for(unsigned repeat=0;repeat<3;++repeat) {
            RgbaImage unused,nb,cb;std::vector<Color> n,b,f,scratch;
            CHECK(NativeImage(window,{c},1,unused,nullptr,64,64,0xffffffff,&n,&ps9,native.Get()));
            CHECK(model_batch_color::Stage11(c,64,64,ps11,true,unused,b,{1,1,1,1},.5f,nullptr,&baseline));
            CHECK(model_batch_color::Stage11(c,64,64,ps11,true,unused,f,{1,1,1,1},.5f,nullptr,&candidate));
            if(!repeat && !matrix && !set && !normalize && !stage) {
                const auto p=std::size_t(40)*64+10;
                std::printf("scope focus native=(%.9g,%.9g,%.9g,%.9g) baseline=(%.9g,%.9g,%.9g,%.9g) candidate=(%.9g,%.9g,%.9g,%.9g)\n",n[p][0],n[p][1],n[p][2],n[p][3],b[p][0],b[p][1],b[p][2],b[p][3],f[p][0],f[p][1],f[p][2],f[p][3]);std::fflush(stdout);
            }
            CHECK(NativeImage(window,{c},1,nb,nullptr,64,64,0xffffffff,nullptr,nullptr,native.Get()));
            CHECK(model_batch_color::Stage11(c,64,64,pixel,false,cb,scratch,{1,1,1,1},.5f,nullptr,&candidate));
            if(repeat)CHECK(n==previousNative && f==previousCandidate && b==previousBaseline && cb.pixels==previousRgba);
            previousNative=n;previousCandidate=f;previousBaseline=b;previousRgba=cb.pixels;
            unsigned bd=0,fd=0,regressed=0,rd=0;
            unsigned covered=0;for(const auto& value:n)covered+=value[2]==0 && value[3]==1;
            CHECK(covered>1000);
            for(unsigned p=0;p<n.size();++p){bd+=n[p]!=b[p];fd+=n[p]!=f[p];regressed+=n[p]==b[p] && n[p]!=f[p];}
            for(unsigned p=0;p<nb.pixels.size()/4;++p)rd+=std::memcmp(nb.pixels.data()+p*4,cb.pixels.data()+p*4,4)!=0;
            report<<matrix<<","<<set<<","<<normalize<<","<<stage<<","<<(matrix==3 || set==1)<<","<<repeat<<","<<bd<<","<<fd<<","<<regressed<<","<<rd<<"\n";report.flush();
            ++observations;candidateFailures+=fd!=0 || rd!=0;regressions+=regressed!=0;baselineFailures+=bd!=0;
        }
        std::printf("texture FMA scope matrix=%u normalSet=%u normalize=%u stage=%u\n",matrix,set,normalize,stage);std::fflush(stdout);
    }
    std::ofstream summary(output/"summary.txt");summary<<"observations="<<observations<<" controls=48 repeats=3 baselineFailures="<<baselineFailures<<" candidateFailures="<<candidateFailures<<" regressions="<<regressions<<"\n";
    CHECK(report && summary && baselineFailures>0);return candidateFailures || regressions?33:0;
}
}
