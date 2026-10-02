#pragma once
// Diagnostic functional history tests. Resolved equality is not per-sample
// depth/stencil readback.
int AttachmentHistoryProbe(const std::filesystem::path& root){
    std::filesystem::create_directories(root);std::ofstream log(root/"attachment_history.log",std::ios::trunc);
    HWND window=CreateWindowW(L"STATIC",L"MSAA attachment history",WS_OVERLAPPEDWINDOW,0,0,96,96,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window)return 77;
    struct Cleanup{HWND h;~Cleanup(){DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=96;
    pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.MultiSampleType=D3DMULTISAMPLE_8_SAMPLES;
    pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
    ComPtr<IDirect3DDevice9> d;HRESULT creation=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d);
    if(FAILED(creation)){log<<"UNAVAILABLE creation="<<std::hex<<creation<<"\n";return 77;}
    ComPtr<IDirect3DSurface9> targets[2],depths[2],resolved,system;
    if(FAILED(d->GetRenderTarget(0,&targets[0]))||FAILED(d->GetDepthStencilSurface(&depths[0]))||
       FAILED(d->CreateRenderTarget(96,96,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_8_SAMPLES,0,FALSE,&targets[1],nullptr))||
       FAILED(d->CreateDepthStencilSurface(96,96,D3DFMT_D24S8,D3DMULTISAMPLE_8_SAMPLES,0,FALSE,&depths[1],nullptr))||
       FAILED(d->CreateRenderTarget(96,96,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&resolved,nullptr))||
       FAILED(d->CreateOffscreenPlainSurface(96,96,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
    struct Vertex{float x,y,z,w;DWORD color;};
    const auto rs=[&](D3DRENDERSTATETYPE key,DWORD value){return SUCCEEDED(d->SetRenderState(key,value));};
    const auto draw=[&](float z,DWORD color,bool sloped,bool shifted=false){
        Vertex vertices[]={{8.1875f,7.3125f,z,1,color},{85.8125f,19.6875f,sloped?z+.12f:z,1,color},{19.3125f,87.1875f,z,1,color}};
        if(shifted)for(auto& vertex:vertices)vertex.x+=7.25f;
        return SUCCEEDED(d->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,vertices,sizeof(Vertex)));
    };
    const auto read=[&](unsigned target,std::vector<unsigned char>& pixels){
        if(FAILED(d->StretchRect(targets[target].Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return false;
        D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
        pixels.resize(96*96*4);for(unsigned y=0;y<96;++y)std::memcpy(pixels.data()+y*96*4,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,96*4);
        return SUCCEEDED(system->UnlockRect());
    };
    const auto differences=[](const std::vector<unsigned char>& a,const std::vector<unsigned char>& b){size_t n=0;for(size_t i=0;i<a.size();i+=4)if(std::memcmp(a.data()+i,b.data()+i,4))++n;return n;};
    const char* names[]={"depth_occlusion","depth_no_write","stencil_equal","stencil_zfail","alpha_blend","combined"};
    unsigned failed=0;
    for(unsigned mode=0;mode<6;++mode){
        std::vector<unsigned char> baselineBefore,baselineAfter,control;
        for(unsigned controlMode=0;controlMode<2;++controlMode)for(unsigned target=0;target<4;++target)for(unsigned repeat=0;repeat<3;++repeat){
            if(controlMode&&(target||repeat))continue;
            bool ok=SUCCEEDED(d->SetRenderTarget(0,targets[target%2].Get()))&&SUCCEEDED(d->SetDepthStencilSurface(depths[target/2].Get()));
            D3DVIEWPORT9 viewport{0,0,96,96,0,1};ok=SUCCEEDED(d->SetViewport(&viewport))&&ok;
            ok=rs(D3DRS_ZENABLE,TRUE)&&rs(D3DRS_ZWRITEENABLE,TRUE)&&rs(D3DRS_ZFUNC,D3DCMP_LESSEQUAL)&&rs(D3DRS_STENCILENABLE,FALSE)&&
               rs(D3DRS_ALPHABLENDENABLE,FALSE)&&rs(D3DRS_ALPHATESTENABLE,FALSE)&&rs(D3DRS_SCISSORTESTENABLE,FALSE)&&
               rs(D3DRS_COLORWRITEENABLE,15)&&rs(D3DRS_CULLMODE,D3DCULL_NONE)&&rs(D3DRS_LIGHTING,FALSE)&&rs(D3DRS_FOGENABLE,FALSE)&&
               rs(D3DRS_MULTISAMPLEANTIALIAS,TRUE)&&rs(D3DRS_MULTISAMPLEMASK,0xffffffff)&&rs(D3DRS_SRGBWRITEENABLE,FALSE)&&
               rs(D3DRS_SEPARATEALPHABLENDENABLE,FALSE)&&rs(D3DRS_TWOSIDEDSTENCILMODE,FALSE)&&ok;
            ok=SUCCEEDED(d->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE))&&SUCCEEDED(d->SetTexture(0,nullptr))&&
               SUCCEEDED(d->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1))&&SUCCEEDED(d->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_DIFFUSE))&&
               SUCCEEDED(d->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1))&&SUCCEEDED(d->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_DIFFUSE))&&
               SUCCEEDED(d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE))&&ok;
            ok=SUCCEEDED(d->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff123456,1,0))&&ok;
            ok=SUCCEEDED(d->BeginScene())&&ok;
            if(mode==1)ok=rs(D3DRS_ZWRITEENABLE,controlMode?TRUE:FALSE)&&ok;
            if(mode==2||mode==5)ok=rs(D3DRS_STENCILENABLE,TRUE)&&rs(D3DRS_STENCILFUNC,D3DCMP_ALWAYS)&&rs(D3DRS_STENCILREF,3)&&rs(D3DRS_STENCILMASK,255)&&rs(D3DRS_STENCILWRITEMASK,255)&&rs(D3DRS_STENCILFAIL,D3DSTENCILOP_KEEP)&&rs(D3DRS_STENCILZFAIL,D3DSTENCILOP_KEEP)&&rs(D3DRS_STENCILPASS,D3DSTENCILOP_REPLACE)&&ok;
            ok=draw(.3f,0xffb05020,true)&&ok;
            if(mode==3){
                ok=rs(D3DRS_STENCILENABLE,TRUE)&&rs(D3DRS_STENCILFUNC,D3DCMP_ALWAYS)&&rs(D3DRS_STENCILREF,3)&&rs(D3DRS_STENCILMASK,255)&&rs(D3DRS_STENCILWRITEMASK,255)&&rs(D3DRS_STENCILFAIL,D3DSTENCILOP_KEEP)&&rs(D3DRS_STENCILZFAIL,D3DSTENCILOP_REPLACE)&&rs(D3DRS_STENCILPASS,D3DSTENCILOP_KEEP)&&draw(.65f,0xffabcdef,false)&&ok;
            }
            if(mode==4||mode==5)ok=rs(D3DRS_ALPHABLENDENABLE,TRUE)&&rs(D3DRS_SRCBLEND,D3DBLEND_SRCALPHA)&&rs(D3DRS_DESTBLEND,D3DBLEND_INVSRCALPHA)&&rs(D3DRS_BLENDOP,D3DBLENDOP_ADD)&&rs(D3DRS_ZWRITEENABLE,FALSE)&&draw(.2f,0x8050a0e0,true)&&ok;
            ok=SUCCEEDED(d->EndScene())&&ok;
            std::vector<unsigned char> before,after;ok=read(target%2,before)&&ok;
            ok=SUCCEEDED(d->BeginScene())&&ok;
            if(mode==2||mode==3||mode==5)ok=rs(D3DRS_STENCILFUNC,D3DCMP_EQUAL)&&rs(D3DRS_STENCILPASS,D3DSTENCILOP_KEEP)&&rs(D3DRS_STENCILZFAIL,D3DSTENCILOP_KEEP)&&rs(D3DRS_ZENABLE,FALSE)&&ok;
            if(controlMode){if(mode==0)ok=rs(D3DRS_ZENABLE,FALSE)&&ok;else if(mode==2||mode==3)ok=rs(D3DRS_STENCILENABLE,FALSE)&&ok;else ok=rs(D3DRS_ALPHABLENDENABLE,FALSE)&&ok;}
            ok=draw(mode==4||mode==5?.1f:.55f,0x8060e050,false,true)&&ok;
            ok=SUCCEEDED(d->EndScene())&&ok;ok=read(target%2,after)&&ok;
            if(!ok){log<<"FAIL operation mode="<<names[mode]<<"\n";return 1;}
            if(controlMode){control=after;size_t sensitive=differences(control,baselineAfter);log<<"CONTROL mode="<<names[mode]<<" differentPixels="<<sensitive<<"\n";if(!sensitive)++failed;continue;}
            if(!target&&!repeat){
                baselineBefore=before;baselineAfter=after;
                std::ofstream beforeFile(root/(std::string(names[mode])+".before.bgra"),std::ios::binary|std::ios::trunc);
                std::ofstream afterFile(root/(std::string(names[mode])+".after.bgra"),std::ios::binary|std::ios::trunc);
                beforeFile.write(reinterpret_cast<const char*>(before.data()),before.size());afterFile.write(reinterpret_cast<const char*>(after.data()),after.size());
                if(!beforeFile||!afterFile)return 1;
            }
            const auto beforeDiff=differences(baselineBefore,before),afterDiff=differences(baselineAfter,after);
            log<<"HISTORY mode="<<names[mode]<<" target="<<target<<" repeat="<<repeat<<" beforeDifferentPixels="<<beforeDiff<<" afterDifferentPixels="<<afterDiff<<" selectedChangedPixels="<<differences(before,after)<<"\n";
            if(beforeDiff||afterDiff)++failed;
        }
    }
    log<<"SUMMARY status="<<(failed?"FAIL":"PASS")<<" failedChecks="<<failed<<" perSampleReadback=0 verification=functional_resolved_images\n";
    return failed?2:0;
}
