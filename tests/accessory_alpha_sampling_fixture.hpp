#pragma once
// Saved real geometry and generated constant-alpha controls only. No changes
// to production shader policy. Native FF float output and diagnostic PS output
// are separate observations, not interchangeable captures.
namespace accessory_alpha_sampling {
using Color=model_batch_color::Color;
inline std::string Pixel(unsigned mode,bool eleven){
    const auto inputs=eleven?"float4 position:SV_POSITION;float4 diffuse:COLOR0;float2 uv:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 specular:COLOR1;":"float4 diffuse:COLOR0;float4 specular:COLOR1;float2 uv:TEXCOORD0;";
    const auto texture=eleven?"Texture2D tex:register(t0);SamplerState sampling:register(s0);":"sampler2D tex:register(s0);";
    const auto sample=eleven?"tex.Sample(sampling,i.uv)":"tex2D(tex,i.uv)";
    std::string body;
    if(mode==0)body="return float4(i.uv,0,1);";
    if(mode==1)body="return float4(ddx(i.uv),ddy(i.uv));";
    if(mode==2)body="return "+std::string(sample)+";";
    if(mode==3)body="return i.diffuse;";
    if(mode>=4){body="float a=i.diffuse.a*"+std::string(sample)+".a;";
        if(mode==4)body+="return float4(a,a,a,a);";
        if(mode==5)body+="float q=floor(saturate(a)*255.0+0.5);return float4(a,a*255.0,q,q>=1?1:0);";
        if(mode==6)body+="float q=floor(saturate(a)*255.0+0.5);if(q<1)discard;return float4(1,1,1,a);";
        if(mode==7)body+="if(a<1.0/255.0)discard;return float4(1,1,1,a);";}
    return std::string(texture)+"struct I{"+inputs+"};float4 main(I i):"+(eleven?"SV_TARGET":"COLOR0")+"{"+body+"}";
}
inline D3D9ReplaySnapshot Unrestricted(D3D9ReplaySnapshot c){
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})ground_history_isolation::State(c,key,0);
    ground_history_isolation::State(c,D3DRS_CULLMODE,D3DCULL_NONE);return c;
}
inline D3D9ReplaySnapshot ConstantAlpha(const D3D9ReplaySnapshot& source){
    auto c=ground_endpoint_depth::Id(source,false);c.accessoryMaterial=true;c.material.Emissive={1,1,1,1};
    Stage(c,0,D3DTSS_COLOROP,D3DTOP_MODULATE);Stage(c,0,D3DTSS_COLORARG1,D3DTA_TEXTURE);Stage(c,0,D3DTSS_COLORARG2,D3DTA_DIFFUSE);
    Stage(c,0,D3DTSS_ALPHAOP,D3DTOP_MODULATE);Stage(c,0,D3DTSS_ALPHAARG1,D3DTA_TEXTURE);Stage(c,0,D3DTSS_ALPHAARG2,D3DTA_CURRENT);
    c.textureInfo[0]={true,D3DFMT_A8R8G8B8,1,1,1,0,false};c.textureBytes[0]={255,255,255,255};
    c=Unrestricted(c);ground_history_isolation::State(c,D3DRS_ALPHAFUNC,D3DCMP_GREATEREQUAL);return c;
}
inline int Run(HWND window,const char* archive,const char* destination){
    ground_history_isolation::Archive capture;CHECK(capture.Load(archive,66));
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    auto source=Unrestricted(capture.draws[64]);source.accessoryMaterial=true;
    CHECK(source.stride==32 && source.material.Diffuse.a==.5f);
    CHECK(std::any_of(source.renderStates.begin(),source.renderStates.end(),[](const auto& s){return s.key==D3DRS_ALPHAFUNC && s.value==D3DCMP_GREATEREQUAL;}));
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(bundle);
    ModelReplayStream converted;converted.target.width=capture.width;converted.target.height=capture.height;converted.events.push_back({1,ModelReplayOp::Clear});CHECK(AppendD3D9ReplaySnapshot(converted,source));
    const auto& layout=converted.events.back().draw.pipeline.shader.layout;CHECK(layout.stages[0].role!=MaterialTextureRole::None && layout.stages[1].role==MaterialTextureRole::None);
    const std::vector<std::array<unsigned,2>> points{{1040,725},{1097,740},{1136,757},{1163,776},{1041,725},{1097,741}};
    std::ofstream floats(output/"float_stages.csv"),bytes(output/"byte_controls.csv"),scan(output/"constant_alpha.csv");
    floats<<"mode,repeat,point,x,y,dx9R,dx9G,dx9B,dx9Alpha,dx11R,dx11G,dx11B,dx11Alpha,dx9AlphaBits,dx11AlphaBits\n"<<std::setprecision(17);
    bytes<<"mode,repeat,point,x,y,dx9R,dx9G,dx9B,dx9Alpha,dx11R,dx11G,dx11B,dx11Alpha\n";
    scan<<"inputAlpha,inputBits,comparison,repeat,point,dx9FloatAlpha,dx11FloatAlpha,dx9Alpha,dx11Alpha,dx9PassRef1,dx11PassRef1\n"<<std::setprecision(17);
    const auto floatRows=[&](const char* name,unsigned repeat,const std::vector<Color>& a,const std::vector<Color>& b){for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const auto at=std::size_t(xy[1])*capture.width+xy[0];floats<<name<<","<<repeat<<","<<p<<","<<xy[0]<<","<<xy[1];
        for(float f:a[at])floats<<","<<f;if(b.empty())floats<<",nan,nan,nan,nan";else for(float f:b[at])floats<<","<<f;
        floats<<","<<ground_endpoint_depth::Bits(a[at][3])<<","<<(b.empty()?0:ground_endpoint_depth::Bits(b[at][3]))<<"\n";}floats.flush();};
    const auto byteRows=[&](const char* name,unsigned repeat,const RgbaImage& a,const RgbaImage& b){for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const auto at=(std::size_t(xy[1])*capture.width+xy[0])*4;bytes<<name<<","<<repeat<<","<<p<<","<<xy[0]<<","<<xy[1];for(unsigned c=0;c<4;++c)bytes<<","<<unsigned(a.pixels[at+c]);for(unsigned c=0;c<4;++c)bytes<<","<<unsigned(b.pixels[at+c]);bytes<<"\n";}bytes.flush();};
    RgbaImage n,r;std::vector<Color> a,b;
    for(unsigned repeat=0;repeat<3;++repeat){CHECK(NativeImage(window,{source},1,n,nullptr,capture.width,capture.height,0xff000000,&a));floatRows("fixed_function_float",repeat,a,{});}
    const char* names[]{"uv","gradients","sample0","diffuse","alpha_product","rounded_byte","rounded_gate","normalized_gate"};
    for(unsigned mode=0;mode<8;++mode)for(unsigned repeat=0;repeat<3;++repeat){const auto ps9=Pixel(mode,false),ps11=Pixel(mode,true);
        CHECK(NativeImage(window,{source},1,n,nullptr,capture.width,capture.height,0xff000000,&a,&ps9));CHECK(model_batch_color::Stage11(source,capture.width,capture.height,ps11,true,r,b,{0,0,0,1}));floatRows(names[mode],repeat,a,b);
        if(mode>=6){CHECK(NativeImage(window,{source},1,n,nullptr,capture.width,capture.height,0xff000000,nullptr,&ps9));CHECK(model_batch_color::Stage11(source,capture.width,capture.height,ps11,false,r,b,{0,0,0,1}));byteRows(names[mode],repeat,n,r);}
    }
    for(unsigned enabled=0;enabled<2;++enabled)for(unsigned repeat=0;repeat<3;++repeat){auto c=source;ground_history_isolation::State(c,D3DRS_ALPHATESTENABLE,enabled);
        CHECK(accessory_depth_threshold::Render(window,capture,bundle,{c},n,r,0xff000000));byteRows(enabled?"production_ref1":"production_no_alpha_test",repeat,n,r);}
    // Generated constant-alpha texture and white emissive material remove
    // sampling/interpolation uncertainty. Sweep around half-byte and byte edges.
    auto constant=ConstantAlpha(source);ground_history_isolation::State(constant,D3DRS_ALPHAREF,1);
    std::vector<float> values{0,.25f/255,.49f/255,.51f/255,.75f/255,.99f/255,1.01f/255,1.49f/255,1.51f/255,2.f/255};
    for(float edge:{.5f/255,1.f/255,1.5f/255})for(int step=-2;step<=2;++step)values.push_back(ground_endpoint_depth::Float(ground_endpoint_depth::Bits(edge)+step));
    std::map<unsigned,std::array<float,2>> observed;
    for(float value:values)for(unsigned comparison:{D3DCMP_GREATEREQUAL,D3DCMP_EQUAL,D3DCMP_NOTEQUAL})for(unsigned repeat=0;repeat<3;++repeat){constant.material.Diffuse.a=value;ground_history_isolation::State(constant,D3DRS_ALPHAFUNC,comparison);ground_history_isolation::State(constant,D3DRS_ALPHATESTENABLE,FALSE);
        const auto xy=points[0];const auto focus=std::size_t(xy[1])*capture.width+xy[0];const auto key=ground_endpoint_depth::Bits(value);
        if(!observed.count(key)){CHECK(NativeImage(window,{constant},1,n,nullptr,capture.width,capture.height,0xff000000,&a));
            CHECK(model_batch_color::Stage11(constant,capture.width,capture.height,Pixel(4,true),true,r,b,{0,0,0,1}));observed[key]={a[focus][3],b[focus][3]};}
        CHECK(accessory_depth_threshold::Render(window,capture,bundle,{constant},n,r,0xff000000));const auto at=focus*4;const auto na=n.pixels[at+3],ra=r.pixels[at+3];
        ground_history_isolation::State(constant,D3DRS_ALPHATESTENABLE,TRUE);CHECK(accessory_depth_threshold::Render(window,capture,bundle,{constant},n,r,0xff000000));
        scan<<value<<","<<key<<","<<comparison<<","<<repeat<<",0,"<<observed[key][0]<<","<<observed[key][1]<<","<<unsigned(na)<<","<<unsigned(ra)<<","<<(n.pixels[at]!=0)<<","<<(r.pixels[at]!=0)<<"\n";scan.flush();}
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 repeats=3 floatRows=162 byteRows=72 constantRows=225 fixedFunctionFloatSeparate=1 nativeDiagnosticPsSeparate=1 productionActivation=0 imageAcceptance=0 adapter="<<bundle.adapterName<<"\n";
    CHECK(floats && bytes && scan && summary && bundle.swapchain->Retire());return 0;
}
inline int References(HWND window,const char* archive,const char* destination,bool fine=false,bool reuse=false){
    ground_history_isolation::Archive capture;CHECK(capture.Load(archive,66));
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(bundle);
    auto c=ConstantAlpha(capture.draws[64]);const unsigned x=1040,y=725;const auto focus=std::size_t(y)*capture.width+x;
    // Keep one explicit HAL device during this long numerical scan. This is
    // a test-only observation mode, not evidence of device-creation stability.
    ComPtr<IDirect3D9> api;ComPtr<IDirect3DDevice9> native;
    if(reuse){api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
    D3DPRESENT_PARAMETERS pp{};pp.BackBufferWidth=capture.width;pp.BackBufferHeight=capture.height;pp.BackBufferFormat=D3DFMT_A8R8G8B8;
    pp.BackBufferCount=1;pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.hDeviceWindow=window;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
    const auto creation=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&native);
    if(FAILED(creation))std::fprintf(stderr,"reference scan DX9 creation HRESULT=%08lx\n",static_cast<unsigned long>(creation));CHECK(SUCCEEDED(creation));}
    std::ofstream report(output/"reference_scan.csv");report<<"reference,step,bytePosition,inputAlpha,repeat,dx9FloatAlpha,dx11FloatAlpha,dx9Byte,dx11Byte,dx9Pass,dx11Pass\n"<<std::setprecision(17);
    for(unsigned reference:{1u,2u,17u,127u,254u})for(unsigned step=0;step<=16;++step){const float bytePosition=reference-1+(fine?.5f+step/256.f:step/16.f);const float alpha=bytePosition/255.f;
        c.material.Diffuse.a=alpha;ground_history_isolation::State(c,D3DRS_ALPHAREF,reference);ground_history_isolation::State(c,D3DRS_ALPHATESTENABLE,FALSE);
        RgbaImage n,r;std::vector<Color> a,b;CHECK(NativeImage(window,{c},1,n,nullptr,capture.width,capture.height,0xff000000,&a,nullptr,native.Get()));
        CHECK(model_batch_color::Stage11(c,capture.width,capture.height,Pixel(4,true),true,r,b,{0,0,0,1}));
        const auto floats=std::array<float,2>{a[focus][3],b[focus][3]};
        for(unsigned repeat=0;repeat<3;++repeat){ground_history_isolation::State(c,D3DRS_ALPHATESTENABLE,FALSE);
            CHECK(accessory_depth_threshold::Render(window,capture,bundle,{c},n,r,0xff000000,native.Get()));const auto na=n.pixels[focus*4+3],ra=r.pixels[focus*4+3];
            ground_history_isolation::State(c,D3DRS_ALPHATESTENABLE,TRUE);CHECK(accessory_depth_threshold::Render(window,capture,bundle,{c},n,r,0xff000000,native.Get()));
            report<<reference<<","<<step<<","<<bytePosition<<","<<alpha<<","<<repeat<<","<<floats[0]<<","<<floats[1]<<","<<unsigned(na)<<","<<unsigned(ra)<<","<<(n.pixels[focus*4]!=0)<<","<<(r.pixels[focus*4]!=0)<<"\n";report.flush();}
    }
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 references=5 steps=17 repeats=3 rows=255 fine="<<fine<<" nativeMeasurementDeviceReuse="<<reuse<<" productionActivation=0 imageAcceptance=0 adapter="<<bundle.adapterName<<"\n";
    CHECK(report && summary && bundle.swapchain->Retire());return 0;
}
}
