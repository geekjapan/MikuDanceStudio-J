#pragma once
#include "lighting_rounding_fixture.hpp"
#include "d3d11_normal_candidate_shader.hpp"

namespace normal_precision_diagnostic {
using Color=lighting_rounding_diagnostic::Color;
using Matrix=depth_diagnostic::Matrix;
inline std::string Source(unsigned policy,unsigned stage) {
    if(policy>5 || stage>6)return {};
    std::string text=lighting_rounding_diagnostic::StageSource(0);
    const char* raw="float3 normal = mul(float4(input.normal,0),normalView).xyz;";
    const auto at=text.find(raw);if(at==std::string::npos)return {};
    if(policy)text.replace(at,std::strlen(raw),"float3 normal=NormalFusedTransform(input.normal,normalView);");
    const char* normalize="if(flags.y) normal=normalize(normal);";const auto n=text.find(normalize);if(n==std::string::npos)return {};
    const std::string length=policy>=3?"NormalFusedDot(normal,normal)":"dot(normal,normal)";
    const std::string reciprocal=policy==4?"NormalRefinedRsqrt(observedLength)":policy==5?"1.0/sqrt(observedLength)":"rsqrt(observedLength)";
    std::string replacement="float observedLength="+length+";float observedReciprocal="+reciprocal+"; ";
    replacement+=policy<2?"if(flags.y) normal=normalize(normal);":"if(flags.y) normal=normal*observedReciprocal;";
    text.replace(n,std::strlen(normalize),replacement);
    const char* expressions[]={"rawNormal","normal","observedLength.xxx","observedReciprocal.xxx","capturedToward","capturedFacing.xxx","color"};
    const auto out=text.find("output.coordinate0=Coordinate");if(out==std::string::npos)return {};
    text.insert(out,std::string("output.litDiffuse=float4(")+expressions[stage]+",1);");
    return normal_shader_diagnostic::Functions()+R"(
float NormalRefinedRsqrt(float length) {
    precise double x=double(rsqrt(length));precise double square=x*x;
    precise double scaled=double(length)*square;precise double error=1.0-scaled;
    precise double half=0.5*x;precise double correction=half*error;
    precise double refined=x+correction;return float(refined);
}
)"+text;
}

