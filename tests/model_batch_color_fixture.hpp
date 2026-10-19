#pragma once
#include "mikudancestudio/rhi_scene_renderer.hpp"
// Private captured inputs, production compatibility policy, fresh evidence.
// Controls diagnose the failure; they never relax the native image gate.
namespace model_batch_color {
using ground_history_isolation::State;
using ground_history_isolation::Triangles;
using ground_history_isolation::CompactTriangle;
struct Probe {
    HWND window;ground_history_isolation::Archive& archive;D3D11Bundle bundle;
    std::filesystem::path output;std::ofstream report,pixels;
    std::vector<unsigned char> native,candidate;
    unsigned focusX=867,focusY=486,comparisons=0;
    bool textureFma=false;
    bool Initialize() {
        if(std::filesystem::exists(output))return false;std::filesystem::create_directories(output);
        SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
        bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured,textureFma,textureFma});if(!bundle)return false;
        report.open(output/"controls.csv");pixels.open(output/"pixels.csv");
        report<<"mode,firstTriangle,triangles,draws,differentPixels,maxDelta,focusDifferent,nativeHash,candidateHash\n";
        pixels<<"mode,x,y,nB,nG,nR,nA,cB,cG,cR,cA\n";
        const auto& r=archive.region;
        std::ofstream metadata(output/"metadata.txt");metadata<<"draw=23 backend=dx11 compatibility=Dx9Measured samples=1 productionActivation=0 imageAcceptance=0 adapter="<<bundle.adapterName
            <<"\nwidth="<<archive.width<<" height="<<archive.height<<" region="<<r.X<<","<<r.Y<<","<<r.Width<<","<<r.Height<<" focus="<<focusX<<","<<focusY<<" diagnosticTextureFma="<<textureFma<<"\n";
        return focusX>=r.X && focusY>=r.Y && focusX-r.X<r.Width && focusY-r.Y<r.Height && report && pixels && metadata;
    }
    std::size_t Focus()const{return std::size_t(focusY-archive.region.Y)*archive.region.Width+focusX-archive.region.X;}
    bool FocusDifferent()const{return std::memcmp(native.data()+Focus()*4,candidate.data()+Focus()*4,4)!=0;}
    bool Render(const std::string& name,const std::vector<D3D9ReplaySnapshot>& draws,unsigned first=0) {
        ModelReplayStream stream;stream.target.width=archive.width;stream.target.height=archive.height;
        const auto color=archive.clear;stream.clear={((color>>16)&255)/255.f,((color>>8)&255)/255.f,(color&255)/255.f,((color>>24)&255)/255.f};
        const auto& r=archive.region;stream.initializedRegion=ModelViewport{r.X,r.Y,r.Width,r.Height,r.MinZ,r.MaxZ};stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& draw:draws){const auto converted=AppendD3D9ReplaySnapshot(stream,draw,true);
            if(!converted){std::fprintf(stderr,"model23 mode=%s conversion=%s\n",name.c_str(),converted.reason.c_str());return false;}}
        stream.complete=true;RgbaImage a,b;
        if(!NativeImage(window,draws,unsigned(draws.size()),a,nullptr,archive.width,archive.height,color))return false;
        SceneRenderer renderer(*bundle.device);PreparedModelFrame frame;CompletionToken token;
        if(!renderer.Prepare(1,stream,frame) || !renderer.Submit(frame,token) || !bundle.device->ReadModelTarget(b))return false;
        native=scene_prefix_diagnostic::Crop(a,r);candidate=scene_prefix_diagnostic::Crop(b,r);
        if(native.size()!=std::size_t(r.Width)*r.Height*4 || candidate.size()!=native.size())return false;
        unsigned different=0,maximum=0;
        for(std::size_t p=0;p<native.size();p+=4){unsigned delta=0;for(unsigned k=0;k<4;++k)delta=(std::max)(delta,unsigned(std::abs(int(native[p+k])-candidate[p+k])));different+=delta!=0;maximum=(std::max)(maximum,delta);}
        report<<name<<","<<first<<","<<draws.back().count<<","<<draws.size()<<","<<different<<","<<maximum<<","<<FocusDifferent()<<","<<scene_prefix_diagnostic::Hash(native)<<","<<scene_prefix_diagnostic::Hash(candidate)<<"\n";report.flush();
        pixels<<name<<","<<focusX<<","<<focusY;for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(native[Focus()*4+k]);for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(candidate[Focus()*4+k]);pixels<<"\n";pixels.flush();
        for(unsigned path=0;path<2;++path){const auto& bytes=path?candidate:native;std::ofstream file(output/(name+(path?".candidate.bgra":".native.bgra")),std::ios::binary);file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());if(!file)return false;}
        std::printf("model23 mode=%s first=%u triangles=%u differentPixels=%u maxDelta=%u focus=%u\n",name.c_str(),first,draws.back().count,different,maximum,FocusDifferent());std::fflush(stdout);++comparisons;return true;
    }
    bool Single(const std::string& name,const D3D9ReplaySnapshot& c,unsigned first=0){return Render(name,{c},first);}
};
inline int Run(HWND window,const char* root,const char* destination,unsigned focusX=867,unsigned focusY=486,bool textureFma=false) {
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,24));
    const auto original=archive.draws[22];CHECK(original.indexed && original.type==D3DPT_TRIANGLELIST && original.stride==32 && original.start==7275 && original.count==7667);
    Probe p{window,archive};p.output=destination;p.focusX=focusX;p.focusY=focusY;p.textureFma=textureFma;CHECK(p.Initialize());
    std::vector<D3D9ReplaySnapshot> preceding(archive.draws.begin(),archive.draws.begin()+23);
    CHECK(p.Render("history23",preceding));CHECK(p.native==archive.Boundary(23));CHECK(p.FocusDifferent());
    const auto historyN=p.native,historyC=p.candidate;
    for(unsigned n=1;n<=3;++n){CHECK(p.Render("history_repeat"+std::to_string(n),preceding));CHECK(p.native==historyN && p.candidate==historyC);}
    CHECK(p.Single("original",original));const auto originalN=p.native,originalC=p.candidate;const bool isolated=p.FocusDifferent();
    for(unsigned n=1;n<=3;++n){CHECK(p.Single("repeat"+std::to_string(n),original));CHECK(p.native==originalN && p.candidate==originalC);}
    const char* names[]={"original","no_blend","no_alpha_test","no_depth_stencil","no_specular","no_lighting","no_normalize","toon_only","base_only","no_textures","white_toon","white_base","white_both","point","linear_mip_point","linear_mip_linear"};
    for(unsigned mode=1;mode<16;++mode)CHECK(p.Single(names[mode],model_color_isolation::Control(original,mode)));
    auto frozen=original;CHECK(model_color_isolation::FreezeMips(frozen,0) && model_color_isolation::FreezeMips(frozen,1));
    CHECK(p.Single("frozen_mips",frozen));CHECK(p.native==originalN && p.candidate==originalC);
    std::vector<unsigned> leaves;
    if(isolated) {
        std::vector<std::pair<unsigned,unsigned>> pending{{0,original.count}};
        for(std::size_t n=0;n<pending.size();++n){const auto [first,count]=pending[n];CHECK(p.Single("range_"+std::to_string(first)+"_"+std::to_string(count),Triangles(original,first,count),first));
            if(!p.FocusDifferent())continue;if(count==1){leaves.push_back(first);continue;}const auto half=count/2;pending.push_back({first,half});pending.push_back({first+half,count-half});}
        CHECK(!leaves.empty());
        std::ofstream triangles(p.output/"triangles.csv");triangles<<"triangle,index0,index1,index2\n";
        for(unsigned first:leaves){auto triangle=Triangles(original,first,1);auto compact=CompactTriangle(triangle);const auto label="compact_"+std::to_string(first);
            triangles<<first;for(unsigned n=0;n<3;++n)triangles<<","<<ground_history_isolation::Index(original,original.start+first*3+n);triangles<<"\n";
            CHECK(p.Single("leaf_"+std::to_string(first),triangle,first));const auto n=p.native,c=p.candidate;
            CHECK(p.Single(label,compact,first));CHECK(p.native==n && p.candidate==c);
            for(unsigned mode=1;mode<16;++mode)CHECK(p.Single(label+"_"+names[mode],model_color_isolation::Control(compact,mode),first));
            std::ofstream vertices(p.output/(label+".vertices"),std::ios::binary);vertices.write(reinterpret_cast<const char*>(compact.vertexBytes.data()),compact.vertexBytes.size());CHECK(vertices);
        }
        CHECK(triangles);
    }
    CHECK(p.bundle.swapchain->Retire());
    std::ofstream summary(p.output/"summary.txt");summary<<"complete=1 draw=23 comparisons="<<p.comparisons<<" isolatedFocus="<<isolated<<" leaves="<<leaves.size()<<" repeats=3 frozenMipsExact=1 nativeArchiveExact=1 productionActivation=0 imageAcceptance=0\n";CHECK(summary);return 0;
}
}
