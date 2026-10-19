#pragma once
#include "shared_clip_depth_fixture.hpp"
#include "rhi_d3d11_w_candidate_backend.hpp"
#include <set>

inline int ZExplicitShaderSmoke() {
    // Fixed first independent fixture: fused/double and separate float Z are
    // distinct at vertex 2. This checks GPU behavior, not just CPU helpers.
    const depth_diagnostic::Matrix matrix{6,0,-.40171122550964355f,0,0,6,-.366606742143631f,0,
        0,0,-.621910810470581f,0,0,0,4.053401470184326f,6};
    const std::array<std::array<float,4>,3> objects{{{-.8624122738838196f,-.8624122738838196f,.2893954813480377f,1},
        {-.8624122738838196f,.8624122738838196f,.4297514259815216f,1},{.8624122738838196f,-.8624122738838196f,.42755499482154846f,1}}};
    auto source=Fixture();std::memcpy(&source.projection,matrix.data(),64);for(unsigned n=0;n<3;++n)std::memcpy(source.vertexBytes.data()+n*32,objects[n].data(),12);
    const float z[]={matrix[2],matrix[6],matrix[10],matrix[14]};CHECK(depth_diagnostic::Dot(objects[2].data(),z,depth_diagnostic::Rounding::Fused)!=depth_diagnostic::Dot(objects[2].data(),z,depth_diagnostic::Rounding::Sequential));
    std::vector<std::array<float,4>> base,baseRaw;CHECK(CaptureDepthVertexShader(source,base,&baseRaw,true,2));
    for(unsigned p=3;p<=5;++p)for(unsigned repeat=0;repeat<3;++repeat){std::vector<std::array<float,4>> result,raw;CHECK(CaptureDepthVertexShader(source,result,&raw,true,p));CHECK(raw.size()==3);
        for(unsigned n=0;n<3;++n){const float expected=depth_diagnostic::Dot(objects[n].data(),z,w_shader_diagnostic::ZRounding(p));CHECK(std::memcmp(&expected,&raw[n][2],4)==0);for(unsigned k:{0u,1u,3u})CHECK(std::memcmp(&baseRaw[n][k],&raw[n][k],4)==0);}}
    std::printf("explicitZShaderSmoke policies=3 vertices=3 repeats=3 cpuZBits=EXACT heldXYW=EXACT\n");return 0;
}

