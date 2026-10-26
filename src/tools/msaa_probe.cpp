// ===========================================================================
// --mds-msaa-probe <pmm> <out>  (wave 3 slice winprobe2, Windows)
// ===========================================================================
// Measures where the multisampled back buffer of --mds-frame-dump samples a
// pixel, so the golden2 edge pixels can be matched
// (tests/fixtures/rust/golden2/README.md). The PMM only hosts the device.
//
// A grid of 64x64 cells, 5 px apart from pixel (8, 8): cell (a, b) owns pixel
// (i, j) = (8 + 5a, 8 + 5b) and draws one white quad, 2 px square, on black,
// with its top-left corner at (i - 1 + (a + 0.5) / 32, j - 1 + (b + 0.5) / 32).
// So pixel (i, j) holds the samples right of and below that corner, and the
// corners sweep 2 px around the pixel in steps of 1/32 px, between the
// 1/32 lines. The quads are pre-transformed vertices (D3DFVF_XYZRHW, screen
// coordinates as given) with no depth, stencil, blending, texture, or shader,
// under the app's D3DRS_MULTISAMPLEANTIALIAS. The grid is drawn once with the
// app's D3DRS_MULTISAMPLEMASK and once with each single bit 0..7, and each
// time resolved as DumpFrame (trace_mode.cpp) resolves the back buffer:
// StretchRect into a 640x360 render target without multisampling.
//
// Format, LF line ends:
//   "mds-msaa-probe 1"
//   "device" multisampleType quality colorLevels depthLevels backbufferFormat
//            depthFormat width height multisampleAntialias multisampleMask
//            (the type and quality of the device; the quality levels
//            CheckDeviceMultiSampleType reports for the type, with the back
//            buffer and the depth format; the back buffer size; the two render
//            states as the app left them, the mask in hex)
//   "grid" cells pitch origin step
//   "mask" hex                    (per drawing: the app's mask, then 1 .. 80)
//   "row" b v0 .. v63             (per b: the red channel of pixel (i, j) for
//                                  a = 0..63; the run fails unless green and
//                                  blue are the same)
// =========================================================================//
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>
#include <vector>

#include "mikudancestudio/d3d_wrapper.hpp"
#include "mikudancestudio/mmd_app.hpp"

#include "trace_mode.hpp"

