#pragma once
int FloatInterpolationProbe(const std::filesystem::path& root,bool sweep=false,bool triangleOrders=false,bool geometry=false,bool targeted=false){
    std::vector<std::string> captureTargets;if(targeted){std::ifstream input(root/"capture_targets.txt");std::string line;while(std::getline(input,line))if(!line.empty())captureTargets.push_back(line);if(captureTargets.empty())return 1;}
    std::filesystem::create_directories(root);std::ofstream log(root/"float.log");
    HWND window=CreateWindowW(L"STATIC",L"Float interpolation",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window)return 77;struct Cleanup{HWND h;~Cleanup(){DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DADAPTER_IDENTIFIER9 adapter{};api->GetAdapterIdentifier(0,0,&adapter);log<<"ADAPTER "<<adapter.Description<<"\n";
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=64;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;
    ComPtr<IDirect3DDevice9> d;HRESULT hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d);if(FAILED(hr)){log<<"UNAVAILABLE createDevice="<<std::hex<<hr<<"\n";return 77;}
    for(auto state:{D3DRS_LIGHTING,D3DRS_SPECULARENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_FOGENABLE,D3DRS_DITHERENABLE,D3DRS_SRGBWRITEENABLE})if(FAILED(d->SetRenderState(state,FALSE)))return 1;
    if(FAILED(d->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE))||FAILED(d->SetRenderState(D3DRS_COLORWRITEENABLE,15)))return 1;
    for(auto state:{D3DTSS_COLOROP,D3DTSS_ALPHAOP})if(FAILED(d->SetTextureStageState(0,state,D3DTOP_SELECTARG1)))return 1;
    for(auto state:{D3DTSS_COLORARG1,D3DTSS_ALPHAARG1})if(FAILED(d->SetTextureStageState(0,state,D3DTA_DIFFUSE)))return 1;
    if(FAILED(d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE)))return 1;
    struct Vertex{float x,y,z,rhw;DWORD color;};
    D3DVERTEXELEMENT9 elements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_D3DCOLOR,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
    ComPtr<IDirect3DVertexDeclaration9> declaration;if(FAILED(d->CreateVertexDeclaration(elements,&declaration)))return 1;
    ComPtr<IDirect3DVertexShader9> vs;ComPtr<IDirect3DPixelShader9> ps[3];
    for(unsigned variant=0;variant<3;++variant){
        std::string code="float4 K:register(c0);struct O{float4 p:POSITION;float4 c:COLOR0;};O vs(float4 p:POSITION,float4 c:COLOR0){O o;o.p=float4(p.x/32-1,1-p.y/32,p.z,1);o.c=c;return o;}";
        if(variant==0)code+="float4 ps(float4 c:COLOR0):COLOR0{return c;}";
        if(variant==1)code+="float4 ps(float2 p:VPOS):COLOR0{return float4((K.z+(p.x+0.5)*K.x)/255,(K.w+(p.y+0.5)*K.y)/255,64./255,1);}";
        if(variant==2)code+="float4 ps():COLOR0{return float4(K.xxx,1);}";
        ComPtr<ID3DBlob> vb,pb,error;if(FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"vs","vs_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vb,&error))||FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"ps","ps_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&pb,&error)))return 1;
        if(variant==0&&FAILED(d->CreateVertexShader(static_cast<const DWORD*>(vb->GetBufferPointer()),&vs)))return 1;
        if(FAILED(d->CreatePixelShader(static_cast<const DWORD*>(pb->GetBufferPointer()),&ps[variant])))return 1;
    }
    D3DDISPLAYMODE display{};if(FAILED(api->GetAdapterDisplayMode(0,&display)))return 1;log<<"DISPLAY format="<<unsigned(display.Format)<<"\n";
    unsigned formats=0,failed=0;
    for(auto format:{D3DFMT_A8R8G8B8,D3DFMT_A16B16G16R16F,D3DFMT_A32B32G32R32F}){
        hr=api->CheckDeviceFormat(0,D3DDEVTYPE_HAL,display.Format,D3DUSAGE_RENDERTARGET,D3DRTYPE_SURFACE,format);log<<"FORMAT id="<<unsigned(format)<<" support="<<std::hex<<hr<<std::dec<<"\n";if(FAILED(hr))continue;
        ComPtr<IDirect3DSurface9> target,system;if(FAILED(d->CreateRenderTarget(64,64,format,D3DMULTISAMPLE_NONE,0,FALSE,&target,nullptr))||FAILED(d->CreateOffscreenPlainSurface(64,64,format,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
        if(FAILED(d->SetRenderTarget(0,target.Get())))return 1;D3DVIEWPORT9 viewport{0,0,64,64,0,1};if(FAILED(d->SetViewport(&viewport)))return 1;++formats;
        for(unsigned axis=0;axis<(triangleOrders||geometry?1u:2u);++axis)for(unsigned spanIndex=0;spanIndex<(sweep?4u:1u);++spanIndex)for(unsigned palette=0;palette<(sweep?4u:1u);++palette){
            const auto v=[&](float x,float y){const auto byte=[](float f){return DWORD(std::floor((std::max)(0.f,(std::min)(255.f,f))+.5f));};return Vertex{x,y,.5f,1,0xff000040|(byte(x*4+.5f)<<16)|(byte(y*4+.5f)<<8)};};
            for(unsigned geometryCase=0;geometryCase<(geometry?4u:1u);++geometryCase){
            if(targeted){const std::string key="g"+std::to_string(geometryCase)+"-s"+std::to_string(spanIndex)+"-c"+std::to_string(palette);bool selected=false;for(const auto& target:captureTargets)selected|=target==key;if(!selected)continue;}
            const float spans[]={32.f,48.f,64.f,63.75f};const float span=spans[spanIndex];const float right=sweep?span-.5f:axis?63.5f:30.5f,bottom=sweep?(geometry&&geometryCase>=2?span*.5f-.5f:span-.5f):axis?30.5f:63.5f;
            Vertex vertices[]={v(-.5f,-.5f),v(right,-.5f),v(-.5f,bottom),v(right,-.5f),v(right,bottom),v(-.5f,bottom)};
            if(sweep){const unsigned starts[]={64,0,255,63},ends[]={64,255,0,65};for(auto& vertex:vertices){const auto byte=[](float value){return DWORD(std::floor(value+.5f));};const float tX=(vertex.x+.5f)/span,tY=(vertex.y+.5f)/span;const float start=float(geometry&&starts[palette]==255?254:starts[palette]),end=float(geometry&&ends[palette]==255?254:ends[palette]);vertex.color=0xff000040|(byte(start+tX*(end-start))<<16)|(byte(start+tY*(end-start))<<8);}}
            if(geometry&&(geometryCase==1||geometryCase==3)){Vertex alternate[]={vertices[0],vertices[1],vertices[4],vertices[0],vertices[4],vertices[2]};std::memcpy(vertices,alternate,sizeof(vertices));}
            for(unsigned orderCase=0;orderCase<(triangleOrders?13u:1u);++orderCase){
            const unsigned permutations[6][3]={{0,1,2},{1,2,0},{2,0,1},{0,2,1},{2,1,0},{1,0,2}};
            Vertex drawVertices[6];unsigned primitiveCount=2;
            if(orderCase){primitiveCount=1;const unsigned triangle=(orderCase-1)/6,permutation=(orderCase-1)%6;for(unsigned index=0;index<3;++index)drawVertices[index]=vertices[triangle*3+permutations[permutation][index]];}
            else std::memcpy(drawVertices,vertices,sizeof(vertices));
            std::vector<unsigned char> fixedImage;
            for(unsigned path=0;path<(sweep?4u:7u);++path){
                if(FAILED(d->SetVertexShader(path==0||path==1?nullptr:vs.Get()))||FAILED(d->SetPixelShader(path==0?nullptr:ps[path<=2?0:path==3?1:2].Get())))return 1;
                if(path<=1){if(FAILED(d->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE)))return 1;}else if(FAILED(d->SetVertexDeclaration(declaration.Get())))return 1;
                const float originR=float((vertices[0].color>>16)&255),originG=float((vertices[0].color>>8)&255);
                float K[]={path>=4?113.5546875f/255.f:(float((vertices[1].color>>16)&255)-originR)/(right+.5f),(float((vertices[2].color>>8)&255)-originG)/(bottom+.5f),originR,originG};if(path==5)K[0]=std::nextafter(K[0],0.f);if(path==6)K[0]=std::nextafter(K[0],1.f);if(FAILED(d->SetPixelShaderConstantF(0,K,1)))return 1;
                std::vector<unsigned char> baseline;const unsigned bytes=format==D3DFMT_A8R8G8B8?4:format==D3DFMT_A16B16G16R16F?8:16;
                for(unsigned repeat=0;repeat<10;++repeat){
                    if(FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET,0,1,0))||FAILED(d->BeginScene()))return 1;HRESULT drawn=d->DrawPrimitiveUP(D3DPT_TRIANGLELIST,primitiveCount,drawVertices,sizeof(Vertex)),ended=d->EndScene();
                    if(FAILED(drawn)||FAILED(ended)||FAILED(d->GetRenderTargetData(target.Get(),system.Get())))return 1;
                    D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;std::vector<unsigned char> image(64*64*bytes);for(unsigned y=0;y<64;++y)std::memcpy(image.data()+y*64*bytes,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,64*bytes);system->UnlockRect();
                    const auto name=(geometry?"g"+std::to_string(geometryCase)+"-":std::string())+(triangleOrders?"o"+std::to_string(orderCase)+"-":std::string())+(sweep?"s"+std::to_string(spanIndex)+"-c"+std::to_string(palette)+"-":std::string())+"f"+std::to_string(unsigned(format))+"-a"+std::to_string(axis)+"-p"+std::to_string(path);
                    if(!repeat){baseline=image;std::ofstream out(root/(name+".raw"),std::ios::binary);out.write(reinterpret_cast<const char*>(image.data()),image.size());if(!out)return 1;}else if(image!=baseline){++failed;log<<"REPEAT_FAIL "<<name<<" repeat="<<repeat<<"\n";}
                }
                if(sweep){if(path==0)fixedImage=baseline;else if((path==1||path==2||palette==0)&&baseline!=fixedImage){++failed;log<<"CONTROL_FAIL span="<<spanIndex<<" palette="<<palette<<" path="<<path<<"\n";}}
            }
            }
            }
        }
    }
    log<<"SUMMARY formats="<<formats<<" repeatFailures="<<failed<<" highPrecisionEquivalence=DIAGNOSTIC\n";return formats<2?77:failed?2:0;
}
