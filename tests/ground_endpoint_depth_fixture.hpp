#pragma once
// Measurements on fixed private captures; no production arithmetic changes.
namespace ground_endpoint_depth {
using Clip=std::array<float,4>;
using ground_history_isolation::State;
inline unsigned Bits(float f){unsigned u;std::memcpy(&u,&f,4);return u;}
inline float Float(unsigned u){float f;std::memcpy(&f,&u,4);return f;}
inline void Save(const std::filesystem::path& path,const void* data,std::size_t bytes){std::ofstream f(path,std::ios::binary);f.write(static_cast<const char*>(data),bytes);}
inline Clip Screen(const Clip& p,const D3DVIEWPORT9& v,bool corrected) {
    return {v.X+(p[0]/p[3]+1)*v.Width/2-(corrected?.5f:0),v.Y+(1-p[1]/p[3])*v.Height/2-(corrected?.5f:0),
        v.MinZ+p[2]/p[3]*(v.MaxZ-v.MinZ),1/p[3]};
}
// ProcessVertices is an API observation, not stream output from the actual
// fixed-function draw. Software and hardware creation flags remain explicit.
inline HRESULT Process(HWND window,const D3D9ReplaySnapshot& c,bool software,std::vector<Clip>& positions) {
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));if(!api)return E_FAIL;
    D3DPRESENT_PARAMETERS pp{};pp.BackBufferWidth=c.viewport.X+c.viewport.Width;pp.BackBufferHeight=c.viewport.Y+c.viewport.Height;
    pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.BackBufferCount=1;pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.hDeviceWindow=window;
    ComPtr<IDirect3DDevice9> device;HRESULT hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,software?D3DCREATE_SOFTWARE_VERTEXPROCESSING:D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);if(FAILED(hr))return hr;
    ComPtr<IDirect3DVertexBuffer9> input,output;const unsigned count=static_cast<unsigned>(c.vertexBytes.size()/c.stride);
    hr=device->CreateVertexBuffer(static_cast<unsigned>(c.vertexBytes.size()),0,c.fvf,software?D3DPOOL_SYSTEMMEM:D3DPOOL_DEFAULT,&input,nullptr);if(FAILED(hr))return hr;
    hr=device->CreateVertexBuffer(count*20,0,D3DFVF_XYZRHW|D3DFVF_DIFFUSE,software?D3DPOOL_SYSTEMMEM:D3DPOOL_DEFAULT,&output,nullptr);if(FAILED(hr))return hr;
    void* bytes=nullptr;hr=input->Lock(0,0,&bytes,0);if(FAILED(hr))return hr;std::memcpy(bytes,c.vertexBytes.data(),c.vertexBytes.size());if(FAILED(hr=input->Unlock()))return hr;
    if(FAILED(hr=device->SetStreamSource(0,input.Get(),0,c.stride)) || FAILED(hr=device->SetFVF(c.fvf)) || FAILED(hr=device->SetViewport(&c.viewport)) ||
       FAILED(hr=device->SetTransform(D3DTS_WORLD,&c.world)) || FAILED(hr=device->SetTransform(D3DTS_VIEW,&c.view)) || FAILED(hr=device->SetTransform(D3DTS_PROJECTION,&c.projection)) ||
       FAILED(hr=device->SetRenderState(D3DRS_LIGHTING,FALSE)))return hr;
    ComPtr<IDirect3DVertexDeclaration9> declaration;
    const D3DVERTEXELEMENT9 elements[]={{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITIONT,0},
        {0,16,D3DDECLTYPE_D3DCOLOR,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_COLOR,0},D3DDECL_END()};
    if(!software && FAILED(hr=device->CreateVertexDeclaration(elements,&declaration)))return hr;
    hr=device->ProcessVertices(0,0,count,output.Get(),declaration.Get(),0);if(FAILED(hr))return hr;
    hr=output->Lock(0,0,&bytes,D3DLOCK_READONLY);if(FAILED(hr))return hr;positions.resize(count);
    for(unsigned n=0;n<count;++n)std::memcpy(positions[n].data(),static_cast<char*>(bytes)+n*20,16);
    return output->Unlock();
}
inline D3D9ReplaySnapshot Line18(const D3D9ReplaySnapshot& source) {
    auto c=source;c.start+=17*2;c.count=1;std::vector<unsigned char> bytes;
    for(unsigned n=0;n<2;++n){const auto index=ground_history_isolation::Index(c,c.start+n);if(index>=c.vertexBytes.size()/16)return {};
        bytes.insert(bytes.end(),c.vertexBytes.begin()+index*16,c.vertexBytes.begin()+(index+1)*16);}
    c.vertexBytes=std::move(bytes);c.indexBytes={0,0,1,0};c.start=c.minimum=0;c.vertices=2;c.indexFormat=D3DFMT_INDEX16;return c;
}
inline int ProcessChild(HWND window,const char* archive,const char* destination,bool software) {
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
    ground_history_isolation::Archive a;CHECK(a.Load(archive,1));auto line=Line18(a.draws[0]);CHECK(line.vertexBytes.size()==32);
    std::vector<Clip> positions;const auto hr=Process(window,line,software,positions);std::ofstream status(std::string(destination)+".status");
    status<<"HRESULT="<<std::hex<<static_cast<unsigned long>(hr)<<std::dec<<" actualDrawOutputCapture=0\n";status.flush();
    if(FAILED(hr))return 31;CHECK(positions.size()==2);Save(std::string(destination)+".screen.bin",positions.data(),32);return 0;
}
inline DWORD ProcessIsolated(const char* archive,const std::filesystem::path& stem,bool software) {
    wchar_t module[MAX_PATH];if(!GetModuleFileNameW(nullptr,module,MAX_PATH))return ~0u;
    const std::wstring input=std::filesystem::absolute(archive).wstring(),output=std::filesystem::absolute(stem).wstring();
    std::wstring command=L"\""+std::wstring(module)+L"\" --ground-process-vertices \""+input+L"\" \""+output+L"\" "+(software?L"software":L"hardware");
    STARTUPINFOW startup{};startup.cb=sizeof(startup);startup.dwFlags=STARTF_USESHOWWINDOW;startup.wShowWindow=SW_HIDE;
    PROCESS_INFORMATION process{};if(!CreateProcessW(nullptr,command.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&startup,&process))return ~0u;
    CloseHandle(process.hThread);const auto waited=WaitForSingleObject(process.hProcess,30000);DWORD exit=~0u;
    if(waited==WAIT_OBJECT_0)GetExitCodeProcess(process.hProcess,&exit);else TerminateProcess(process.hProcess,78);
    CloseHandle(process.hProcess);return exit;
}
inline int Endpoints(HWND window,const char* archive,const char* destination) {
    ground_history_isolation::Archive a;CHECK(a.Load(archive,1));ground_history_isolation::Probe probe(window,a,destination);CHECK(probe.Initialize());
    CHECK(probe.Render("original",a.draws,true));CHECK(a.draws[0].count>17);auto line=Line18(a.draws[0]);CHECK(line.vertexBytes.size()==32);
    CHECK(probe.Render("compact",{line}));std::vector<Clip> final,raw;
    CHECK(CaptureDepthVertexShader(line,final,&raw,true,3,nullptr,nullptr,nullptr,true));CHECK(final.size()==2 && raw.size()==2);
    for(unsigned repeat=0;repeat<3;++repeat){std::vector<Clip> p,q;CHECK(CaptureDepthVertexShader(line,p,&q,true,3,nullptr,nullptr,nullptr,true));CHECK(p==final && q==raw);}
    Save(probe.output/"candidate.raw_clip.bin",raw.data(),raw.size()*16);Save(probe.output/"candidate.final_clip.bin",final.data(),final.size()*16);
    Save(probe.output/"source.vertices",line.vertexBytes.data(),line.vertexBytes.size());
    std::ofstream report(probe.output/"endpoints.csv");report<<"source,endpoint,x,y,z,w,bitsX,bitsY,bitsZ,bitsW\n";report<<std::setprecision(17);
    auto row=[&](const std::string& name,unsigned n,const Clip& p){report<<name<<","<<n;for(float f:p)report<<","<<f;for(float f:p)report<<","<<Bits(f);report<<"\n";};
    for(unsigned n=0;n<2;++n){row("candidate_raw_clip",n,raw[n]);row("candidate_final_clip",n,final[n]);row("candidate_screen",n,Screen(final[n],a.region,true));}
    std::ofstream process(probe.output/"process_vertices.txt");
    report.flush();
    for(bool software:{false,true}){const std::string name=software?"process_software":"process_hardware";
        const auto exit=ProcessIsolated(archive,probe.output/name,software);process<<name<<" childExit="<<exit<<" actualDrawOutputCapture=0\n";process.flush();
        if(!exit){std::vector<Clip> p(2);std::ifstream f(probe.output/(name+".screen.bin"),std::ios::binary);CHECK(f.read(reinterpret_cast<char*>(p.data()),32));
            for(unsigned n=0;n<2;++n)row(name,n,p[n]);}}
    // CPU candidates are labelled hypotheses, never native output captures.
    depth_diagnostic::Matrix w,v,p;std::memcpy(w.data(),&line.world,64);std::memcpy(v.data(),&line.view,64);std::memcpy(p.data(),&line.projection,64);
    for(unsigned rule=0;rule<4;++rule){const auto rounding=static_cast<depth_diagnostic::Rounding>(rule);
        const auto combined=depth_diagnostic::Multiply(depth_diagnostic::Multiply(w,v,rounding),p,rounding);
        for(unsigned n=0;n<2;++n){Clip object{0,0,0,1},clip;std::memcpy(object.data(),line.vertexBytes.data()+n*16,12);
            for(unsigned col=0;col<4;++col){const float column[]={combined[col],combined[col+4],combined[col+8],combined[col+12]};clip[col]=depth_diagnostic::Dot(object.data(),column,rounding);}
            row("cpu_rule"+std::to_string(rule)+"_clip",n,clip);row("cpu_rule"+std::to_string(rule)+"_screen",n,Screen(clip,a.region,false));}}
    auto uniform=line;State(uniform,D3DRS_ZENABLE,0);State(uniform,D3DRS_ZWRITEENABLE,0);State(uniform,D3DRS_STENCILENABLE,0);
    State(uniform,D3DRS_ALPHATESTENABLE,0);State(uniform,D3DRS_ALPHABLENDENABLE,0);State(uniform,D3DRS_LIGHTING,0);
    for(unsigned n=0;n<2;++n){const DWORD red=0xffff0000;std::memcpy(uniform.vertexBytes.data()+n*16+12,&red,4);}
    CHECK(probe.Render("uniform",{uniform}));const auto uniformN=probe.native,uniformR=probe.candidate;
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,a.width,a.height,&a.region));RgbaImage native,replay;
    CHECK(shared.RenderLine(raw,native,replay));const auto firstN=scene_prefix_diagnostic::Crop(native,a.region),firstR=scene_prefix_diagnostic::Crop(replay,a.region);
    Save(probe.output/"common_clip.native.bgra",firstN.data(),firstN.size());Save(probe.output/"common_clip.candidate.bgra",firstR.data(),firstR.size());
    CHECK(shared.RenderLine(raw,native,replay) && scene_prefix_diagnostic::Crop(native,a.region)==firstN && scene_prefix_diagnostic::Crop(replay,a.region)==firstR);
    unsigned different=0,nativeChanged=0,candidateChanged=0;for(unsigned at=0;at<firstN.size();at+=4){different+=std::memcmp(firstN.data()+at,firstR.data()+at,4)!=0;
        nativeChanged+=std::memcmp(firstN.data()+at,uniformN.data()+at,4)!=0;candidateChanged+=std::memcmp(firstR.data()+at,uniformR.data()+at,4)!=0;}
    process<<"commonClipDifferentPixels="<<different<<" commonClipRepeatExact=1 nativeChangedFromUniform="<<nativeChanged<<" candidateChangedFromUniform="<<candidateChanged<<" outsideRegionUnspecified=1\n";
    std::printf("endpointMeasurement commonClipDifferentPixels=%u candidateStreamOutputRepeated=1 processVerticesIsActualDrawCapture=0\n",different);
    CHECK(report && process);CHECK(probe.Finish());return 0;
}
inline D3D9ReplaySnapshot Id(D3D9ReplaySnapshot c,bool green) {
    State(c,D3DRS_ZENABLE,TRUE);State(c,D3DRS_ZWRITEENABLE,TRUE);State(c,D3DRS_ZFUNC,D3DCMP_LESSEQUAL);
    State(c,D3DRS_STENCILENABLE,FALSE);State(c,D3DRS_ALPHABLENDENABLE,FALSE);State(c,D3DRS_ALPHATESTENABLE,FALSE);
    State(c,D3DRS_CULLMODE,D3DCULL_NONE);State(c,D3DRS_COLORWRITEENABLE,15);State(c,D3DRS_SPECULARENABLE,FALSE);
    Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);c.textureInfo={};c.textureBytes={};c.preparedMips={};c.lights.clear();
    if(c.stride==16){State(c,D3DRS_LIGHTING,FALSE);const DWORD color=green?0xff00ff00:0xffff0000;for(std::size_t n=12;n<c.vertexBytes.size();n+=16)std::memcpy(c.vertexBytes.data()+n,&color,4);}
    else{State(c,D3DRS_LIGHTING,TRUE);State(c,D3DRS_AMBIENT,0);c.material={};c.material.Diffuse.a=1;c.material.Emissive=green?D3DCOLORVALUE{0,1,0,0}:D3DCOLORVALUE{1,0,0,0};}
    return c;
}
inline D3D9ReplaySnapshot Ruler(float depth,const D3DVIEWPORT9& viewport,unsigned compare) {
    auto c=Id(Fixture(),true);c.viewport=viewport;
    const float vertices[]={-1,-1,depth,0,0,1,0,0,-1,1,depth,0,0,1,0,0,1,-1,depth,0,0,1,0,0,1,1,depth,0,0,1,0,0};
    c.vertexBytes.resize(sizeof(vertices));std::memcpy(c.vertexBytes.data(),vertices,sizeof(vertices));c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};c.count=2;c.vertices=4;
    State(c,D3DRS_ZWRITEENABLE,FALSE);State(c,D3DRS_ZFUNC,compare);return c;
}
inline char Color(const RgbaImage& image,unsigned x,unsigned y){const auto* p=image.pixels.data()+(std::size_t(y)*image.width+x)*4;
    return p[0]==255 && !p[1] && !p[2] && p[3]==255?'R':!p[0] && p[1]==255 && !p[2] && p[3]==255?'G':'B';}
