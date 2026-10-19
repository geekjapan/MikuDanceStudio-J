#pragma once
namespace accessory_alpha_history {
// Independent saved-data reduction. Mutations apply equally to both APIs;
// this diagnostic reports differences and never relaxes an acceptance gate.
inline int Run(HWND window,const char* archivePath,const char* outputPath){
    const std::filesystem::path archive(archivePath),output(outputPath);std::filesystem::create_directories(output);
    std::vector<D3D9ReplaySnapshot> captured(66);
    unsigned width=0,height=0;DWORD clear=0;
    for(unsigned n=0;n<captured.size();++n){const auto path=archive/("history_replay.scene_prefix.draw"+std::to_string(n+1)+".state");
        CHECK(ReadUntexturedReduction(path,captured[n],true));
        captured[n].accessoryMaterial=n>=2 && n<=20 || n>=61;
        if(!n){std::ifstream file(path);std::string line;while(std::getline(file,line)){
            unsigned color=0,depth=0,samples=0,quality=0;
            std::sscanf(line.c_str(),"TARGET width=%u height=%u colorFormat=%u depthFormat=%u samples=%u quality=%u",&width,&height,&color,&depth,&samples,&quality);
            unsigned flags=0,stencil=0;float z=0;std::sscanf(line.c_str(),"CLEAR flags=%u color=%lu depth=%f stencil=%u",&flags,&clear,&z,&stencil);}}
    }
    CHECK(width && height);SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(bundle);
    std::ofstream report(output/"trace.csv");report<<"scenario,repeat,draws,differentPixels,rgbDifferent,alphaDifferent,maxAlphaDelta\n";
    const char* scenarios[]={"history","history_no_depth","history_no_stencil","history_no_alpha_test","isolated","isolated_no_depth","isolated_no_alpha_test","history_no_ground_depth_write","history_no_model_depth_write","history_no_earlier_accessory_depth_write","history_no_front_accessory_depth_write","history_no_tail_accessory_depth_write","history_no_draw62_depth_write","history_no_draw63_depth_write","history_no_draw64_depth_write","history_no_draw65_depth_write"};
    for(unsigned scenario=0;scenario<16;++scenario)for(unsigned repeat=0;repeat<3;++repeat){
        auto snapshots=scenario>=4 && scenario<=6?std::vector<D3D9ReplaySnapshot>{captured.back()}:captured;
        const auto set=[&](unsigned key,DWORD value){for(auto& state:snapshots.back().renderStates)if(state.key==key)state.value=value;};
        if(scenario==1 || scenario==5)set(D3DRS_ZENABLE,FALSE);
        if(scenario==2)set(D3DRS_STENCILENABLE,FALSE);
        if(scenario==3 || scenario==6)set(D3DRS_ALPHATESTENABLE,FALSE);
        if(scenario>=7)for(unsigned n=0;n+1<snapshots.size();++n){
            const bool selected=scenario==7?n<2:scenario==8?n>=21 && n<=60:
                scenario==9?(n>=2 && n<=20 || n>=61):scenario==10?n>=2 && n<=20:
                scenario==11?n>=61:n==scenario+49;
            if(selected)for(auto& state:snapshots[n].renderStates)if(state.key==D3DRS_ZWRITEENABLE)state.value=FALSE;
        }
        ModelReplayStream stream;stream.target.width=width;stream.target.height=height;
        stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& snapshot:snapshots)CHECK(AppendD3D9ReplaySnapshot(stream,snapshot,true));stream.complete=true;
        RgbaImage native,candidate;CHECK(NativeImage(window,snapshots,unsigned(snapshots.size()),native,nullptr,width,height,clear));
        CHECK(ReplayD3D11ModelPrefix(*bundle.device,stream,snapshots.size(),candidate));
        const auto& area=captured[0].viewport;unsigned different=0,rgb=0,alpha=0,maximum=0;
        for(unsigned y=area.Y;y<area.Y+area.Height;++y)for(unsigned x=area.X;x<area.X+area.Width;++x){const auto at=(std::size_t(y)*width+x)*4;
            const auto* a=native.pixels.data()+at;const auto* b=candidate.pixels.data()+at;
            different+=std::memcmp(a,b,4)!=0;rgb+=std::memcmp(a,b,3)!=0;alpha+=a[3]!=b[3];maximum=(std::max)(maximum,unsigned(std::abs(int(a[3])-int(b[3]))));}
        report<<scenarios[scenario]<<","<<repeat<<","<<snapshots.size()<<","<<different<<","<<rgb<<","<<alpha<<","<<maximum<<"\n";report.flush();
    }
    CHECK(bundle.swapchain->Retire());std::printf("accessory alpha history reduction capturedDraw=66 repeats=3 productionActivation=0\n");return 0;
}
}
