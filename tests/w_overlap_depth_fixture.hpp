#pragma once
#include "shared_clip_depth_fixture.hpp"
#include "rhi_d3d11_w_candidate_backend.hpp"
#include <set>

inline int SharedClipDepthSmoke(HWND window) {
    using Clip=std::array<float,4>;SharedClipDepthRenderer renderer;CHECK(renderer.Initialize(window));
    const std::vector<Clip> input{{-.8f,-.8f,.75f,1},{-.8f,.8f,.75f,1},{.8f,-.8f,.75f,1}};
    std::vector<Clip> captured;CHECK(renderer.Capture(input,captured));CHECK(captured.size()==input.size());
    for(unsigned n=0;n<3;++n){auto expected=input[n];expected[0]+=1.f/64;expected[1]-=1.f/64;CHECK(std::memcmp(expected.data(),captured[n].data(),16)==0);}
    for(bool equal:{false,true})for(int offset:{-1,0,1}) {
        const float depth=offset?std::nextafter(.75f,offset<0?0.f:1.f):.75f;RgbaImage native,replay;CHECK(renderer.Render(input,depth,equal,native,replay));
        CHECK(!PixelDifferences(native,replay));const auto* p=native.pixels.data()+(40*64+16)*4;
        const bool green=equal?offset==0:offset<0;CHECK(p[0]==(green?0:255) && p[1]==(green?255:0) && p[2]==0 && p[3]==255);
    }
    std::printf("sharedClipDepth defaultTarget=64x64 passthrough=EXACT comparisons=6 differences=0\n");return 0;
}

