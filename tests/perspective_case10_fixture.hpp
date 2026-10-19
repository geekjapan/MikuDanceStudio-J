#pragma once
#include "shared_clip_depth_fixture.hpp"
#include "rhi_d3d11_w_candidate_backend.hpp"

inline int PerspectiveCase10(HWND window,const char* fixturePath,const char* outputPath,bool perturbW=false,bool independentGeometry=false,bool gpuWValidation=false) {
    using namespace depth_diagnostic;using Clip=std::array<float,4>;
    std::ifstream input(fixturePath,std::ios::binary);char magic[8];unsigned count=0;
    CHECK(input.read(magic,8) && std::memcmp(magic,independentGeometry?"WGEOM001":"SDEP0002",8)==0 && input.read(reinterpret_cast<char*>(&count),4) && count==12);
    std::array<std::array<Matrix,3>,12> fixtures{};std::array<Matrix,12> geometryMatrices{};std::array<std::array<Clip,3>,12> geometryObjects{};
    if(independentGeometry){for(unsigned n=0;n<12;++n)CHECK(input.read(reinterpret_cast<char*>(geometryMatrices[n].data()),64) && input.read(reinterpret_cast<char*>(geometryObjects[n].data()),48));}
    else CHECK(input.read(reinterpret_cast<char*>(fixtures.data()),12*48*4));CHECK(input.peek()==std::char_traits<char>::eof());
    const auto& matrices=fixtures[10];auto combined=independentGeometry?geometryMatrices[0]:Multiply(Multiply(matrices[0],matrices[1],Rounding::Sequential),matrices[2],Rounding::Sequential);
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    {std::ofstream file(directory/"combined_matrix.bin",std::ios::binary);file.write(reinterpret_cast<const char*>(combined.data()),64);}
    std::ofstream report(directory/"measurements.csv");report<<"variant,x,y,dx9Bits,dx11Bits,repeatExact\n";
    SharedClipDepthRenderer shared;CHECK(shared.Initialize(window));
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;auto bundle=CreateD3D11Device(desc,D3D11Driver::Hardware);CHECK(bundle);
    D3D11Bundle gpuBundle;if(gpuWValidation){gpuBundle=CreateD3D11WCandidateDevice(desc,D3D11Driver::Hardware,1);CHECK(gpuBundle);}
    std::printf("case10Device adapter=%s singleSample=1 depth=D24S8\n",bundle.adapterName.c_str());
    auto id=[](D3D9ReplaySnapshot c,bool green){Set(c,D3DRS_LIGHTING,TRUE);Set(c,D3DRS_SPECULARENABLE,FALSE);Set(c,D3DRS_AMBIENT,0);c.material={};c.material.Diffuse.a=1;c.material.Emissive=green?D3DCOLORVALUE{0,1,0,0}:D3DCOLORVALUE{1,0,0,0};Stage(c,0,D3DTSS_COLOROP,D3DTOP_DISABLE);return c;};
    auto snapshot=id(Fixture(),false);snapshot.world=snapshot.view=Fixture().world;std::memcpy(&snapshot.projection,combined.data(),64);
    const float xy[][2]={{-.8f,-.8f},{-.8f,.8f},{.8f,-.8f}};std::vector<Clip> object;
    for(unsigned n=0;n<3;++n){const Clip vertex=independentGeometry?geometryObjects[0][n]:Clip{xy[n][0],xy[n][1],0,1};std::memcpy(snapshot.vertexBytes.data()+n*32,vertex.data(),12);object.push_back(vertex);}
    {std::ofstream file(directory/"object.bin",std::ios::binary);file.write(reinterpret_cast<const char*>(object.data()),48);}
    std::vector<Clip> production,instrumented,raw;CHECK(CaptureDepthVertexShader(snapshot,production));CHECK(CaptureDepthVertexShader(snapshot,instrumented,&raw,true));CHECK(std::memcmp(production.data(),instrumented.data(),48)==0);
    const auto save=[&](const std::string& name,const std::vector<Clip>& vertices){std::ofstream file(directory/(name+".clip"),std::ios::binary);file.write(reinterpret_cast<const char*>(vertices.data()),vertices.size()*16);};save("production_output",production);save("raw",raw);
    std::vector<Clip> passthrough;CHECK(shared.Capture(raw,passthrough));CHECK(std::memcmp(production.data(),passthrough.data(),48)==0);
    std::printf("case10ProductionClip passthroughBits=EXACT vertices=3\n");
    auto color=[](const RgbaImage& image,unsigned x,unsigned y){const auto* p=image.pixels.data()+(y*64+x)*4;return p[0]==255 && !p[1] && !p[2]?'R':!p[0] && p[1]==255 && !p[2]?'G':'B';};
    auto ruler=[&](float depth,bool equal){auto c=id(Fixture(),true);const float v[]={-1,-1,depth,0,0,1,0,0,-1,1,depth,0,0,1,0,0,1,-1,depth,0,0,1,0,0,1,1,depth,0,0,1,0,0};c.vertexBytes.resize(sizeof(v));std::memcpy(c.vertexBytes.data(),v,sizeof(v));c.indexBytes={0,0,1,0,2,0,2,0,1,0,3,0};c.vertices=4;c.count=2;Set(c,D3DRS_ZWRITEENABLE,FALSE);Set(c,D3DRS_ZFUNC,equal?D3DCMP_EQUAL:D3DCMP_LESS);return c;};
    auto productionRender=[&](float depth,bool equal,RgbaImage& native,RgbaImage& replay,bool candidate=false){const std::vector<D3D9ReplaySnapshot> draws{snapshot,ruler(depth,equal)};if(!NativeImage(window,draws,2,native))return false;ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});for(const auto& draw:draws)if(!AppendD3D9ReplaySnapshot(stream,draw))return false;stream.complete=true;return candidate?bool(ReplayD3D11WCandidatePrefix(*gpuBundle.device,stream,2,replay)):bool(ReplayD3D11ModelPrefix(*bundle.device,stream,2,replay));};
    unsigned differences=0,measured=0;
    std::vector<std::array<unsigned,2>> coordinates{{36,46},{20,42}};if(independentGeometry)coordinates.push_back({28,44});
    const auto measure=[&](const std::string& name,const std::vector<Clip>& vertices,int path){
        save(name,vertices);std::vector<Clip> observed;if(!shared.Capture(vertices,observed))return false;save(name+"-dx11",observed);
        for(const auto& coordinate:coordinates){const auto x=coordinate[0],y=coordinate[1];std::map<std::pair<unsigned,bool>,std::array<char,2>> cached;
            auto relation=[&](unsigned bits,bool equal,std::array<char,2>& answer,bool fresh=false){const auto key=std::make_pair(bits,equal);const auto found=cached.find(key);if(!fresh && found!=cached.end()){answer=found->second;return true;}float depth;std::memcpy(&depth,&bits,4);RgbaImage a,b;
                const bool ok=(path==0 || path==10)?productionRender(depth,equal,a,b,path==10):shared.Render(vertices,depth,equal,a,b,path>=2?&object:nullptr,path>=2?&combined:nullptr,path>=2?unsigned(path-2):0);
                if(!ok)return false;answer={color(a,x,y),color(b,x,y)};if(answer[0]=='B' || answer[1]=='B' || (found!=cached.end() && found->second!=answer))return false;cached[key]=answer;return true;};
            float lower=independentGeometry?.5f:.74f,upper=independentGeometry?.95f:.78f;unsigned lo,hi;std::memcpy(&lo,&lower,4);std::memcpy(&hi,&upper,4);std::array<char,2> a,b;
            if(!relation(lo,false,a) || !relation(hi,false,b) || a!=std::array<char,2>{'G','G'} || b!=std::array<char,2>{'R','R'})return false;
            unsigned threshold[2];for(unsigned backend=0;backend<2;++backend){unsigned low=lo,high=hi;while(high-low>1){const auto middle=low+(high-low)/2;if(!relation(middle,false,a))return false;if(a[backend]=='G')low=middle;else high=middle;}threshold[backend]=high;if(!relation(high,true,a) || a[backend]!='G')return false;}
            for(unsigned repeat=0;repeat<3;++repeat)for(unsigned backend=0;backend<(threshold[0]==threshold[1]?1u:2u);++backend)if(!relation(threshold[backend],true,a,true) || a[backend]!='G' || !relation(threshold[backend]-1,false,a,true) || a[backend]!='G')return false;
            report<<name<<","<<x<<","<<y<<","<<threshold[0]<<","<<threshold[1]<<",1\n";report.flush();std::printf("case10 variant=%s pixel=%u,%u dx9=%u dx11=%u delta=%lld repeat=EXACT\n",name.c_str(),x,y,threshold[0],threshold[1],static_cast<long long>(threshold[0])-threshold[1]);++measured;if(threshold[0]!=threshold[1])++differences;
        }return true;};
    if(independentGeometry) {
        const Rounding rules[]={Rounding::Sequential,Rounding::Double,Rounding::Paired,Rounding::Fused};const char* ruleNames[]={"sequential","double","paired","fused"};
        for(unsigned number=0;number<12;++number){combined=geometryMatrices[number];object.assign(geometryObjects[number].begin(),geometryObjects[number].end());
            const std::string prefix="g"+std::to_string(number);
            {std::ofstream m(directory/(prefix+".matrix"),std::ios::binary);m.write(reinterpret_cast<const char*>(combined.data()),64);std::ofstream o(directory/(prefix+".object"),std::ios::binary);o.write(reinterpret_cast<const char*>(object.data()),48);}
            for(unsigned n=0;n<3;++n){CHECK(object[n][3]==1);for(unsigned k=0;k<3;++k)CHECK(object[n][k]!=0 && combined[k*4+3]!=0);std::memcpy(snapshot.vertexBytes.data()+n*32,object[n].data(),12);}
            std::memcpy(&snapshot.projection,combined.data(),64);CHECK(CaptureDepthVertexShader(snapshot,production));CHECK(CaptureDepthVertexShader(snapshot,instrumented,&raw,true));CHECK(std::memcmp(production.data(),instrumented.data(),48)==0);
            CHECK(shared.Capture(raw,passthrough) && std::memcmp(production.data(),passthrough.data(),48)==0);for(const auto& v:raw)CHECK(v[2]==3 && v[3]>0);save(prefix+"_production_output",production);
            if(gpuWValidation){std::vector<Clip> gpuFinal,gpuRaw;CHECK(CaptureDepthVertexShader(snapshot,gpuFinal,&gpuRaw,true,1));
                const float wColumn[]={combined[3],combined[7],combined[11],combined[15]};
                for(unsigned n=0;n<3;++n){const float expected=Dot(object[n].data(),wColumn,Rounding::Fused);CHECK(std::memcmp(&expected,&gpuRaw[n][3],4)==0);for(unsigned k=0;k<3;++k)CHECK(std::memcmp(&raw[n][k],&gpuRaw[n][k],4)==0);}
                save(prefix+"_gpu_final",gpuFinal);CHECK(shared.Capture(gpuRaw,passthrough) && std::memcmp(gpuFinal.data(),passthrough.data(),48)==0);
                std::printf("gpuWVerification geometry=%u vertices=3 cpuFmaBits=EXACT heldXYZBits=EXACT\n",number);CHECK(measure(prefix+"_gpu_shader",gpuRaw,10));}
            CHECK(measure(prefix+"_production",raw,0));CHECK(measure(prefix+"_shared_clip",raw,1));CHECK(measure(prefix+"_native_dot",raw,2));CHECK(measure(prefix+"_native_ordered",raw,3));CHECK(measure(prefix+"_native_dot_w",raw,7));
            const float column[]={combined[3],combined[7],combined[11],combined[15]};
            for(unsigned rule=0;rule<4;++rule){auto candidate=raw;for(unsigned n=0;n<3;++n)candidate[n][3]=Dot(object[n].data(),column,rules[rule]);CHECK(measure(prefix+"_cpu_"+ruleNames[rule],candidate,1));}
        }
        CHECK(bundle.swapchain->Retire());if(gpuWValidation)CHECK(gpuBundle.swapchain->Retire());std::printf("wGeometrySummary cases=12 measured=%u differences=%u nativeVertexCapture=0\n",measured,differences);return differences?32:0;
    }
    if(perturbW) {
        const auto baseMatrix=combined;const auto baseRaw=raw;
        std::ofstream cases(directory/"perturbations.csv");cases<<"case,coefficient,offset,split,baseBits,newBits\n";
        unsigned number=0;
        // Preassigned +/-1 ULP calibration and +/-2,+/-4 ULP holdouts. Each
        // coefficient is changed independently; no residual-driven selection.
        for(unsigned coefficient:{3u,7u,15u})for(int offset:{0,-1,1,-2,2,-4,4}) {
            if(offset==0 && coefficient!=3)continue;
            combined=baseMatrix;for(int step=0;step<std::abs(offset);++step)combined[coefficient]=std::nextafter(combined[coefficient],offset>0?std::numeric_limits<float>::infinity():-std::numeric_limits<float>::infinity());
            unsigned oldBits,newBits;std::memcpy(&oldBits,&baseMatrix[coefficient],4);std::memcpy(&newBits,&combined[coefficient],4);
            const std::string prefix="p"+std::to_string(number);cases<<number<<","<<coefficient<<","<<offset<<","<<(std::abs(offset)<=1?"calibration":"holdout")<<","<<oldBits<<","<<newBits<<"\n";cases.flush();
            {std::ofstream file(directory/(prefix+".matrix"),std::ios::binary);file.write(reinterpret_cast<const char*>(combined.data()),64);}
            std::memcpy(&snapshot.projection,combined.data(),64);
            CHECK(CaptureDepthVertexShader(snapshot,production));CHECK(CaptureDepthVertexShader(snapshot,instrumented,&raw,true));CHECK(std::memcmp(production.data(),instrumented.data(),48)==0);
            CHECK(shared.Capture(raw,passthrough) && std::memcmp(production.data(),passthrough.data(),48)==0);
            for(unsigned n=0;n<3;++n)for(unsigned k=0;k<3;++k)CHECK(raw[n][k]==baseRaw[n][k]); // Hold X/Y/Z fixed before center correction.
            save(prefix+"_production_output",production);
            CHECK(measure(prefix+"_production",raw,0));CHECK(measure(prefix+"_shared_clip",raw,1));CHECK(measure(prefix+"_native_dot",raw,2));CHECK(measure(prefix+"_native_ordered",raw,3));CHECK(measure(prefix+"_native_dot_w",raw,7));
            const float column[]={combined[3],combined[7],combined[11],combined[15]};
            const Rounding rules[]={Rounding::Sequential,Rounding::Double,Rounding::Paired,Rounding::Fused};const char* ruleNames[]={"sequential","double","paired","fused"};
            for(unsigned rule=0;rule<4;++rule){auto candidate=raw;for(unsigned n=0;n<3;++n)candidate[n][3]=Dot(object[n].data(),column,rules[rule]);CHECK(measure(prefix+"_cpu_"+ruleNames[rule],candidate,1));}
            ++number;
        }
        CHECK(number==19);CHECK(bundle.swapchain->Retire());std::printf("wPerturbSummary cases=%u measured=%u differences=%u nativeVertexCapture=0\n",number,measured,differences);return differences?32:0;
    }
    CHECK(measure("production",raw,0));CHECK(measure("shared_clip",raw,1));CHECK(measure("native_dot",raw,2));CHECK(measure("native_ordered",raw,3));
    CHECK(measure("native_reverse",raw,4));CHECK(measure("native_paired",raw,5));
    CHECK(measure("native_dot_z",raw,6));CHECK(measure("native_dot_w",raw,7));CHECK(measure("native_dot_zw",raw,8));CHECK(measure("native_dot_xy",raw,9));
    for(unsigned cycle=1;cycle<3;++cycle){auto vertices=raw;std::rotate(vertices.begin(),vertices.begin()+cycle,vertices.end());CHECK(measure("cycle"+std::to_string(cycle),vertices,1));}
    auto reverse=raw;std::swap(reverse[0],reverse[1]);CHECK(measure("reverse",reverse,1));
    for(unsigned scale:{2u,8u}){auto vertices=raw;for(auto& vertex:vertices)for(auto& value:vertex)value*=scale;CHECK(measure("homogeneous"+std::to_string(scale),vertices,1));}
    auto ndc=raw;for(auto& vertex:ndc){for(unsigned k=0;k<3;++k)vertex[k]/=vertex[3];vertex[3]=1;}CHECK(measure("ndc",ndc,1));
    // Restrict one edge at a time while retaining the homogeneous plane.
    // Float32 rounding of the new endpoint is saved for independent analysis.
    for(unsigned edge=1;edge<3;++edge){auto vertices=raw;for(unsigned k=0;k<4;++k)vertices[edge][k]=float(double(raw[0][k])*.125+double(raw[edge][k])*.875);CHECK(measure("short_edge"+std::to_string(edge),vertices,1));}
    CHECK(bundle.swapchain->Retire());std::printf("case10Summary measured=%u differences=%u nativeVertexCapture=0\n",measured,differences);return differences?32:0;
}
