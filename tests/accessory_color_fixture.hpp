#pragma once

// Hardware observations only. Float render targets expose raster output, not
// native DX9 vertex-register contents. Shared inputs are counterfactual controls.
namespace accessory_color_diagnostic {
using Color=std::array<float,4>;
struct Vertex {Color clip,color;};

class Renderer {
    unsigned width=0,height=0;
    D3DVIEWPORT9 viewport{};
    ComPtr<IDirect3D9> api9;
    ComPtr<IDirect3DDevice9> d9;
    ComPtr<IDirect3DVertexShader9> vs9;
    ComPtr<IDirect3DPixelShader9> ps9;
    ComPtr<IDirect3DVertexDeclaration9> layout9;
    std::array<ComPtr<IDirect3DSurface9>,2> target9,cpu9;
    ComPtr<ID3D11Device> d11;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<ID3D11VertexShader> vs11,modelVs;
    ComPtr<ID3D11PixelShader> ps11;
    ComPtr<ID3D11InputLayout> layout11,modelLayout;
    ComPtr<ID3D11Buffer> viewportBuffer;
    std::array<ComPtr<ID3D11Texture2D>,2> target11,cpu11;
    std::array<ComPtr<ID3D11RenderTargetView>,2> rtv;
    ComPtr<ID3D11RasterizerState> raster;
    ComPtr<ID3D11DepthStencilState> noDepth;

