#include "mikudancestudio/rhi_d3d9.hpp"
#define NOMINMAX
#include <d3d9.h>
#include <vector>

namespace mikudancestudio::rhi {
namespace {
using LoadSurface = HRESULT (WINAPI*)(IDirect3DSurface9*, const void*, const RECT*,
    const void*, D3DFORMAT, UINT, const void*, const RECT*, DWORD, D3DCOLOR);
class LegacyPreparer final : public TexturePreparer {
    IDirect3DDevice9* device_;
    HMODULE library_;
    LoadSurface load_;
public:
    LegacyPreparer(IDirect3DDevice9* device, HMODULE library, LoadSurface load)
        : device_(device), library_(library), load_(load) { device_->AddRef(); }
    ~LegacyPreparer() override { device_->Release(); FreeLibrary(library_); }
    bool Prepare(const RgbaImage& source, std::uint32_t width,
                 std::uint32_t height, RgbaImage& prepared) override {
        if (&source==&prepared) { const auto copy=source; return Prepare(copy,width,height,prepared); }
        prepared={};
        if(!source.width || !source.height || source.width>4096 || source.height>4096 ||
           !width || !height || width>4096 || height>4096 ||
           source.pixels.size()!=static_cast<std::size_t>(source.width)*source.height*4 ||
           FAILED(device_->TestCooperativeLevel())) return false;
        D3DCAPS9 caps{};
        if(FAILED(device_->GetDeviceCaps(&caps)) || width>caps.MaxTextureWidth ||
           height>caps.MaxTextureHeight)return false;
        std::vector<std::uint8_t> bgra(source.pixels.size());
        for(std::size_t i=0;i<bgra.size();i+=4) {
            bgra[i]=source.pixels[i+2];bgra[i+1]=source.pixels[i+1];
            bgra[i+2]=source.pixels[i];bgra[i+3]=source.pixels[i+3];
        }
        IDirect3DTexture9* texture=nullptr;
        // Scratch native texture is never exposed as an RHI handle or borrowed
        // from the host. Normal cache upload owns the final GPU texture.
        if(FAILED(device_->CreateTexture(width,height,1,0,D3DFMT_A8R8G8B8,
            D3DPOOL_MANAGED,&texture,nullptr)))return false;
        IDirect3DSurface9* surface=nullptr;
        const RECT sourceRect{0,0,static_cast<LONG>(source.width),static_cast<LONG>(source.height)};
        const bool loaded=SUCCEEDED(texture->GetSurfaceLevel(0,&surface)) &&
            SUCCEEDED(load_(surface,nullptr,nullptr,bgra.data(),D3DFMT_A8R8G8B8,
                source.width*4,nullptr,&sourceRect,0x80004u,0));
        if(surface)surface->Release();
        D3DLOCKED_RECT lock{};
        bool ready=loaded && SUCCEEDED(texture->LockRect(0,&lock,nullptr,D3DLOCK_READONLY));
        if(ready) {
            prepared.width=width;prepared.height=height;
            prepared.pixels.resize(static_cast<std::size_t>(width)*height*4);
            for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x) {
                const auto* p=static_cast<const std::uint8_t*>(lock.pBits)+y*lock.Pitch+x*4;
                auto* q=prepared.pixels.data()+(static_cast<std::size_t>(y)*width+x)*4;
                q[0]=p[2];q[1]=p[1];q[2]=p[0];q[3]=p[3];
            }
            ready=SUCCEEDED(texture->UnlockRect(0));
        }
        texture->Release();
        if(!ready)prepared={};
        return ready;
    }
};
}
std::unique_ptr<TexturePreparer> CreateD3D9TexturePreparer(IDirect3DDevice9* device) {
    if(!device)return {};
    // Load only the installed system library, never a scene-local DLL.
    const auto library=LoadLibraryExW(L"d3dx9_43.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
    const auto load=library?reinterpret_cast<LoadSurface>(GetProcAddress(library,
        "D3DXLoadSurfaceFromMemory")):nullptr;
    if(!load) { if(library)FreeLibrary(library); return {}; }
    return std::make_unique<LegacyPreparer>(device,library,load);
}
}
