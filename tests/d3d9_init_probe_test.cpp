#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <d3d9.h>
#include <cstdio>

namespace {
IDirect3D9* creatingD3d = nullptr;
HRESULT createWhileCreating = E_FAIL;
LRESULT CALLBACK ProbeWindowProc(HWND window, UINT message,
                                 WPARAM first, LPARAM second) {
    if (message == WM_CREATE && creatingD3d) {
        D3DPRESENT_PARAMETERS parameters{};
        parameters.BackBufferWidth = 1920;
        parameters.BackBufferHeight = 1080;
        parameters.BackBufferFormat = D3DFMT_X8R8G8B8;
        parameters.BackBufferCount = 1;
        parameters.SwapEffect = D3DSWAPEFFECT_COPY;
        parameters.hDeviceWindow = window;
        parameters.Windowed = TRUE;
        parameters.EnableAutoDepthStencil = TRUE;
        parameters.AutoDepthStencilFormat = D3DFMT_D16;
        parameters.Flags = D3DPRESENTFLAG_LOCKABLE_BACKBUFFER;
        parameters.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
        IDirect3DDevice9* device = nullptr;
        createWhileCreating = creatingD3d->CreateDevice(0, D3DDEVTYPE_HAL,
            window, D3DCREATE_SOFTWARE_VERTEXPROCESSING,
            &parameters, &device);
        if (device) device->Release();
    }
    return DefWindowProcW(window, message, first, second);
}
}

int main() {
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) return 2;
    WNDCLASSW windowClass{};
    windowClass.lpfnWndProc = ProbeWindowProc;
    windowClass.hInstance = GetModuleHandleW(nullptr);
    windowClass.lpszClassName = L"D3D9 init probe window";
    RegisterClassW(&windowClass);
    creatingD3d = d3d;
    const HWND window = CreateWindowW(windowClass.lpszClassName,
        L"D3D9 init probe", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64,
        nullptr, nullptr, windowClass.hInstance, nullptr);
    creatingD3d = nullptr;
    if (!window || !d3d) return 2;
    const struct Trial {
        const char* name;
        unsigned width, height;
        D3DFORMAT color, depth;
        bool lockable, enableDepth;
    } trials[] = {
        {"app-final", 1920, 1080, D3DFMT_X8R8G8B8, D3DFMT_D16, true, true},
        {"app-no-lock", 1920, 1080, D3DFMT_X8R8G8B8, D3DFMT_D16, false, true},
        {"app-no-depth", 1920, 1080, D3DFMT_X8R8G8B8, D3DFMT_D16, false, false},
        {"small-depth", 640, 480, D3DFMT_X8R8G8B8, D3DFMT_D16, false, true},
        {"small-no-depth", 640, 480, D3DFMT_X8R8G8B8, D3DFMT_D16, false, false},
        {"minimal", 64, 64, D3DFMT_A8R8G8B8, D3DFMT_D16, false, false},
    };
    D3DADAPTER_IDENTIFIER9 identifier{};
    d3d->GetAdapterIdentifier(0, 0, &identifier);
    std::printf("adapter=%s display=%dx%d\n", identifier.Description,
                GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN));
    std::printf("during-WM_CREATE hr=0x%08X\n",
                static_cast<unsigned>(createWhileCreating));
    for (const auto& trial : trials) {
        const DWORD modes[] = {D3DCREATE_HARDWARE_VERTEXPROCESSING,
                               D3DCREATE_SOFTWARE_VERTEXPROCESSING};
        for (const DWORD vertexProcessing : modes) {
            D3DPRESENT_PARAMETERS parameters{};
            parameters.BackBufferWidth = trial.width;
            parameters.BackBufferHeight = trial.height;
            parameters.BackBufferFormat = trial.color;
            parameters.BackBufferCount = 1;
            parameters.SwapEffect = trial.lockable ? D3DSWAPEFFECT_COPY :
                                      D3DSWAPEFFECT_DISCARD;
            parameters.hDeviceWindow = window;
            parameters.Windowed = TRUE;
            parameters.EnableAutoDepthStencil = trial.enableDepth;
            parameters.AutoDepthStencilFormat = trial.depth;
            parameters.Flags = trial.lockable ?
                D3DPRESENTFLAG_LOCKABLE_BACKBUFFER : 0;
            parameters.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
            IDirect3DDevice9* device = nullptr;
            const HRESULT result = d3d->CreateDevice(0, D3DDEVTYPE_HAL,
                window, vertexProcessing, &parameters, &device);
            std::printf("%s vp=%s hr=0x%08X\n", trial.name,
                vertexProcessing == D3DCREATE_HARDWARE_VERTEXPROCESSING ?
                    "hardware" : "software", static_cast<unsigned>(result));
            if (device) device->Release();
        }
    }
    d3d->Release();
    DestroyWindow(window);
    return 0;
}
