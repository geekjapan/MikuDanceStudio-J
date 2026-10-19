#pragma once
#include "normal_precision_fixture.hpp"

// Inputs are fixed before measurement. Signed/permuted/diagonal views have
// exactly axial transformed probe lights. General rotations do not: their
// signed-light responses measure the effective normal/light composition.
namespace normal_transform_diagnostic {
using namespace normal_precision_diagnostic;
struct Transform {const char* name;Matrix world,view;bool exactAxes;};
inline Matrix Affine(std::array<float,9> a,std::array<float,3> t={}) {
    Matrix m{};m[15]=1;
    for(unsigned r=0;r<3;++r)for(unsigned c=0;c<3;++c)m[r*4+c]=a[r*3+c];
    for(unsigned c=0;c<3;++c)m[12+c]=t[c];return m;
}
inline std::vector<Transform> Inputs() {
    const auto identity=Affine({1,0,0,0,1,0,0,0,1});
    const auto uniform=Affine({4,0,0,0,4,0,0,0,4},{.17f,-.23f,.31f});
    const auto nonuniform=Affine({4,0,0,0,6,0,0,0,8},{-.31f,.27f,-.19f});
    const auto shear=Affine({4,.375f,-.25f,.125f,5,.5f,-.375f,.25f,6},{.41f,-.13f,.29f});
    const auto mixed=Affine({3.73f,.19f,-.37f,-.13f,5.17f,.23f,.41f,-.29f,6.31f},{-.17f,.43f,.11f});
    const auto rotated=Affine({3.2f,0,-2.4f,0,4,0,2.4f,0,3.2f},{.13f,-.27f,.37f});
    const auto cycle=Affine({0,1,0,0,0,1,1,0,0},{.23f,-.11f,.17f});
    const auto signedCycle=Affine({0,0,-1,-1,0,0,0,1,0},{-.37f,.19f,.31f});
    const auto nearUnit=Affine({.99999994039535522f,0,0,0,.99999994039535522f,0,0,0,1},{.19f,-.41f,.23f});
    const auto nearUnit2=Affine({.99999988079071045f,0,0,0,1,0,0,0,.99999994039535522f},{-.11f,.37f,.29f});
    const auto yRotation=Affine({.8f,0,-.6f,0,1,0,.6f,0,.8f},{-.23f,.17f,.41f});
    const auto xRotation=Affine({1,0,0,0,.9230769230769231f,.3846153846153846f,0,-.3846153846153846f,.9230769230769231f},{.31f,-.19f,.13f});
    const auto xyRotation=depth_diagnostic::Multiply(xRotation,yRotation,depth_diagnostic::Rounding::Sequential);
    return {{"uniform_translation",uniform,identity,true},{"nonuniform",nonuniform,identity,true},
        {"dyadic_shear",shear,identity,true},{"mixed_signed_view",mixed,signedCycle,true},
        {"rotated_cycle_view",rotated,cycle,true},{"shear_cycle_view",shear,cycle,true},
        {"mixed_near_unit_view",mixed,nearUnit,true},{"rotated_near_unit_view",rotated,nearUnit2,true},
        {"mixed_y_view",mixed,yRotation,false},{"shear_x_view",shear,xRotation,false},
        {"nonuniform_xy_view",nonuniform,xyRotation,false},{"mixed_xy_view",mixed,xyRotation,false}};
}
inline bool Inverse(const Matrix& m,Matrix& out) {
    // Geometry/light construction only; this is not the normal-matrix candidate.
    double a[4][8]{};for(unsigned r=0;r<4;++r){for(unsigned c=0;c<4;++c)a[r][c]=m[r*4+c];a[r][r+4]=1;}
    for(unsigned c=0;c<4;++c){unsigned pivot=c;for(unsigned r=c+1;r<4;++r)if(std::abs(a[r][c])>std::abs(a[pivot][c]))pivot=r;
        if(a[pivot][c]==0)return false;for(unsigned k=0;k<8;++k)std::swap(a[c][k],a[pivot][k]);
        const auto divisor=a[c][c];for(unsigned k=0;k<8;++k)a[c][k]/=divisor;
        for(unsigned r=0;r<4;++r)if(r!=c){const auto factor=a[r][c];for(unsigned k=0;k<8;++k)a[r][k]-=factor*a[c][k];}}
    for(unsigned r=0;r<4;++r)for(unsigned c=0;c<4;++c)out[r*4+c]=static_cast<float>(a[r][c+4]);return true;
}
inline bool Patch(const Transform& transform,const std::array<float,3>& normal,D3D9ReplaySnapshot& source) {
    source=lighting_rounding_diagnostic::Patch(Fixture(),normal,false);
    std::memcpy(&source.world,transform.world.data(),64);std::memcpy(&source.view,transform.view.data(),64);
    source.projection=Fixture().projection;Matrix inverse;
    if(!Inverse(depth_diagnostic::Multiply(transform.world,transform.view,depth_diagnostic::Rounding::Double),inverse))return false;
    const Color positions[]={{{-.75f,-.75f,.5f,1}},{{-.75f,.75f,.5f,1}},{{.75f,-.75f,.5f,1}}};
    for(unsigned v=0;v<3;++v)for(unsigned c=0;c<3;++c){double position=0;for(unsigned k=0;k<4;++k)position+=double(positions[v][k])*inverse[k*4+c];
        const float rounded=static_cast<float>(position);std::memcpy(source.vertexBytes.data()+v*32+c*4,&rounded,4);}
    lighting_rounding_diagnostic::Change(source,D3DRS_NORMALIZENORMALS,TRUE);
    source.material={};source.material.Diffuse={.073f,.21f,.37f,1};source.material.Ambient={.19f,.09f,.061f,1};source.material.Emissive={.027f,.041f,.003f,1};
    D3D9ReplaySnapshot::Light light{};light.index=0;light.enabled=TRUE;light.value.Type=D3DLIGHT_DIRECTIONAL;
    light.value.Direction={.27f,-.43f,.61f};light.value.Diffuse={1.37f,.73f,1.13f,1};light.value.Ambient={-.17f,.23f,-.083f,1};source.lights={light};return true;
}
inline void AxialLight(D3D9ReplaySnapshot& source,const Matrix& inverseView,unsigned axis,unsigned sign) {
    // A row-vector camera-space axis times inverse(view) gives world direction.
    source.lights[0].value.Direction={inverseView[axis*4]*(sign?1.f:-1.f),inverseView[axis*4+1]*(sign?1.f:-1.f),inverseView[axis*4+2]*(sign?1.f:-1.f)};
    source.lights[0].value.Diffuse={1,1,1,1};source.lights[0].value.Ambient={};source.material={};source.material.Diffuse={1,1,1,1};
}
inline bool Capture(const D3D9ReplaySnapshot& source,const Matrix& matrix,bool candidate,unsigned stage,std::vector<Color>& colors) {
    // Existing material-order candidate plus the independently tested normal
    // dot rule. No native measurements enter shader constants.
    auto shader=lighting_shader_diagnostic::Source(Source(candidate?1:0,stage).c_str());std::vector<Color> positions;
    return !shader.empty() && CaptureDepthVertexShader(source,positions,nullptr,false,0,&colors,&shader,&matrix);
}
inline int Run(HWND window,const char* outputPath) {
    using namespace lighting_rounding_diagnostic;
    const std::filesystem::path directory(outputPath);std::filesystem::create_directories(directory);
    NativeRenderer native;CHECK(native.Initialize(window,directory));const auto transforms=Inputs();
    const std::array<float,3> normals[]={{.13f,.37f,-.91f},{-.83f,.11f,-.47f},{.007f,-.015f,.019f},{.25f,1.75f,-2.5f},{-1.33f,-.27f,.51f},{.61f,.73f,-.89f}};
    std::ofstream matrices(directory/"matrices.csv"),axes(directory/"axes.csv"),values(directory/"values.csv");
    matrices<<"transform,name,holdout,exactAxes,kind,k,bits,value\n"<<std::setprecision(17);
    axes<<"transform,holdout,exactAxes,normal,normalize,axis,sign,path,bits,value\n"<<std::setprecision(17);
    values<<"transform,holdout,normal,path,stage,k,bits,value\n"<<std::setprecision(17);
    unsigned matrixExact=0,rawExact=0,normalizedExact=0,lengthExact=0,reciprocalExact=0,facingExact=0,colorExact=0,axisExact=0;
    for(unsigned t=0;t<transforms.size();++t){const auto& transform=transforms[t];Matrix original,rounded,inverseView,identity=Inputs()[0].view;
        CHECK(BuildShaderNormalMatrix(transform.world,transform.view,original));
        const auto combined=depth_diagnostic::Multiply(transform.world,transform.view,depth_diagnostic::Rounding::Sequential);
        CHECK(BuildShaderNormalMatrix(combined,identity,rounded));CHECK(Inverse(transform.view,inverseView));
        for(unsigned kind=0;kind<4;++kind){const Matrix& m=kind==0?transform.world:kind==1?transform.view:kind==2?original:rounded;
            for(unsigned k=0;k<16;++k)matrices<<t<<","<<transform.name<<","<<(t>=6)<<","<<transform.exactAxes<<","<<kind<<","<<k<<","<<accessory_color_diagnostic::Bits(m[k])<<","<<m[k]<<"\n";}
        // Observe coefficients with object axes. For general rotations these
        // remain effective lighting responses, not claimed normal coefficients.
        for(unsigned row=0;row<3;++row){std::array<float,3> axis{};axis[row]=1;D3D9ReplaySnapshot source;CHECK(Patch(transform,axis,source));Change(source,D3DRS_NORMALIZENORMALS,FALSE);
            for(unsigned col=0;col<3;++col){float responses[2];for(unsigned sign=0;sign<2;++sign){AxialLight(source,inverseView,col,sign);Color value;CHECK(native.Fixed(source,value));responses[sign]=value[0];
                axes<<t<<","<<(t>=6)<<","<<transform.exactAxes<<","<<(6+row)<<",0,"<<col<<","<<sign<<",0,"<<accessory_color_diagnostic::Bits(value[0])<<","<<value[0]<<"\n";}
                matrixExact+=transform.exactAxes && responses[0]-responses[1]==rounded[row*4+col];}}
        auto batch=Fixture();for(unsigned n=0;n<6;++n){D3D9ReplaySnapshot source;CHECK(Patch(transform,normals[n],source));if(!n){batch=source;batch.vertices=6;batch.vertexBytes.resize(6*32);}std::memcpy(batch.vertexBytes.data()+n*32,source.vertexBytes.data(),32);
            for(unsigned normalize=0;normalize<2;++normalize){Change(source,D3DRS_NORMALIZENORMALS,normalize?TRUE:FALSE);
                for(unsigned axis=0;axis<3;++axis)for(unsigned sign=0;sign<2;++sign){AxialLight(source,inverseView,axis,sign);Color value;CHECK(native.Fixed(source,value));
                    axes<<t<<","<<(t>=6)<<","<<transform.exactAxes<<","<<n<<","<<normalize<<","<<axis<<","<<sign<<",0,"<<accessory_color_diagnostic::Bits(value[0])<<","<<value[0]<<"\n";
                    std::vector<Color> candidate,repeat;CHECK(Capture(source,rounded,true,5,candidate));CHECK(Capture(source,rounded,true,5,repeat));
                    CHECK(candidate==repeat && candidate.size()==3 && candidate[0]==candidate[1] && candidate[0]==candidate[2]);
                    axes<<t<<","<<(t>=6)<<","<<transform.exactAxes<<","<<n<<","<<normalize<<","<<axis<<","<<sign<<",1,"<<accessory_color_diagnostic::Bits(candidate[0][0])<<","<<candidate[0][0]<<"\n";
                    axisExact+=candidate[0][0]==value[0];}
            }
        }
        auto log=[&](unsigned n,unsigned path,unsigned stage,const Color& value){for(unsigned k=0;k<4;++k)values<<t<<","<<(t>=6)<<","<<n<<","<<path<<","<<stage<<","<<k<<","<<accessory_color_diagnostic::Bits(value[k])<<","<<value[k]<<"\n";};
        std::array<std::vector<Color>,6> captured;
        for(unsigned path=0;path<2;++path)for(unsigned stage=0;stage<6;++stage){std::vector<Color> first,repeat;
            CHECK(Capture(batch,path?rounded:original,path,stage,first));CHECK(Capture(batch,path?rounded:original,path,stage,repeat));CHECK(first==repeat && first.size()==6);
            for(unsigned n=0;n<6;++n)log(n,path,stage,first[n]);if(path)captured[stage]=first;}
        for(unsigned n=0;n<6;++n){D3D9ReplaySnapshot source;CHECK(Patch(transform,normals[n],source));const Color toward=captured[4][n];
            auto explicitSource=source;const float explicitPositions[][3]={{-6,-6,0},{-6,6,0},{6,-6,0}};
            for(unsigned v=0;v<3;++v)std::memcpy(explicitSource.vertexBytes.data()+v*32,explicitPositions[v],12);
            for(unsigned stage=0;stage<4;++stage){Color observed;CHECK(native.Explicit(explicitSource,rounded,toward,stage,observed));log(n,2,stage,observed);
                const unsigned corresponding[]={0,2,3,1};for(unsigned k=0;k<3;++k){const bool match=observed[k]==captured[corresponding[stage]][n][k];if(!stage)rawExact+=match;if(stage==3)normalizedExact+=match;}
                if(stage==1)lengthExact+=observed[0]==captured[2][n][0];if(stage==2)reciprocalExact+=observed[0]==captured[3][n][0];}
            Color nativeFacing,nativeColor;auto white=source;white.material={};white.material.Diffuse={1,1,1,1};white.lights[0].value.Diffuse={1,1,1,1};white.lights[0].value.Ambient={};
            CHECK(native.Fixed(white,nativeFacing));CHECK(native.Fixed(source,nativeColor));log(n,3,5,nativeFacing);log(n,3,6,nativeColor);facingExact+=nativeFacing[0]==captured[5][n][0];
            std::vector<Color> candidateColor,repeatedColor;CHECK(Capture(source,rounded,true,6,candidateColor));CHECK(Capture(source,rounded,true,6,repeatedColor));
            CHECK(candidateColor==repeatedColor && candidateColor[0]==candidateColor[1] && candidateColor[0]==candidateColor[2]);log(n,1,6,candidateColor[0]);
            for(unsigned k=0;k<3;++k)colorExact+=nativeColor[k]==std::clamp(candidateColor[0][k],0.f,1.f);
        }
    }
    CHECK(matrices && axes && values);
    std::ofstream manifest(directory/"manifest.json");manifest<<"{\"transforms\":12,\"holdoutTransforms\":6,\"normals\":6,\"exactAxisTransforms\":8,\"samples\":1,\"nativeRepeats\":3,\"gpuRepeats\":2,\"productionActivation\":false}\n";CHECK(manifest);
    std::printf("normalTransforms transforms=12 holdoutTransforms=6 normals=6 axialMatrixExact=%u/72 rawProgrammableExact=%u/216 normalizedProgrammableExact=%u/216 lengthExact=%u/72 reciprocalExact=%u/72 signedFacingExact=%u/864 facingExact=%u/72 colorExact=%u/216 productionActivation=0\n",matrixExact,rawExact,normalizedExact,lengthExact,reciprocalExact,axisExact,facingExact,colorExact);
    return matrixExact==72 && rawExact==216 && normalizedExact==216 && lengthExact==72 && reciprocalExact==72 && axisExact==864 && facingExact==72 && colorExact==216?0:32;
}
} // namespace normal_transform_diagnostic
