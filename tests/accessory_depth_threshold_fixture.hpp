#pragma once
namespace accessory_depth_threshold {
using Clip=std::array<float,4>;
using ground_endpoint_depth::Bits;using ground_endpoint_depth::Float;using ground_endpoint_depth::Id;using ground_endpoint_depth::Color;
inline bool Render(HWND window,ground_history_isolation::Archive& capture,D3D11Bundle& bundle,
    const std::vector<D3D9ReplaySnapshot>& draws,RgbaImage& native,RgbaImage& replay,DWORD clear,IDirect3DDevice9* measurementDevice=nullptr){
    if(!NativeImage(window,draws,unsigned(draws.size()),native,nullptr,capture.width,capture.height,clear,nullptr,nullptr,measurementDevice))return false;
    ModelReplayStream stream;stream.target.width=capture.width;stream.target.height=capture.height;
    stream.clear={((clear>>16)&255)/255.f,((clear>>8)&255)/255.f,(clear&255)/255.f,((clear>>24)&255)/255.f};stream.events.push_back({1,ModelReplayOp::Clear});
    for(const auto& draw:draws)if(!AppendD3D9ReplaySnapshot(stream,draw,true))return false;stream.complete=true;
    return bool(ReplayD3D11ModelPrefix(*bundle.device,stream,draws.size(),replay));
}
inline int Run(HWND window,const char* archive,const char* destination){
    ground_history_isolation::Archive capture;CHECK(capture.Load(archive,66));
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    auto first=capture.draws[64],second=capture.draws[65];first.accessoryMaterial=second.accessoryMaterial=true;
    CHECK(first.vertexBytes==second.vertexBytes && first.indexBytes==second.indexBytes && first.count==2 && second.count==2 && first.stride==32);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(bundle);
    std::ofstream metadata(output/"metadata.txt");metadata<<"adapter="<<bundle.adapterName<<"\nsourceDraws=65,66 samples=1 depth=D24S8 rawDepthReadback=0 nativeFixedVertexCapture=0 productionActivation=0\n";
    const std::vector<std::array<unsigned,2>> points{{1040,725},{1097,740},{1136,757},{1163,776},{1041,725},{1097,741}};
    std::ofstream queries(output/"queries.csv"),thresholds(output/"thresholds.csv"),vertices(output/"vertices.csv"),controls(output/"controls.csv");
    queries<<"path,draw,bits,comparison,fresh,point,x,y,dx9,dx11\n";
    thresholds<<"path,draw,point,x,y,dx9ThresholdBits,dx11ThresholdBits,dx9Depth,dx11Depth,floatBitDelta,d24TickDelta,repeatExact\n";
    vertices<<"draw,vertex,component,gpuValue,gpuBits,cpuFusedValue,cpuFusedBits\n";vertices.precision(17);thresholds.precision(17);
    controls<<"name,repeat,point,x,y,dx9R,dx9G,dx9B,dx11R,dx11G,dx11B\n";
    auto render=[&](const std::vector<D3D9ReplaySnapshot>& draws,RgbaImage& native,RgbaImage& replay,DWORD clear=0xff000000){
        return Render(window,capture,bundle,draws,native,replay,clear);
    };
    // Remove textures/light/blending equally; preserve original geometry,
    // transforms, viewport and depth tests. First confirm paired overlap.
    const auto controlsRow=[&](const char* name,unsigned repeat,const RgbaImage& n,const RgbaImage& r){for(unsigned p=0;p<points.size();++p){auto xy=points[p];const auto at=(std::size_t(xy[1])*capture.width+xy[0])*4;
        controls<<name<<","<<repeat<<","<<p<<","<<xy[0]<<","<<xy[1];for(unsigned c=0;c<3;++c)controls<<","<<unsigned(n.pixels[at+c]);for(unsigned c=0;c<3;++c)controls<<","<<unsigned(r.pixels[at+c]);controls<<"\n";}controls.flush();};
    for(unsigned repeat=0;repeat<3;++repeat){RgbaImage n,r;CHECK(render({Id(first,false),Id(second,true)},n,r));controlsRow("pair_depth",repeat,n,r);
        auto a=Id(first,false),b=Id(second,true);ground_history_isolation::State(b,D3DRS_ZENABLE,FALSE);CHECK(render({a,b},n,r));controlsRow("pair_no_depth",repeat,n,r);}
    std::array<std::vector<Clip>,2> clips;const std::array<D3D9ReplaySnapshot,2> sources{first,second};
    for(unsigned t=0;t<2;++t){const auto source=Id(sources[t],false);std::vector<Clip> raw;
        CHECK(CaptureDepthVertexShader(source,raw,nullptr,false,0,nullptr,nullptr,nullptr,false,nullptr,0,false,false,true));CHECK(raw.size()==4);
        for(unsigned repeat=0;repeat<3;++repeat){std::vector<Clip> repeated;CHECK(CaptureDepthVertexShader(source,repeated,nullptr,false,0,nullptr,nullptr,nullptr,false,nullptr,0,false,false,true));CHECK(repeated==raw);}
        auto matrix=[](const D3DMATRIX& value){depth_diagnostic::Matrix result;std::memcpy(result.data(),&value,64);return result;};
        const auto combined=depth_diagnostic::Multiply(depth_diagnostic::Multiply(matrix(source.world),matrix(source.view),depth_diagnostic::Rounding::Sequential),matrix(source.projection),depth_diagnostic::Rounding::Sequential);
        for(unsigned v=0;v<raw.size();++v){Clip object{0,0,0,1};std::memcpy(object.data(),source.vertexBytes.data()+v*32,12);
            for(unsigned c=0;c<4;++c){const float column[]{combined[c],combined[c+4],combined[c+8],combined[c+12]};const float predicted=depth_diagnostic::Dot(object.data(),column,depth_diagnostic::Rounding::Fused);
                vertices<<65+t<<","<<v<<","<<c<<","<<raw[v][c]<<","<<Bits(raw[v][c])<<","<<predicted<<","<<Bits(predicted)<<"\n";CHECK(Bits(raw[v][c])==Bits(predicted));}}
        for(unsigned n=0;n<source.count*3;++n){const auto index=ground_history_isolation::Index(source,source.start+n);CHECK(index<raw.size());clips[t].push_back(raw[index]);}
        ground_endpoint_depth::Save(output/("draw"+std::to_string(65+t)+".clip.bin"),raw.data(),raw.size()*16);
    }
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,capture.width,capture.height,&capture.region,true));
    std::size_t queryCount=0,measurements=0;
    for(unsigned path=0;path<2;++path)for(unsigned t=0;t<2;++t){
        using Answers=std::vector<std::array<char,2>>;std::map<std::pair<unsigned,bool>,Answers> cache;
        const auto relation=[&](unsigned bits,bool equal,Answers& answer,bool fresh=false){const auto key=std::make_pair(bits,equal);const auto prior=cache.find(key);
            if(!fresh && prior!=cache.end()){answer=prior->second;return true;}RgbaImage n,r;
            const bool okay=path?shared.Render(clips[t],Float(bits),equal,n,r):render({Id(sources[t],false),ground_endpoint_depth::Ruler(Float(bits),capture.region,equal?D3DCMP_EQUAL:D3DCMP_LESS)},n,r);
            if(!okay)return false;answer.clear();for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const std::array<char,2> pair{Color(n,xy[0],xy[1]),Color(r,xy[0],xy[1])};if(pair[0]=='B' || pair[1]=='B')return false;answer.push_back(pair);
                queries<<(path?"shared_clip":"original_transform")<<","<<65+t<<","<<bits<<","<<(equal?"Equal":"Less")<<","<<fresh<<","<<p<<","<<xy[0]<<","<<xy[1]<<","<<pair[0]<<","<<pair[1]<<"\n";}
            if(prior!=cache.end() && prior->second!=answer)return false;cache[key]=answer;queries.flush();++queryCount;return bool(queries);};
        for(unsigned point=0;point<points.size();++point){Answers answer;unsigned limits[2];const unsigned low=Bits(.9f),high=Bits(.99999f);
            CHECK(relation(low,false,answer) && answer[point]==(std::array<char,2>{'G','G'}));CHECK(relation(high,false,answer) && answer[point]==(std::array<char,2>{'R','R'}));
            for(unsigned backend=0;backend<2;++backend){unsigned lo=low,hi=high;while(hi-lo>1){const auto mid=lo+(hi-lo)/2;CHECK(relation(mid,false,answer));if(answer[point][backend]=='G')lo=mid;else hi=mid;}limits[backend]=hi;
                CHECK(relation(hi,true,answer) && answer[point][backend]=='G');}
            for(unsigned repeat=0;repeat<3;++repeat)for(unsigned backend=0;backend<(limits[0]==limits[1]?1u:2u);++backend){const auto threshold=limits[backend];
                CHECK(relation(threshold,true,answer,true) && answer[point][backend]=='G');CHECK(relation(threshold-1,false,answer,true) && answer[point][backend]=='G');CHECK(relation(threshold,false,answer,true) && answer[point][backend]=='R');}
            thresholds<<(path?"shared_clip":"original_transform")<<","<<65+t<<","<<point<<","<<points[point][0]<<","<<points[point][1]<<","<<limits[0]<<","<<limits[1]<<","<<Float(limits[0])<<","<<Float(limits[1])<<","<<std::int64_t(limits[1])-limits[0]<<","<<std::llround(double(Float(limits[1]))*16777215)-std::llround(double(Float(limits[0]))*16777215)<<",1\n";thresholds.flush();++measurements;
            std::printf("accessoryDepth path=%s draw=%u point=%u dx9Bits=%u dx11Bits=%u repeatExact=1\n",path?"shared_clip":"original_transform",65+t,point,limits[0],limits[1]);std::fflush(stdout);
        }
    }
    // Independent ruler calibration, including equality and adjacent floats.
    std::ofstream calibration(output/"calibration.csv");calibration<<"offset,compare,point,dx9,dx11,expected\n";
    const unsigned center=Bits(.97f);for(int offset=-2;offset<=2;++offset)for(unsigned mode=0;mode<3;++mode){auto plane=Id(ground_endpoint_depth::Ruler(Float(center),capture.region,D3DCMP_ALWAYS),false);
        const auto comparison=mode==0?D3DCMP_LESS:mode==1?D3DCMP_EQUAL:D3DCMP_LESSEQUAL;RgbaImage n,r;CHECK(render({plane,ground_endpoint_depth::Ruler(Float(center+offset),capture.region,comparison)},n,r));
        const char expected=(mode==0?offset<0:mode==1?offset==0:offset<=0)?'G':'R';for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const auto a=Color(n,xy[0],xy[1]),b=Color(r,xy[0],xy[1]);CHECK(a==expected && b==expected);calibration<<offset<<","<<mode<<","<<p<<","<<a<<","<<b<<","<<expected<<"\n";}}
    // Retain all native material states, alpha tests, textures and preceding
    // draws when measuring the actual stored history. A red color-only cover
    // makes ruler visibility unambiguous without changing depth or stencil.
    for(unsigned n=0;n<capture.draws.size();++n)capture.draws[n].accessoryMaterial=(n>=2 && n<=20) || n>=61;
    std::ofstream history(output/"history_thresholds.csv"),historyQueries(output/"history_queries.csv"),historyControls(output/"history_controls.csv");
    history<<"afterDraw,point,x,y,dx9ThresholdBits,dx11ThresholdBits,dx9Depth,dx11Depth,floatBitDelta,d24TickDelta,repeatExact\n";history.precision(17);
    historyQueries<<"afterDraw,phase,iteration,point,bits,comparison,dx9,dx11\n";
    historyControls<<"afterDraw,repeat,differentPixels,rgbDifferent,alphaDifferent,point,x,y,dx9Alpha,dx11Alpha\n";
    auto cover=Id(ground_endpoint_depth::Ruler(0,capture.region,D3DCMP_ALWAYS),false);ground_history_isolation::State(cover,D3DRS_ZENABLE,FALSE);ground_history_isolation::State(cover,D3DRS_ZWRITEENABLE,FALSE);
    auto rulers=[&](const std::vector<unsigned>& bits,bool equal){auto c=ground_endpoint_depth::Ruler(0,capture.region,equal?D3DCMP_EQUAL:D3DCMP_LESS);c.vertexBytes.clear();c.indexBytes.clear();
        for(unsigned p=0;p<points.size();++p){for(unsigned v=0;v<4;++v){const float x=float(points[p][0])+(v>=2?.375f:-.375f),y=float(points[p][1])+(v%2?.375f:-.375f);
                const float vertex[]{2*(x-capture.region.X)/capture.region.Width-1,1-2*(y-capture.region.Y)/capture.region.Height,Float(bits[p]),0,0,1,0,0};
                const auto* bytes=reinterpret_cast<const unsigned char*>(vertex);c.vertexBytes.insert(c.vertexBytes.end(),bytes,bytes+sizeof(vertex));}
            for(unsigned local:{0u,1u,2u,2u,1u,3u}){const unsigned short index=static_cast<unsigned short>(p*4+local);const auto* bytes=reinterpret_cast<const unsigned char*>(&index);c.indexBytes.insert(c.indexBytes.end(),bytes,bytes+2);}}
        c.count=unsigned(points.size()*2);c.vertices=unsigned(points.size()*4);return c;};
    std::size_t historySubmissions=0;
    for(unsigned after:{65u,66u}){const std::vector<D3D9ReplaySnapshot> prefix(capture.draws.begin(),capture.draws.begin()+after);
        for(unsigned repeat=0;repeat<3;++repeat){RgbaImage n,r;CHECK(render(prefix,n,r,capture.clear));unsigned different=0,rgb=0,alpha=0;
            for(unsigned y=capture.region.Y;y<capture.region.Y+capture.region.Height;++y)for(unsigned x=capture.region.X;x<capture.region.X+capture.region.Width;++x){const auto at=(std::size_t(y)*capture.width+x)*4;different+=std::memcmp(n.pixels.data()+at,r.pixels.data()+at,4)!=0;rgb+=std::memcmp(n.pixels.data()+at,r.pixels.data()+at,3)!=0;alpha+=n.pixels[at+3]!=r.pixels[at+3];}
            for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const auto at=(std::size_t(xy[1])*capture.width+xy[0])*4;historyControls<<after<<","<<repeat<<","<<different<<","<<rgb<<","<<alpha<<","<<p<<","<<xy[0]<<","<<xy[1]<<","<<unsigned(n.pixels[at+3])<<","<<unsigned(r.pixels[at+3])<<"\n";}historyControls.flush();
            std::printf("accessoryHistory after=%u repeat=%u differentPixels=%u rgb=%u alpha=%u\n",after,repeat,different,rgb,alpha);std::fflush(stdout);}
        using Answers=std::vector<std::array<char,2>>;
        auto query=[&](const std::vector<unsigned>& bits,bool equal,const char* phase,unsigned iteration,Answers& answer){auto draws=prefix;draws.push_back(cover);draws.push_back(rulers(bits,equal));RgbaImage n,r;if(!render(draws,n,r,capture.clear))return false;
            answer.clear();for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const std::array<char,2> pair{Color(n,xy[0],xy[1]),Color(r,xy[0],xy[1])};if(pair[0]=='B' || pair[1]=='B')return false;answer.push_back(pair);
                historyQueries<<after<<","<<phase<<","<<iteration<<","<<p<<","<<bits[p]<<","<<(equal?"Equal":"Less")<<","<<pair[0]<<","<<pair[1]<<"\n";}historyQueries.flush();++historySubmissions;return bool(historyQueries);};
        Answers answer;std::array<std::vector<unsigned>,2> limits;
        for(unsigned backend=0;backend<2;++backend){std::vector<unsigned> lo(points.size(),Bits(.9f)),hi(points.size(),Bits(.99999f));
            CHECK(query(lo,false,"low",backend,answer));for(auto a:answer)CHECK(a[backend]=='G');CHECK(query(hi,false,"high",backend,answer));for(auto a:answer)CHECK(a[backend]=='R');
            for(unsigned iteration=0;;++iteration){std::vector<unsigned> mid;bool done=true;for(unsigned p=0;p<points.size();++p){mid.push_back(lo[p]+(hi[p]-lo[p])/2);done&=hi[p]-lo[p]<=1;}if(done)break;
                CHECK(iteration<32 && query(mid,false,backend?"search11":"search9",iteration,answer));for(unsigned p=0;p<points.size();++p)if(hi[p]-lo[p]>1){if(answer[p][backend]=='G')lo[p]=mid[p];else hi[p]=mid[p];}}
            limits[backend]=hi;
            for(unsigned repeat=0;repeat<3;++repeat){CHECK(query(hi,true,"repeatEqual",repeat,answer));for(auto a:answer)CHECK(a[backend]=='G');
                CHECK(query(lo,false,"repeatBelow",repeat,answer));for(auto a:answer)CHECK(a[backend]=='G');CHECK(query(hi,false,"repeatAt",repeat,answer));for(auto a:answer)CHECK(a[backend]=='R');}}
        for(unsigned p=0;p<points.size();++p){const auto a=limits[0][p],b=limits[1][p];history<<after<<","<<p<<","<<points[p][0]<<","<<points[p][1]<<","<<a<<","<<b<<","<<Float(a)<<","<<Float(b)<<","<<std::int64_t(b)-a<<","<<std::llround(double(Float(b))*16777215)-std::llround(double(Float(a))*16777215)<<",1\n";
            std::printf("accessoryHistoryDepth after=%u point=%u dx9Bits=%u dx11Bits=%u\n",after,p,a,b);std::fflush(stdout);}history.flush();
    }
    std::ofstream summary(output/"summary.txt");summary<<"measurements="<<measurements<<" querySubmissions="<<queryCount<<" pointQueries="<<queryCount*points.size()<<" calibration=90 historyMeasurements=12 historyQuerySubmissions="<<historySubmissions<<" vertexRepeatExact=1 thresholdRepeatExact=1 productionActivation=0 rawD24Readback=0 nativeFixedVertexCapture=0\n";
    CHECK(metadata && queries && thresholds && vertices && controls && calibration && history && historyQueries && historyControls && summary && bundle.swapchain->Retire());return 0;
}
inline int AlphaControls(HWND window,const char* archive,const char* destination){
    ground_history_isolation::Archive capture;CHECK(capture.Load(archive,66));
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    for(unsigned n=0;n<capture.draws.size();++n)capture.draws[n].accessoryMaterial=(n>=2 && n<=20) || n>=61;
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware,{ModelCompatibility::Dx9Measured});CHECK(bundle);
    const std::vector<std::array<unsigned,2>> points{{1040,725},{1097,740},{1136,757},{1163,776},{1041,725},{1097,741}};
    std::ofstream report(output/"alpha_controls.csv");report<<"mode,reference,repeat,point,x,y,dx9R,dx9G,dx9B,dx9Alpha,dx11R,dx11G,dx11B,dx11Alpha\n";
    // Color-only observations isolate the original alpha test without depth,
    // stencil or blending. Ref -1 disables alpha testing; 0..3 scan its edge.
    for(int reference=-1;reference<=3;++reference)for(unsigned repeat=0;repeat<3;++repeat){auto source=capture.draws[64];
        ground_history_isolation::State(source,D3DRS_ZENABLE,FALSE);ground_history_isolation::State(source,D3DRS_ZWRITEENABLE,FALSE);
        ground_history_isolation::State(source,D3DRS_STENCILENABLE,FALSE);ground_history_isolation::State(source,D3DRS_ALPHABLENDENABLE,FALSE);
        ground_history_isolation::State(source,D3DRS_ALPHATESTENABLE,reference>=0);if(reference>=0)ground_history_isolation::State(source,D3DRS_ALPHAREF,DWORD(reference));
        RgbaImage n,r;CHECK(Render(window,capture,bundle,{source},n,r,0xff000000));
        for(unsigned p=0;p<points.size();++p){const auto xy=points[p];const auto at=(std::size_t(xy[1])*capture.width+xy[0])*4;report<<"isolated65,"<<reference<<","<<repeat<<","<<p<<","<<xy[0]<<","<<xy[1];
            for(unsigned c=0;c<4;++c)report<<","<<unsigned(n.pixels[at+c]);for(unsigned c=0;c<4;++c)report<<","<<unsigned(r.pixels[at+c]);report<<"\n";}report.flush();}
    // A constant ruler between the two stored depth histories verifies the
    // depth-write consequence of changing only draw 65's alpha test.
    for(unsigned enabled=0;enabled<2;++enabled)for(unsigned repeat=0;repeat<3;++repeat){auto prefix=capture.draws;prefix.resize(65);
        ground_history_isolation::State(prefix.back(),D3DRS_ALPHATESTENABLE,enabled);
        auto cover=Id(ground_endpoint_depth::Ruler(0,capture.region,D3DCMP_ALWAYS),false);ground_history_isolation::State(cover,D3DRS_ZENABLE,FALSE);ground_history_isolation::State(cover,D3DRS_ZWRITEENABLE,FALSE);prefix.push_back(cover);
        const float a=0.97888469696044922f,b=0.97915250062942505f;prefix.push_back(ground_endpoint_depth::Ruler((a+b)/2,capture.region,D3DCMP_LESS));
        RgbaImage n,r;CHECK(Render(window,capture,bundle,prefix,n,r,capture.clear));const auto xy=points[0];const auto at=(std::size_t(xy[1])*capture.width+xy[0])*4;
        report<<"history65_midpoint,"<<enabled<<","<<repeat<<",0,"<<xy[0]<<","<<xy[1];for(unsigned c=0;c<4;++c)report<<","<<unsigned(n.pixels[at+c]);for(unsigned c=0;c<4;++c)report<<","<<unsigned(r.pixels[at+c]);report<<"\n";report.flush();}
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 alphaReferenceControls=15 historyDepthControls=6 productionActivation=0 imageAcceptance=0\n";
    CHECK(report && summary && bundle.swapchain->Retire());return 0;
}
}
