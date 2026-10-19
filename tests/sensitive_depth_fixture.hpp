#pragma once

// Asset-free diagnostics using fixtures selected before any GPU measurement.
inline int SensitiveDepthControls(HWND window,const char* fixturePath,const char* outputPath) {
    using namespace depth_diagnostic;
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    std::ifstream input(fixturePath,std::ios::binary);char magic[8];unsigned count=0;
    CHECK(input.read(magic,8));const bool perspective=std::memcmp(magic,"SDEP0002",8)==0;
    CHECK((perspective || std::memcmp(magic,"SDEP0001",8)==0) && input.read(reinterpret_cast<char*>(&count),4));CHECK(count==12);
    std::vector<std::array<Matrix,3>> cases(count);
    CHECK(input.read(reinterpret_cast<char*>(cases.data()),count*48*4));CHECK(input.peek()==std::char_traits<char>::eof());
    std::ofstream csv(directory/"thresholds.csv");csv<<"case,split,mode,x,y,dx9ThresholdBits,dx11ThresholdBits,dx9Equal,dx11Equal,repeatExact\n";
    std::ofstream predictions(directory/"coefficients.csv");predictions<<"case,mode,z0,z1,z2,z3,w0,w1,w2,w3\n";predictions<<std::setprecision(17);
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware);CHECK(bundle);
    const char* names[]={"original","left_sequential","left_double","left_paired","left_fused","right_sequential","right_double","shared_camera","shared_ndc_float","shared_ndc_double"};
    const Rounding rules[]={Rounding::Sequential,Rounding::Double,Rounding::Paired,Rounding::Fused,Rounding::Sequential,Rounding::Double};
    auto id=[](D3D9ReplaySnapshot c,bool green){Set(c,D3DRS_LIGHTING,TRUE);Set(c,D3DRS_SPECULARENABLE,FALSE);
        Set(c,D3DRS_AMBIENT,0);c.material={};c.material.Diffuse.a=1;c.material.Emissive=green?D3DCOLORVALUE{0,1,0,0}:D3DCOLORVALUE{1,0,0,0};
        Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);return c;};
    auto render=[&](const std::vector<D3D9ReplaySnapshot>& draws,RgbaImage& native,RgbaImage& replay){
        if(!NativeImage(window,draws,unsigned(draws.size()),native))return false;
        ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& draw:draws)if(!AppendD3D9ReplaySnapshot(stream,draw))return false;
        stream.complete=true;return bool(ReplayD3D11ModelPrefix(*bundle.device,stream,draws.size(),replay));};
    auto color=[](const RgbaImage& image,unsigned x,unsigned y){const auto* p=image.pixels.data()+(y*64+x)*4;
        return p[0]==255 && !p[1] && !p[2]?'R':!p[0] && p[1]==255 && !p[2]?'G':'B';};
    auto reference=[&](float depth,unsigned comparison){auto c=id(Fixture(),true);
        const float v[]={-1,-1,depth,0,0,1,0,0,-1,1,depth,0,0,1,0,0,1,-1,depth,0,0,1,0,0,1,1,depth,0,0,1,0,0};
        c.vertexBytes.resize(sizeof(v));std::memcpy(c.vertexBytes.data(),v,sizeof(v));c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};c.vertices=4;c.count=2;
        Set(c,D3DRS_ZWRITEENABLE,FALSE);Set(c,D3DRS_ZFUNC,comparison);return c;};
    unsigned differing=0,measurements=0;
    std::printf("sensitiveDevice adapter=%s perspective=%u\n",bundle.adapterName.c_str(),unsigned(perspective));
    const auto planeDepth=[](const std::vector<std::array<float,4>>& clip,unsigned x,unsigned y){
        std::array<std::array<double,3>,3> p;
        for(unsigned n=0;n<3;++n){const auto& v=clip[n];if(!(v[3]>0))return -1.;
            p[n]={(double(v[0])/v[3]+1)*32-.5,(1-double(v[1])/v[3])*32-.5,double(v[2])/v[3]};}
        const auto& a=p[0];const auto& b=p[1];const auto& c=p[2];
        const double den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(den==0)return -1.;
        const double u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den;
        const double v=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den;
        return u*a[2]+v*b[2]+(1-u-v)*c[2];};
    for(unsigned number=0;number<count;++number) {
        auto original=id(Fixture(),false);for(unsigned n=0;n<3;++n){float z=0;std::memcpy(original.vertexBytes.data()+n*32+8,&z,4);}
        std::memcpy(&original.world,cases[number][0].data(),64);std::memcpy(&original.view,cases[number][1].data(),64);std::memcpy(&original.projection,cases[number][2].data(),64);
        std::array<Matrix,6> combined;
        for(unsigned mode=0;mode<6;++mode){const auto& m=cases[number];combined[mode]=mode<4?Multiply(Multiply(m[0],m[1],rules[mode]),m[2],rules[mode]):Multiply(m[0],Multiply(m[1],m[2],rules[mode]),rules[mode]);
            predictions<<number<<","<<names[mode+1];for(unsigned col:{2u,3u})for(unsigned row=0;row<4;++row)predictions<<","<<combined[mode][row*4+col];predictions<<"\n";}
        unsigned unique=0;for(unsigned n=0;n<6;++n){bool first=true;for(unsigned k=0;k<n;++k)if(combined[n][14]/combined[n][15]==combined[k][14]/combined[k][15])first=false;if(first)++unique;}CHECK(unique>=3);
        std::vector<std::array<float,4>> originalClip,camera,checkedClip;CHECK(CaptureDepthVertexShader(original,originalClip));
        if(perspective){CHECK(CaptureDepthVertexShader(original,checkedClip,&camera));CHECK(checkedClip.size()==originalClip.size() && std::memcmp(checkedClip.data(),originalClip.data(),originalClip.size()*16)==0);}
        for(unsigned mode=0;mode<(perspective?10u:7u);++mode) {
            auto draw=original;if(mode>0 && mode<7){draw.world=draw.view=Fixture().world;std::memcpy(&draw.projection,combined[mode-1].data(),64);}
            if(mode>=7){draw.world=draw.view=Fixture().world;if(mode>=8)draw.projection=Fixture().projection;
                for(unsigned n=0;n<3;++n){float xyz[3];if(mode==7){CHECK(camera[n][3]==1);std::memcpy(xyz,camera[n].data(),12);}
                    else{CHECK(originalClip[n][3]>0);for(unsigned k=0;k<3;++k)xyz[k]=mode==8?originalClip[n][k]/originalClip[n][3]:float(double(originalClip[n][k])/originalClip[n][3]);xyz[0]-=1.f/64;xyz[1]+=1.f/64;}
                    std::memcpy(draw.vertexBytes.data()+n*32,xyz,12);}}
            std::vector<std::array<float,4>> clip;CHECK(CaptureDepthVertexShader(draw,clip));
            if(mode==7)CHECK(clip.size()==originalClip.size() && std::memcmp(clip.data(),originalClip.data(),clip.size()*16)==0);
            {std::ofstream file(directory/("case"+std::to_string(number)+"-"+names[mode]+"-clip.bin"),std::ios::binary);file.write(reinterpret_cast<const char*>(clip.data()),clip.size()*16);}
            RgbaImage native,replay;CHECK(render({draw},native,replay));
            for(const auto& point:std::array<std::array<unsigned,2>,2>{{{20,42},{36,46}}}) {
                const auto x=point[0],y=point[1];CHECK(color(native,x,y)=='R' && color(replay,x,y)=='R');
                // CPU candidate planes center a conservative search bracket.
                float loDepth=1,hiDepth=0;
                for(const auto& m:combined){std::vector<std::array<float,4>> projected(3);
                    const float xy[][2]={{-.8f,-.8f},{-.8f,.8f},{.8f,-.8f}};
                    for(unsigned n=0;n<3;++n){for(unsigned k=0;k<4;++k)projected[n][k]=float(double(xy[n][0])*m[k]+double(xy[n][1])*m[4+k]+m[12+k]);projected[n][0]+=projected[n][3]/64;projected[n][1]-=projected[n][3]/64;}
                    const float d=float(planeDepth(projected,x,y));CHECK(d>0 && d<1);loDepth=(std::min)(loDepth,d);hiDepth=(std::max)(hiDepth,d);}
                const float observedCenter=float(planeDepth(clip,x,y));CHECK(observedCenter>0 && observedCenter<1);loDepth=(std::min)(loDepth,observedCenter);hiDepth=(std::max)(hiDepth,observedCenter);
                unsigned lo=0,hi=0;std::memcpy(&lo,&loDepth,4);std::memcpy(&hi,&hiDepth,4);CHECK(lo>256 && hi<0x3f7fff00);lo-=256;hi+=256;
                std::map<std::pair<unsigned,unsigned>,std::array<char,2>> cache;
                auto relation=[&](unsigned bits,unsigned comparison,std::array<char,2>& result,bool fresh=false){
                    const auto key=std::make_pair(bits,comparison);const auto found=cache.find(key);
                    if(!fresh && found!=cache.end()){result=found->second;return true;}
                    float d;std::memcpy(&d,&bits,4);RgbaImage a,b;
                    if(!render({draw,reference(d,comparison)},a,b))return false;result={color(a,x,y),color(b,x,y)};
                    if(result[0]=='B' || result[1]=='B')return false;
                    if(found!=cache.end() && result!=found->second)return false;cache[key]=result;return true;};
                std::array<char,2> lower,upper;CHECK(relation(lo,D3DCMP_LESS,lower) && relation(hi,D3DCMP_LESS,upper));CHECK(lower[0]=='G' && lower[1]=='G' && upper[0]=='R' && upper[1]=='R');
                unsigned thresholds[2];char equal[2];
                for(unsigned backend=0;backend<2;++backend){unsigned low=lo,high=hi;
                    while(high-low>1){const unsigned middle=low+(high-low)/2;std::array<char,2> result;CHECK(relation(middle,D3DCMP_LESS,result));if(result[backend]=='G')low=middle;else high=middle;}
                    thresholds[backend]=high;std::array<char,2> result;CHECK(relation(high,D3DCMP_EQUAL,result));equal[backend]=result[backend];CHECK(equal[backend]=='G');
                }
                // Cached search queries only avoid duplicate bisection renders.
                // Boundary repetitions always issue fresh native/DX11 draws.
                for(unsigned repeat=0;repeat<3;++repeat)for(unsigned backend=0;backend<(thresholds[0]==thresholds[1]?1u:2u);++backend){std::array<char,2> result;
                    CHECK(relation(thresholds[backend],D3DCMP_EQUAL,result,true) && result[backend]=='G');
                    CHECK(relation(thresholds[backend]-1,D3DCMP_LESS,result,true) && result[backend]=='G');}
                csv<<number<<","<<(number<6?"calibration":"holdout")<<","<<names[mode]<<","<<x<<","<<y<<","<<thresholds[0]<<","<<thresholds[1]<<","<<equal[0]<<","<<equal[1]<<",1\n";csv.flush();
                ++measurements;if(thresholds[0]!=thresholds[1])++differing;
                std::printf("sensitiveDepth case=%u split=%s mode=%s pixel=%u,%u dx9Bits=%u dx11Bits=%u delta=%lld repeat=EXACT\n",number,number<6?"calibration":"holdout",names[mode],x,y,thresholds[0],thresholds[1],static_cast<long long>(thresholds[0])-thresholds[1]);
            }
        }
    }
    CHECK(bundle.swapchain->Retire());std::printf("sensitiveSummary measured=%u differing=%u nativeVertexCapture=0 rawD24Readback=0\n",measurements,differing);
    return differing?32:0;
}
