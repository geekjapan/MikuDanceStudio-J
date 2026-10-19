#pragma once
#include "accessory_color_fixture.hpp"
#include "d3d11_lighting_candidate_shader.hpp"

namespace lighting_rounding_diagnostic {
using Color=accessory_color_diagnostic::Color;
inline void Change(D3D9ReplaySnapshot& source,unsigned key,DWORD value) {
    for(auto& state:source.renderStates)if(state.key==key){state.value=value;return;}
    source.renderStates.push_back({0,key,value});
}
inline D3D9ReplaySnapshot Patch(D3D9ReplaySnapshot source,const std::array<float,3>& normal,bool originalTransform=true) {
    source.viewport={0,0,64,64,0,1};source.start=0;source.minimum=0;source.count=1;source.vertices=3;source.base=source.offset=0;
    source.indexBytes={0,0,1,0,2,0};source.vertexBytes.resize(96);source.textureInfo={};source.textureBytes={};source.preparedMips={};
    // Use orthographic constant W, preserving the original normal/light matrices.
    if(!originalTransform)source.world=source.view=Fixture().world;
    source.projection={};source.projection._11=source.projection._22=originalTransform?.01f:1.f;source.projection._43=.5f;source.projection._44=1;
    const float p[][3]={{-1,-1,0},{-1,1,0},{1,-1,0}};
    for(unsigned v=0;v<3;++v){const float scale=originalTransform?6.f:.75f;const float position[]={p[v][0]*scale,p[v][1]*scale,0};
        std::memcpy(source.vertexBytes.data()+v*32,position,12);std::memcpy(source.vertexBytes.data()+v*32+12,normal.data(),12);const float uv[]={0,0};std::memcpy(source.vertexBytes.data()+v*32+24,uv,8);}
    for(unsigned key:{D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_STENCILENABLE,D3DRS_SPECULARENABLE})Change(source,key,FALSE);
    Change(source,D3DRS_CULLMODE,D3DCULL_NONE);Change(source,D3DRS_LIGHTING,TRUE);Change(source,D3DRS_AMBIENT,0);
    Change(source,D3DRS_DIFFUSEMATERIALSOURCE,D3DMCS_MATERIAL);Change(source,D3DRS_AMBIENTMATERIALSOURCE,D3DMCS_MATERIAL);
    Change(source,D3DRS_SPECULARMATERIALSOURCE,D3DMCS_MATERIAL);Change(source,D3DRS_EMISSIVEMATERIALSOURCE,D3DMCS_MATERIAL);
    Stage(source,0,D3DTSS_COLOROP,D3DTOP_DISABLE);source.material.Diffuse.a=1;source.material.Specular={};return source;
}
inline bool NativeConstant(HWND window,const D3D9ReplaySnapshot& source,Color& result) {
    RgbaImage unused;std::vector<Color> values;
    if(!NativeImage(window,{source},1,unused,nullptr,64,64,0,&values))return false;
    result=values[42*64+21];if(result[3]!=1)return false;
    unsigned covered=0;for(const auto& value:values)if(value[3]==1){if(value!=result)return false;++covered;}
    return covered>128;
}
inline std::string StageSource(unsigned stage) {
    std::string text=modelVertexSource;
    const auto normalAt=text.find("float3 normal = mul(float4(input.normal,0),normalView).xyz;");
    if(normalAt==std::string::npos)return {};
    const auto at=normalAt+std::strlen("float3 normal = mul(float4(input.normal,0),normalView).xyz;");
    text.insert(at," float3 rawNormal=normal;float3 capturedToward=0;float capturedFacing=0;float3 capturedAmbient=0,capturedDiffuseCoefficient=0,capturedDiffuseTerm=0; ");
    const auto factor=text.find("float facing=max(dot(normal,towardLight),0);");if(factor==std::string::npos)return {};
    text.insert(factor+std::strlen("float facing=max(dot(normal,towardLight),0);")," capturedToward=towardLight;capturedFacing=facing;capturedAmbient=ambient.rgb*lightAmbient[i].rgb;capturedDiffuseCoefficient=diffuse.rgb*lightDiffuse[i].rgb;capturedDiffuseTerm=diffuse.rgb*lightDiffuse[i].rgb*facing; ");
    const char* expressions[]={nullptr,"rawNormal","normal","capturedToward","capturedFacing.xxx","capturedAmbient","capturedDiffuseCoefficient","capturedDiffuseTerm","color"};
    if(stage>=9)return {};if(stage){const auto end=text.find("output.coordinate0=Coordinate");if(end==std::string::npos)return {};
        text.insert(end,std::string("output.litDiffuse=float4(")+expressions[stage]+",1); ");}
    return text;
}
inline bool CaptureStage(const D3D9ReplaySnapshot& source,unsigned stage,Color& result,bool candidate=false,const std::array<float,16>* normalMatrixOverride=nullptr) {
    auto text=StageSource(stage);if(candidate)text=lighting_shader_diagnostic::Source(text.c_str());if(text.empty())return false;std::vector<Color> positions,colors;
    if(!CaptureDepthVertexShader(source,positions,nullptr,false,0,&colors,&text,normalMatrixOverride) || colors.size()!=3 || colors[0]!=colors[1] || colors[0]!=colors[2])return false;
    result=colors[0];return true;
}

inline int Smoke(HWND window) {
    unsigned comparisons=0;
    for(unsigned normalize=0;normalize<2;++normalize){auto source=Patch(Fixture(),{0,0,normalize?-2.f:-.75f},false);
        Change(source,D3DRS_NORMALIZENORMALS,normalize?TRUE:FALSE);
        source.material.Diffuse={.073f,.21f,.37f,1};source.material.Ambient={.19f,.09f,.061f,1};source.material.Emissive={.027f,.041f,.003f,1};
        D3D9ReplaySnapshot::Light light{};light.index=0;light.enabled=TRUE;light.value.Type=D3DLIGHT_DIRECTIONAL;light.value.Direction={0,0,1};
        light.value.Diffuse={1.37f,.73f,1.13f,1};light.value.Ambient={-.17f,.23f,-.083f,1};source.lights={light};
        const float facing=normalize?1.f:.75f;
        for(unsigned repeat=0;repeat<3;++repeat){Color actual;CHECK(CaptureStage(source,0,actual,true));
            for(unsigned k=0;k<3;++k){volatile float scaled=(&source.material.Diffuse.r)[k]*facing;
                const float withEmissive=std::fma((&light.value.Diffuse.r)[k],scaled,(&source.material.Emissive.r)[k]);
                const float expected=std::fma((&source.material.Ambient.r)[k],(&light.value.Ambient.r)[k],withEmissive);
                CHECK(expected==actual[k]);++comparisons;}CHECK(actual[3]==1);
        }
        auto factor=source;factor.material={};factor.material.Diffuse={1,1,1,1};factor.lights[0].value.Diffuse={1,1,1,1};factor.lights[0].value.Ambient={};
        Color native;CHECK(NativeConstant(window,factor,native));CHECK(native==Color({facing,facing,facing,1}));
    }
    std::printf("lightingOrderSmoke gpuCpuFusedComparisons=%u repeats=3 nativeExactFactor=PASS productionActivation=0\n",comparisons);return 0;
}

inline int MatrixAxes(HWND window,const char* archivePath,const char* outputPath) {
    std::filesystem::create_directories(outputPath);D3D9ReplaySnapshot original;
    CHECK(ReadUntexturedReduction(std::filesystem::path(archivePath)/"history_replay.reduction.draw2.state",original));
    std::array<float,16> world,view;std::memcpy(world.data(),&original.world,64);std::memcpy(view.data(),&original.view,64);
    const auto roundedCombined=depth_diagnostic::Multiply(world,view,depth_diagnostic::Rounding::Sequential);
    std::array<float,16> roundedNormal,identity;const auto fixture=Fixture();std::memcpy(identity.data(),&fixture.world,64);
    CHECK(BuildShaderNormalMatrix(roundedCombined,identity,roundedNormal));
    std::ofstream output(std::filesystem::path(outputPath)/"normal_matrix_axes.csv");output<<"row,column,nativeBits,shaderBits,roundedCombinedBits,native,shader,roundedCombined\n"<<std::setprecision(17);
    unsigned exact=0;
    for(unsigned row=0;row<3;++row){std::array<float,3> normal{};normal[row]=1;auto source=Patch(original,normal);
        Change(source,D3DRS_NORMALIZENORMALS,FALSE);source.material={};source.material.Diffuse={1,1,1,1};
        for(auto& l:source.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};}
        Color shader;CHECK(CaptureStage(source,1,shader));
        ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});CHECK(AppendD3D9ReplaySnapshot(stream,source));
        const auto& matrix=stream.events.back().draw.pipeline.shader.normalView;
        for(unsigned column=0;column<3;++column)CHECK(shader[column]==matrix[row*4+column]);
        for(unsigned column=0;column<3;++column){float axisValues[2]{};
            for(unsigned sign=0;sign<2;++sign){auto probe=source;for(auto& l:probe.lights){l.value.Direction={};(&l.value.Direction.x)[column]=sign?1.f:-1.f;}
                Color native,repeated;CHECK(NativeConstant(window,probe,native));CHECK(NativeConstant(window,probe,repeated));CHECK(native==repeated);axisValues[sign]=native[0];}
            const float native=axisValues[0]-axisValues[1];const float rounded=roundedNormal[row*4+column];CHECK(native==rounded);
            output<<row<<","<<column<<","<<accessory_color_diagnostic::Bits(native)<<","<<accessory_color_diagnostic::Bits(shader[column])<<","<<accessory_color_diagnostic::Bits(rounded)<<","<<native<<","<<shader[column]<<","<<rounded<<"\n";
            exact+=native==shader[column];
        }
    }
    std::vector<std::array<float,3>> normals;
    for(unsigned v=0;v<3;++v){unsigned short index;std::memcpy(&index,original.indexBytes.data()+(original.start+197*3+v)*2,2);
        std::array<float,3> normal;std::memcpy(normal.data(),original.vertexBytes.data()+index*32+12,12);normals.push_back(normal);}
    const std::array<float,3> independent[]={{.2f,.7f,-.3f},{-.5f,.2f,-.75f},{.3f,-.8f,.4f},{1,2,-3},{-.15f,.9f,-.25f},{.9f,.1f,-.6f}};
    normals.insert(normals.end(),std::begin(independent),std::end(independent));
    std::ofstream adjusted(std::filesystem::path(outputPath)/"normal_adjusted.csv");adjusted<<"case,holdout,stage,k,bits,value\n"<<std::setprecision(17);
    for(unsigned n=0;n<normals.size();++n){auto source=Patch(original,normals[n]);for(unsigned stage:{0u,1u,2u,4u}){Color value;
        CHECK(CaptureStage(source,stage,value,true,&roundedNormal));
        for(unsigned k=0;k<4;++k)adjusted<<n<<","<<(n>=6)<<","<<stage<<","<<k<<","<<accessory_color_diagnostic::Bits(value[k])<<","<<value[k]<<"\n";}}
    std::printf("normalMatrixAxes coefficients=9 nativeShaderExact=%u roundedCombinationExact=9 nativeRepeat=EXACT samples=1\n",exact);return output && adjusted?0:1;
}

