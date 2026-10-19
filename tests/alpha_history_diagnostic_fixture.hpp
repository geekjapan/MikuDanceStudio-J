#pragma once
#include "mikudancestudio/rhi_scene_renderer.hpp"
#include "mikudancestudio/rhi_d3d12.hpp"
#include <sstream>

// Frozen conversion candidate; no fitted coordinates, acceptance tolerance,
// application activation, or changes to the captured resources/states.
namespace alpha_history_diagnostic {
inline int Run(HWND window,const char* archivePath,const char* outputPath,bool textureFma=false,bool specularFma=false) {
    using scene_prefix_diagnostic::Crop;using scene_prefix_diagnostic::Hash;
    const std::filesystem::path root(outputPath);CHECK(!std::filesystem::exists(root));std::filesystem::create_directories(root);
    std::ifstream manifest(std::filesystem::path(archivePath)/"history_replay.scene_prefix.manifest");std::string line,field;
    CHECK(std::getline(manifest,line));unsigned count=0;std::istringstream fields(line);
    while(fields>>field)if(field.rfind("draws=",0)==0){std::istringstream value(field.substr(6));CHECK(value>>count);}
    CHECK(count && count<=10000);ground_history_isolation::Archive archive;CHECK(archive.Load(archivePath,count));
    std::vector<std::string> passes(count);
    while(std::getline(manifest,line)) {
        unsigned draw=0;char pass[64]{};
        if(std::sscanf(line.c_str(),"PASS draw=%u name=%63s",&draw,pass)!=2)continue;
        CHECK(draw && draw<=count && passes[draw-1].empty());passes[draw-1]=pass;
    }
    for(unsigned n=0;n<count;++n){const auto& pass=passes[n];
        CHECK(pass=="ground" || pass=="accessory" || pass=="accessory_tail" || pass=="projected_shadow" || pass=="model_material" || pass=="model_outline");
        // Stage zero of an accessory is Base, not the model Toon slot.
        archive.draws[n].accessoryMaterial=pass=="accessory" || pass=="accessory_tail";
    }
    const auto& region=archive.region;std::vector<std::vector<unsigned char>> reference(count+1);
    for(unsigned n=0;n<=count;++n){const auto file=archive.path/(n==count?"history_replay.scene_prefix.final.bgra":"history_replay.scene_prefix.draw"+std::to_string(n+1)+".before.bgra");
        std::ifstream in(file,std::ios::binary);reference[n]={std::istreambuf_iterator<char>{in},{}};CHECK(reference[n].size()==std::size_t(region.Width)*region.Height*4);}
    ModelReplayStream stream;stream.target.width=archive.width;stream.target.height=archive.height;const auto c=archive.clear;
    stream.clear={((c>>16)&255)/255.f,((c>>8)&255)/255.f,(c&255)/255.f,((c>>24)&255)/255.f};
    stream.initializedRegion=ModelViewport{region.X,region.Y,region.Width,region.Height,region.MinZ,region.MaxZ};stream.events.push_back({1,ModelReplayOp::Clear});
    for(const auto& draw:archive.draws)CHECK(AppendD3D9ReplaySnapshot(stream,draw,true));stream.complete=true;CHECK(ValidateModelReplay(stream));
    std::ofstream table(root/"boundaries.csv"),pixels(root/"pixels.csv"),metadata(root/"metadata.txt");
    table<<"api,policy,phase,boundary,pass,differentPixels,maxDelta,hash,uploads,textureUploads,identity,epoch\n";
    pixels<<"api,policy,phase,boundary,x,y,nativeB,nativeG,nativeR,nativeA,actualB,actualG,actualR,actualA\n";
    metadata<<"archive="<<std::filesystem::absolute(archive.path).string()<<"\ndraws="<<count<<" width="<<archive.width<<" height="<<archive.height
        <<" region="<<region.X<<","<<region.Y<<","<<region.Width<<","<<region.Height<<" samples=1 resources="<<stream.resources.size()
        <<"\ncandidate=8994 fixed12_truncate_multiply255_round_even diagnosticTextureFma="<<textureFma<<" diagnosticSpecularFma="<<specularFma<<" applicationActivation=0\n";
    unsigned nativeFailures=0,candidateFailures=0,baselineFailures=0,observations=0;bool nativeUnavailable=false;
    auto compare=[&](const char* api,bool diagnostic,const char* phase,unsigned boundary,const RgbaImage& image,const SceneRendererStats& stats,DeviceStatus status)->int {
        const auto actual=Crop(image,region);if(actual.size()!=reference[boundary].size())return -1;unsigned different=0,maximum=0;
        for(unsigned p=0;p<actual.size()/4;++p){unsigned delta=0;
            for(unsigned k=0;k<4;++k)delta=(std::max)(delta,unsigned(std::abs(int(actual[p*4+k])-reference[boundary][p*4+k])));
            if(delta){++different;pixels<<api<<","<<diagnostic<<","<<phase<<","<<boundary<<","<<region.X+p%region.Width<<","<<region.Y+p/region.Width;
                for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(reference[boundary][p*4+k]);for(unsigned k=0;k<4;++k)pixels<<","<<unsigned(actual[p*4+k]);pixels<<"\n";}
            maximum=(std::max)(maximum,delta);
        }
        table<<api<<","<<diagnostic<<","<<phase<<","<<boundary<<","<<(boundary?passes[boundary-1]:"clear")<<","<<different<<","<<maximum<<","<<Hash(actual)
            <<","<<stats.uploads<<","<<stats.textureUploads<<","<<status.identity<<","<<status.epoch<<"\n";table.flush();pixels.flush();++observations;
        if(different){const auto file=root/(std::string(api)+"_"+std::to_string(diagnostic)+"_"+phase+"_"+std::to_string(boundary)+".bgra");
            if(!model_transform_diagnostic::Save(file,actual.data(),actual.size()))return -1;}
        return table && pixels?static_cast<int>(different):-1;
    };
    // First prove that fresh native rendering reproduces every saved boundary.
    // Each observation creates, clears and replays a fresh native target.
    {
        for(unsigned n=0;n<=count;++n){RgbaImage image;if(!NativeImage(window,archive.draws,n,image,nullptr,archive.width,archive.height,c)){nativeUnavailable=true;metadata<<"nativeReplayUnavailableAtBoundary="<<n<<"\n";break;}
            const auto different=compare("dx9",false,"prefix",n,image,{},{});CHECK(different>=0);nativeFailures+=different!=0;
            if(n%10==0){std::printf("native history boundary=%u/%u\n",n,count);std::fflush(stdout);}}
    }
    struct Window {HWND h;~Window(){DestroyWindow(h);}} twelveWindow{CreateWindowExW(0,L"STATIC",L"DX12 Alpha history",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};CHECK(twelveWindow.h);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=archive.width;desc.height=archive.height;desc.present=PresentMode::Immediate;
    // Both backends reject a diagnostic request outside the measured policy.
    const auto invalid11=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Default,true});CHECK(!invalid11 && invalid11.creationReason=="diagnostic_alpha_requires_dx9_measured");
    auto twelveDesc=desc;twelveDesc.window.handle=reinterpret_cast<std::uintptr_t>(twelveWindow.h);
    const auto invalid12=CreateD3D12Device(twelveDesc,D3D12Driver::Hardware,{{ModelCompatibility::Default,true},true});CHECK(!invalid12 && invalid12.creationReason=="diagnostic_alpha_requires_dx9_measured");
    CHECK(!ModelOptions{}.diagnosticTextureFma);
    const auto invalidTexture11=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Default,false,true});CHECK(!invalidTexture11 && invalidTexture11.creationReason=="diagnostic_texture_requires_dx9_measured");
    const auto invalidTexture12=CreateD3D12Device(twelveDesc,D3D12Driver::Hardware,{{ModelCompatibility::Default,false,true},true});CHECK(!invalidTexture12 && invalidTexture12.creationReason=="diagnostic_texture_requires_dx9_measured");
    CHECK(!ModelOptions{}.diagnosticSpecularFma);
    const auto invalidSpecular11=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Default,false,false,true});
    CHECK(!invalidSpecular11 && invalidSpecular11.creationReason=="diagnostic_specular_requires_dx9_measured");
    const auto invalidSpecular12=CreateD3D12Device(twelveDesc,D3D12Driver::Hardware,{{ModelCompatibility::Default,false,false,true},true});
    CHECK(!invalidSpecular12 && invalidSpecular12.creationReason=="diagnostic_specular_requires_dx9_measured");
    ModelReplayStream isolated;
    if(specularFma && !nativeUnavailable) {
        CHECK(count>=23 && passes[22]=="model_material");
        isolated=stream;unsigned draw=0;
        isolated.events.erase(std::remove_if(isolated.events.begin(),isolated.events.end(),[&](const ModelReplayEvent& event){return event.op==ModelReplayOp::Draw && ++draw!=23;}),isolated.events.end());
        for(std::size_t n=0;n<isolated.events.size();++n)isolated.events[n].sequence=n+1;
        CHECK(ValidateModelReplay(isolated));RgbaImage image;
        CHECK(NativeImage(window,{archive.draws[22]},1,image,nullptr,archive.width,archive.height,c));
        reference.push_back(Crop(image,region));passes.push_back("isolated_material23");
        CHECK(NativeImage(window,{archive.draws[22]},1,image,nullptr,archive.width,archive.height,c));
        CHECK(compare("dx9",false,"isolated23",count+1,image,{},{})==0);
    }
    auto replay=[&](Device& device,const char* api,bool diagnostic,const auto& replace)->int {
        SceneRenderer renderer(device);PreparedModelFrame prepared;CompletionToken completion;
        if(specularFma && !isolated.events.empty()) {
            CHECK(renderer.Prepare(1,isolated,prepared));CHECK(renderer.Submit(prepared,completion));RgbaImage image;CHECK(device.ReadModelTarget(image));
            const auto different=compare(api,diagnostic,"isolated23",count+1,image,renderer.Stats(),device.Status());CHECK(different>=0);
            (diagnostic?candidateFailures:baselineFailures)+=different!=0;
        }
        for(unsigned boundary=1;boundary<=count;++boundary){auto prefix=stream;unsigned draws=0;auto end=prefix.events.begin()+1;
            for(auto e=prefix.events.begin();e!=prefix.events.end();++e)if(e->op==ModelReplayOp::Draw && ++draws==boundary){end=e+1;break;}
            prefix.events.erase(end,prefix.events.end());const auto prep=renderer.Prepare(1,prefix,prepared);if(!prep){std::fprintf(stderr,"%s prepare boundary=%u reason=%s seq=%llu\n",api,boundary,prep.reason.c_str(),static_cast<unsigned long long>(prep.sequence));return 1;}CHECK(renderer.Submit(prepared,completion));RgbaImage image;CHECK(device.ReadModelTarget(image));
            const auto stats=renderer.Stats();CHECK(stats.uploads==stream.resources.size());const auto different=compare(api,diagnostic,"prefix",boundary,image,stats,device.Status());CHECK(different>=0);
            (diagnostic?candidateFailures:baselineFailures)+=different!=0;
            if(boundary%10==0 || different){std::printf("%s diagnostic=%u boundary=%u/%u different=%u\n",api,unsigned(diagnostic),boundary,count,different);std::fflush(stdout);}
        }
        for(unsigned n=0;n<3;++n){CHECK(renderer.Submit(prepared,completion));RgbaImage image;CHECK(device.ReadModelTarget(image));
            const auto different=compare(api,diagnostic,("repeat"+std::to_string(n+1)).c_str(),count,image,renderer.Stats(),device.Status());CHECK(different>=0);(diagnostic?candidateFailures:baselineFailures)+=different!=0;}
        if(diagnostic)for(unsigned n=0;n<3;++n){auto resized=stream;resized.target.width+=(n%2+1)*32;resized.target.height+=(n%2+1)*16;PreparedModelFrame next;
            CHECK(renderer.Prepare(1,resized,next));CHECK(!renderer.Submit(prepared,completion));CHECK(renderer.Submit(next,completion));RgbaImage image;CHECK(device.ReadModelTarget(image));
            CHECK(renderer.Stats().uploads==stream.resources.size());const auto different=compare(api,true,("resize"+std::to_string(n+1)).c_str(),count,image,renderer.Stats(),device.Status());CHECK(different>=0);candidateFailures+=different!=0;}
        if(diagnostic && specularFma) {
            // Make the old submission valid immediately before replacement;
            // an earlier target resize must not explain its later rejection.
            CHECK(renderer.Prepare(1,stream,prepared));CHECK(renderer.Submit(prepared,completion));
            Device* replacement=replace();CHECK(replacement && replacement->Status().identity!=device.Status().identity);
            CHECK(renderer.Rebind(*replacement));CHECK(!renderer.Submit(prepared,completion));PreparedModelFrame recovered;
            CHECK(renderer.Prepare(1,stream,recovered));CHECK(renderer.Submit(recovered,completion));RgbaImage image;CHECK(replacement->ReadModelTarget(image));
            const auto different=compare(api,true,"replacement",count,image,renderer.Stats(),replacement->Status());CHECK(different>=0);candidateFailures+=different!=0;
            CHECK(renderer.Stats().uploads==stream.resources.size()*2);
        }
        CHECK(renderer.Unload(1));CHECK(table && pixels && metadata);return 0;
    };
    for(bool diagnostic:{false,true}){
        Window replacementWindow11{CreateWindowExW(0,L"STATIC",L"DX11 replacement history",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};
        Window replacementWindow12{CreateWindowExW(0,L"STATIC",L"DX12 replacement history",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};
        CHECK(replacementWindow11.h && replacementWindow12.h);
        auto replacementDesc11=desc;replacementDesc11.window.handle=reinterpret_cast<std::uintptr_t>(replacementWindow11.h);
        auto replacementDesc12=twelveDesc;replacementDesc12.window.handle=reinterpret_cast<std::uintptr_t>(replacementWindow12.h);
        // In specular mode both arms retain the already measured Alpha/UV
        // policies. Only the new specular policy changes between the two arms.
        const ModelOptions options{ModelCompatibility::Dx9Measured,diagnostic || specularFma,textureFma && (diagnostic || specularFma),specularFma && diagnostic};
        auto eleven=CreateD3D11Device(desc,D3D11Driver::Hardware,options);D3D11Bundle replacement11;
        CHECK(eleven && eleven.modelSupport.diagnosticAlpha12==options.diagnosticAlpha12 && eleven.modelSupport.diagnosticTextureFma==options.diagnosticTextureFma && eleven.modelSupport.diagnosticSpecularFma==options.diagnosticSpecularFma);
        metadata<<"dx11 policy="<<diagnostic<<" adapter="<<eleven.adapterName<<"\n";
        const auto replace11=[&]()->Device* {replacement11=CreateD3D11Device(replacementDesc11,D3D11Driver::Hardware,options);if(!replacement11 || replacement11.modelSupport.diagnosticSpecularFma!=options.diagnosticSpecularFma)return nullptr;return replacement11.device.get();};
        CHECK(replay(*eleven.device,"dx11",diagnostic,replace11)==0);
        // Debug is enabled before the first DX12 native device.
        auto twelve=CreateD3D12Device(twelveDesc,D3D12Driver::Hardware,{options,true});D3D12Bundle replacement12;
        CHECK(twelve && twelve.modelSupport.diagnosticAlpha12==options.diagnosticAlpha12 && twelve.modelSupport.diagnosticTextureFma==options.diagnosticTextureFma && twelve.modelSupport.diagnosticSpecularFma==options.diagnosticSpecularFma);
        metadata<<"dx12 policy="<<diagnostic<<" adapter="<<twelve.adapterName<<" debug=1\n";
        const auto replace12=[&]()->Device* {replacement12=CreateD3D12Device(replacementDesc12,D3D12Driver::Hardware,{options,true});if(!replacement12 || replacement12.modelSupport.diagnosticSpecularFma!=options.diagnosticSpecularFma)return nullptr;return replacement12.device.get();};
        CHECK(replay(*twelve.device,"dx12",diagnostic,replace12)==0);
        CHECK(QueryD3D12Stats(*twelve.device).debugErrors==0);
        if(replacement12)CHECK(QueryD3D12Stats(*replacement12.device).debugErrors==0);
    }
    std::ofstream summary(root/"summary.txt");summary<<"complete=1 observations="<<observations<<" nativeFailures="<<nativeFailures<<" nativeReplayUnavailable="<<nativeUnavailable<<" baselineFailures="<<baselineFailures
        <<" candidateFailures="<<candidateFailures<<" debugErrors=0 applicationActivation=0 diagnosticTextureFma="<<textureFma<<" diagnosticSpecularFma="<<specularFma<<" referenceArchiveNativeExact="<<(!nativeUnavailable && !nativeFailures)<<"\n";
    std::printf("Alpha history complete: observations=%u nativeFailures=%u nativeReplayUnavailable=%u baselineFailures=%u candidateFailures=%u\n",observations,nativeFailures,unsigned(nativeUnavailable),baselineFailures,candidateFailures);
    return table && pixels && metadata && summary && !candidateFailures && !nativeUnavailable && !nativeFailures?0:32;
}
}
