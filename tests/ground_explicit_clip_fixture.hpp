#pragma once
#include "explicit_clip_geometry.hpp"
namespace ground_explicit_clip {
using Clip=explicit_clip_geometry::Vertex;
using ground_endpoint_depth::Save;
inline bool Read(const std::filesystem::path& path,std::vector<Clip>& out) {
    std::ifstream f(path,std::ios::binary);const std::vector<char> bytes(std::istreambuf_iterator<char>{f},{});
    if(bytes.empty() || bytes.size()%16)return false;out.resize(bytes.size()/16);std::memcpy(out.data(),bytes.data(),bytes.size());return true;
}
inline void Geometry(const std::filesystem::path& output,const std::string& name,const std::vector<Clip>& vertices) {
    Save(output/(name+".clip.bin"),vertices.data(),vertices.size()*16);
}
inline unsigned Difference(const std::vector<unsigned char>& a,const std::vector<unsigned char>& b) {
    if(a.size()!=b.size())return ~0u;unsigned out=0;for(std::size_t at=0;at<a.size();at+=4)out+=std::memcmp(a.data()+at,b.data()+at,4)!=0;return out;
}
inline bool RegionMatches(const std::vector<unsigned char>& bytes,const std::filesystem::path& path) {
    std::ifstream f(path,std::ios::binary);return bytes==std::vector<unsigned char>(std::istreambuf_iterator<char>{f},{});
}
inline bool RepeatBaseline(ground_history_isolation::Probe& probe,const std::vector<D3D9ReplaySnapshot>& draws) {
    const auto native=probe.native,candidate=probe.candidate;
    for(unsigned repeat=1;repeat<=3;++repeat)
        if(!probe.Render("repeat"+std::to_string(repeat),draws) || probe.native!=native || probe.candidate!=candidate)return false;
    return true;
}
inline std::vector<std::pair<std::string,explicit_clip_geometry::Policy>> Policies() {
    using R=explicit_clip_geometry::Rounding;
    return {{"deferred",{R::Deferred,15}},{"nearest",{R::Nearest,15}},{"zero",{R::Zero,15}},
        {"down",{R::Down,15}},{"up",{R::Up,15}},{"nearest_z",{R::Nearest,4}},{"nearest_xyw",{R::Nearest,11}},
        {"nearest_x",{R::Nearest,1}},{"nearest_y",{R::Nearest,2}},{"nearest_w",{R::Nearest,8}}};
}
inline void RoundingHeaders(std::ofstream& policies,std::ofstream& trace) {
    policies<<"variant,triangle,guardPixels,policy,mask,intersections\n";
    trace<<"variant,triangle,intersection,plane,beforeX,beforeY,beforeZ,beforeW,afterX,afterY,afterZ,afterW\n";
    trace<<std::setprecision(17);
}
inline void RoundingRows(std::ofstream& policies,std::ofstream& trace,const std::string& variant,unsigned triangle,unsigned guard,
        const std::string& name,explicit_clip_geometry::Policy policy,const std::vector<explicit_clip_geometry::Intersection>& intersections) {
    policies<<variant<<","<<triangle<<","<<guard<<","<<name<<","<<policy.mask<<","<<intersections.size()<<"\n";
    for(unsigned n=0;n<intersections.size();++n){trace<<variant<<","<<triangle<<","<<n<<","<<intersections[n].plane;
        for(double v:intersections[n].before)trace<<","<<v;for(double v:intersections[n].after)trace<<","<<v;trace<<"\n";}
}
inline void StageHeaders(std::ofstream& stream) {
    stream<<"variant,triangle,geometry,center,viewportX,viewportY,width,height,minDepth,maxDepth,shaderShift\n";
}
inline std::string Base(const std::string& name){return name.substr(0,name.rfind('_'));}
inline void StageRows(std::ofstream& stream,const std::string& name,unsigned triangle,bool viewportCenter,const D3DVIEWPORT9& region) {
    stream<<name<<","<<triangle<<","<<Base(name)<<","<<(viewportCenter?"viewport":"shader")<<","<<region.X+(viewportCenter?.5:0)<<","<<region.Y+(viewportCenter?.5:0)
        <<","<<region.Width<<","<<region.Height<<","<<region.MinZ<<","<<region.MaxZ<<","<<!viewportCenter<<"\n";
}
inline bool CaptureStage(SharedClipDepthRenderer& renderer,const std::vector<Clip>& vertices,const std::filesystem::path& output,const std::string& name) {
    std::vector<Clip> first,repeated;if(!renderer.Capture(vertices,first))return false;
    for(unsigned repeat=0;repeat<3;++repeat)if(!renderer.Capture(vertices,repeated) || repeated!=first)return false;
    Save(output/(name+".shader_clip.bin"),first.data(),first.size()*16);return true;
}
inline int Lines(HWND window,const char* archive,const char* previousPath,const char* output,const char* roundingReference=nullptr,const char* stageReference=nullptr) {
    ground_history_isolation::Archive a;CHECK(a.Load(archive,1));ground_history_isolation::Probe probe(window,a,output);CHECK(probe.Initialize());
    CHECK(probe.Render("original",a.draws,true));CHECK(RepeatBaseline(probe,a.draws));
    auto line=ground_endpoint_depth::Line18(a.draws[0]);std::vector<Clip> raw,final,previous;
    CHECK(CaptureDepthVertexShader(line,final,&raw,true,3,nullptr,nullptr,nullptr,true));const std::filesystem::path prior(previousPath);
    CHECK(Read(prior/"candidate.raw_clip.bin",previous) && previous==raw);Geometry(probe.output,"source",raw);
    CHECK(!roundingReference || !stageReference);
    struct Variant {std::string name;std::vector<Clip> vertices;unsigned guard;bool viewportCenter=false;};
    std::vector<Variant> variants{{"raw",raw,0}};
    std::ofstream policies,trace;
    if(stageReference){variants.clear();for(const std::string base:{"raw","near_far","six_plane","guard2"}){
            const unsigned guard=base=="guard2"?2:0;const auto vertices=base=="raw"?raw:explicit_clip_geometry::Line(raw,base=="near_far"?explicit_clip_geometry::NearFarPlanes():explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard));
            CHECK(vertices.size()==2);if(guard)CHECK(explicit_clip_geometry::Visible(vertices,a.region.Width,a.region.Height,true));
            for(bool viewportCenter:{false,true})variants.push_back({base+(viewportCenter?"_viewport":"_shader"),vertices,guard,viewportCenter});}
    }else if(roundingReference){policies.open(probe.output/"rounding.csv");trace.open(probe.output/"intersections.csv");CHECK(policies && trace);RoundingHeaders(policies,trace);
        for(unsigned guard:{0u,2u})for(const auto& policy:Policies()){
            const auto base=guard?"guard2":"canonical";const auto name=std::string(base)+"_"+policy.first;std::vector<explicit_clip_geometry::Intersection> intersections;
            const auto vertices=explicit_clip_geometry::Line(raw,explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard),policy.second,&intersections);CHECK(vertices.size()==2);
            if(guard)CHECK(explicit_clip_geometry::Visible(vertices,a.region.Width,a.region.Height,true));
            if(policy.first=="deferred")CHECK(RegionMatches(std::vector<unsigned char>(reinterpret_cast<const unsigned char*>(vertices.data()),reinterpret_cast<const unsigned char*>(vertices.data())+vertices.size()*16),std::filesystem::path(roundingReference)/(std::string(base)+".clip.bin")));
            variants.push_back({name,vertices,guard});RoundingRows(policies,trace,name,0,guard,policy.first,policy.second,intersections);}
    }else for(unsigned guard:{0u,2u,8u}){const auto vertices=explicit_clip_geometry::Line(raw,explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard));CHECK(vertices.size()==2);
        if(guard)CHECK(explicit_clip_geometry::Visible(vertices,a.region.Width,a.region.Height,true));
        const std::string name=guard?"guard"+std::to_string(guard):"canonical";variants.push_back({name,vertices,guard});
        auto reversed=vertices;std::reverse(reversed.begin(),reversed.end());variants.push_back({name+"_reverse",reversed,guard});}
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,a.width,a.height,&a.region));
    std::unique_ptr<SharedClipDepthRenderer> shifted;std::ofstream stages;
    if(stageReference){shifted=std::make_unique<SharedClipDepthRenderer>();CHECK(shifted->Initialize(window,a.width,a.height,&a.region,true));stages.open(probe.output/"stages.csv");StageHeaders(stages);CHECK(stages);}
    std::ofstream csv(probe.output/"line_controls.csv"),pixels(probe.output/"line_pixels.csv");
    csv<<"variant,guardPixels,vertices,differentPixels,maxDelta,firstX,firstY,nativeChangedFromRaw,candidateChangedFromRaw,nativeHash,candidateHash\n";
    pixels<<"variant,x,y,nativeB,nativeG,nativeR,nativeA,candidateB,candidateG,candidateR,candidateA\n";
    std::vector<unsigned char> baselineN,baselineR;
    for(const auto& variant:variants){Geometry(probe.output,variant.name,variant.vertices);auto& renderer=variant.viewportCenter?*shifted:shared;
        if(stageReference){CHECK(CaptureStage(renderer,variant.vertices,probe.output,variant.name));StageRows(stages,variant.name,0,variant.viewportCenter,a.region);}
        RgbaImage n,r;CHECK(renderer.RenderLine(variant.vertices,n,r) && renderer.CheckViewport());
        const auto native=scene_prefix_diagnostic::Crop(n,a.region),candidate=scene_prefix_diagnostic::Crop(r,a.region);
        if(variant.name=="raw" || variant.name=="raw_shader"){baselineN=native;baselineR=candidate;CHECK(RegionMatches(native,prior/"common_clip.native.bgra") && RegionMatches(candidate,prior/"common_clip.candidate.bgra"));}
        if(stageReference && !variant.viewportCenter && Base(variant.name)!="near_far"){const auto base=Base(variant.name);const auto previous=base=="six_plane"?"canonical":base.c_str();
            if(base!="raw")CHECK(RegionMatches(native,std::filesystem::path(stageReference)/(std::string(previous)+".native.bgra")) && RegionMatches(candidate,std::filesystem::path(stageReference)/(std::string(previous)+".candidate.bgra")));}
        if(roundingReference && variant.name.find("_deferred")!=std::string::npos){const auto base=variant.guard?"guard2":"canonical";
            CHECK(RegionMatches(native,std::filesystem::path(roundingReference)/(std::string(base)+".native.bgra")) && RegionMatches(candidate,std::filesystem::path(roundingReference)/(std::string(base)+".candidate.bgra")));}
        for(unsigned repeat=0;repeat<3;++repeat){CHECK(renderer.RenderLine(variant.vertices,n,r) && renderer.CheckViewport());CHECK(scene_prefix_diagnostic::Crop(n,a.region)==native && scene_prefix_diagnostic::Crop(r,a.region)==candidate);}
        unsigned changed=0,maximum=0,first=0;for(unsigned p=0;p<native.size()/4;++p){unsigned delta=0;for(unsigned k=0;k<4;++k)delta=(std::max)(delta,unsigned(std::abs(int(native[p*4+k])-candidate[p*4+k])));
            if(delta){if(!changed)first=p;++changed;pixels<<variant.name<<","<<a.region.X+p%a.region.Width<<","<<a.region.Y+p/a.region.Width;
                for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(native[p*4+k]);for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(candidate[p*4+k]);pixels<<"\n";}maximum=(std::max)(maximum,delta);}
        csv<<variant.name<<","<<variant.guard<<","<<variant.vertices.size()<<","<<changed<<","<<maximum<<","<<a.region.X+first%a.region.Width<<","<<a.region.Y+first/a.region.Width
            <<","<<Difference(native,baselineN)<<","<<Difference(candidate,baselineR)<<","<<scene_prefix_diagnostic::Hash(native)<<","<<scene_prefix_diagnostic::Hash(candidate)<<"\n";csv.flush();pixels.flush();
        Save(probe.output/(variant.name+".native.bgra"),native.data(),native.size());Save(probe.output/(variant.name+".candidate.bgra"),candidate.data(),candidate.size());
        std::printf("explicitLine variant=%s guard=%u differentPixels=%u maxDelta=%u repeatExact=1\n",variant.name.c_str(),variant.guard,changed,maximum);std::fflush(stdout);
    }
    std::ofstream summary(probe.output/"clip_summary.txt");summary<<"variants="<<variants.size()<<" repeats=3 priorRawExact=1 CPUIntersection=double intersectionRounding="<<bool(roundingReference)<<" centerStages="<<bool(stageReference)<<" rawNativeVertexCapture=0 productionActivation=0\n";
    if(roundingReference)CHECK(policies && trace);
    if(stageReference)CHECK(stages);
    CHECK(csv && pixels && summary);CHECK(probe.Finish());return 0;
}
inline int Depth(HWND window,const char* archive,const char* previousPath,const char* output,const char* roundingReference=nullptr,const char* stageReference=nullptr) {
    ground_history_isolation::Archive a;CHECK(a.Load(archive,6));ground_history_isolation::Probe probe(window,a,output);CHECK(probe.Initialize());CHECK(probe.Render("original",a.draws,true));
    CHECK(RepeatBaseline(probe,a.draws));
    const std::filesystem::path previous(previousPath);std::array<std::vector<Clip>,2> raw;
    for(unsigned t=0;t<2;++t){auto triangle=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(a.draws[t?5:1],t?1141:1,1));
        std::vector<Clip> final,observed;CHECK(CaptureDepthVertexShader(triangle,final,&observed,true,3,nullptr,nullptr,nullptr,true));
        CHECK(Read(previous/("triangle"+std::to_string(t)+".raw_clip.bin"),raw[t]) && observed==raw[t]);Geometry(probe.output,"source_t"+std::to_string(t),raw[t]);}
    CHECK(!roundingReference || !stageReference);
    struct Variant {std::string name;unsigned guard=0,anchor=0;std::array<std::vector<Clip>,2> vertices;bool viewportCenter=false;};
    std::vector<Variant> variants{{"raw",0,0,raw}};
    std::ofstream policies,trace;
    if(stageReference){variants.clear();for(const std::string base:{"raw","near_far","six_plane","guard2"})for(bool viewportCenter:{false,true}){
            Variant v;v.name=base+(viewportCenter?"_viewport":"_shader");v.guard=base=="guard2"?2:0;v.viewportCenter=viewportCenter;
            for(unsigned t=0;t<2;++t){if(base=="raw")v.vertices[t]=raw[t];else{
                    const auto polygon=explicit_clip_geometry::Polygon(raw[t],base=="near_far"?explicit_clip_geometry::NearFarPlanes():explicit_clip_geometry::Planes(a.region.Width,a.region.Height,v.guard));CHECK(polygon.size()>=3);
                    Geometry(probe.output,v.name+"_polygon_t"+std::to_string(t),polygon);v.vertices[t]=explicit_clip_geometry::Fan(polygon);}
                if(v.guard)CHECK(explicit_clip_geometry::Visible(v.vertices[t],a.region.Width,a.region.Height,true));}
            variants.push_back(v);}
    }else if(roundingReference){policies.open(probe.output/"rounding.csv");trace.open(probe.output/"intersections.csv");CHECK(policies && trace);RoundingHeaders(policies,trace);
        for(unsigned guard:{0u,2u})for(const auto& policy:Policies()){Variant v;const auto base=guard?"guard2":"canonical";v.name=std::string(base)+"_"+policy.first;v.guard=guard;
            for(unsigned t=0;t<2;++t){std::vector<explicit_clip_geometry::Intersection> intersections;
                const auto polygon=explicit_clip_geometry::Polygon(raw[t],explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard),policy.second,&intersections);
                const auto standard=explicit_clip_geometry::Polygon(raw[t],explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard));CHECK(polygon.size()==standard.size());
                Geometry(probe.output,v.name+"_polygon_t"+std::to_string(t),polygon);v.vertices[t]=explicit_clip_geometry::Fan(polygon);
                if(guard)CHECK(explicit_clip_geometry::Visible(v.vertices[t],a.region.Width,a.region.Height,true));
                if(policy.first=="deferred"){std::vector<Clip> expected;CHECK(Read(std::filesystem::path(roundingReference)/(std::string(base)+"_t"+std::to_string(t)+".clip.bin"),expected) && expected==v.vertices[t]);}
                RoundingRows(policies,trace,v.name,t,guard,policy.first,policy.second,intersections);}
            variants.push_back(v);}
    }else for(unsigned guard:{0u,2u,8u}){Variant v;v.name=guard?"guard"+std::to_string(guard):"canonical";v.guard=guard;
        for(unsigned t=0;t<2;++t){const auto polygon=explicit_clip_geometry::Polygon(raw[t],explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard));CHECK(polygon.size()>=3);
            Geometry(probe.output,v.name+"_polygon_t"+std::to_string(t),polygon);v.vertices[t]=explicit_clip_geometry::Fan(polygon);
            if(guard)CHECK(explicit_clip_geometry::Visible(v.vertices[t],a.region.Width,a.region.Height,true));}
        variants.push_back(v);
        if(guard==2){v.name="guard2_anchor1";v.anchor=1;for(unsigned t=0;t<2;++t)v.vertices[t]=explicit_clip_geometry::Fan(explicit_clip_geometry::Polygon(raw[t],explicit_clip_geometry::Planes(a.region.Width,a.region.Height,guard)),1);variants.push_back(v);}}
    // Retain the earlier coverage-selected coordinates, never select by agreement.
    std::vector<std::array<unsigned,2>> points;std::ifstream prior(previous/"thresholds.csv");std::string line;CHECK(std::getline(prior,line));
    while(std::getline(prior,line)){char path[64];unsigned t,p,x,y,b9,b11;char e9,e11;unsigned repeat;
        CHECK(std::sscanf(line.c_str(),"%63[^,],%u,%u,%u,%u,%u,%u,%c,%c,%u",path,&t,&p,&x,&y,&b9,&b11,&e9,&e11,&repeat)==10);
        if(std::string(path)=="shared_clip" && t==0){CHECK(p==points.size());points.push_back({x,y});}}
    CHECK(points.size()==3);SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,a.width,a.height,&a.region));
    std::unique_ptr<SharedClipDepthRenderer> shifted;std::ofstream stages;
    if(stageReference){shifted=std::make_unique<SharedClipDepthRenderer>();CHECK(shifted->Initialize(window,a.width,a.height,&a.region,true));stages.open(probe.output/"stages.csv");StageHeaders(stages);CHECK(stages);}
    std::ofstream thresholds(probe.output/"thresholds.csv"),queries(probe.output/"queries.csv"),geometry(probe.output/"geometry.csv");
    thresholds<<"variant,triangle,point,x,y,dx9ThresholdBits,dx11ThresholdBits,repeatExact\n";
    queries<<"variant,triangle,point,x,y,bits,comparison,fresh,dx9,dx11\n";
    geometry<<"variant,triangle,guardPixels,anchor,vertices,strictInterior\n";
    unsigned measured=0,queryCount=0;
    for(const auto& variant:variants)for(unsigned t=0;t<2;++t){const auto& vertices=variant.vertices[t];Geometry(probe.output,variant.name+"_t"+std::to_string(t),vertices);
        auto& renderer=variant.viewportCenter?*shifted:shared;
        if(stageReference){CHECK(CaptureStage(renderer,vertices,probe.output,variant.name+"_t"+std::to_string(t)));StageRows(stages,variant.name,t,variant.viewportCenter,a.region);}
        geometry<<variant.name<<","<<t<<","<<variant.guard<<","<<variant.anchor<<","<<vertices.size()<<","<<explicit_clip_geometry::Visible(vertices,a.region.Width,a.region.Height,true)<<"\n";
        for(unsigned p=0;p<points.size();++p){const auto xy=points[p];std::map<std::pair<unsigned,bool>,std::array<char,2>> cache;
            auto relation=[&](unsigned bits,bool equal,std::array<char,2>& answer,bool fresh=false){const auto key=std::make_pair(bits,equal);auto old=cache.find(key);
                if(!fresh && old!=cache.end()){answer=old->second;return true;}RgbaImage n,r;
                if(!renderer.Render(vertices,ground_endpoint_depth::Float(bits),equal,n,r) || !renderer.CheckViewport())return false;
                answer={ground_endpoint_depth::Color(n,xy[0],xy[1]),ground_endpoint_depth::Color(r,xy[0],xy[1])};
                if(answer[0]=='B' || answer[1]=='B' || (old!=cache.end() && old->second!=answer))return false;cache[key]=answer;
                queries<<variant.name<<","<<t<<","<<p<<","<<xy[0]<<","<<xy[1]<<","<<bits<<","<<(equal?"Equal":"Less")<<","<<fresh<<","<<answer[0]<<","<<answer[1]<<"\n";queries.flush();++queryCount;
                if(fresh){const std::string name=variant.name+"_t"+std::to_string(t)+"_p"+std::to_string(p)+"_b"+std::to_string(bits)+(equal?"_equal":"_less");
                    D3DVIEWPORT9 roi{xy[0]-2,xy[1]-2,5,5,0,1};const auto a=scene_prefix_diagnostic::Crop(n,roi),b=scene_prefix_diagnostic::Crop(r,roi);
                    Save(probe.output/(name+".native.bgra"),a.data(),a.size());Save(probe.output/(name+".candidate.bgra"),b.data(),b.size());}return bool(queries);};
            const unsigned lower=ground_endpoint_depth::Bits(.9f),upper=ground_endpoint_depth::Bits(.99999f);std::array<char,2> answer;unsigned boundary[2];
            CHECK(relation(lower,false,answer) && answer==(std::array<char,2>{'G','G'}));CHECK(relation(upper,false,answer) && answer==(std::array<char,2>{'R','R'}));
            for(unsigned backend=0;backend<2;++backend){unsigned lo=lower,hi=upper;while(hi-lo>1){const auto mid=lo+(hi-lo)/2;CHECK(relation(mid,false,answer));if(answer[backend]=='G')lo=mid;else hi=mid;}boundary[backend]=hi;CHECK(relation(hi,true,answer) && answer[backend]=='G');}
            for(unsigned repeat=0;repeat<3;++repeat)for(unsigned backend=0;backend<(boundary[0]==boundary[1]?1u:2u);++backend){const auto bits=boundary[backend];
                CHECK(relation(bits,true,answer,true) && answer[backend]=='G');CHECK(relation(bits-1,false,answer,true) && answer[backend]=='G');CHECK(relation(bits,false,answer,true) && answer[backend]=='R');}
            thresholds<<variant.name<<","<<t<<","<<p<<","<<xy[0]<<","<<xy[1]<<","<<boundary[0]<<","<<boundary[1]<<",1\n";thresholds.flush();++measured;
            std::printf("explicitDepth variant=%s triangle=%u point=%u dx9Bits=%u dx11Bits=%u strictInterior=%u repeatExact=1\n",variant.name.c_str(),t,p,boundary[0],boundary[1],explicit_clip_geometry::Visible(vertices,a.region.Width,a.region.Height,true));std::fflush(stdout);
        }}
    std::ofstream summary(probe.output/"clip_summary.txt");summary<<"variants="<<variants.size()<<" measurements="<<measured<<" queries="<<queryCount<<" repeats=3 priorClipExact=1 rawD24Readback=0 CPUIntersection=double intersectionRounding="<<bool(roundingReference)<<" centerStages="<<bool(stageReference)<<" productionActivation=0\n";
    if(roundingReference)CHECK(policies && trace);
    if(stageReference)CHECK(stages);
    CHECK(thresholds && queries && geometry && summary);CHECK(probe.Finish());return 0;
}
}
