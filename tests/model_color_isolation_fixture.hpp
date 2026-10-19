#pragma once
// Real material diagnostics. Altered controls are never an image acceptance gate.
namespace model_color_isolation {
using ground_history_isolation::State;
using ground_history_isolation::Triangles;
using ground_history_isolation::CompactTriangle;
struct Probe {
    HWND window; ground_history_isolation::Archive& archive; D3D11Bundle bundle;
    std::filesystem::path output; std::ofstream report,pixels;
    std::vector<unsigned char> native,candidate;
    std::vector<unsigned> focus;
    unsigned comparisons=0;
    bool Initialize() {
        if(std::filesystem::exists(output))return false;
        std::filesystem::create_directories(output);
        SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
        bundle=CreateD3D11ViewportCenterCandidateDevice(desc,D3D11Driver::Hardware);if(!bundle)return false;
        report.open(output/"controls.csv");pixels.open(output/"pixels.csv");
        report<<"mode,firstTriangle,triangles,differentPixels,maxDelta,focusMask,nativeHash,candidateHash\n";
        pixels<<"mode,x,y,nB,nG,nR,nA,cB,cG,cR,cA\n";
        std::ofstream metadata(output/"mode.txt");metadata<<"center=viewport shaderShift=0 viewportShiftX=0.5 viewportShiftY=0.5 samples=1 productionActivation=0 adapter="<<bundle.adapterName<<"\n";
        return report && pixels && metadata;
    }
    bool Render(const std::string& name,const D3D9ReplaySnapshot& c,unsigned first=0) {
        ModelReplayStream stream;stream.target.width=archive.width;stream.target.height=archive.height;
        const auto clear=archive.clear;stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};
        const auto& r=archive.region;stream.initializedRegion=ModelViewport{r.X,r.Y,r.Width,r.Height,r.MinZ,r.MaxZ};stream.events.push_back({1,ModelReplayOp::Clear});
        const auto converted=AppendD3D9ReplaySnapshot(stream,c,true);
        if(!converted){std::fprintf(stderr,"modelColor blocked mode=%s reason=%s\n",name.c_str(),converted.reason.c_str());return false;}stream.complete=true;
        RgbaImage a,b;
        if(!NativeImage(window,{c},1,a,nullptr,archive.width,archive.height,clear) || !ReplayD3D11WCandidatePrefix(*bundle.device,stream,1,b))return false;
        native=scene_prefix_diagnostic::Crop(a,r);candidate=scene_prefix_diagnostic::Crop(b,r);
        if(native.size()!=candidate.size() || native.empty())return false;
        unsigned different=0,maximum=0;
        for(unsigned p=0;p<native.size()/4;++p){unsigned delta=0;
            for(unsigned k=0;k<4;++k)delta=(std::max)(delta,unsigned(std::abs(int(native[p*4+k])-candidate[p*4+k])));
            if(delta){++different;if(name=="original")focus.push_back(p);}maximum=(std::max)(maximum,delta);
        }
        if(focus.size()>31)return false;
        report<<name<<","<<first<<","<<c.count<<","<<different<<","<<maximum<<","<<Mask()<<","<<scene_prefix_diagnostic::Hash(native)<<","<<scene_prefix_diagnostic::Hash(candidate)<<"\n";report.flush();
        for(unsigned p:focus){pixels<<name<<","<<r.X+p%r.Width<<","<<r.Y+p/r.Width;
            for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(native[p*4+k]);for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(candidate[p*4+k]);pixels<<"\n";}pixels.flush();
        for(unsigned path=0;path<2;++path){const auto& bytes=path?candidate:native;std::ofstream image(output/(name+(path?".candidate.bgra":".native.bgra")),std::ios::binary);image.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());if(!image)return false;}
        std::printf("modelColor mode=%s triangles=%u first=%u differentPixels=%u maxDelta=%u focusMask=%u\n",name.c_str(),c.count,first,different,maximum,Mask());std::fflush(stdout);
        ++comparisons;return true;
    }
    unsigned Mask() const {unsigned mask=0;for(unsigned n=0;n<focus.size();++n)if(std::memcmp(native.data()+focus[n]*4,candidate.data()+focus[n]*4,4))mask|=1u<<n;return mask;}
};
inline void Sampler(D3D9ReplaySnapshot& c,unsigned stage,unsigned key,DWORD value) {
    for(auto& state:c.samplerStates)if(state.stage==stage && state.key==key){state.value=value;return;}
    c.samplerStates.push_back({stage,key,value});
}
inline void White(D3D9ReplaySnapshot& c,unsigned stage) {
    c.textureInfo[stage]={true,D3DFMT_A8R8G8B8,1,1,1,0,false,D3DTEXF_LINEAR};c.textureBytes[stage]={255,255,255,255};c.preparedMips[stage]={};
}
inline bool FreezeMips(D3D9ReplaySnapshot& c,unsigned stage) {
    if(!c.textureInfo[stage].autogen)return true;
    const auto data=c.preparedMips[stage];if(data.levels.empty() || data.generateMips || data.srgb)return false;
    c.textureInfo[stage].autogen=false;c.textureInfo[stage].levels=static_cast<unsigned>(data.levels.size());c.textureBytes[stage].clear();
    for(const auto& level:data.levels)for(std::size_t i=0;i<level.pixels.size();i+=4)
        c.textureBytes[stage].insert(c.textureBytes[stage].end(),{level.pixels[i+2],level.pixels[i+1],level.pixels[i],level.pixels[i+3]});
    c.preparedMips[stage]={};return true;
}
inline D3D9ReplaySnapshot Control(D3D9ReplaySnapshot c,unsigned mode) {
    if(mode==1)State(c,D3DRS_ALPHABLENDENABLE,0);
    if(mode==2)State(c,D3DRS_ALPHATESTENABLE,0);
    if(mode==3){State(c,D3DRS_ZENABLE,0);State(c,D3DRS_ZWRITEENABLE,0);State(c,D3DRS_STENCILENABLE,0);}
    if(mode==4)State(c,D3DRS_SPECULARENABLE,0);
    if(mode==5)State(c,D3DRS_LIGHTING,0);
    if(mode==6)State(c,D3DRS_NORMALIZENORMALS,0);
    if(mode==7)Stage(c,1,D3DTSS_COLOROP,D3DTOP_DISABLE); // Toon only.
    if(mode==8){ // Sphere promoted to logical stage zero, including immutable mip bytes.
        c.textureInfo[0]=c.textureInfo[1];c.textureBytes[0]=c.textureBytes[1];c.preparedMips[0]=c.preparedMips[1];c.textureMatrices[0]=c.textureMatrices[1];
        for(auto& s:c.stageStates)if(s.stage==0){for(const auto& t:c.stageStates)if(t.stage==1 && t.key==s.key){s.value=t.value;break;}}
        Stage(c,0,D3DTSS_COLORARG2,D3DTA_DIFFUSE);
        for(auto& s:c.samplerStates)if(s.stage==0){for(const auto& t:c.samplerStates)if(t.stage==1 && t.key==s.key){s.value=t.value;break;}}
        Stage(c,1,D3DTSS_COLOROP,D3DTOP_DISABLE);
    }
    if(mode==9)Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);
    if(mode==10 || mode==12)White(c,0);
    if(mode==11 || mode==12)White(c,1);
    if(mode>=13 && mode<=15)for(unsigned s=0;s<2;++s){Sampler(c,s,D3DSAMP_MINFILTER,mode==13?D3DTEXF_POINT:D3DTEXF_LINEAR);Sampler(c,s,D3DSAMP_MAGFILTER,mode==13?D3DTEXF_POINT:D3DTEXF_LINEAR);Sampler(c,s,D3DSAMP_MIPFILTER,mode==15?D3DTEXF_LINEAR:D3DTEXF_POINT);}
    return c;
}
inline int Run(HWND window,const char* root,const char* reference,const char* destination) {
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,42));
    const auto& original=archive.draws.back();CHECK(original.type==D3DPT_TRIANGLELIST && original.indexed && original.stride==32);
    Probe probe{window,archive};probe.output=destination;CHECK(probe.Initialize());CHECK(probe.Render("original",original));
    const auto baselineNative=probe.native,baselineCandidate=probe.candidate;CHECK(!probe.focus.empty());
    for(unsigned path=0;path<2;++path){std::ifstream file(std::filesystem::path(reference)/(path?"isolated42.candidate.bgra":"isolated42.native.bgra"),std::ios::binary);const std::vector<unsigned char> bytes(std::istreambuf_iterator<char>{file},{});CHECK(bytes==(path?baselineCandidate:baselineNative));}
    for(unsigned n=1;n<=3;++n){CHECK(probe.Render("repeat"+std::to_string(n),original));CHECK(probe.native==baselineNative && probe.candidate==baselineCandidate);}
    const char* names[]={"original","no_blend","no_alpha_test","no_depth_stencil","no_specular","no_lighting","no_normalize","toon_only","sphere_only","no_textures","white_toon","white_sphere","white_both","point","linear_mip_point","linear_mip_linear"};
    for(unsigned mode=1;mode<16;++mode)CHECK(probe.Render(names[mode],Control(original,mode)));
    std::vector<std::pair<unsigned,unsigned>> ranges{{0,original.count}};std::vector<unsigned> leaves;
    for(unsigned at=0;at<ranges.size();++at){const auto [first,count]=ranges[at];
        CHECK(probe.Render("range_"+std::to_string(first)+"_"+std::to_string(count),Triangles(original,first,count),first));
        if(!probe.Mask())continue;
        if(count==1){leaves.push_back(first);continue;}
        const auto half=count/2;ranges.push_back({first,half});ranges.push_back({first+half,count-half});
    }
    CHECK(!leaves.empty());std::ofstream indices(probe.output/"triangles.csv");indices<<"triangle,index0,index1,index2\n";
    for(unsigned first:leaves){const auto triangle=Triangles(original,first,1),compact=CompactTriangle(triangle);
        indices<<first;for(unsigned n=0;n<3;++n)indices<<","<<ground_history_isolation::Index(original,original.start+first*3+n);indices<<"\n";
        CHECK(probe.Render("leaf_"+std::to_string(first),triangle,first));const auto n=probe.native,c=probe.candidate;
        CHECK(probe.Render("compact_"+std::to_string(first),compact,first));CHECK(probe.native==n && probe.candidate==c);
        for(unsigned mode=1;mode<16;++mode)CHECK(probe.Render("compact_"+std::to_string(first)+"_"+names[mode],Control(compact,mode),first));
        std::ofstream vertices(probe.output/("compact_"+std::to_string(first)+".vertices"),std::ios::binary);vertices.write(reinterpret_cast<const char*>(compact.vertexBytes.data()),compact.vertexBytes.size());CHECK(vertices);
    }
    auto frozen=original;CHECK(FreezeMips(frozen,1));CHECK(probe.Render("frozen_sphere_mips",frozen));
    CHECK(probe.native==baselineNative && probe.candidate==baselineCandidate);
    for(unsigned first:leaves) {
        const auto compact=CompactTriangle(Triangles(original,first,1));const auto label="compact_"+std::to_string(first);
        std::vector<std::array<float,4>> positions,colors;std::vector<std::array<float,2>> uv;
        CHECK(CaptureDepthVertexShader(compact,positions,nullptr,false,3,&colors,nullptr,nullptr,true,&uv,1,true));
        CHECK(positions.size()==3 && uv.size()==3 && colors.size()==3);
        std::ofstream observed(probe.output/(label+".sphere.so"),std::ios::binary);
        for(unsigned v=0;v<3;++v){observed.write(reinterpret_cast<const char*>(positions[v].data()),16);observed.write(reinterpret_cast<const char*>(uv[v].data()),8);observed.write(reinterpret_cast<const char*>(colors[v].data()),16);
            CHECK(std::isfinite(uv[v][0]) && std::isfinite(uv[v][1]) && std::isfinite(positions[v][3]) && positions[v][3]>0);}
        CHECK(observed);
        for(unsigned repeat=0;repeat<3;++repeat){std::vector<std::array<float,4>> p,c;std::vector<std::array<float,2>> t;
            CHECK(CaptureDepthVertexShader(compact,p,nullptr,false,3,&c,nullptr,nullptr,true,&t,1,true));CHECK(p==positions && c==colors && t==uv);
            std::ofstream file(probe.output/(label+".sphere.repeat"+std::to_string(repeat+1)+".so"),std::ios::binary);
            for(unsigned v=0;v<3;++v){file.write(reinterpret_cast<const char*>(p[v].data()),16);file.write(reinterpret_cast<const char*>(t[v].data()),8);file.write(reinterpret_cast<const char*>(c[v].data()),16);}CHECK(file);}
        // Counterfactual shared UV: both APIs read the exact DX11 observation
        // as mesh input. This is not a native DX9 vertex-coordinate capture.
        auto baked=compact;Stage(baked,1,D3DTSS_TEXCOORDINDEX,0);Stage(baked,1,D3DTSS_TEXTURETRANSFORMFLAGS,0);
        for(unsigned v=0;v<3;++v)std::memcpy(baked.vertexBytes.data()+v*32+24,uv[v].data(),8);
        std::ofstream vertices(probe.output/(label+".baked.vertices"),std::ios::binary);vertices.write(reinterpret_cast<const char*>(baked.vertexBytes.data()),baked.vertexBytes.size());CHECK(vertices);
        CHECK(probe.Render(label+"_shared_uv",baked,first));const auto n=probe.native,c=probe.candidate;
        auto explicitMips=baked;CHECK(FreezeMips(explicitMips,1));CHECK(probe.Render(label+"_shared_uv_frozen",explicitMips,first));CHECK(probe.native==n && probe.candidate==c);
        for(unsigned mode=13;mode<16;++mode)CHECK(probe.Render(label+"_shared_uv_"+names[mode],Control(baked,mode),first));
        auto pure=Control(baked,8);Stage(pure,0,D3DTSS_TEXCOORDINDEX,0);Stage(pure,0,D3DTSS_TEXTURETRANSFORMFLAGS,0);
        State(pure,D3DRS_LIGHTING,0);State(pure,D3DRS_SPECULARENABLE,0);State(pure,D3DRS_ALPHABLENDENABLE,0);State(pure,D3DRS_ALPHATESTENABLE,0);State(pure,D3DRS_ZENABLE,0);State(pure,D3DRS_ZWRITEENABLE,0);State(pure,D3DRS_STENCILENABLE,0);
        CHECK(probe.Render(label+"_pure_shared_uv",pure,first));const auto pureN=probe.native,pureC=probe.candidate;
        auto pureFrozen=pure;CHECK(FreezeMips(pureFrozen,0));CHECK(probe.Render(label+"_pure_shared_uv_frozen",pureFrozen,first));CHECK(probe.native==pureN && probe.candidate==pureC);
        for(unsigned mode=13;mode<16;++mode)CHECK(probe.Render(label+"_pure_shared_uv_"+names[mode],Control(pure,mode),first));
        // Constant coordinates remove the triangle's varying UV plane. These
        // are controls, not substitutes for the original varying-input gate.
        for(unsigned point=0;point<7;++point){auto flat=pure;std::array<float,2> value{};
            for(unsigned k=0;k<2;++k)value[k]=point<3?uv[point][k]:point<6?(uv[point-3][k]+uv[(point-2)%3][k])*.5f:(uv[0][k]+uv[1][k]+uv[2][k])/3.f;
            for(unsigned v=0;v<3;++v)std::memcpy(flat.vertexBytes.data()+v*32+24,value.data(),8);
            CHECK(probe.Render(label+"_pure_constant_uv"+std::to_string(point),flat,first));
        }
    }
    CHECK(indices && probe.report && probe.pixels);CHECK(probe.bundle.swapchain->Retire());
    std::ofstream summary(probe.output/"summary.txt");summary<<"complete=1 draw=42 comparisons="<<probe.comparisons<<" leaves="<<leaves.size()<<" repeats=3 sphereSoRepeats=3 frozenMipsExact=1 sourceReferenceExact=1 productionActivation=0 imageAcceptance=0\n";CHECK(summary);return 0;
}
} // namespace model_color_isolation