// Diagnostic reduction of the archived PMM residuals. Native matrices are
// unchanged. Policy 0/1/2 always mean production/W-only/combined-XYZ+W.
inline int WOverlapDepthControls(HWND window,const char* archivePath,const char* referencePath,const char* outputPath) {
    using Clip=std::array<float,4>;
    const std::filesystem::path archive(archivePath),reference(referencePath),directory(outputPath);
    std::filesystem::create_directories(directory);
    D3D9ReplaySnapshot source;CHECK(ReadUntexturedReduction(archive/"history_replay.reduction.draw2.state",source));
    CHECK(source.fvf==274 && source.stride==32 && source.base==0 && source.offset==0 && source.start==6 && source.count==232);
    unsigned x=0,y=0,w=0,h=0;std::ifstream trace(reference/"history_replay.dx9");std::string line;
    while(std::getline(trace,line))if(std::sscanf(line.c_str(),"PORTABLE_REGION x=%u y=%u width=%u height=%u",&x,&y,&w,&h)==4)break;
    CHECK(w && h && x+w<=4096 && y+h<=4096);source.viewport={x,y,w,h,0,1};const unsigned width=x+w,height=y+h;
    struct Pair {unsigned a,b,px,py;};std::vector<Pair> pairs;
    if(w==1032 && h==774 && x==565 && y==25)pairs={{135,227,1220,505}};
    else if(w==670 && h==503 && x==274 && y==25)pairs={{197,231,427,338},{185,231,381,340},{197,197,430,234}};
    else CHECK(false); // Only these captured residuals, never a scene heuristic.
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    std::array<D3D11Bundle,3> bundles;bundles[0]=CreateD3D11Device(desc,D3D11Driver::Hardware);
    for(unsigned policy=1;policy<3;++policy)bundles[policy]=CreateD3D11WCandidateDevice(desc,D3D11Driver::Hardware,policy);
    for(const auto& bundle:bundles)CHECK(bundle);
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,width,height,&source.viewport));
    std::printf("overlapDevice adapter=%s viewport=%u,%u,%u,%u singleSample=1 depth=D24S8\n",bundles[0].adapterName.c_str(),x,y,w,h);
    auto change=[](D3D9ReplaySnapshot& c,unsigned key,DWORD value){for(auto& s:c.renderStates)if(s.key==key){s.value=value;return;}c.renderStates.push_back({0,key,value});};
    auto color=[&](D3D9ReplaySnapshot c,bool green){
        for(const auto& kv:{std::pair<unsigned,DWORD>{D3DRS_LIGHTING,TRUE},{D3DRS_SPECULARENABLE,FALSE},{D3DRS_ALPHABLENDENABLE,FALSE},
            {D3DRS_ALPHATESTENABLE,FALSE},{D3DRS_STENCILENABLE,FALSE},{D3DRS_CULLMODE,D3DCULL_NONE},{D3DRS_ZENABLE,TRUE},
            {D3DRS_ZWRITEENABLE,TRUE},{D3DRS_ZFUNC,D3DCMP_LESSEQUAL},{D3DRS_AMBIENT,0}})change(c,kv.first,kv.second);
        c.material={};c.material.Diffuse.a=1;c.material.Emissive=green?D3DCOLORVALUE{0,1,0,0}:D3DCOLORVALUE{1,0,0,0};c.lights.clear();
        Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);c.textureInfo={};c.textureBytes={};c.preparedMips={};return c;
    };
    auto triangle=[&](unsigned n,bool green,bool ids,unsigned cycle=0){auto c=ids?color(source,green):source;c.start+=n*3;c.count=1;
        if(cycle){const unsigned step=c.indexFormat==D3DFMT_INDEX16?2:4;std::array<unsigned char,12> indices{};std::memcpy(indices.data(),c.indexBytes.data()+c.start*step,step*3);
            for(unsigned k=0;k<3;++k)std::memcpy(c.indexBytes.data()+(c.start+k)*step,indices.data()+((k+cycle)%3)*step,step);}
        return c;};
    auto index=[&](unsigned triangle,unsigned vertex){unsigned i=0;const unsigned step=source.indexFormat==D3DFMT_INDEX16?2:4;std::memcpy(&i,source.indexBytes.data()+(source.start+triangle*3+vertex)*step,step);return i;};
    auto replay=[&](const std::vector<D3D9ReplaySnapshot>& draws,unsigned policy,RgbaImage& out,DWORD clear=0xff000000){ModelReplayStream stream;stream.target.width=width;stream.target.height=height;
        stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& c:draws)if(!AppendD3D9ReplaySnapshot(stream,c))return false;stream.complete=true;
        return policy?bool(ReplayD3D11WCandidatePrefix(*bundles[policy].device,stream,draws.size(),out)):bool(ReplayD3D11ModelPrefix(*bundles[0].device,stream,draws.size(),out));};
    auto classify=[&](const RgbaImage& image,unsigned px,unsigned py){const auto* p=image.pixels.data()+(std::size_t(py)*width+px)*4;
        return p[0]==255 && !p[1] && !p[2] && p[3]==255?'R':!p[0] && p[1]==255 && !p[2] && p[3]==255?'G':'B';};
    auto saveImage=[&](const std::string& name,const RgbaImage& image){std::ofstream file(directory/(name+".rgba"),std::ios::binary);file.write(reinterpret_cast<const char*>(image.pixels.data()),image.pixels.size());};
    auto saveClip=[&](const std::string& name,const std::vector<Clip>& data){std::ofstream file(directory/(name+".clip"),std::ios::binary);file.write(reinterpret_cast<const char*>(data.data()),data.size()*16);};
    std::array<std::vector<Clip>,3> raw,final;
    for(unsigned p=0;p<3;++p){CHECK(CaptureDepthVertexShader(source,final[p],&raw[p],true,p));saveClip("p"+std::to_string(p)+"_raw",raw[p]);saveClip("p"+std::to_string(p)+"_final",final[p]);}
    depth_diagnostic::Matrix world,view,projectionMatrix;std::memcpy(world.data(),&source.world,64);std::memcpy(view.data(),&source.view,64);std::memcpy(projectionMatrix.data(),&source.projection,64);
    const auto combined=w_shader_diagnostic::Inputs(world,view,projectionMatrix,2).combined;
    {std::ofstream vb(directory/"source.vertices",std::ios::binary);vb.write(reinterpret_cast<const char*>(source.vertexBytes.data()),source.vertexBytes.size());
        std::ofstream ib(directory/"source.indices",std::ios::binary);ib.write(reinterpret_cast<const char*>(source.indexBytes.data()),source.indexBytes.size());
        std::ofstream m(directory/"source.matrices",std::ios::binary);for(const auto* matrix:{&source.world,&source.view,&source.projection})m.write(reinterpret_cast<const char*>(matrix),64);}
    auto clips=[&](unsigned triangle,unsigned policy,unsigned cycle){std::vector<Clip> out;for(unsigned n=0;n<3;++n)out.push_back(raw[policy][index(triangle,(n+cycle)%3)]);return out;};
    // Fail before collecting evidence if shared-center arithmetic changes a
    // production clip bit. This catches diagnostic harness differences.
    for(const auto& pair:pairs)for(unsigned t:std::set<unsigned>{pair.a,pair.b})for(unsigned p=0;p<3;++p){std::vector<Clip> observed;CHECK(shared.Capture(clips(t,p,0),observed));
        for(unsigned n=0;n<3;++n)for(unsigned k=0;k<4;++k){unsigned actual,expected;std::memcpy(&actual,&observed[n][k],4);std::memcpy(&expected,&final[p][index(t,n)][k],4);
            if(actual!=expected){std::fprintf(stderr,"sharedCenterMismatch triangle=%u policy=%u vertex=%u component=%u actual=%u expected=%u\n",t,p,n,k,actual,expected);return 1;}}}
    std::printf("sharedCenterPreflight allSelectedClipBits=EXACT\n");
    auto projection=[&](unsigned vertex){const auto& p=raw[0][vertex];return std::array<double,3>{x+(double(p[0])/p[3]+1)*w/2,y+(1-double(p[1])/p[3])*h/2,double(p[2])/p[3]};};
    auto plane=[&](unsigned t,unsigned px,unsigned py,bool coverage){const auto a=projection(index(t,0)),b=projection(index(t,1)),c=projection(index(t,2));
        const double d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(!d)return -1.;
        const double u=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(py-c[1]))/d,v=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(py-c[1]))/d;
        return coverage?(u>1e-4 && v>1e-4 && 1-u-v>1e-4?1.:-1.):u*a[2]+v*b[2]+(1-u-v)*c[2];};
    std::ofstream images(directory/"images.csv");images<<"pair,kind,cycle,order,comparison,repeat,policy,differentPixels,x,y,nativeR,nativeG,nativeB,replayR,replayG,replayB\n";
    std::ofstream probes(directory/"thresholds.csv");probes<<"pair,triangle,x,y,holdout,cycle,path,dx9Bits,dx11Bits,repeatExact\n";
    std::ofstream coordinates(directory/"coordinates.csv");coordinates<<"pair,x,y,holdout\n";
    unsigned imageComparisons=0,failedImages=0,thresholdCount=0,failedThresholds=0;
    std::vector<unsigned char> savedNative;{std::ifstream f(reference/"history_replay.dx11_first_actual.bgra",std::ios::binary);savedNative.assign(std::istreambuf_iterator<char>{f},{});CHECK(savedNative.size()==std::size_t(w)*h*4);}
    for(const auto& pair:pairs){const std::string label=std::to_string(pair.a)+"_"+std::to_string(pair.b);
        std::vector<std::array<unsigned,3>> points{{pair.px,pair.py,0}};
        // Additional coordinates chosen by interior coverage alone, not a fitted error.
        const int offsets[][2]={{-2,0},{2,0},{-1,0},{1,0},{-3,0},{3,0},{-2,-1},{2,-1},{0,-1},{-2,1},{2,1},{0,1}};
        for(const auto& offset:offsets) {const auto px=static_cast<unsigned>(int(pair.px)+offset[0]),py=static_cast<unsigned>(int(pair.py)+offset[1]);if(plane(pair.a,px,py,true)>0 && plane(pair.b,px,py,true)>0){points.push_back({px,py,1});if(points.size()==3)break;}}
        CHECK(points.size()==3);for(const auto& point:points)coordinates<<label<<","<<point[0]<<","<<point[1]<<","<<point[2]<<"\n";
        // Shaded pair/solo proves the original pixel survives removing other geometry.
        for(unsigned kind=0;kind<2;++kind)for(unsigned comparison=0;comparison<(kind?3u:1u);++comparison)for(unsigned order=0;order<(pair.a==pair.b?1u:2u);++order) {
            auto a=triangle(pair.a,false,kind!=0),b=triangle(pair.b,true,kind!=0);
            for(auto* c:{&a,&b}){if(comparison==1)change(*c,D3DRS_ZFUNC,D3DCMP_LESS);if(comparison==2)change(*c,D3DRS_ZENABLE,FALSE);}
            const std::vector<D3D9ReplaySnapshot> draws=pair.a==pair.b?std::vector<D3D9ReplaySnapshot>{a}:order?std::vector<D3D9ReplaySnapshot>{b,a}:std::vector<D3D9ReplaySnapshot>{a,b};
            RgbaImage native;const DWORD clear=kind?0xff000000:0xffffffff;CHECK(NativeImage(window,draws,draws.size(),native,nullptr,width,height,clear));
            for(unsigned policy=0;policy<3;++policy){RgbaImage result;CHECK(replay(draws,policy,result,clear));const unsigned diff=PixelDifferences(native,result);++imageComparisons;failedImages+=diff!=0;
                const auto at=(std::size_t(pair.py)*width+pair.px)*4;const auto* n=native.pixels.data()+at;const auto* r=result.pixels.data()+at;
                images<<label<<","<<(kind?"ID":"Shaded")<<",0,"<<order<<","<<comparison<<",0,"<<policy<<","<<diff<<","<<pair.px<<","<<pair.py<<","<<unsigned(n[0])<<","<<unsigned(n[1])<<","<<unsigned(n[2])<<","<<unsigned(r[0])<<","<<unsigned(r[1])<<","<<unsigned(r[2])<<"\n";images.flush();
                const auto stem=label+"_"+(kind?"id":"shaded")+"_c"+std::to_string(comparison)+"_o"+std::to_string(order)+"_p"+std::to_string(policy);saveImage(stem+"_native",native);saveImage(stem+"_dx11",result);
                std::printf("overlapImage pair=%s kind=%s compare=%u order=%u policy=%u differences=%u pixel=%u,%u native=%u,%u,%u replay=%u,%u,%u\n",label.c_str(),kind?"ID":"Shaded",comparison,order,policy,diff,pair.px,pair.py,n[0],n[1],n[2],r[0],r[1],r[2]);
                if(!kind && !order){const auto savedAt=(std::size_t(pair.py-y)*w+pair.px-x)*4;CHECK(n[0]==savedNative[savedAt+2] && n[1]==savedNative[savedAt+1] && n[2]==savedNative[savedAt]);}
                if(kind && comparison==2)CHECK(!diff);
            }
        }
        std::set<unsigned> selected{pair.a,pair.b};
        for(auto selectedTriangle:selected)for(unsigned cycle=0;cycle<3;++cycle) {
            auto t=triangle(selectedTriangle,false,true,cycle);std::array<std::vector<Clip>,3> triangleClip;
            std::vector<Clip> objects;for(unsigned n=0;n<3;++n){Clip object{0,0,0,1};std::memcpy(object.data(),source.vertexBytes.data()+index(selectedTriangle,(n+cycle)%3)*32,12);objects.push_back(object);}
            for(unsigned p=0;p<3;++p){triangleClip[p]=clips(selectedTriangle,p,cycle);std::vector<Clip> captured;CHECK(shared.Capture(triangleClip[p],captured));
                for(unsigned n=0;n<3;++n){if(std::memcmp(captured[n].data(),final[p][index(selectedTriangle,(n+cycle)%3)].data(),16)){std::fprintf(stderr,"clipMismatch triangle=%u policy=%u cycle=%u vertex=%u\n",selectedTriangle,p,cycle,n);return 1;}}}
            auto ruler=[&](float z,bool equal){auto c=color(Fixture(),true);c.viewport=source.viewport;const float full[]={-1,-1,z,0,0,1,0,0,-1,1,z,0,0,1,0,0,1,-1,z,0,0,1,0,0,1,1,z,0,0,1,0,0};
                c.vertexBytes.resize(sizeof(full));std::memcpy(c.vertexBytes.data(),full,sizeof(full));c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};c.vertices=4;c.count=2;
                change(c,D3DRS_ZWRITEENABLE,FALSE);change(c,D3DRS_ZFUNC,equal?D3DCMP_EQUAL:D3DCMP_LESS);return c;};
            const unsigned activeBackends=cycle?8u:12u; // Instruction controls keep original order.
            for(const auto& point:points){const unsigned px=point[0],py=point[1];std::map<std::pair<unsigned,bool>,std::array<char,12>> cached;
                auto relation=[&](unsigned bits,bool equal,std::array<char,12>& answer,bool fresh=false){const auto key=std::make_pair(bits,equal);const auto found=cached.find(key);if(!fresh && found!=cached.end()){answer=found->second;return true;}
                    float depth;std::memcpy(&depth,&bits,4);const std::vector<D3D9ReplaySnapshot> draws{t,ruler(depth,equal)};RgbaImage native,out;
                    if(!NativeImage(window,draws,2,native,nullptr,width,height))return false;answer[0]=classify(native,px,py);
                    for(unsigned p=0;p<3;++p){if(!replay(draws,p,out))return false;answer[p+1]=classify(out,px,py);}
                    for(unsigned p=1;p<3;++p){RgbaImage a,b;if(!shared.Render(triangleClip[p],depth,equal,a,b))return false;answer[2+p*2]=classify(a,px,py);answer[3+p*2]=classify(b,px,py);}
                    if(!cycle){const unsigned operations[]={0,4,5,6};for(unsigned k=0;k<4;++k){RgbaImage a,b;if(!shared.Render(triangleClip[2],depth,equal,a,b,&objects,&combined,operations[k]))return false;answer[8+k]=classify(a,px,py);if(classify(b,px,py)!=answer[7])return false;}}
                    for(unsigned k=0;k<activeBackends;++k)if(answer[k]=='B')return false;if(found!=cached.end() && found->second!=answer)return false;cached[key]=answer;return true;};
                const float estimate=static_cast<float>(plane(selectedTriangle,px,py,false));unsigned center;std::memcpy(&center,&estimate,4);CHECK(center>64 && estimate>0 && estimate<1);
                std::array<char,12> answer{};CHECK(relation(center-32,false,answer));for(unsigned k=0;k<activeBackends;++k)CHECK(answer[k]=='G');CHECK(relation(center+32,false,answer));for(unsigned k=0;k<activeBackends;++k)CHECK(answer[k]=='R');
                std::array<unsigned,12> threshold{};
                for(unsigned backend=0;backend<activeBackends;++backend){unsigned low=center-32,high=center+32;while(high-low>1){const auto middle=low+(high-low)/2;CHECK(relation(middle,false,answer));if(answer[backend]=='G')low=middle;else high=middle;}threshold[backend]=high;CHECK(relation(high,true,answer));CHECK(answer[backend]=='G');CHECK(relation(high-1,true,answer));CHECK(answer[backend]=='R');CHECK(relation(high+1,true,answer));CHECK(answer[backend]=='R');}
                for(unsigned repeat=0;repeat<3;++repeat)for(unsigned bits:std::set<unsigned>(threshold.begin(),threshold.begin()+activeBackends)){CHECK(relation(bits,true,answer,true));for(unsigned b=0;b<activeBackends;++b)if(threshold[b]==bits)CHECK(answer[b]=='G');CHECK(relation(bits-1,false,answer,true));for(unsigned b=0;b<activeBackends;++b)if(threshold[b]==bits)CHECK(answer[b]=='G');}
                for(unsigned p=0;p<3;++p){probes<<label<<","<<selectedTriangle<<","<<px<<","<<py<<","<<point[2]<<","<<cycle<<",p"<<p<<","<<threshold[0]<<","<<threshold[p+1]<<",1\n";++thresholdCount;failedThresholds+=threshold[0]!=threshold[p+1];}
                for(unsigned p=1;p<3;++p){probes<<label<<","<<selectedTriangle<<","<<px<<","<<py<<","<<point[2]<<","<<cycle<<",shared"<<p<<","<<threshold[2+p*2]<<","<<threshold[3+p*2]<<",1\n";++thresholdCount;failedThresholds+=threshold[2+p*2]!=threshold[3+p*2];}
                if(!cycle){const char* names[]={"native_dp4","native_dot_z","native_dot_w","native_dot_zw"};for(unsigned k=0;k<4;++k){probes<<label<<","<<selectedTriangle<<","<<px<<","<<py<<","<<point[2]<<",0,"<<names[k]<<","<<threshold[8+k]<<","<<threshold[7]<<",1\n";++thresholdCount;failedThresholds+=threshold[8+k]!=threshold[7];}
                    std::printf("overlapInstructions pair=%s triangle=%u pixel=%u,%u originalNative=%u dp4=%u dotZ=%u dotW=%u dotZW=%u candidate=%u\n",label.c_str(),selectedTriangle,px,py,threshold[0],threshold[8],threshold[9],threshold[10],threshold[11],threshold[7]);}
                probes.flush();std::printf("overlapThreshold pair=%s triangle=%u pixel=%u,%u holdout=%u cycle=%u native=%u p0=%u p1=%u p2=%u shared1=%u,%u shared2=%u,%u repeat=EXACT clipPassthrough=EXACT\n",label.c_str(),selectedTriangle,px,py,point[2],cycle,threshold[0],threshold[1],threshold[2],threshold[3],threshold[4],threshold[5],threshold[6],threshold[7]);
            }
        }
    }
    for(auto& bundle:bundles)CHECK(bundle.swapchain->Retire());
    std::printf("overlapSummary imageComparisons=%u failedImages=%u thresholdPairs=%u failedThresholds=%u nativeVertexCapture=0\n",imageComparisons,failedImages,thresholdCount,failedThresholds);
    return failedImages || failedThresholds?32:0;
}
