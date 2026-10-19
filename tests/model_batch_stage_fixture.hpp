#pragma once
#include "../src/render/rhi_model_constants.hpp"
#include <map>
// Observe the unchanged measured VS and floating point PS stages. Native PS
// observations are labelled separately from untouched fixed-function output.
namespace model_batch_color {
using Color=std::array<float,4>;
inline bool Stage11(const D3D9ReplaySnapshot& source,unsigned width,unsigned height,const std::string& pixelText,
    bool floating,RgbaImage& bytes,std::vector<Color>& pixels,const std::array<float,4>& clearColor={1,1,1,1},float viewportOffset=.5f,
    const std::vector<Color>* diagnosticConstants=nullptr,const std::string* diagnosticVertexSource=nullptr) {
    ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.events.push_back({1,ModelReplayOp::Clear});
    if(!AppendD3D9ReplaySnapshot(stream,source))return false;const auto& draw=stream.events.back().draw;
    detail::ModelConstants constants;if(!detail::BuildModelConstants(draw.pipeline,*draw.pipeline.viewport,true,constants))return false;
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;D3D_FEATURE_LEVEL feature;
    if(FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,&feature,&context)))return false;
    const auto compile=[](const std::string& text,const char* profile,const D3D_SHADER_MACRO* macros,ComPtr<ID3DBlob>& code){ComPtr<ID3DBlob> error;
        // Reuse only test-local bytecode. Each observation still creates a
        // fresh device/shader, submits geometry and reads fresh GPU output.
        static std::map<std::string,ComPtr<ID3DBlob>> cache;
        const auto key=std::string(profile)+":"+(macros?"measured:":"pixel:")+text;
        const auto found=cache.find(key);if(found!=cache.end()){code=found->second;return true;}
        const auto hr=D3DCompile(text.data(),text.size(),nullptr,macros,nullptr,"main",profile,D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error);
        if(FAILED(hr) && error)std::fprintf(stderr,"model23 stages %s: %s\n",profile,static_cast<const char*>(error->GetBufferPointer()));
        if(SUCCEEDED(hr))cache.emplace(key,code);return SUCCEEDED(hr);};
    ComPtr<ID3DBlob> vcode,pcode;const D3D_SHADER_MACRO macros[]={{"MDS_MODEL_DX9_COMPATIBILITY","1"},{nullptr,nullptr}};
    const auto vertexText=diagnosticVertexSource?*diagnosticVertexSource:std::string(modelDx9CompatibilitySource)+modelVertexSource;
    if(!compile(vertexText,"vs_5_0",macros,vcode) || !compile(pixelText,"ps_5_0",nullptr,pcode))return false;
    ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11PixelShader> ps;ComPtr<ID3D11InputLayout> layout;
    const D3D11_INPUT_ELEMENT_DESC elements[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
    if(FAILED(device->CreateVertexShader(vcode->GetBufferPointer(),vcode->GetBufferSize(),nullptr,&vs)) ||
       FAILED(device->CreatePixelShader(pcode->GetBufferPointer(),pcode->GetBufferSize(),nullptr,&ps)) ||
       FAILED(device->CreateInputLayout(elements,3,vcode->GetBufferPointer(),vcode->GetBufferSize(),&layout)))return false;
    const auto buffer=[&](const void* data,UINT size,UINT bind,ComPtr<ID3D11Buffer>& out){D3D11_BUFFER_DESC desc{};desc.ByteWidth=size;desc.BindFlags=bind;D3D11_SUBRESOURCE_DATA initial{data,0,0};return SUCCEEDED(device->CreateBuffer(&desc,&initial,&out));};
    ComPtr<ID3D11Buffer> vb,ib,vc,extra,pc,diagnostic;
    if(!buffer(source.vertexBytes.data(),UINT(source.vertexBytes.size()),D3D11_BIND_VERTEX_BUFFER,vb) ||
       !buffer(source.indexBytes.data(),UINT(source.indexBytes.size()),D3D11_BIND_INDEX_BUFFER,ib) ||
       !buffer(&constants.vertex,sizeof(constants.vertex),D3D11_BIND_CONSTANT_BUFFER,vc) ||
       !buffer(&constants.compatibility,sizeof(constants.compatibility),D3D11_BIND_CONSTANT_BUFFER,extra) ||
       !buffer(&constants.pixel,sizeof(constants.pixel),D3D11_BIND_CONSTANT_BUFFER,pc))return false;
    if(diagnosticConstants && (diagnosticConstants->empty() ||
        !buffer(diagnosticConstants->data(),UINT(diagnosticConstants->size()*sizeof(Color)),D3D11_BIND_CONSTANT_BUFFER,diagnostic)))return false;
    for(unsigned stage=0;stage<3;++stage) {
        if(draw.pipeline.shader.layout.stages[stage].role==MaterialTextureRole::None)continue;
        const auto found=std::find_if(stream.resources.begin(),stream.resources.end(),[&](const auto& r){return r.key.id==draw.textures[stage].id;});
        if(found==stream.resources.end())return false;const auto& levels=found->texture.levels;std::vector<D3D11_SUBRESOURCE_DATA> data;
        for(const auto& level:levels)data.push_back({level.pixels.data(),level.width*4,0});
        D3D11_TEXTURE2D_DESC td{};td.Width=levels[0].width;td.Height=levels[0].height;td.MipLevels=UINT(levels.size());td.ArraySize=td.SampleDesc.Count=1;
        td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.Usage=D3D11_USAGE_IMMUTABLE;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        ComPtr<ID3D11Texture2D> texture;ComPtr<ID3D11ShaderResourceView> srv;
        if(FAILED(device->CreateTexture2D(&td,data.data(),&texture)) || FAILED(device->CreateShaderResourceView(texture.Get(),nullptr,&srv)))return false;
        auto* view=srv.Get();context->PSSetShaderResources(stage,1,&view);
        const auto& sampler=draw.pipeline.shader.samplers[stage];D3D11_SAMPLER_DESC sd{};
        sd.Filter=sampler.min==SamplerFilter::Anisotropic || sampler.mag==SamplerFilter::Anisotropic?D3D11_FILTER_ANISOTROPIC:
            sampler.min==SamplerFilter::Point && sampler.mag==SamplerFilter::Point?D3D11_FILTER_MIN_MAG_MIP_POINT:D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;
        sd.MaxAnisotropy=sampler.maxAnisotropy;sd.ComparisonFunc=D3D11_COMPARISON_NEVER;sd.MaxLOD=D3D11_FLOAT32_MAX;
        const auto address=[](SamplerAddress a){return a==SamplerAddress::Clamp?D3D11_TEXTURE_ADDRESS_CLAMP:D3D11_TEXTURE_ADDRESS_WRAP;};
        sd.AddressU=address(sampler.u);sd.AddressV=address(sampler.v);sd.AddressW=D3D11_TEXTURE_ADDRESS_WRAP;
        ComPtr<ID3D11SamplerState> state;if(FAILED(device->CreateSamplerState(&sd,&state)))return false;auto* native=state.Get();context->PSSetSamplers(stage,1,&native);
    }
    D3D11_TEXTURE2D_DESC td{};td.Width=width;td.Height=height;td.MipLevels=td.ArraySize=td.SampleDesc.Count=1;
    td.Format=floating?DXGI_FORMAT_R32G32B32A32_FLOAT:DXGI_FORMAT_R8G8B8A8_UNORM;td.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> target,cpu;ComPtr<ID3D11RenderTargetView> view;
    if(FAILED(device->CreateTexture2D(&td,nullptr,&target)) || FAILED(device->CreateRenderTargetView(target.Get(),nullptr,&view)))return false;
    td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;if(FAILED(device->CreateTexture2D(&td,nullptr,&cpu)))return false;
    D3D11_RASTERIZER_DESC rs{};rs.FillMode=D3D11_FILL_SOLID;rs.CullMode=D3D11_CULL_NONE;rs.DepthClipEnable=TRUE;
    ComPtr<ID3D11RasterizerState> raster;if(FAILED(device->CreateRasterizerState(&rs,&raster)))return false;
    D3D11_DEPTH_STENCIL_DESC ds{};ds.DepthFunc=D3D11_COMPARISON_ALWAYS;ComPtr<ID3D11DepthStencilState> depth;if(FAILED(device->CreateDepthStencilState(&ds,&depth)))return false;
    const auto& r=source.viewport;D3D11_VIEWPORT viewport{float(r.X)+viewportOffset,float(r.Y)+viewportOffset,float(r.Width),float(r.Height),r.MinZ,r.MaxZ};
    auto* rtv=view.Get();context->OMSetRenderTargets(1,&rtv,nullptr);context->ClearRenderTargetView(rtv,clearColor.data());
    context->RSSetState(raster.Get());context->RSSetViewports(1,&viewport);context->OMSetDepthStencilState(depth.Get(),0);
    UINT stride=source.stride,offset=source.offset;auto* vertex=vb.Get();context->IASetInputLayout(layout.Get());context->IASetVertexBuffers(0,1,&vertex,&stride,&offset);
    context->IASetIndexBuffer(ib.Get(),source.indexFormat==D3DFMT_INDEX16?DXGI_FORMAT_R16_UINT:DXGI_FORMAT_R32_UINT,0);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(vs.Get(),nullptr,0);context->PSSetShader(ps.Get(),nullptr,0);ID3D11Buffer* uniforms[]={vc.Get(),extra.Get()};context->VSSetConstantBuffers(0,2,uniforms);
    auto* cascade=pc.Get();context->PSSetConstantBuffers(0,1,&cascade);
    if(diagnosticConstants){auto* values=diagnostic.Get();context->PSSetConstantBuffers(1,1,&values);}
    context->DrawIndexed(source.count*3,source.start,source.base);
    context->CopyResource(cpu.Get(),target.Get());D3D11_MAPPED_SUBRESOURCE map{};if(FAILED(context->Map(cpu.Get(),0,D3D11_MAP_READ,0,&map)))return false;
    pixels.resize(std::size_t(width)*height);if(!floating)bytes={width,height,std::vector<unsigned char>(std::size_t(width)*height*4)};
    for(unsigned y=0;y<height;++y){const auto* row=static_cast<const unsigned char*>(map.pData)+y*map.RowPitch;
        if(floating)std::memcpy(pixels.data()+std::size_t(y)*width,row,width*16);
        else for(unsigned x=0;x<width;++x)for(unsigned k=0;k<4;++k){bytes.pixels[(std::size_t(y)*width+x)*4+k]=row[x*4+k];pixels[std::size_t(y)*width+x][k]=row[x*4+k]/255.f;}}
    context->Unmap(cpu.Get(),0);return true;
}
inline std::string PixelStage(unsigned stage,bool eleven) {
    const std::string inputs=eleven?"float4 position:SV_POSITION;float4 diffuse:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 specular:COLOR1;":"float4 diffuse:COLOR0;float4 specular:COLOR1;float2 a:TEXCOORD0;float2 b:TEXCOORD1;";
    std::string declaration=eleven?"Texture2D t0:register(t0),t1:register(t1);SamplerState s0:register(s0),s1:register(s1);":"sampler2D t0:register(s0),t1:register(s1);";
    const auto a=eleven?"t0.Sample(s0,input.a)":"tex2D(t0,input.a)";const auto b=eleven?"t1.Sample(s1,input.b)":"tex2D(t1,input.b)";
    const std::string expressions[]={"input.diffuse","float4(input.specular.rgb,1)","float4(input.a,0,1)","float4(input.b,0,1)",a,b,
        std::string("float4(input.diffuse.rgb*")+a+".rgb*"+b+".rgb,1)",
        std::string("float4(saturate(input.diffuse.rgb*")+a+".rgb*"+b+".rgb+input.specular.rgb),1)"};
    if(stage>=8)return {};
    return declaration+"struct Input{"+inputs+"};float4 main(Input input):"+(eleven?"SV_TARGET":"COLOR0")+"{return "+expressions[stage]+";}";
}
inline std::string FusedFinal() {
    std::string source=PixelStage(7,true);const auto at=source.find("{return ");
    if(at==std::string::npos)return {};
    source.replace(at,std::string::npos,"{precise float3 stage0=input.diffuse.rgb*t0.Sample(s0,input.a).rgb;float3 sampled=t1.Sample(s1,input.b).rgb;precise double3 product=double3(stage0)*double3(sampled);precise double3 combined=product+double3(input.specular.rgb);return float4(saturate(float3(combined)),1);}");return source;
}
inline int Stages(HWND window,const char* root,const char* destination,unsigned focusX=867,unsigned focusY=486,unsigned triangle=1383,bool textureFma=false) {
    const auto vertexShader=std::string(textureFma?"#define MDS_MODEL_TEXTURE_FMA_DIAGNOSTIC 1\n":"")+modelDx9CompatibilitySource+modelVertexSource;
    const auto Stage11=[&](const D3D9ReplaySnapshot& draw,unsigned width,unsigned height,const std::string& ps,bool floating,
                          RgbaImage& image,std::vector<Color>& values,const std::array<float,4>& clear=std::array<float,4>{1,1,1,1},float offset=.5f) {
        return model_batch_color::Stage11(draw,width,height,ps,floating,image,values,clear,offset,nullptr,&vertexShader);
    };
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,24));
    CHECK(triangle<archive.draws[22].count);
    auto compact=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(archive.draws[22],triangle,1));
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})ground_history_isolation::State(compact,key,0);
    ground_history_isolation::State(compact,D3DRS_CULLMODE,D3DCULL_NONE);
    CHECK(focusX<archive.width && focusY<archive.height);
    std::ofstream table(output/"stages.csv");table<<"mode,repeat,x,y,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA\n"<<std::setprecision(17);
    const unsigned x=focusX,y=focusY;const auto focus=std::size_t(y)*archive.width+x;RgbaImage a,b;std::vector<Color> native,candidate;
    std::ofstream metadata(output/"metadata.txt");metadata<<"draw=23 triangle="<<triangle<<" x="<<x<<" y="<<y<<" width="<<archive.width<<" height="<<archive.height<<" diagnosticTextureFma="<<textureFma<<" productionActivation=0 imageAcceptance=0\n";CHECK(metadata);
    // Untouched FF float target preserves its own pixel path; stage observations
    // install a PS after native FF vertices, so their evidence stays separate.
    CHECK(NativeImage(window,{compact},1,a,nullptr,archive.width,archive.height,archive.clear,&native));
    table<<"fixed_function_float,0,"<<x<<","<<y;for(float f:native[focus])table<<","<<f;table<<",nan,nan,nan,nan\n";
    const auto fixed=native[focus];
    CHECK(NativeImage(window,{compact},1,a,nullptr,archive.width,archive.height,archive.clear));const auto baselineNative=a.pixels;
    const std::string production=std::string("#define MDS_MODEL_SPECULAR 1\n")+modelPixelSource;
    CHECK(Stage11(compact,archive.width,archive.height,production,false,b,candidate));const auto baselineCandidate=b.pixels;
    // The saved x64 and x86 captures have different failing channels. Keep
    // the observed bytes as evidence instead of hard-coding the old x64
    // green-channel values into the probe.
    // A different policy or fixture can already match the byte target. Still
    // measure the individual float stages; parity here is not an image gate.
    const char* names[]={"diffuse","specular","coordinate0","coordinate1","sample0","sample1","pre_specular","final"};
    for(unsigned stage=0;stage<8;++stage)for(unsigned repeat=0;repeat<3;++repeat) {
        const auto ps9=PixelStage(stage,false),ps11=PixelStage(stage,true);
        CHECK(NativeImage(window,{compact},1,a,nullptr,archive.width,archive.height,archive.clear,&native,&ps9));
        CHECK(Stage11(compact,archive.width,archive.height,ps11,true,b,candidate));
        table<<names[stage]<<","<<repeat<<","<<x<<","<<y;for(float f:native[focus])table<<","<<f;for(float f:candidate[focus])table<<","<<f;table<<"\n";table.flush();
        std::ofstream file(output/(std::string(names[stage])+".repeat"+std::to_string(repeat)+".float"),std::ios::binary);
        for(const auto* values:{&native,&candidate})for(unsigned row=y-2;row<=y+2;++row)file.write(reinterpret_cast<const char*>(values->data()+std::size_t(row)*archive.width+x-2),5*sizeof(Color));CHECK(file);
        if(stage==7 && repeat==0) {
            CHECK(NativeImage(window,{compact},1,a,nullptr,archive.width,archive.height,archive.clear,nullptr,&ps9));
            CHECK(Stage11(compact,archive.width,archive.height,ps11,false,b,candidate));
            std::ofstream gate(output/"byte_gate.txt");gate<<"nativeExplicitPsExact="<<(a.pixels==baselineNative)<<" candidateExplicitPsExact="<<(b.pixels==baselineCandidate)
                <<" fixedFloat="<<std::setprecision(17)<<fixed[0]<<","<<fixed[1]<<","<<fixed[2]<<","<<fixed[3]<<"\n";CHECK(gate);
        }
    }
    // Targeted raster controls.  The native side always uses the captured
    // DX9 viewport; only the diagnostic DX11 viewport origin is changed.
    std::ofstream centers(output/"pixel_center.csv");
    centers<<"mode,offset,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA,differentPixels,knownDifferentPixels,focusDifferent,maxAbsDelta\n"<<std::setprecision(17);
    auto compareCenter=[&](std::ostream& report,const D3D9ReplaySnapshot& draw,const char* mode,unsigned stage,float offset) {
        const auto ps9=PixelStage(stage,false),ps11=PixelStage(stage,true);std::vector<Color> n,c;RgbaImage nb,cb;
        if(!NativeImage(window,{draw},1,nb,nullptr,archive.width,archive.height,archive.clear,&n,&ps9) ||
           !Stage11(draw,archive.width,archive.height,ps11,true,cb,c,{},offset))return false;
        unsigned different=0,knownDifferent=0;double maximum=0;const auto& viewport=draw.viewport;
        const unsigned left=(std::min)(archive.width,static_cast<unsigned>(viewport.X));
        const unsigned top=(std::min)(archive.height,static_cast<unsigned>(viewport.Y));
        const unsigned right=(std::min)(archive.width,static_cast<unsigned>(viewport.X+viewport.Width));
        const unsigned bottom=(std::min)(archive.height,static_cast<unsigned>(viewport.Y+viewport.Height));
        bool focusChanged=false;
        for(std::size_t p=0;p<n.size();++p){bool changed=false;for(unsigned k=0;k<4;++k){changed|=n[p][k]!=c[p][k];maximum=(std::max)(maximum,std::abs(double(n[p][k])-double(c[p][k])));}different+=changed;
            const unsigned px=static_cast<unsigned>(p%archive.width),py=static_cast<unsigned>(p/archive.width);
            if(changed && px>=left && px<right && py>=top && py<bottom)++knownDifferent;
            if(p==focus)focusChanged=changed;
        }
        report<<mode<<","<<offset;for(float v:n[focus])report<<","<<v;for(float v:c[focus])report<<","<<v;report<<","<<different<<","<<knownDifferent<<","<<focusChanged<<","<<maximum<<"\n";report.flush();return true;
    };
    for(const auto& item:std::array<std::pair<const char*,unsigned>,4>{{{"coordinate0",2},{"sample0",4},{"sample1",5},{"final",7}}})
        for(float offset:std::array<float,2>{{.5f,0.f}})CHECK(compareCenter(centers,compact,item.first,item.second,offset));
    CHECK(centers);
    std::ofstream sampling(output/"sampling_precision.csv");
    sampling<<"mode,offset,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA,differentPixels,knownDifferentPixels,focusDifferent,maxAbsDelta\n"<<std::setprecision(17);
    for(const auto& item:std::array<const char*,4>{{"captured","point","linear_mip_point","linear_mip_linear"}}) {
        auto draw=compact;
        if(std::string(item)=="point") {
            model_color_isolation::Sampler(draw,0,D3DSAMP_MINFILTER,D3DTEXF_POINT);model_color_isolation::Sampler(draw,0,D3DSAMP_MAGFILTER,D3DTEXF_POINT);model_color_isolation::Sampler(draw,0,D3DSAMP_MIPFILTER,D3DTEXF_POINT);
        } else if(std::string(item)=="linear_mip_point") model_color_isolation::Sampler(draw,0,D3DSAMP_MIPFILTER,D3DTEXF_POINT);
        else if(std::string(item)=="linear_mip_linear") model_color_isolation::Sampler(draw,0,D3DSAMP_MIPFILTER,D3DTEXF_LINEAR);
        CHECK(compareCenter(sampling,draw,item,4,.5f));
    }
    CHECK(sampling);
    const auto fused=FusedFinal();CHECK(!fused.empty());
    if(textureFma) {
        const auto actualSource=std::string("#define MDS_MODEL_SPECULAR 1\n#define MDS_MODEL_DX9_COMPATIBILITY 1\n#define MDS_MODEL_ALPHA12_DIAGNOSTIC 1\n")+modelPixelSource;
        for(unsigned repeat=0;repeat<3;++repeat) {
            CHECK(Stage11(compact,archive.width,archive.height,actualSource,true,b,candidate));
            table<<"production_measured,"<<repeat<<","<<x<<","<<y;for(float f:fixed)table<<","<<f;for(float f:candidate[focus])table<<","<<f;table<<"\n";table.flush();
            CHECK(Stage11(compact,archive.width,archive.height,actualSource,false,b,candidate));
            std::ofstream bytes(output/("production_measured.repeat"+std::to_string(repeat)+".rgba"),std::ios::binary);
            bytes.write(reinterpret_cast<const char*>(b.pixels.data()),b.pixels.size());CHECK(bytes);
        }
    }
    for(unsigned repeat=0;repeat<3;++repeat) {
        const auto ps9=PixelStage(7,false);CHECK(NativeImage(window,{compact},1,a,nullptr,archive.width,archive.height,archive.clear,&native,&ps9));
        CHECK(Stage11(compact,archive.width,archive.height,fused,true,b,candidate));
        table<<"final_fused,"<<repeat<<","<<x<<","<<y;for(float f:native[focus])table<<","<<f;for(float f:candidate[focus])table<<","<<f;table<<"\n";
        // The fused expression is a diagnostic arithmetic candidate.  Keep
        // its output even when this batch's earlier varying/texture stage is
        // already different; it must not turn a diagnostic into acceptance.
        CHECK(Stage11(compact,archive.width,archive.height,fused,false,b,candidate));
        if(repeat==0)for(unsigned path=0;path<3;++path) {
            const auto& bytes=path==0?baselineNative:path==1?baselineCandidate:b.pixels;
            RgbaImage image{archive.width,archive.height,bytes};const auto cropped=scene_prefix_diagnostic::Crop(image,archive.region);
            const char* names[]={"native.bgra","baseline.candidate.bgra","fused.candidate.bgra"};
            std::ofstream file(output/names[path],std::ios::binary);file.write(reinterpret_cast<const char*>(cropped.data()),cropped.size());CHECK(file);
        }
    }
    for(unsigned mode=0;mode<2;++mode) {
        const auto text=mode?fused:PixelStage(7,true);ComPtr<ID3DBlob> code,error,assembly;
        CHECK(SUCCEEDED(D3DCompile(text.data(),text.size(),nullptr,nullptr,nullptr,"main","ps_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error)));
        CHECK(SUCCEEDED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&assembly)));
        std::ofstream file(output/(mode?"final_fused.dxbc.txt":"final.dxbc.txt"));file.write(static_cast<const char*>(assembly->GetBufferPointer()),assembly->GetBufferSize());CHECK(file);
    }
    CHECK(table);std::ofstream summary(output/"summary.txt");summary<<"complete=1 triangle="<<triangle<<" focus="<<x<<","<<y<<" observations="<<(textureFma?30:27)<<" repeats=3 diagnosticTextureFma="<<textureFma<<" fusedFloatExact=diagnostic fusedByteExact=diagnostic nativeFixedFunctionFloatSeparate=1 productionActivation=0 imageAcceptance=0\n";CHECK(summary);return 0;
}
}
