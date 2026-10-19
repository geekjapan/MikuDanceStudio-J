#pragma once
// Native FF point observations have no varying interpolation; they are not
// claimed to be a capture of DX9 pre-raster registers. Shared COLOR1 draws
// must reproduce the original raster output before attributing a difference.
namespace model_specular_origin {
using model_batch_color::Color;
using model_sampling_diagnostic::Vertex;
using model_sampling_diagnostic::Area;
using model_transform_diagnostic::Crop;
using model_transform_diagnostic::Save;
struct Images {std::vector<Color> n,c;};
inline std::string Source(unsigned cameraPolicy=0) {
    std::string text=modelVertexSource;
    const std::string anchor="float4 camera = mul(mul(float4(input.position,1),world),view);";
    const auto at=text.find(anchor);if(at==std::string::npos || cameraPolicy>7)return {};
    if(cameraPolicy==1 || cameraPolicy==2)text.replace(at,anchor.size(),cameraPolicy==1?
        "float4 camera=SpecularCamera(SpecularCamera(float4(input.position,1),world),view);":
        "row_major float4x4 worldView;[unroll]for(uint r=0;r<4;++r)[unroll]for(uint c=0;c<4;++c){precise float sum=0;[unroll]for(uint k=0;k<4;++k){precise float product=world[r][k]*view[k][c];sum=sum+product;}worldView[r][c]=sum;}float4 camera=SpecularCamera(float4(input.position,1),worldView);");
    if(cameraPolicy==3){const std::string original="dot(normal,halfway)";std::size_t p=0;while((p=text.find(original,p))!=std::string::npos){text.replace(p,original.size(),"Dx9Dot3(normal,halfway)");p+=std::strlen("Dx9Dot3(normal,halfway)");}}
    if(cameraPolicy==4){const std::string original="-normalize(mul(float4(lightDirection[i].xyz,0),view).xyz)";const auto p=text.find(original);if(p==std::string::npos)return {};
        text.replace(p,original.size(),"-mul(float4(normalize(lightDirection[i].xyz),0),view).xyz");}
    if(cameraPolicy==5){const std::string original="normalize(-camera.xyz)";const auto p=text.find(original);if(p==std::string::npos)return {};text.replace(p,original.size(),"SpecularNormalize(-camera.xyz)");}
    if(cameraPolicy==6){const std::string original="normalize(towardLight+viewer)";const auto p=text.find(original);if(p==std::string::npos)return {};text.replace(p,original.size(),"SpecularNormalize(towardLight+viewer)");}
    if(cameraPolicy==7){const std::string original="mul(float4(lightDirection[i].xyz,0),view).xyz";const auto p=text.find(original);if(p==std::string::npos)return {};text.replace(p,original.size(),"Dx9Normal(lightDirection[i].xyz,view)");}
    return std::string("#define MDS_MODEL_DX9_COMPATIBILITY 1\n#define MDS_MODEL_TEXTURE_FMA_DIAGNOSTIC 1\n")+modelDx9CompatibilitySource+R"(
float3 SpecularNormalize(float3 n){precise float inverse=rsqrt(Dx9Dot3(n,n));return n*inverse;}
float4 SpecularCamera(float4 p,row_major float4x4 m) {
    float4 result;[unroll]for(uint c=0;c<4;++c)result[c]=Dx9Dot4(p,float4(m[0][c],m[1][c],m[2][c],m[3][c]));return result;
}
)"+text;
}
struct Interpolation : model_sampling_diagnostic::Renderer {
    bool Initialize(HWND window,unsigned w,unsigned h,const D3DVIEWPORT9& v,const Area& area) {
        ModelTextureData dummy;dummy.levels.push_back({1,1,{255,255,255,255}});
        if(!Renderer::Initialize(window,w,h,v,area,dummy))return false;
        const std::string input9="struct O{float4 p:POSITION;float4 c:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 s:COLOR1;};";
        const std::string input11="struct O{float4 p:SV_POSITION;float4 c:COLOR0;float2 a:TEXCOORD0;float2 b:TEXCOORD1;float2 d:TEXCOORD2;float3 s:COLOR1;};";
        const std::string body="O main(float4 p:POSITION,float2 uv:TEXCOORD0){O o;o.p=p;o.c=1;o.a=o.b=o.d=0;o.s=float3(uv,0);return o;}";
        ComPtr<ID3DBlob> code;
        if(!Compile(input9+body,"vs_3_0",code) || FAILED(d9->CreateVertexShader(static_cast<DWORD*>(code->GetBufferPointer()),&vs9)))return false;
        if(!Compile(input9+body,"vs_2_0",code) || FAILED(d9->CreateVertexShader(static_cast<DWORD*>(code->GetBufferPointer()),&legacyVs9)))return false;
        if(!Compile(input11+body,"vs_5_0",code) || FAILED(d11->CreateVertexShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&vs11)))return false;
        const auto ps9text=input9+"float4 main(O i):COLOR0{return float4(i.s,1);}";
        const auto ps11text=input11+"float4 main(O i):SV_TARGET{return float4(i.s,1);}";
        if(!Compile(ps9text,"ps_3_0",code) || FAILED(d9->CreatePixelShader(static_cast<DWORD*>(code->GetBufferPointer()),&ps9[1])))return false;
        if(!Compile(ps9text,"ps_2_a",code) || FAILED(d9->CreatePixelShader(static_cast<DWORD*>(code->GetBufferPointer()),&legacyPs9[1])))return false;
        return Compile(ps11text,"ps_5_0",code) && SUCCEEDED(d11->CreatePixelShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&ps11[1]));
    }
    bool Observe(const std::vector<Color>& clip,const std::vector<std::array<float,3>>& values,bool legacy,Images& out) {
        if(clip.size()!=3 || values.size()!=3)return false;std::array<Images,2> pair;
        for(unsigned p=0;p<2;++p){std::array<Vertex,3> vertices;
            for(unsigned v=0;v<3;++v)vertices[v]={clip[v],{values[v][p],values[v][p+1]}};
            std::vector<unsigned char> nb,cb;
            if(!Render(vertices,1,1,0,pair[p].n,pair[p].c,nb,cb,{},{},legacy))return false;
        }
        out.n=pair[0].n;out.c=pair[0].c;
        for(unsigned p=0;p<out.n.size();++p) {
            if(pair[0].n[p][1]!=pair[1].n[p][0] || pair[0].c[p][1]!=pair[1].c[p][0])return false;
            out.n[p][2]=pair[1].n[p][1];out.c[p][2]=pair[1].c[p][1];
        }
        return true;
    }
};
inline bool NativeVertex(HWND window,const D3D9ReplaySnapshot& original,unsigned v,unsigned width,unsigned height,IDirect3DDevice9* device,Color& value,unsigned& covered,bool centered=false) {
    auto point=original;point.type=D3DPT_POINTLIST;point.indexed=false;point.count=point.vertices=1;point.start=v;
    // Optional control changes only projection XY. Camera position, normals
    // and lighting remain original, including local-viewer direction.
    if(centered)for(unsigned r=0;r<4;++r){point.projection.m[r][0]=0;point.projection.m[r][1]=0;}
    float size=4;DWORD bits;std::memcpy(&bits,&size,4);
    if(FAILED(device->SetRenderState(D3DRS_POINTSIZE,bits)) || FAILED(device->SetRenderState(D3DRS_POINTSCALEENABLE,FALSE)))return false;
    RgbaImage unused;std::vector<Color> pixels;const auto ps=model_batch_color::PixelStage(1,false);
    if(!NativeImage(window,{point},1,unused,nullptr,width,height,0xffffffff,&pixels,&ps,device))return false;
    covered=0;for(const auto& p:pixels)if(p!=Color{1,1,1,1}) {if(covered && p!=value)return false;value=p;++covered;}
    return covered>0 && value[3]==1;
}
inline bool NativeFlat(HWND window,const D3D9ReplaySnapshot& original,unsigned rotation,unsigned width,unsigned height,IDirect3DDevice9* device,
                       Color& value,unsigned& covered,bool& constant) {
    auto draw=original;draw.indexFormat=D3DFMT_INDEX16;draw.indexBytes.clear();draw.start=0;
    for(unsigned v=0;v<3;++v){const unsigned index=(v+rotation)%3;draw.indexBytes.push_back(static_cast<unsigned char>(index));draw.indexBytes.push_back(0);}
    ground_history_isolation::State(draw,D3DRS_SHADEMODE,D3DSHADE_FLAT);
    RgbaImage unused;std::vector<Color> pixels;const auto ps=model_batch_color::PixelStage(1,false);
    if(!NativeImage(window,{draw},1,unused,nullptr,width,height,0xffffffff,&pixels,&ps,device))return false;
    covered=0;constant=true;for(const auto& p:pixels)if(p!=Color{1,1,1,1}){if(covered && p!=value)constant=false;if(!covered)value=p;++covered;}
    return covered>0;
}
inline bool Observe(HWND window,const D3D9ReplaySnapshot& draw,unsigned width,unsigned height,IDirect3DDevice9* device,Images& out) {
    RgbaImage unused;const auto a=model_batch_color::PixelStage(1,false),b=model_batch_color::PixelStage(1,true),shader=Source();
    return NativeImage(window,{draw},1,unused,nullptr,width,height,0xffffffff,&out.n,&a,device) &&
        model_batch_color::Stage11(draw,width,height,b,true,unused,out.c,{1,1,1,1},.5f,nullptr,&shader);
}
inline bool MeshValues(HWND window,const D3D9ReplaySnapshot& source,unsigned width,unsigned height,IDirect3DDevice9* device,
                       const std::vector<std::array<float,3>>& values,Images& out) {
    std::array<Images,2> pairs;
    for(unsigned pair=0;pair<2;++pair){auto draw=source;
        for(unsigned v=0;v<3;++v)std::memcpy(draw.vertexBytes.data()+v*32+24,values[v].data()+pair,8);
        Stage(draw,0,D3DTSS_TEXCOORDINDEX,0);Stage(draw,0,D3DTSS_TEXTURETRANSFORMFLAGS,0);
        RgbaImage unused;const auto a=model_batch_color::PixelStage(2,false),b=model_batch_color::PixelStage(2,true),shader=Source();
        if(!NativeImage(window,{draw},1,unused,nullptr,width,height,0xffffffff,&pairs[pair].n,&a,device) ||
           !model_batch_color::Stage11(draw,width,height,b,true,unused,pairs[pair].c,{1,1,1,1},.5f,nullptr,&shader))return false;
    }
    out=pairs[0];for(unsigned p=0;p<out.n.size();++p){if(pairs[0].n[p][1]!=pairs[1].n[p][0] || pairs[0].c[p][1]!=pairs[1].c[p][0])return false;
        out.n[p][2]=pairs[1].n[p][1];out.c[p][2]=pairs[1].c[p][1];}
    return true;
}
inline int Run(HWND window,const char* root,const char* destination,unsigned x,unsigned y,unsigned triangle) {
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,24));CHECK(triangle<archive.draws[22].count);
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    auto source=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(archive.draws[22],triangle,1));
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})ground_history_isolation::State(source,key,0);
    ground_history_isolation::State(source,D3DRS_CULLMODE,D3DCULL_NONE);
    std::ofstream vertices(output/"vertices.csv"),report(output/"controls.csv"),pixels(output/"pixels.csv"),stages(output/"vertex_stages.csv"),cameraVertices(output/"camera_vertices.csv"),powerValues(output/"power_controls.csv"),flatVertices(output/"flat_vertices.csv");
    flatVertices<<"geometry,repeat,rotation,channel,value,bits,constant,coveredPixels\n"<<std::setprecision(17);
    powerValues<<"geometry,control,repeat,vertex,channel,power,nativePoint,dx11SO,nativeBits,dx11Bits,nativeFlat,nativeFlatBits,flatConstant\n"<<std::setprecision(17);
    cameraVertices<<"geometry,policy,repeat,vertex,channel,nativePoint,candidateSO,nativeBits,candidateBits\n"<<std::setprecision(17);
    vertices<<"geometry,repeat,vertex,channel,nativePoint,dx11SO,nativeBits,dx11Bits,pointPixels,centeredPoint,centeredBits\n"<<std::setprecision(17);
    report<<"geometry,mode,repeat,coveredPixels,betweenApis,nativeVsOriginal,candidateVsOriginal\n";
    pixels<<"geometry,mode,repeat,x,y,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA\n"<<std::setprecision(17);
    stages<<"geometry,stage,repeat,vertex,channel,value,bits\n"<<std::setprecision(17);
    unsigned observations=0,vertexDifferences=0;
    for(unsigned geometry=0;geometry<3;++geometry) {
        auto base=geometry?model_batch_causal::Independent(source):source;
        // Holdout changes normals and shininess without using any observations.
        if(geometry==2){const float n[][3]={{-.43f,.27f,-.81f},{.17f,-.31f,-.93f},{-.71f,.09f,-.53f}};
            for(unsigned v=0;v<3;++v)std::memcpy(base.vertexBytes.data()+v*32+12,n[v],12);base.material.Power=7.3f;}
        const std::string label=geometry==0?"saved":geometry==1?"independent":"holdout";
        const unsigned width=geometry?64:archive.width,height=geometry?64:archive.height,fx=geometry?24:x,fy=geometry?32:y;
        const auto& viewport=base.viewport;const Area area{viewport.X,viewport.Y,viewport.Width,viewport.Height};
        CHECK(fx>=area.x+2 && fy>=area.y+2 && fx+2<area.x+area.width && fy+2<area.y+area.height);
        ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=width;pp.BackBufferHeight=height;pp.BackBufferCount=1;
        pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        ComPtr<IDirect3DDevice9> device;const auto hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
        if(FAILED(hr))std::fprintf(stderr,"specular origin DX9=%08lx\n",static_cast<unsigned long>(hr));CHECK(SUCCEEDED(hr));
        Interpolation shared;CHECK(shared.Initialize(window,width,height,viewport,area));
        Images original;CHECK(Observe(window,base,width,height,device.Get(),original));original={Crop(original.n,width,area),Crop(original.c,width,area)};
        const auto record=[&](const std::string& mode,unsigned repeat,const Images& image) {
            if(image.n.size()!=original.n.size() || image.c.size()!=original.c.size())return false;
            unsigned between=0,nd=0,cd=0,covered=0;
            for(unsigned p=0;p<image.n.size();++p){const bool mask=original.n[p]!=Color{1,1,1,1} && original.c[p]!=Color{1,1,1,1};
                covered+=mask;between+=image.n[p]!=image.c[p];nd+=image.n[p]!=original.n[p];cd+=image.c[p]!=original.c[p];}
            if(!covered)return false;
            report<<label<<","<<mode<<","<<repeat<<","<<covered<<","<<between<<","<<nd<<","<<cd<<"\n";
            for(unsigned py=fy-2;py<=fy+2;++py)for(unsigned px=fx-2;px<=fx+2;++px){const auto p=std::size_t(py-area.y)*area.width+px-area.x;
                pixels<<label<<","<<mode<<","<<repeat<<","<<px<<","<<py;for(float f:image.n[p])pixels<<","<<f;for(float f:image.c[p])pixels<<","<<f;pixels<<"\n";}
            const auto stem=label+"_"+mode+".repeat"+std::to_string(repeat);
            if(!Save(output/(stem+".dx9.float"),image.n.data(),image.n.size()*16) || !Save(output/(stem+".dx11.float"),image.c.data(),image.c.size()*16))return false;
            ++observations;report.flush();pixels.flush();std::printf("specularOrigin %s %s repeat=%u between=%u nativeDelta=%u candidateDelta=%u\n",label.c_str(),mode.c_str(),repeat,between,nd,cd);std::fflush(stdout);return bool(report && pixels);
        };
        std::vector<Color> positions;std::vector<std::array<float,3>> nativeValues(3),candidateValues,previousNative;
        const auto shader=Source();
        for(unsigned repeat=0;repeat<3;++repeat) {
            std::vector<Color> clip;std::vector<std::array<float,3>> spec;
            CHECK(CaptureDepthVertexShader(base,clip,nullptr,false,0,nullptr,&shader,nullptr,false,nullptr,0,false,false,true,&spec));CHECK(clip.size()==3 && spec.size()==3);
            if(repeat)CHECK(clip==positions && spec==candidateValues);else {positions=clip;candidateValues=spec;}
            for(unsigned v=0;v<3;++v){Color value{},centered{};unsigned covered,centeredCovered;CHECK(NativeVertex(window,base,v,width,height,device.Get(),value,covered));
                CHECK(NativeVertex(window,base,v,width,height,device.Get(),centered,centeredCovered,true));
                nativeValues[v]={value[0],value[1],value[2]};
                for(unsigned k=0;k<3;++k){vertices<<label<<","<<repeat<<","<<v<<","<<k<<","<<value[k]<<","<<spec[v][k]<<","<<ground_endpoint_depth::Bits(value[k])<<","<<ground_endpoint_depth::Bits(spec[v][k])<<","<<covered<<","<<centered[k]<<","<<ground_endpoint_depth::Bits(centered[k])<<"\n";vertexDifferences+=value[k]!=spec[v][k];}
            }
            if(repeat)CHECK(nativeValues==previousNative);previousNative=nativeValues;
            std::vector<std::array<float,3>> flatValues(3);bool flatConstant=true;
            for(unsigned v=0;v<3;++v){Color value{};unsigned covered;bool constant;
                CHECK(NativeFlat(window,base,v,width,height,device.Get(),value,covered,constant));flatConstant=flatConstant && constant;flatValues[v]={value[0],value[1],value[2]};
                for(unsigned k=0;k<3;++k)flatVertices<<label<<","<<repeat<<","<<v<<","<<k<<","<<value[k]<<","<<ground_endpoint_depth::Bits(value[k])<<","<<constant<<","<<covered<<"\n";
            }
            Images actual;CHECK(Observe(window,base,width,height,device.Get(),actual));actual={Crop(actual.n,width,area),Crop(actual.c,width,area)};
            CHECK(actual.n==original.n && actual.c==original.c);CHECK(record("original",repeat,actual));
            for(unsigned side=0;side<2;++side)for(bool legacy:{false,true}){Images image;CHECK(shared.Observe(positions,side?candidateValues:nativeValues,legacy,image));
                CHECK(record(std::string(side?"shared_dx11_values":"shared_dx9_point_values")+(legacy?"_ps2":"_ps3"),repeat,image));}
            for(unsigned side=0;side<2;++side){Images mesh;CHECK(MeshValues(window,base,width,height,device.Get(),side?candidateValues:nativeValues,mesh));
                CHECK(record(side?"mesh_dx11_values":"mesh_dx9_point_values",repeat,{Crop(mesh.n,width,area),Crop(mesh.c,width,area)}));}
            if(flatConstant){Images image;CHECK(shared.Observe(positions,flatValues,true,image));CHECK(record("shared_dx9_flat_values",repeat,image));}
            for(unsigned policy=1;policy<=7;++policy){const auto cameraSource=Source(policy);std::vector<Color> clip;std::vector<std::array<float,3>> high;
                CHECK(CaptureDepthVertexShader(base,clip,nullptr,false,0,nullptr,&cameraSource,nullptr,false,nullptr,0,false,false,true,&high));CHECK(clip==positions && high.size()==3);
                for(unsigned v=0;v<3;++v)for(unsigned k=0;k<3;++k)cameraVertices<<label<<","<<policy<<","<<repeat<<","<<v<<","<<k<<","<<nativeValues[v][k]<<","<<high[v][k]<<","<<ground_endpoint_depth::Bits(nativeValues[v][k])<<","<<ground_endpoint_depth::Bits(high[v][k])<<"\n";
                Images image;RgbaImage unused;const auto ps=model_batch_color::PixelStage(1,true);
                CHECK(model_batch_color::Stage11(base,width,height,ps,true,unused,image.c,{1,1,1,1},.5f,nullptr,&cameraSource));
                image.n=original.n;image.c=Crop(image.c,width,area);CHECK(record("camera_policy"+std::to_string(policy),repeat,image));
            }
            for(unsigned control=0;control<6;++control){auto unit=base;unit.material.Specular={1,1,1,1};
                for(auto& light:unit.lights)if(light.enabled)light.value.Specular={1,1,1,1};
                if(control<4)unit.material.Power=control==3?5.f:float(control);
                else {ground_history_isolation::State(unit,D3DRS_LOCALVIEWER,0);unit.material.Power=control==4?1.f:5.f;}
                std::vector<Color> clip;std::vector<std::array<float,3>> high;
                CHECK(CaptureDepthVertexShader(unit,clip,nullptr,false,0,nullptr,&shader,nullptr,false,nullptr,0,false,false,true,&high));CHECK(high.size()==3);
                for(unsigned v=0;v<3;++v){Color point{},flat{};unsigned covered,flatCovered;bool constant;CHECK(NativeVertex(window,unit,v,width,height,device.Get(),point,covered));
                    CHECK(NativeFlat(window,unit,v,width,height,device.Get(),flat,flatCovered,constant));CHECK(constant);
                    for(unsigned k=0;k<3;++k)powerValues<<label<<","<<control<<","<<repeat<<","<<v<<","<<k<<","<<unit.material.Power<<","<<point[k]<<","<<high[v][k]<<","<<ground_endpoint_depth::Bits(point[k])<<","<<ground_endpoint_depth::Bits(high[v][k])<<","<<flat[k]<<","<<ground_endpoint_depth::Bits(flat[k])<<","<<constant<<"\n";}
            }
        }
        // Retain actual production VS intermediate arithmetic, observed with
        // stream output. These are DX11 values, not native FF stage captures.
        const char* expressions[]={"float4(camera.xyz,1)","float4(normal,1)","float4(towardLight,1)","float4(viewer,1)","float4(halfway,1)",
            "float4(dot(normal,halfway),max(dot(normal,halfway),0),facing,1)","float4(pow(max(dot(normal,halfway),0),parameters.x).xxx,1)",
            "float4(specular.rgb*lightSpecular[i].rgb,1)"};
        for(unsigned stage=0;stage<8;++stage)for(unsigned repeat=0;repeat<3;++repeat) {
            auto diagnostic=shader;const std::string declaration="float3 specular:COLOR1;";auto at=diagnostic.find(declaration);CHECK(at!=std::string::npos);
            diagnostic.insert(at+declaration.size(),"float4 probe:TEXCOORD3;");
            const std::string anchor="highlight += specular.rgb*lightSpecular[i].rgb*pow(max(dot(normal,halfway),0),parameters.x);";
            at=diagnostic.find(anchor);CHECK(at!=std::string::npos);diagnostic.insert(at,"output.probe="+std::string(expressions[stage])+";");
            at=diagnostic.find("return output;");CHECK(at!=std::string::npos);diagnostic.insert(at,"output.litDiffuse=output.probe;");
            std::vector<Color> clip,values;CHECK(CaptureDepthVertexShader(base,clip,nullptr,false,0,&values,&diagnostic,nullptr,false,nullptr,0,false,false,true));CHECK(values.size()==3);
            for(unsigned v=0;v<3;++v)for(unsigned k=0;k<4;++k)stages<<label<<","<<stage<<","<<repeat<<","<<v<<","<<k<<","<<values[v][k]<<","<<ground_endpoint_depth::Bits(values[v][k])<<"\n";
        }
    }
    for(unsigned policy=0;policy<=7;++policy){const auto shader=Source(policy);ComPtr<ID3DBlob> code,error,listing;
        CHECK(SUCCEEDED(D3DCompile(shader.data(),shader.size(),nullptr,nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error)));
        CHECK(SUCCEEDED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)));
        std::ofstream hlsl(output/("policy"+std::to_string(policy)+".hlsl")),assembly(output/("policy"+std::to_string(policy)+".asm"));hlsl<<shader;
        assembly.write(static_cast<const char*>(listing->GetBufferPointer()),listing->GetBufferSize());CHECK(hlsl && assembly);}
    std::ofstream metadata(output/"metadata.txt"),summary(output/"summary.txt");metadata<<"archive="<<root<<" triangle="<<triangle<<" focus="<<x<<","<<y<<" dx11PreRasterSO=1 dx9PreRasterCapture=0 nativePointOriginalProjection=1 centeredPointControl=1 diagnosticTextureFma=1 productionActivation=0 imageAcceptance=0\n";
    summary<<"complete=1 geometries=3 repeats=3 observations="<<observations<<" vertexChannelDifferences="<<vertexDifferences<<" productionActivation=0 imageAcceptance=0\n";
    CHECK(vertices && report && pixels && stages && cameraVertices && powerValues && flatVertices && metadata && summary);return 0;
}
}
