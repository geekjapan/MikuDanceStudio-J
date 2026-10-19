#pragma once
// Generated geometry/texture only; no PMM capture required. Observe original
// DX9 FF output and unchanged DX11 production compatibility separately.
namespace alpha_conversion_independent {
inline int Run(HWND window,const char* inputs,const char* destination){
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));
    struct Input{unsigned id,reference,bits;};std::vector<Input> cases;
    std::ifstream file(inputs);std::string line;CHECK(std::getline(file,line) && line=="case,reference,inputBits");
    while(std::getline(file,line)){Input c;CHECK(std::sscanf(line.c_str(),"%u,%u,%u",&c.id,&c.reference,&c.bits)==3);CHECK(c.reference<=255 && std::isfinite(ground_endpoint_depth::Float(c.bits)));cases.push_back(c);}
    CHECK(!cases.empty() && cases.size()<=64);std::filesystem::create_directories(output);
    ground_history_isolation::Archive target;target.width=target.height=128;
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(bundle);
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
    D3DPRESENT_PARAMETERS pp{};pp.BackBufferWidth=pp.BackBufferHeight=128;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.BackBufferCount=1;
    pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.hDeviceWindow=window;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
    ComPtr<IDirect3DDevice9> native;const auto hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&native);
    if(FAILED(hr))std::fprintf(stderr,"independent alpha DX9 HRESULT=%08lx\n",static_cast<unsigned long>(hr));CHECK(SUCCEEDED(hr));
    std::ofstream report(output/"independent.csv");report<<"geometry,case,reference,inputBits,comparison,repeat,x,y,dx9FloatAlpha,dx11FloatAlpha,dx9Byte,dx11Byte,dx9Pass,dx11Pass\n"<<std::setprecision(17);
    for(unsigned geometry=0;geometry<2;++geometry){auto c=accessory_alpha_sampling::ConstantAlpha(Fixture());
        c.viewport=geometry?D3DVIEWPORT9{17,11,80,96,0,1}:D3DVIEWPORT9{0,0,64,64,0,1};
        if(geometry){const float vertices[]{-.8f,-.8f,.5f,0,0,1,0,0,-.8f,.8f,.5f,0,0,1,0,1,.8f,-.8f,.5f,0,0,1,1,0,.8f,.8f,.5f,0,0,1,1,1};
            c.vertexBytes.resize(sizeof(vertices));std::memcpy(c.vertexBytes.data(),vertices,sizeof(vertices));c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};c.count=2;c.vertices=4;
            c.projection._14=.125f;c.projection._24=-.0625f;}
        const unsigned x=geometry?50:16,y=geometry?50:40;const auto at=std::size_t(y)*128+x;
        for(const auto& input:cases){c.material.Diffuse.a=ground_endpoint_depth::Float(input.bits);ground_history_isolation::State(c,D3DRS_ALPHAREF,input.reference);
            for(unsigned repeat=0;repeat<3;++repeat){ground_history_isolation::State(c,D3DRS_ALPHATESTENABLE,FALSE);RgbaImage n,r;std::vector<model_batch_color::Color> a,b;
                CHECK(NativeImage(window,{c},1,n,nullptr,128,128,0xff000000,&a,nullptr,native.Get()));
                CHECK(model_batch_color::Stage11(c,128,128,accessory_alpha_sampling::Pixel(4,true),true,r,b,{0,0,0,1}));
                const auto fa=a[at][3],fb=b[at][3];CHECK(fa>=0 && fa<1 && fb>=0 && fb<1);
                CHECK(accessory_depth_threshold::Render(window,target,bundle,{c},n,r,0xff000000,native.Get()));const auto na=n.pixels[at*4+3],ra=r.pixels[at*4+3];
                for(unsigned comparison:{D3DCMP_GREATEREQUAL,D3DCMP_EQUAL,D3DCMP_NOTEQUAL}){ground_history_isolation::State(c,D3DRS_ALPHATESTENABLE,TRUE);ground_history_isolation::State(c,D3DRS_ALPHAFUNC,comparison);
                    CHECK(accessory_depth_threshold::Render(window,target,bundle,{c},n,r,0xff000000,native.Get()));
                    report<<geometry<<","<<input.id<<","<<input.reference<<","<<input.bits<<","<<comparison<<","<<repeat<<","<<x<<","<<y<<","<<fa<<","<<fb<<","<<unsigned(na)<<","<<unsigned(ra)<<","<<(n.pixels[at*4]!=0)<<","<<(r.pixels[at*4]!=0)<<"\n";report.flush();}
            }
        }
    }
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 generatedGeometry=2 inputs="<<cases.size()<<" comparisons=3 repeats=3 rows="<<cases.size()*18<<" nativeMeasurementDeviceReuse=1 productionActivation=0 imageAcceptance=0 adapter="<<bundle.adapterName<<"\n";
    CHECK(report && summary && bundle.swapchain->Retire());return 0;
}
}