    bool Read11(unsigned format,std::vector<Color>& pixels,RgbaImage& bytes) {
        context->CopyResource(cpu11[format].Get(),target11[format].Get());
        D3D11_MAPPED_SUBRESOURCE map{};
        if(FAILED(context->Map(cpu11[format].Get(),0,D3D11_MAP_READ,0,&map)))return false;
        pixels.resize(std::size_t(width)*height);
        if(!format)bytes={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
        for(unsigned y=0;y<height;++y) {
            const auto* row=static_cast<const unsigned char*>(map.pData)+y*map.RowPitch;
            if(format)std::memcpy(pixels.data()+std::size_t(y)*width,row,std::size_t(width)*16);
            else for(unsigned x=0;x<width;++x)for(unsigned k=0;k<4;++k){const auto at=std::size_t(y)*width+x;
                bytes.pixels[at*4+k]=row[x*4+k];pixels[at][k]=row[x*4+k]/255.f;}
        }
        context->Unmap(cpu11[format].Get(),0);return true;
    }
    void Bind11(unsigned format) {
        auto* view=rtv[format].Get();const float white[]={1,1,1,1};
        context->OMSetRenderTargets(1,&view,nullptr);context->ClearRenderTargetView(view,white);
        context->OMSetDepthStencilState(noDepth.Get(),0);context->OMSetBlendState(nullptr,nullptr,~0u);
        const D3D11_VIEWPORT v{float(viewport.X),float(viewport.Y),float(viewport.Width),float(viewport.Height),0,1};
        context->RSSetViewports(1,&v);context->RSSetState(raster.Get());context->PSSetShader(ps11.Get(),nullptr,0);
        context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    }
public:
    bool Initialize(HWND window,unsigned w,unsigned h,const D3DVIEWPORT9& area) {
        width=w;height=h;viewport=area;
        if(!w || !h || w>4096 || h>4096 || !area.Width || !area.Height || area.X+area.Width>w || area.Y+area.Height>h)return false;
        api9.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api9)return false;
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=w;pp.BackBufferHeight=h;
        pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;
        const auto hr=api9->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&d9);
        if(FAILED(hr)){std::fprintf(stderr,"sharedColor DX9 creation=%08lx\n",static_cast<unsigned long>(hr));return false;}
        D3DADAPTER_IDENTIFIER9 adapter{};if(FAILED(api9->GetAdapterIdentifier(0,0,&adapter)))return false;
        std::printf("sharedColorDevice adapter=%s viewport=%u,%u,%u,%u hardwareVP=1 samples=1\n",adapter.Description,area.X,area.Y,area.Width,area.Height);
        D3D_FEATURE_LEVEL level;
        if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&d11,&level,&context)) || level<D3D_FEATURE_LEVEL_11_0)return false;
        auto compile=[](const std::string& source,const char* profile,ComPtr<ID3DBlob>& blob){ComPtr<ID3DBlob> error;
            const auto result=D3DCompile(source.data(),source.size(),nullptr,nullptr,nullptr,"main",profile,D3DCOMPILE_IEEE_STRICTNESS,0,&blob,&error);
            if(FAILED(result) && error)std::fprintf(stderr,"sharedColor %s: %s\n",profile,static_cast<const char*>(error->GetBufferPointer()));return SUCCEEDED(result);};
        ComPtr<ID3DBlob> v9,p9,v11,p11,modelCode;
        const std::string vertex9="struct O{float4 p:POSITION;float4 c:COLOR0;};O main(float4 p:POSITION,float4 c:COLOR0){O o;o.p=p;o.c=c;return o;}";
        const std::string signature="struct O{float4 p:SV_POSITION;float4 c:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 s:COLOR1;};";
        const std::string vertex11="cbuffer V:register(b0){float4 parameters;}"+signature+"O main(float4 p:POSITION,float4 c:COLOR0){O o=(O)0;p.xy+=float2(1/parameters.y,-1/parameters.z)*p.w;o.p=p;o.c=c;return o;}";
        if(!compile(vertex9,"vs_3_0",v9) || !compile("float4 main(float4 c:COLOR0):COLOR0{return c;}","ps_3_0",p9) ||
           !compile(vertex11,"vs_5_0",v11) || !compile(signature+"float4 main(O input):SV_TARGET{return input.c;}","ps_5_0",p11) ||
           !compile(w_shader_diagnostic::Source(modelVertexSource),"vs_5_0",modelCode))return false;
        const D3DVERTEXELEMENT9 e9[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},
            {0,16,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
        const D3D11_INPUT_ELEMENT_DESC e11[]={{"POSITION",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
            {"COLOR",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,16,D3D11_INPUT_PER_VERTEX_DATA,0}};
        const D3D11_INPUT_ELEMENT_DESC m11[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
            {"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
        if(FAILED(d9->CreateVertexShader(static_cast<DWORD*>(v9->GetBufferPointer()),&vs9)) || FAILED(d9->CreatePixelShader(static_cast<DWORD*>(p9->GetBufferPointer()),&ps9)) || FAILED(d9->CreateVertexDeclaration(e9,&layout9)) ||
           FAILED(d11->CreateVertexShader(v11->GetBufferPointer(),v11->GetBufferSize(),nullptr,&vs11)) || FAILED(d11->CreatePixelShader(p11->GetBufferPointer(),p11->GetBufferSize(),nullptr,&ps11)) ||
           FAILED(d11->CreateInputLayout(e11,2,v11->GetBufferPointer(),v11->GetBufferSize(),&layout11)) ||
           FAILED(d11->CreateVertexShader(modelCode->GetBufferPointer(),modelCode->GetBufferSize(),nullptr,&modelVs)) || FAILED(d11->CreateInputLayout(m11,3,modelCode->GetBufferPointer(),modelCode->GetBufferSize(),&modelLayout)))return false;
        D3D11_RASTERIZER_DESC rs{};rs.FillMode=D3D11_FILL_SOLID;rs.CullMode=D3D11_CULL_NONE;rs.DepthClipEnable=TRUE;
        D3D11_DEPTH_STENCIL_DESC ds{};ds.DepthFunc=D3D11_COMPARISON_ALWAYS;
        if(FAILED(d11->CreateRasterizerState(&rs,&raster)) || FAILED(d11->CreateDepthStencilState(&ds,&noDepth)))return false;
        const Color parameters{0,float(area.Width),float(area.Height),0};D3D11_BUFFER_DESC bd{};bd.ByteWidth=16;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        D3D11_SUBRESOURCE_DATA initial{parameters.data(),0,0};if(FAILED(d11->CreateBuffer(&bd,&initial,&viewportBuffer)))return false;
        for(unsigned f=0;f<2;++f) {
            const auto format9=f?D3DFMT_A32B32G32R32F:D3DFMT_A8R8G8B8;
            if(FAILED(d9->CreateRenderTarget(w,h,format9,D3DMULTISAMPLE_NONE,0,FALSE,&target9[f],nullptr)) || FAILED(d9->CreateOffscreenPlainSurface(w,h,format9,D3DPOOL_SYSTEMMEM,&cpu9[f],nullptr)))return false;
            D3D11_TEXTURE2D_DESC td{};td.Width=w;td.Height=h;td.MipLevels=td.ArraySize=1;td.SampleDesc.Count=1;
            td.Format=f?DXGI_FORMAT_R32G32B32A32_FLOAT:DXGI_FORMAT_R8G8B8A8_UNORM;td.BindFlags=D3D11_BIND_RENDER_TARGET;
            if(FAILED(d11->CreateTexture2D(&td,nullptr,&target11[f])) || FAILED(d11->CreateRenderTargetView(target11[f].Get(),nullptr,&rtv[f])))return false;
            td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
            if(FAILED(d11->CreateTexture2D(&td,nullptr,&cpu11[f])))return false;
        }
        return true;
    }
    bool Shared(const std::array<Vertex,3>& vertices,unsigned format,std::vector<Color>& native,std::vector<Color>& replay,RgbaImage& nativeBytes,RgbaImage& replayBytes) {
        if(format>1)return false;
        if(FAILED(d9->SetRenderTarget(0,target9[format].Get())) || FAILED(d9->SetDepthStencilSurface(nullptr)) || FAILED(d9->SetViewport(&viewport)) ||
           FAILED(d9->SetVertexDeclaration(layout9.Get())) || FAILED(d9->SetVertexShader(vs9.Get())) || FAILED(d9->SetPixelShader(ps9.Get())))return false;
        for(auto s:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,FALSE},{D3DRS_ZWRITEENABLE,FALSE},{D3DRS_CULLMODE,D3DCULL_NONE},
            {D3DRS_ALPHABLENDENABLE,FALSE},{D3DRS_ALPHATESTENABLE,FALSE},{D3DRS_STENCILENABLE,FALSE},{D3DRS_SCISSORTESTENABLE,FALSE},
            {D3DRS_SRGBWRITEENABLE,FALSE},{D3DRS_DITHERENABLE,FALSE},{D3DRS_COLORWRITEENABLE,15}})if(FAILED(d9->SetRenderState(s.first,s.second)))return false;
        const D3DVIEWPORT9 full{0,0,width,height,0,1};
        if(FAILED(d9->SetViewport(&full)) || FAILED(d9->Clear(0,nullptr,D3DCLEAR_TARGET,0xffffffff,1,0)) ||
           FAILED(d9->SetViewport(&viewport)) || FAILED(d9->BeginScene()))return false;
        const auto draw=d9->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,vertices.data(),sizeof(Vertex));const auto end=d9->EndScene();
        if(FAILED(draw) || FAILED(end) || FAILED(d9->GetRenderTargetData(target9[format].Get(),cpu9[format].Get())))return false;
        D3DLOCKED_RECT map{};if(FAILED(cpu9[format]->LockRect(&map,nullptr,D3DLOCK_READONLY)))return false;
        native.resize(std::size_t(width)*height);if(!format)nativeBytes={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
        for(unsigned y=0;y<height;++y){const auto* row=static_cast<const unsigned char*>(map.pBits)+y*map.Pitch;
            if(format)std::memcpy(native.data()+std::size_t(y)*width,row,std::size_t(width)*16);
            else for(unsigned x=0;x<width;++x)for(unsigned k=0;k<4;++k){const unsigned order[]={2,1,0,3};const auto at=std::size_t(y)*width+x;
                nativeBytes.pixels[at*4+k]=row[x*4+order[k]];native[at][k]=row[x*4+order[k]]/255.f;}}
        if(FAILED(cpu9[format]->UnlockRect()))return false;
        D3D11_BUFFER_DESC bd{};bd.ByteWidth=sizeof(vertices);bd.BindFlags=D3D11_BIND_VERTEX_BUFFER;D3D11_SUBRESOURCE_DATA initial{vertices.data(),0,0};ComPtr<ID3D11Buffer> buffer;
        if(FAILED(d11->CreateBuffer(&bd,&initial,&buffer)))return false;
        Bind11(format);const UINT stride=sizeof(Vertex),offset=0;auto* vb=buffer.Get();auto* cb=viewportBuffer.Get();
        context->IASetInputLayout(layout11.Get());context->IASetVertexBuffers(0,1,&vb,&stride,&offset);context->VSSetShader(vs11.Get(),nullptr,0);context->VSSetConstantBuffers(0,1,&cb);
        context->Draw(3,0);return Read11(format,replay,replayBytes);
    }
    bool Model(const D3D9ReplaySnapshot& source,unsigned format,std::vector<Color>& pixels,RgbaImage& bytes) {
        ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.events.push_back({1,ModelReplayOp::Clear});
        if(format>1 || source.count!=1 || source.stride!=32 || source.indexFormat!=D3DFMT_INDEX16 || !AppendD3D9ReplaySnapshot(stream,source))return false;
        const auto& s=stream.events.back().draw.pipeline.shader;
        ModelVertexConstants c{};c.w=s.world;c.v=s.view;c.p=s.projection;c.n=s.normalView;c.transforms=s.textureTransforms;
        c.diffuse=s.nativeDiffuse;c.ambient=s.materialAmbient;c.specular=s.materialSpecular;c.emissive=s.emissive;c.globalAmbient=s.globalAmbient;
        c.flags={s.lighting,s.normalizeNormals,s.specularEnabled,s.localViewer};c.parameters={s.shininess,float(viewport.Width),float(viewport.Height),0};
        for(unsigned i=0;i<8;++i){const auto& l=s.lights[i];c.direction[i]={l.direction[0],l.direction[1],l.direction[2],l.enabled?1.f:0.f};
            c.lightDiffuse[i]=l.diffuse;c.lightAmbient[i]=l.ambient;c.lightSpecular[i]=l.specular;}
        for(unsigned i=0;i<3;++i)c.coordinates[i]=static_cast<unsigned>(s.layout.stages[i].coordinates);
        const auto diagnostic=w_shader_diagnostic::Inputs(c.w,c.v,c.p,3);
        auto make=[&](UINT size,UINT bind,const void* data,ComPtr<ID3D11Buffer>& buffer){D3D11_BUFFER_DESC bd{};bd.ByteWidth=size;bd.BindFlags=bind;D3D11_SUBRESOURCE_DATA initial{data,0,0};return SUCCEEDED(d11->CreateBuffer(&bd,&initial,&buffer));};
        ComPtr<ID3D11Buffer> vb,ib,cb,extra;
        if(!make(static_cast<UINT>(source.vertexBytes.size()),D3D11_BIND_VERTEX_BUFFER,source.vertexBytes.data(),vb) || !make(static_cast<UINT>(source.indexBytes.size()),D3D11_BIND_INDEX_BUFFER,source.indexBytes.data(),ib) ||
           !make(sizeof(c),D3D11_BIND_CONSTANT_BUFFER,&c,cb) || !make(sizeof(diagnostic),D3D11_BIND_CONSTANT_BUFFER,&diagnostic,extra))return false;
        Bind11(format);const UINT stride=32,offset=0;auto* vertices=vb.Get();ID3D11Buffer* uniforms[]={cb.Get(),extra.Get()};
        context->IASetInputLayout(modelLayout.Get());context->IASetVertexBuffers(0,1,&vertices,&stride,&offset);context->IASetIndexBuffer(ib.Get(),DXGI_FORMAT_R16_UINT,0);
        context->VSSetShader(modelVs.Get(),nullptr,0);context->VSSetConstantBuffers(0,2,uniforms);context->DrawIndexed(3,source.start,0);
        return Read11(format,pixels,bytes);
    }
};

