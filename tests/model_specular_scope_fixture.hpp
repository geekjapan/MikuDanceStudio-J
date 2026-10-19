#pragma once
// Predetermined synthetic inputs, no scene archive and no fitted coefficients.
// Native flat observations are accepted only after reproducing Gouraud output.
namespace model_specular_scope {
using model_batch_color::Color;
using model_specular_stages::Vector;
using ground_history_isolation::State;
using Matrix=depth_diagnostic::Matrix;
struct Transform {const char* name;Matrix world,view;bool holdout;};
inline std::vector<Transform> Transforms() {
    using normal_transform_diagnostic::Affine;
    const auto identity=Affine({1,0,0,0,1,0,0,0,1});
    return {
        {"identity",identity,identity,false},
        {"rotated_world",Affine({.8f,0,-.6f,0,1,0,.6f,0,.8f},{.173f,-.291f,3.731f}),
            Affine({1,0,0,0,1,0,0,0,1},{-.419f,.237f,.613f}),false},
        {"nonuniform_world",Affine({1.7f,0,0,0,2.3f,0,0,0,1.3f},{-.317f,.193f,2.813f}),
            Affine({.8f,0,-.6f,0,1,0,.6f,0,.8f},{.271f,-.137f,1.193f}),false},
        {"sheared_world_rotated_view",Affine({1.31f,.17f,-.11f,-.09f,1.73f,.23f,.19f,-.13f,1.57f},{.413f,-.227f,2.917f}),
            Affine({1,0,0,0,.9230769230769231f,.3846153846153846f,0,-.3846153846153846f,.9230769230769231f},{-.319f,.157f,.731f}),true},
        {"mixed_holdout",Affine({.97f,-.13f,.17f,.21f,1.43f,-.19f,-.11f,.07f,1.19f},{-.173f,.431f,3.113f}),
            Affine({.96f,.28f,0,-.28f,.96f,0,0,0,1},{.293f,-.179f,.617f}),true}};
}
inline bool FixtureFor(const Transform& transform,unsigned normalSet,unsigned normalize,unsigned localViewer,float power,D3D9ReplaySnapshot& draw) {
    draw=model_specular_stages::FixtureFor({0,0,-1},power);
    // The observation PS reads COLOR1 directly. Disable the unused cascade
    // so this generated input also passes the production replay validator.
    Stage(draw,0,D3DTSS_COLOROP,D3DTOP_DISABLE);
    State(draw,D3DRS_NORMALIZENORMALS,normalize);State(draw,D3DRS_LOCALVIEWER,localViewer);
    std::memcpy(&draw.world,transform.world.data(),64);std::memcpy(&draw.view,transform.view.data(),64);
    draw.projection={};draw.projection._11=draw.projection._22=.8f;draw.projection._43=.5f;draw.projection._44=1;
    const Vector normals[][3]={{{.13f,.37f,-.91f},{-.83f,.11f,-.47f},{.27f,-.19f,-.73f}},
        {{-.43f,.27f,-.81f},{.17f,-.31f,-.93f},{-.71f,.09f,-.53f}}};
    const Color camera[]={{{-.713f,-.593f,3.17f,1}},{{-.537f,.787f,4.31f,1}},{{.817f,-.487f,3.73f,1}}};
    Matrix inverse;
    // Mathematical geometry construction only, not an observed/fitted shader
    // result. Independent CPU rounding keeps the GPU transform under test.
    if(!normal_transform_diagnostic::Inverse(depth_diagnostic::Multiply(transform.world,transform.view,depth_diagnostic::Rounding::Double),inverse))return false;
    for(unsigned v=0;v<3;++v){Vector object{};
        for(unsigned c=0;c<3;++c){double value=0;for(unsigned k=0;k<4;++k)value+=double(camera[v][k])*inverse[k*4+c];object[c]=float(value);}
        std::memcpy(draw.vertexBytes.data()+v*32,object.data(),12);std::memcpy(draw.vertexBytes.data()+v*32+12,normals[normalSet][v].data(),12);
    }
    draw.lights[0].value.Direction={.27f,-.43f,.61f};return true;
}
inline unsigned Changed(const std::vector<Color>& a,const std::vector<Color>& b) {
    if(a.size()!=b.size())return ~0u;unsigned count=0;for(unsigned p=0;p<a.size();++p)count+=a[p]!=b[p];return count;
}
inline std::uint64_t Hash(const std::vector<Color>& values) {
    std::uint64_t hash=14695981039346656037ull;const auto* bytes=reinterpret_cast<const unsigned char*>(values.data());
    for(std::size_t n=0;n<values.size()*sizeof(Color);++n)hash=(hash^bytes[n])*1099511628211ull;return hash;
}
inline int Run(HWND window,const char* destination) {
    const std::filesystem::path directory(destination);std::filesystem::create_directories(directory);
    std::ofstream inputLog(directory/"inputs.csv"),vertices(directory/"vertices.csv"),report(directory/"scope.csv");
    inputLog<<"transform,name,holdout,kind,index,value,bits\n"<<std::setprecision(17);
    vertices<<"transform,normalSet,normalize,localViewer,powerIndex,power,holdout,repeat,vertex,channel,native,baseline,candidate,nativeBits,baselineBits,candidateBits\n"<<std::setprecision(17);
    report<<"transform,normalSet,normalize,localViewer,powerIndex,holdout,repeat,coveredPixels,activeVertexChannels,baselineChannels,candidateChannels,regressedChannels,nativeReproductionPixels,candidateReproductionPixels,baselinePixels,candidatePixels,regressedPixels,nativeHash,baselineHash,candidateHash\n";
    ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=pp.BackBufferHeight=64;
    pp.BackBufferCount=1;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
    ComPtr<IDirect3DDevice9> native;const auto hr=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&native);
    if(FAILED(hr))std::fprintf(stderr,"specularScope DX9 creation=%08lx\n",static_cast<unsigned long>(hr));CHECK(SUCCEEDED(hr));
    D3DADAPTER_IDENTIFIER9 adapter{};CHECK(SUCCEEDED(api->GetAdapterIdentifier(0,0,&adapter)));
    model_specular_origin::Interpolation interpolation;CHECK(interpolation.Initialize(window,64,64,{0,0,64,64,0,1},{0,0,64,64}));
    const auto baseline=model_specular_origin::Source(),candidate=std::string("#define MDS_MODEL_SPECULAR_FMA_DIAGNOSTIC 1\n")+model_specular_origin::Source();
    for(unsigned policy=0;policy<2;++policy){const auto& text=policy?candidate:baseline;ComPtr<ID3DBlob> code,listing,error;
        CHECK(SUCCEEDED(D3DCompile(text.data(),text.size(),nullptr,nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error)));
        CHECK(SUCCEEDED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)));
        std::ofstream hlsl(directory/(policy?"candidate.hlsl":"baseline.hlsl")),assembly(directory/(policy?"candidate.asm":"baseline.asm"));hlsl<<text;
        assembly.write(static_cast<const char*>(listing->GetBufferPointer()),listing->GetBufferSize());CHECK(hlsl && assembly);}
    const auto transforms=Transforms();const float powers[]={.5f,1.7f,5.f,7.3f};
    unsigned observations=0,controls=0,baselineFailures=0,candidateFailures=0,regressions=0,gateFailures=0,unchangedFailures=0;
    for(unsigned t=0;t<transforms.size();++t){const auto& transform=transforms[t];
        for(unsigned kind=0;kind<2;++kind){const auto& matrix=kind?transform.view:transform.world;
            for(unsigned k=0;k<16;++k)inputLog<<t<<","<<transform.name<<","<<transform.holdout<<","<<(kind?"view":"world")<<","<<k<<","<<matrix[k]<<","<<ground_endpoint_depth::Bits(matrix[k])<<"\n";}
        for(unsigned set=0;set<2;++set)for(unsigned normalize=0;normalize<2;++normalize)for(unsigned viewer=0;viewer<2;++viewer)for(unsigned power=0;power<4;++power){
            D3D9ReplaySnapshot draw;CHECK(FixtureFor(transform,set,normalize,viewer,powers[power],draw));const bool holdout=transform.holdout || set==1;
            if(!normalize && !viewer && !power)for(unsigned v=0;v<3;++v)for(unsigned k=0;k<8;++k){float value;std::memcpy(&value,draw.vertexBytes.data()+v*32+k*4,4);
                inputLog<<t<<","<<transform.name<<","<<holdout<<",vertices"<<set<<","<<(v*8+k)<<","<<value<<","<<ground_endpoint_depth::Bits(value)<<"\n";}
            std::vector<Color> previousNative,previousBaseline,previousCandidate;
            std::vector<Vector> previousFlat,previousBaselineVertices,previousCandidateVertices;
            for(unsigned repeat=0;repeat<3;++repeat){std::vector<Color> clipB,clipC;std::vector<Vector> b,c,n(3);
                CHECK(CaptureDepthVertexShader(draw,clipB,nullptr,false,0,nullptr,&baseline,nullptr,false,nullptr,0,false,false,true,&b));
                CHECK(CaptureDepthVertexShader(draw,clipC,nullptr,false,0,nullptr,&candidate,nullptr,false,nullptr,0,false,false,true,&c));
                CHECK(clipB==clipC && clipB.size()==3 && b.size()==3 && c.size()==3);
                unsigned active=0,bd=0,cd=0,regressed=0;
                for(unsigned v=0;v<3;++v){Color flat{};unsigned covered;bool constant;
                    CHECK(model_specular_origin::NativeFlat(window,draw,v,64,64,native.Get(),flat,covered,constant));CHECK(constant && covered>128);
                    for(unsigned k=0;k<3;++k){n[v][k]=flat[k];active+=flat[k]>0 && flat[k]<1;bd+=flat[k]!=b[v][k];cd+=flat[k]!=c[v][k];regressed+=flat[k]==b[v][k] && flat[k]!=c[v][k];
                        vertices<<t<<","<<set<<","<<normalize<<","<<viewer<<","<<power<<","<<powers[power]<<","<<holdout<<","<<repeat<<","<<v<<","<<k<<","<<flat[k]<<","<<b[v][k]<<","<<c[v][k]<<","<<ground_endpoint_depth::Bits(flat[k])<<","<<ground_endpoint_depth::Bits(b[v][k])<<","<<ground_endpoint_depth::Bits(c[v][k])<<"\n";}
                }
                RgbaImage unused;std::vector<Color> actualN,actualB,actualC;
                const auto ps9=model_batch_color::PixelStage(1,false),ps11=model_batch_color::PixelStage(1,true);
                CHECK(NativeImage(window,{draw},1,unused,nullptr,64,64,0xffffffff,&actualN,&ps9,native.Get()));
                CHECK(model_batch_color::Stage11(draw,64,64,ps11,true,unused,actualB,{1,1,1,1},.5f,nullptr,&baseline));
                CHECK(model_batch_color::Stage11(draw,64,64,ps11,true,unused,actualC,{1,1,1,1},.5f,nullptr,&candidate));
                model_specular_origin::Images nativeShared,candidateShared;
                CHECK(interpolation.Observe(clipC,n,true,nativeShared));CHECK(interpolation.Observe(clipC,c,true,candidateShared));
                CHECK(nativeShared.n==nativeShared.c && candidateShared.n==candidateShared.c);
                const auto nativeGate=Changed(nativeShared.n,actualN),candidateGate=Changed(candidateShared.c,actualC);
                const auto bp=Changed(actualN,actualB),cp=Changed(actualN,actualC);unsigned rp=0,covered=0;
                for(unsigned p=0;p<actualN.size();++p){rp+=actualN[p]==actualB[p] && actualN[p]!=actualC[p];covered+=actualN[p]!=Color{1,1,1,1};}
                CHECK(covered>128 && active>0);
                if(repeat)CHECK(actualN==previousNative && actualB==previousBaseline && actualC==previousCandidate && n==previousFlat && b==previousBaselineVertices && c==previousCandidateVertices);
                previousNative=actualN;previousBaseline=actualB;previousCandidate=actualC;previousFlat=n;previousBaselineVertices=b;previousCandidateVertices=c;
                report<<t<<","<<set<<","<<normalize<<","<<viewer<<","<<power<<","<<holdout<<","<<repeat<<","<<covered<<","<<active<<","<<bd<<","<<cd<<","<<regressed<<","<<nativeGate<<","<<candidateGate<<","<<bp<<","<<cp<<","<<rp<<","<<Hash(actualN)<<","<<Hash(actualB)<<","<<Hash(actualC)<<"\n";report.flush();
                ++observations;baselineFailures+=bd!=0 || bp!=0;candidateFailures+=cd!=0 || cp!=0;regressions+=regressed!=0 || rp!=0;gateFailures+=nativeGate!=0 || candidateGate!=0;
                unchangedFailures+=!viewer && (actualB!=actualC || b!=c);
                if(!repeat && (cd || cp || nativeGate || candidateGate))std::printf("specularScope mismatch transform=%u set=%u normalize=%u viewer=%u power=%u channels=%u pixels=%u nativeGate=%u candidateGate=%u\n",t,set,normalize,viewer,power,cd,cp,nativeGate,candidateGate);
            }
            ++controls;
        }
        std::printf("specularScope transform=%u name=%s observations=%u candidateFailures=%u regressions=%u gates=%u\n",t,transform.name,observations,candidateFailures,regressions,gateFailures);std::fflush(stdout);
    }
    std::ofstream metadata(directory/"metadata.txt"),summary(directory/"summary.txt");
    metadata<<"adapter="<<adapter.Description<<" transforms=5 normalSets=2 normalizeModes=2 localViewerModes=2 powers=0.5,1.7,5,7.3 samples=1 archiveRequired=0 productionActivation=0 imageAcceptance=0\n";
    summary<<"complete=1 controls="<<controls<<" observations="<<observations<<" repeats=3 baselineFailures="<<baselineFailures<<" candidateFailures="<<candidateFailures<<" regressions="<<regressions<<" gateFailures="<<gateFailures<<" localViewerOffChanges="<<unchangedFailures<<" productionActivation=0 imageAcceptance=0\n";
    CHECK(inputLog && vertices && report && metadata && summary);return candidateFailures || regressions || gateFailures || unchangedFailures?33:0;
}
}
