#pragma once
#include "mikudancestudio/rhi_swapchain.hpp"
#include "mikudancestudio/rhi_image.hpp"
#include <string>
struct ID3D11Texture2D;
namespace mikudancestudio::rhi {
enum class D3D11Driver { Hardware, Warp };
enum class D3D11CreationStage { Parameters, NativeDevice, Shaders, Targets, Ready };
// Destruction order: swapchain before device. Cache owners must die first.
struct D3D11Bundle {
    std::unique_ptr<Device> device;
    std::unique_ptr<Swapchain> swapchain;
    std::int64_t creationError=0;
    D3D11CreationStage stage=D3D11CreationStage::Parameters;
    std::string adapterName;
    std::uint32_t vendorId=0, deviceId=0;
    explicit operator bool() const { return device && swapchain; }
};
#ifdef MIKUDANCESTUDIO_RHI_D3D11
D3D11Bundle CreateD3D11Device(const SwapchainDesc&, D3D11Driver);
// Diagnostic readback, after EndFrame and before Present; single-sample RGBA8 only.
bool ReadD3D11Swapchain(Device&, RgbaImage&);
// Diagnostic reference: caller must Release before ResizeBuffers can succeed.
bool AcquireD3D11Backbuffer(Device&, ID3D11Texture2D**);
#endif
}
