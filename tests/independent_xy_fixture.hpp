#pragma once
// Generated inputs fixed before measurement. A completed experiment is not a
// native-equivalence acceptance: native mismatches stay in the evidence.
namespace independent_xy_diagnostic {
using model_sampling_diagnostic::Color;
using model_sampling_diagnostic::Vertex;
using model_sampling_diagnostic::Renderer;
using depth_diagnostic::Matrix;
using depth_diagnostic::Rounding;
using model_transform_diagnostic::Save;
using model_transform_diagnostic::Changed;
using normal_transform_diagnostic::Affine;
struct Transform {const char* name;Matrix world,view,projection;};
inline Matrix Perspective(float x,float y,float nearZ,float farZ,float offsetX=0,float offsetY=0) {
    Matrix m{};m[0]=x;m[5]=y;m[8]=offsetX;m[9]=offsetY;
    m[10]=farZ/(farZ-nearZ);m[11]=1;m[14]=-nearZ*m[10];return m;
}
inline std::vector<Transform> Inputs() {
    const auto identity=Affine({1,0,0,0,1,0,0,0,1});
    const auto dyadic=Affine({2,.25f,0,0,1.5f,.125f,.5f,0,1},{.125f,-.25f,.5f});
    const auto dense=Affine({1.13f,.19f,-.37f,-.13f,1.17f,.23f,.41f,-.29f,1.31f},{-.17f,.43f,.11f});
    const auto view=Affine({.8f,.13f,-.6f,-.17f,.93f,.11f,.6f,-.23f,.8f},{.31f,-.19f,.37f});
    const auto rotate=Affine({.8f,0,-.6f,0,1,0,.6f,0,.8f},{-.23f,.17f,.41f});
    const auto cycle=Affine({0,1,0,0,0,1,1,0,0},{.23f,-.11f,.17f});
    const auto large=Affine({1.13f,.19f,-.37f,-.13f,1.17f,.23f,.41f,-.29f,1.31f},{4096.13f,-8192.27f,2048.19f});
    const auto nearUnit=Affine({.99999994039535522f,.000013f,0,-.000017f,1,0,0,.000023f,.99999988079071045f},{-.11f,.37f,.29f});
    const auto p=Perspective(1.173f,1.619f,.173f,19.37f);
    const auto offset=Perspective(1.371f,1.913f,.219f,31.13f,.071f,-.13f);
    auto ortho=identity;ortho[0]=.73f;ortho[5]=1.13f;ortho[10]=.17f;ortho[12]=.11f;ortho[13]=-.19f;ortho[14]=.23f;
    return {{"identity",identity,identity,identity},{"dyadic_affine",dyadic,cycle,identity},
        {"dense_orthographic",dense,view,ortho},{"rotated_perspective",rotate,view,p},
        {"permuted_perspective",dense,cycle,p},{"dense_perspective",dyadic,view,p},
        {"large_cancellation",large,identity,p},{"near_unit_view",dense,nearUnit,p},
        {"off_axis_perspective",dense,view,offset},{"view_only_perspective",identity,view,offset},
        {"narrow_perspective",view,dense,Perspective(2.731f,3.917f,.073f,53.19f,.113f,.071f)},
        {"dense_both_orthographic",view,dense,ortho}};
}
inline ModelTextureData Texture() {
    ModelTextureData data;RgbaImage level;level.width=level.height=32;level.pixels.resize(32*32*4);
    for(unsigned y=0;y<32;++y)for(unsigned x=0;x<32;++x){auto* p=level.pixels.data()+(y*32+x)*4;
        p[0]=(17*x+29*y+13)%239;p[1]=(31*x+7*y+47)%241;p[2]=(11*x+23*y+71)%251;p[3]=255;}
    data.levels.push_back(std::move(level));return data;
}
inline bool Make(const Transform& transform,unsigned geometry,D3D9ReplaySnapshot& draw) {
    // Camera-space points are fixed analytically, then inverse(WV) constructs
    // object coordinates. No measured GPU output selects or adjusts geometry.
    const float ndc[3][3][2]={{{-.731f,-.617f},{-.413f,.713f},{.791f,-.337f}},
        {{-.813f,-.139f},{.793f,.017f},{.717f,.151f}},
        {{-.173f,.817f},{.617f,-.713f},{-.717f,-.317f}}};
    const float z[3][3]={{2.313f,4.719f,3.137f},{5.173f,2.719f,6.131f},{3.731f,6.317f,2.113f}};
    const float uv[3][2]={{.173f,.297f},{1.113f,-.231f},{-.407f,1.371f}};
    Matrix inverse;if(!normal_transform_diagnostic::Inverse(depth_diagnostic::Multiply(transform.world,transform.view,Rounding::Double),inverse))return false;
    draw=Fixture();draw.viewport={5,7,64,56,0,1};draw.indexed=false;draw.indexBytes.clear();
    std::memcpy(&draw.world,transform.world.data(),64);std::memcpy(&draw.view,transform.view.data(),64);std::memcpy(&draw.projection,transform.projection.data(),64);
    Set(draw,D3DRS_ZENABLE,0);Set(draw,D3DRS_ZWRITEENABLE,0);
    draw.textureInfo[0]={true,D3DFMT_A8R8G8B8,32,32,1,0,false};draw.textureBytes[0].clear();const auto texture=Texture();
    for(std::size_t n=0;n<texture.levels[0].pixels.size();n+=4){const auto* p=texture.levels[0].pixels.data()+n;draw.textureBytes[0].insert(draw.textureBytes[0].end(),{p[2],p[1],p[0],p[3]});}
    model_color_isolation::Sampler(draw,0,D3DSAMP_MINFILTER,D3DTEXF_LINEAR);model_color_isolation::Sampler(draw,0,D3DSAMP_MAGFILTER,D3DTEXF_LINEAR);
    model_color_isolation::Sampler(draw,0,D3DSAMP_ADDRESSV,D3DTADDRESS_WRAP);
    for(unsigned n=0;n<3;++n){const bool perspective=transform.projection[11]!=0;
        const double depth=perspective?z[geometry][n]:(transform.projection[10]==1?.5:2.);
        const double w=perspective?depth:1;
        const double camera[4]={(ndc[geometry][n][0]*w-depth*transform.projection[8]-transform.projection[12])/transform.projection[0],
            (ndc[geometry][n][1]*w-depth*transform.projection[9]-transform.projection[13])/transform.projection[5],depth,1};
        float vertex[8]={0,0,0,0,0,1,uv[n][0],uv[n][1]};
        for(unsigned c=0;c<3;++c){double value=0;for(unsigned k=0;k<4;++k)value+=camera[k]*inverse[k*4+c];vertex[c]=static_cast<float>(value);}
        std::memcpy(draw.vertexBytes.data()+n*32,vertex,32);
    }return true;
}
inline bool Native(Renderer& r,const D3D9ReplaySnapshot& draw,unsigned channel,std::vector<Color>& pixels,std::vector<unsigned char>& bytes) {
    const unsigned shader=channel==3?0:channel,format=channel==3?0:1;
    auto* d=r.d9.Get();
    if(FAILED(d->SetRenderTarget(0,r.target9[format].Get())) || FAILED(d->SetDepthStencilSurface(nullptr)) ||
       FAILED(d->SetVertexShader(nullptr)) || FAILED(d->SetFVF(draw.fvf)) || FAILED(d->SetPixelShader(r.legacyPs9[shader].Get())) ||
       FAILED(d->SetTransform(D3DTS_WORLD,&draw.world)) || FAILED(d->SetTransform(D3DTS_VIEW,&draw.view)) || FAILED(d->SetTransform(D3DTS_PROJECTION,&draw.projection)) ||
       FAILED(d->SetTexture(0,r.texture9.Get())))return false;
    for(auto state:{std::pair<D3DRENDERSTATETYPE,DWORD>{D3DRS_ZENABLE,0},{D3DRS_ZWRITEENABLE,0},{D3DRS_LIGHTING,0},{D3DRS_SPECULARENABLE,0},{D3DRS_FOGENABLE,0},{D3DRS_CULLMODE,D3DCULL_NONE},
        {D3DRS_ALPHABLENDENABLE,0},{D3DRS_ALPHATESTENABLE,0},{D3DRS_STENCILENABLE,0},{D3DRS_SCISSORTESTENABLE,0},{D3DRS_SRGBWRITEENABLE,0},{D3DRS_DITHERENABLE,0},{D3DRS_COLORWRITEENABLE,15}})
        if(FAILED(d->SetRenderState(state.first,state.second)))return false;
    for(auto state:{std::pair<D3DTEXTURESTAGESTATETYPE,DWORD>{D3DTSS_TEXCOORDINDEX,0},{D3DTSS_TEXTURETRANSFORMFLAGS,0},{D3DTSS_COLOROP,D3DTOP_MODULATE},{D3DTSS_COLORARG1,D3DTA_TEXTURE},{D3DTSS_COLORARG2,D3DTA_DIFFUSE},
        {D3DTSS_ALPHAOP,D3DTOP_MODULATE},{D3DTSS_ALPHAARG1,D3DTA_TEXTURE},{D3DTSS_ALPHAARG2,D3DTA_DIFFUSE}})if(FAILED(d->SetTextureStageState(0,state.first,state.second)))return false;
    if(FAILED(d->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE)))return false;
    for(auto state:{std::pair<D3DSAMPLERSTATETYPE,DWORD>{D3DSAMP_MINFILTER,D3DTEXF_LINEAR},{D3DSAMP_MAGFILTER,D3DTEXF_LINEAR},{D3DSAMP_MIPFILTER,D3DTEXF_POINT},
        {D3DSAMP_ADDRESSU,D3DTADDRESS_WRAP},{D3DSAMP_ADDRESSV,D3DTADDRESS_WRAP},{D3DSAMP_SRGBTEXTURE,0},{D3DSAMP_MAXMIPLEVEL,0},{D3DSAMP_MIPMAPLODBIAS,0}})
        if(FAILED(d->SetSamplerState(0,state.first,state.second)))return false;
    const D3DVIEWPORT9 full{0,0,r.width,r.height,0,1};
    if(FAILED(d->SetViewport(&full)) || FAILED(d->Clear(0,nullptr,D3DCLEAR_TARGET,0xffffffff,1,0)) || FAILED(d->SetViewport(&draw.viewport)) || FAILED(d->BeginScene()))return false;
    const auto hr=d->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,draw.vertexBytes.data(),32),end=d->EndScene();
    if(FAILED(hr) || FAILED(end) || FAILED(d->GetRenderTargetData(r.target9[format].Get(),r.cpu9[format].Get())))return false;
    D3DLOCKED_RECT lock;if(FAILED(r.cpu9[format]->LockRect(&lock,nullptr,D3DLOCK_READONLY)))return false;
    pixels.resize(std::size_t(r.width)*r.height);bytes.clear();if(!format)bytes.resize(pixels.size()*4);
    for(unsigned y=0;y<r.height;++y)for(unsigned x=0;x<r.width;++x){const auto i=y*r.width+x;const auto* src=static_cast<const unsigned char*>(lock.pBits)+y*lock.Pitch+x*(format?16:4);
        if(format)std::memcpy(pixels[i].data(),src,16);else for(unsigned k=0;k<4;++k){const unsigned order[]={2,1,0,3};bytes[i*4+k]=src[order[k]];pixels[i][k]=src[order[k]]/255.f;}}
    return SUCCEEDED(r.cpu9[format]->UnlockRect());
}
inline unsigned BytePixelDiff(const std::vector<unsigned char>& a,const std::vector<unsigned char>& b) {
    if(a.size()!=b.size() || a.size()%4)return ~0u;unsigned count=0;
    for(std::size_t n=0;n<a.size();n+=4)count+=std::memcmp(a.data()+n,b.data()+n,4)!=0;return count;
}
inline float drawVertex(const D3D9ReplaySnapshot& draw,unsigned n,unsigned c) {
    float value;std::memcpy(&value,draw.vertexBytes.data()+n*32+c*4,4);return value;
}
inline int Run(HWND window,const char* outputPath,bool controlsOnly=false,bool productionAdapter=false) {
    const auto root=controlsOnly?std::filesystem::path(outputPath)/("run-"+std::to_string(GetCurrentProcessId())):std::filesystem::path(outputPath);
    CHECK(!std::filesystem::exists(root));std::filesystem::create_directories(root);
    std::printf("independentXY evidence=%s controlsOnly=%u\n",root.string().c_str(),controlsOnly);std::fflush(stdout);
    const auto transforms=Inputs();const auto texture=Texture();Renderer renderer;const D3DVIEWPORT9 viewport{5,7,64,56,0,1};
    CHECK(renderer.Initialize(window,80,72,viewport,{0,0,80,72},texture));CHECK(Save(root/"texture.rgba",texture.levels[0].pixels.data(),texture.levels[0].pixels.size()));
    std::ofstream table(root/"observations.csv"),cases(root/"cases.csv"),materials(root/"materials.csv");
    table<<"case,mode,channel,nativeDifferent,candidateDifferent,betweenApis,maxAbsDelta\n"<<std::setprecision(17);
    cases<<"case,transform,name,holdout,geometry,coverage\n";
    materials<<"case,mode,differentPixels\n";
    SwapchainDesc desc;desc.window={WindowSystem::Win32,reinterpret_cast<std::uintptr_t>(window)};desc.width=desc.height=64;
    std::array<D3D11Bundle,2> bundles{productionAdapter?CreateD3D11Device(desc,D3D11Driver::Hardware):CreateD3D11ViewportCenterCandidateDevice(desc,D3D11Driver::Hardware),
        productionAdapter?CreateD3D11Device(desc,D3D11Driver::Hardware,{D3D11ModelCompatibility::Dx9Measured}):CreateD3D11FusedXYCandidateDevice(desc,D3D11Driver::Hardware)};
    CHECK(bundles[0] && bundles[1]);
    if(productionAdapter) {
        CHECK(CheckD3D11ModelCompatibility(D3D11ModelCompatibility::Dx9Measured,false)==D3D11CompatibilityResult::ShaderDoublesRequired);
        CHECK(CheckD3D11ModelCompatibility(D3D11ModelCompatibility::Default,false)==D3D11CompatibilityResult::Supported);
        const auto support=QueryD3D11ModelSupport(*bundles[1].device,D3D11ModelCompatibility::Dx9Measured);
        CHECK(support.shaderDoubles && support.selected==D3D11ModelCompatibility::Dx9Measured && support.requestedSupport==D3D11CompatibilityResult::Supported);
        CHECK(QueryD3D11ModelSupport(*bundles[0].device,D3D11ModelCompatibility::Default).selected==D3D11ModelCompatibility::Default);
        auto invalid=CreateD3D11Device(desc,D3D11Driver::Hardware,{static_cast<D3D11ModelCompatibility>(99)});
        CHECK(!invalid && invalid.creationReason=="invalid_model_compatibility");
    }
    const char* rules[]={"sequential","double","paired","fused"},*channels[]={"sample","uv","gradients","rgba8"};
    unsigned observations=0,qualified=0,sharedFailures=0,materialQualified=0;
    auto replay=[&](Device& device,const ModelReplayStream& stream,RgbaImage& image) {
        return productionAdapter?ReplayD3D11ModelPrefix(device,stream,1,image):ReplayD3D11WCandidatePrefix(device,stream,1,image);
    };
    for(unsigned t=0;t<transforms.size();++t)for(unsigned geometry=0;geometry<3;++geometry){const unsigned id=t*3+geometry;const auto label="case"+std::to_string(id);
        D3D9ReplaySnapshot draw;CHECK(Make(transforms[t],geometry,draw));CHECK(Save(root/(label+".vertices"),draw.vertexBytes.data(),96));
        const std::array<Matrix,3> source{transforms[t].world,transforms[t].view,transforms[t].projection};CHECK(Save(root/(label+".matrices"),source.data(),192));
        std::array<std::vector<Color>,4> reference;std::array<std::vector<unsigned char>,4> referenceBytes;
        for(unsigned c=0;c<4;++c){CHECK(Native(renderer,draw,c,reference[c],referenceBytes[c]));const auto& b=referenceBytes[c];
            CHECK(c==3?Save(root/(label+"_native_"+channels[c]+".rgba"),b.data(),b.size()):Save(root/(label+"_native_"+channels[c]+".float"),reference[c].data(),reference[c].size()*16));
            for(unsigned n=1;n<=3;++n){std::vector<Color> a;std::vector<unsigned char> bytes;CHECK(Native(renderer,draw,c,a,bytes));CHECK(Changed(a,reference[c])==0 && bytes==b);
                const auto name=label+"_native_repeat"+std::to_string(n)+"_"+channels[c];CHECK(c==3?Save(root/(name+".rgba"),bytes.data(),bytes.size()):Save(root/(name+".float"),a.data(),a.size()*16));}
        }
        unsigned coverage=0;for(const auto& p:reference[1])coverage+=p[2]==0;CHECK(coverage>8);
        cases<<id<<","<<t<<","<<transforms[t].name<<","<<(t>=6)<<","<<geometry<<","<<coverage<<"\n";cases.flush();
        auto shared=[&](const std::string& mode,const std::array<Vertex,3>& vertices,bool all){
            if(!Save(root/(label+"_"+mode+".input"),vertices.data(),sizeof(vertices)))return false;bool exact=true;
            for(unsigned c=0;c<4;++c){if(!all && c!=1 && c!=2)continue;std::vector<Color> a,b;std::vector<unsigned char> aa,bb;
                if(!renderer.Render(vertices,c==3?0:c,c==3?0:1,1,a,b,aa,bb))return false;
                const unsigned na=c==3?BytePixelDiff(aa,referenceBytes[3]):Changed(a,reference[c]),nb=c==3?BytePixelDiff(bb,referenceBytes[3]):Changed(b,reference[c]);
                const unsigned between=c==3?BytePixelDiff(aa,bb):Changed(a,b);double maxDelta=0;
                for(unsigned i=0;i<a.size();++i)for(unsigned k=0;k<4;++k){if(!std::isfinite(a[i][k]) || !std::isfinite(b[i][k]) || !std::isfinite(reference[c][i][k]))return false;
                    maxDelta=(std::max)(maxDelta,std::abs(double(b[i][k])-reference[c][i][k]));}
                if(c==3){if(!Save(root/(label+"_"+mode+"_rgba8.dx9.rgba"),aa.data(),aa.size()) || !Save(root/(label+"_"+mode+"_rgba8.dx11.rgba"),bb.data(),bb.size()))return false;}
                else if(!Save(root/(label+"_"+mode+"_"+channels[c]+".dx9.float"),a.data(),a.size()*16) || !Save(root/(label+"_"+mode+"_"+channels[c]+".dx11.float"),b.data(),b.size()*16))return false;
                table<<id<<","<<mode<<","<<channels[c]<<","<<na<<","<<nb<<","<<between<<","<<maxDelta<<"\n";table.flush();++observations;sharedFailures+=between!=0;exact&=nb==0;
            }if(mode=="gpu_fused_xy")qualified+=exact;return true;
        };
        for(unsigned m=0;m<4;++m){const auto combined=depth_diagnostic::Multiply(depth_diagnostic::Multiply(source[0],source[1],static_cast<Rounding>(m)),source[2],static_cast<Rounding>(m));
            CHECK(Save(root/(label+".combined_"+rules[m]),combined.data(),64));
            for(unsigned d=0;d<4;++d){std::array<Vertex,3> values;for(unsigned n=0;n<3;++n){Color object{0,0,0,1};std::memcpy(object.data(),draw.vertexBytes.data()+n*32,12);
                values[n].clip=model_transform_diagnostic::Transform(object,combined,static_cast<Rounding>(d));std::memcpy(values[n].uv.data(),draw.vertexBytes.data()+n*32+24,8);}
                CHECK(shared("matrix_"+std::string(rules[m])+"_dot_"+rules[d],values,false));
            }
            auto precombined=draw;precombined.world=precombined.view=Fixture().world;std::memcpy(&precombined.projection,combined.data(),64);
            for(unsigned c=1;c<=2;++c){std::vector<Color> a;std::vector<unsigned char> bytes;CHECK(Native(renderer,precombined,c,a,bytes));
                CHECK(Save(root/(label+"_precombined_"+rules[m]+"_"+channels[c]+".float"),a.data(),a.size()*16));
                table<<id<<",precombined_"<<rules[m]<<","<<channels[c]<<","<<Changed(a,reference[c])<<",-1,-1,0\n";++observations;}
        }
        for(unsigned policy=0;policy<2;++policy){std::vector<Color> positions;std::vector<std::array<float,2>> uv;
            CHECK(CaptureDepthVertexShader(draw,positions,nullptr,false,3,nullptr,nullptr,nullptr,false,&uv,0,true,policy!=0));CHECK(positions.size()==3 && uv.size()==3);
            std::array<Vertex,3> values;for(unsigned n=0;n<3;++n){values[n]={positions[n],uv[n]};CHECK(uv[n][0]==drawVertex(draw,n,6) && uv[n][1]==drawVertex(draw,n,7));
                if(policy){Color object{drawVertex(draw,n,0),drawVertex(draw,n,1),drawVertex(draw,n,2),1};const auto combined=w_shader_diagnostic::Inputs(source[0],source[1],source[2],3).combined;
                    const auto expected=model_transform_diagnostic::Transform(object,combined,Rounding::Fused);CHECK(std::memcmp(expected.data(),positions[n].data(),16)==0);}}
            const std::string mode=policy?"gpu_fused_xy":"gpu_baseline";CHECK(shared(mode,values,true));
            for(unsigned repeat=1;repeat<=3;++repeat){std::vector<Color> p;std::vector<std::array<float,2>> u;
                CHECK(CaptureDepthVertexShader(draw,p,nullptr,false,3,nullptr,nullptr,nullptr,false,&u,0,true,policy!=0));CHECK(p==positions && u==uv);
                CHECK(shared(mode+"_repeat"+std::to_string(repeat),values,true));}
        }
        ModelReplayStream stream;stream.target.width=80;stream.target.height=72;stream.clear={1,1,1,1};stream.events.push_back({1,ModelReplayOp::Clear});CHECK(AppendD3D9ReplaySnapshot(stream,draw));stream.complete=true;
        RgbaImage fixed;CHECK(NativeImage(window,{draw},1,fixed,nullptr,80,72,0xffffffff));CHECK(Save(root/(label+"_material.native.rgba"),fixed.pixels.data(),fixed.pixels.size()));
        for(unsigned policy=0;policy<2;++policy){RgbaImage image;CHECK(replay(*bundles[policy].device,stream,image));const auto mode=policy?"fused_xy":"baseline";
            const auto different=PixelDifferences(fixed,image);materials<<id<<","<<mode<<","<<different<<"\n";if(policy)materialQualified+=different==0;
            CHECK(Save(root/(label+"_material."+mode+".rgba"),image.pixels.data(),image.pixels.size()));
            for(unsigned repeat=1;repeat<=3;++repeat){RgbaImage repeated,repeatNative;CHECK(replay(*bundles[policy].device,stream,repeated));CHECK(NativeImage(window,{draw},1,repeatNative,nullptr,80,72,0xffffffff));
                CHECK(PixelDifferences(image,repeated)==0 && PixelDifferences(fixed,repeatNative)==0);
                CHECK(Save(root/(label+"_material."+mode+".repeat"+std::to_string(repeat)+".rgba"),repeated.pixels.data(),repeated.pixels.size()));}
        }
        std::printf("independentXY case=%u transform=%s geometry=%u qualifiedSoFar=%u materialQualified=%u sharedFailures=%u\n",id,transforms[t].name,geometry,qualified,materialQualified,sharedFailures);std::fflush(stdout);
    }
    for(auto& bundle:bundles)CHECK(bundle.swapchain->Retire());
    CHECK(table && cases && materials);std::ofstream summary(root/"summary.txt");
    summary<<"complete=1 transforms=12 holdoutTransforms=6 geometries=3 cases=36 observations="<<observations<<" qualifiedCases="<<qualified<<" sharedFailures="<<sharedFailures
        <<" materialQualified="<<materialQualified<<" samples=1 nativeRepeats=3 gpuRepeats=3 productionActivation=0 nativeVertexCapture=0 controlsOnly="<<controlsOnly<<" productionAdapter="<<productionAdapter<<"\n";CHECK(summary);
    std::ofstream meta(root/"metadata.txt");meta<<"width=80 height=72 viewport=5,7,64,56 center=viewport mipLevels=1 filter=linear adapter="<<renderer.adapter<<"\n";CHECK(meta);
    std::printf("independentXY complete=1 qualified=%u/36 materialQualified=%u/36 sharedFailures=%u productionActivation=0\n",qualified,materialQualified,sharedFailures);
    return sharedFailures?32:((controlsOnly && !productionAdapter) || (qualified==36 && materialQualified==36)?0:32);
}
} // namespace independent_xy_diagnostic
