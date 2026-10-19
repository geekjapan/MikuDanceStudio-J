#pragma once
// Native/API arithmetic diagnostics only. No production renderer selection or
// acceptance tolerance changes. Every altered state is named in evidence.
namespace ground_history_isolation {
struct Archive {
    std::vector<D3D9ReplaySnapshot> draws;
    unsigned width=0,height=0;DWORD clear=0;D3DVIEWPORT9 region{};
    std::filesystem::path path;
    bool Load(const char* root,unsigned count) {
        path=root;std::ifstream manifest(path/"history_replay.scene_prefix.manifest");std::string line;
        if(!std::getline(manifest,line) || line.find("status=READY nativeExact=1")==std::string::npos)return false;
        draws.resize(count);
        for(unsigned n=0;n<count;++n)if(!ReadUntexturedReduction(path/("history_replay.scene_prefix.draw"+std::to_string(n+1)+".state"),draws[n],true))return false;
        std::ifstream input(path/"history_replay.scene_prefix.draw1.state");bool target=false,cleared=false;
        while(std::getline(input,line)) {
            unsigned color=0,depth=0,samples=0,quality=0,flags=0,stencil=0;float z=0;
            if(std::sscanf(line.c_str(),"TARGET width=%u height=%u colorFormat=%u depthFormat=%u samples=%u quality=%u",&width,&height,&color,&depth,&samples,&quality)==6)
                target=color==D3DFMT_A8R8G8B8 && depth==D3DFMT_D24S8 && !samples && !quality;
            if(std::sscanf(line.c_str(),"CLEAR flags=%u color=%lu depth=%f stencil=%u",&flags,&clear,&z,&stencil)==4)cleared=flags==7 && z==1 && !stencil;
        }
        region=draws[0].viewport;return target && cleared && width<=4096 && height<=4096 &&
            draws[0].type==D3DPT_LINELIST && draws[0].indexed && draws[0].stride==16 &&
            ValidModelViewport({region.X,region.Y,region.Width,region.Height,region.MinZ,region.MaxZ},width,height);
    }
    std::vector<unsigned char> Boundary(unsigned after) const {
        std::ifstream file(path/("history_replay.scene_prefix.draw"+std::to_string(after+1)+".before.bgra"),std::ios::binary);
        return {std::istreambuf_iterator<char>{file},{}};
    }
};
inline void State(D3D9ReplaySnapshot& c,unsigned key,DWORD value) {
    for(auto& state:c.renderStates)if(state.key==key){state.value=value;return;}
    c.renderStates.push_back({0,key,value});
}
inline unsigned Index(const D3D9ReplaySnapshot& c,unsigned at) {
    const unsigned step=c.indexFormat==D3DFMT_INDEX16?2:4;unsigned value=0;
    if(std::uint64_t(at)*step+step>c.indexBytes.size())return ~0u;
    std::memcpy(&value,c.indexBytes.data()+std::size_t(at)*step,step);return value;
}
inline void Reverse(D3D9ReplaySnapshot& c) {
    const unsigned step=c.indexFormat==D3DFMT_INDEX16?2:4;
    for(unsigned n=0;n<c.count;++n)for(unsigned b=0;b<step;++b)
        std::swap(c.indexBytes[(c.start+n*2)*step+b],c.indexBytes[(c.start+n*2+1)*step+b]);
}
struct Probe {
    HWND window;Archive& archive;D3D11Bundle bundle;std::filesystem::path output;
    std::ofstream report,pixels;unsigned comparisons=0;
    std::vector<unsigned char> native,candidate,baselineNative,baselineCandidate;
    Probe(HWND w,Archive& a,const char* destination):window(w),archive(a),output(destination) {}
    bool Initialize() {
        // Fresh evidence only; never append new rows to a stale partial run.
        if(std::filesystem::exists(output))return false;
        std::filesystem::create_directories(output);
        SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
        bundle=CreateD3D11NormalCandidateDevice(desc,D3D11Driver::Hardware);if(!bundle)return false;
        report.open(output/"controls.csv");pixels.open(output/"pixels.csv");
        report<<"mode,draws,differentPixels,maxDelta,firstX,firstY,nativeChangedFromBaseline,candidateChangedFromBaseline,nativeHash,candidateHash\n";
        pixels<<"mode,x,y,nativeB,nativeG,nativeR,nativeA,candidateB,candidateG,candidateR,candidateA\n";
        std::ofstream metadata(output/"metadata.txt");metadata<<"adapter="<<bundle.adapterName<<"\nwidth="<<archive.width<<" height="<<archive.height<<" region="<<archive.region.X<<","<<archive.region.Y<<","<<archive.region.Width<<","<<archive.region.Height<<" samples=1 productionActivation=0\n";
        return report && pixels && metadata;
    }
    bool Render(const std::string& name,const std::vector<D3D9ReplaySnapshot>& draws,bool original=false) {
        if(draws.empty())return false;
        ModelReplayStream stream;stream.target.width=archive.width;stream.target.height=archive.height;
        const auto c=archive.clear;stream.clear={((c>>16)&255)/255.f,((c>>8)&255)/255.f,(c&255)/255.f,((c>>24)&255)/255.f};
        stream.initializedRegion=ModelViewport{archive.region.X,archive.region.Y,archive.region.Width,archive.region.Height,archive.region.MinZ,archive.region.MaxZ};
        stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& draw:draws){const auto result=AppendD3D9ReplaySnapshot(stream,draw,true);if(!result){std::fprintf(stderr,"isolation conversion mode=%s reason=%s\n",name.c_str(),result.reason.c_str());return false;}}
        stream.complete=true;RgbaImage n,r;
        if(!NativeImage(window,draws,static_cast<unsigned>(draws.size()),n,nullptr,archive.width,archive.height,c) ||
           !ReplayD3D11WCandidatePrefix(*bundle.device,stream,draws.size(),r))return false;
        native=scene_prefix_diagnostic::Crop(n,archive.region);candidate=scene_prefix_diagnostic::Crop(r,archive.region);
        if(native.size()!=std::size_t(archive.region.Width)*archive.region.Height*4 || candidate.size()!=native.size())return false;
        if(original){if(native!=archive.Boundary(static_cast<unsigned>(draws.size())))return false;baselineNative=native;baselineCandidate=candidate;}
        unsigned different=0,maximum=0,first=0,changedN=0,changedR=0;
        for(unsigned p=0;p<native.size()/4;++p) {
            unsigned delta=0;for(unsigned k=0;k<4;++k)delta=(std::max)(delta,unsigned(std::abs(int(native[p*4+k])-candidate[p*4+k])));
            if(delta){if(!different)first=p;++different;pixels<<name<<","<<archive.region.X+p%archive.region.Width<<","<<archive.region.Y+p/archive.region.Width;
                for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(native[p*4+k]);for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(candidate[p*4+k]);pixels<<"\n";}
            maximum=(std::max)(maximum,delta);
            if(!baselineNative.empty()){changedN+=std::memcmp(native.data()+p*4,baselineNative.data()+p*4,4)!=0;changedR+=std::memcmp(candidate.data()+p*4,baselineCandidate.data()+p*4,4)!=0;}
        }
        report<<name<<","<<draws.size()<<","<<different<<","<<maximum<<","<<archive.region.X+first%archive.region.Width<<","<<archive.region.Y+first/archive.region.Width<<","<<changedN<<","<<changedR<<","<<scene_prefix_diagnostic::Hash(native)<<","<<scene_prefix_diagnostic::Hash(candidate)<<"\n";report.flush();pixels.flush();
        for(unsigned side=0;side<2;++side){const auto& bytes=side?candidate:native;std::ofstream file(output/(name+(side?".candidate.bgra":".native.bgra")),std::ios::binary);file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());if(!file)return false;}
        ++comparisons;std::printf("groundIsolation mode=%s draws=%zu differentPixels=%u maxDelta=%u first=%u,%u\n",name.c_str(),draws.size(),different,maximum,archive.region.X+first%archive.region.Width,archive.region.Y+first/archive.region.Width);std::fflush(stdout);
        return report && pixels;
    }
    bool Finish() {
        std::ofstream summary(output/"summary.txt");summary<<"comparisons="<<comparisons<<" baselineNativeExact=1 repeatedBaselineExact=1 productionActivation=0 imageAcceptance=0\n";
        return summary && bundle.swapchain->Retire();
    }
};
inline int Lines(HWND window,const char* root,const char* output) {
    Archive a;CHECK(a.Load(root,1));CHECK(a.draws[0].count<=512 && a.draws[0].fvf==(D3DFVF_XYZ|D3DFVF_DIFFUSE));
    Probe probe(window,a,output);CHECK(probe.Initialize());CHECK(probe.Render("original",a.draws,true));
    const auto originalN=probe.native,originalR=probe.candidate;
    for(unsigned repeat=1;repeat<=3;++repeat){CHECK(probe.Render("repeat"+std::to_string(repeat),a.draws));CHECK(probe.native==originalN && probe.candidate==originalR);}
    for(unsigned mode=0;mode<7;++mode) {
        auto c=a.draws[0];const char* names[]={"no_depth","no_stencil","no_alpha_test","no_blend","unlit_uniform","reverse_all","no_depth_write"};
        if(mode==0){State(c,D3DRS_ZENABLE,0);State(c,D3DRS_ZWRITEENABLE,0);}
        if(mode==1)State(c,D3DRS_STENCILENABLE,0);
        if(mode==2)State(c,D3DRS_ALPHATESTENABLE,0);
        if(mode==3)State(c,D3DRS_ALPHABLENDENABLE,0);
        if(mode==4){State(c,D3DRS_LIGHTING,0);State(c,D3DRS_ALPHABLENDENABLE,0);State(c,D3DRS_ALPHATESTENABLE,0);State(c,D3DRS_STENCILENABLE,0);State(c,D3DRS_ZENABLE,0);
            for(std::size_t at=12;at<c.vertexBytes.size();at+=16){const DWORD red=0xffff0000;std::memcpy(c.vertexBytes.data()+at,&red,4);}}
        if(mode==5)Reverse(c);if(mode==6)State(c,D3DRS_ZWRITEENABLE,0);
        CHECK(probe.Render(names[mode],{c}));
    }
    std::ofstream endpoints(probe.output/"segments.csv");endpoints<<"segment,endpoint,index,x,y,z,color\n";endpoints<<std::setprecision(9);
    for(unsigned segment=0;segment<a.draws[0].count;++segment) {
        auto c=a.draws[0];c.start+=segment*2;c.count=1;
        for(unsigned endpoint=0;endpoint<2;++endpoint){const auto index=Index(c,c.start+endpoint);CHECK(index<c.vertexBytes.size()/c.stride);float pos[3];DWORD color=0;
            std::memcpy(pos,c.vertexBytes.data()+std::size_t(index)*c.stride,12);std::memcpy(&color,c.vertexBytes.data()+std::size_t(index)*c.stride+12,4);
            endpoints<<segment+1<<","<<endpoint<<","<<index<<","<<pos[0]<<","<<pos[1]<<","<<pos[2]<<","<<color<<"\n";}
        CHECK(probe.Render("segment"+std::to_string(segment+1),{c}));const bool failed=probe.native!=probe.candidate;Reverse(c);
        CHECK(probe.Render("reverse"+std::to_string(segment+1),{c}));
        if(failed) {
            Reverse(c);std::vector<unsigned char> bytes;
            for(unsigned n=0;n<2;++n){const auto index=Index(c,c.start+n);bytes.insert(bytes.end(),c.vertexBytes.begin()+std::size_t(index)*16,c.vertexBytes.begin()+std::size_t(index+1)*16);}
            c.vertexBytes=std::move(bytes);c.indexBytes={0,0,1,0};c.indexFormat=D3DFMT_INDEX16;c.start=c.minimum=0;c.vertices=2;
            const auto name="compact_segment"+std::to_string(segment+1);CHECK(probe.Render(name,{c}));CHECK(probe.native!=probe.candidate);
            std::ofstream v(probe.output/(name+".vertices"),std::ios::binary),i(probe.output/(name+".indices"),std::ios::binary);
            v.write(reinterpret_cast<const char*>(c.vertexBytes.data()),c.vertexBytes.size());i.write(reinterpret_cast<const char*>(c.indexBytes.data()),c.indexBytes.size());CHECK(v && i);
            Reverse(c);CHECK(probe.Render("compact_reverse"+std::to_string(segment+1),{c}));Reverse(c);
            State(c,D3DRS_ZENABLE,0);State(c,D3DRS_ZWRITEENABLE,0);State(c,D3DRS_STENCILENABLE,0);State(c,D3DRS_ALPHATESTENABLE,0);State(c,D3DRS_ALPHABLENDENABLE,0);State(c,D3DRS_LIGHTING,0);
            for(std::size_t at=12;at<c.vertexBytes.size();at+=16){const DWORD red=0xffff0000;std::memcpy(c.vertexBytes.data()+at,&red,4);}
            CHECK(probe.Render("compact_uniform"+std::to_string(segment+1),{c}));
        }
    }
    CHECK(endpoints);CHECK(probe.Finish());return 0;
}
inline int History(HWND window,const char* root,const char* output,unsigned selected) {
    CHECK(selected>=3 && selected<=8);Archive a;CHECK(a.Load(root,selected));
    CHECK(a.draws[1].type==D3DPT_TRIANGLELIST && !a.draws[1].indexed);
    Probe probe(window,a,output);CHECK(probe.Initialize());CHECK(probe.Render("original",a.draws,true));
    const auto originalN=probe.native,originalR=probe.candidate;
    for(unsigned repeat=1;repeat<=3;++repeat){CHECK(probe.Render("repeat"+std::to_string(repeat),a.draws));CHECK(probe.native==originalN && probe.candidate==originalR);}
    // Exhaust every subset of prior draws, always preserving their order and
    // the unmodified selected draw. No intermediate color seeds depth history.
    for(unsigned mask=0;mask<(1u<<(selected-1));++mask){std::vector<D3D9ReplaySnapshot> draws;
        for(unsigned n=0;n<selected-1;++n)if(mask&(1u<<n))draws.push_back(a.draws[n]);draws.push_back(a.draws.back());
        CHECK(probe.Render("prior_mask"+std::to_string(mask),draws));}
    const char* names[]={"ground_no_depth_write","grid_no_depth_write","plane_no_depth_write","all_no_stencil","ground_no_stencil_write",
        "ground_depth_only","ground_color_only","selected_no_depth","selected_always","selected_less","selected_equal","selected_no_depth_write","selected_no_stencil","selected_no_blend"};
    for(unsigned mode=0;mode<14;++mode){auto draws=a.draws;
        for(unsigned n=0;n<draws.size();++n){auto& c=draws[n];const bool ground=n<2,last=n+1==draws.size();
            if((mode==0 && ground) || (mode==1 && n==0) || (mode==2 && n==1))State(c,D3DRS_ZWRITEENABLE,0);
            if(mode==3 || (mode==5 && ground))State(c,D3DRS_STENCILENABLE,0);
            if(mode==4 && ground)State(c,D3DRS_STENCILWRITEMASK,0);
            if(mode==5 && ground)State(c,D3DRS_COLORWRITEENABLE,0);
            if(mode==6 && ground){State(c,D3DRS_ZWRITEENABLE,0);State(c,D3DRS_STENCILWRITEMASK,0);}
            if(last && mode==7){State(c,D3DRS_ZENABLE,0);State(c,D3DRS_ZWRITEENABLE,0);}
            if(last && mode>=8 && mode<=10)State(c,D3DRS_ZFUNC,mode==8?D3DCMP_ALWAYS:mode==9?D3DCMP_LESS:D3DCMP_EQUAL);
            if(last && mode==11)State(c,D3DRS_ZWRITEENABLE,0);
            if(last && mode==12)State(c,D3DRS_STENCILENABLE,0);
            if(last && mode==13)State(c,D3DRS_ALPHABLENDENABLE,0);
        }CHECK(probe.Render(names[mode],draws));
    }
    CHECK(probe.Finish());return 0;
}
inline D3D9ReplaySnapshot Triangles(const D3D9ReplaySnapshot& source,unsigned first,unsigned count) {
    auto c=source;c.start+=first*3;c.count=count;return c;
}
inline D3D9ReplaySnapshot CompactTriangle(const D3D9ReplaySnapshot& source) {
    auto c=source;std::vector<unsigned char> bytes;
    for(unsigned n=0;n<3;++n){const auto index=c.indexed?Index(c,c.start+n):c.start+n;
        bytes.insert(bytes.end(),c.vertexBytes.begin()+std::size_t(index)*c.stride,c.vertexBytes.begin()+std::size_t(index+1)*c.stride);}
    c.vertexBytes=std::move(bytes);c.start=0;c.minimum=0;c.vertices=c.indexed?3:0;
    if(c.indexed){c.indexFormat=D3DFMT_INDEX16;c.indexBytes={0,0,1,0,2,0};}return c;
}
inline int DepthReduction(HWND window,const char* root,const char* output,unsigned selected) {
    CHECK(selected>=3 && selected<=8);Archive a;CHECK(a.Load(root,selected));Probe probe(window,a,output);CHECK(probe.Initialize());
    CHECK(probe.Render("original",a.draws,true));const auto originalN=probe.native,originalR=probe.candidate;
    unsigned focus=~0u;for(unsigned p=0;p<originalN.size()/4;++p)if(std::memcmp(originalN.data()+p*4,originalR.data()+p*4,4)){focus=p;break;}CHECK(focus!=~0u);
    auto mismatched=[&](){return std::memcmp(probe.native.data()+focus*4,probe.candidate.data()+focus*4,4)!=0;};
    for(unsigned repeat=1;repeat<=3;++repeat){CHECK(probe.Render("repeat"+std::to_string(repeat),a.draws));CHECK(probe.native==originalN && probe.candidate==originalR);}
    CHECK(a.draws[1].type==D3DPT_TRIANGLELIST && !a.draws[1].indexed && a.draws[1].count==2);
    auto plane=a.draws[1],accessory=a.draws.back();CHECK(accessory.type==D3DPT_TRIANGLELIST && accessory.indexed);
    CHECK(probe.Render("pair",{plane,accessory}) && mismatched());unsigned planeTriangle=~0u;
    for(unsigned n=0;n<2;++n){CHECK(probe.Render("plane_triangle"+std::to_string(n),{Triangles(plane,n,1),accessory}));if(mismatched() && planeTriangle==~0u)planeTriangle=n;}
    CHECK(planeTriangle!=~0u);plane=Triangles(plane,planeTriangle,1);
    unsigned first=0,count=accessory.count,step=0;
    while(count>1) {
        const unsigned left=count/2,right=count-left;bool retained=false;
        for(unsigned half=0;half<2;++half){const unsigned partFirst=first+(half?left:0),partCount=half?right:left;
            CHECK(probe.Render("reduce_step"+std::to_string(step)+"_half"+std::to_string(half),{plane,Triangles(accessory,partFirst,partCount)}));
            if(mismatched()){first=partFirst;count=partCount;retained=true;break;}}
        if(!retained)break;++step;
    }
    accessory=Triangles(accessory,first,count);CHECK(probe.Render("minimal_pair",{plane,accessory}) && mismatched());
    // A genuine one-triangle repro must survive independent buffer compaction,
    // not depend on the original unused vertices or index range.
    if(count==1){plane=CompactTriangle(plane);accessory=CompactTriangle(accessory);
        CHECK(probe.Render("compact_pair",{plane,accessory}) && mismatched());}
    CHECK(probe.Render("minimal_plane_alone",{plane}));CHECK(probe.Render("minimal_accessory_alone",{accessory}));
    const char* names[]={"minimal_plane_no_depth_write","minimal_no_stencil","minimal_plane_depth_only","minimal_less","minimal_equal","minimal_always","minimal_no_depth"};
    for(unsigned mode=0;mode<7;++mode){auto p=plane,c=accessory;
        if(mode==0)State(p,D3DRS_ZWRITEENABLE,0);
        if(mode==1){State(p,D3DRS_STENCILENABLE,0);State(c,D3DRS_STENCILENABLE,0);}
        if(mode==2){State(p,D3DRS_STENCILENABLE,0);State(p,D3DRS_COLORWRITEENABLE,0);}
        if(mode>=3 && mode<=5)State(c,D3DRS_ZFUNC,mode==3?D3DCMP_LESS:mode==4?D3DCMP_EQUAL:D3DCMP_ALWAYS);
        if(mode==6){State(c,D3DRS_ZENABLE,0);State(c,D3DRS_ZWRITEENABLE,0);}
        CHECK(probe.Render(names[mode],{p,c}));
    }
    std::ofstream reduction(probe.output/"reduction.txt");reduction<<"selectedDraw="<<selected<<" planeSourceDraw=2 planeTriangle="<<planeTriangle
        <<" accessoryFirstTriangle="<<first<<" accessoryTriangles="<<count<<" compact="<<(count==1)<<" focusX="<<a.region.X+focus%a.region.Width<<" focusY="<<a.region.Y+focus/a.region.Width<<"\n";
    for(unsigned n=0;n<2;++n){const auto& c=n?accessory:plane;const std::string stem=n?"minimal_accessory":"minimal_plane";
        std::ofstream v(probe.output/(stem+".vertices"),std::ios::binary),i(probe.output/(stem+".indices"),std::ios::binary);
        v.write(reinterpret_cast<const char*>(c.vertexBytes.data()),c.vertexBytes.size());i.write(reinterpret_cast<const char*>(c.indexBytes.data()),c.indexBytes.size());CHECK(v && i);}
    CHECK(reduction);CHECK(probe.Finish());return 0;
}
}
