#pragma once
namespace mikudancestudio {
class MMDApp;
// Default off. Startup environment: MDS_RHI_SWAPCHAIN_CONTROLLER=1.
bool ApplicationSwapchainEnabled();
bool ApplicationSwapchainCanRender(MMDApp*);
bool PollApplicationSwapchain(MMDApp*);
void ForgetApplicationSwapchain(MMDApp*);
#ifdef MIKUDANCESTUDIO_DIAG
void RunApplicationSwapchainDiagnostic(MMDApp*);
#endif
}
