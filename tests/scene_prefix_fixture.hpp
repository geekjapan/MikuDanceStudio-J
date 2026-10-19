#pragma once

namespace scene_prefix_diagnostic {
inline std::vector<unsigned char> Crop(const RgbaImage& image,const D3DVIEWPORT9& region) {
    if(!region.Width || !region.Height || region.X+region.Width>image.width || region.Y+region.Height>image.height)return {};
    std::vector<unsigned char> out(std::size_t(region.Width)*region.Height*4);
    for(unsigned y=0;y<region.Height;++y)for(unsigned x=0;x<region.Width;++x){const auto src=(std::size_t(y+region.Y)*image.width+x+region.X)*4,at=(std::size_t(y)*region.Width+x)*4;
        out[at]=image.pixels[src+2];out[at+1]=image.pixels[src+1];out[at+2]=image.pixels[src];out[at+3]=image.pixels[src+3];}return out;
}
inline std::uint64_t Hash(const std::vector<unsigned char>& bytes) {
    std::uint64_t h=14695981039346656037ull;for(auto b:bytes)h=(h^b)*1099511628211ull;return h;
}
inline int Run(HWND window,const char* archivePath,const char* outputPath,bool viewportCenter=false,bool fusedXY=false) {
    const std::filesystem::path archive(archivePath),output(outputPath);std::filesystem::create_directories(output);
    std::ifstream manifest(archive/"history_replay.scene_prefix.manifest");std::string line;CHECK(std::getline(manifest,line));
    unsigned schema=0,count=0,events=0,nativeExact=0,blockedDraw=0;char status[32]{},reason[256]{};unsigned long long blockedSequence=0;
    CHECK(std::sscanf(line.c_str(),"SCENE_PREFIX schema=%u status=%31s nativeExact=%u draws=%u events=%u blockedDraw=%u blockedSequence=%llu reason=%255s",&schema,status,&nativeExact,&count,&events,&blockedDraw,&blockedSequence,reason)==8 && schema==1);
    if(std::string(status)!="READY" || !nativeExact){std::ofstream report(output/"blocked.txt");report<<line<<"\n";
        std::printf("scenePrefix BLOCKED draw=%u sequence=%llu reason=%s nativeExact=%u\n",blockedDraw,blockedSequence,reason,nativeExact);return 31;}
    CHECK(count && count<=512 && events<=10000);
    std::vector<std::string> passes;while(std::getline(manifest,line)){unsigned draw;char pass[128]{};CHECK(std::sscanf(line.c_str(),"PASS draw=%u name=%127s",&draw,pass)==2 && draw==passes.size()+1);passes.push_back(pass);}CHECK(passes.size()==count);
    std::vector<D3D9ReplaySnapshot> snapshots(count);unsigned width=0,height=0;DWORD clear=0;D3DVIEWPORT9 region{};
    ModelReplayStream stream;std::vector<std::uint64_t> drawSequences;
    for(unsigned draw=0;draw<count;++draw){const auto file=archive/("history_replay.scene_prefix.draw"+std::to_string(draw+1)+".state");
        CHECK(ReadUntexturedReduction(file,snapshots[draw],true));
        std::ifstream input(file);unsigned targetWidth=0,targetHeight=0,color=0,depthFormat=0,samples=0,quality=0,flags=0,stencil=0;DWORD targetClear=0;float depth=0;bool target=false,knownClear=false;
        while(std::getline(input,line)){
            if(std::sscanf(line.c_str(),"TARGET width=%u height=%u colorFormat=%u depthFormat=%u samples=%u quality=%u",&targetWidth,&targetHeight,&color,&depthFormat,&samples,&quality)==6)target=true;
            if(std::sscanf(line.c_str(),"CLEAR flags=%u color=%lu depth=%f stencil=%u",&flags,&targetClear,&depth,&stencil)==4)knownClear=true;
        }
        CHECK(target && knownClear && color==D3DFMT_A8R8G8B8 && depthFormat==D3DFMT_D24S8 && !samples && !quality && flags==7 && depth==1 && !stencil);
        if(!draw){width=targetWidth;height=targetHeight;clear=targetClear;region=snapshots[0].viewport;
            CHECK(width<=4096 && height<=4096 && ValidModelViewport({region.X,region.Y,region.Width,region.Height,region.MinZ,region.MaxZ},width,height));
            stream.target.width=width;stream.target.height=height;stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};
            stream.initializedRegion=ModelViewport{region.X,region.Y,region.Width,region.Height,region.MinZ,region.MaxZ};stream.events.push_back({1,ModelReplayOp::Clear});}
        CHECK(targetWidth==width && targetHeight==height && targetClear==clear);
        const auto converted=AppendD3D9ReplaySnapshot(stream,snapshots[draw],true);
        if(!converted){std::fprintf(stderr,"scenePrefix conversion BLOCKED draw=%u pass=%s reason=%s\n",draw+1,passes[draw].c_str(),converted.reason.c_str());return 31;}
        stream.events.back().label=passes[draw];drawSequences.push_back(stream.events.back().sequence);
    }
    stream.complete=true;const auto validation=ValidateModelReplay(stream);CHECK(validation && validation.draws==count && stream.events.size()==events);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    CHECK(!fusedXY || viewportCenter);
    auto bundle=fusedXY?CreateD3D11FusedXYCandidateDevice(desc,D3D11Driver::Hardware):viewportCenter?CreateD3D11ViewportCenterCandidateDevice(desc,D3D11Driver::Hardware):CreateD3D11NormalCandidateDevice(desc,D3D11Driver::Hardware);CHECK(bundle);
    if(viewportCenter){std::ofstream mode(output/"center_mode.txt");mode<<"center=viewport shaderShift=0 viewportShiftX=0.5 viewportShiftY=0.5 geometryUnchanged=1 CPUClipping=0 productionActivation=0\n";CHECK(mode);}
    if(fusedXY){std::ofstream policy(output/"xy_policy.txt");policy<<"fusedXY=1 geometryUnchanged=1 nativeVertexCapture=0 productionActivation=0\n";CHECK(policy);}
    std::printf("scenePrefix adapter=%s draws=%u events=%u resources=%zu samples=1 region=%u,%u,%u,%u productionActivation=0\n",bundle.adapterName.c_str(),count,events,stream.resources.size(),region.X,region.Y,region.Width,region.Height);
    std::ofstream trace(output/"trace.csv");trace<<"afterDraw,pass,event,nativeDifferentPixels,candidateDifferentPixels,maxDelta,firstX,firstY,nativeHash,candidateHash\n";
    unsigned nativeFailures=0,candidateFailures=0,firstDifference=0;std::vector<unsigned char> finalCandidate;
    for(unsigned boundary=0;boundary<=count;++boundary){
        const auto actualPath=archive/(boundary==count?"history_replay.scene_prefix.final.bgra":"history_replay.scene_prefix.draw"+std::to_string(boundary+1)+".before.bgra");
        std::ifstream actualFile(actualPath,std::ios::binary);const std::vector<unsigned char> actual(std::istreambuf_iterator<char>{actualFile},{});CHECK(actual.size()==std::size_t(region.Width)*region.Height*4);
        RgbaImage native;CHECK(NativeImage(window,snapshots,boundary,native,nullptr,width,height,clear));const auto nativeCrop=Crop(native,region);CHECK(nativeCrop.size()==actual.size());
        RgbaImage candidate;const auto replay=ReplayD3D11WCandidatePrefix(*bundle.device,stream,boundary,candidate);
        if(!replay){std::fprintf(stderr,"scenePrefix BLOCKED draw=%u sequence=%llu reason=%s\n",boundary,static_cast<unsigned long long>(replay.sequence),replay.reason.c_str());return 31;}
        const auto crop=Crop(candidate,region);CHECK(crop.size()==actual.size());unsigned nativeDiff=0,candidateDiff=0,maximum=0,first=0;
        for(unsigned pixel=0;pixel<actual.size()/4;++pixel){nativeDiff+=std::memcmp(actual.data()+pixel*4,nativeCrop.data()+pixel*4,4)!=0;unsigned delta=0;
            for(unsigned channel=0;channel<4;++channel)delta=(std::max)(delta,unsigned(std::abs(int(actual[pixel*4+channel])-crop[pixel*4+channel])));
            if(delta){if(!candidateDiff)first=pixel;++candidateDiff;}maximum=(std::max)(maximum,delta);}
        if(nativeDiff)++nativeFailures;if(candidateDiff){if(!candidateFailures)firstDifference=boundary;++candidateFailures;}
        trace<<boundary<<","<<(boundary?passes[boundary-1]:"clear")<<","<<(boundary?drawSequences[boundary-1]:1)<<","<<nativeDiff<<","<<candidateDiff<<","<<maximum<<","<<region.X+first%region.Width<<","<<region.Y+first/region.Width<<","<<Hash(actual)<<","<<Hash(crop)<<"\n";trace.flush();
        std::ofstream image(output/("after"+std::to_string(boundary)+".bgra"),std::ios::binary);image.write(reinterpret_cast<const char*>(crop.data()),crop.size());CHECK(image);
        std::printf("scenePrefix afterDraw=%u pass=%s nativeDifferentPixels=%u candidateDifferentPixels=%u maxDelta=%u first=%u,%u\n",boundary,boundary?passes[boundary-1].c_str():"clear",nativeDiff,candidateDiff,maximum,region.X+first%region.Width,region.Y+first/region.Width);std::fflush(stdout);
        if(boundary==count)finalCandidate=crop;
    }
    for(unsigned repetition=1;repetition<=(viewportCenter?3u:1u);++repetition){RgbaImage repeat;CHECK(ReplayD3D11WCandidatePrefix(*bundle.device,stream,count,repeat));const auto bytes=Crop(repeat,region);CHECK(bytes==finalCandidate);
        if(viewportCenter){std::ofstream image(output/("repeat"+std::to_string(repetition)+".bgra"),std::ios::binary);image.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());CHECK(image);}}
    // Draw-alone controls distinguish a batch's own shading/raster behavior
    // from inherited depth/stencil/blend history. They never accept a prefix.
    std::ofstream isolated(output/"isolated.csv");isolated<<"draw,pass,differentPixels,maxDelta,nativeHash,candidateHash\n";
    unsigned isolatedFailures=0;
    for(unsigned draw=0;draw<count;++draw) {
        ModelReplayStream single;single.target=stream.target;single.clear=stream.clear;single.initializedRegion=stream.initializedRegion;single.events.push_back({1,ModelReplayOp::Clear});
        CHECK(AppendD3D9ReplaySnapshot(single,snapshots[draw],true));single.complete=true;
        RgbaImage native,candidate;CHECK(NativeImage(window,{snapshots[draw]},1,native,nullptr,width,height,clear));
        CHECK(ReplayD3D11WCandidatePrefix(*bundle.device,single,1,candidate));const auto actual=Crop(native,region),image=Crop(candidate,region);CHECK(actual.size()==image.size());
        unsigned different=0,maximum=0;for(unsigned pixel=0;pixel<actual.size()/4;++pixel){unsigned delta=0;for(unsigned channel=0;channel<4;++channel)delta=(std::max)(delta,unsigned(std::abs(int(actual[pixel*4+channel])-image[pixel*4+channel])));
            different+=delta!=0;maximum=(std::max)(maximum,delta);}
        isolatedFailures+=different!=0;isolated<<draw+1<<","<<passes[draw]<<","<<different<<","<<maximum<<","<<Hash(actual)<<","<<Hash(image)<<"\n";isolated.flush();
        if(different)for(unsigned path=0;path<2;++path){const auto& bytes=path?image:actual;std::ofstream file(output/("isolated"+std::to_string(draw+1)+(path?".candidate.bgra":".native.bgra")),std::ios::binary);file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());CHECK(file);}
        std::printf("sceneIsolated draw=%u pass=%s differentPixels=%u maxDelta=%u acceptanceEligible=0\n",draw+1,passes[draw].c_str(),different,maximum);
    }
    CHECK(bundle.swapchain->Retire());CHECK(trace);
    CHECK(isolated);std::ofstream report(output/"summary.txt");report<<"SCENE_PREFIX_RESULT draws="<<count<<" boundaries="<<count+1<<" nativeFailingBoundaries="<<nativeFailures<<" candidateFailingBoundaries="<<candidateFailures<<" firstAfterDraw="<<firstDifference<<" isolatedFailingDraws="<<isolatedFailures<<" finalRepeatExact=1 finalRepeats="<<(viewportCenter?3:1)<<" productionActivation=0\n";CHECK(report);
    std::printf("scenePrefix completed boundaries=%u nativeFailures=%u candidateFailures=%u firstAfterDraw=%u finalRepeatExact=1\n",count+1,nativeFailures,candidateFailures,firstDifference);return nativeFailures || candidateFailures?32:0;
}
inline int FirstDrawControls(HWND window,const char* archivePath,const char* outputPath,unsigned selected) {
    const std::filesystem::path archive(archivePath),output(outputPath);std::filesystem::create_directories(output);CHECK(selected && selected<=512);
    std::vector<D3D9ReplaySnapshot> snapshots(selected);unsigned width=0,height=0;DWORD clear=0xffffffff;D3DVIEWPORT9 region{};
    for(unsigned n=0;n<selected;++n)CHECK(ReadUntexturedReduction(archive/("history_replay.scene_prefix.draw"+std::to_string(n+1)+".state"),snapshots[n],true));
    std::ifstream metadata(archive/"history_replay.scene_prefix.draw1.state");std::string line;unsigned c,d,s,q;bool target=false;
    while(std::getline(metadata,line))if(std::sscanf(line.c_str(),"TARGET width=%u height=%u colorFormat=%u depthFormat=%u samples=%u quality=%u",&width,&height,&c,&d,&s,&q)==6){target=c==21 && d==75 && !s && !q;break;}CHECK(target);region=snapshots[0].viewport;
    std::ofstream report(output/"controls.csv");report<<"mode,differentPixels,maxDelta,firstX,firstY,nativeHash,candidateHash\n";
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11NormalCandidateDevice(desc,D3D11Driver::Hardware);CHECK(bundle);
    const char* names[]={"original","repeat","selected_only","no_depth","no_stencil","no_specular","no_normalize","no_lighting","selected_only_no_depth","selected_only_no_stencil","before_selected","small_viewport","small_viewport_no_depth"};
    unsigned baseline=0;
    for(unsigned mode=0;mode<13;++mode){auto controls=snapshots;auto area=region;
        if(mode==2 || mode==8 || mode==9)controls.erase(controls.begin(),controls.end()-1);
        if(mode==10)controls.pop_back();
        if(mode>=11){area={274,25,670,503,0,1};CHECK(area.X+area.Width<=width && area.Y+area.Height<=height);for(auto& c:controls)c.viewport=area;}
        for(auto& snapshot:controls)for(auto& state:snapshot.renderStates){
            if((mode==3 || mode==8 || mode==12) && (state.key==D3DRS_ZENABLE || state.key==D3DRS_ZWRITEENABLE))state.value=0;
            if((mode==4 || mode==9) && state.key==D3DRS_STENCILENABLE)state.value=0;
            if(mode==5 && state.key==D3DRS_SPECULARENABLE)state.value=0;
            if(mode==6 && state.key==D3DRS_NORMALIZENORMALS)state.value=0;
            if(mode==7 && state.key==D3DRS_LIGHTING)state.value=0;
        }
        ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.clear={1,1,1,1};stream.initializedRegion=ModelViewport{area.X,area.Y,area.Width,area.Height,0,1};stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& c:controls)CHECK(AppendD3D9ReplaySnapshot(stream,c,true));stream.complete=true;
        RgbaImage native,candidate;CHECK(NativeImage(window,controls,static_cast<unsigned>(controls.size()),native,nullptr,width,height,clear));
        CHECK(ReplayD3D11WCandidatePrefix(*bundle.device,stream,controls.size(),candidate));const auto actual=Crop(native,area),image=Crop(candidate,area);CHECK(actual.size()==image.size());
        if(mode<2){std::ifstream input(archive/("history_replay.scene_prefix.draw"+std::to_string(selected+1)+".before.bgra"),std::ios::binary);const std::vector<unsigned char> saved(std::istreambuf_iterator<char>{input},{});CHECK(actual==saved);}
        unsigned different=0,maximum=0,first=0;for(unsigned n=0;n<actual.size()/4;++n){unsigned delta=0;for(unsigned k=0;k<4;++k)delta=(std::max)(delta,unsigned(std::abs(int(actual[n*4+k])-image[n*4+k])));
            if(delta){if(!different)first=n;++different;}maximum=(std::max)(maximum,delta);}
        if(!mode)baseline=different;if(mode==1)CHECK(different==baseline);
        report<<names[mode]<<","<<different<<","<<maximum<<","<<area.X+first%area.Width<<","<<area.Y+first/area.Width<<","<<Hash(actual)<<","<<Hash(image)<<"\n";report.flush();
        for(unsigned path=0;path<2;++path){const auto& bytes=path?image:actual;std::ofstream file(output/(std::string(names[mode])+(path?".candidate.bgra":".native.bgra")),std::ios::binary);file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());CHECK(file);}
        std::printf("firstDrawControls draw=%u mode=%s differentPixels=%u maxDelta=%u first=%u,%u originalInputs=%u\n",selected,names[mode],different,maximum,area.X+first%area.Width,area.Y+first/area.Width,unsigned(mode<2));
    }
    CHECK(bundle.swapchain->Retire());CHECK(report);return 0;
}
} // namespace scene_prefix_diagnostic
