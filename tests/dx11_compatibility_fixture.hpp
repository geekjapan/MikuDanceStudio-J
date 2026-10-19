#pragma once
#include <chrono>
namespace dx11_compatibility_test {
using scene_prefix_diagnostic::Crop;
using scene_prefix_diagnostic::Hash;
using model_transform_diagnostic::Save;
struct Uploads {
    Device& device;std::map<ReplayResourceKey,Handle> handles;unsigned textures=0;
    ~Uploads(){for(const auto& h:handles)device.Destroy(h.second);}
    bool Load(const ModelReplayStream& stream) {
        for(const auto& r:stream.resources){Handle h;
            if(r.kind==ReplayResourceKind::Texture){h=CreateD3D11ModelTexture(device,r.texture);++textures;}
            else {BufferDesc d{r.kind==ReplayResourceKind::Vertices?BufferUsage::Vertex:BufferUsage::Index,r.bytes.size()};d.indexFormat=r.indexFormat;h=device.CreateBuffer(d,r.bytes.data());}
            if(!h || !handles.emplace(r.key,h).second)return false;
        }return true;
    }
};
inline bool Submit(Device& device,const ModelReplayStream& stream,const Uploads& uploads,unsigned count,RgbaImage& output,SubmissionIdentity stale={},unsigned* rejected=nullptr) {
    if(!device.BeginFrame(stream.clear))return false;unsigned submitted=0;
    for(const auto& e:stream.events){if(e.op!=ModelReplayOp::Draw || submitted==count)continue;const auto& draw=e.draw;
        if(!device.SetModelPipeline(draw.pipeline)){device.EndFrame();return false;}
        for(unsigned slot=0;slot<3;++slot)if(draw.pipeline.shader.layout.stages[slot].role!=MaterialTextureRole::None && !device.BindTexture(slot,uploads.handles.at(draw.textures[slot]))){device.EndFrame();return false;}
        bool ok=false;
        if(draw.indexed){auto cmd=device.Record(IndexedDraw{uploads.handles.at(draw.vertices),uploads.handles.at(draw.indices),draw.firstIndex,draw.indexCount,draw.vertexCount,draw.pipeline.vertexLayout});
            if(stale.device){auto old=cmd;old.submission=stale;if(device.DrawIndexed(old)){device.EndFrame();return false;}if(rejected)++*rejected;}
            ok=device.DrawIndexed(cmd);
        }else {NonIndexedDraw cmd{uploads.handles.at(draw.vertices),draw.firstVertex,draw.drawVertexCount};cmd.layout=draw.pipeline.vertexLayout;cmd=device.Record(cmd);
            if(stale.device){auto old=cmd;old.submission=stale;if(device.Draw(old)){device.EndFrame();return false;}if(rejected)++*rejected;}
            ok=device.Draw(cmd);
        }if(!ok){device.EndFrame();return false;}++submitted;
    }
    return submitted==count && device.EndFrame() && ReadD3D11Offscreen(device,output);
}
inline int Run(HWND window,const char* archivePath,const char* outputPath) {
    const std::filesystem::path root(outputPath);CHECK(!std::filesystem::exists(root));std::filesystem::create_directories(root);
    ground_history_isolation::Archive archive;CHECK(archive.Load(archivePath,51));ModelReplayStream stream;
    stream.target.width=archive.width;stream.target.height=archive.height;const auto clear=archive.clear;
    stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};
    const auto& r=archive.region;stream.initializedRegion=ModelViewport{r.X,r.Y,r.Width,r.Height,r.MinZ,r.MaxZ};stream.events.push_back({1,ModelReplayOp::Clear});
    for(const auto& draw:archive.draws)CHECK(AppendD3D9ReplaySnapshot(stream,draw,true));stream.complete=true;CHECK(ValidateModelReplay(stream));
    std::array<std::vector<unsigned char>,52> reference;
    for(unsigned n=0;n<=51;++n){const auto file=archive.path/(n==51?"history_replay.scene_prefix.final.bgra":"history_replay.scene_prefix.draw"+std::to_string(n+1)+".before.bgra");
        std::ifstream in(file,std::ios::binary);reference[n]={std::istreambuf_iterator<char>{in},{}};CHECK(reference[n].size()==std::size_t(r.Width)*r.Height*4);}
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    const D3D11ModelOptions options{D3D11ModelCompatibility::Dx9Measured};
    CHECK(CheckD3D11ModelCompatibility(options.compatibility,false)==D3D11CompatibilityResult::ShaderDoublesRequired);
    CHECK(CheckD3D11ModelCompatibility(D3D11ModelCompatibility::Default,false)==D3D11CompatibilityResult::Supported);
    auto invalid=CreateD3D11Device(desc,D3D11Driver::Hardware,{static_cast<D3D11ModelCompatibility>(99)});CHECK(!invalid && invalid.creationReason=="invalid_model_compatibility");
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,options);CHECK(bundle);
    const auto support=QueryD3D11ModelSupport(*bundle.device,options.compatibility);CHECK(support.shaderDoubles && support.selected==options.compatibility && support.requestedSupport==D3D11CompatibilityResult::Supported);
    std::ofstream meta(root/"metadata.txt");meta<<"adapter="<<bundle.adapterName<<" vendor="<<bundle.vendorId<<" device="<<bundle.deviceId<<" draws=51 events="<<stream.events.size()<<" resources="<<stream.resources.size()<<" doubles=1 selected=dx9_measured applicationActivation=0 samples=1\n";CHECK(meta);
    std::ofstream table(root/"lifecycle.csv");table<<"phase,boundary,width,height,identity,epoch,rejected,uploads,textureUploads,differentPixels,hash\n";
    unsigned checks=0,rejections=0,uploadsTotal=0;SubmissionIdentity retired{};
    for(unsigned replacement=0;replacement<2;++replacement){
        if(replacement){const auto status=bundle.device->Status();retired={status.identity,status.epoch};CHECK(bundle.swapchain->Retire() && !bundle.device->BeginFrame({}));
            bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,options);CHECK(bundle && bundle.device->Status().identity!=retired.device);}
        auto& device=*bundle.device;Uploads uploads{device};CHECK(uploads.Load(stream));uploadsTotal+=uploads.handles.size();
        const auto stableHandles=uploads.handles;
        for(unsigned resize=0;resize<5;++resize){const auto before=device.Status();const SubmissionIdentity stale=replacement && !resize?retired:SubmissionIdentity{before.identity,before.epoch};
            const unsigned width=archive.width+(resize%2?16*resize:0),height=archive.height+(resize%2?8*resize:0);
            CHECK(ResizeD3D11Offscreen(device,width,height));CHECK(device.Status().identity==before.identity && device.Status().epoch==before.epoch+1);
            CHECK(uploads.handles.size()==stableHandles.size());
            for(const auto& entry:stableHandles){const auto h=uploads.handles.at(entry.first);CHECK(h.device==entry.second.device && h.index==entry.second.index && h.generation==entry.second.generation);}
            for(unsigned n=0;n<=51;++n){RgbaImage image;unsigned rejected=0;CHECK(Submit(device,stream,uploads,n,image,stale,&rejected));const auto actual=Crop(image,r);
                CHECK(actual==reference[n]);rejections+=rejected;++checks;const auto phase="device"+std::to_string(replacement)+"_resize"+std::to_string(resize);
                table<<phase<<","<<n<<","<<width<<","<<height<<","<<device.Status().identity<<","<<device.Status().epoch<<","<<rejected<<","<<uploads.handles.size()<<","<<uploads.textures<<",0,"<<Hash(actual)<<"\n";table.flush();
                if(n==51)CHECK(Save(root/(phase+".bgra"),actual.data(),actual.size()));
            }
            for(unsigned repeat=1;repeat<=3;++repeat){RgbaImage image;CHECK(Submit(device,stream,uploads,51,image));const auto actual=Crop(image,r);CHECK(actual==reference[51]);
                CHECK(Save(root/("device"+std::to_string(replacement)+"_resize"+std::to_string(resize)+"_repeat"+std::to_string(repeat)+".bgra"),actual.data(),actual.size()));}
            std::printf("compatibility device=%u resize=%u boundaries=52 zeroDifference=1 epoch=%llu retainedResources=%zu\n",replacement,resize,static_cast<unsigned long long>(device.Status().epoch),uploads.handles.size());std::fflush(stdout);
        }
    }
    CHECK(bundle.swapchain->Retire());
    // Timestamp intervals exclude upload/rebuild/readback; whole-call wall time
    // is reported separately. Alternate order to reduce drift, never time DX9.
    std::array<D3D11Bundle,2> timed{CreateD3D11Device(desc,D3D11Driver::Hardware),CreateD3D11Device(desc,D3D11Driver::Hardware,options)};CHECK(timed[0] && timed[1]);
    // A finite input stream can still contain a singular normal transform
    // which this mode rejects. Close failed timed frames and allow recovery.
    auto unsupported=stream;
    for(auto& event:unsupported.events)if(event.op==ModelReplayOp::Draw && event.draw.pipeline.vertexLayout==VertexLayout::PositionNormalUv){
        event.draw.pipeline.shader.world={};event.draw.pipeline.shader.world[15]=1;break;}
    CHECK(ValidateModelReplay(unsupported));RgbaImage failedImage;D3D11ReplayTiming failedTiming;
    const auto rejected=ReplayD3D11ModelPrefix(*timed[1].device,unsupported,51,failedImage,&failedTiming);
    CHECK(!rejected && rejected.reason=="pipeline_failed" && !failedTiming.valid && failedImage.pixels.empty());
    std::ofstream timing(root/"timing.csv");timing<<"iteration,mode,warmup,valid,disjoint,frequency,gpuMs,wholeReplayMs,differentPixels\n"<<std::setprecision(17);
    for(unsigned iteration=0;iteration<15;++iteration)for(unsigned order=0;order<2;++order){const unsigned mode=(order+iteration)%2;RgbaImage image;D3D11ReplayTiming measured;
        const auto begin=std::chrono::steady_clock::now();CHECK(ReplayD3D11ModelPrefix(*timed[mode].device,stream,51,image,&measured));const auto end=std::chrono::steady_clock::now();
        CHECK(measured.valid && !measured.disjoint && measured.frequency);const auto actual=Crop(image,r);unsigned different=0;for(unsigned p=0;p<actual.size();p+=4)different+=std::memcmp(actual.data()+p,reference[51].data()+p,4)!=0;
        if(mode)CHECK(!different);
        timing<<iteration<<","<<(mode?"dx9_measured":"default")<<","<<(iteration<3)<<","<<measured.valid<<","<<measured.disjoint<<","<<measured.frequency<<","<<measured.gpuSeconds*1000<<","<<std::chrono::duration<double,std::milli>(end-begin).count()<<","<<different<<"\n";timing.flush();
    }
    for(auto& b:timed)CHECK(b.swapchain->Retire());CHECK(table && timing);
    std::ofstream summary(root/"summary.txt");summary<<"complete=1 devices=2 resizesPerDevice=5 boundaries="<<checks<<" staleRejected="<<rejections<<" totalUploads="<<uploadsTotal<<" repeats=3 timingSamplesPerMode=12 timingWarmup=3 timedFailureRecovered=1 applicationActivation=0\n";CHECK(summary);return 0;
}
} // namespace dx11_compatibility_test
