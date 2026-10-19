#pragma once
#include "mikudancestudio/rhi_scene_renderer.hpp"
#include "mikudancestudio/rhi_d3d12.hpp"
#include <sstream>
namespace resident_pmm_test {
inline int Run(HWND window,const char* archivePath,const char* outputPath) {
    using scene_prefix_diagnostic::Crop;using scene_prefix_diagnostic::Hash;
    const std::filesystem::path root(outputPath);CHECK(!std::filesystem::exists(root));std::filesystem::create_directories(root);
    std::ifstream manifest(std::filesystem::path(archivePath)/"history_replay.scene_prefix.manifest");std::string line;
    CHECK(std::getline(manifest,line));unsigned drawCount=0;std::istringstream fields(line);std::string field;
    while(fields>>field)if(field.rfind("draws=",0)==0){std::istringstream value(field.substr(6));CHECK(value>>drawCount);}
    CHECK(drawCount && drawCount<=10000);
    ground_history_isolation::Archive archive;CHECK(archive.Load(archivePath,drawCount));ModelReplayStream stream;
    stream.target.width=archive.width;stream.target.height=archive.height;const auto clear=archive.clear;const auto& region=archive.region;
    stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};
    stream.initializedRegion=ModelViewport{region.X,region.Y,region.Width,region.Height,region.MinZ,region.MaxZ};stream.events.push_back({1,ModelReplayOp::Clear});
    for(const auto& draw:archive.draws)CHECK(AppendD3D9ReplaySnapshot(stream,draw,true));stream.complete=true;CHECK(ValidateModelReplay(stream));
    std::vector<std::vector<unsigned char>> reference(drawCount+1);
    for(unsigned n=1;n<=drawCount;++n){const auto file=archive.path/(n==drawCount?"history_replay.scene_prefix.final.bgra":"history_replay.scene_prefix.draw"+std::to_string(n+1)+".before.bgra");
        std::ifstream in(file,std::ios::binary);reference[n]={std::istreambuf_iterator<char>{in},{}};CHECK(reference[n].size()==std::size_t(region.Width)*region.Height*4);}
    struct Window {HWND h;~Window(){DestroyWindow(h);}} dx12Window{CreateWindowExW(0,L"STATIC",L"DX12 resident PMM",WS_POPUP,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr)};CHECK(dx12Window.h);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;desc.present=PresentMode::Immediate;
    auto eleven=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(eleven);
    desc.window.handle=reinterpret_cast<std::uintptr_t>(dx12Window.h);
    auto twelve=CreateD3D12Device(desc,D3D12Driver::Hardware,{{ModelCompatibility::Dx9Measured},true});CHECK(twelve);
    std::ofstream table(root/"resident.csv");table<<"api,phase,boundary,uploads,textureUploads,resident,retiring,identity,epoch,differentPixels,hash\n";
    std::ofstream metadata(root/"metadata.txt");metadata<<"dx11="<<eleven.adapterName<<" dx12="<<twelve.adapterName<<" resources="<<stream.resources.size()<<" draws="<<drawCount<<" samples=1 doubles="<<twelve.modelSupport.shaderDoubles<<" applicationActivation=0 debug=1\n";
    unsigned checks=0;
    for(unsigned backend=0;backend<2;++backend){auto& device=backend?*twelve.device:*eleven.device;SceneRenderer renderer(device);PreparedModelFrame prepared;std::uint64_t targetRebuilds=0;
        for(unsigned boundary=1;boundary<=drawCount;++boundary){auto prefix=stream;unsigned draws=0;
            auto end=prefix.events.end();for(auto e=prefix.events.begin();e!=prefix.events.end();++e)if(e->op==ModelReplayOp::Draw && ++draws==boundary){end=e+1;break;}prefix.events.erase(end,prefix.events.end());
            CHECK(renderer.Prepare(1,prefix,prepared));CompletionToken completion;CHECK(renderer.Submit(prepared,completion));RgbaImage image;CHECK(device.ReadModelTarget(image));
            const auto actual=Crop(image,region);unsigned different=0;for(unsigned p=0;p<actual.size();p+=4)different+=std::memcmp(actual.data()+p,reference[boundary].data()+p,4)!=0;
            const auto stats=renderer.Stats();table<<(backend?"dx12":"dx11")<<",prefix,"<<boundary<<","<<stats.uploads<<","<<stats.textureUploads<<","<<stats.residentResources<<","<<stats.retiringResources<<","<<device.Status().identity<<","<<device.Status().epoch<<","<<different<<","<<Hash(actual)<<"\n";table.flush();
            if(different){CHECK(model_transform_diagnostic::Save(root/("failure_"+std::to_string(backend)+"_"+std::to_string(boundary)+".bgra"),actual.data(),actual.size()));std::printf("api=%s firstMismatch=%u pixels=%u\n",backend?"dx12":"dx11",boundary,different);}
            CHECK(!different);if(boundary==1)targetRebuilds=stats.targetRebuilds;
            CHECK(stats.uploads==stream.resources.size() && targetRebuilds<=1 && stats.targetRebuilds==targetRebuilds);++checks;
        }
        CompletionToken completion;for(unsigned n=0;n<1000;++n)CHECK(renderer.Submit(prepared,completion));CHECK(device.WaitCompletion(completion,5000));RgbaImage image;CHECK(device.ReadModelTarget(image) && Crop(image,region)==reference[drawCount]);
        CHECK(renderer.Stats().uploads==stream.resources.size());
        for(unsigned resize=0;resize<6;++resize){auto resized=stream;resized.target.width+=(resize%2)*32;resized.target.height+=(resize%2)*16;PreparedModelFrame next;
            CHECK(renderer.Prepare(1,resized,next) && !renderer.Submit(prepared,completion));CHECK(renderer.Submit(next,completion));CHECK(device.ReadModelTarget(image) && Crop(image,region)==reference[drawCount]);
            CHECK(renderer.Stats().uploads==stream.resources.size());++checks;}
        // Keep scene IDs/CPU versions and replace only the backend resource owner.
        auto& other=backend?*eleven.device:*twelve.device;CHECK(renderer.Rebind(other));
        PreparedModelFrame switched;CHECK(!renderer.Submit(prepared,completion));CHECK(renderer.Prepare(1,stream,switched));
        CHECK(renderer.Submit(switched,completion) && other.ReadModelTarget(image) && Crop(image,region)==reference[drawCount]);
        CHECK(renderer.Stats().uploads==stream.resources.size()*2);++checks;
        CHECK(renderer.Unload(1));CHECK(renderer.Rebind(device));if(backend)CHECK(QueryD3D12Stats(device).debugErrors==0);
        std::printf("resident PMM %s: %u boundaries exact, 1000 frames retained, 6 target resizes exact, backend switch exact, uploads=%llu\n",backend?"dx12":"dx11",drawCount,renderer.Stats().uploads);std::fflush(stdout);
    }
    CHECK(table && metadata);std::ofstream summary(root/"summary.txt");summary<<"complete=1 exactChecks="<<checks<<" residentFramesPerApi=1000 targetResizesPerApi=6 debugErrors=0 applicationActivation=0\n";return summary?0:1;
}
}
