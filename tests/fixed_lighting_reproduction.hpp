#pragma once
#include <cmath>
#include <string>
int FixedLightingReproduction(const std::filesystem::path& root,unsigned triangleMode=0){
    std::filesystem::create_directories(root);std::ofstream report(root/"fixed_lighting.log");
    HWND window=CreateWindowW(L"STATIC",L"Procedural fixed lighting",WS_OVERLAPPEDWINDOW,0,0,256,192,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window)return 77;struct Cleanup{HWND h;~Cleanup(){DestroyWindow(h);}} cleanup{window};
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return 77;
    D3DADAPTER_IDENTIFIER9 adapter{};api->GetAdapterIdentifier(0,0,&adapter);report<<"ADAPTER description="<<adapter.Description<<" vendor="<<adapter.VendorId<<" device="<<adapter.DeviceId<<"\n";
    struct Vertex{float x,y,z,nx,ny,nz,u,v;};
    const unsigned repeats=triangleMode?40:10;
    unsigned failed=0;
    std::vector<std::vector<unsigned char>> caseImages;
    for(unsigned samples:{1u,8u}){
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=256;pp.BackBufferHeight=192;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;
        pp.MultiSampleType=samples==8?D3DMULTISAMPLE_8_SAMPLES:D3DMULTISAMPLE_NONE;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        ComPtr<IDirect3DDevice9> d;const auto created=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d);
        if(FAILED(created)){report<<"UNAVAILABLE samples="<<samples<<" hr="<<std::hex<<created<<"\n";return 77;}
        ComPtr<IDirect3DSurface9> target,resolved,system;d->GetRenderTarget(0,&target);
        if(FAILED(d->CreateRenderTarget(256,192,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&resolved,nullptr))||FAILED(d->CreateOffscreenPlainSurface(256,192,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&system,nullptr)))return 1;
        D3DMATRIX world={9.99977016f,-.000162607743f,-.0677892044f,0,0,9.99997139f,-.0239871927f,0,.0677893981f,.0239866432f,9.99974155f,0,.0417158604f,-12.2499666f,.0291015189f,1};
        D3DMATRIX view={.99999994f,0,0,0,0,.99999994f,0,0,0,0,1,0,0,0,38.0938644f,1};
        D3DMATRIX projection={2.37869596f,0,0,0,0,3.17159486f,0,0,0,0,1.00001001f,1,0,0,-1.00001001f,0};
        D3DMATERIAL9 material{};material.Diffuse={.044879999f,.044879999f,.044879999f,1};material.Ambient={.448799998f,.448799998f,.448799998f,1};material.Specular={.0410000011f,.0410000011f,.0410000011f,1};material.Emissive={.0560999997f,.0560999997f,.0560999997f,1};material.Power=2;
        D3DLIGHT9 light{};light.Type=D3DLIGHT_DIRECTIONAL;light.Diffuse={10,10,10,0};light.Specular={0,.078125f,.25390625f,0};light.Ambient={-.300000012f,-.221875012f,-.0460937619f,0};light.Direction={-.496599048f,-.998789728f,.505775273f};
        const auto rs=[&](D3DRENDERSTATETYPE key,DWORD value){return SUCCEEDED(d->SetRenderState(key,value));};
        for(unsigned zero=0;zero<(triangleMode?4u:2u);++zero)for(unsigned normalize=0;normalize<2;++normalize)for(unsigned specular=0;specular<2;++specular)for(unsigned lighting=0;lighting<2;++lighting){
            std::vector<Vertex> mesh;const auto vertex=[&](unsigned x,unsigned y){float px=-1.1f+x/24.f*2.2f,py=.35f+y/24.f*2.2f;float nx=std::sin(x*.31f),ny=std::cos(y*.23f),nz=-1;float length=std::sqrt(nx*nx+ny*ny+nz*nz);if(zero&&((x+y)%7==0))nx=ny=nz=0;else{nx/=length;ny/=length;nz/=length;}return Vertex{px,py,.13f*std::sin(x*.3f)*std::cos(y*.2f),nx,ny,nz,0,0};};
            for(unsigned y=0;y<24;++y)for(unsigned x=0;x<24;++x){mesh.push_back(vertex(x,y));mesh.push_back(vertex(x+1,y));mesh.push_back(vertex(x,y+1));mesh.push_back(vertex(x+1,y));mesh.push_back(vertex(x+1,y+1));mesh.push_back(vertex(x,y+1));}
            if(triangleMode){
                mesh={{-1.05f,.4f,.03f,0,0,-1,0,0},{1.07f,.52f,-.02f,.6f,0,-.8f,0,0},{-.23f,2.48f,.09f,0,.8f,-.6f,0,0}};
                if(zero==1)mesh[0].nx=mesh[0].ny=mesh[0].nz=0;
                if(zero==2)for(auto& v:mesh)v.nx=v.ny=v.nz=0;
                if(zero==3)for(auto& v:mesh){v.nx*=1e-12f;v.ny*=1e-12f;v.nz*=1e-12f;}
                if(triangleMode==2){mesh.push_back(mesh[1]);mesh.push_back(Vertex{1.08f,2.46f,.04f,0,0,-1,0,0});mesh.push_back(mesh[2]);if(zero==2)mesh[4].nz=0;if(zero==3)mesh[4].nz=-1e-12f;}
            }
            ComPtr<IDirect3DVertexBuffer9> buffer;void* bits=nullptr;
            if(FAILED(d->CreateVertexBuffer(static_cast<UINT>(mesh.size()*sizeof(Vertex)),0,274,D3DPOOL_MANAGED,&buffer,nullptr))||FAILED(buffer->Lock(0,0,&bits,0)))return 1;
            std::memcpy(bits,mesh.data(),mesh.size()*sizeof(Vertex));if(FAILED(buffer->Unlock()))return 1;
            std::vector<unsigned char> baseline;unsigned maxDiff=0,changed=0;
            for(unsigned repeat=0;repeat<repeats;++repeat){
                bool ok=SUCCEEDED(d->SetTransform(D3DTS_WORLD,&world))&&SUCCEEDED(d->SetTransform(D3DTS_VIEW,&view))&&SUCCEEDED(d->SetTransform(D3DTS_PROJECTION,&projection))&&SUCCEEDED(d->SetMaterial(&material))&&SUCCEEDED(d->SetLight(0,&light))&&SUCCEEDED(d->LightEnable(0,TRUE));
                ok=rs(D3DRS_LIGHTING,lighting)&&rs(D3DRS_NORMALIZENORMALS,normalize)&&rs(D3DRS_SPECULARENABLE,specular)&&rs(D3DRS_LOCALVIEWER,FALSE)&&rs(D3DRS_COLORVERTEX,FALSE)&&rs(D3DRS_DIFFUSEMATERIALSOURCE,D3DMCS_MATERIAL)&&rs(D3DRS_AMBIENTMATERIALSOURCE,D3DMCS_MATERIAL)&&rs(D3DRS_SPECULARMATERIALSOURCE,D3DMCS_MATERIAL)&&rs(D3DRS_EMISSIVEMATERIALSOURCE,D3DMCS_MATERIAL)&&rs(D3DRS_AMBIENT,0)&&rs(D3DRS_ZENABLE,TRUE)&&rs(D3DRS_ZWRITEENABLE,TRUE)&&rs(D3DRS_ZFUNC,D3DCMP_LESSEQUAL)&&rs(D3DRS_ALPHABLENDENABLE,FALSE)&&rs(D3DRS_STENCILENABLE,FALSE)&&rs(D3DRS_ALPHATESTENABLE,FALSE)&&rs(D3DRS_CULLMODE,D3DCULL_NONE)&&rs(D3DRS_MULTISAMPLEANTIALIAS,TRUE)&&rs(D3DRS_MULTISAMPLEMASK,0xffffffff)&&ok;
                ok=SUCCEEDED(d->SetFVF(274))&&SUCCEEDED(d->SetStreamSource(0,buffer.Get(),0,sizeof(Vertex)))&&SUCCEEDED(d->SetTexture(0,nullptr))&&SUCCEEDED(d->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1))&&SUCCEEDED(d->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_DIFFUSE))&&SUCCEEDED(d->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1))&&SUCCEEDED(d->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_DIFFUSE))&&SUCCEEDED(d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE))&&ok;
                ok=SUCCEEDED(d->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff123456,1,0))&&SUCCEEDED(d->BeginScene())&&ok;
                const auto draw=d->DrawPrimitive(D3DPT_TRIANGLELIST,0,static_cast<UINT>(mesh.size()/3));const auto end=d->EndScene();
                if(!ok||FAILED(draw)||FAILED(end)||FAILED(d->StretchRect(target.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return 1;
                D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;
                std::vector<unsigned char> pixels(256*192*4);for(unsigned y=0;y<192;++y)std::memcpy(pixels.data()+y*256*4,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,256*4);system->UnlockRect();
                unsigned diff=0;if(!repeat){baseline=pixels;for(size_t i=0;i<pixels.size();i+=4){DWORD color;std::memcpy(&color,pixels.data()+i,4);if(color!=0xff123456)++changed;}}
                else for(size_t i=0;i<pixels.size();i+=4)if(std::memcmp(pixels.data()+i,baseline.data()+i,4))++diff;
                if(diff){
                    std::ofstream image(root/("case"+std::to_string(caseImages.size())+"-repeat"+std::to_string(repeat)+".bgra"),std::ios::binary|std::ios::trunc);
                    image.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());if(!image)return 1;
                    for(size_t at=0;at<pixels.size();at+=4)if(std::memcmp(pixels.data()+at,baseline.data()+at,4)){
                        report<<"FIRST_DIFFERENCE case="<<caseImages.size()<<" repeat="<<repeat<<" x="<<(at/4%256)<<" y="<<(at/4/256)<<" baselineBGRA=";
                        for(unsigned c=0;c<4;++c)report<<unsigned(baseline[at+c])<<(c==3?' ':',');
                        report<<" actualBGRA=";for(unsigned c=0;c<4;++c)report<<unsigned(pixels[at+c])<<(c==3?'\n':',');break;
                    }
                }
                if(diff>maxDiff)maxDiff=diff;
                report<<"REPEAT samples="<<samples<<" zeroNormals="<<zero<<" normalize="<<normalize<<" specular="<<specular<<" lighting="<<lighting<<" repeat="<<repeat<<" differentPixels="<<diff<<"\n";
            }
            const auto caseNumber=caseImages.size();caseImages.push_back(baseline);
            std::ofstream image(root/("case"+std::to_string(caseNumber)+".bgra"),std::ios::binary|std::ios::trunc);
            image.write(reinterpret_cast<const char*>(baseline.data()),baseline.size());if(!image)return 1;
            report<<"CASE samples="<<samples<<" zeroNormals="<<zero<<" normalize="<<normalize<<" specular="<<specular<<" lighting="<<lighting<<" maximumDifferentPixels="<<maxDiff<<" changedPixels="<<changed<<" status="<<(maxDiff||!changed?"FAIL":"PASS")<<"\n";
            if(maxDiff||!changed)++failed;
            if((zero||triangleMode)&&normalize&&!specular&&lighting){
                for(unsigned centroid=0;centroid<(triangleMode?2u:1u);++centroid){
                const char* code="row_major float4x4 W:register(c0);row_major float4x4 V:register(c4);row_major float4x4 P:register(c8);struct O{float4 p:POSITION;float4 c:COLOR0;};O vs(float3 p:POSITION,float3 n:NORMAL){O o;float4 w=mul(float4(p,1),W);o.p=mul(mul(w,V),P);float3 normal=mul(n,(float3x3)W);float len=length(normal);normal=len>0?normal/len:float3(0,0,0);float3 L=normalize(float3(.496599048,.998789728,-.505775273));float nd=max(0,dot(normal,L));float3 color=float3(.0560999997,.0560999997,.0560999997)+float3(.448799998,.448799998,.448799998)*float3(-.300000012,-.221875012,-.0460937619)+float3(.044879999,.044879999,.044879999)*10*nd;o.c=float4(saturate(color),1);return o;}float4 ps(float4 c:COLOR0):COLOR0{return c;}";
                std::string shaderText=code;
                if(centroid){
                    for(size_t at=shaderText.find("c:COLOR0");at!=std::string::npos;at=shaderText.find("c:COLOR0"))shaderText.replace(at,8,"c:TEXCOORD0");
                    const auto at=shaderText.find("ps(float4 c:TEXCOORD0)");shaderText.replace(at,std::strlen("ps(float4 c:TEXCOORD0)"),"ps(centroid float4 c:TEXCOORD0)");
                }
                ComPtr<ID3DBlob> vertexCode,pixelCode,errors;ComPtr<IDirect3DVertexShader9> vs;ComPtr<IDirect3DPixelShader9> ps;
                if(FAILED(D3DCompile(shaderText.data(),shaderText.size(),nullptr,nullptr,nullptr,"vs","vs_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&vertexCode,&errors))||FAILED(D3DCompile(shaderText.data(),shaderText.size(),nullptr,nullptr,nullptr,"ps","ps_3_0",D3DCOMPILE_IEEE_STRICTNESS,0,&pixelCode,&errors))||FAILED(d->CreateVertexShader(static_cast<const DWORD*>(vertexCode->GetBufferPointer()),&vs))||FAILED(d->CreatePixelShader(static_cast<const DWORD*>(pixelCode->GetBufferPointer()),&ps)))return 1;
                if(FAILED(d->SetVertexShader(vs.Get()))||FAILED(d->SetPixelShader(ps.Get()))||FAILED(d->SetVertexShaderConstantF(0,reinterpret_cast<const float*>(&world),4))||FAILED(d->SetVertexShaderConstantF(4,reinterpret_cast<const float*>(&view),4))||FAILED(d->SetVertexShaderConstantF(8,reinterpret_cast<const float*>(&projection),4)))return 1;
                std::vector<unsigned char> shaderBaseline;unsigned shaderMaximum=0,fixedDiff=0;
                for(unsigned repeat=0;repeat<repeats;++repeat){
                    if(FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff123456,1,0))||FAILED(d->BeginScene()))return 1;
                    auto drawn=d->DrawPrimitive(D3DPT_TRIANGLELIST,0,static_cast<UINT>(mesh.size()/3));auto ended=d->EndScene();
                    if(FAILED(drawn)||FAILED(ended)||FAILED(d->StretchRect(target.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return 1;
                    D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;
                    std::vector<unsigned char> pixels(256*192*4);for(unsigned y=0;y<192;++y)std::memcpy(pixels.data()+y*256*4,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,256*4);system->UnlockRect();
                    unsigned delta=0;if(!repeat){shaderBaseline=pixels;for(size_t i=0;i<pixels.size();i+=4)if(std::memcmp(pixels.data()+i,baseline.data()+i,4))++fixedDiff;}
                    else for(size_t i=0;i<pixels.size();i+=4)if(std::memcmp(pixels.data()+i,shaderBaseline.data()+i,4))++delta;
                    if(!repeat&&triangleMode){
                        std::ofstream image(root/("explicit-s"+std::to_string(samples)+"-n"+std::to_string(zero)+"-c"+std::to_string(centroid)+".bgra"),std::ios::binary|std::ios::trunc);
                        image.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());if(!image)return 1;
                    }
                    if(delta>shaderMaximum)shaderMaximum=delta;
                }
                if(triangleMode&&samples==8&&centroid==0){
                    // Resolve one enabled sample at a time. These remain
                    // resolved control images, not direct per-sample readback.
                    for(unsigned sample=0;sample<8;++sample){
                        std::vector<unsigned char> images[2];
                        for(unsigned path=0;path<2;++path){
                            if(FAILED(d->SetVertexShader(path?vs.Get():nullptr))||FAILED(d->SetPixelShader(path?ps.Get():nullptr))||!rs(D3DRS_MULTISAMPLEMASK,1u<<sample))return 1;
                            if(FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff123456,1,0))||FAILED(d->BeginScene()))return 1;
                            const HRESULT draw=d->DrawPrimitive(D3DPT_TRIANGLELIST,0,static_cast<UINT>(mesh.size()/3));const HRESULT end=d->EndScene();
                            if(FAILED(draw)||FAILED(end)||FAILED(d->StretchRect(target.Get(),nullptr,resolved.Get(),nullptr,D3DTEXF_NONE))||FAILED(d->GetRenderTargetData(resolved.Get(),system.Get())))return 1;
                            D3DLOCKED_RECT lock{};if(FAILED(system->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return 1;
                            images[path].resize(256*192*4);for(unsigned y=0;y<192;++y)std::memcpy(images[path].data()+y*256*4,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch,256*4);if(FAILED(system->UnlockRect()))return 1;
                            std::ofstream image(root/("mask-n"+std::to_string(zero)+"-s"+std::to_string(sample)+"-p"+std::to_string(path)+".bgra"),std::ios::binary|std::ios::trunc);image.write(reinterpret_cast<const char*>(images[path].data()),images[path].size());if(!image)return 1;
                        }
                        unsigned diff=0;for(size_t at=0;at<images[0].size();at+=4)if(std::memcmp(images[0].data()+at,images[1].data()+at,4))++diff;
                        report<<"SAMPLE_MASK normalMode="<<zero<<" sample="<<sample<<" fixedShaderDifferentPixels="<<diff<<" verification=resolved_mask_control\n";
                    }
                    if(!rs(D3DRS_MULTISAMPLEMASK,0xffffffff))return 1;
                }
                if(shaderMaximum)++failed;
                report<<"EXPLICIT samples="<<samples<<" normalMode="<<zero<<" centroid="<<centroid<<" repeats="<<repeats<<" maximumDifferentPixels="<<shaderMaximum<<" fixedBaselineDifferentPixels="<<fixedDiff<<" formulaEquivalence=NOT_VERIFIED zeroNormalPolicy=explicit_zero\n";
                }
                if(FAILED(d->SetVertexShader(nullptr))||FAILED(d->SetPixelShader(nullptr)))return 1;
            }

        }
    }
    const auto diff=[](const std::vector<unsigned char>& a,const std::vector<unsigned char>& b){unsigned n=0;for(size_t i=0;i<a.size();i+=4)if(std::memcmp(a.data()+i,b.data()+i,4))++n;return n;};
    if(!triangleMode)for(unsigned base:{0u,16u}){
        const auto lighting=diff(caseImages[base],caseImages[base+1]);
        const auto normalize=diff(caseImages[base+1],caseImages[base+5]);
        const auto specular=diff(caseImages[base+5],caseImages[base+7]);
        const auto zero=diff(caseImages[base+5],caseImages[base+13]);
        report<<"SENSITIVITY samples="<<(base?8:1)<<" lightingChangedPixels="<<lighting<<" normalizationChangedPixels="<<normalize<<" specularChangedPixels="<<specular<<" zeroNormalChangedPixels="<<zero<<"\n";
        if(!lighting||!normalize||!specular||!zero)++failed;
    }
    report<<"SUMMARY failedCases="<<failed<<" proceduralCases="<<caseImages.size()<<" triangles="<<(triangleMode?triangleMode:1152)<<" repeatsPerCase="<<repeats<<" realPmmGate=NOT_PASSED\n";
    return failed?2:0;
}