inline int Depth(HWND window,const char* archive,const char* destination) {
    ground_history_isolation::Archive a;CHECK(a.Load(archive,6));ground_history_isolation::Probe probe(window,a,destination);CHECK(probe.Initialize());CHECK(probe.Render("original",a.draws,true));
    unsigned focus=~0u;for(unsigned n=0;n<probe.native.size()/4;++n)if(std::memcmp(probe.native.data()+n*4,probe.candidate.data()+n*4,4)){focus=n;break;}CHECK(focus!=~0u);
    const unsigned fx=a.region.X+focus%a.region.Width,fy=a.region.Y+focus/a.region.Width;
    std::array<D3D9ReplaySnapshot,2> triangles{ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(a.draws[1],1,1)),
        ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(a.draws[5],1141,1))};
    CHECK(probe.Render("compact_pair",{triangles[0],triangles[1]}));CHECK(std::memcmp(probe.native.data()+focus*4,probe.candidate.data()+focus*4,4));
    std::array<std::vector<Clip>,2> final,raw;
    for(unsigned t=0;t<2;++t){CHECK(CaptureDepthVertexShader(triangles[t],final[t],&raw[t],true,3,nullptr,nullptr,nullptr,true));CHECK(raw[t].size()==3);
        Save(probe.output/("triangle"+std::to_string(t)+".raw_clip.bin"),raw[t].data(),48);Save(probe.output/("triangle"+std::to_string(t)+".final_clip.bin"),final[t].data(),48);
        Save(probe.output/("triangle"+std::to_string(t)+".vertices"),triangles[t].vertexBytes.data(),triangles[t].vertexBytes.size());}
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,a.width,a.height,&a.region));
    auto render=[&](const std::vector<D3D9ReplaySnapshot>& draws,RgbaImage& native,RgbaImage& replay){
        if(!NativeImage(window,draws,static_cast<unsigned>(draws.size()),native,nullptr,a.width,a.height))return false;
        ModelReplayStream s;s.target.width=a.width;s.target.height=a.height;s.events.push_back({1,ModelReplayOp::Clear});for(const auto& c:draws)if(!AppendD3D9ReplaySnapshot(s,c,true))return false;
        s.complete=true;return bool(ReplayD3D11WCandidatePrefix(*probe.bundle.device,s,draws.size(),replay));};
    // Holdout points depend only on common coverage, before threshold searches.
    std::array<RgbaImage,2> coverageN,coverageR;
    for(unsigned t=0;t<2;++t)CHECK(render({Id(triangles[t],false)},coverageN[t],coverageR[t]));
    std::vector<std::array<unsigned,2>> points{{fx,fy}};
    for(unsigned radius=1;radius<=8 && points.size()<3;++radius)for(int dy=-int(radius);dy<=int(radius) && points.size()<3;++dy)for(int dx=-int(radius);dx<=int(radius) && points.size()<3;++dx) {
        if((std::max)(std::abs(dx),std::abs(dy))!=int(radius))continue;const int x=int(fx)+dx,y=int(fy)+dy;if(x<0 || y<0 || x>=int(a.width) || y>=int(a.height))continue;
        bool covered=true;for(unsigned t=0;t<2;++t)covered&=Color(coverageN[t],x,y)=='R' && Color(coverageR[t],x,y)=='R';
        if(covered)points.push_back({unsigned(x),unsigned(y)});
    }CHECK(points.size()==3);
    std::ofstream csv(probe.output/"thresholds.csv"),queries(probe.output/"queries.csv"),calibration(probe.output/"calibration.csv");
    csv<<"path,triangle,point,x,y,dx9ThresholdBits,dx11ThresholdBits,dx9Equal,dx11Equal,repeatExact\n";
    queries<<"path,triangle,point,x,y,bits,comparison,fresh,dx9,dx11\n";
    calibration<<"offset,comparison,bits,dx9,dx11,expected\n";
    unsigned measurements=0,queryCount=0;
    for(unsigned path=0;path<2;++path)for(unsigned t=0;t<2;++t)for(unsigned point=0;point<points.size();++point) {
        const auto xy=points[point];const char* name=path?"shared_clip":"original_transform";
        std::map<std::pair<unsigned,bool>,std::array<char,2>> cache;
        auto relation=[&](unsigned bits,bool equal,std::array<char,2>& answer,bool fresh=false){const auto key=std::make_pair(bits,equal);auto found=cache.find(key);
            if(!fresh && found!=cache.end()){answer=found->second;return true;}RgbaImage n,r;const float z=Float(bits);
            const bool ok=path?shared.Render(raw[t],z,equal,n,r):render({Id(triangles[t],false),Ruler(z,a.region,equal?D3DCMP_EQUAL:D3DCMP_LESS)},n,r);
            if(!ok)return false;answer={Color(n,xy[0],xy[1]),Color(r,xy[0],xy[1])};if(answer[0]=='B' || answer[1]=='B' || (found!=cache.end() && found->second!=answer))return false;
            cache[key]=answer;queries<<name<<","<<t<<","<<point<<","<<xy[0]<<","<<xy[1]<<","<<bits<<","<<(equal?"Equal":"Less")<<","<<fresh<<","<<answer[0]<<","<<answer[1]<<"\n";queries.flush();++queryCount;
            if(fresh){const std::string stem=std::string(name)+"_t"+std::to_string(t)+"_p"+std::to_string(point)+"_b"+std::to_string(bits)+(equal?"_equal":"_less");
                // Small readback ROI retains the independently selected pixel,
                // neighboring coverage and classification, without huge files.
                D3DVIEWPORT9 roi{xy[0]-2,xy[1]-2,5,5,0,1};const auto a=scene_prefix_diagnostic::Crop(n,roi),b=scene_prefix_diagnostic::Crop(r,roi);
                Save(probe.output/(stem+".native.bgra"),a.data(),a.size());Save(probe.output/(stem+".candidate.bgra"),b.data(),b.size());}
            return bool(queries);};
        unsigned thresholds[2];std::array<char,2> answer;const unsigned low=Bits(.9f),high=Bits(.99999f);
        CHECK(relation(low,false,answer) && answer==(std::array<char,2>{'G','G'}));CHECK(relation(high,false,answer) && answer==(std::array<char,2>{'R','R'}));
        for(unsigned backend=0;backend<2;++backend){unsigned lo=low,hi=high;while(hi-lo>1){const unsigned mid=lo+(hi-lo)/2;CHECK(relation(mid,false,answer));if(answer[backend]=='G')lo=mid;else hi=mid;}thresholds[backend]=hi;
            CHECK(relation(hi,true,answer) && answer[backend]=='G');}
        for(unsigned repeat=0;repeat<3;++repeat)for(unsigned backend=0;backend<(thresholds[0]==thresholds[1]?1u:2u);++backend) {
            CHECK(relation(thresholds[backend],true,answer,true) && answer[backend]=='G');CHECK(relation(thresholds[backend]-1,false,answer,true) && answer[backend]=='G');
            CHECK(relation(thresholds[backend],false,answer,true) && answer[backend]=='R');}
        csv<<name<<","<<t<<","<<point<<","<<xy[0]<<","<<xy[1]<<","<<thresholds[0]<<","<<thresholds[1]<<",G,G,1\n";csv.flush();++measurements;
        std::printf("groundDepth path=%s triangle=%u point=%u pixel=%u,%u dx9Bits=%u dx11Bits=%u repeatExact=1\n",name,t,point,xy[0],xy[1],thresholds[0],thresholds[1]);std::fflush(stdout);
    }
    // Validate the ruler on a constant plane independently of scene geometry.
    const unsigned center=Bits(.97f);for(int offset=-2;offset<=2;++offset)for(unsigned mode=0;mode<3;++mode){auto first=Ruler(Float(center),a.region,D3DCMP_ALWAYS);first=Id(first,false);
        const auto comparison=mode==0?D3DCMP_LESS:mode==1?D3DCMP_EQUAL:D3DCMP_LESSEQUAL;RgbaImage n,r;CHECK(render({first,Ruler(Float(center+offset),a.region,comparison)},n,r));
        const char expected=(mode==0?offset<0:mode==1?offset==0:offset<=0)?'G':'R';CHECK(Color(n,fx,fy)==expected && Color(r,fx,fy)==expected);
        calibration<<offset<<","<<(mode==0?"Less":mode==1?"Equal":"LessEqual")<<","<<center+offset<<","<<Color(n,fx,fy)<<","<<Color(r,fx,fy)<<","<<expected<<"\n";}
    std::ofstream summary(probe.output/"measurement_summary.txt");summary<<"measurements="<<measurements<<" queries="<<queryCount<<" calibration=15 repeatExact=1 rawD24Readback=0 nativeFixedVertexCapture=0\n";
    CHECK(csv && queries && calibration && summary);CHECK(probe.Finish());return 0;
}
}
