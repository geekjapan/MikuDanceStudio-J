#pragma once
#include "mikudancestudio/rhi_d3d11.hpp"
namespace mikudancestudio::rhi {
D3D11Bundle CreateD3D11WCandidateDevice(const SwapchainDesc&,D3D11Driver,unsigned policy);
D3D11Bundle CreateD3D11LightingCandidateDevice(const SwapchainDesc&,D3D11Driver);
D3D11Bundle CreateD3D11NormalCandidateDevice(const SwapchainDesc&,D3D11Driver);
D3D11Bundle CreateD3D11ViewportCenterCandidateDevice(const SwapchainDesc&,D3D11Driver);
D3D11Bundle CreateD3D11FusedXYCandidateDevice(const SwapchainDesc&,D3D11Driver);
ModelReplayResult ReplayD3D11WCandidatePrefix(Device&,const ModelReplayStream&,std::size_t drawCount,RgbaImage&,D3D11ReplayTiming* timing=nullptr);
}
