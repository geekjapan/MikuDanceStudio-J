#pragma once

// Test-local programmable passthrough. Both backends consume the same float4
// clip bytes; this is not a capture of DX9 fixed-function vertex outputs.
class SharedClipDepthRenderer {
    using Clip=std::array<float,4>;
    unsigned width=64,height=64;D3DVIEWPORT9 area{0,0,64,64,0,1};
    bool centerInViewport=false;
    D3D11_VIEWPORT Viewport11() const {const float shift=centerInViewport?.5f:0.f;
        return {float(area.X)+shift,float(area.Y)+shift,float(area.Width),float(area.Height),area.MinZ,area.MaxZ};}
    ComPtr<IDirect3D9> api9;ComPtr<IDirect3DDevice9> device9;
    ComPtr<IDirect3DVertexShader9> vs9,dp9,ordered9,reverse9,paired9;ComPtr<IDirect3DPixelShader9> ps9;
    ComPtr<IDirect3DVertexDeclaration9> layout9;ComPtr<IDirect3DSurface9> target9,cpu9;
    std::array<ComPtr<IDirect3DVertexShader9>,4> hybrid9;ComPtr<IDirect3DVertexDeclaration9> hybridLayout9;
    ComPtr<ID3D11Device> device11;ComPtr<ID3D11DeviceContext> context11;
    ComPtr<ID3D11VertexShader> vs11;ComPtr<ID3D11PixelShader> ps11;
    ComPtr<ID3D11InputLayout> layout11;ComPtr<ID3D11Buffer> vertices11,color11,viewportConstants11;
    ComPtr<ID3D11Texture2D> target11,depth11,cpu11;ComPtr<ID3D11RenderTargetView> rtv11;ComPtr<ID3D11DepthStencilView> dsv11;
    ComPtr<ID3D11RasterizerState> raster11;ComPtr<ID3D11DepthStencilState> write11,less11,equal11;
public:
    bool Initialize(HWND window,unsigned targetWidth=64,unsigned targetHeight=64,const D3DVIEWPORT9* viewport=nullptr,bool viewportCenter=false) {
        if(!targetWidth || !targetHeight || targetWidth>4096 || targetHeight>4096)return false;
        width=targetWidth;height=targetHeight;area=viewport?*viewport:D3DVIEWPORT9{0,0,width,height,0,1};centerInViewport=viewportCenter;
        if(!area.Width || !area.Height || area.X+area.Width>width || area.Y+area.Height>height || area.MinZ!=0 || area.MaxZ!=1)return false;
        api9.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api9)return false;
        D3DPRESENT_PARAMETERS pp{};pp.BackBufferWidth=width;pp.BackBufferHeight=height;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.BackBufferCount=1;
        pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.hDeviceWindow=window;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        if(FAILED(api9->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device9)))return false;
        D3D_FEATURE_LEVEL level;
        if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device11,&level,&context11)) || level<D3D_FEATURE_LEVEL_11_0)return false;
        auto compile=[](const char* source,const char* profile,ComPtr<ID3DBlob>& blob){ComPtr<ID3DBlob> error;return SUCCEEDED(D3DCompile(source,std::strlen(source),nullptr,nullptr,nullptr,"main",profile,D3DCOMPILE_IEEE_STRICTNESS,0,&blob,&error));};
        ComPtr<ID3DBlob> vertex9,pixel9,vertex11,pixel11;
        // Match production's dynamic viewport division: folding 1/width into
        // an immediate can change the center-correction output bits.
        const char* clipShader="cbuffer Viewport:register(b0){float4 parameters;}float4 main(float4 p:POSITION):SV_POSITION{p.xy+=float2(1/parameters.y,-1/parameters.z)*p.w;return p;}";
        if(!compile("float4 main(float4 p:POSITION):POSITION{return p;}","vs_3_0",vertex9) ||
           !compile("float4 c:register(c0); float4 main():COLOR{return c;}","ps_3_0",pixel9) ||
           !compile(centerInViewport?"float4 main(float4 p:POSITION):SV_POSITION{return p;}":clipShader,"vs_5_0",vertex11) ||
           !compile("cbuffer C:register(b0){float4 c;}float4 main():SV_TARGET{return c;}","ps_5_0",pixel11))return false;
        const D3DVERTEXELEMENT9 element9[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},D3DDECL_END()};
        if(FAILED(device9->CreateVertexShader(static_cast<DWORD*>(vertex9->GetBufferPointer()),&vs9)) || FAILED(device9->CreatePixelShader(static_cast<DWORD*>(pixel9->GetBufferPointer()),&ps9)) || FAILED(device9->CreateVertexDeclaration(element9,&layout9)) ||
           FAILED(device9->GetRenderTarget(0,&target9)) || FAILED(device9->CreateOffscreenPlainSurface(width,height,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&cpu9,nullptr)))return false;
        for(unsigned rule=0;rule<4;++rule){ComPtr<ID3DBlob> shader,listing;
            const char* sources[]={"float4 a:register(c0),b:register(c1),c:register(c2),d:register(c3);float4 main(float4 p:POSITION):POSITION{return float4(dot(p,a),dot(p,b),dot(p,c),dot(p,d));}",
                "row_major float4x4 m:register(c0);float4 main(float4 p:POSITION):POSITION{float4 a=p.x*m[0];float4 b=p.y*m[1];float4 c=p.z*m[2];float4 d=p.w*m[3];float4 ab=a+b;float4 abc=ab+c;return abc+d;}",
                "row_major float4x4 m:register(c0);float4 main(float4 p:POSITION):POSITION{float4 a=p.x*m[0];float4 b=p.y*m[1];float4 c=p.z*m[2];float4 d=p.w*m[3];float4 dc=d+c;float4 dcb=dc+b;return dcb+a;}",
                "row_major float4x4 m:register(c0);float4 main(float4 p:POSITION):POSITION{float4 a=p.x*m[0];float4 b=p.y*m[1];float4 c=p.z*m[2];float4 d=p.w*m[3];return (a+b)+(c+d);}"};
            if(!compile(sources[rule],"vs_3_0",shader) || FAILED(device9->CreateVertexShader(static_cast<DWORD*>(shader->GetBufferPointer()),rule==0?&dp9:rule==1?&ordered9:rule==2?&reverse9:&paired9)))return false;
            if(FAILED(D3DDisassemble(shader->GetBufferPointer(),shader->GetBufferSize(),0,nullptr,&listing)))return false;
            const std::string instructions=static_cast<const char*>(listing->GetBufferPointer());
            auto count=[&](const std::string& op){unsigned total=0;std::size_t at=0;while((at=instructions.find(op,at))!=std::string::npos){++total;at+=op.size();}return total;};
            if(rule==0?count("dp4 ")!=4:(count("mul ")!=4 || count("add ")!=3 || count("mad ")!=0))return false;
            std::printf("nativeDiagnosticShader rule=%u\n%s\n",rule,static_cast<const char*>(listing->GetBufferPointer()));}
        const D3DVERTEXELEMENT9 hybridElements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_TEXCOORD,0},D3DDECL_END()};
        if(FAILED(device9->CreateVertexDeclaration(hybridElements,&hybridLayout9)))return false;
        const char* hybridOutputs[]={"float4(q.xy,dot(p,c),q.w)","float4(q.xyz,dot(p,d))","float4(q.xy,dot(p,c),dot(p,d))","float4(dot(p,a),dot(p,b),q.zw)"};
        for(unsigned n=0;n<4;++n){const std::string source=std::string("float4 a:register(c0),b:register(c1),c:register(c2),d:register(c3);float4 main(float4 p:POSITION,float4 q:TEXCOORD0):POSITION{return ")+hybridOutputs[n]+";}";ComPtr<ID3DBlob> code,listing;
            if(!compile(source.c_str(),"vs_3_0",code) || FAILED(device9->CreateVertexShader(static_cast<DWORD*>(code->GetBufferPointer()),&hybrid9[n])) || FAILED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)))return false;
            const std::string instructions=static_cast<const char*>(listing->GetBufferPointer());unsigned dots=0;std::size_t at=0;while((at=instructions.find("dp4 ",at))!=std::string::npos){++dots;at+=4;}if(dots!=(n<2?1u:2u))return false;
            std::printf("nativeHybridShader components=%u\n%s\n",n,static_cast<const char*>(listing->GetBufferPointer()));}
        const D3D11_INPUT_ELEMENT_DESC element11={"POSITION",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0};
        if(FAILED(device11->CreateVertexShader(vertex11->GetBufferPointer(),vertex11->GetBufferSize(),nullptr,&vs11)) || FAILED(device11->CreatePixelShader(pixel11->GetBufferPointer(),pixel11->GetBufferSize(),nullptr,&ps11)) ||
           FAILED(device11->CreateInputLayout(&element11,1,vertex11->GetBufferPointer(),vertex11->GetBufferSize(),&layout11)))return false;
        D3D11_BUFFER_DESC buffer{};buffer.ByteWidth=6*16;buffer.BindFlags=D3D11_BIND_VERTEX_BUFFER;
        if(FAILED(device11->CreateBuffer(&buffer,nullptr,&vertices11)))return false;buffer.ByteWidth=16;buffer.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        if(FAILED(device11->CreateBuffer(&buffer,nullptr,&color11)))return false;
        const Clip viewportInputs{0,float(area.Width),float(area.Height),0};const D3D11_SUBRESOURCE_DATA initialViewport{viewportInputs.data(),0,0};
        if(FAILED(device11->CreateBuffer(&buffer,&initialViewport,&viewportConstants11)))return false;
        D3D11_TEXTURE2D_DESC texture{};texture.Width=width;texture.Height=height;texture.MipLevels=texture.ArraySize=1;texture.SampleDesc.Count=1;texture.Format=DXGI_FORMAT_R8G8B8A8_UNORM;texture.BindFlags=D3D11_BIND_RENDER_TARGET;
        if(FAILED(device11->CreateTexture2D(&texture,nullptr,&target11)) || FAILED(device11->CreateRenderTargetView(target11.Get(),nullptr,&rtv11)))return false;
        texture.Format=DXGI_FORMAT_D24_UNORM_S8_UINT;texture.BindFlags=D3D11_BIND_DEPTH_STENCIL;
        if(FAILED(device11->CreateTexture2D(&texture,nullptr,&depth11)) || FAILED(device11->CreateDepthStencilView(depth11.Get(),nullptr,&dsv11)))return false;
        texture.Format=DXGI_FORMAT_R8G8B8A8_UNORM;texture.BindFlags=0;texture.Usage=D3D11_USAGE_STAGING;texture.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        if(FAILED(device11->CreateTexture2D(&texture,nullptr,&cpu11)))return false;
        D3D11_RASTERIZER_DESC raster{};raster.FillMode=D3D11_FILL_SOLID;raster.CullMode=D3D11_CULL_NONE;raster.DepthClipEnable=TRUE;
        if(FAILED(device11->CreateRasterizerState(&raster,&raster11)))return false;
        D3D11_DEPTH_STENCIL_DESC depth{};depth.DepthEnable=TRUE;depth.DepthWriteMask=D3D11_DEPTH_WRITE_MASK_ALL;depth.DepthFunc=D3D11_COMPARISON_LESS_EQUAL;
        if(FAILED(device11->CreateDepthStencilState(&depth,&write11)))return false;
        depth.DepthWriteMask=D3D11_DEPTH_WRITE_MASK_ZERO;depth.DepthFunc=D3D11_COMPARISON_LESS;
        if(FAILED(device11->CreateDepthStencilState(&depth,&less11)))return false;depth.DepthFunc=D3D11_COMPARISON_EQUAL;
        if(FAILED(device11->CreateDepthStencilState(&depth,&equal11)))return false;
        return true;
    }
    bool Capture(const std::vector<Clip>& vertices,std::vector<Clip>& result) {
        if(vertices.empty() || vertices.size()>48)return false;ComPtr<ID3DBlob> code,error;
        const char* shader="struct O{float4 p:SV_POSITION;};[maxvertexcount(1)]void main(point O p[1],inout PointStream<O> o){o.Append(p[0]);}";
        if(FAILED(D3DCompile(shader,std::strlen(shader),nullptr,nullptr,nullptr,"main","gs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error))){if(error)std::fprintf(stderr,"sharedClipGS=%s\n",static_cast<const char*>(error->GetBufferPointer()));return false;}
        ComPtr<ID3D11GeometryShader> gs;const D3D11_SO_DECLARATION_ENTRY entry{0,"SV_POSITION",0,0,4,0};const UINT stride=16;
        if(FAILED(device11->CreateGeometryShaderWithStreamOutput(code->GetBufferPointer(),code->GetBufferSize(),&entry,1,&stride,1,D3D11_SO_NO_RASTERIZED_STREAM,nullptr,&gs)))return false;
        ComPtr<ID3D11Buffer> output,cpu;D3D11_BUFFER_DESC desc{};desc.ByteWidth=static_cast<UINT>(vertices.size()*16);desc.BindFlags=D3D11_BIND_STREAM_OUTPUT;
        if(FAILED(device11->CreateBuffer(&desc,nullptr,&output)))return false;desc.BindFlags=0;desc.Usage=D3D11_USAGE_STAGING;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        if(FAILED(device11->CreateBuffer(&desc,nullptr,&cpu)))return false;
        const UINT offset=0;auto* vb=vertices11.Get();auto* so=output.Get();
        context11->IASetInputLayout(layout11.Get());context11->IASetVertexBuffers(0,1,&vb,&stride,&offset);context11->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_POINTLIST);context11->VSSetShader(vs11.Get(),nullptr,0);
        auto* viewportBuffer=viewportConstants11.Get();context11->VSSetConstantBuffers(0,1,&viewportBuffer);
        context11->GSSetShader(gs.Get(),nullptr,0);context11->SOSetTargets(1,&so,&offset);
        for(std::size_t at=0;at<vertices.size();at+=6){std::array<Clip,6> padded{};const auto count=(std::min)(std::size_t(6),vertices.size()-at);
            std::copy_n(vertices.begin()+at,count,padded.begin());context11->UpdateSubresource(vertices11.Get(),0,nullptr,padded.data(),0,0);context11->Draw(static_cast<UINT>(count),0);}
        context11->SOSetTargets(0,nullptr,nullptr);context11->GSSetShader(nullptr,nullptr,0);
        context11->CopyResource(cpu.Get(),output.Get());D3D11_MAPPED_SUBRESOURCE mapped{};
        if(FAILED(context11->Map(cpu.Get(),0,D3D11_MAP_READ,0,&mapped)))return false;result.resize(vertices.size());std::memcpy(result.data(),mapped.pData,vertices.size()*16);context11->Unmap(cpu.Get(),0);return true;
    }
    bool Render(const std::vector<Clip>& vertices,float reference,bool equal,RgbaImage& native,RgbaImage& replay,const std::vector<Clip>* nativeObject=nullptr,const depth_diagnostic::Matrix* matrix=nullptr,unsigned arithmetic=0) {
        if(vertices.empty() || vertices.size()%3 || vertices.size()>48 || (matrix && vertices.size()!=3))return false;const Clip red{1,0,0,1},green{0,1,0,1};const Clip ruler[]={{-1,-1,reference,1},{-1,1,reference,1},{1,-1,reference,1},{1,-1,reference,1},{-1,1,reference,1},{1,1,reference,1}};
        const D3DVIEWPORT9 viewport=area;
        if(FAILED(device9->SetViewport(&viewport)) || FAILED(device9->SetVertexDeclaration(layout9.Get())) || FAILED(device9->SetVertexShader(vs9.Get())) || FAILED(device9->SetPixelShader(ps9.Get())))return false;
        for(auto state:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,TRUE},{D3DRS_ZWRITEENABLE,TRUE},{D3DRS_ZFUNC,D3DCMP_LESSEQUAL},{D3DRS_CULLMODE,D3DCULL_NONE},{D3DRS_ALPHABLENDENABLE,FALSE},{D3DRS_ALPHATESTENABLE,FALSE},{D3DRS_STENCILENABLE,FALSE},{D3DRS_SCISSORTESTENABLE,FALSE},{D3DRS_SRGBWRITEENABLE,FALSE},{D3DRS_COLORWRITEENABLE,15}})
            if(FAILED(device9->SetRenderState(state.first,state.second)))return false;
        std::array<std::array<float,8>,3> hybridVertices{};
        if(matrix){depth_diagnostic::Matrix constants=*matrix;if(!arithmetic || arithmetic>=4)for(unsigned row=0;row<4;++row)for(unsigned col=0;col<4;++col)constants[row*4+col]=(*matrix)[col*4+row];
            if(!nativeObject || nativeObject->size()!=3 || arithmetic>7 || FAILED(device9->SetVertexShader(arithmetic>=4?hybrid9[arithmetic-4].Get():arithmetic==0?dp9.Get():arithmetic==1?ordered9.Get():arithmetic==2?reverse9.Get():paired9.Get())) || FAILED(device9->SetVertexShaderConstantF(0,constants.data(),4)))return false;
            if(arithmetic>=4){if(FAILED(device9->SetVertexDeclaration(hybridLayout9.Get())))return false;for(unsigned n=0;n<3;++n){std::memcpy(hybridVertices[n].data(),(*nativeObject)[n].data(),16);std::memcpy(hybridVertices[n].data()+4,vertices[n].data(),16);}}}
        const void* nativeVertices=matrix?(arithmetic>=4?static_cast<const void*>(hybridVertices.data()):static_cast<const void*>(nativeObject->data())):static_cast<const void*>(vertices.data());
        if(FAILED(device9->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xff000000,1,0)) || FAILED(device9->BeginScene()) || FAILED(device9->SetPixelShaderConstantF(0,red.data(),1)) || FAILED(device9->DrawPrimitiveUP(D3DPT_TRIANGLELIST,static_cast<UINT>(vertices.size()/3),nativeVertices,matrix && arithmetic>=4?32:16)) || FAILED(device9->SetVertexShader(vs9.Get())) || FAILED(device9->SetVertexDeclaration(layout9.Get())) ||
           FAILED(device9->SetRenderState(D3DRS_ZWRITEENABLE,FALSE)) || FAILED(device9->SetRenderState(D3DRS_ZFUNC,equal?D3DCMP_EQUAL:D3DCMP_LESS)) || FAILED(device9->SetPixelShaderConstantF(0,green.data(),1)) || FAILED(device9->DrawPrimitiveUP(D3DPT_TRIANGLELIST,2,ruler,16)) || FAILED(device9->EndScene()) || FAILED(device9->GetRenderTargetData(target9.Get(),cpu9.Get())))return false;
        D3DLOCKED_RECT lock{};if(FAILED(cpu9->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;native={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x){const auto* src=static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;auto* dst=native.pixels.data()+(std::size_t(y)*width+x)*4;dst[0]=src[2];dst[1]=src[1];dst[2]=src[0];dst[3]=src[3];}if(FAILED(cpu9->UnlockRect()))return false;
        const auto viewport11=Viewport11();auto* target=rtv11.Get();auto* vb=vertices11.Get();auto* cb=color11.Get();const UINT stride=16,offset=0;const float black[]={0,0,0,1};
        context11->OMSetRenderTargets(1,&target,dsv11.Get());context11->ClearRenderTargetView(target,black);context11->ClearDepthStencilView(dsv11.Get(),D3D11_CLEAR_DEPTH|D3D11_CLEAR_STENCIL,1,0);
        context11->RSSetViewports(1,&viewport11);context11->RSSetState(raster11.Get());context11->OMSetBlendState(nullptr,nullptr,~0u);context11->OMSetDepthStencilState(write11.Get(),0);
        context11->IASetInputLayout(layout11.Get());context11->IASetVertexBuffers(0,1,&vb,&stride,&offset);context11->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context11->VSSetShader(vs11.Get(),nullptr,0);context11->GSSetShader(nullptr,nullptr,0);context11->PSSetShader(ps11.Get(),nullptr,0);context11->PSSetConstantBuffers(0,1,&cb);
        auto* viewportBuffer=viewportConstants11.Get();context11->VSSetConstantBuffers(0,1,&viewportBuffer);
        // Pad to the full buffer size: UpdateSubresource reads ByteWidth bytes.
        context11->UpdateSubresource(color11.Get(),0,nullptr,red.data(),0,0);
        for(std::size_t at=0;at<vertices.size();at+=6){std::array<Clip,6> padded{};const auto count=(std::min)(std::size_t(6),vertices.size()-at);
            std::copy_n(vertices.begin()+at,count,padded.begin());context11->UpdateSubresource(vertices11.Get(),0,nullptr,padded.data(),0,0);context11->Draw(static_cast<UINT>(count),0);}
        context11->OMSetDepthStencilState(equal?equal11.Get():less11.Get(),0);context11->UpdateSubresource(vertices11.Get(),0,nullptr,ruler,0,0);context11->UpdateSubresource(color11.Get(),0,nullptr,green.data(),0,0);context11->Draw(6,0);
        context11->CopyResource(cpu11.Get(),target11.Get());D3D11_MAPPED_SUBRESOURCE mapped{};if(FAILED(context11->Map(cpu11.Get(),0,D3D11_MAP_READ,0,&mapped)))return false;replay={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
        for(unsigned y=0;y<height;++y)std::memcpy(replay.pixels.data()+std::size_t(y)*width*4,static_cast<const unsigned char*>(mapped.pData)+y*mapped.RowPitch,std::size_t(width)*4);context11->Unmap(cpu11.Get(),0);return true;
    }
    // Same clip endpoints on both APIs, no depth/stencil or color interpolation.
    // This tests line clipping/coverage, not native fixed-function arithmetic.
    bool RenderLine(const std::vector<Clip>& vertices,RgbaImage& native,RgbaImage& replay) {
        if(vertices.size()!=2)return false;const Clip red{1,0,0,1};
        if(FAILED(device9->SetViewport(&area)) || FAILED(device9->SetVertexDeclaration(layout9.Get())) ||
           FAILED(device9->SetVertexShader(vs9.Get())) || FAILED(device9->SetPixelShader(ps9.Get())))return false;
        for(auto state:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,FALSE},{D3DRS_ZWRITEENABLE,FALSE},
            {D3DRS_ALPHABLENDENABLE,FALSE},{D3DRS_ALPHATESTENABLE,FALSE},{D3DRS_STENCILENABLE,FALSE},
            {D3DRS_SCISSORTESTENABLE,FALSE},{D3DRS_SRGBWRITEENABLE,FALSE},{D3DRS_COLORWRITEENABLE,15}})
            if(FAILED(device9->SetRenderState(state.first,state.second)))return false;
        if(FAILED(device9->Clear(0,nullptr,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER|D3DCLEAR_STENCIL,0xffffffff,1,0)) ||
           FAILED(device9->BeginScene()) || FAILED(device9->SetPixelShaderConstantF(0,red.data(),1)) ||
           FAILED(device9->DrawPrimitiveUP(D3DPT_LINELIST,1,vertices.data(),16)) || FAILED(device9->EndScene()) ||
           FAILED(device9->GetRenderTargetData(target9.Get(),cpu9.Get())))return false;
        D3DLOCKED_RECT lock{};if(FAILED(cpu9->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
        native={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x){const auto* p=static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*4;
            auto* q=native.pixels.data()+(std::size_t(y)*width+x)*4;q[0]=p[2];q[1]=p[1];q[2]=p[0];q[3]=p[3];}
        if(FAILED(cpu9->UnlockRect()))return false;
        const auto view=Viewport11();
        D3D11_DEPTH_STENCIL_DESC disabled{};disabled.DepthEnable=FALSE;ComPtr<ID3D11DepthStencilState> state;
        if(FAILED(device11->CreateDepthStencilState(&disabled,&state)))return false;
        auto* target=rtv11.Get();auto* vb=vertices11.Get();auto* cb=color11.Get();auto* viewport=viewportConstants11.Get();
        const UINT stride=16,offset=0;const float white[]={1,1,1,1};
        context11->OMSetRenderTargets(1,&target,dsv11.Get());context11->ClearRenderTargetView(target,white);
        context11->OMSetDepthStencilState(state.Get(),0);context11->OMSetBlendState(nullptr,nullptr,~0u);
        context11->RSSetViewports(1,&view);context11->RSSetState(raster11.Get());
        context11->IASetInputLayout(layout11.Get());context11->IASetVertexBuffers(0,1,&vb,&stride,&offset);
        context11->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_LINELIST);context11->VSSetShader(vs11.Get(),nullptr,0);
        context11->VSSetConstantBuffers(0,1,&viewport);context11->GSSetShader(nullptr,nullptr,0);
        context11->PSSetShader(ps11.Get(),nullptr,0);context11->PSSetConstantBuffers(0,1,&cb);
        std::array<Clip,6> padded{};std::copy(vertices.begin(),vertices.end(),padded.begin());
        context11->UpdateSubresource(vertices11.Get(),0,nullptr,padded.data(),0,0);context11->UpdateSubresource(cb,0,nullptr,red.data(),0,0);context11->Draw(2,0);
        context11->CopyResource(cpu11.Get(),target11.Get());D3D11_MAPPED_SUBRESOURCE mapped{};
        if(FAILED(context11->Map(cpu11.Get(),0,D3D11_MAP_READ,0,&mapped)))return false;
        replay={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
        for(unsigned y=0;y<height;++y)std::memcpy(replay.pixels.data()+std::size_t(y)*width*4,static_cast<const unsigned char*>(mapped.pData)+y*mapped.RowPitch,std::size_t(width)*4);
        context11->Unmap(cpu11.Get(),0);return true;
    }
    bool CheckViewport() const {UINT count=1;D3D11_VIEWPORT observed{};context11->RSGetViewports(&count,&observed);const auto expected=Viewport11();
        return count==1 && observed.TopLeftX==expected.TopLeftX && observed.TopLeftY==expected.TopLeftY && observed.Width==expected.Width && observed.Height==expected.Height && observed.MinDepth==expected.MinDepth && observed.MaxDepth==expected.MaxDepth;}
};