namespace mikudancestudio::tools {
namespace {

constexpr int kCells = 64;
constexpr int kPitch = 5;
constexpr int kOrigin = 8;
constexpr float kStep = 1.0f / 32.0f;
constexpr UINT kWidth = 640; // the frame dump's output size
constexpr UINT kHeight = 360;

struct Vertex {
    float x, y, z, rhw;
    D3DCOLOR color;
};

void Fail(const char* text) {
    const std::string line = std::string("mds-msaa-probe: ") + text + "\n";
    HANDLE error = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written = 0;
    if (error != nullptr && error != INVALID_HANDLE_VALUE)
        WriteFile(error, line.data(), static_cast<DWORD>(line.size()), &written, nullptr);
    OutputDebugStringA(line.c_str());
}

std::vector<Vertex> GridQuads() {
    std::vector<Vertex> vertices;
    vertices.reserve(kCells * kCells * 6);
    for (int b = 0; b < kCells; ++b) {
        for (int a = 0; a < kCells; ++a) {
            const float x0 = static_cast<float>(kOrigin + kPitch * a - 1) + (a + 0.5f) * kStep;
            const float y0 = static_cast<float>(kOrigin + kPitch * b - 1) + (b + 0.5f) * kStep;
            const float x1 = x0 + 2.0f;
            const float y1 = y0 + 2.0f;
            const Vertex quad[6] = {
                {x0, y0, 0.5f, 1.0f, 0xFFFFFFFF}, {x1, y0, 0.5f, 1.0f, 0xFFFFFFFF},
                {x0, y1, 0.5f, 1.0f, 0xFFFFFFFF}, {x1, y0, 0.5f, 1.0f, 0xFFFFFFFF},
                {x1, y1, 0.5f, 1.0f, 0xFFFFFFFF}, {x0, y1, 0.5f, 1.0f, 0xFFFFFFFF}};
            vertices.insert(vertices.end(), quad, quad + 6);
        }
    }
    return vertices;
}

void FlatColorStates(IDirect3DDevice9* device) {
    device->SetVertexShader(nullptr);
    device->SetPixelShader(nullptr);
    device->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    const DWORD states[][2] = {{D3DRS_ZENABLE, FALSE},          {D3DRS_ZWRITEENABLE, FALSE},
                               {D3DRS_STENCILENABLE, FALSE},    {D3DRS_ALPHABLENDENABLE, FALSE},
                               {D3DRS_ALPHATESTENABLE, FALSE},  {D3DRS_CULLMODE, D3DCULL_NONE},
                               {D3DRS_FILLMODE, D3DFILL_SOLID}, {D3DRS_FOGENABLE, FALSE},
                               {D3DRS_LIGHTING, FALSE},         {D3DRS_SCISSORTESTENABLE, FALSE},
                               {D3DRS_COLORWRITEENABLE, 0xF},   {D3DRS_SRGBWRITEENABLE, FALSE},
                               {D3DRS_DITHERENABLE, FALSE}};
    for (const auto& state : states)
        device->SetRenderState(static_cast<D3DRENDERSTATETYPE>(state[0]), state[1]);
}

// Draws the grid under `mask` and appends its rows.
bool DrawGrid(IDirect3DDevice9* device, IDirect3DSurface9* backbuffer, D3DFORMAT format,
              const std::vector<Vertex>& quads, DWORD mask, std::string& text) {
    device->SetRenderState(D3DRS_MULTISAMPLEMASK, mask);
    device->Clear(0, nullptr, D3DCLEAR_TARGET, 0xFF000000, 1.0f, 0);
    if (FAILED(device->BeginScene()))
        return false;
    HRESULT hr = device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(quads.size() / 3),
                                         quads.data(), sizeof(Vertex));
    device->EndScene();
    if (FAILED(hr))
        return false;

    IDirect3DSurface9* resolved = nullptr;
    IDirect3DSurface9* system = nullptr;
    if (FAILED(device->CreateRenderTarget(kWidth, kHeight, format, D3DMULTISAMPLE_NONE, 0, FALSE,
                                          &resolved, nullptr)))
        return false;
    RECT rect{0, 0, static_cast<LONG>(kWidth), static_cast<LONG>(kHeight)};
    hr = device->StretchRect(backbuffer, &rect, resolved, &rect, D3DTEXF_LINEAR);
    if (FAILED(hr))
        hr = device->StretchRect(backbuffer, &rect, resolved, &rect, D3DTEXF_NONE);
    if (SUCCEEDED(hr))
        hr = device->CreateOffscreenPlainSurface(kWidth, kHeight, format, D3DPOOL_SYSTEMMEM,
                                                 &system, nullptr);
    if (SUCCEEDED(hr))
        hr = device->GetRenderTargetData(resolved, system);
    D3DLOCKED_RECT locked{};
    if (SUCCEEDED(hr))
        hr = system->LockRect(&locked, nullptr, D3DLOCK_READONLY);
    bool ok = SUCCEEDED(hr);
    if (ok) {
        char word[32];
        std::snprintf(word, sizeof word, "mask %lx\n", static_cast<unsigned long>(mask));
        text += word;
        const auto* bits = static_cast<const unsigned char*>(locked.pBits);
        for (int b = 0; ok && b < kCells; ++b) {
            std::snprintf(word, sizeof word, "row %d", b);
            text += word;
            for (int a = 0; a < kCells; ++a) {
                // A8R8G8B8 and X8R8G8B8 are B, G, R, A in memory.
                const unsigned char* p =
                    bits + (kOrigin + kPitch * b) * locked.Pitch + (kOrigin + kPitch * a) * 4;
                ok = ok && p[0] == p[1] && p[1] == p[2];
                std::snprintf(word, sizeof word, " %u", p[2]);
                text += word;
            }
            text += '\n';
        }
        system->UnlockRect();
        if (!ok)
            Fail("a resolved pixel is not gray");
    }
    if (system != nullptr)
        system->Release();
    resolved->Release();
    return ok;
}
} // namespace

