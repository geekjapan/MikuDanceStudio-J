#pragma once
// Test-owned cuts of the specular expression. Explicit SM3 results and FF
// axis responses are observations, not captures of hidden FF registers.
namespace model_specular_stages {
using model_batch_color::Color;
using Vector=std::array<float,3>;
using Inputs=std::array<Color,6>; // camera, normal, raw light, viewer, halfway, dot/power
using ground_history_isolation::State;
constexpr unsigned StageCount=23;
inline const char* StageName(unsigned stage) {
    static const char* names[]={"viewer_length2","viewer_rsqrt","viewer","half_sum","half_length2","half_rsqrt","halfway",
        "dot","log2","power_log","exp2","pow","full_strength","fixed_viewer_strength","fixed_half_strength","light_length2","light_rsqrt","toward_light","shared_value",
        "fused_half_sum","fused_halfway","fused_dot","fused_strength"};
    return stage<StageCount?names[stage]:"invalid";
}
inline std::string ArithmeticSource(unsigned stage,bool eleven) {
    if(stage>=StageCount)return {};
    static const char* result[]={"viewerLength.xxx","viewerInverse.xxx","viewer","sum","halfLength.xxx","halfInverse.xxx","halfway",
        "ndh.xxx","logarithm.xxx","poweredLog.xxx","exponent.xxx","powerValue.xxx","fullStrength.xxx","viewerStrength.xxx","halfStrength.xxx",
        "lightLength.xxx","lightInverse.xxx","toward","q[3].xyz","fusedSum","fusedHalfway","fusedDot.xxx","fusedStrength.xxx"};
    const auto functions=std::string(eleven?modelDx9CompatibilitySource:"");
    const auto sum=eleven?"float3(Dx9FusedStep(-q[0].x,viewerInverse,toward.x),Dx9FusedStep(-q[0].y,viewerInverse,toward.y),Dx9FusedStep(-q[0].z,viewerInverse,toward.z))":"mad(-q[0].xyz,viewerInverse,toward)";
    return functions+std::string(eleven?"cbuffer Probe:register(b0){float4 q[6];};":"float4 q[6]:register(c0);")+
        "struct O{float4 p:"+(eleven?"SV_POSITION":"POSITION")+";float4 value:TEXCOORD0;};"+R"(
O main(float4 p:POSITION,float2 unused:TEXCOORD0){O o;o.p=p;
float lightLength=dot(q[2].xyz,q[2].xyz);float lightInverse=rsqrt(lightLength);float3 toward=normalize(q[2].xyz);
float viewerLength=dot(q[0].xyz,q[0].xyz);float viewerInverse=rsqrt(viewerLength);
float3 viewer=normalize(-q[0].xyz);
float3 sum=toward+q[3].xyz;float halfLength=dot(sum,sum);float halfInverse=rsqrt(halfLength);float3 halfway=normalize(sum);
float ndh=dot(q[1].xyz,q[4].xyz);
float logarithm=log2(max(q[5].x,0));float poweredLog=logarithm*q[5].y;float exponent=exp2(poweredLog);
float powerValue=pow(max(q[5].x,0),q[5].y);
float fullStrength=pow(max(dot(q[1].xyz,normalize(toward+viewer)),0),q[5].y);
float viewerStrength=pow(max(dot(q[1].xyz,halfway),0),q[5].y);
float halfStrength=pow(max(ndh,0),q[5].y);
)"+"float3 fusedSum="+sum+R"(;float3 fusedHalfway=normalize(fusedSum);float fusedDot=dot(q[1].xyz,fusedHalfway);
float fusedStrength=pow(max(fusedDot,0),q[5].y);
o.value=float4()"+result[stage]+",1);return o;}";
}
inline std::string FusedSource(unsigned cameraPolicy) {
    auto text=model_specular_origin::Source(cameraPolicy);const std::string anchor="float3 halfway=normalize(towardLight+viewer);";
    const auto at=text.find(anchor);if(at==std::string::npos)return {};
    text.replace(at,anchor.size(),"float3 halfSum=towardLight+viewer;if(flags.w){float inverse=rsqrt(dot(camera.xyz,camera.xyz));halfSum=Dx9Lighting(-camera.xyz,inverse.xxx,towardLight);}float3 halfway=normalize(halfSum);");return text;
}
struct Arithmetic : model_sampling_diagnostic::Renderer {
    std::array<ComPtr<IDirect3DVertexShader9>,StageCount> vertex9;
    std::array<ComPtr<ID3D11VertexShader>,StageCount> vertex11;
    ComPtr<IDirect3DPixelShader9> pixel9;
    ComPtr<ID3D11GeometryShader> geometry11;
    ComPtr<ID3D11Buffer> constants11,vertices11,output11,read11;
    ComPtr<IDirect3DSurface9> fixedDepth;
    std::array<model_sampling_diagnostic::Vertex,3> triangle{{{{-.75f,-.75f,.5f,1},{}},{{-.75f,.75f,.5f,1},{}},{{.75f,-.75f,.5f,1},{}}}};
    bool Initialize(HWND window,const std::filesystem::path& directory) {
        ModelTextureData dummy;dummy.levels.push_back({1,1,{255,255,255,255}});
        if(!Renderer::Initialize(window,64,64,{0,0,64,64,0,1},{0,0,64,64},dummy))return false;
        if(FAILED(d9->CreateDepthStencilSurface(64,64,D3DFMT_D24S8,D3DMULTISAMPLE_NONE,0,TRUE,&fixedDepth,nullptr)))return false;
        for(unsigned stage=0;stage<StageCount;++stage)for(bool eleven:{false,true}) {
            const auto text=ArithmeticSource(stage,eleven);ComPtr<ID3DBlob> code,listing;
            if(!Compile(text,eleven?"vs_5_0":"vs_3_0",code) || FAILED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)))return false;
            if(eleven?FAILED(d11->CreateVertexShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&vertex11[stage])):
                FAILED(d9->CreateVertexShader(static_cast<const DWORD*>(code->GetBufferPointer()),&vertex9[stage])))return false;
            std::ofstream hlsl(directory/(std::string(eleven?"dx11_":"dx9_")+StageName(stage)+".hlsl"));hlsl<<text;
            std::ofstream assembly(directory/(std::string(eleven?"dx11_":"dx9_")+StageName(stage)+".asm"));
            assembly.write(static_cast<const char*>(listing->GetBufferPointer()),listing->GetBufferSize());if(!hlsl || !assembly)return false;
        }
        ComPtr<ID3DBlob> code;
        if(!Compile("float4 main(float4 value:TEXCOORD0):COLOR0{return value;}","ps_3_0",code) ||
            FAILED(d9->CreatePixelShader(static_cast<const DWORD*>(code->GetBufferPointer()),&pixel9)))return false;
        const std::string gs="struct O{float4 p:SV_POSITION;float4 value:TEXCOORD0;};[maxvertexcount(1)]void main(point O input[1],inout PointStream<O> output){output.Append(input[0]);}";
        if(!Compile(gs,"gs_5_0",code))return false;
        const D3D11_SO_DECLARATION_ENTRY entry{0,"TEXCOORD",0,0,4,0};const UINT stride=16;
        if(FAILED(d11->CreateGeometryShaderWithStreamOutput(code->GetBufferPointer(),code->GetBufferSize(),&entry,1,&stride,1,D3D11_SO_NO_RASTERIZED_STREAM,nullptr,&geometry11)))return false;
        const auto buffer=[&](UINT size,UINT bind,const void* data,ComPtr<ID3D11Buffer>& target){D3D11_BUFFER_DESC d{};d.ByteWidth=size;d.BindFlags=bind;
            D3D11_SUBRESOURCE_DATA initial{data,0,0};return SUCCEEDED(d11->CreateBuffer(&d,data?&initial:nullptr,&target));};
        if(!buffer(sizeof(Inputs),D3D11_BIND_CONSTANT_BUFFER,nullptr,constants11) ||
            !buffer(sizeof(triangle),D3D11_BIND_VERTEX_BUFFER,triangle.data(),vertices11) || !buffer(48,D3D11_BIND_STREAM_OUTPUT,nullptr,output11))return false;
        D3D11_BUFFER_DESC staging{};staging.ByteWidth=48;staging.Usage=D3D11_USAGE_STAGING;staging.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        return SUCCEEDED(d11->CreateBuffer(&staging,nullptr,&read11));
    }
    bool Observe(unsigned stage,const Inputs& input,Color& native,Color& candidate) {
        if(stage>=StageCount || FAILED(d9->SetRenderTarget(0,target9[1].Get())) || FAILED(d9->SetDepthStencilSurface(nullptr)) ||
            FAILED(d9->SetVertexDeclaration(layout9.Get())) || FAILED(d9->SetVertexShader(vertex9[stage].Get())) ||
            FAILED(d9->SetPixelShader(pixel9.Get())) || FAILED(d9->SetVertexShaderConstantF(0,input[0].data(),6)))return false;
        for(auto s:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,0},{D3DRS_ZWRITEENABLE,0},{D3DRS_CULLMODE,D3DCULL_NONE},
            {D3DRS_ALPHABLENDENABLE,0},{D3DRS_ALPHATESTENABLE,0},{D3DRS_STENCILENABLE,0},{D3DRS_SCISSORTESTENABLE,0},
            {D3DRS_SRGBWRITEENABLE,0},{D3DRS_DITHERENABLE,0},{D3DRS_COLORWRITEENABLE,15},{D3DRS_SHADEMODE,D3DSHADE_GOURAUD}})
            if(FAILED(d9->SetRenderState(s.first,s.second)))return false;
        const D3DVIEWPORT9 vp{0,0,64,64,0,1};if(FAILED(d9->SetViewport(&vp)) || FAILED(d9->Clear(0,nullptr,D3DCLEAR_TARGET,0,1,0)) || FAILED(d9->BeginScene()))return false;
        const auto drawn=d9->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,triangle.data(),sizeof(triangle[0]));const auto ended=d9->EndScene();
        if(FAILED(drawn) || FAILED(ended) || FAILED(d9->GetRenderTargetData(target9[1].Get(),cpu9[1].Get())))return false;
        D3DLOCKED_RECT lock{};if(FAILED(cpu9[1]->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
        unsigned covered=0;bool constant=true;
        for(unsigned y=0;y<64;++y)for(unsigned x=0;x<64;++x){Color value;std::memcpy(value.data(),static_cast<const char*>(lock.pBits)+y*lock.Pitch+x*16,16);
            if(value[3]==1){if(covered && value!=native)constant=false;if(!covered)native=value;++covered;}}
        const auto unlocked=cpu9[1]->UnlockRect();if(FAILED(unlocked) || !constant || covered<512)return false;
        context->UpdateSubresource(constants11.Get(),0,nullptr,input.data(),0,0);
        UINT stride=sizeof(triangle[0]),offset=0;auto* vb=vertices11.Get();auto* cb=constants11.Get();auto* so=output11.Get();
        context->IASetInputLayout(layout11.Get());context->IASetVertexBuffers(0,1,&vb,&stride,&offset);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_POINTLIST);
        context->VSSetShader(vertex11[stage].Get(),nullptr,0);context->VSSetConstantBuffers(0,1,&cb);context->GSSetShader(geometry11.Get(),nullptr,0);
        context->SOSetTargets(1,&so,&offset);context->Draw(3,0);context->SOSetTargets(0,nullptr,nullptr);context->CopyResource(read11.Get(),output11.Get());
        D3D11_MAPPED_SUBRESOURCE mapped{};if(FAILED(context->Map(read11.Get(),0,D3D11_MAP_READ,0,&mapped)))return false;
        std::array<Color,3> values;std::memcpy(values.data(),mapped.pData,48);context->Unmap(read11.Get(),0);
        candidate=values[0];return candidate==values[1] && candidate==values[2] && candidate[3]==1;
    }
    bool Fixed(HWND window,D3D9ReplaySnapshot draw,bool specular,Color& output) {
        State(draw,D3DRS_SHADEMODE,D3DSHADE_FLAT);
        if(FAILED(d9->SetVertexShader(nullptr)) || FAILED(d9->SetDepthStencilSurface(fixedDepth.Get())))return false;
        RgbaImage unused;std::vector<Color> values;const auto ps=model_batch_color::PixelStage(specular?1:0,false);
        if(!NativeImage(window,{draw},1,unused,nullptr,64,64,0,&values,&ps,d9.Get()))return false;
        unsigned covered=0;for(const auto& value:values)if(value[3]==1){if(covered && value!=output)return false;if(!covered)output=value;++covered;}
        return covered>128;
    }
};
inline D3D9ReplaySnapshot FixtureFor(const Vector& normal,float power=5) {
    auto draw=Fixture();draw.textureInfo={};draw.textureBytes={};draw.preparedMips={};
    for(unsigned v=0;v<3;++v)std::memcpy(draw.vertexBytes.data()+v*32+12,normal.data(),12);
    for(unsigned key:{D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_STENCILENABLE,D3DRS_NORMALIZENORMALS,D3DRS_COLORVERTEX,D3DRS_AMBIENT})State(draw,key,0);
    State(draw,D3DRS_LIGHTING,1);State(draw,D3DRS_SPECULARENABLE,1);State(draw,D3DRS_LOCALVIEWER,0);
    for(unsigned key:{D3DRS_DIFFUSEMATERIALSOURCE,D3DRS_AMBIENTMATERIALSOURCE,D3DRS_SPECULARMATERIALSOURCE,D3DRS_EMISSIVEMATERIALSOURCE})State(draw,key,D3DMCS_MATERIAL);
    draw.material={};draw.material.Diffuse={1,1,1,1};draw.material.Specular={1,1,1,1};draw.material.Power=power;
    D3D9ReplaySnapshot::Light light{};light.index=0;light.enabled=TRUE;light.value.Type=D3DLIGHT_DIRECTIONAL;
    light.value.Direction={0,0,1};light.value.Diffuse={1,1,1,1};light.value.Specular={1,1,1,1};draw.lights={light};
    Stage(draw,0,D3DTSS_COLOROP,D3DTOP_SELECTARG1);Stage(draw,0,D3DTSS_COLORARG1,D3DTA_DIFFUSE);
    Stage(draw,0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1);Stage(draw,0,D3DTSS_ALPHAARG1,D3DTA_DIFFUSE);return draw;
}
inline bool NormalizeFixed(HWND window,Arithmetic& gpu,const Vector& raw,Vector& output) {
    auto draw=FixtureFor(raw);State(draw,D3DRS_NORMALIZENORMALS,1);State(draw,D3DRS_SPECULARENABLE,0);
    for(unsigned c=0;c<3;++c){float values[2]{};
        for(unsigned sign=0;sign<2;++sign){draw.lights[0].value.Direction={};(&draw.lights[0].value.Direction.x)[c]=sign?1.f:-1.f;
            Color value{};if(!gpu.Fixed(window,draw,false,value))return false;values[sign]=value[0];}
        output[c]=values[0]-values[1];}
    return true;
}
inline bool LightFixed(HWND window,Arithmetic& gpu,const Vector& toward,Vector& output) {
    for(unsigned c=0;c<3;++c){float values[2]{};
        for(unsigned sign=0;sign<2;++sign){Vector normal{};normal[c]=sign?-1.f:1.f;auto draw=FixtureFor(normal);State(draw,D3DRS_SPECULARENABLE,0);
            draw.lights[0].value.Direction={-toward[0],-toward[1],-toward[2]};Color value{};if(!gpu.Fixed(window,draw,false,value))return false;values[sign]=value[0];}
        output[c]=values[0]-values[1];}
    return true;
}
inline D3D9ReplaySnapshot Rebased(const Inputs& q,float power) {
    auto draw=FixtureFor({q[1][0],q[1][1],q[1][2]},power);State(draw,D3DRS_LOCALVIEWER,1);
    for(unsigned v=0;v<3;++v){Vector p{q[0][0]+(v==2?1.f:0.f),q[0][1]+(v==1?1.f:0.f),q[0][2]};std::memcpy(draw.vertexBytes.data()+v*32,p.data(),12);}
    // Lighting uses exactly the supplied camera coordinates. Projection only
    // places the triangle on screen; it has no input to viewer computation.
    draw.projection={};draw.projection._11=draw.projection._22=1;draw.projection._41=-q[0][0]-.5f;
    draw.projection._42=-q[0][1]-.5f;draw.projection._43=.5f;draw.projection._44=1;
    draw.lights[0].value.Direction={-q[2][0],-q[2][1],-q[2][2]};return draw;
}
inline bool Capture(const D3D9ReplaySnapshot& source,unsigned stage,std::vector<Color>& values) {
    static const char* expressions[]={"float4(camera.xyz,1)","float4(normal,1)","float4(-mul(float4(lightDirection[i].xyz,0),view).xyz,1)",
        "float4(viewer,1)","float4(halfway,1)","float4(dot(normal,halfway),max(dot(normal,halfway),0),facing,1)",
        "float4(pow(max(dot(normal,halfway),0),parameters.x).xxx,1)","float4(towardLight,1)"};
    if(stage>=8)return false;auto text=model_specular_origin::Source();
    const std::string declaration="float3 specular:COLOR1;",anchor="highlight += specular.rgb*lightSpecular[i].rgb*pow(max(dot(normal,halfway),0),parameters.x);";
    auto at=text.find(declaration);if(at==std::string::npos)return false;text.insert(at+declaration.size(),"float4 probe:TEXCOORD3;");
    at=text.find(anchor);if(at==std::string::npos)return false;text.insert(at,"output.probe="+std::string(expressions[stage])+";");
    at=text.find("return output;");if(at==std::string::npos)return false;text.insert(at,"output.litDiffuse=output.probe;");
    std::vector<Color> clip;return CaptureDepthVertexShader(source,clip,nullptr,false,0,&values,&text,nullptr,false,nullptr,0,false,false,true) && values.size()==3;
}
inline int Run(HWND window,const char* archivePath,const char* destination,unsigned triangle) {
    ground_history_isolation::Archive archive;CHECK(archive.Load(archivePath,24));CHECK(triangle<archive.draws[22].count);
    const std::filesystem::path directory(destination);CHECK(!std::filesystem::exists(directory));std::filesystem::create_directories(directory);
    Arithmetic gpu;CHECK(gpu.Initialize(window,directory));
    std::ofstream inputLog(directory/"inputs.csv"),stages(directory/"arithmetic.csv"),fixed(directory/"fixed.csv"),powers(directory/"pow_scan.csv"),references(directory/"references.csv"),rebased(directory/"rebased.csv"),halfAxes(directory/"half_axes.csv"),halfScan(directory/"half_scan.csv"),halfCausal(directory/"half_causal.csv"),candidates(directory/"candidates.csv");
    inputLog<<"geometry,repeat,vertex,slot,channel,value,bits\n"<<std::setprecision(17);
    stages<<"geometry,repeat,vertex,cut,stage,channel,dx9,dx11,dx9Bits,dx11Bits\n"<<std::setprecision(17);
    fixed<<"geometry,repeat,vertex,stage,channel,native,explicit,nativeBits,explicitBits\n"<<std::setprecision(17);
    powers<<"geometry,repeat,vertex,offset,power,dot,dotBits,nativePow,dx9Pow,dx11Pow,nativeBits,dx9Bits,dx11Bits\n"<<std::setprecision(17);
    references<<"geometry,repeat,vertex,power,native,dx11,nativeBits,dx11Bits\n"<<std::setprecision(17);
    rebased<<"geometry,repeat,vertex,power,nativeRebased,dx11Full,nativeBits,dx11Bits\n"<<std::setprecision(17);
    halfAxes<<"geometry,repeat,vertex,channel,power,native,bits\n"<<std::setprecision(17);
    halfScan<<"geometry,repeat,vertex,channel,offset,power,input,inputBits,nativePow,nativeBits,matchesAxis\n"<<std::setprecision(17);
    halfCausal<<"geometry,repeat,vertex,uniqueComponents,dot,strength,nativeRebased,nativePowAtDot,dotBits,strengthBits,rebasedBits,nativePowBits\n"<<std::setprecision(17);
    candidates<<"geometry,repeat,vertex,power,cameraPolicy,native,candidate,nativeBits,candidateBits\n"<<std::setprecision(17);
    unsigned observations=0;
    auto original=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(archive.draws[22],triangle,1));
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})State(original,key,0);State(original,D3DRS_CULLMODE,D3DCULL_NONE);
    for(unsigned geometry=0;geometry<3;++geometry){auto source=geometry?model_batch_causal::Independent(original):original;
        if(geometry){for(unsigned v=0;v<3;++v){float z;std::memcpy(&z,source.vertexBytes.data()+v*32+8,4);z+=4;std::memcpy(source.vertexBytes.data()+v*32+8,&z,4);}
            source.projection._33=0;source.projection._43=.5f;}
        if(geometry==2){const Vector normals[]={{-.43f,.27f,-.81f},{.17f,-.31f,-.93f},{-.71f,.09f,-.53f}};
            for(unsigned v=0;v<3;++v)std::memcpy(source.vertexBytes.data()+v*32+12,normals[v].data(),12);source.material.Power=7.3f;}
        const std::string label=geometry==0?"saved":geometry==1?"independent":"holdout";
        const auto width=geometry?64:archive.width,height=geometry?64:archive.height;
        ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=width;pp.BackBufferHeight=height;pp.BackBufferCount=1;
        pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        ComPtr<IDirect3DDevice9> device;const auto created=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
        if(FAILED(created))std::fprintf(stderr,"specularStages native=%08lx\n",static_cast<unsigned long>(created));CHECK(SUCCEEDED(created));
        for(unsigned repeat=0;repeat<3;++repeat){std::array<std::vector<Color>,8> captured;
            for(unsigned s=0;s<8;++s)CHECK(Capture(source,s,captured[s]));
            for(float power:{1.f,2.f,5.f}){auto unit=source;unit.material.Specular={1,1,1,1};unit.material.Power=power;
                for(auto& light:unit.lights)if(light.enabled)light.value.Specular={1,1,1,1};std::vector<Color> strength;CHECK(Capture(unit,6,strength));
                std::array<std::vector<Vector>,3> candidateValues;
                for(unsigned policy=0;policy<3;++policy){const auto text=FusedSource(policy);std::vector<Color> clip;
                    CHECK(CaptureDepthVertexShader(unit,clip,nullptr,false,0,nullptr,&text,nullptr,false,nullptr,0,false,false,true,&candidateValues[policy]));CHECK(candidateValues[policy].size()==3);}
                for(unsigned v=0;v<3;++v){Color native{};unsigned covered;bool constant;CHECK(model_specular_origin::NativeFlat(window,unit,v,width,height,device.Get(),native,covered,constant));CHECK(constant);
                    references<<label<<","<<repeat<<","<<v<<","<<power<<","<<native[0]<<","<<strength[v][0]<<","<<ground_endpoint_depth::Bits(native[0])<<","<<ground_endpoint_depth::Bits(strength[v][0])<<"\n";
                    for(unsigned policy=0;policy<3;++policy)candidates<<label<<","<<repeat<<","<<v<<","<<power<<","<<policy<<","<<native[0]<<","<<candidateValues[policy][v][0]<<","<<ground_endpoint_depth::Bits(native[0])<<","<<ground_endpoint_depth::Bits(candidateValues[policy][v][0])<<"\n";}}
            for(unsigned v=0;v<3;++v){Inputs q{captured[0][v],captured[1][v],captured[2][v],captured[3][v],captured[4][v],{captured[5][v][0],source.material.Power,0,0}};
                for(unsigned s=0;s<6;++s)for(unsigned c=0;c<4;++c)inputLog<<label<<","<<repeat<<","<<v<<","<<s<<","<<c<<","<<q[s][c]<<","<<ground_endpoint_depth::Bits(q[s][c])<<"\n";
                for(unsigned s=0;s<StageCount;++s){Color a{},b{};CHECK(gpu.Observe(s,q,a,b));if(s==18)CHECK(a==q[3] && b==q[3]);
                    for(unsigned c=0;c<4;++c)stages<<label<<","<<repeat<<","<<v<<",baseline,"<<StageName(s)<<","<<c<<","<<a[c]<<","<<b[c]<<","<<ground_endpoint_depth::Bits(a[c])<<","<<ground_endpoint_depth::Bits(b[c])<<"\n";++observations;}
                Vector viewer{},half{},toward{};CHECK(NormalizeFixed(window,gpu,{-q[0][0],-q[0][1],-q[0][2]},viewer));
                Vector sum{};for(unsigned c=0;c<3;++c)sum[c]=captured[7][v][c]+q[3][c];CHECK(NormalizeFixed(window,gpu,sum,half));
                CHECK(LightFixed(window,gpu,{q[2][0],q[2][1],q[2][2]},toward));
                for(unsigned s=0;s<3;++s)for(unsigned c=0;c<3;++c){const auto native=s==2?toward[c]:s?half[c]:viewer[c],candidate=s==2?captured[7][v][c]:q[s?4:3][c];
                    fixed<<label<<","<<repeat<<","<<v<<","<<(s==2?"light_direction":s?"normalizer_half":"normalizer_viewer")<<","<<c<<","<<native<<","<<candidate<<","<<ground_endpoint_depth::Bits(native)<<","<<ground_endpoint_depth::Bits(candidate)<<"\n";}
                for(float power:{1.f,2.f,5.f}){auto fed=q;fed[5][1]=power;Color n{},a{},b{};
                    CHECK(gpu.Fixed(window,Rebased(q,power),true,n));CHECK(gpu.Observe(12,fed,a,b));
                    rebased<<label<<","<<repeat<<","<<v<<","<<power<<","<<n[0]<<","<<b[0]<<","<<ground_endpoint_depth::Bits(n[0])<<","<<ground_endpoint_depth::Bits(b[0])<<"\n";}
                for(unsigned cut=0;cut<2;++cut){auto fed=q;for(unsigned c=0;c<3;++c)fed[cut?4:3][c]=cut?half[c]:viewer[c];
                    for(unsigned s:{cut?7u:6u,cut?14u:13u}){Color a{},b{};CHECK(gpu.Observe(s,fed,a,b));
                        for(unsigned c=0;c<4;++c)stages<<label<<","<<repeat<<","<<v<<","<<(cut?"ff_normalizer_half":"ff_normalizer_viewer")<<","<<StageName(s)<<","<<c<<","<<a[c]<<","<<b[c]<<","<<ground_endpoint_depth::Bits(a[c])<<","<<ground_endpoint_depth::Bits(b[c])<<"\n";++observations;}}
                // Infer each effective half-vector component through native
                // axis responses, with independent pow calibration at three
                // exponents. Never equate a Power=1 output to a raw dot.
                auto inferred=q;unsigned unique=0;
                for(unsigned c=0;c<3;++c){std::array<Color,3> targets{};auto axis=q;axis[1]={};const float sign=q[4][c]<0?-1.f:1.f;axis[1][c]=sign;
                    unsigned k=0;for(float power:{1.f,2.f,5.f}){CHECK(gpu.Fixed(window,Rebased(axis,power),true,targets[k]));
                        halfAxes<<label<<","<<repeat<<","<<v<<","<<c<<","<<power<<","<<targets[k][0]<<","<<ground_endpoint_depth::Bits(targets[k][0])<<"\n";++k;}
                    const float magnitude=std::abs(q[4][c]);const auto center=ground_endpoint_depth::Bits(magnitude);unsigned matched=0;float inferredComponent=0;
                    for(int offset=-4;offset<=4;++offset){const auto bits=center+offset;float component;std::memcpy(&component,&bits,4);CHECK(component>0 && component<1);bool all=true;k=0;
                        for(float power:{1.f,2.f,5.f}){Color value{};CHECK(gpu.Fixed(window,FixtureFor({0,0,-component},power),true,value));const bool match=value[0]==targets[k][0];all&=match;
                            halfScan<<label<<","<<repeat<<","<<v<<","<<c<<","<<offset<<","<<power<<","<<component<<","<<bits<<","<<value[0]<<","<<ground_endpoint_depth::Bits(value[0])<<","<<match<<"\n";++k;}
                        if(all){++matched;inferredComponent=sign*component;}}
                    if(matched==1){++unique;inferred[4][c]=inferredComponent;}
                }
                if(unique==3){Color a{},dot{},strength{},n{},nativePow{};inferred[5][1]=5;
                    CHECK(gpu.Observe(7,inferred,a,dot));inferred[5][0]=dot[0];CHECK(gpu.Observe(11,inferred,a,strength));
                    CHECK(gpu.Fixed(window,Rebased(q,5),true,n));CHECK(gpu.Fixed(window,FixtureFor({0,0,-dot[0]},5),true,nativePow));
                    halfCausal<<label<<","<<repeat<<","<<v<<","<<unique<<","<<dot[0]<<","<<strength[0]<<","<<n[0]<<","<<nativePow[0]<<","<<ground_endpoint_depth::Bits(dot[0])<<","<<ground_endpoint_depth::Bits(strength[0])<<","<<ground_endpoint_depth::Bits(n[0])<<","<<ground_endpoint_depth::Bits(nativePow[0])<<"\n";
                }else halfCausal<<label<<","<<repeat<<","<<v<<","<<unique<<",0,0,0,0,0,0,0,0\n";
                // Probe a finite neighborhood of the captured dot. The same
                // input is fed to FF axis-aligned pow and explicit SM3/SM5.
                for(int offset=-4;offset<=4;++offset){auto fed=q;const auto bits=ground_endpoint_depth::Bits(q[5][0])+offset;std::memcpy(&fed[5][0],&bits,4);
                    CHECK(fed[5][0]>0 && fed[5][0]<1);
                    for(float power:{1.f,2.f,5.f}){fed[5][1]=power;auto draw=FixtureFor({0,0,-fed[5][0]},power);Color n{},a{},b{};
                        CHECK(gpu.Fixed(window,draw,true,n));CHECK(gpu.Observe(11,fed,a,b));
                        powers<<label<<","<<repeat<<","<<v<<","<<offset<<","<<power<<","<<fed[5][0]<<","<<bits<<","<<n[0]<<","<<a[0]<<","<<b[0]<<","<<ground_endpoint_depth::Bits(n[0])<<","<<ground_endpoint_depth::Bits(a[0])<<","<<ground_endpoint_depth::Bits(b[0])<<"\n";++observations;}
                }
                std::printf("specularStages geometry=%s repeat=%u vertex=%u observations=%u\n",label.c_str(),repeat,v,observations);std::fflush(stdout);
            }
        }
    }
    std::ofstream metadata(directory/"metadata.txt");metadata<<"archive="<<archivePath<<" triangle="<<triangle<<" adapter="<<gpu.adapter<<" samples=1 repeats=3 geometries=3 dx9PreRasterCapture=0 productionActivation=0 imageAcceptance=0\n";
    std::ofstream summary(directory/"summary.txt");summary<<"complete=1 observations="<<observations<<" productionActivation=0 imageAcceptance=0\n";
    for(unsigned policy=0;policy<3;++policy){std::ofstream text(directory/("candidate"+std::to_string(policy)+".hlsl"));text<<FusedSource(policy);CHECK(text);}
    CHECK(inputLog && stages && fixed && powers && references && rebased && halfAxes && halfScan && halfCausal && candidates && metadata && summary);return 0;
}
}
