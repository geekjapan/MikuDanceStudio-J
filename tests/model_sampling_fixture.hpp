#pragma once
// Test-only raster observations. DX11 shared geometry must match its prior
// image; DX9 proxy failures are retained. Native-vertex PS observations must
// preserve both original byte images and untouched fixed-function float color.
namespace model_sampling_diagnostic {
using Color=std::array<float,4>;
struct Vertex {Color clip;std::array<float,2> uv;};
struct Area {unsigned x,y,width,height;};
struct Renderer {
    ComPtr<IDirect3D9> api;ComPtr<IDirect3DDevice9> d9;
    ComPtr<ID3D11Device> d11;ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDirect3DVertexShader9> vs9;ComPtr<IDirect3DVertexDeclaration9> layout9;
    ComPtr<IDirect3DVertexShader9> legacyVs9;
    ComPtr<ID3D11VertexShader> vs11;ComPtr<ID3D11InputLayout> layout11;
    std::vector<ComPtr<IDirect3DPixelShader9>> ps9;
    std::vector<ComPtr<IDirect3DPixelShader9>> legacyPs9;
    std::vector<ComPtr<ID3D11PixelShader>> ps11;
    std::array<ComPtr<IDirect3DSurface9>,2> target9,cpu9;
    std::array<ComPtr<ID3D11Texture2D>,2> target11,cpu11;
    std::array<ComPtr<ID3D11RenderTargetView>,2> views;
    ComPtr<IDirect3DTexture9> texture9;ComPtr<ID3D11Texture2D> texture11;ComPtr<ID3D11ShaderResourceView> textureView;
    ComPtr<ID3D11RasterizerState> raster;ComPtr<ID3D11DepthStencilState> depth;
    unsigned width=0,height=0;D3DVIEWPORT9 viewport{};Area roi{};
    std::string adapter;
    static bool Compile(const std::string& text,const char* profile,ComPtr<ID3DBlob>& blob) {
        ComPtr<ID3DBlob> error;const auto hr=D3DCompile(text.data(),text.size(),nullptr,nullptr,nullptr,"main",profile,D3DCOMPILE_IEEE_STRICTNESS,0,&blob,&error);
        if(FAILED(hr) && error)std::fprintf(stderr,"sampling %s: %s\n",profile,static_cast<const char*>(error->GetBufferPointer()));return SUCCEEDED(hr);
    }
    bool Initialize(HWND window,unsigned w,unsigned h,const D3DVIEWPORT9& region,const Area& crop,const ModelTextureData& mipData) {
        width=w;height=h;viewport=region;roi=crop;if(!w || !h || !crop.width || !crop.height || crop.x+crop.width>w || crop.y+crop.height>h || mipData.levels.empty())return false;
        api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return false;
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=w;pp.BackBufferHeight=h;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;
        const auto hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d9);
        if(FAILED(hr)){std::fprintf(stderr,"sampling DX9 CreateDevice=%08lx\n",static_cast<unsigned long>(hr));return false;}
        D3DADAPTER_IDENTIFIER9 id{};if(FAILED(api->GetAdapterIdentifier(0,0,&id)))return false;adapter=id.Description;
        D3D_FEATURE_LEVEL level;if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&d11,&level,&context)) || level<D3D_FEATURE_LEVEL_11_0)return false;
        ComPtr<ID3DBlob> a,b;
        if(!Compile("struct O{float4 p:POSITION;float2 uv:TEXCOORD0;};O main(float4 p:POSITION,float2 uv:TEXCOORD0){O o;o.p=p;o.uv=uv;return o;}","vs_3_0",a) ||
           !Compile("struct O{float4 p:SV_POSITION;float2 uv:TEXCOORD0;};O main(float4 p:POSITION,float2 uv:TEXCOORD0){O o;o.p=p;o.uv=uv;return o;}","vs_5_0",b))return false;
        const D3DVERTEXELEMENT9 e9[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT2,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_TEXCOORD,0},D3DDECL_END()};
        const D3D11_INPUT_ELEMENT_DESC e11[]={{"POSITION",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,16,D3D11_INPUT_PER_VERTEX_DATA,0}};
        if(FAILED(d9->CreateVertexShader(static_cast<DWORD*>(a->GetBufferPointer()),&vs9)) || FAILED(d9->CreateVertexDeclaration(e9,&layout9)) ||
           FAILED(d11->CreateVertexShader(b->GetBufferPointer(),b->GetBufferSize(),nullptr,&vs11)) || FAILED(d11->CreateInputLayout(e11,2,b->GetBufferPointer(),b->GetBufferSize(),&layout11)))return false;
        if(!Compile("struct O{float4 p:POSITION;float2 uv:TEXCOORD0;};O main(float4 p:POSITION,float2 uv:TEXCOORD0){O o;o.p=p;o.uv=uv;return o;}","vs_2_0",a) || FAILED(d9->CreateVertexShader(static_cast<DWORD*>(a->GetBufferPointer()),&legacyVs9)))return false;
        // Modes 0..3: sampling, UV, ddx/ddy, explicit gradients. 4..12: LOD 0..8.
        for(unsigned mode=0;mode<14;++mode){std::string expression9,expression11;
            if(mode==0){expression9="tex2D(tex,uv)";expression11="tex.Sample(sampling,uv)";}
            else if(mode==1){expression9=expression11="float4(uv,0,1)";}
            else if(mode==2){expression9=expression11="float4(ddx(uv),ddy(uv))";}
            else if(mode==3){expression9="tex2Dgrad(tex,uv,ddx(uv),ddy(uv))";expression11="tex.SampleGrad(sampling,uv,ddx(uv),ddy(uv))";}
            else if(mode==13){expression9="tex2Dgrad(tex,query.xy,gradients.xy,gradients.zw)";expression11="tex.SampleGrad(sampling,query.xy,gradients.xy,gradients.zw)";}
            else {expression9="tex2Dlod(tex,float4(uv,0,"+std::to_string(mode-4)+"))";expression11="tex.SampleLevel(sampling,uv,"+std::to_string(mode-4)+")";}
            const std::string p9="sampler2D tex:register(s0);float4 query:register(c0);float4 gradients:register(c1);float4 main(float2 uv:TEXCOORD0):COLOR0{return "+expression9+";}";
            const std::string p11="Texture2D tex:register(t0);SamplerState sampling:register(s0);cbuffer Q:register(b0){float4 query,gradients;}float4 main(float4 p:SV_POSITION,float2 uv:TEXCOORD0):SV_TARGET{return "+expression11+";}";
            if(!Compile(p9,"ps_3_0",a) || !Compile(p11,"ps_5_0",b))return false;
            ComPtr<IDirect3DPixelShader9> p;ComPtr<ID3D11PixelShader> q;
            if(FAILED(d9->CreatePixelShader(static_cast<DWORD*>(a->GetBufferPointer()),&p)) || FAILED(d11->CreatePixelShader(b->GetBufferPointer(),b->GetBufferSize(),nullptr,&q)))return false;ps9.push_back(p);ps11.push_back(q);
            ComPtr<IDirect3DPixelShader9> legacy;if(mode<4 && (!Compile(p9,"ps_2_a",a) || FAILED(d9->CreatePixelShader(static_cast<DWORD*>(a->GetBufferPointer()),&legacy))))return false;legacyPs9.push_back(legacy);
        }
        D3D11_RASTERIZER_DESC rs{};rs.FillMode=D3D11_FILL_SOLID;rs.CullMode=D3D11_CULL_NONE;rs.DepthClipEnable=TRUE;
        D3D11_DEPTH_STENCIL_DESC ds{};ds.DepthFunc=D3D11_COMPARISON_ALWAYS;
        if(FAILED(d11->CreateRasterizerState(&rs,&raster)) || FAILED(d11->CreateDepthStencilState(&ds,&depth)))return false;
        for(unsigned format=0;format<2;++format){const auto f9=format?D3DFMT_A32B32G32R32F:D3DFMT_A8R8G8B8;
            if(FAILED(d9->CreateRenderTarget(w,h,f9,D3DMULTISAMPLE_NONE,0,FALSE,&target9[format],nullptr)) || FAILED(d9->CreateOffscreenPlainSurface(w,h,f9,D3DPOOL_SYSTEMMEM,&cpu9[format],nullptr)))return false;
            D3D11_TEXTURE2D_DESC td{};td.Width=w;td.Height=h;td.MipLevels=td.ArraySize=1;td.SampleDesc.Count=1;td.Format=format?DXGI_FORMAT_R32G32B32A32_FLOAT:DXGI_FORMAT_R8G8B8A8_UNORM;td.BindFlags=D3D11_BIND_RENDER_TARGET;
            if(FAILED(d11->CreateTexture2D(&td,nullptr,&target11[format])) || FAILED(d11->CreateRenderTargetView(target11[format].Get(),nullptr,&views[format])))return false;
            td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;if(FAILED(d11->CreateTexture2D(&td,nullptr,&cpu11[format])))return false;
        }
        const auto& top=mipData.levels.front();if(FAILED(d9->CreateTexture(top.width,top.height,static_cast<UINT>(mipData.levels.size()),0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&texture9,nullptr)))return false;
        std::vector<D3D11_SUBRESOURCE_DATA> initial;
        for(unsigned n=0;n<mipData.levels.size();++n){const auto& levelData=mipData.levels[n];D3DLOCKED_RECT lock{};
            if(FAILED(texture9->LockRect(n,&lock,nullptr,0)))return false;
            for(unsigned y=0;y<levelData.height;++y)for(unsigned x=0;x<levelData.width;++x){auto* dst=static_cast<unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;const auto* src=levelData.pixels.data()+(std::size_t(y)*levelData.width+x)*4;dst[0]=src[2];dst[1]=src[1];dst[2]=src[0];dst[3]=src[3];}
            if(FAILED(texture9->UnlockRect(n)))return false;initial.push_back({levelData.pixels.data(),levelData.width*4,0});
        }
        D3D11_TEXTURE2D_DESC td{};td.Width=top.width;td.Height=top.height;td.MipLevels=static_cast<UINT>(initial.size());td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.Usage=D3D11_USAGE_IMMUTABLE;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        return SUCCEEDED(d11->CreateTexture2D(&td,initial.data(),&texture11)) && SUCCEEDED(d11->CreateShaderResourceView(texture11.Get(),nullptr,&textureView));
    }
    bool Render(const std::array<Vertex,3>& vertices,unsigned shader,unsigned format,unsigned filter,std::vector<Color>& native,std::vector<Color>& candidate,
                std::vector<unsigned char>& nativeBytes,std::vector<unsigned char>& candidateBytes,const Color& query={},const Color& gradients={},bool legacyLink=false) {
        if(shader>=ps9.size() || format>1 || filter>2 || (legacyLink && !legacyPs9[shader]))return false;
        const unsigned minmag=filter==0?D3DTEXF_ANISOTROPIC:filter==1?D3DTEXF_LINEAR:D3DTEXF_POINT;
        const unsigned mip=filter==0?D3DTEXF_ANISOTROPIC:D3DTEXF_POINT;
        if(FAILED(d9->SetRenderTarget(0,target9[format].Get())) || FAILED(d9->SetDepthStencilSurface(nullptr)) || FAILED(d9->SetVertexDeclaration(layout9.Get())) || FAILED(d9->SetVertexShader(legacyLink?legacyVs9.Get():vs9.Get())) || FAILED(d9->SetPixelShader(legacyLink?legacyPs9[shader].Get():ps9[shader].Get())) || FAILED(d9->SetTexture(0,texture9.Get())))return false;
        for(auto state:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,FALSE},{D3DRS_ZWRITEENABLE,FALSE},{D3DRS_CULLMODE,D3DCULL_NONE},{D3DRS_ALPHABLENDENABLE,FALSE},{D3DRS_ALPHATESTENABLE,FALSE},{D3DRS_STENCILENABLE,FALSE},{D3DRS_SCISSORTESTENABLE,FALSE},{D3DRS_SRGBWRITEENABLE,FALSE},{D3DRS_DITHERENABLE,FALSE},{D3DRS_COLORWRITEENABLE,15}})
            if(FAILED(d9->SetRenderState(state.first,state.second)))return false;
        for(auto state:{std::pair<D3DSAMPLERSTATETYPE,DWORD>{D3DSAMP_MINFILTER,minmag},{D3DSAMP_MAGFILTER,minmag},{D3DSAMP_MIPFILTER,mip},{D3DSAMP_MAXANISOTROPY,16},{D3DSAMP_ADDRESSU,D3DTADDRESS_WRAP},{D3DSAMP_ADDRESSV,D3DTADDRESS_WRAP},{D3DSAMP_SRGBTEXTURE,0},{D3DSAMP_MAXMIPLEVEL,0},{D3DSAMP_MIPMAPLODBIAS,0}})
            if(FAILED(d9->SetSamplerState(0,state.first,state.second)))return false;
        if(FAILED(d9->SetPixelShaderConstantF(0,query.data(),1)) || FAILED(d9->SetPixelShaderConstantF(1,gradients.data(),1)))return false;
        const D3DVIEWPORT9 full{0,0,width,height,0,1};if(FAILED(d9->SetViewport(&full)) || FAILED(d9->Clear(0,nullptr,D3DCLEAR_TARGET,0xffffffff,1,0)) || FAILED(d9->SetViewport(&viewport)) || FAILED(d9->BeginScene()))return false;
        const auto draw=d9->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,vertices.data(),sizeof(Vertex));const auto end=d9->EndScene();
        if(FAILED(draw) || FAILED(end) || FAILED(d9->GetRenderTargetData(target9[format].Get(),cpu9[format].Get())))return false;
        D3DLOCKED_RECT lock{};if(FAILED(cpu9[format]->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
        if(shader==0 && !format)for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)if(x<roi.x || x>=roi.x+roi.width || y<roi.y || y>=roi.y+roi.height){DWORD pixel;std::memcpy(&pixel,static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*4,4);if(pixel!=0xffffffff){cpu9[format]->UnlockRect();return false;}}
        native.resize(std::size_t(roi.width)*roi.height);nativeBytes.clear();candidateBytes.clear();if(!format)nativeBytes.resize(native.size()*4);
        for(unsigned y=0;y<roi.height;++y)for(unsigned x=0;x<roi.width;++x){const auto p=std::size_t(y)*roi.width+x;const auto* src=static_cast<const unsigned char*>(lock.pBits)+(roi.y+y)*lock.Pitch+(roi.x+x)*(format?16:4);
            if(format)std::memcpy(native[p].data(),src,16);else for(unsigned k=0;k<4;++k){const unsigned order[]={2,1,0,3};nativeBytes[p*4+k]=src[order[k]];native[p][k]=src[order[k]]/255.f;}}
        if(FAILED(cpu9[format]->UnlockRect()))return false;
        D3D11_BUFFER_DESC bd{};bd.ByteWidth=sizeof(vertices);bd.BindFlags=D3D11_BIND_VERTEX_BUFFER;D3D11_SUBRESOURCE_DATA vbData{vertices.data(),0,0};ComPtr<ID3D11Buffer> vb,cb;
        if(FAILED(d11->CreateBuffer(&bd,&vbData,&vb)))return false;const std::array<Color,2> parameters{query,gradients};bd.ByteWidth=sizeof(parameters);bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;D3D11_SUBRESOURCE_DATA cbData{parameters.data(),0,0};if(FAILED(d11->CreateBuffer(&bd,&cbData,&cb)))return false;
        D3D11_SAMPLER_DESC sd{};sd.Filter=filter==0?D3D11_FILTER_ANISOTROPIC:filter==1?D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT:D3D11_FILTER_MIN_MAG_MIP_POINT;sd.MaxAnisotropy=16;sd.MaxLOD=D3D11_FLOAT32_MAX;sd.AddressU=sd.AddressV=D3D11_TEXTURE_ADDRESS_WRAP;sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;
        ComPtr<ID3D11SamplerState> sampler;if(FAILED(d11->CreateSamplerState(&sd,&sampler)))return false;
        auto* view=views[format].Get();const float white[]={1,1,1,1};context->OMSetRenderTargets(1,&view,nullptr);context->ClearRenderTargetView(view,white);context->OMSetDepthStencilState(depth.Get(),0);context->OMSetBlendState(nullptr,nullptr,~0u);
        const D3D11_VIEWPORT v{float(viewport.X)+.5f,float(viewport.Y)+.5f,float(viewport.Width),float(viewport.Height),viewport.MinZ,viewport.MaxZ};context->RSSetViewports(1,&v);context->RSSetState(raster.Get());
        const UINT stride=sizeof(Vertex),offset=0;auto* buffer=vb.Get();auto* constants=cb.Get();auto* srv=textureView.Get();auto* sampling=sampler.Get();
        context->IASetInputLayout(layout11.Get());context->IASetVertexBuffers(0,1,&buffer,&stride,&offset);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context->VSSetShader(vs11.Get(),nullptr,0);context->PSSetShader(ps11[shader].Get(),nullptr,0);context->PSSetConstantBuffers(0,1,&constants);context->PSSetShaderResources(0,1,&srv);context->PSSetSamplers(0,1,&sampling);context->Draw(3,0);
        context->CopyResource(cpu11[format].Get(),target11[format].Get());D3D11_MAPPED_SUBRESOURCE map{};if(FAILED(context->Map(cpu11[format].Get(),0,D3D11_MAP_READ,0,&map)))return false;
        if(shader==0 && !format)for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)if(x<roi.x || x>=roi.x+roi.width || y<roi.y || y>=roi.y+roi.height){DWORD pixel;std::memcpy(&pixel,static_cast<const unsigned char*>(map.pData)+y*map.RowPitch+x*4,4);if(pixel!=0xffffffff){context->Unmap(cpu11[format].Get(),0);return false;}}
        candidate.resize(native.size());if(!format)candidateBytes.resize(candidate.size()*4);
        for(unsigned y=0;y<roi.height;++y)for(unsigned x=0;x<roi.width;++x){const auto p=std::size_t(y)*roi.width+x;const auto* src=static_cast<const unsigned char*>(map.pData)+(roi.y+y)*map.RowPitch+(roi.x+x)*(format?16:4);
            if(format)std::memcpy(candidate[p].data(),src,16);else for(unsigned k=0;k<4;++k){candidateBytes[p*4+k]=src[k];candidate[p][k]=src[k]/255.f;}}
        context->Unmap(cpu11[format].Get(),0);return true;
    }
};
inline std::vector<unsigned char> CropReference(const std::filesystem::path& path,const D3DVIEWPORT9& region,const Area& area) {
    std::ifstream file(path,std::ios::binary);std::vector<unsigned char> source(std::istreambuf_iterator<char>{file},{}),result;
    if(source.size()!=std::size_t(region.Width)*region.Height*4)return {};
    result.resize(std::size_t(area.width)*area.height*4);
    for(unsigned y=0;y<area.height;++y)for(unsigned x=0;x<area.width;++x){const auto* src=source.data()+((area.y+y-region.Y)*std::size_t(region.Width)+area.x+x-region.X)*4;auto* dst=result.data()+(std::size_t(y)*area.width+x)*4;dst[0]=src[2];dst[1]=src[1];dst[2]=src[0];dst[3]=src[3];}return result;
}
inline int Run(HWND window,const char* archivePath,const char* referencePath,const char* outputPath) {
    const std::filesystem::path source(archivePath),reference(referencePath),output(outputPath);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    ground_history_isolation::Archive archive;CHECK(archive.Load(archivePath,42));const auto& c=archive.draws.back();
    // Bounds of all 133 previously covered pixels, padded by two pixels. Keep
    // the full viewport for rasterization and derivatives; crop only readback.
    const Area area{847,333,42,27};Renderer renderer;CHECK(renderer.Initialize(window,archive.width,archive.height,archive.region,area,c.preparedMips[1]));
    std::ofstream metadata(output/"metadata.txt");metadata<<"draw=42 width="<<archive.width<<" height="<<archive.height<<" roi="<<area.x<<","<<area.y<<","<<area.width<<","<<area.height<<" samples=1 center=viewport productionActivation=0 adapter="<<renderer.adapter<<"\n";
    std::ofstream table(output/"observations.csv");table<<"triangle,mode,format,shader,filter,differentPixels,maxAbsDelta\n"<<std::setprecision(17);
    unsigned measurements=0;std::ofstream gates(output/"gates.csv");gates<<"triangle,sharedDx9ReferencePixels,sharedDx11ReferencePixels,nativeVertexPsReferencePixels\n";
    std::ofstream feed(output/"crossfeed.csv");feed<<"triangle,x,y,inputPath,u,v,dxU,dxV,dyU,dyV,nR,nG,nB,nA,cR,cG,cB,cA,nR8,nG8,nB8,nA8,cR8,cG8,cB8,cA8\n"<<std::setprecision(17);unsigned feedCount=0;
    for(unsigned triangle:{1478u,1822u,1823u}){
        auto compact=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(c,triangle,1));const auto label="compact_"+std::to_string(triangle);
        std::vector<Color> positions,colors;std::vector<std::array<float,2>> uv;
        CHECK(CaptureDepthVertexShader(compact,positions,nullptr,false,3,&colors,nullptr,nullptr,true,&uv,1,true));CHECK(positions.size()==3 && uv.size()==3);
        std::array<Vertex,3> vertices;for(unsigned n=0;n<3;++n)vertices[n]={positions[n],uv[n]};
        std::ofstream input(output/(label+".input"),std::ios::binary);input.write(reinterpret_cast<const char*>(vertices.data()),sizeof(vertices));CHECK(input);
        auto pure=model_color_isolation::Control(compact,8);Stage(pure,0,D3DTSS_TEXCOORDINDEX,0);Stage(pure,0,D3DTSS_TEXTURETRANSFORMFLAGS,0);
        for(unsigned n=0;n<3;++n)std::memcpy(pure.vertexBytes.data()+n*32+24,uv[n].data(),8);
        for(unsigned key:{unsigned(D3DRS_LIGHTING),unsigned(D3DRS_SPECULARENABLE),unsigned(D3DRS_ALPHABLENDENABLE),unsigned(D3DRS_ALPHATESTENABLE),unsigned(D3DRS_ZENABLE),unsigned(D3DRS_ZWRITEENABLE),unsigned(D3DRS_STENCILENABLE)})ground_history_isolation::State(pure,key,0);
        auto observe=[&](const std::string& mode,unsigned shader,unsigned filter,unsigned format,std::vector<Color>* savedN=nullptr,std::vector<Color>* savedC=nullptr,bool legacy=false){
            std::vector<Color> a,b;std::vector<unsigned char> aa,bb;if(!renderer.Render(vertices,shader,format,filter,a,b,aa,bb,{},{},legacy))return false;
            unsigned count=0;double maximum=0;for(unsigned p=0;p<a.size();++p){bool different=false;for(unsigned k=0;k<4;++k){if(!std::isfinite(a[p][k]) || !std::isfinite(b[p][k]))return false;different|=a[p][k]!=b[p][k];maximum=(std::max)(maximum,std::abs(double(a[p][k])-b[p][k]));}count+=different;}
            table<<triangle<<","<<mode<<","<<format<<","<<shader<<","<<filter<<","<<count<<","<<maximum<<"\n";table.flush();
            for(unsigned side=0;side<2;++side){std::ofstream file(output/(label+"_"+mode+(side?".dx11":".dx9")+(format?".float":".rgba")),std::ios::binary);const auto& values=side?b:a;const auto& bytes=side?bb:aa;if(format)file.write(reinterpret_cast<const char*>(values.data()),values.size()*sizeof(Color));else file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());if(!file)return false;}
            if(savedN)*savedN=a;if(savedC)*savedC=b;++measurements;std::printf("sampling triangle=%u mode=%s float=%u differentPixels=%u maxAbsDelta=%.9g\n",triangle,mode.c_str(),format,count,maximum);std::fflush(stdout);return true;
        };
        CHECK(observe("auto",0,0,0));
        unsigned sharedDifferent[2]{};
        for(unsigned side=0;side<2;++side){const auto ref=CropReference(reference/(label+"_pure_shared_uv"+(side?".candidate.bgra":".native.bgra")),archive.region,area);
            std::ifstream file(output/(label+"_auto"+(side?".dx11.rgba":".dx9.rgba")),std::ios::binary);const std::vector<unsigned char> result(std::istreambuf_iterator<char>{file},{});CHECK(!ref.empty() && ref.size()==result.size());
            for(unsigned p=0;p<ref.size()/4;++p)sharedDifferent[side]+=std::memcmp(ref.data()+p*4,result.data()+p*4,4)!=0;
            if(side)CHECK(!sharedDifferent[side]);}
        std::vector<Color> nativeAuto,candidateAuto;CHECK(observe("auto",0,0,1,&nativeAuto,&candidateAuto));
        RgbaImage unused;std::vector<Color> fixed;CHECK(NativeImage(window,{pure},1,unused,nullptr,archive.width,archive.height,archive.clear,&fixed));
        std::vector<Color> fixedCrop(std::size_t(area.width)*area.height);for(unsigned y=0;y<area.height;++y)std::copy_n(fixed.begin()+(area.y+y)*archive.width+area.x,area.width,fixedCrop.begin()+y*area.width);
        std::ofstream fixedFile(output/(label+".fixed.float"),std::ios::binary);fixedFile.write(reinterpret_cast<const char*>(fixedCrop.data()),fixedCrop.size()*sizeof(Color));CHECK(fixedFile);
        auto frozenPure=pure;CHECK(model_color_isolation::FreezeMips(frozenPure,0));std::vector<Color> frozenPixels;
        CHECK(NativeImage(window,{frozenPure},1,unused,nullptr,archive.width,archive.height,archive.clear,&frozenPixels));
        std::ofstream frozenFile(output/(label+".frozen_fixed.float"),std::ios::binary);
        for(unsigned y=0;y<area.height;++y){const auto* observed=frozenPixels.data()+(area.y+y)*archive.width+area.x;CHECK(!std::memcmp(observed,fixedCrop.data()+y*area.width,area.width*sizeof(Color)));frozenFile.write(reinterpret_cast<const char*>(observed),area.width*sizeof(Color));}CHECK(frozenFile);
        unsigned nativeVertexDifferent=0;std::vector<Color> nativeUv,nativeGrad;
        for(unsigned mode=0;mode<4;++mode)for(unsigned format=0;format<2;++format){if((mode==1 || mode==2) && !format)continue;
            const std::string expression=mode==0?"tex2D(tex,uv)":mode==1?"float4(uv,0,1)":mode==2?"float4(ddx(uv),ddy(uv))":"tex2Dgrad(tex,uv,ddx(uv),ddy(uv))";
            const std::string ps="sampler2D tex:register(s0);float4 main(float2 uv:TEXCOORD0):COLOR0{return "+expression+";}";
            RgbaImage image;std::vector<Color> pixels;CHECK(NativeImage(window,{pure},1,image,nullptr,archive.width,archive.height,archive.clear,format?&pixels:nullptr,&ps));
            const std::string name=label+".native_vertex_"+(mode==0?"sample":mode==1?"uv":mode==2?"gradients":"explicit_grad");
            std::ofstream file(output/(name+(format?".float":".rgba")),std::ios::binary);
            if(format){std::vector<Color> crop(std::size_t(area.width)*area.height);for(unsigned y=0;y<area.height;++y){std::copy_n(pixels.begin()+(area.y+y)*archive.width+area.x,area.width,crop.begin()+y*area.width);file.write(reinterpret_cast<const char*>(crop.data()+y*area.width),area.width*sizeof(Color));}
                if(mode==1)nativeUv=crop;if(mode==2)nativeGrad=crop;if(mode==0)CHECK(crop==fixedCrop);}
            else{std::vector<unsigned char> bytes(std::size_t(area.width)*area.height*4);for(unsigned y=0;y<area.height;++y)std::copy_n(image.pixels.begin()+((area.y+y)*archive.width+area.x)*4,area.width*4,bytes.begin()+y*area.width*4);file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
                if(mode==0){const auto ref=CropReference(reference/(label+"_pure_shared_uv.native.bgra"),archive.region,area);for(unsigned p=0;p<ref.size()/4;++p)nativeVertexDifferent+=std::memcmp(ref.data()+p*4,bytes.data()+p*4,4)!=0;}}
            CHECK(file);}
        gates<<triangle<<","<<sharedDifferent[0]<<","<<sharedDifferent[1]<<","<<nativeVertexDifferent<<"\n";gates.flush();
        CHECK(!nativeVertexDifferent);
        for(unsigned mode=0;mode<3;++mode)for(unsigned repeat=1;repeat<=3;++repeat){const std::string expression=mode==0?"tex2D(tex,uv)":mode==1?"float4(uv,0,1)":"float4(ddx(uv),ddy(uv))";
            const std::string ps="sampler2D tex:register(s0);float4 main(float2 uv:TEXCOORD0):COLOR0{return "+expression+";}";std::vector<Color> pixels;RgbaImage image;
            CHECK(NativeImage(window,{pure},1,image,nullptr,archive.width,archive.height,archive.clear,&pixels,&ps));const auto& expected=mode==0?fixedCrop:mode==1?nativeUv:nativeGrad;
            std::ofstream file(output/(label+".native_vertex_"+(mode==0?"sample":mode==1?"uv":"gradients")+".repeat"+std::to_string(repeat)+".float"),std::ios::binary);
            for(unsigned y=0;y<area.height;++y){const auto* observed=pixels.data()+(area.y+y)*archive.width+area.x;CHECK(!std::memcmp(observed,expected.data()+y*area.width,area.width*sizeof(Color)));file.write(reinterpret_cast<const char*>(observed),area.width*sizeof(Color));}CHECK(file);}
        for(unsigned repeat=1;repeat<=3;++repeat){std::vector<Color> a,b;CHECK(observe("auto_repeat"+std::to_string(repeat),0,0,1,&a,&b));CHECK(a==nativeAuto && b==candidateAuto);}
        std::vector<Color> sharedUv,sharedGrad;CHECK(observe("uv",1,0,1,nullptr,&sharedUv));CHECK(observe("gradients",2,0,1,nullptr,&sharedGrad));CHECK(observe("explicit_grad",3,0,1));
        CHECK(observe("legacy_auto",0,0,0,nullptr,nullptr,true));CHECK(observe("legacy_auto",0,0,1,nullptr,nullptr,true));
        CHECK(observe("legacy_uv",1,0,1,nullptr,nullptr,true));CHECK(observe("legacy_gradients",2,0,1,nullptr,nullptr,true));
        CHECK(observe("linear_auto",0,1,0));CHECK(observe("linear_auto",0,1,1));CHECK(observe("point_auto",0,2,0));CHECK(observe("point_auto",0,2,1));
        for(unsigned lod=0;lod<=8;++lod){CHECK(observe("lod"+std::to_string(lod),lod+4,1,0));CHECK(observe("lod"+std::to_string(lod),lod+4,1,1));}
        // PS2 has no texldl. Zero explicit gradients force top-level sampling;
        // min/mag linear with point mip makes the LOD0 control unambiguous.
        auto nativeLod=model_color_isolation::Control(frozenPure,14);
        const std::string zeroGrad="sampler2D tex:register(s0);float4 main(float2 uv:TEXCOORD0):COLOR0{return tex2Dgrad(tex,uv,float2(0,0),float2(0,0));}";
        for(unsigned format=0;format<2;++format){RgbaImage image;std::vector<Color> pixels;
            CHECK(NativeImage(window,{nativeLod},1,image,nullptr,archive.width,archive.height,archive.clear,format?&pixels:nullptr,&zeroGrad));
            std::ofstream file(output/(label+".native_vertex_lod0"+(format?".float":".rgba")),std::ios::binary);
            for(unsigned y=0;y<area.height;++y){if(format)file.write(reinterpret_cast<const char*>(pixels.data()+(area.y+y)*archive.width+area.x),area.width*sizeof(Color));else file.write(reinterpret_cast<const char*>(image.pixels.data()+((area.y+y)*archive.width+area.x)*4),area.width*4);}CHECK(file);}
        const auto originalBytes=CropReference(reference/(label+"_pure_shared_uv.native.bgra"),archive.region,area);
        for(unsigned p=0;p<nativeUv.size();++p){if(std::memcmp(originalBytes.data()+p*4,"\xff\xff\xff\xff",4)==0)continue;
            // 0=native/native, 1=shared/shared, 2=native UV/shared gradients,
            // 3=shared UV/native gradients. No fitted or rounded inputs.
            for(unsigned inputPath=0;inputPath<4;++inputPath){const auto& value=(inputPath==1 || inputPath==3)?sharedUv[p]:nativeUv[p];const auto& derivative=(inputPath==1 || inputPath==2)?sharedGrad[p]:nativeGrad[p];
                const Color query{value[0],value[1],0,0};std::vector<Color> a,b;std::vector<unsigned char> aa,bb;CHECK(renderer.Render(vertices,13,1,0,a,b,aa,bb,query,derivative));
                feed<<triangle<<","<<area.x+p%area.width<<","<<area.y+p/area.width<<","<<inputPath<<","<<value[0]<<","<<value[1];for(float f:derivative)feed<<","<<f;for(float f:a[p])feed<<","<<f;for(float f:b[p])feed<<","<<f;
                CHECK(renderer.Render(vertices,13,0,0,a,b,aa,bb,query,derivative));for(unsigned k=0;k<4;++k)feed<<","<<unsigned(aa[p*4+k]);for(unsigned k=0;k<4;++k)feed<<","<<unsigned(bb[p*4+k]);feed<<"\n";++feedCount;}
        }feed.flush();
    }
    CHECK(metadata && table && gates && feed);std::ofstream summary(output/"summary.txt");summary<<"complete=1 triangles=3 measurements="<<measurements<<" crossfeed="<<feedCount<<" dx11ByteReferenceExact=1 dx9ProxyIsDiagnostic=1 nativeVertexPsFloatExact=1 repeats=3 productionActivation=0 imageAcceptance=0\n";CHECK(summary);return 0;
}
} // namespace model_sampling_diagnostic