// Reusable hardware device. All probe draws have a constant normal and W;
// each readback must be spatially constant on every covered pixel.
class NativeRenderer {
    ComPtr<IDirect3D9> api;
    ComPtr<IDirect3DDevice9> device;
    ComPtr<IDirect3DSurface9> target,cpu;
    std::array<ComPtr<IDirect3DVertexShader9>,5> shaders;
    ComPtr<IDirect3DPixelShader9> pixel;
    bool Read(Color& result) {
        if(FAILED(device->GetRenderTargetData(target.Get(),cpu.Get())))return false;
        D3DLOCKED_RECT lock{};if(FAILED(cpu->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
        std::memcpy(result.data(),static_cast<const char*>(lock.pBits)+42*lock.Pitch+21*16,16);
        unsigned covered=0;bool valid=result[3]==1;
        for(unsigned y=0;y<64;++y)for(unsigned x=0;x<64;++x){Color p;std::memcpy(p.data(),static_cast<const char*>(lock.pBits)+y*lock.Pitch+x*16,16);
            if(p[3]==1){++covered;valid&=p==result;}}
        const auto unlocked=cpu->UnlockRect();return valid && covered>128 && SUCCEEDED(unlocked);
    }
    bool Draw(const D3D9ReplaySnapshot& source,Color& output) {
        if(source.vertexBytes.size()<96 || FAILED(device->Clear(0,nullptr,D3DCLEAR_TARGET,0,1,0)) || FAILED(device->BeginScene()))return false;
        const auto drawn=device->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,source.vertexBytes.data(),32);const auto ended=device->EndScene();
        return SUCCEEDED(drawn) && SUCCEEDED(ended) && Read(output);
    }
    bool StableDraw(const D3D9ReplaySnapshot& source,Color& output) {
        if(!Draw(source,output))return false;
        for(unsigned repeat=0;repeat<2;++repeat){Color observed;if(!Draw(source,observed) || observed!=output)return false;}
        return true;
    }
public:
    bool Initialize(HWND window,const std::filesystem::path& directory) {
        api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return false;
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=64;
        pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;
        const auto created=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
        if(FAILED(created)){std::fprintf(stderr,"normalPrecision DX9 creation=%08lx\n",static_cast<unsigned long>(created));return false;}
        D3DADAPTER_IDENTIFIER9 adapter{};if(FAILED(api->GetAdapterIdentifier(0,0,&adapter)))return false;
        std::printf("normalPrecisionDevice adapter=%s hardwareVP=1 sampleCount=1 target=RGBA32F\n",adapter.Description);
        if(FAILED(device->CreateRenderTarget(64,64,D3DFMT_A32B32G32R32F,D3DMULTISAMPLE_NONE,0,FALSE,&target,nullptr)) ||
           FAILED(device->CreateOffscreenPlainSurface(64,64,D3DFMT_A32B32G32R32F,D3DPOOL_SYSTEMMEM,&cpu,nullptr)) ||
           FAILED(device->SetRenderTarget(0,target.Get())) || FAILED(device->SetDepthStencilSurface(nullptr)))return false;
        const D3DVIEWPORT9 viewport{0,0,64,64,0,1};if(FAILED(device->SetViewport(&viewport)))return false;
        for(auto s:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,FALSE},{D3DRS_ZWRITEENABLE,FALSE},{D3DRS_ALPHABLENDENABLE,FALSE},
            {D3DRS_ALPHATESTENABLE,FALSE},{D3DRS_STENCILENABLE,FALSE},{D3DRS_SPECULARENABLE,FALSE},{D3DRS_SCISSORTESTENABLE,FALSE},
            {D3DRS_SRGBWRITEENABLE,FALSE},{D3DRS_DITHERENABLE,FALSE},{D3DRS_FOGENABLE,FALSE},{D3DRS_CULLMODE,D3DCULL_NONE},
            {D3DRS_LIGHTING,TRUE},{D3DRS_AMBIENT,0},{D3DRS_COLORWRITEENABLE,15},{D3DRS_FILLMODE,D3DFILL_SOLID},{D3DRS_SHADEMODE,D3DSHADE_GOURAUD},
            {D3DRS_DIFFUSEMATERIALSOURCE,D3DMCS_MATERIAL},{D3DRS_AMBIENTMATERIALSOURCE,D3DMCS_MATERIAL},
            {D3DRS_SPECULARMATERIALSOURCE,D3DMCS_MATERIAL},{D3DRS_EMISSIVEMATERIALSOURCE,D3DMCS_MATERIAL}})if(FAILED(device->SetRenderState(s.first,s.second)))return false;
        for(auto s:{std::pair<D3DTEXTURESTAGESTATETYPE,DWORD>{D3DTSS_COLOROP,D3DTOP_SELECTARG1},{D3DTSS_COLORARG1,D3DTA_DIFFUSE},
            {D3DTSS_ALPHAOP,D3DTOP_SELECTARG1},{D3DTSS_ALPHAARG1,D3DTA_DIFFUSE}})if(FAILED(device->SetTextureStageState(0,s.first,s.second)))return false;
        if(FAILED(device->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE)))return false;
        auto compile=[](const std::string& source,const char* profile,ComPtr<ID3DBlob>& code){ComPtr<ID3DBlob> error;
            const auto hr=D3DCompile(source.data(),source.size(),nullptr,nullptr,nullptr,"main",profile,D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error);
            if(FAILED(hr) && error)std::fprintf(stderr,"normalPrecisionShader %s\n",static_cast<const char*>(error->GetBufferPointer()));return SUCCEEDED(hr);};
        ComPtr<ID3DBlob> ps;if(!compile("float4 main(float4 value:TEXCOORD0):COLOR0{return value;}","ps_3_0",ps) || FAILED(device->CreatePixelShader(static_cast<const DWORD*>(ps->GetBufferPointer()),&pixel)))return false;
        const char* expressions[]={"raw","length.xxx","inverse.xxx","normalized","max(dot(normalized,toward.xyz),0).xxx"};
        for(unsigned stage=0;stage<5;++stage){const std::string text=std::string(R"(
float4 a:register(c0),b:register(c1),c:register(c2),toward:register(c3);
struct O{float4 p:POSITION;float4 value:TEXCOORD0;};
O main(float3 p:POSITION,float3 n:NORMAL){O o;o.p=float4(p.xy/8,.5,1);
float3 raw=float3(dot(n,a.xyz),dot(n,b.xyz),dot(n,c.xyz));
float length=dot(raw,raw);float inverse=rsqrt(length);float3 normalized=raw*inverse;
o.value=float4()")+expressions[stage]+",1);return o;}";
            ComPtr<ID3DBlob> code,listing;if(!compile(text,"vs_3_0",code) || FAILED(device->CreateVertexShader(static_cast<const DWORD*>(code->GetBufferPointer()),&shaders[stage])) ||
                FAILED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)))return false;
            std::ofstream file(directory/("native-stage"+std::to_string(stage)+".asm"));file.write(static_cast<const char*>(listing->GetBufferPointer()),listing->GetBufferSize());if(!file)return false;
        }
        return true;
    }
    bool Fixed(const D3D9ReplaySnapshot& source,Color& output) {
        if(FAILED(device->SetVertexShader(nullptr)) || FAILED(device->SetPixelShader(nullptr)) || FAILED(device->SetFVF(source.fvf)) ||
           FAILED(device->SetTransform(D3DTS_WORLD,&source.world)) || FAILED(device->SetTransform(D3DTS_VIEW,&source.view)) ||
           FAILED(device->SetTransform(D3DTS_PROJECTION,&source.projection)) || FAILED(device->SetMaterial(&source.material)))return false;
        for(const auto& s:source.renderStates)if(s.key==D3DRS_NORMALIZENORMALS && FAILED(device->SetRenderState(D3DRS_NORMALIZENORMALS,s.value)))return false;
        for(unsigned i=0;i<8;++i)if(FAILED(device->LightEnable(i,FALSE)))return false;
        for(const auto& l:source.lights)if(FAILED(device->SetLight(l.index,&l.value)) || FAILED(device->LightEnable(l.index,l.enabled)))return false;
        return StableDraw(source,output);
    }
    bool Explicit(const D3D9ReplaySnapshot& source,const Matrix& matrix,const Color& toward,unsigned stage,Color& output) {
        if(stage>=5)return false;std::array<Color,4> constants{};
        for(unsigned column=0;column<3;++column)for(unsigned row=0;row<3;++row)constants[column][row]=matrix[row*4+column];constants[3]=toward;
        if(FAILED(device->SetFVF(source.fvf)) || FAILED(device->SetVertexShader(shaders[stage].Get())) || FAILED(device->SetPixelShader(pixel.Get())) ||
           FAILED(device->SetVertexShaderConstantF(0,constants[0].data(),4)))return false;
        return StableDraw(source,output);
    }
};

