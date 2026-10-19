#pragma once
// Isolate captured normal/normalization/texture dot arithmetic. Policy one
// now exercises the default-off production diagnostic rule; separate-rounding
// control remains test-local.
namespace model_toon_rounding {
using model_batch_color::Color;
using model_sampling_diagnostic::Area;
using model_transform_diagnostic::Crop;
using model_transform_diagnostic::Save;
inline std::string VertexSource(unsigned policy) {
    std::string text=modelVertexSource;
    const auto at=text.find("float2 Coordinate(");const auto end=text.find("PixelInput main(",at);
    if(at==std::string::npos || end==std::string::npos || policy>2)return {};
    // Policy one exercises the production opt-in source. Policy zero remains
    // the production default; policy two is the separate-rounding control.
    if(policy==1)return std::string("#define MDS_MODEL_TEXTURE_FMA_DIAGNOSTIC 1\n")+modelDx9CompatibilitySource+text;
    if(policy) {
        text.replace(at,end-at,"float2 Coordinate(uint stage,uint mode,float3 normal,float2 uv){if(mode!=2)return uv;float2 result;[unroll]for(uint c=0;c<2;++c){float4 column=float4(textureTransform[stage][0][c],textureTransform[stage][1][c],textureTransform[stage][2][c],textureTransform[stage][3][c]);result[c]=ToonSeparateDot(float4(normal,1),column);}return result;}\n");
    }
    return std::string(modelDx9CompatibilitySource)+R"(
float ToonSeparateDot(float4 a,float4 b) {
    precise float p0=a.x*b.x;precise float p1=a.y*b.y;
    precise float p2=a.z*b.z;precise float p3=a.w*b.w;
    precise float sum=p0+p1;sum=sum+p2;return sum+p3;
}
)"+text;
}
inline unsigned State(const D3D9ReplaySnapshot& c,unsigned key) {
    for(const auto& s:c.renderStates)if(s.key==key)return s.value;return ~0u;
}
inline int Run(HWND window,const char* root,const char* destination,unsigned x,unsigned y,unsigned triangle) {
    ground_history_isolation::Archive archive;CHECK(archive.Load(root,24));CHECK(triangle<archive.draws[22].count);
    CHECK(x>=2 && y>=2 && x+2<archive.width && y+2<archive.height);
    const std::filesystem::path output(destination);CHECK(!std::filesystem::exists(output));std::filesystem::create_directories(output);
    auto source=ground_history_isolation::CompactTriangle(ground_history_isolation::Triangles(archive.draws[22],triangle,1));
    for(unsigned key:{D3DRS_ALPHABLENDENABLE,D3DRS_ALPHATESTENABLE,D3DRS_ZENABLE,D3DRS_ZWRITEENABLE,D3DRS_STENCILENABLE})ground_history_isolation::State(source,key,0);
    ground_history_isolation::State(source,D3DRS_CULLMODE,D3DCULL_NONE);
    std::ofstream metadata(output/"metadata.txt"),report(output/"controls.csv"),pixels(output/"pixels.csv"),vertices(output/"vertices.csv"),images(output/"images.csv");
    metadata<<"x="<<x<<" y="<<y<<" triangle="<<triangle<<" originalNormalize="<<State(source,D3DRS_NORMALIZENORMALS)<<" dx9NativePreRasterCapture=0 productionActivation=0 imageAcceptance=0\n";
    report<<"geometry,mode,repeat,knownPixels,coveredPixels,betweenApis,nativeVsOriginal,candidateVsOriginal\n";
    pixels<<"geometry,mode,repeat,x,y,nativeX,nativeY,nativeZ,nativeW,candidateX,candidateY,candidateZ,candidateW\n"<<std::setprecision(17);
    vertices<<"geometry,mode,repeat,vertex,x,y,bitsX,bitsY\n"<<std::setprecision(17);
    images<<"geometry,mode,repeat,differentPixels,maxDelta,x,y,nativeR,nativeG,nativeB,nativeA,candidateR,candidateG,candidateB,candidateA\n";
    unsigned observations=0;
    for(unsigned geometry=0;geometry<2;++geometry) {
        const auto base=geometry?model_batch_causal::Independent(source):source;const std::string label=geometry?"independent":"saved";
        const unsigned width=geometry?64:archive.width,height=geometry?64:archive.height,fx=geometry?24:x,fy=geometry?32:y;
        const auto& viewport=base.viewport;const Area area{viewport.X,viewport.Y,viewport.Width,viewport.Height};
        ComPtr<IDirect3D9> api;api.Attach(Direct3DCreate9(D3D_SDK_VERSION));CHECK(api);
        D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.hDeviceWindow=window;pp.BackBufferWidth=width;pp.BackBufferHeight=height;
        pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.BackBufferCount=1;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.EnableAutoDepthStencil=TRUE;pp.AutoDepthStencilFormat=D3DFMT_D24S8;
        ComPtr<IDirect3DDevice9> device;const auto created=api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device);
        if(FAILED(created))std::fprintf(stderr,"Toon rounding DX9 creation=%08lx\n",static_cast<unsigned long>(created));CHECK(SUCCEEDED(created));
        std::vector<Color> originalN,originalC;
        const char* modes[]={"original","raw_xy","raw_z","normalized_xy","normalized_z","toon_normalized",
                             "toon_fused","toon_separate","toon_normalized_fused"};
        for(unsigned mode=0;mode<9;++mode) {
            auto c=base;
            if(mode==1 || mode==2)ground_history_isolation::State(c,D3DRS_NORMALIZENORMALS,0);
            if(mode==3 || mode==4 || mode==5 || mode==8)ground_history_isolation::State(c,D3DRS_NORMALIZENORMALS,1);
            if(mode>=1 && mode<=4) {
                c.textureMatrices[0]={};c.textureMatrices[0]._44=1;
                if(mode==2 || mode==4){c.textureMatrices[0]._31=1;c.textureMatrices[0]._32=1;}
                else {c.textureMatrices[0]._11=1;c.textureMatrices[0]._22=1;}
            }
            const unsigned policy=mode==6 || mode==8?1:mode==7?2:0;
            const auto shader=VertexSource(policy);CHECK(!shader.empty());
            const auto soShader=std::string("#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+shader;
            std::vector<std::array<float,2>> soOriginal;std::vector<Color> nOriginal,cOriginal;
            for(unsigned repeat=0;repeat<3;++repeat) {
                RgbaImage unused;std::vector<Color> n,candidate;const auto ps9=model_batch_color::PixelStage(2,false),ps11=model_batch_color::PixelStage(2,true);
                CHECK(NativeImage(window,{c},1,unused,nullptr,width,height,0xffffffff,&n,&ps9,device.Get()));
                CHECK(model_batch_color::Stage11(c,width,height,ps11,true,unused,candidate,{1,1,1,1},.5f,nullptr,&shader));
                n=Crop(n,width,area);candidate=Crop(candidate,width,area);
                std::vector<Color> positions;std::vector<std::array<float,2>> uv;
                CHECK(CaptureDepthVertexShader(c,positions,nullptr,false,0,nullptr,&soShader,nullptr,false,&uv,0,false,false,true));CHECK(uv.size()==3);
                if(repeat)CHECK(n==nOriginal && candidate==cOriginal && uv==soOriginal);else {nOriginal=n;cOriginal=candidate;soOriginal=uv;}
                if(!mode){if(repeat)CHECK(n==originalN && candidate==originalC);else {originalN=n;originalC=candidate;}}
                unsigned between=0,ndelta=0,cdelta=0,covered=0;
                for(unsigned p=0;p<n.size();++p){between+=n[p]!=candidate[p];ndelta+=n[p]!=originalN[p];cdelta+=candidate[p]!=originalC[p];covered+=n[p][2]==0 && n[p][3]==1;}
                report<<label<<","<<modes[mode]<<","<<repeat<<","<<n.size()<<","<<covered<<","<<between<<","<<ndelta<<","<<cdelta<<"\n";
                for(unsigned py=fy-2;py<=fy+2;++py)for(unsigned px=fx-2;px<=fx+2;++px){const auto p=std::size_t(py-area.y)*area.width+px-area.x;
                    pixels<<label<<","<<modes[mode]<<","<<repeat<<","<<px<<","<<py;for(float f:n[p])pixels<<","<<f;for(float f:candidate[p])pixels<<","<<f;pixels<<"\n";}
                for(unsigned v=0;v<3;++v)vertices<<label<<","<<modes[mode]<<","<<repeat<<","<<v<<","<<uv[v][0]<<","<<uv[v][1]<<","<<ground_endpoint_depth::Bits(uv[v][0])<<","<<ground_endpoint_depth::Bits(uv[v][1])<<"\n";
                const auto stem=label+"_"+modes[mode]+".repeat"+std::to_string(repeat);
                CHECK(Save(output/(stem+".dx9.float"),n.data(),n.size()*16));CHECK(Save(output/(stem+".dx11.float"),candidate.data(),candidate.size()*16));
                if(mode==0 || mode==5 || mode==6 || mode==7 || mode==8) {
                    const auto ps=std::string("#define MDS_MODEL_SPECULAR 1\n#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+modelPixelSource;
                    RgbaImage nb,cb;std::vector<Color> scratch;
                    CHECK(NativeImage(window,{c},1,nb,nullptr,width,height,0xffffffff,nullptr,nullptr,device.Get()));
                    CHECK(model_batch_color::Stage11(c,width,height,ps,false,cb,scratch,{1,1,1,1},.5f,nullptr,&shader));
                    std::vector<unsigned char> na,ca;for(unsigned row=area.y;row<area.y+area.height;++row){
                        const auto offset=(std::size_t(row)*width+area.x)*4;
                        na.insert(na.end(),nb.pixels.begin()+offset,nb.pixels.begin()+offset+area.width*4);
                        ca.insert(ca.end(),cb.pixels.begin()+offset,cb.pixels.begin()+offset+area.width*4);}
                    unsigned different=0,maximum=0;
                    for(unsigned p=0;p<na.size()/4;++p){unsigned d=0;for(unsigned k=0;k<4;++k)d=(std::max)(d,unsigned(std::abs(int(na[p*4+k])-int(ca[p*4+k]))));different+=d!=0;maximum=(std::max)(maximum,d);}
                    images<<label<<","<<modes[mode]<<","<<repeat<<","<<different<<","<<maximum<<","<<fx<<","<<fy;
                    const auto f=(std::size_t(fy)*width+fx)*4;for(unsigned k=0;k<4;++k)images<<","<<unsigned(nb.pixels[f+k]);for(unsigned k=0;k<4;++k)images<<","<<unsigned(cb.pixels[f+k]);images<<"\n";images.flush();
                    CHECK(Save(output/(stem+".dx9.rgba"),na.data(),na.size()));CHECK(Save(output/(stem+".dx11.rgba"),ca.data(),ca.size()));
                }
                report.flush();pixels.flush();vertices.flush();++observations;
                std::printf("toonRounding geometry=%s mode=%s repeat=%u between=%u nativeDelta=%u candidateDelta=%u\n",label.c_str(),modes[mode],repeat,between,ndelta,cdelta);std::fflush(stdout);
            }
        }
    }
    // Retain generated VS source + disassembly to verify actual rounding,
    // rather than relying on HLSL expression names.
    for(unsigned policy=0;policy<3;++policy) {
        const auto shader=std::string("#define MDS_MODEL_DX9_COMPATIBILITY 1\n")+VertexSource(policy);ComPtr<ID3DBlob> code,error,listing;
        CHECK(SUCCEEDED(D3DCompile(shader.data(),shader.size(),nullptr,nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_IEEE_STRICTNESS,0,&code,&error)));
        CHECK(SUCCEEDED(D3DDisassemble(code->GetBufferPointer(),code->GetBufferSize(),0,nullptr,&listing)));
        std::ofstream hlsl(output/("vertex"+std::to_string(policy)+".hlsl")),assembly(output/("vertex"+std::to_string(policy)+".asm"));
        hlsl<<shader;assembly.write(static_cast<const char*>(listing->GetBufferPointer()),listing->GetBufferSize());CHECK(hlsl && assembly);
    }
    std::ofstream summary(output/"summary.txt");summary<<"complete=1 observations="<<observations<<" controls=18 repeats=3 geometries=2 productionActivation=0 imageAcceptance=0\n";
    CHECK(metadata && report && pixels && vertices && images && summary);return 0;
}
}