int RunMsaaProbe(MMDApp* app, const TraceRequest& request) {
    D3DRenderer* r = app->Renderer();
    if (r == nullptr || r->device == nullptr)
        return 1;
    IDirect3DDevice9* device = r->device;
    const D3DPRESENT_PARAMETERS& pp = r->presentParameters;
    const D3DFORMAT format = r->backbufferFormat;
    if (r->multisampleAvailable == 0 || (format != D3DFMT_A8R8G8B8 && format != D3DFMT_X8R8G8B8)) {
        Fail("needs a multisampled A8R8G8B8 or X8R8G8B8 back buffer");
        return 1;
    }
    IDirect3DSurface9* backbuffer = nullptr;
    if (FAILED(device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &backbuffer)))
        return 1;
    D3DSURFACE_DESC desc{};
    backbuffer->GetDesc(&desc);
    DWORD colorLevels = 0;
    DWORD depthLevels = 0;
    IDirect3D9* d3d = nullptr;
    if (SUCCEEDED(device->GetDirect3D(&d3d))) {
        d3d->CheckDeviceMultiSampleType(0, D3DDEVTYPE_HAL, format, TRUE, pp.MultiSampleType,
                                        &colorLevels);
        d3d->CheckDeviceMultiSampleType(0, D3DDEVTYPE_HAL, pp.AutoDepthStencilFormat, TRUE,
                                        pp.MultiSampleType, &depthLevels);
        d3d->Release();
    }
    DWORD antialias = 0;
    DWORD mask = 0;
    device->GetRenderState(D3DRS_MULTISAMPLEANTIALIAS, &antialias);
    device->GetRenderState(D3DRS_MULTISAMPLEMASK, &mask);

    char line[256];
    std::snprintf(
        line, sizeof line,
        "mds-msaa-probe 1\ndevice %d %lu %lu %lu %d %d %u %u %lu %lx\ngrid %d %d %d %.9g\n",
        static_cast<int>(desc.MultiSampleType), desc.MultiSampleQuality, colorLevels, depthLevels,
        static_cast<int>(format), static_cast<int>(pp.AutoDepthStencilFormat), desc.Width,
        desc.Height, antialias, mask, kCells, kPitch, kOrigin, kStep);
    std::string text = line;

    bool ok = desc.Width >= kWidth && desc.Height >= kHeight &&
              SUCCEEDED(device->SetRenderTarget(0, backbuffer));
    if (ok) {
        const D3DVIEWPORT9 viewport{0, 0, kWidth, kHeight, 0.0f, 1.0f};
        device->SetViewport(&viewport);
        FlatColorStates(device);
        const std::vector<Vertex> quads = GridQuads();
        ok = DrawGrid(device, backbuffer, format, quads, mask, text);
        for (int bit = 0; ok && bit < 8; ++bit)
            ok = DrawGrid(device, backbuffer, format, quads, 1u << bit, text);
        device->SetRenderState(D3DRS_MULTISAMPLEMASK, mask);
    }
    backbuffer->Release();
    if (!ok) {
        Fail("draw or read-back failed");
        return 1;
    }

    const std::wstring temp = request.out + L".tmp";
    {
        std::ofstream file(std::filesystem::path(temp), std::ios::binary | std::ios::trunc);
        file << text;
        file.flush();
        ok = file.good();
    }
    if (!ok || !MoveFileExW(temp.c_str(), request.out.c_str(),
                            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(temp.c_str());
        return 1;
    }
    return 0;
}
} // namespace mikudancestudio::tools