inline int Smoke(HWND window,const char* outputPath) {
    using namespace lighting_rounding_diagnostic;
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    NativeRenderer native;CHECK(native.Initialize(window,directory));
    const Matrix matrix{.099997714161872864f,-.0000016260775055343402f,-.00067789200693368912f,0,
        -.000000000000074162742190898162f,.099999718368053436f,-.00023987193708308041f,0,
        .00067789404420182109f,.00023986643645912409f,.099997416138648987f,0,0,0,0,1};
    const std::array<float,3> normals[]={{.13f,.37f,-.91f},{-.83f,.11f,-.47f},{.007f,-.015f,.019f},{.25f,1.75f,-2.5f},{-1.33f,-.27f,.51f},{.61f,.73f,-.89f}};
    auto batch=Patch(Fixture(),normals[0]);Change(batch,D3DRS_NORMALIZENORMALS,TRUE);batch.vertices=6;batch.vertexBytes.resize(6*32);
    std::array<Color,6> expectedRaw{},nativeNormalized{};const Color toward{0,0,-1,1};
    for(unsigned n=0;n<6;++n){auto source=Patch(Fixture(),normals[n]);std::memcpy(batch.vertexBytes.data()+n*32,source.vertexBytes.data(),32);
        expectedRaw[n][3]=1;const float vector[]={normals[n][0],normals[n][1],normals[n][2],0};
        for(unsigned k=0;k<3;++k){const float column[]={matrix[k],matrix[4+k],matrix[8+k],0};expectedRaw[n][k]=depth_diagnostic::Dot(vector,column,depth_diagnostic::Rounding::Fused);}
        Color observed;CHECK(native.Explicit(source,matrix,toward,0,observed));CHECK(observed==expectedRaw[n]);
        CHECK(native.Explicit(source,matrix,toward,3,nativeNormalized[n]));
    }
    unsigned compared=0;
    for(unsigned repeat=0;repeat<3;++repeat){std::array<std::vector<Color>,4> stages;
        for(unsigned stage=0;stage<4;++stage){auto shader=Source(3,stage);std::vector<Color> positions;
            CHECK(CaptureDepthVertexShader(batch,positions,nullptr,false,0,&stages[stage],&shader,&matrix));CHECK(stages[stage].size()==6);}
        for(unsigned n=0;n<6;++n){CHECK(stages[0][n]==expectedRaw[n]);CHECK(stages[1][n]==nativeNormalized[n]);
            const float raw[]={expectedRaw[n][0],expectedRaw[n][1],expectedRaw[n][2],0};
            const float length=depth_diagnostic::Dot(raw,raw,depth_diagnostic::Rounding::Fused);CHECK(stages[2][n][0]==length);
            for(unsigned k=0;k<3;++k){volatile float normalized=raw[k]*stages[3][n][0];CHECK(normalized==stages[1][n][k]);++compared;}
        }
    }
    std::printf("normalPrecisionSmoke normals=6 repeats=3 fusedCpuRaw=EXACT nativeNormalized=EXACT length=EXACT multiplyComparisons=%u productionActivation=0\n",compared);return 0;
}

