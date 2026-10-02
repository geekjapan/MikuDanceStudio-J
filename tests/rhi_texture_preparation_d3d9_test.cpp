#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include "mikudancestudio/rhi_image.hpp"
#include "mikudancestudio/rhi_d3d9.hpp"
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <string>
#include <algorithm>
#include <float.h>
#include <cmath>
#include <cstring>
#include <cwchar>
using namespace mikudancestudio::rhi;
using Load = HRESULT (WINAPI*)(IDirect3DDevice9*,const void*,UINT,UINT,UINT,UINT,DWORD,
    D3DFORMAT,D3DPOOL,DWORD,DWORD,D3DCOLOR,void*,void*,IDirect3DTexture9**);
namespace {
struct Native {
    IDirect3D9* api = nullptr; IDirect3DDevice9* device = nullptr;
    HWND window = nullptr; HMODULE dll = nullptr;
    ~Native() {
        if (device) device->Release(); if (api) api->Release();
        if (window) DestroyWindow(window); if (dll) FreeLibrary(dll);
    }
};
void U32(std::vector<std::uint8_t>& b, unsigned at, unsigned value) {
    for (unsigned i = 0; i < 4; ++i) b[at + i] = static_cast<std::uint8_t>(value >> (i * 8));
}
std::vector<std::uint8_t> Synthetic() {
    std::vector<std::uint8_t> b(90);
    b[0]='B'; b[1]='M'; U32(b,2,90); U32(b,10,54); U32(b,14,40);
    U32(b,18,3); U32(b,22,3); b[26]=1; b[28]=24;
    for (unsigned y=0; y<3; ++y) for (unsigned x=0; x<3; ++x) {
        const unsigned at=54+(2-y)*12+x*3;
        b[at]=(x+y)%2?255:0; b[at+1]=y==0?0:y==1?127:255; b[at+2]=x==0?0:x==1?127:255;
    }
    return b;
}
// Original counterexample: a constant field plus one green-channel impulse.
// Contains no model content; isolates the same filtering boundary as the eye.
std::vector<std::uint8_t> Boundary(unsigned pattern=0) {
    constexpr unsigned width=106, pitch=(width*3+3)&~3u;
    std::vector<std::uint8_t> b(54+pitch*width);
    b[0]='B'; b[1]='M'; U32(b,2,static_cast<unsigned>(b.size()));
    U32(b,10,54); U32(b,14,40); U32(b,18,width); U32(b,22,width);
    b[26]=1; b[28]=24;
    for(unsigned y=0;y<width;++y)for(unsigned x=0;x<width;++x) {
        const unsigned at=54+(width-1-y)*pitch+x*3;
        b[at]=b[at+1]=b[at+2]=pattern<2?45:0;
        if(pattern==0 && x==44 && y==39)b[at+1]=46;
        if(pattern>=2 && y==39+pattern-2 && x>=42 && x<=44)b[at+2-(x-42)]=255;
    }
    return b;
}
bool ReadTexture(IDirect3DTexture9* texture, RgbaImage& image, D3DSURFACE_DESC& desc) {
    D3DLOCKED_RECT lock{};
    if (FAILED(texture->GetLevelDesc(0,&desc)) || desc.Format!=D3DFMT_A8R8G8B8 ||
        FAILED(texture->LockRect(0,&lock,nullptr,D3DLOCK_READONLY))) return false;
    image.width=desc.Width; image.height=desc.Height; image.pixels.resize(desc.Width*desc.Height*4u);
    for (unsigned y=0; y<desc.Height; ++y) for (unsigned x=0; x<desc.Width; ++x) {
        const auto* from=static_cast<const std::uint8_t*>(lock.pBits)+y*lock.Pitch+x*4;
        auto* to=image.pixels.data()+(static_cast<std::size_t>(y)*desc.Width+x)*4;
        to[0]=from[2];to[1]=from[1];to[2]=from[0];to[3]=from[3];
    }
    return SUCCEEDED(texture->UnlockRect(0));
}
bool ReadFloatTexture(IDirect3DTexture9* texture, unsigned width, unsigned height,
                      std::vector<float>& values) {
    D3DSURFACE_DESC desc{}; D3DLOCKED_RECT lock{};
    if(FAILED(texture->GetLevelDesc(0,&desc)) ||
       desc.Format!=D3DFMT_A32B32G32R32F || desc.Width!=width || desc.Height!=height ||
       FAILED(texture->LockRect(0,&lock,nullptr,D3DLOCK_READONLY)))return false;
    values.resize(static_cast<std::size_t>(width)*height*4);
    for(unsigned y=0;y<height;++y)
        std::memcpy(values.data()+static_cast<std::size_t>(y)*width*4,
            static_cast<const char*>(lock.pBits)+y*lock.Pitch,width*4*sizeof(float));
    return SUCCEEDED(texture->UnlockRect(0));
}
bool FloatDiagnostic(Load load, IDirect3DDevice9* device,
    const std::vector<std::uint8_t>& bytes, const RgbaImage& raw,
    const RgbaImage& reference, DWORD filter,
    const std::filesystem::path& root, bool boundary) {
    IDirect3DTexture9* texture=nullptr;
    // Separate diagnostic target: usage 0, RGBA32F. Never enters an upload cache.
    const auto hr=load(device,bytes.data(),static_cast<UINT>(bytes.size()),
        reference.width,reference.height,1,0,D3DFMT_A32B32G32R32F,D3DPOOL_MANAGED,
        filter,0xffffffffu,0,nullptr,nullptr,&texture);
    std::vector<float> values;
    const bool ready=SUCCEEDED(hr) && texture &&
        ReadFloatTexture(texture,reference.width,reference.height,values);
    if(texture)texture->Release();
    if(!ready)return false;
    constexpr unsigned thresholds[4][4]={{31,15,27,11},{19,3,23,7},
                                        {25,9,29,13},{21,5,17,1}};
    std::size_t differences=0;
    for(std::size_t i=0;i<values.size();++i) {
        if(!std::isfinite(values[i]))return false;
        const auto x=(i/4)%reference.width,y=i/4/reference.width;
        const float quantized=std::floor(values[i]*255.0f+thresholds[y%4][x%4]/32.0f);
        differences+=static_cast<unsigned>(std::clamp(quantized,0.0f,255.0f))!=reference.pixels[i];
    }
    std::string report="FLOAT filter="+std::to_string(filter)+" status="+
        (differences?"DIFFERENT":"MATCH")+" reconstructedChannels="+std::to_string(differences)+"\n";
    IDirect3DTexture9* identityTexture=nullptr;
    const auto identityHr=load(device,bytes.data(),static_cast<UINT>(bytes.size()),
        raw.width,raw.height,1,0,D3DFMT_A32B32G32R32F,D3DPOOL_MANAGED,
        filter,0xffffffffu,0,nullptr,nullptr,&identityTexture);
    std::vector<float> normalized;
    const bool identityReady=SUCCEEDED(identityHr) && identityTexture &&
        ReadFloatTexture(identityTexture,raw.width,raw.height,normalized);
    if(identityTexture)identityTexture->Release();
    if(!identityReady)return false;
    std::size_t divisionDifferences=0,reciprocalDifferences=0;
    for(std::size_t i=0;i<normalized.size();++i) {
        divisionDifferences+=normalized[i]!=(raw.pixels[i]/255.0f);
        reciprocalDifferences+=normalized[i]!=(raw.pixels[i]*(1.0f/255.0f));
    }
    report+="NORMALIZATION divisionDifferences="+std::to_string(divisionDifferences)+
        " reciprocalMultiplyDifferences="+std::to_string(reciprocalDifferences)+"\n";
    std::ofstream sourceFloats(root/(std::to_string(filter)+".source.rgba32f"),std::ios::binary);
    sourceFloats.write(reinterpret_cast<const char*>(normalized.data()),normalized.size()*sizeof(float));
    std::ofstream sourceBytes(root/"source.rgba",std::ios::binary);
    sourceBytes.write(reinterpret_cast<const char*>(raw.pixels.data()),raw.pixels.size());
    if(!sourceFloats || !sourceBytes)return false;
    if(boundary) {
        const auto at=(48u*reference.width+52)*4+1;
        char detail[256];
        // Exact canonical integration: baseline 45 plus two separable tap weights.
        std::snprintf(detail,sizeof(detail),
            "BOUNDARY x=52 y=48 channel=G canonical=%.12g native=%.12g nativeByte=%u\n",
            45.0+(18.0/53)*(625.0/6784),static_cast<double>(values[at])*255,
            reference.pixels[at]);
        report+=detail;
        // Constant response and nine RGB-separated impulses identify weight
        // behavior independently of any real texture content.
        double weightSum=0;
        for(unsigned pattern=1;pattern<=4;++pattern) {
            const auto input=Boundary(pattern);
            IDirect3DTexture9* probe=nullptr;
            const auto result=load(device,input.data(),static_cast<UINT>(input.size()),
                reference.width,reference.height,1,0,D3DFMT_A32B32G32R32F,D3DPOOL_MANAGED,
                filter,0xffffffffu,0,nullptr,nullptr,&probe);
            std::vector<float> response;
            const bool readable=SUCCEEDED(result) && probe &&
                ReadFloatTexture(probe,reference.width,reference.height,response);
            if(probe)probe->Release();
            if(!readable)return false;
            const auto pixel=(48u*reference.width+52)*4;
            if(pattern==1) {
                std::snprintf(detail,sizeof(detail),
                    "CONSTANT input=45 nativeR=%.12g nativeG=%.12g nativeB=%.12g nativeAlpha=%.12g\n",
                    static_cast<double>(response[pixel])*255,
                    static_cast<double>(response[pixel+1])*255,
                    static_cast<double>(response[pixel+2])*255,
                    static_cast<double>(response[pixel+3]));
            } else {
                for(unsigned c=0;c<3;++c)weightSum+=response[pixel+c];
                std::snprintf(detail,sizeof(detail),
                    "KERNEL sourceY=%u sourceXs=42,43,44 weights=%.12g,%.12g,%.12g\n",
                    39+pattern-2,static_cast<double>(response[pixel]),
                    static_cast<double>(response[pixel+1]),static_cast<double>(response[pixel+2]));
            }
            report+=detail;
        }
        std::snprintf(detail,sizeof(detail),"KERNEL_SUM native=%.12g canonical=1\n",weightSum);
        report+=detail;
    }
    std::fputs(report.c_str(),stdout);
    std::ofstream(root/(std::to_string(filter)+".float.report"))<<report;
    std::ofstream out(root/(std::to_string(filter)+".rgba32f"),std::ios::binary);
    out.write(reinterpret_cast<const char*>(values.data()),values.size()*sizeof(float));
    return static_cast<bool>(out);
}
}
// No arguments is the always-available synthetic CTest. File arguments measure
// external resources; zero-difference is required, mismatch exits 2 (not PASS).
// --boundary <directory> reproduces the known issue using only an original BMP.
int wmain(int argc, wchar_t** argv) {
    if (argc!=1 && argc!=3) return 1;
    Native native;
    native.api=Direct3DCreate9(D3D_SDK_VERSION);
    native.window=CreateWindowW(L"STATIC",L"texture preparation",WS_OVERLAPPEDWINDOW,
        0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if (!native.api || !native.window) return 77;
    D3DPRESENT_PARAMETERS params{};
    params.Windowed=TRUE;params.BackBufferWidth=64;params.BackBufferHeight=64;
    params.BackBufferFormat=D3DFMT_A8R8G8B8;params.SwapEffect=D3DSWAPEFFECT_DISCARD;params.hDeviceWindow=native.window;
    params.EnableAutoDepthStencil=TRUE;params.AutoDepthStencilFormat=D3DFMT_D24S8;
    unsigned int controlBefore=0,controlAfter=0;
    _controlfp_s(&controlBefore,0,0);
    wchar_t hardware[8]{};
    GetEnvironmentVariableW(L"MDS_TEXTURE_PROBE_HARDWARE",hardware,8);
    DWORD behavior=hardware[0]==L'1'?D3DCREATE_HARDWARE_VERTEXPROCESSING:
        D3DCREATE_SOFTWARE_VERTEXPROCESSING;
    wchar_t preserve[8]{};
    GetEnvironmentVariableW(L"MDS_TEXTURE_PROBE_PRESERVE",preserve,8);
    if (preserve[0]==L'1') behavior|=D3DCREATE_FPU_PRESERVE;
    if (FAILED(native.api->CreateDevice(0,D3DDEVTYPE_HAL,native.window,
        behavior,&params,&native.device))) return 77;
    _controlfp_s(&controlAfter,0,0);
    native.dll=LoadLibraryW(L"d3dx9_43.dll");
    const auto load=native.dll?reinterpret_cast<Load>(GetProcAddress(native.dll,
        "D3DXCreateTextureFromFileInMemoryEx")):nullptr;
    if (!load) return 77;
    const bool boundary=argc==3 && std::wcscmp(argv[1],L"--boundary")==0;
    auto bytes=boundary?Boundary():Synthetic();
    if (argc==3 && !boundary) {
        std::ifstream stream(std::filesystem::path(argv[1]),std::ios::binary|std::ios::ate);
        if (!stream) return 1;
        const auto size=stream.tellg();
        if(size<=0 || size>16*1024*1024) return 1;
        bytes.resize(static_cast<std::size_t>(size));stream.seekg(0);
        if(!stream.read(reinterpret_cast<char*>(bytes.data()),size))return 1;
    }
    RgbaImage raw;
    if(!DecodeTextureRgba(bytes.data(),bytes.size(),raw))return 1;
    std::uint32_t width=0,height=0;
    if(!NextPowerOfTwoTextureSize(raw.width,4096,width) ||
       !NextPowerOfTwoTextureSize(raw.height,4096,height))return 1;
    RgbaImage candidate;
    if(!PrepareTriangleDitherWrap(raw,width,height,candidate))return 1;
    auto preparer=CreateD3D9TexturePreparer(native.device);
    RgbaImage backendPrepared;
    const auto retained=raw.pixels;
    if(!preparer)return 77;
    if(!preparer->Prepare(raw,width,height,backendPrepared) || raw.pixels!=retained ||
       backendPrepared.width!=width || backendPrepared.height!=height)return 1;
    bool exact=true;
    for (DWORD filter : {0xffffffffu,0x80004u}) {
        IDirect3DTexture9* texture=nullptr;
        const auto hr=load(native.device,bytes.data(),static_cast<UINT>(bytes.size()),
            0xffffffffu,0xffffffffu,1,1024,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,
            filter,0xffffffffu,0,nullptr,nullptr,&texture);
        RgbaImage reference;D3DSURFACE_DESC desc{};
        const bool ready=SUCCEEDED(hr) && texture && ReadTexture(texture,reference,desc);
        if(texture)texture->Release();
        if(!ready)return 1;
        std::size_t differences=0,pixels=0,first=candidate.pixels.size();unsigned maximum=0;
        if(reference.width!=width || reference.height!=height)return 1;
        for(std::size_t i=0;i<candidate.pixels.size();++i)if(candidate.pixels[i]!=reference.pixels[i]) {
            ++differences; first=std::min(first,i);
            maximum=std::max(maximum,static_cast<unsigned>(std::abs(
                static_cast<int>(candidate.pixels[i])-reference.pixels[i])));
        }
        for(std::size_t i=0;i<candidate.pixels.size();i+=4)
            pixels+=!std::equal(candidate.pixels.begin()+i,candidate.pixels.begin()+i+4,reference.pixels.begin()+i);
        exact=exact && !differences;
        if(backendPrepared.pixels!=reference.pixels) {
            std::fputs("BACKEND preparation mismatch\n",stderr);return 1;
        }
        std::fputs("BACKEND preparation RGBA differences=0\n",stdout);
        const auto report=std::string("filter=")+std::to_string(filter)+" status="+
            (differences?"BLOCKED":"PASS")+" raw="+std::to_string(raw.width)+"x"+std::to_string(raw.height)+
            " prepared="+std::to_string(width)+"x"+std::to_string(height)+
            " deviceBehavior="+std::to_string(behavior)+
            " fpuBefore="+std::to_string(controlBefore)+" fpuAfter="+std::to_string(controlAfter)+
            " differentChannels="+std::to_string(differences)+" differentPixels="+std::to_string(pixels)+
            " maxChannelError="+std::to_string(maximum)+" firstX="+(differences?std::to_string((first/4)%width):"none")+
            " firstY="+(differences?std::to_string(first/4/width):"none")+
            " firstChannel="+(differences?std::to_string(first%4):"none")+"\n";
        std::fputs(report.c_str(),stdout);
        if(argc==3) {
            const auto root=std::filesystem::path(argv[2]);std::filesystem::create_directories(root);
            std::ofstream(root/(std::to_string(filter)+".report"))<<report;
            std::ofstream ref(root/(std::to_string(filter)+".rgba"),std::ios::binary);
            ref.write(reinterpret_cast<const char*>(reference.pixels.data()),reference.pixels.size());
            std::ofstream out(root/"candidate.rgba",std::ios::binary);
            out.write(reinterpret_cast<const char*>(candidate.pixels.data()),candidate.pixels.size());
            if(!ref || !out || !FloatDiagnostic(load,native.device,bytes,raw,reference,filter,root,boundary))return 1;
            if(boundary) {
                std::ofstream input(root/"original-boundary.bmp",std::ios::binary);
                input.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
                if(!input)return 1;
            }
        }
    }
    auto device=CreateD3D9Device(native.device);
    if(!device)return 1;
    MaterialTextureCache cache(*device);
    MaterialTextureAsset asset;
    asset.identity="native-preparation-test";
    asset.content={raw,ImageRevision(raw)};
    asset.prepared={backendPrepared,ImageRevision(backendPrepared)};
    asset.usePrepared=true;
    asset.mips=TextureDesc::Mips::GenerateLinear;
    const auto handle=cache.Get(asset),hit=cache.Get(asset);
    if(!handle || !hit || handle.index!=hit.index || cache.Uploads()!=1 || cache.Hits()!=1 ||
       !device->BeginFrame({}) || !device->SetFixedPipeline(HudSpritePipeline()) ||
       !device->BindTexture(0,handle))return 1;
    IDirect3DBaseTexture9* binding=nullptr;
    if(FAILED(native.device->GetTexture(0,&binding)) || !binding)return 1;
    RgbaImage uploaded;D3DSURFACE_DESC uploadedDesc{};
    const bool uploadedMatch=binding->GetType()==D3DRTYPE_TEXTURE &&
        ReadTexture(static_cast<IDirect3DTexture9*>(binding),uploaded,uploadedDesc) &&
        uploaded.pixels==backendPrepared.pixels && (uploadedDesc.Usage&D3DUSAGE_AUTOGENMIPMAP);
    binding->Release();
    if(!uploadedMatch)return 1;
    if(!device->EndFrame() || !device->Present())return 1;
    cache.Invalidate();
    if(!device->PrepareForReset() || device->BindTexture(0,handle) ||
       FAILED(native.device->Reset(&params)) || !device->RestoreAfterReset() ||
       !cache.Get(asset) || cache.Uploads()!=2 || asset.content.image.pixels!=retained)return 1;
    if(!device->BeginFrame({}) || !device->SetFixedPipeline(HudSpritePipeline()) ||
       device->BindTexture(0,handle) || !device->EndFrame() || !device->Present())return 1;
    RgbaImage alpha{2,2,{255,0,0,0,0,255,0,64,0,0,255,128,10,20,30,255}},alphaOutput;
    if(!preparer->Prepare(alpha,2,2,alphaOutput) || alphaOutput.pixels!=alpha.pixels ||
       CreateD3D9TexturePreparer(nullptr))return 1;
    RgbaImage invalid=backendPrepared;
    if(preparer->Prepare({},width,height,invalid) || !invalid.pixels.empty())return 1;
    RgbaImage aliased=raw;
    if(!preparer->Prepare(aliased,width,height,aliased) || aliased.pixels!=backendPrepared.pixels)return 1;
    std::fputs("BACKEND owned upload, reuse, stale-handle rejection, reset/reupload and aliasing: PASS\n",stdout);
    if(argc==3) {
        const auto root=std::filesystem::path(argv[2]);
        std::ofstream report(root/"backend.preparation.report");
        report<<"status=PASS backend=D3D9 method=D3DXLoadSurfaceFromMemory rgbaDifferences=0 "
              <<"rawPreserved=1 uploads="<<cache.Uploads()<<" staleHandleRejected=1 resetReupload=1\n";
        std::ofstream bytes(root/"backend.rgba",std::ios::binary);
        bytes.write(reinterpret_cast<const char*>(backendPrepared.pixels.data()),backendPrepared.pixels.size());
        if(!report || !bytes)return 1;
    }
    return exact?0:2;
}