inline unsigned Bits(float value){unsigned bits;std::memcpy(&bits,&value,4);return bits;}
} // namespace accessory_color_diagnostic

inline int SharedColorSmoke(HWND window) {
    using namespace accessory_color_diagnostic;
    Renderer renderer;CHECK(renderer.Initialize(window,64,64,{0,0,64,64,0,1}));
    unsigned comparisons=0;
    for(unsigned mode=0;mode<3;++mode){std::array<Vertex,3> vertices{{{{-.75f,-.75f,.5f,1},{.125f,.25f,.75f,1}},
        {{-.75f,mode==2?1.25f:.75f,.5f,1},{.125f,.25f,.75f,1}},{{.75f,-.75f,.5f,1},{.125f,.25f,.75f,1}}}};
        if(mode){vertices[1].color={.875f,.5f,.125f,1};vertices[2].color={.25f,.875f,.5f,1};}
        for(unsigned format=0;format<2;++format){std::vector<Color> baseline;RgbaImage baselineBytes;
            for(unsigned repeat=0;repeat<3;++repeat){std::vector<Color> a,b;RgbaImage aa,bb;
                CHECK(renderer.Shared(vertices,format,a,b,aa,bb));CHECK(a==b);if(!format)CHECK(PixelDifferences(aa,bb)==0);
                CHECK(a[40*64+16][0]<1);if(!mode && format)CHECK(a[40*64+16]==vertices[0].color);
                if(!repeat){baseline=a;baselineBytes=aa;}else{CHECK(a==baseline);if(!format)CHECK(aa.pixels==baselineBytes.pixels);}
                ++comparisons;
            }
        }
    }
    std::printf("sharedColorSmoke cases=3 formats=2 repeats=3 comparisons=%u sameInput=EXACT floatAndByte=EXACT\n",comparisons);return 0;
}