inline int Run(HWND window,const char* archivePath,const char* outputPath) {
    using namespace lighting_rounding_diagnostic;
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    D3D9ReplaySnapshot original;CHECK(ReadUntexturedReduction(std::filesystem::path(archivePath)/"history_replay.reduction.draw2.state",original));
    CHECK(original.fvf==274 && original.count==232 && original.start==6 && original.indexFormat==D3DFMT_INDEX16 && original.stride==32);
    Matrix world,view,identity,normalMatrix;std::memcpy(world.data(),&original.world,64);std::memcpy(view.data(),&original.view,64);const auto fixture=Fixture();std::memcpy(identity.data(),&fixture.world,64);
    const auto combined=depth_diagnostic::Multiply(world,view,depth_diagnostic::Rounding::Sequential);CHECK(BuildShaderNormalMatrix(combined,identity,normalMatrix));
    std::vector<std::array<float,3>> normals;for(unsigned v=0;v<3;++v){unsigned short i;std::memcpy(&i,original.indexBytes.data()+(original.start+197*3+v)*2,2);
        std::array<float,3> n;std::memcpy(n.data(),original.vertexBytes.data()+i*32+12,12);normals.push_back(n);}
    const std::array<float,3> independent[]={{.2f,.7f,-.3f},{-.5f,.2f,-.75f},{.3f,-.8f,.4f},{1,2,-3},{-.15f,.9f,-.25f},{.9f,.1f,-.6f},
        {.13f,.37f,-.91f},{-.83f,.11f,-.47f},{.007f,-.015f,.019f},{.25f,1.75f,-2.5f},{-1.33f,-.27f,.51f},{.61f,.73f,-.89f}};
    normals.insert(normals.end(),std::begin(independent),std::end(independent));
    NativeRenderer native;CHECK(native.Initialize(window,directory));
    auto originalPatch=Patch(original,normals[0]);Color toward;CHECK(CaptureStage(originalPatch,3,toward,false,&normalMatrix));
    std::ofstream matrix(directory/"matrix.csv");matrix<<"row,column,bits,value\n"<<std::setprecision(17);
    // Re-observe all coefficients before collecting dot/normalization results.
    for(unsigned row=0;row<3;++row){std::array<float,3> axis{};axis[row]=1;auto source=Patch(original,axis);source.material={};source.material.Diffuse={1,1,1,1};Change(source,D3DRS_NORMALIZENORMALS,FALSE);
        for(unsigned col=0;col<3;++col){Color values[2];for(unsigned sign=0;sign<2;++sign){for(auto& l:source.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};l.value.Direction={};(&l.value.Direction.x)[col]=sign?1.f:-1.f;}CHECK(native.Fixed(source,values[sign]));}
            const float observed=values[0][0]-values[1][0];CHECK(observed==normalMatrix[row*4+col]);matrix<<row<<","<<col<<","<<accessory_color_diagnostic::Bits(observed)<<","<<observed<<"\n";}}
    std::ofstream fixed(directory/"fixed.csv"),explicitLog(directory/"native_explicit.csv"),gpu(directory/"gpu.csv"),inputs(directory/"inputs.csv");
    fixed<<"case,holdout,stage,k,bits,value\n"<<std::setprecision(17);explicitLog<<"case,holdout,stage,k,bits,value\n"<<std::setprecision(17);
    gpu<<"case,holdout,policy,stage,k,bits,value\n"<<std::setprecision(17);inputs<<"case,holdout,k,bits,value\n"<<std::setprecision(17);
    auto log=[&](std::ofstream& file,unsigned n,unsigned stage,const Color& value){for(unsigned k=0;k<4;++k)file<<n<<","<<(n>=6)<<","<<stage<<","<<k<<","<<accessory_color_diagnostic::Bits(value[k])<<","<<value[k]<<"\n";};
    std::vector<Color> rawObservations;
    for(unsigned n=0;n<normals.size();++n){auto source=Patch(original,normals[n]);
        for(unsigned k=0;k<3;++k)inputs<<n<<","<<(n>=6)<<","<<k<<","<<accessory_color_diagnostic::Bits(normals[n][k])<<","<<normals[n][k]<<"\n";
        for(unsigned stage=0;stage<3;++stage){Color value{0,0,0,1};
            if(stage<2){Change(source,D3DRS_NORMALIZENORMALS,stage?TRUE:FALSE);source.material={};source.material.Diffuse={1,1,1,1};
                for(unsigned k=0;k<3;++k){float component[2];for(unsigned sign=0;sign<2;++sign){for(auto& l:source.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};l.value.Direction={};(&l.value.Direction.x)[k]=sign?1.f:-1.f;}
                    Color baseline;CHECK(native.Fixed(source,baseline));component[sign]=baseline[0];}value[k]=component[0]-component[1];}}
            else{source=Patch(original,normals[n]);source.material={};source.material.Diffuse={1,1,1,1};for(auto& l:source.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};}
                CHECK(native.Fixed(source,value));}
            log(fixed,n,stage,value);
        }
        source=Patch(original,normals[n]);for(unsigned stage=0;stage<5;++stage){Color value;CHECK(native.Explicit(source,normalMatrix,toward,stage,value));
            if(!stage)rawObservations.push_back(value);
            log(explicitLog,n,stage,value);}
    }
    // Bypass transformation with exactly the raw float bytes observed above.
    // Both APIs normalize the same input; native fixed-function signed-axis
    // responses independently check the programmable normalized output.
    std::ofstream shared(directory/"shared_raw.csv");shared<<"case,holdout,path,stage,k,bits,value\n"<<std::setprecision(17);
    auto sharedLog=[&](unsigned n,unsigned path,unsigned stage,const Color& value){for(unsigned k=0;k<4;++k)shared<<n<<","<<(n>=6)<<","<<path<<","<<stage<<","<<k<<","<<accessory_color_diagnostic::Bits(value[k])<<","<<value[k]<<"\n";};
    auto sharedBatch=Patch(original,{0,0,1});sharedBatch.world=sharedBatch.view=fixture.world;sharedBatch.vertices=static_cast<UINT>(normals.size());sharedBatch.vertexBytes.resize(normals.size()*32);
    for(unsigned n=0;n<normals.size();++n){const std::array<float,3> raw{rawObservations[n][0],rawObservations[n][1],rawObservations[n][2]};auto source=Patch(original,raw);source.world=source.view=fixture.world;
        source.projection._11=source.projection._22=.1f;std::memcpy(sharedBatch.vertexBytes.data()+n*32,source.vertexBytes.data(),32);
        for(unsigned stage=0;stage<5;++stage){Color value;CHECK(native.Explicit(source,identity,toward,stage,value));sharedLog(n,0,stage,value);}
        Color normalized{0,0,0,1};source.material={};source.material.Diffuse={1,1,1,1};
        for(unsigned k=0;k<3;++k){float components[2];for(unsigned sign=0;sign<2;++sign){for(auto& l:source.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};l.value.Direction={};(&l.value.Direction.x)[k]=sign?1.f:-1.f;}
            Color result;CHECK(native.Fixed(source,result));components[sign]=result[0];}normalized[k]=components[0]-components[1];}sharedLog(n,2,1,normalized);
    }
    for(unsigned stage=0;stage<4;++stage){const unsigned mappedStage[]={0,2,3,1};auto shader=Source(3,mappedStage[stage]);std::vector<Color> positions,values;
        CHECK(CaptureDepthVertexShader(sharedBatch,positions,nullptr,false,0,&values,&shader,&identity));CHECK(values.size()==normals.size());
        std::vector<Color> repeated;CHECK(CaptureDepthVertexShader(sharedBatch,positions,nullptr,false,0,&repeated,&shader,&identity));CHECK(repeated==values);
        for(unsigned n=0;n<normals.size();++n)sharedLog(n,1,stage,values[n]);}
    // Batch independent normals into one SO draw per shader; no raster
    // interpolation participates in the DX11 stage observations.
    auto batch=Patch(original,normals[0]);batch.vertices=static_cast<UINT>(normals.size());batch.vertexBytes.resize(normals.size()*32);
    for(unsigned n=0;n<normals.size();++n){const auto source=Patch(original,normals[n]);std::memcpy(batch.vertexBytes.data()+n*32,source.vertexBytes.data(),32);}
    for(unsigned policy=0;policy<=5;++policy)for(unsigned stage=0;stage<=6;++stage){auto shader=Source(policy,stage);CHECK(!shader.empty());std::vector<Color> positions,colors;
        if(stage==1){ComPtr<ID3DBlob> code,error,listing;CHECK(SUCCEEDED(D3DCompile(shader.data(),shader.size(),nullptr,nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error)));
            CHECK(SUCCEEDED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)));
            std::ofstream file(directory/("dx11-policy"+std::to_string(policy)+".asm"));file.write(static_cast<const char*>(listing->GetBufferPointer()),listing->GetBufferSize());CHECK(file);}
        CHECK(CaptureDepthVertexShader(batch,positions,nullptr,false,0,&colors,&shader,&normalMatrix));CHECK(colors.size()==normals.size());
        std::vector<Color> repeated;CHECK(CaptureDepthVertexShader(batch,positions,nullptr,false,0,&repeated,&shader,&normalMatrix));CHECK(repeated==colors);
        for(unsigned n=0;n<normals.size();++n)for(unsigned k=0;k<4;++k)gpu<<n<<","<<(n>=6)<<","<<policy<<","<<stage<<","<<k<<","<<accessory_color_diagnostic::Bits(colors[n][k])<<","<<colors[n][k]<<"\n";
    }
    auto lightPatch=Patch(original,{0,0,1},false);lightPatch.view=original.view;lightPatch.material={};lightPatch.material.Diffuse={1,1,1,1};
    std::ofstream light(directory/"toward.csv");light<<"k,nativeBits,explicitInputBits,native,explicitInput\n"<<std::setprecision(17);
    for(unsigned k=0;k<3;++k){float axis[2];for(unsigned sign=0;sign<2;++sign){const std::array<float,3> n={k==0?(sign?-1.f:1.f):0,k==1?(sign?-1.f:1.f):0,k==2?(sign?-1.f:1.f):0};
            lightPatch=Patch(original,n,false);lightPatch.view=original.view;lightPatch.material={};lightPatch.material.Diffuse={1,1,1,1};for(auto& l:lightPatch.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};}
            Color result;CHECK(native.Fixed(lightPatch,result));axis[sign]=result[0];}
        const float observed=axis[0]-axis[1];light<<k<<","<<accessory_color_diagnostic::Bits(observed)<<","<<accessory_color_diagnostic::Bits(toward[k])<<","<<observed<<","<<toward[k]<<"\n";}
    std::printf("normalPrecision cases=%u holdout=%u fixedStages=3 nativeExplicitStages=5 dx11Policies=6 dx11Stages=7 matrixCoefficients=EXACT repeats=EXACT productionActivation=0\n",unsigned(normals.size()),unsigned(normals.size()-6));
    std::ofstream manifest(directory/"manifest.json");manifest<<"{\"cases\":15,\"holdoutCases\":9,\"samples\":1,\"nativeHardwareVP\":true,\"nativeSpatialConstant\":true,\"nativeRepeats\":3,\"gpuRepeats\":2,\"matrixPreflight\":true,\"productionActivation\":false}\n";
    return matrix && fixed && explicitLog && gpu && inputs && light && shared && manifest?0:1;
}
} // namespace normal_precision_diagnostic
