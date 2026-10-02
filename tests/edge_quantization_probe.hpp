#pragma once
// Separate constant-output conversion and coverage-dependent interpolation experiments.
int EdgeQuantizationProbe(const std::filesystem::path& root){
    std::filesystem::create_directories(root);
    std::ofstream quant(root/"quantization.csv"),edge(root/"edges.csv"),mask(root/"coverage.csv"),resolve(root/"resolve.csv"),report(root/"scan.log"),comparison(root/"comparison.csv");
    comparison<<"samples,axis,step,phase,mask,path,B,G,R,A,differentPixels,maxChannel,leftR,rightR,topG,bottomG,vertexControlDifferentPixels\n";
    quant<<"samples,base,step,path,valueBits,B,G,R,A\n";
    edge<<"samples,axis,step,phase,path,B,G,R,A,interiorB,interiorG,interiorR\n";
    mask<<"axis,step,sample,coverageByte\n";
    resolve<<"samples,axis,step,source,B,G,R,A\n";
    HWND window=CreateWindowW(L"STATIC",L"Edge and quantization scan",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window)return 77;struct Cleanup{HWND h;~Cleanup(){DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DADAPTER_IDENTIFIER9 adapter{};api->GetAdapterIdentifier(0,0,&adapter);report<<"ADAPTER "<<adapter.Description<<"\n";
    struct Vertex{float x,y,z,rhw,r,g,b,a;};
    struct Packed{float x,y,z,rhw;DWORD color;};
    unsigned failed=0,draws=0;
    for(unsigned samples:{1u,8u}){
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=64;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.MultiSampleType=samples==8?D3DMULTISAMPLE_8_SAMPLES:D3DMULTISAMPLE_NONE;
        ComPtr<IDirect3DDevice9> d;HRESULT hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d);if(FAILED(hr)){report<<"UNAVAILABLE hr="<<std::hex<<hr<<"\n";return 77;}
        ComPtr<IDirect3DSurface9> target,resolved,system;d->GetRenderTarget(0,&target);
        if(FAILED(d->CreateRenderTarget(64,64,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&resolved,nullptr))||FAILED(d->CreateOffscreenPlainSurface(64,64,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
        for(auto state:{D3DRS_LIGHTING,D3DRS_SPECULARENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_FOGENABLE,D3DRS_DITHERENABLE,D3DRS_SRGBWRITEENABLE})if(FAILED(d->SetRenderState(state,FALSE)))return 1;
        if(FAILED(d->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE))||FAILED(d->SetRenderState(D3DRS_MULTISAMPLEANTIALIAS,TRUE))||FAILED(d->SetRenderState(D3DRS_COLORWRITEENABLE,15)))return 1;
        DWORD srgb=~DWORD(0);if(FAILED(d->GetRenderState(D3DRS_SRGBWRITEENABLE,&srgb)))return 1;report<<"STATE samples="<<samples<<" sRGBWrite="<<srgb<<" resolveFilter=NONE sampleQuality=0\n";
        D3DVERTEXELEMENT9 elements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
        ComPtr<IDirect3DVertexDeclaration9> declaration;if(FAILED(d->CreateVertexDeclaration(elements,&declaration))||FAILED(d->SetVertexDeclaration(declaration.Get())))return 1;
        D3DVERTEXELEMENT9 packedElements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_D3DCOLOR,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
        ComPtr<IDirect3DVertexDeclaration9> packedDeclaration;if(FAILED(d->CreateVertexDeclaration(packedElements,&packedDeclaration)))return 1;
        for(auto state:{D3DTSS_COLOROP,D3DTSS_ALPHAOP})if(FAILED(d->SetTextureStageState(0,state,D3DTOP_SELECTARG1)))return 1;
        for(auto state:{D3DTSS_COLORARG1,D3DTSS_ALPHAARG1})if(FAILED(d->SetTextureStageState(0,state,D3DTA_DIFFUSE)))return 1;
        if(FAILED(d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE))||FAILED(d->SetTexture(0,nullptr)))return 1;
        ComPtr<IDirect3DVertexShader9> vs[2];ComPtr<IDirect3DPixelShader9> ps[9];
        for(unsigned variant=0;variant<9;++variant){
            std::string code="float4 K:register(c0);struct O{float4 p:POSITION;float4 c:COLOR0;};O vs(float4 p:POSITION,float4 c:COLOR0){O o;o.p=float4(p.x/32-1,1-p.y/32,p.z,1);o.c=c;return o;}";
            if(variant==2){auto at=code.find("c:COLOR0");code.replace(at,8,"c:TEXCOORD0");code+="float4 ps(centroid float4 c:TEXCOORD0):COLOR0{return c;}";}
            else if(variant==1)code+="float4 ps(float4 c:COLOR0):COLOR0{return c;}";
            else if(variant==3)code+="float4 ps(float2 p:VPOS):COLOR0{return float4((p.x*4+K.y)/255,(p.y*4+K.y)/255,64./255,1);}";
            else if(variant==4)code+="float4 ps():COLOR0{return float4(floor(K.xxx*255+0.5)/255,1);}";
            else if(variant==7)code+="float4 C:register(c1);float4 S:register(c2);float4 ps(float2 p:VPOS):COLOR0{return float4(C.x+(p.x+0.5)*S.x,C.y+(p.y+0.5)*S.y,C.z,1);}";
            else if(variant==8)code+="float4 C:register(c1);float4 S:register(c2);float4 ps(float2 p:VPOS):COLOR0{float2 t=float2(p.x+0.5,p.y+0.5)*S.xy;return float4((C.xy+t)/255,C.z/255,1);}";
            else if(variant==6)code+="float4 C:register(c1);float4 S:register(c2);float4 ps(float2 p:VPOS):COLOR0{return float4((C.x+(p.x+0.5)*S.x)/255,(C.y+(p.y+0.5)*S.y)/255,C.z/255,1);}";
            else if(variant==5)code+="float4 ps():COLOR0{return float4(floor(K.xxx*255)/255,1);}";
            else code+="float4 ps():COLOR0{return float4(K.xxx,1);}";
            ComPtr<ID3DBlob> vb,pb,error;if(FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"vs","vs_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vb,&error))||FAILED(D3DCompile(code.data(),code.size(),nullptr,nullptr,nullptr,"ps","ps_3_0",(variant==8?D3DCOMPILE_SKIP_OPTIMIZATION:0)|D3DCOMPILE_IEEE_STRICTNESS,0,&pb,&error)))return 1;
            if(variant==0&&FAILED(d->CreateVertexShader(static_cast<const DWORD*>(vb->GetBufferPointer()),&vs[0])))return 1;
            if(variant==2&&FAILED(d->CreateVertexShader(static_cast<const DWORD*>(vb->GetBufferPointer()),&vs[1])))return 1;
            if(FAILED(d->CreatePixelShader(static_cast<const DWORD*>(pb->GetBufferPointer()),&ps[variant])))return 1;
        }
        const auto mesh=[](float right,float bottom,float phase){
            const auto v=[&](float x,float y){return Vertex{x,y,.5f,1,(x*4+phase)/255,(y*4+phase)/255,64.f/255,1};};
            return std::vector<Vertex>{v(-.5f,-.5f),v(right,-.5f),v(-.5f,bottom),v(right,-.5f),v(right,bottom),v(-.5f,bottom)};
        };
        const auto render=[&](const std::vector<Vertex>& vertices,unsigned path,float value,float phase,DWORD sampleMask,const std::string& tag,std::vector<unsigned char>& baseline){
            float constants[]={value,phase,0,0};
            std::vector<Packed> packed;
            if(path>=6){const auto byte=[](float v){return DWORD(std::floor((std::max)(0.f,(std::min)(1.f,v))*255+.5f));};for(const auto& v:vertices)packed.push_back({v.x,v.y,v.z,v.rhw,(byte(v.a)<<24)|(byte(v.r)<<16)|(byte(v.g)<<8)|byte(v.b)});}
            if(FAILED(d->SetVertexShader(path==6||path==7?nullptr:vs[path==2?1:0].Get()))||FAILED(d->SetPixelShader(path==6?nullptr:ps[path>=9?path-3:path>=7?1:path].Get()))||FAILED(d->SetPixelShaderConstantF(0,constants,1))||FAILED(d->SetRenderState(D3DRS_MULTISAMPLEMASK,sampleMask)))return false;
            if(path==6||path==7){if(FAILED(d->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE)))return false;}
            else if(FAILED(d->SetVertexDeclaration(path>=8?packedDeclaration.Get():declaration.Get())))return false;
            if(path>=9){
                const auto channel=[](DWORD c,unsigned shift){return float((c>>shift)&255);};
                float origins[]={channel(packed[0].color,16),channel(packed[0].color,8),channel(packed[0].color,0),1};
                float slopes[]={(channel(packed[1].color,16)-origins[0])/(packed[1].x-packed[0].x),(channel(packed[2].color,8)-origins[1])/(packed[2].y-packed[0].y),0,0};
                if(path==10){for(unsigned c=0;c<3;++c){origins[c]/=255.f;slopes[c]/=255.f;}}
                if(FAILED(d->SetPixelShaderConstantF(1,origins,1))||FAILED(d->SetPixelShaderConstantF(2,slopes,1)))return false;
            }
            for(unsigned repeat=0;repeat<3;++repeat){
                if(FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET,0,1,0))||FAILED(d->BeginScene()))return false;
                HRESULT drawn=d->DrawPrimitiveUP(D3DPT_TRIANGLELIST,2,path>=6?static_cast<const void*>(packed.data()):static_cast<const void*>(vertices.data()),path>=6?sizeof(Packed):sizeof(Vertex)),ended=d->EndScene();++draws;
                if(FAILED(drawn)||FAILED(ended)||FAILED(d->StretchRect(target.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return false;
                D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
                std::vector<unsigned char> pixels(64*64*4);for(unsigned y=0;y<64;++y)std::memcpy(pixels.data()+y*256,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,256);if(FAILED(system->UnlockRect()))return false;
                if(!repeat)baseline=pixels;else if(pixels!=baseline){++failed;report<<"REPEAT_FAIL tag="<<tag<<" repeat="<<repeat<<"\n";std::ofstream image(root/(tag+"-r"+std::to_string(repeat)+".bgra"),std::ios::binary);image.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());std::ofstream first(root/(tag+"-baseline.bgra"),std::ios::binary);first.write(reinterpret_cast<const char*>(baseline.data()),baseline.size());}
            }
            return true;
        };
        std::vector<unsigned char> pixels;auto full=mesh(63.5f,63.5f,0);
        for(unsigned base:{63u,64u,65u,113u,120u,121u,122u,123u,124u,125u,126u,127u,128u})for(unsigned step=0;step<=64;++step)for(unsigned path:{0u,4u,5u}){
            const float value=(base+step/64.f)/255.f;DWORD bits;std::memcpy(&bits,&value,4);
            const auto tag="quant-s"+std::to_string(samples)+"-b"+std::to_string(base)+"-k"+std::to_string(step)+"-p"+std::to_string(path);
            if(!render(full,path,value,0,0xffffffff,tag,pixels))return 1;
            const size_t at=(16*64+16)*4;for(unsigned y=8;y<24;++y)for(unsigned x=8;x<24;++x)if(std::memcmp(pixels.data()+(y*64+x)*4,pixels.data()+at,4)){++failed;report<<"NONUNIFORM "<<tag<<"\n";y=24;break;}
            if(!pixels[at+2]||pixels[at+3]!=255){++failed;report<<"EMPTY_OR_INVALID_QUANT "<<tag<<"\n";}
            quant<<samples<<","<<base<<","<<step<<","<<path<<","<<bits;for(unsigned c=0;c<4;++c)quant<<","<<unsigned(pixels[at+c]);quant<<"\n";
        }
        {const float value=113.5546875f/255.f;if(!render(full,0,value,0,0xffffffff,"constant113_5546875-s"+std::to_string(samples),pixels))return 1;report<<"DIRECT_CONSTANT samples="<<samples<<" theoreticalByte=113.5546875 observed="<<unsigned(pixels[(16*64+16)*4+2])<<"\n";}
        for(unsigned axis=0;axis<2;++axis)for(unsigned step=0;step<=64;++step){
            const float boundary=30.5f+step/64.f;
            if(samples==8)for(unsigned sample=0;sample<8;++sample){auto geometry=mesh(axis?63.5f:boundary,axis?boundary:63.5f,0);if(!render(geometry,0,1,0,1u<<sample,"mask-a"+std::to_string(axis)+"-k"+std::to_string(step)+"-s"+std::to_string(sample),pixels))return 1;mask<<axis<<","<<step<<","<<sample<<","<<unsigned(pixels[(31*64+31)*4])<<"\n";}
            for(unsigned source:{0u,32u,64u,120u,121u,122u,123u,124u,125u,126u,127u,128u,255u}){
                auto geometry=mesh(axis?63.5f:boundary,axis?boundary:63.5f,0);
                const auto tag="resolve-s"+std::to_string(samples)+"-a"+std::to_string(axis)+"-k"+std::to_string(step)+"-c"+std::to_string(source);
                if(!render(geometry,0,source/255.f,0,0xffffffff,tag,pixels))return 1;
                resolve<<samples<<","<<axis<<","<<step<<","<<source;for(unsigned c=0;c<4;++c)resolve<<","<<unsigned(pixels[(31*64+31)*4+c]);resolve<<"\n";
            }
            for(unsigned phase=0;phase<8;++phase)for(unsigned maskIndex=0;maskIndex<(samples==8&&phase==0?9u:1u);++maskIndex){
                DWORD sampleMask=maskIndex?1u<<(maskIndex-1):0xffffffff;
                auto geometry=mesh(axis?63.5f:boundary,axis?boundary:63.5f,phase/8.f);
                std::vector<unsigned char> fixed,explicitPixel;
                for(unsigned path=6;path<12;++path){
                    const auto tag="comparison-s"+std::to_string(samples)+"-a"+std::to_string(axis)+"-k"+std::to_string(step)+"-h"+std::to_string(phase)+"-m"+std::to_string(maskIndex)+"-p"+std::to_string(path);
                    if(!render(geometry,path,1,phase/8.f,sampleMask,tag,pixels))return 1;
                    if(path==6)fixed=pixels;
                    if(path==7)explicitPixel=pixels;
                    unsigned different=0,maximum=0;for(size_t at=0;at<pixels.size();at+=4){if(std::memcmp(pixels.data()+at,fixed.data()+at,4))++different;for(unsigned c=0;c<4;++c)maximum=(std::max)(maximum,unsigned(std::abs(int(pixels[at+c])-int(fixed[at+c]))));}
                    comparison<<samples<<","<<axis<<","<<step<<","<<phase<<","<<maskIndex<<","<<path;for(unsigned c=0;c<4;++c)comparison<<","<<unsigned(pixels[(31*64+31)*4+c]);comparison<<","<<different<<","<<maximum;
                    const auto byte=[](float v){return unsigned(std::floor((std::max)(0.f,(std::min)(1.f,v))*255+.5f));};comparison<<","<<byte(geometry[0].r)<<","<<byte(geometry[1].r)<<","<<byte(geometry[0].g)<<","<<byte(geometry[2].g);
                    unsigned vertexDelta=0;if(path==8){for(size_t at=0;at<pixels.size();at+=4)vertexDelta+=std::memcmp(pixels.data()+at,explicitPixel.data()+at,4)!=0;if(vertexDelta)++failed;}
                    comparison<<","<<vertexDelta<<"\n";
                    if(path>=9&&samples==1&&different&&phase==4&&step==0){
                        for(unsigned imagePath=0;imagePath<2;++imagePath){const auto& image=imagePath?pixels:fixed;std::ofstream file(root/(tag+(imagePath?"-analytic.bgra":"-fixed.bgra")),std::ios::binary);file.write(reinterpret_cast<const char*>(image.data()),image.size());if(!file)return 1;}
                        for(size_t at=0;at<pixels.size();at+=4)if(std::memcmp(pixels.data()+at,fixed.data()+at,4)){report<<"CENTER_FIRST axis="<<axis<<" x="<<(at/4%64)<<" y="<<(at/4/64)<<" fixed=";for(unsigned c=0;c<4;++c)report<<unsigned(fixed[at+c])<<",";report<<" analytic=";for(unsigned c=0;c<4;++c)report<<unsigned(pixels[at+c])<<",";report<<"\n";break;}
                    }
                    // Single-sample packed inputs must agree; MSAA mismatches remain diagnostics.
                    if(samples==1&&path<9&&different)++failed;
                }
            }
            for(unsigned phase=0;phase<8;++phase)for(unsigned path=0;path<4;++path){
                if(path==0&&phase)continue;
                auto geometry=mesh(axis?63.5f:boundary,axis?boundary:63.5f,phase/8.f);
                const auto tag="edge-s"+std::to_string(samples)+"-a"+std::to_string(axis)+"-k"+std::to_string(step)+"-h"+std::to_string(phase)+"-p"+std::to_string(path);
                if(!render(geometry,path,1,phase/8.f,0xffffffff,tag,pixels))return 1;
                edge<<samples<<","<<axis<<","<<step<<","<<phase<<","<<path;for(unsigned c=0;c<4;++c)edge<<","<<unsigned(pixels[(31*64+31)*4+c]);for(unsigned c=0;c<3;++c)edge<<","<<unsigned(pixels[(16*64+16)*4+c]);edge<<"\n";
            }
        }
    }
    report<<"SUMMARY draws="<<draws<<" failed="<<failed<<" readback=resolved_only realPmmGate=NOT_PASSED\n";
    return !quant||!edge||!mask||!resolve||!comparison||!report?1:failed?2:0;
}
