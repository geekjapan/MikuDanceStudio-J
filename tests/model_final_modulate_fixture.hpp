#pragma once
// Generated geometry/material controls; no PMM, archived vertices or fitted
// coefficients. Both APIs consume the same independently chosen CPU inputs.
namespace model_final_modulate {
inline int Run(HWND window,const char* destination,bool smoke=false) {
    const auto output=smoke?std::filesystem::path(destination)/("run."+std::to_string(GetCurrentProcessId())):std::filesystem::path(destination);
    CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    const auto source=std::string("#define MDS_MODEL_SPECULAR 1\n#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+modelPixelSource;
    const auto generic=std::string("#define MDS_MODEL_SPECULAR 1\n")+modelPixelSource;
    std::ofstream report(output/"controls.csv");report<<"stages,pattern,material,highlight,repeat,byteDifferent,floatDifferent,genericByteDifferent,nativeG,candidateG\n"<<std::setprecision(17);
    unsigned comparisons=0,totalBytes=0,totalFloats=0,genericDifferences=0;
    for(unsigned count=0;count<=3;++count)for(unsigned pattern=0;pattern<3;++pattern)
    for(unsigned material=0;material<4;++material)for(unsigned highlight=0;highlight<4;++highlight) {
        if((count==0 && pattern) || (count==1 && pattern==2) || (highlight>=2 && material))continue;
        if(smoke && (material || !highlight))continue;
        auto c=Fixture();c.viewport={0,0,64,64,0,1};
        const float points[][3]={{-.875f,-.75f,.4f},{-.75f,.875f,.4f},{.875f,-.625f,.4f}};
        for(unsigned n=0;n<3;++n){std::memcpy(c.vertexBytes.data()+n*32,points[n],12);const float normal[]={0,0,-1};std::memcpy(c.vertexBytes.data()+n*32+12,normal,12);}
        for(unsigned key:{D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE,D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE})ground_history_isolation::State(c,key,0);
        ground_history_isolation::State(c,D3DRS_LIGHTING,highlight==3?0:1);ground_history_isolation::State(c,D3DRS_NORMALIZENORMALS,1);
        ground_history_isolation::State(c,D3DRS_SPECULARENABLE,highlight?1:0);ground_history_isolation::State(c,D3DRS_LOCALVIEWER,0);
        ground_history_isolation::State(c,D3DRS_DIFFUSEMATERIALSOURCE,D3DMCS_MATERIAL);ground_history_isolation::State(c,D3DRS_SPECULARMATERIALSOURCE,D3DMCS_MATERIAL);
        ground_history_isolation::State(c,D3DRS_AMBIENTMATERIALSOURCE,D3DMCS_MATERIAL);ground_history_isolation::State(c,D3DRS_EMISSIVEMATERIALSOURCE,D3DMCS_MATERIAL);
        c.material={};c.material.Diffuse={1,1,1,1};
        const float values[][3]={{.234567f,.578123f,.765432f},{0,1,.5f},{.99999994f,.000000119f,.812345f},{.49f,.51f,.25f}};
        c.material.Emissive={values[material][0],values[material][1],values[material][2],0};c.material.Specular={1,1,1,1};c.material.Power=5;
        D3D9ReplaySnapshot::Light light{};light.enabled=TRUE;light.value.Type=D3DLIGHT_DIRECTIONAL;light.value.Direction={0,0,1};
        light.value.Specular=highlight==2?D3DCOLORVALUE{}:D3DCOLORVALUE{.003123f,.017777f,.412345f,0};c.lights={light};
        c.textureInfo={};c.textureBytes={};c.preparedMips={};c.stageStates.clear();c.samplerStates.clear();
        for(unsigned stage=0;stage<8;++stage) {
            const auto operation=stage<count?(pattern==0?D3DTOP_MODULATE:pattern==1?D3DTOP_ADD:(stage+1==count?D3DTOP_MODULATE:D3DTOP_ADD)):D3DTOP_DISABLE;
            Stage(c,stage,D3DTSS_COLOROP,operation);Stage(c,stage,D3DTSS_ALPHAOP,D3DTOP_MODULATE);
            Stage(c,stage,D3DTSS_COLORARG1,D3DTA_TEXTURE);Stage(c,stage,D3DTSS_COLORARG2,stage?D3DTA_CURRENT:D3DTA_DIFFUSE);
            Stage(c,stage,D3DTSS_ALPHAARG1,D3DTA_TEXTURE);Stage(c,stage,D3DTSS_ALPHAARG2,D3DTA_CURRENT);Stage(c,stage,D3DTSS_RESULTARG,D3DTA_CURRENT);
            Stage(c,stage,D3DTSS_TEXCOORDINDEX,0);Stage(c,stage,D3DTSS_TEXTURETRANSFORMFLAGS,0);
            if(stage<count){c.textureInfo[stage]={true,D3DFMT_A8R8G8B8,1,1,1,0,false};
                const unsigned char colors[][4]={{97,158,34,255},{181,73,217,255},{51,249,113,255}};c.textureBytes[stage].assign(colors[stage],colors[stage]+4);
                for(auto state:Fixture().samplerStates){state.stage=stage;c.samplerStates.push_back(state);}}
        }
        RgbaImage nativeBytes,candidateBytes,genericBytes;std::vector<model_batch_color::Color> native,candidate,unused;
        CHECK(NativeImage(window,{c},1,nativeBytes,nullptr,64,64,0xffffffff,&native));
        const auto nativeFloat=native;
        CHECK(NativeImage(window,{c},1,nativeBytes,nullptr,64,64,0xffffffff));
        CHECK(model_batch_color::Stage11(c,64,64,generic,false,genericBytes,unused));
        const auto baseline=PixelDifferences(nativeBytes,genericBytes);genericDifferences+=baseline;
        for(unsigned repeat=0;repeat<3;++repeat) {
            CHECK(model_batch_color::Stage11(c,64,64,source,false,candidateBytes,candidate));
            const auto different=PixelDifferences(nativeBytes,candidateBytes);totalBytes+=different;
            CHECK(model_batch_color::Stage11(c,64,64,source,true,candidateBytes,candidate));unsigned floatDifferent=0;
            for(std::size_t n=0;n<candidate.size();++n)floatDifferent+=nativeFloat[n]!=candidate[n];totalFloats+=floatDifferent;
            const auto focus=32*64+24;report<<count<<","<<pattern<<","<<material<<","<<highlight<<","<<repeat<<","<<different<<","<<floatDifferent<<","<<baseline<<","<<nativeFloat[focus][1]<<","<<candidate[focus][1]<<"\n";report.flush();++comparisons;
        }
    }
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 comparisons="<<comparisons<<" byteDifferences="<<totalBytes<<" floatDifferences="<<totalFloats<<" genericByteDifferences="<<genericDifferences<<" productionActivation=0\n";CHECK(summary && report);
    std::printf("finalModulate comparisons=%u bytes=%u floats=%u genericBytes=%u\n",comparisons,totalBytes,totalFloats,genericDifferences);return totalBytes || totalFloats?1:0;
}
}