inline int Run(HWND window,const char* archivePath,const char* outputPath) {
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    D3D9ReplaySnapshot original;CHECK(ReadUntexturedReduction(std::filesystem::path(archivePath)/"history_replay.reduction.draw2.state",original));
    CHECK(original.fvf==274 && original.stride==32 && original.indexFormat==D3DFMT_INDEX16 && original.count==232 && original.start==6);
    CHECK(original.material.Specular.r==0 && original.material.Specular.g==0 && original.material.Specular.b==0);
    unsigned enabled=0;for(const auto& light:original.lights)if(light.enabled){CHECK(light.index==0 && light.value.Type==D3DLIGHT_DIRECTIONAL);++enabled;}CHECK(enabled==1);
    std::vector<std::array<float,3>> normals;
    for(unsigned v=0;v<3;++v){unsigned short index;std::memcpy(&index,original.indexBytes.data()+(original.start+197*3+v)*2,2);
        std::array<float,3> normal;std::memcpy(normal.data(),original.vertexBytes.data()+index*32+12,12);normals.push_back(normal);}
    const std::array<float,3> independent[]={{.2f,.7f,-.3f},{-.5f,.2f,-.75f},{.3f,-.8f,.4f},{1,2,-3},{-.15f,.9f,-.25f},{.9f,.1f,-.6f}};
    normals.insert(normals.end(),std::begin(independent),std::end(independent));
    std::ofstream stages(directory/"stages.csv"),probes(directory/"probes.csv");
    stages<<"case,holdout,stage,k,bits,value\n"<<std::setprecision(17);
    probes<<"case,holdout,mode,k,nativeBits,shaderBits,candidateBits,native,shader,candidate\n"<<std::setprecision(17);
    unsigned measurements=0,differences=0;
    for(unsigned n=0;n<normals.size();++n){auto source=Patch(original,normals[n]);std::array<Color,9> captured{};
        for(unsigned stage=0;stage<9;++stage){CHECK(CaptureStage(source,stage,captured[stage]));for(unsigned k=0;k<4;++k)stages<<n<<","<<(n>=6)<<","<<stage<<","<<k<<","<<accessory_color_diagnostic::Bits(captured[stage][k])<<","<<captured[stage][k]<<"\n";}
        std::vector<Color> p,c;CHECK(CaptureDepthVertexShader(source,p,nullptr,false,0,&c));CHECK(c[0]==captured[0]);
        for(unsigned mode=0;mode<20;++mode){auto probe=source;
            if(mode==1){probe.material={};probe.material.Diffuse={1,1,1,1};for(auto& l:probe.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};}}
            if(mode==2){probe.material.Ambient={};probe.material.Emissive={};}
            if(mode==3){probe.material.Diffuse={0,0,0,1};probe.material.Ambient={};}
            if(mode==4){probe.material.Diffuse={0,0,0,1};probe.material.Emissive={};for(auto& l:probe.lights){l.value.Ambient.r=-l.value.Ambient.r;l.value.Ambient.g=-l.value.Ambient.g;l.value.Ambient.b=-l.value.Ambient.b;}}
            if(mode==5)probe.material.Ambient={};
            if(mode==6)probe.material.Emissive={};
            if(mode>=7){probe.material={};probe.material.Diffuse={1,1,1,1};for(auto& l:probe.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};}
                if(mode!=13){const unsigned local=mode>=14?mode-14:mode-7;const unsigned axis=local/2;const float sign=local%2?-1.f:1.f;
                    for(auto& l:probe.lights){l.value.Direction={};(&l.value.Direction.x)[axis]=-sign;}}
                if(mode>=13)Change(probe,D3DRS_NORMALIZENORMALS,FALSE);}
            Color native,shader,candidate;CHECK(NativeConstant(window,probe,native));CHECK(CaptureStage(probe,0,shader));CHECK(CaptureStage(probe,0,candidate,true));
            Color repeated;CHECK(NativeConstant(window,probe,repeated));CHECK(native==repeated);
            for(unsigned k=0;k<4;++k){probes<<n<<","<<(n>=6)<<","<<mode<<","<<k<<","<<accessory_color_diagnostic::Bits(native[k])<<","<<accessory_color_diagnostic::Bits(shader[k])<<","<<accessory_color_diagnostic::Bits(candidate[k])<<","<<native[k]<<","<<shader[k]<<","<<candidate[k]<<"\n";
                ++measurements;differences+=native[k]!=shader[k];}
        }
    }
    std::ofstream materials(directory/"materials.csv");materials<<"case,holdout,normalize,k,diffuse,ambient,emissive,lightDiffuse,lightAmbient,nativeFactorBits,shaderFactorBits,nativeBits,shaderBits,candidateBits,native,shader,candidate\n"<<std::setprecision(17);
    const float palette[][5]={{.03125f,.125f,.0625f,3.25f,-.25f},{.073f,.19f,.027f,1.37f,-.17f},{.21f,.09f,.041f,.73f,.23f},
        {.37f,.061f,.003f,1.13f,-.083f},{.017f,.137f,.029f,7.19f,-.071f},{.29f,.41f,.13f,.91f,-.19f}};
    for(unsigned n=0;n<6;++n)for(unsigned normalize=0;normalize<2;++normalize){auto probe=Patch(original,normals[1]);
        // Identity transforms separate material order from inverse-matrix and
        // normalization errors. Exact axial normal/light give a fixed factor.
        probe.world=probe.view=Fixture().world;probe.projection=Fixture().projection;
        const float p[][3]={{-.75f,-.75f,.5f},{-.75f,.75f,.5f},{.75f,-.75f,.5f}};const float normal[]={0,0,normalize?-2.f:-.75f};
        for(unsigned v=0;v<3;++v){std::memcpy(probe.vertexBytes.data()+v*32,p[v],12);std::memcpy(probe.vertexBytes.data()+v*32+12,normal,12);}
        Change(probe,D3DRS_NORMALIZENORMALS,normalize?TRUE:FALSE);
        for(unsigned k=0;k<3;++k){const auto& a=palette[(n+k)%6];(&probe.material.Diffuse.r)[k]=a[0];(&probe.material.Ambient.r)[k]=a[1];(&probe.material.Emissive.r)[k]=a[2];
            (&probe.lights[0].value.Diffuse.r)[k]=a[3];(&probe.lights[0].value.Ambient.r)[k]=a[4];}
        probe.lights[0].value.Direction={0,0,1};auto factor=probe;factor.material={};factor.material.Diffuse={1,1,1,1};factor.lights[0].value.Diffuse={1,1,1,1};factor.lights[0].value.Ambient={};
        Color nativeFactor,shaderFactor,native,shader,candidate;CHECK(NativeConstant(window,factor,nativeFactor));CHECK(CaptureStage(factor,0,shaderFactor));
        CHECK(nativeFactor==shaderFactor && nativeFactor[0]==(normalize?1.f:.75f));
        CHECK(NativeConstant(window,probe,native));CHECK(CaptureStage(probe,0,shader));CHECK(CaptureStage(probe,0,candidate,true));
        Color repeated;CHECK(NativeConstant(window,probe,repeated));CHECK(repeated==native);
        for(unsigned k=0;k<3;++k)materials<<n<<","<<(n>=3)<<","<<normalize<<","<<k<<","<<(&probe.material.Diffuse.r)[k]<<","<<(&probe.material.Ambient.r)[k]<<","<<(&probe.material.Emissive.r)[k]<<","<<(&probe.lights[0].value.Diffuse.r)[k]<<","<<(&probe.lights[0].value.Ambient.r)[k]<<","<<accessory_color_diagnostic::Bits(nativeFactor[k])<<","<<accessory_color_diagnostic::Bits(shaderFactor[k])<<","<<accessory_color_diagnostic::Bits(native[k])<<","<<accessory_color_diagnostic::Bits(shader[k])<<","<<accessory_color_diagnostic::Bits(candidate[k])<<","<<native[k]<<","<<shader[k]<<","<<candidate[k]<<"\n";
    }
    std::ofstream lightAxes(directory/"light_axes.csv");lightAxes<<"axis,sign,nativeBits,shaderBits,native,shader\n"<<std::setprecision(17);
    for(unsigned axis=0;axis<3;++axis)for(unsigned sign=0;sign<2;++sign){std::array<float,3> normal{};normal[axis]=sign?-1.f:1.f;
        auto probe=Patch(original,normal,false);probe.view=original.view;probe.material={};probe.material.Diffuse={1,1,1,1};
        for(auto& l:probe.lights){l.value.Diffuse={1,1,1,1};l.value.Ambient={};}
        Color native,shader;CHECK(NativeConstant(window,probe,native));CHECK(CaptureStage(probe,0,shader));
        lightAxes<<axis<<","<<sign<<","<<accessory_color_diagnostic::Bits(native[0])<<","<<accessory_color_diagnostic::Bits(shader[0])<<","<<native[0]<<","<<shader[0]<<"\n";
    }
    std::ofstream inputs(directory/"inputs.json");inputs<<"{\"normals\":[";
    for(unsigned n=0;n<normals.size();++n){if(n)inputs<<",";inputs<<"["<<std::setprecision(17)<<normals[n][0]<<","<<normals[n][1]<<","<<normals[n][2]<<"]";}
    inputs<<"],\"calibrationCases\":6,\"holdoutCases\":3,\"samples\":1,\"nativeVP\":\"hardware\",\"repeats\":2}\n";
    std::printf("lightingRounding cases=%u stages=9 modes=20 measurements=%u differingChannels=%u constantW=1 repeatedNative=EXACT productionColorPreflight=EXACT\n",unsigned(normals.size()),measurements,differences);
    return stages && probes && inputs && materials && lightAxes?0:1;
}
} // namespace lighting_rounding_diagnostic