inline int AccessoryColorControls(HWND window,const char* archivePath,const char* referencePath,const char* outputPath) {
    using namespace accessory_color_diagnostic;
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    D3D9ReplaySnapshot source;CHECK(ReadUntexturedReduction(std::filesystem::path(archivePath)/"history_replay.reduction.draw2.state",source));
    CHECK(source.count==232 && source.start==6 && source.stride==32 && source.fvf==274 && source.base==0 && source.offset==0 && source.indexFormat==D3DFMT_INDEX16);
    unsigned x=0,y=0,w=0,h=0;std::ifstream trace(std::filesystem::path(referencePath)/"history_replay.dx9");std::string line;
    while(std::getline(trace,line))if(std::sscanf(line.c_str(),"PORTABLE_REGION x=%u y=%u width=%u height=%u",&x,&y,&w,&h)==4)break;
    CHECK(w && h);source.viewport={x,y,w,h,0,1};const unsigned width=x+w,height=y+h;
    // Deliberately remove visibility/history operations. Alpha is one, material
    // specular RGB is zero, and all enabled lights are directional: lighting is
    // independent of object position. Constant-normal patches below rely on this.
    CHECK(source.material.Specular.r==0 && source.material.Specular.g==0 && source.material.Specular.b==0 && source.material.Diffuse.a==1);
    for(const auto& l:source.lights)CHECK(!l.enabled || l.value.Type==D3DLIGHT_DIRECTIONAL);
    for(auto& state:source.renderStates)if(state.key==D3DRS_ZENABLE || state.key==D3DRS_ZWRITEENABLE || state.key==D3DRS_ALPHABLENDENABLE ||
        state.key==D3DRS_ALPHATESTENABLE || state.key==D3DRS_STENCILENABLE)state.value=FALSE;
    for(auto& state:source.renderStates)if(state.key==D3DRS_CULLMODE)state.value=D3DCULL_NONE;
    source.start+=197*3;source.count=1;
    std::vector<Color> final,raw,colors;CHECK(CaptureDepthVertexShader(source,final,&raw,true,3,&colors));
    std::array<unsigned,3> indices{};std::array<Vertex,3> vertices{};
    std::ofstream vertexLog(directory/"vertices.csv");vertexLog<<"vertex,sourceIndex,k,rawClipBits,finalClipBits,diffuseBits,diffuse\n"<<std::setprecision(17);
    for(unsigned n=0;n<3;++n){unsigned short index;std::memcpy(&index,source.indexBytes.data()+(source.start+n)*2,2);indices[n]=index;
        CHECK(index<raw.size());vertices[n]={raw[index],colors[index]};for(unsigned k=0;k<4;++k)vertexLog<<n<<","<<index<<","<<k<<","<<Bits(raw[index][k])<<","<<Bits(final[index][k])<<","<<Bits(colors[index][k])<<","<<colors[index][k]<<"\n";}
    Renderer renderer;CHECK(renderer.Initialize(window,width,height,source.viewport));
    // The diagnostic PS returns COLOR0 without textures. Guard its domain.
    for(const auto& info:source.textureInfo)CHECK(!info.present);
    std::vector<Color> nativeFloat,modelFloat,sharedNativeFloat,sharedReplayFloat;
    RgbaImage nativeBytes,modelBytes,sharedNativeBytes,sharedReplayBytes,unused;
    CHECK(NativeImage(window,{source},1,nativeBytes,nullptr,width,height,0xffffffff));
    CHECK(NativeImage(window,{source},1,unused,nullptr,width,height,0xffffffff,&nativeFloat));
    CHECK(renderer.Model(source,0,modelFloat,modelBytes));CHECK(renderer.Model(source,1,modelFloat,unused));
    CHECK(renderer.Shared(vertices,0,sharedNativeFloat,sharedReplayFloat,sharedNativeBytes,sharedReplayBytes));
    CHECK(renderer.Shared(vertices,1,sharedNativeFloat,sharedReplayFloat,unused,unused));
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11WCandidateDevice(desc,D3D11Driver::Hardware,3);CHECK(bundle);
    ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.clear={1,1,1,1};stream.events.push_back({1,ModelReplayOp::Clear});
    CHECK(AppendD3D9ReplaySnapshot(stream,source));stream.complete=true;RgbaImage adapter;
    CHECK(ReplayD3D11WCandidatePrefix(*bundle.device,stream,1,adapter));
    const auto preflight=PixelDifferences(adapter,modelBytes);
    if(preflight){for(std::size_t at=0;at<adapter.pixels.size()/4;++at)if(std::memcmp(adapter.pixels.data()+at*4,modelBytes.pixels.data()+at*4,4)){
        std::fprintf(stderr,"colorPreflight different=%u first=%u,%u adapter=%u,%u,%u,%u model=%u,%u,%u,%u\n",preflight,unsigned(at%width),unsigned(at/width),adapter.pixels[at*4],adapter.pixels[at*4+1],adapter.pixels[at*4+2],adapter.pixels[at*4+3],modelBytes.pixels[at*4],modelBytes.pixels[at*4+1],modelBytes.pixels[at*4+2],modelBytes.pixels[at*4+3]);break;}}
    CHECK(!preflight);
    // Shared input must preserve production's DX11 color and center arithmetic.
    CHECK(PixelDifferences(modelBytes,sharedReplayBytes)==0 && modelFloat==sharedReplayFloat);
    auto save=[&](const char* name,const void* data,std::size_t size){std::ofstream file(directory/name,std::ios::binary);file.write(static_cast<const char*>(data),size);return bool(file);};
    CHECK(save("native.rgba",nativeBytes.pixels.data(),nativeBytes.pixels.size()));CHECK(save("model.rgba",modelBytes.pixels.data(),modelBytes.pixels.size()));
    CHECK(save("native.rgba32f",nativeFloat.data(),nativeFloat.size()*16));CHECK(save("model.rgba32f",modelFloat.data(),modelFloat.size()*16));
    CHECK(save("shared-native.rgba32f",sharedNativeFloat.data(),sharedNativeFloat.size()*16));
    CHECK(save("shared-native.rgba",sharedNativeBytes.pixels.data(),sharedNativeBytes.pixels.size()));
    std::ofstream samples(directory/"samples.csv");samples<<"kind,x,y,k,nativeByte,modelByte,sharedNativeByte,sharedReplayByte,nativeBits,modelBits,sharedNativeBits,sharedReplayBits,native,model,sharedNative,sharedReplay\n"<<std::setprecision(17);
    // Preselected x86 residual and nearby interior controls. x64 uses the
    // projected interior at the same triangle barycentric location.
    const unsigned px=w==670?430:x+static_cast<unsigned>((430.-274.)*w/670.);
    const unsigned py=w==670?234:y+static_cast<unsigned>((234.-25.)*h/503.);
    unsigned covered=0,floatDifferent=0,sharedFloatDifferent=0;
    for(std::size_t at=0;at<nativeFloat.size();++at)if(nativeBytes.pixels[at*4]!=255){++covered;
        floatDifferent+=nativeFloat[at]!=modelFloat[at];sharedFloatDifferent+=sharedNativeFloat[at]!=sharedReplayFloat[at];}
    for(int dy=-2;dy<=2;++dy)for(int dx=-2;dx<=2;++dx){const unsigned sx=px+dx,sy=py+dy;const auto at=std::size_t(sy)*width+sx;
        CHECK(sx<width && sy<height);for(unsigned k=0;k<4;++k)samples<<"original,"<<sx<<","<<sy<<","<<k<<","<<unsigned(nativeBytes.pixels[at*4+k])<<","<<unsigned(modelBytes.pixels[at*4+k])<<","<<unsigned(sharedNativeBytes.pixels[at*4+k])<<","<<unsigned(sharedReplayBytes.pixels[at*4+k])<<","<<Bits(nativeFloat[at][k])<<","<<Bits(modelFloat[at][k])<<","<<Bits(sharedNativeFloat[at][k])<<","<<Bits(sharedReplayFloat[at][k])<<","<<nativeFloat[at][k]<<","<<modelFloat[at][k]<<","<<sharedNativeFloat[at][k]<<","<<sharedReplayFloat[at][k]<<"\n";}
    std::ofstream constants(directory/"constant_normals.csv");constants<<"vertex,k,nativeBits,shaderVertexBits,native,nativeByte\n"<<std::setprecision(17);
    std::array<Color,3> nativeColors{};
    for(unsigned n=0;n<3;++n){auto patch=source;patch.start=0;patch.vertices=3;patch.minimum=0;patch.indexBytes={0,0,1,0,2,0};patch.vertexBytes.resize(96);
        // Constant W, no clipping; preserve world/view normal transformation
        // and directional lighting. Projection does not enter the color formula.
        const float positions[][3]={{-6,-6,0},{-6,6,0},{6,-6,0}};
        patch.projection={};patch.projection._11=patch.projection._22=.01f;patch.projection._43=.5f;patch.projection._44=1;
        for(unsigned v=0;v<3;++v){std::memcpy(patch.vertexBytes.data()+v*32,source.vertexBytes.data()+indices[v]*32,32);
            std::memcpy(patch.vertexBytes.data()+v*32,positions[v],12);
            std::memcpy(patch.vertexBytes.data()+v*32+12,source.vertexBytes.data()+indices[n]*32+12,12);}
        std::vector<Color> values;RgbaImage bytes;CHECK(NativeImage(window,{patch},1,bytes,nullptr,width,height,0xffffffff));
        CHECK(NativeImage(window,{patch},1,unused,nullptr,width,height,0xffffffff,&values));
        const auto at=std::size_t(y+h*2/3)*width+x+w/3;CHECK(bytes.pixels[at*4]!=255);nativeColors[n]=values[at];
        unsigned nonconstant=0;for(std::size_t i=0;i<values.size();++i)if(bytes.pixels[i*4]!=255 && values[i]!=nativeColors[n])++nonconstant;
        std::printf("constantNormal vertex=%u nonconstantPixels=%u\n",n,nonconstant);CHECK(!nonconstant);
        for(unsigned k=0;k<4;++k)constants<<n<<","<<k<<","<<Bits(nativeColors[n][k])<<","<<Bits(vertices[n].color[k])<<","<<nativeColors[n][k]<<","<<unsigned(bytes.pixels[at*4+k])<<"\n";
    }
    auto nativeColorVertices=vertices;for(unsigned n=0;n<3;++n)nativeColorVertices[n].color=nativeColors[n];
    std::vector<Color> n,r;RgbaImage nb,rb;
    CHECK(renderer.Shared(nativeColorVertices,0,n,r,nb,rb));const auto nativeColorsByteDiff=PixelDifferences(nb,rb);
    CHECK(PixelDifferences(nativeBytes,nb)==0 && PixelDifferences(nativeBytes,rb)==0);
    CHECK(renderer.Shared(nativeColorVertices,1,n,r,unused,unused));
    CHECK(n==nativeFloat && r==nativeFloat);
    CHECK(save("native-colors-dx9.rgba32f",n.data(),n.size()*16));CHECK(save("native-colors-dx11.rgba32f",r.data(),r.size()*16));
    CHECK(save("native-colors-dx9.rgba",nb.pixels.data(),nb.pixels.size()));CHECK(save("native-colors-dx11.rgba",rb.pixels.data(),rb.pixels.size()));
    for(unsigned repeat=0;repeat<3;++repeat){std::vector<Color> a,b;RgbaImage aa,bb;
        CHECK(NativeImage(window,{source},1,aa,nullptr,width,height,0xffffffff));CHECK(aa.pixels==nativeBytes.pixels);
        CHECK(NativeImage(window,{source},1,unused,nullptr,width,height,0xffffffff,&a));CHECK(a==nativeFloat);
        CHECK(renderer.Model(source,0,a,aa));CHECK(aa.pixels==modelBytes.pixels);
        CHECK(renderer.Model(source,1,a,unused));CHECK(a==modelFloat);
        CHECK(renderer.Shared(vertices,0,a,b,aa,bb));CHECK(aa.pixels==sharedNativeBytes.pixels && bb.pixels==sharedReplayBytes.pixels);
        CHECK(renderer.Shared(vertices,1,a,b,unused,unused));CHECK(a==sharedNativeFloat && b==sharedReplayFloat);}
    CHECK(bundle.swapchain->Retire());
    std::printf("accessoryColor triangle=197 covered=%u nativeVsAdapterPixels=%u sharedColorBytePixels=%u nativeVsModelFloatPixels=%u sharedColorFloatPixels=%u nativeMeasuredColorsBytePixels=%u sharedModelPreflight=EXACT repeat=EXACT\n",
        covered,PixelDifferences(nativeBytes,modelBytes),PixelDifferences(sharedNativeBytes,sharedReplayBytes),floatDifferent,sharedFloatDifferent,nativeColorsByteDiff);
    {std::ofstream manifest(directory/"manifest.json");manifest<<"{\"width\":"<<width<<",\"height\":"<<height<<",\"viewport\":["<<x<<","<<y<<","<<w<<","<<h<<"],\"triangle\":197,\"probe\":["<<px<<","<<py<<"],\"samples\":1,\"diagnosticPolicy\":3,\"repeatCount\":3,\"adapterPreflight\":true,\"sharedModelPreflight\":true,\"nativeColorSubstitution\":true,\"repeatExact\":true}\n";CHECK(manifest);}
    return samples && constants && vertexLog?0:1; // Differences are diagnostic, never acceptance.
}
