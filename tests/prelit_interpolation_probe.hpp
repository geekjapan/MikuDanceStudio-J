#pragma once
// Diagnostic only: no production rendering path is changed.
int PrelitInterpolationProbe(const std::filesystem::path& root){
    std::filesystem::create_directories(root);std::ofstream log(root/"prelit.log");
    HWND window=CreateWindowW(L"STATIC",L"Prelit interpolation",WS_OVERLAPPEDWINDOW,0,0,256,256,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window)return 77;struct Cleanup{HWND h;~Cleanup(){DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DADAPTER_IDENTIFIER9 adapter{};api->GetAdapterIdentifier(0,0,&adapter);log<<"ADAPTER "<<adapter.Description<<"\n";
    struct Packed{float x,y,z,rhw;DWORD color;};struct Floating{float x,y,z,rhw,r,g,b,a;};
    log<<"POLICY paths=0:fixed,1:COLOR,2:centroid,3:float,4:fixedVS_explicitPS,5:float_half_up,6:float_floor,7:VPOS palettes4to11=ramp_phase_0to7_over8 MSAA_readback=resolve_only\n";
    unsigned failures=0,cases=0;
    const auto compare=[](const std::vector<unsigned char>& a,const std::vector<unsigned char>& b,unsigned& maximum){unsigned n=0;maximum=0;for(size_t at=0;at<a.size();at+=4){bool different=false;for(unsigned c=0;c<4;++c){unsigned delta=unsigned(std::abs(int(a[at+c])-int(b[at+c])));maximum=(std::max)(maximum,delta);different|=delta!=0;}n+=different;}return n;};
    for(unsigned samples:{1u,8u}){
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=256;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.MultiSampleType=samples==8?D3DMULTISAMPLE_8_SAMPLES:D3DMULTISAMPLE_NONE;
        ComPtr<IDirect3DDevice9> d;HRESULT hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d);if(FAILED(hr)){log<<"UNAVAILABLE hr="<<std::hex<<hr<<"\n";return 77;}
        ComPtr<IDirect3DSurface9> target,resolved,system;d->GetRenderTarget(0,&target);
        if(FAILED(d->CreateRenderTarget(256,256,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&resolved,nullptr))||FAILED(d->CreateOffscreenPlainSurface(256,256,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
        for(auto state:{D3DRS_LIGHTING,D3DRS_SPECULARENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_FOGENABLE,D3DRS_DITHERENABLE,D3DRS_SRGBWRITEENABLE})if(FAILED(d->SetRenderState(state,FALSE)))return 1;
        if(FAILED(d->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE))||FAILED(d->SetRenderState(D3DRS_SHADEMODE,D3DSHADE_GOURAUD))||FAILED(d->SetRenderState(D3DRS_MULTISAMPLEANTIALIAS,TRUE))||FAILED(d->SetRenderState(D3DRS_COLORWRITEENABLE,15))||FAILED(d->SetTexture(0,nullptr)))return 1;
        for(auto state:{D3DTSS_COLOROP,D3DTSS_ALPHAOP})if(FAILED(d->SetTextureStageState(0,state,D3DTOP_SELECTARG1)))return 1;
        for(auto state:{D3DTSS_COLORARG1,D3DTSS_ALPHAARG1})if(FAILED(d->SetTextureStageState(0,state,D3DTA_DIFFUSE)))return 1;
        if(FAILED(d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE)))return 1;
        ComPtr<IDirect3DVertexShader9> vs[2];ComPtr<IDirect3DPixelShader9> ps[5];
        for(unsigned centroid=0;centroid<2;++centroid){
            std::string code="struct O{float4 p:POSITION;float4 c:COLOR0;};O vs(float4 p:POSITION,float4 c:COLOR0){O o;float w=1/p.w;o.p=float4((p.x/128-1)*w,(1-p.y/128)*w,p.z*w,w);o.c=c;return o;}float4 ps(float4 c:COLOR0):COLOR0{return c;}";
            if(centroid){size_t at;while((at=code.find("c:COLOR0"))!=std::string::npos)code.replace(at,8,"c:TEXCOORD0");at=code.find("vs(float4 p:POSITION,float4 c:TEXCOORD0)");code.replace(at,std::strlen("vs(float4 p:POSITION,float4 c:TEXCOORD0)"),"vs(float4 p:POSITION,float4 c:COLOR0)");at=code.find("ps(float4 c:TEXCOORD0)");code.replace(at,std::strlen("ps(float4 c:TEXCOORD0)"),"ps(centroid float4 c:TEXCOORD0)");}
            ComPtr<ID3DBlob> vb,pb,error;if(FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"vs","vs_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vb,&error))||FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"ps","ps_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&pb,&error))||FAILED(d->CreateVertexShader(static_cast<const DWORD*>(vb->GetBufferPointer()),&vs[centroid]))||FAILED(d->CreatePixelShader(static_cast<const DWORD*>(pb->GetBufferPointer()),&ps[centroid])))return 1;
        }
        for(unsigned rule=0;rule<2;++rule){
            const std::string code=std::string("float4 ps(float4 c:COLOR0):COLOR0{return float4(floor(saturate(c.rgb)*255")+(rule==0?"+0.5":"")+")/255,c.a);}";
            ComPtr<ID3DBlob> blob,error;if(FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"ps","ps_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&blob,&error))||FAILED(d->CreatePixelShader(static_cast<const DWORD*>(blob->GetBufferPointer()),&ps[2+rule])))return 1;
        }
        {const char* code="float4 ramp:register(c0);float4 ps(float2 p:VPOS):COLOR0{return float4((p.x-ramp.x+ramp.z)/255,(p.y-ramp.y+ramp.z)/255,(ramp.w+ramp.z)/255,1);}";ComPtr<ID3DBlob> blob,error;if(FAILED(D3DCompile(code,std::strlen(code),nullptr,nullptr,nullptr,"ps","ps_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&blob,&error))||FAILED(d->CreatePixelShader(static_cast<const DWORD*>(blob->GetBufferPointer()),&ps[4])))return 1;}
        D3DVERTEXELEMENT9 elements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
        D3DVERTEXELEMENT9 packedElements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_D3DCOLOR,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
        ComPtr<IDirect3DVertexDeclaration9> packedDeclaration;if(FAILED(d->CreateVertexDeclaration(packedElements,&packedDeclaration)))return 1;
        ComPtr<IDirect3DVertexDeclaration9> floatDeclaration;if(FAILED(d->CreateVertexDeclaration(elements,&floatDeclaration)))return 1;
        for(unsigned shape=1;shape<=2;++shape)for(unsigned perspective=0;perspective<2;++perspective)for(unsigned palette=0;palette<12;++palette){
            DWORD colors[4]={0xff4080c0,0xff4080c0,0xff4080c0,0xff4080c0};
            if(palette==1){colors[0]=0xffff0000;colors[1]=0xff00ff00;colors[2]=0xff0000ff;colors[3]=0xffffffff;}
            if(palette==2){colors[0]=0xff101112;colors[1]=0xff111213;colors[2]=0xff121314;colors[3]=0xff131415;}
            if(palette==3){colors[0]=0xff4080c0;colors[1]=0xffc04080;colors[2]=0xff80c040;colors[3]=0xff4080c0;}
            Packed points[]={{32.25f,35.5f,.5f,1,colors[0]},{224.5f,43.25f,.5f,perspective?.5f:1,colors[1]},{69.75f,225.25f,.5f,1,colors[2]},{226.25f,224.5f,.5f,perspective?.5f:1,colors[3]}};
            unsigned indices[]={0,1,2,1,3,2};std::vector<Packed> packed;std::vector<Floating> floating;
            for(unsigned i=0;i<shape*3;++i){auto v=points[indices[i]];packed.push_back(v);const float offset=palette==3?.49f:0;floating.push_back({v.x,v.y,v.z,v.rhw,(((v.color>>16)&255)+offset)/255.f,(((v.color>>8)&255)+offset)/255.f,((v.color&255)+offset)/255.f,1});
                if(palette>=4){const float phase=(palette-4)/8.f;floating.back().r=(v.x-32.25f+phase)/255.f;floating.back().g=(v.y-35.5f+phase)/255.f;floating.back().b=(64+phase)/255.f;const auto byte=[](float value){return DWORD(std::floor(value*255+.5f));};packed.back().color=0xff000000|(byte(floating.back().r)<<16)|(byte(floating.back().g)<<8)|byte(floating.back().b);}
}
            for(unsigned maskIndex=0;maskIndex<(samples==8&&palette<4?9u:1u);++maskIndex){
                DWORD mask=maskIndex?1u<<(maskIndex-1):0xffffffff;std::vector<unsigned char> baselines[8];
                const auto tag="s"+std::to_string(samples)+"-t"+std::to_string(shape)+"-w"+std::to_string(perspective)+"-c"+std::to_string(palette)+"-m"+std::to_string(maskIndex);
                for(unsigned path=0;path<(palette>=4?8u:7u);++path){
                    const bool shader=path!=0&&path!=4;const unsigned centroid=path==2?1:0;
                    if(FAILED(d->SetVertexShader(shader?vs[centroid].Get():nullptr))||FAILED(d->SetPixelShader(path?ps[path>=5?path-3:centroid].Get():nullptr))||FAILED(d->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE))||FAILED(d->SetRenderState(D3DRS_MULTISAMPLEMASK,mask)))return 1;
                    if(shader&&FAILED(d->SetVertexDeclaration((path==3||path==5||path==6)?floatDeclaration.Get():packedDeclaration.Get())))return 1;
                    if(path==7){const float ramp[]={32.25f,35.5f,(palette-4)/8.f,64.f};if(FAILED(d->SetPixelShaderConstantF(0,ramp,1)))return 1;}
                    unsigned maxRepeat=0,changed=0;
                    for(unsigned repeat=0;repeat<(maskIndex?3u:40u);++repeat){
                        if(FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET,0xff123456,1,0))||FAILED(d->BeginScene()))return 1;
                        hr=d->DrawPrimitiveUP(D3DPT_TRIANGLELIST,shape,(path==3||path==5||path==6)?static_cast<const void*>(floating.data()):static_cast<const void*>(packed.data()),(path==3||path==5||path==6)?sizeof(Floating):sizeof(Packed));const HRESULT ended=d->EndScene();
                        if(FAILED(hr)||FAILED(ended)||FAILED(d->StretchRect(target.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return 1;
                        D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;std::vector<unsigned char> pixels(256*256*4);for(unsigned y=0;y<256;++y)std::memcpy(pixels.data()+y*1024,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,1024);if(FAILED(system->UnlockRect()))return 1;
                        if(!repeat){baselines[path]=pixels;for(size_t at=0;at<pixels.size();at+=4){DWORD c;std::memcpy(&c,pixels.data()+at,4);changed+=c!=0xff123456;}std::ofstream image(root/(tag+"-p"+std::to_string(path)+".bgra"),std::ios::binary);image.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());if(!image)return 1;}
                        else{unsigned channel=0;unsigned delta=compare(pixels,baselines[path],channel);maxRepeat=(std::max)(maxRepeat,delta);if(delta){std::ofstream image(root/(tag+"-p"+std::to_string(path)+"-r"+std::to_string(repeat)+".bgra"),std::ios::binary);image.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());if(!image)return 1;}}
                    }
                    log<<"REPEAT tag="<<tag<<" path="<<path<<" differentPixels="<<maxRepeat<<" changedPixels="<<changed<<"\n";failures+=(maxRepeat||!changed);++cases;
                }
                for(unsigned path=1;path<(palette>=4?8u:7u);++path){unsigned channel=0;const auto delta=compare(baselines[0],baselines[path],channel);log<<"COMPARE tag="<<tag<<" path="<<path<<" differentPixels="<<delta<<" maxChannel="<<channel<<" kind="<<(maskIndex?"resolved_mask":"full_mask")<<"\n";if(palette==0&&path<5&&delta)++failures;}
                if(palette>=4){unsigned channel=0;log<<"INTERPOLATED_VPOS tag="<<tag<<" differentPixels="<<compare(baselines[3],baselines[7],channel)<<" maxChannel="<<channel<<"\n";}
                unsigned stageChannel=0;log<<"FIXED_VERTEX_SHADER_PIXEL tag="<<tag<<" vsExplicitDifferentPixels="<<compare(baselines[4],baselines[1],stageChannel)<<" maxChannel="<<stageChannel<<"\n";
                unsigned channel=0;log<<"COLOR_CENTROID tag="<<tag<<" differentPixels="<<compare(baselines[1],baselines[2],channel)<<" maxChannel="<<channel<<"\n";
            }
        }
    }
    log<<"SUMMARY cases="<<cases<<" failed="<<failures<<" varyingColorEquivalence=DIAGNOSTIC realPmmGate=NOT_PASSED\n";return failures?2:0;
}
