#include <windows.h>
#include <d3d9.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <initializer_list>

namespace {
template<class T> struct Com {
    T* p = nullptr;
    ~Com() { if (p) p->Release(); }
    T* operator->() const { return p; }
};
bool Hr(const char* operation, HRESULT hr) {
    std::printf("%s HRESULT=0x%08lX status=%s\n", operation,
        static_cast<unsigned long>(hr), SUCCEEDED(hr) ? "supported" : "unsupported");
    std::fflush(stdout);
    return SUCCEEDED(hr);
}
void Desc(const char* name, const D3DSURFACE_DESC& d) {
    std::printf("%s format=%u width=%u height=%u type=%u usage=%lu pool=%u msaa=%u quality=%lu\n",
        name, d.Format, d.Width, d.Height, d.Type, d.Usage, d.Pool,
        d.MultiSampleType, d.MultiSampleQuality);
}
}

int main() {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::puts("diagnostic=HAL_SWVP_only; no REF/WARP/9On12 requested; not RTX3090 equivalence");
    DWORD session = 0;
    const BOOL sessionOk = ProcessIdToSessionId(GetCurrentProcessId(), &session);
    std::printf("session_query=%d session=%lu remote=%d screen=%dx%d\n", sessionOk, session,
        GetSystemMetrics(SM_REMOTESESSION), GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN));
    using VersionFn = LONG (WINAPI*)(OSVERSIONINFOW*);
    const auto versionFn = reinterpret_cast<VersionFn>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion"));
    OSVERSIONINFOW os{};
    os.dwOSVersionInfoSize = sizeof(os);
    if (versionFn && versionFn(&os) == 0)
        std::printf("os=%lu.%lu.%lu platform=%lu\n", os.dwMajorVersion, os.dwMinorVersion, os.dwBuildNumber, os.dwPlatformId);
    else { std::puts("FAIL: OS identity unavailable"); return 1; }
    HWND window = CreateWindowW(L"STATIC", L"D3D9 capability diagnostic", WS_OVERLAPPED,
        0, 0, 640, 360, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!window) { std::printf("FAIL: CreateWindow error=%lu\n", GetLastError()); return 1; }
    struct WindowGuard { HWND h; ~WindowGuard() { DestroyWindow(h); } } guard{window};
    Com<IDirect3D9> d3d;
    d3d.p = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d.p) { std::puts("FAIL/unsupported: Direct3DCreate9"); return 1; }
    D3DADAPTER_IDENTIFIER9 adapter{};
    if (!Hr("GetAdapterIdentifier", d3d->GetAdapterIdentifier(0, 0, &adapter))) return 1;
    std::printf("adapter=%s driver=%s device=%s driver_version=%08lX%08lX vendor=%lu device_id=%lu subsystem=%lu revision=%lu whql=%lu guid=",
        adapter.Description, adapter.Driver, adapter.DeviceName,
        static_cast<unsigned long>(adapter.DriverVersion.HighPart), adapter.DriverVersion.LowPart,
        adapter.VendorId, adapter.DeviceId, adapter.SubSysId, adapter.Revision, adapter.WHQLLevel);
    const auto* guid = reinterpret_cast<const unsigned char*>(&adapter.DeviceIdentifier);
    for (unsigned i = 0; i < sizeof(GUID); ++i) std::printf("%02x", guid[i]);
    std::puts("");
    D3DDISPLAYMODE mode{};
    if (!Hr("GetAdapterDisplayMode", d3d->GetAdapterDisplayMode(0, &mode))) return 1;
    std::printf("display=%ux%u refresh=%u format=%u\n", mode.Width, mode.Height, mode.RefreshRate, mode.Format);
    D3DPRESENT_PARAMETERS pp{};
    pp.BackBufferWidth = pp.BackBufferHeight = 128;
    pp.BackBufferFormat = D3DFMT_A8R8G8B8; pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD; pp.hDeviceWindow = window;
    pp.Windowed = TRUE; pp.EnableAutoDepthStencil = TRUE;
    pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    Com<IDirect3DDevice9> device;
    if (!Hr("CreateDevice_HAL_SWVP_snapshot_fixture_noMSAA", d3d->CreateDevice(0, D3DDEVTYPE_HAL,
        window, D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &device.p))) return 1;
    std::printf("presentation backbuffer=%ux%u format=%u count=%u swap=%u windowed=%d depth=%u msaa=%u quality=%lu flags=0x%08lX interval=0x%08u\n",
        pp.BackBufferWidth, pp.BackBufferHeight, pp.BackBufferFormat, pp.BackBufferCount,
        pp.SwapEffect, pp.Windowed, pp.AutoDepthStencilFormat, pp.MultiSampleType,
        pp.MultiSampleQuality, pp.Flags, pp.PresentationInterval);
    D3DDEVICE_CREATION_PARAMETERS creation{};
    bool ok = Hr("GetCreationParameters", device->GetCreationParameters(&creation));
    std::printf("creation adapter=%u device_type=%u behavior=0x%08lX window=%p\n",
        creation.AdapterOrdinal, creation.DeviceType, creation.BehaviorFlags, creation.hFocusWindow);
    D3DCAPS9 caps{};
    if (!Hr("GetDeviceCaps", device->GetDeviceCaps(&caps))) return 1;
    std::printf("caps vs=0x%08lX ps=0x%08lX max_texture=%lux%lu texture_filter=0x%08lX\n",
        caps.VertexShaderVersion, caps.PixelShaderVersion, caps.MaxTextureWidth, caps.MaxTextureHeight, caps.TextureFilterCaps);
    std::printf("caps_bytes=");
    const auto* bytes = reinterpret_cast<const unsigned char*>(&caps);
    for (unsigned i = 0; i < sizeof(caps); ++i) std::printf("%02x", bytes[i]);
    std::puts("");
    ok = (caps.VertexShaderVersion >= D3DVS_VERSION(3, 0) && caps.PixelShaderVersion >= D3DPS_VERSION(3, 0)) && ok;
    for (auto format : {D3DFMT_X8R8G8B8, D3DFMT_A8R8G8B8, D3DFMT_D24S8, D3DFMT_D24X8}) {
        for (auto sample : {D3DMULTISAMPLE_8_SAMPLES, D3DMULTISAMPLE_4_SAMPLES,
                           D3DMULTISAMPLE_2_SAMPLES, D3DMULTISAMPLE_NONMASKABLE, D3DMULTISAMPLE_NONE}) {
            DWORD quality = 0;
            const HRESULT hr = d3d->CheckDeviceMultiSampleType(0, D3DDEVTYPE_HAL, format, TRUE, sample, &quality);
            std::printf("MSAA format=%u sample=%u quality_levels=%lu ", format, sample, quality);
            Hr("CheckDeviceMultiSampleType", hr);
        }
    }
    ok = Hr("R32F_render_target", d3d->CheckDeviceFormat(0, D3DDEVTYPE_HAL, mode.Format,
        D3DUSAGE_RENDERTARGET, D3DRTYPE_TEXTURE, D3DFMT_R32F)) && ok;
    ok = Hr("R32F_filter_query", d3d->CheckDeviceFormat(0, D3DDEVTYPE_HAL, mode.Format,
        D3DUSAGE_QUERY_FILTER, D3DRTYPE_TEXTURE, D3DFMT_R32F)) && ok;
    ok = Hr("R32F_D24X8_match", d3d->CheckDepthStencilMatch(0, D3DDEVTYPE_HAL,
        mode.Format, D3DFMT_R32F, D3DFMT_D24X8)) && ok;
    const UINT width = std::min<DWORD>(2048, caps.MaxTextureWidth);
    const UINT height = std::min<DWORD>(2048, caps.MaxTextureHeight);
    Com<IDirect3DTexture9> texture;
    Com<IDirect3DSurface9> surface, depth, readback;
    if (Hr("CreateTexture_R32F", device->CreateTexture(width, height, 1, D3DUSAGE_RENDERTARGET,
        D3DFMT_R32F, D3DPOOL_DEFAULT, &texture.p, nullptr))) {
        D3DSURFACE_DESC desc{};
        ok = Hr("GetLevelDesc", texture->GetLevelDesc(0, &desc)) && ok;
        Desc("R32F_level0", desc);
        const bool haveSurface = Hr("GetSurfaceLevel", texture->GetSurfaceLevel(0, &surface.p));
        const bool haveDepth = Hr("CreateDepthStencilSurface_D24X8", device->CreateDepthStencilSurface(
            width, height, D3DFMT_D24X8, D3DMULTISAMPLE_NONE, 0, FALSE, &depth.p, nullptr));
        const bool haveReadback = Hr("CreateSystemMem_R32F", device->CreateOffscreenPlainSurface(
            width, height, D3DFMT_R32F, D3DPOOL_SYSTEMMEM, &readback.p, nullptr));
        ok = haveSurface && haveDepth && haveReadback && ok;
        if (haveSurface && haveDepth && haveReadback) {
            ok = Hr("UnbindDepth", device->SetDepthStencilSurface(nullptr)) && ok;
            ok = Hr("BindR32F", device->SetRenderTarget(0, surface.p)) && ok;
            ok = Hr("BindD24X8", device->SetDepthStencilSurface(depth.p)) && ok;
            ok = Hr("ClearR32F", device->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xffffffff, 1.0f, 0)) && ok;
            const bool copied = Hr("GetRenderTargetData_R32F", device->GetRenderTargetData(surface.p, readback.p));
            ok = copied && ok;
            if (copied) {
                D3DLOCKED_RECT locked{};
                if (Hr("LockRect_R32F", readback->LockRect(&locked, nullptr, D3DLOCK_READONLY))) {
                    float value = 0;
                    std::memcpy(&value, locked.pBits, sizeof(value));
                    std::printf("R32F_readback pitch=%d first_float=%.9g expected=1\n", locked.Pitch, value);
                    ok = value == 1.0f && ok;
                    ok = Hr("UnlockRect_R32F", readback->UnlockRect()) && ok;
                } else ok = false;
            }
        }
    } else ok = false;
    std::printf("diagnostic_result=%s; MSAA queries are per-mode evidence, filtering query is not sampled shader proof\n", ok ? "supported" : "FAIL/unsupported");
    return ok ? 0 : 1;
}