// Fixed arithmetic candidates. No candidate is selected by native agreement.
inline int ZExplicitDepth(HWND window,const char* inputPath,const char* outputPath,const char* referencePath=nullptr) {
    using Clip=std::array<float,4>;using namespace depth_diagnostic;
    const bool real=referencePath!=nullptr;const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    std::vector<D3D9ReplaySnapshot> sources;unsigned width=64,height=64;
    struct Probe {unsigned triangle,x,y,holdout;};std::vector<Probe> points;
    if(real){D3D9ReplaySnapshot c;CHECK(ReadUntexturedReduction(std::filesystem::path(inputPath)/"history_replay.reduction.draw2.state",c));CHECK(c.fvf==274 && c.stride==32 && c.offset==0 && c.base==0 && c.start==6 && c.count==232);
        unsigned x=0,y=0,w=0,h=0;std::ifstream log(std::filesystem::path(referencePath)/"history_replay.dx9");std::string line;
        while(std::getline(log,line))if(std::sscanf(line.c_str(),"PORTABLE_REGION x=%u y=%u width=%u height=%u",&x,&y,&w,&h)==4)break;
        CHECK(w && h && x+w<=4096 && y+h<=4096);c.viewport={x,y,w,h,0,1};width=x+w;height=y+h;sources.push_back(c);
        if(w==1032 && h==774 && x==565 && y==25){for(unsigned t:{135u,227u})for(auto p:std::vector<std::array<unsigned,3>>{{1220,505,0},{1218,505,1},{1222,505,1}})points.push_back({t,p[0],p[1],p[2]});}
        else if(w==670 && h==503 && x==274 && y==25){for(unsigned t:{197u,231u})for(auto p:std::vector<std::array<unsigned,3>>{{427,338,0},{425,338,1},{429,338,1}})points.push_back({t,p[0],p[1],p[2]});
            for(unsigned t:{185u,231u})for(auto p:std::vector<std::array<unsigned,3>>{{381,340,0},{383,339,1},{381,339,1}})points.push_back({t,p[0],p[1],p[2]});
            for(auto p:std::vector<std::array<unsigned,3>>{{430,234,0},{428,234,1},{429,234,1}})points.push_back({197,p[0],p[1],p[2]});}
        else CHECK(false);
    } else {std::ifstream file(inputPath,std::ios::binary);char magic[8];unsigned count=0;CHECK(file.read(magic,8) && std::memcmp(magic,"ZGEOM001",8)==0 && file.read(reinterpret_cast<char*>(&count),4) && count==12);
        for(unsigned n=0;n<count;++n){Matrix m;std::array<Clip,3> objects;CHECK(file.read(reinterpret_cast<char*>(m.data()),64) && file.read(reinterpret_cast<char*>(objects.data()),48));auto c=Fixture();c.world=c.view=Fixture().world;std::memcpy(&c.projection,m.data(),64);
            for(unsigned k=0;k<3;++k){CHECK(objects[k][3]==1);std::memcpy(c.vertexBytes.data()+k*32,objects[k].data(),12);}sources.push_back(c);}
        CHECK(file.peek()==std::char_traits<char>::eof());points={{0,36,46,0},{0,20,42,1},{0,28,44,1}};
    }
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    std::array<D3D11Bundle,4> bundles;for(unsigned p=2;p<=5;++p){bundles[p-2]=CreateD3D11WCandidateDevice(desc,D3D11Driver::Hardware,p);CHECK(bundles[p-2]);}
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window,width,height,&sources[0].viewport));
    std::printf("explicitZDevice adapter=%s realPMM=%u viewport=%u,%u,%u,%u\n",bundles[0].adapterName.c_str(),unsigned(real),sources[0].viewport.X,sources[0].viewport.Y,sources[0].viewport.Width,sources[0].viewport.Height);
    auto change=[](D3D9ReplaySnapshot& c,unsigned key,DWORD value){for(auto& v:c.renderStates)if(v.key==key){v.value=value;return;}c.renderStates.push_back({0,key,value});};
    auto id=[&](D3D9ReplaySnapshot c,bool green){for(auto kv:{std::pair<unsigned,DWORD>{D3DRS_LIGHTING,TRUE},{D3DRS_SPECULARENABLE,FALSE},{D3DRS_AMBIENT,0},{D3DRS_ALPHABLENDENABLE,FALSE},{D3DRS_ALPHATESTENABLE,FALSE},
        {D3DRS_STENCILENABLE,FALSE},{D3DRS_CULLMODE,D3DCULL_NONE},{D3DRS_ZENABLE,TRUE},{D3DRS_ZWRITEENABLE,TRUE},{D3DRS_ZFUNC,D3DCMP_LESSEQUAL}})change(c,kv.first,kv.second);
        c.material={};c.material.Diffuse.a=1;c.material.Emissive=green?D3DCOLORVALUE{0,1,0,0}:D3DCOLORVALUE{1,0,0,0};c.lights.clear();Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);c.textureInfo={};c.textureBytes={};c.preparedMips={};return c;};
    auto replay=[&](const std::vector<D3D9ReplaySnapshot>& draws,unsigned policy,RgbaImage& image){ModelReplayStream stream;stream.target.width=width;stream.target.height=height;stream.events.push_back({1,ModelReplayOp::Clear});
        for(const auto& c:draws)if(!AppendD3D9ReplaySnapshot(stream,c))return false;stream.complete=true;return bool(ReplayD3D11WCandidatePrefix(*bundles[policy-2].device,stream,draws.size(),image));};
    auto classify=[&](const RgbaImage& image,unsigned x,unsigned y){const auto* p=image.pixels.data()+(std::size_t(y)*width+x)*4;return p[0]==255 && !p[1] && !p[2]?'R':!p[0] && p[1]==255 && !p[2]?'G':'B';};
    auto save=[&](const std::string& name,const void* data,std::size_t bytes){std::ofstream f(directory/name,std::ios::binary);f.write(static_cast<const char*>(data),bytes);};
    std::ofstream report(directory/"thresholds.csv");report<<"case,triangle,x,y,holdout,path,dx9Bits,dx11Bits,repeatExact,dx9EqualLast,dx11EqualLast\n";
    std::ofstream verification(directory/"verification.csv");verification<<"case,policy,vertices,zCpuExact,zCpuDifferent,heldXYWExact,zChanged\n";
    unsigned measured=0,different=0,bitMismatches=0;
    for(unsigned number=0;number<sources.size();++number){const auto& source=sources[number];const auto c=id(source,false);Matrix world,view,projection;std::memcpy(world.data(),&source.world,64);std::memcpy(view.data(),&source.view,64);std::memcpy(projection.data(),&source.projection,64);
        const Matrix combined=w_shader_diagnostic::Inputs(world,view,projection,2).combined;const float zColumn[]={combined[2],combined[6],combined[10],combined[14]};
        save("c"+std::to_string(number)+".combined",combined.data(),64);save("c"+std::to_string(number)+".vertices",source.vertexBytes.data(),source.vertexBytes.size());save("c"+std::to_string(number)+".indices",source.indexBytes.data(),source.indexBytes.size());
        {std::ofstream m(directory/("c"+std::to_string(number)+".matrices"),std::ios::binary);for(auto* matrix:{&source.world,&source.view,&source.projection})m.write(reinterpret_cast<const char*>(matrix),64);}
        std::array<std::vector<Clip>,4> raw,final;
        for(unsigned policy=2;policy<=5;++policy){CHECK(CaptureDepthVertexShader(source,final[policy-2],&raw[policy-2],true,policy));save("c"+std::to_string(number)+"_p"+std::to_string(policy)+".raw",raw[policy-2].data(),raw[policy-2].size()*16);
            save("c"+std::to_string(number)+"_p"+std::to_string(policy)+".final",final[policy-2].data(),final[policy-2].size()*16);
            if(policy>2){unsigned exact=0,changed=0;for(unsigned n=0;n<raw[0].size();++n){Clip object{0,0,0,1};std::memcpy(object.data(),source.vertexBytes.data()+n*32,12);const float expected=Dot(object.data(),zColumn,w_shader_diagnostic::ZRounding(policy));
                exact+=std::memcmp(&expected,&raw[policy-2][n][2],4)==0;changed+=std::memcmp(&raw[0][n][2],&raw[policy-2][n][2],4)!=0;
                for(unsigned k:{0u,1u,3u})CHECK(std::memcmp(&raw[0][n][k],&raw[policy-2][n][k],4)==0);}
                verification<<number<<","<<policy<<","<<raw[0].size()<<","<<exact<<","<<raw[0].size()-exact<<","<<raw[0].size()<<","<<changed<<"\n";verification.flush();
                std::printf("explicitZBits case=%u policy=%u vertices=%u cpuExact=%u cpuDifferent=%u heldXYW=EXACT changedZ=%u\n",number,policy,unsigned(raw[0].size()),exact,unsigned(raw[0].size())-exact,changed);
                bitMismatches+=static_cast<unsigned>(raw[0].size())-exact;
                // A measured disagreement is evidence about actual driver arithmetic,
                // not a license to label shader output as the CPU candidate.
            }
        }
        auto index=[&](unsigned triangle,unsigned n){unsigned i=0;const unsigned step=source.indexFormat==D3DFMT_INDEX16?2:4;std::memcpy(&i,source.indexBytes.data()+(source.start+triangle*3+n)*step,step);return i;};
        auto ruler=[&](float z,bool equal){auto c=id(Fixture(),true);c.viewport=source.viewport;const float full[]={-1,-1,z,0,0,1,0,0,-1,1,z,0,0,1,0,0,1,-1,z,0,0,1,0,0,1,1,z,0,0,1,0,0};c.vertexBytes.resize(sizeof(full));std::memcpy(c.vertexBytes.data(),full,sizeof(full));
            c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};c.vertices=4;c.count=2;change(c,D3DRS_ZWRITEENABLE,FALSE);change(c,D3DRS_ZFUNC,equal?D3DCMP_EQUAL:D3DCMP_LESS);return c;};
        for(const auto& point:points){auto t=c;t.start+=point.triangle*3;t.count=1;std::vector<Clip> objects,clip2,clip3;for(unsigned n=0;n<3;++n){const unsigned v=index(point.triangle,n);Clip object{0,0,0,1};std::memcpy(object.data(),source.vertexBytes.data()+v*32,12);objects.push_back(object);clip2.push_back(raw[0][v]);clip3.push_back(raw[1][v]);}
            std::vector<Clip> sharedFinal;CHECK(shared.Capture(clip3,sharedFinal));for(unsigned n=0;n<3;++n)CHECK(std::memcmp(sharedFinal[n].data(),final[1][index(point.triangle,n)].data(),16)==0);
            std::map<std::pair<unsigned,bool>,std::array<char,8>> cached;
            auto relation=[&](unsigned bits,bool equal,std::array<char,8>& answer,bool fresh=false){const auto key=std::make_pair(bits,equal);const auto found=cached.find(key);if(!fresh && found!=cached.end()){answer=found->second;return true;}
                float depth;std::memcpy(&depth,&bits,4);const std::vector<D3D9ReplaySnapshot> draws{t,ruler(depth,equal)};RgbaImage a,b;if(!NativeImage(window,draws,2,a,nullptr,width,height))return false;answer[0]=classify(a,point.x,point.y);
                for(unsigned p=2;p<=5;++p){if(!replay(draws,p,b))return false;answer[p-1]=classify(b,point.x,point.y);}
                if(!shared.Render(clip3,depth,equal,a,b))return false;answer[5]=classify(a,point.x,point.y);answer[6]=classify(b,point.x,point.y);
                if(!shared.Render(clip2,depth,equal,a,b,&objects,&combined,4))return false;answer[7]=classify(a,point.x,point.y);if(classify(b,point.x,point.y)!=answer[1])return false;
                for(char value:answer)if(value=='B')return false;if(found!=cached.end() && answer!=found->second)return false;cached[key]=answer;return true;};
            float lower=real?.98f:.2f,upper=real?.999f:.98f;unsigned lo,hi;std::memcpy(&lo,&lower,4);std::memcpy(&hi,&upper,4);
            std::array<char,8> answer;CHECK(relation(lo,false,answer));for(char value:answer)CHECK(value=='G');CHECK(relation(hi,false,answer));for(char value:answer)CHECK(value=='R');std::array<unsigned,8> thresholds,equalLast;
            for(unsigned backend=0;backend<8;++backend){unsigned low=lo,high=hi;while(high-low>1){const unsigned middle=low+(high-low)/2;CHECK(relation(middle,false,answer));if(answer[backend]=='G')low=middle;else high=middle;}thresholds[backend]=high;
                CHECK(relation(high,true,answer));CHECK(answer[backend]=='G');CHECK(relation(high-1,true,answer));CHECK(answer[backend]=='R');
                // Below 0.5, float32 spacing is finer than D24: multiple
                // reference floats can legitimately map to one equality code.
                unsigned last=high;for(unsigned step=1;step<=8;++step){CHECK(relation(high+step,true,answer));if(answer[backend]=='R')break;last=high+step;}CHECK(last<high+8);equalLast[backend]=last;}
            for(unsigned repeat=0;repeat<3;++repeat)for(unsigned bits:std::set<unsigned>(thresholds.begin(),thresholds.end())){CHECK(relation(bits,true,answer,true));for(unsigned b=0;b<8;++b)if(thresholds[b]==bits)CHECK(answer[b]=='G');CHECK(relation(bits-1,false,answer,true));for(unsigned b=0;b<8;++b)if(thresholds[b]==bits)CHECK(answer[b]=='G');}
            for(unsigned repeat=0;repeat<3;++repeat)for(unsigned bits:std::set<unsigned>(equalLast.begin(),equalLast.end())){CHECK(relation(bits,true,answer,true));for(unsigned b=0;b<8;++b)if(equalLast[b]==bits)CHECK(answer[b]=='G');CHECK(relation(bits+1,true,answer,true));for(unsigned b=0;b<8;++b)if(equalLast[b]==bits)CHECK(answer[b]=='R');}
            for(unsigned p=2;p<=5;++p){report<<number<<","<<point.triangle<<","<<point.x<<","<<point.y<<","<<point.holdout<<",p"<<p<<","<<thresholds[0]<<","<<thresholds[p-1]<<",1,"<<equalLast[0]<<","<<equalLast[p-1]<<"\n";++measured;different+=(thresholds[0]!=thresholds[p-1] || equalLast[0]!=equalLast[p-1]);}
            report<<number<<","<<point.triangle<<","<<point.x<<","<<point.y<<","<<point.holdout<<",shared3,"<<thresholds[5]<<","<<thresholds[6]<<",1,"<<equalLast[5]<<","<<equalLast[6]<<"\n";report<<number<<","<<point.triangle<<","<<point.x<<","<<point.y<<","<<point.holdout<<",native_dot_z,"<<thresholds[7]<<","<<thresholds[1]<<",1,"<<equalLast[7]<<","<<equalLast[1]<<"\n";measured+=2;different+=(thresholds[5]!=thresholds[6] || equalLast[5]!=equalLast[6])+(thresholds[7]!=thresholds[1] || equalLast[7]!=equalLast[1]);report.flush();
            std::printf("explicitZThreshold case=%u triangle=%u pixel=%u,%u native=%u p2=%u fusedZ=%u doubleZ=%u separateZ=%u sharedFused=%u,%u nativeDotZ=%u repeat=EXACT\n",number,point.triangle,point.x,point.y,thresholds[0],thresholds[1],thresholds[2],thresholds[3],thresholds[4],thresholds[5],thresholds[6],thresholds[7]);
        }
    }
    for(auto& bundle:bundles)CHECK(bundle.swapchain->Retire());std::printf("explicitZSummary thresholdPairs=%u differences=%u cpuBitMismatches=%u nativeVertexCapture=0\n",measured,different,bitMismatches);return different || bitMismatches?32:0;
}
