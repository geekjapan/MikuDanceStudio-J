#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include "mikudancestudio/rhi_d3d9.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr unsigned kWidth = 64;
constexpr unsigned kHeight = 64;
struct Vertex {
    float position[3];
    DWORD color;
};
static_assert(sizeof(Vertex) == 16);
struct LineVertex {
    float x, y, z, reciprocalW;
    DWORD color;
};
static_assert(sizeof(LineVertex) == 20);
constexpr std::array<Vertex, 3> kVertices{{
    {{-0.75f, -0.75f, 0.5f}, 0xffff0000},
    {{ 0.75f, -0.75f, 0.5f}, 0xffff0000},
    {{ 0.0f,   0.75f, 0.5f}, 0xffff0000},
}};
constexpr std::array<std::uint16_t, 3> kIndices{{0, 1, 2}};
constexpr std::array<LineVertex, 8> kSelectionLines{{
    {16, 12, 0, 1, 0xffffffff}, {16, 44, 0, 1, 0xffffffff},
    {16, 44, 0, 1, 0xffffffff}, {48, 44, 0, 1, 0xffffffff},
    {48, 44, 0, 1, 0xffffffff}, {48, 12, 0, 1, 0xffffffff},
    {48, 12, 0, 1, 0xffffffff}, {16, 12, 0, 1, 0xffffffff},
}};

struct CapturedState {
    unsigned width = 0, height = 0, format = 0;
    unsigned viewX = 0, viewY = 0, viewWidth = 0, viewHeight = 0;
    float minZ = 0, maxZ = 1;
    unsigned fvf = 0, offset = 0, stride = 0, texture = 0;
    unsigned lighting = 0, cull = 0, depth = 0, depthWrite = 0;
    unsigned depthFunc = 0;
    unsigned blend = 0, source = 0, destination = 0;
    unsigned colorOp = 0, colorArg = 0, colorArg2 = 0;
    unsigned alphaOp = 0, alphaArg = 0, alphaArg2 = 0;
    unsigned vertexShader = 0, pixelShader = 0;
    unsigned stencil = 0, stencilFunc = 0, stencilRef = 0, stencilMask = 0;
    unsigned stencilFail = 0, stencilZFail = 0, stencilPass = 0;
    unsigned stencilWriteMask = 0;
    unsigned alphaTest = 0, alphaFunc = 0, alphaRef = 0;
    unsigned depthBias = 0, slopeDepthBias = 0;
    unsigned stage1ColorOp = 0, stage1AlphaOp = 0;
    unsigned scissor = 0, colorWrite = 0, samples = 0, sampleQuality = 0;
    unsigned depthFormat = 0, depthSamples = 0, depthQuality = 0;
};

bool ReadCapturedState(const char* path, CapturedState& state) {
    std::ifstream input(path);
    const std::string text(std::istreambuf_iterator<char>{input}, {});
    if (!input && text.empty()) return false;
    const int fields = std::sscanf(text.c_str(),
        "target=%ux%u format=%u viewport=%u,%u,%u,%u minZ=%f maxZ=%f "
        "fvf=%u offset=%u stride=%u texture=%u "
        "lighting=%u cull=%u depth=%u depthWrite=%u depthFunc=%u "
        "blend=%u source=%u destination=%u colorOp=%u colorArg=%u "
        "colorArg2=%u alphaOp=%u alphaArg=%u alphaArg2=%u "
        "vertexShader=%u pixelShader=%u scissor=%u colorWrite=%u "
        "stencil=%u stencilFunc=%u stencilRef=%u stencilMask=%u "
        "stencilFail=%u stencilZFail=%u stencilPass=%u stencilWriteMask=%u "
        "alphaTest=%u alphaFunc=%u alphaRef=%u "
        "depthBias=%u slopeDepthBias=%u "
        "stage1ColorOp=%u stage1AlphaOp=%u "
        "samples=%u sampleQuality=%u depthFormat=%u depthSamples=%u depthQuality=%u",
        &state.width, &state.height, &state.format,
        &state.viewX, &state.viewY, &state.viewWidth, &state.viewHeight,
        &state.minZ, &state.maxZ,
        &state.fvf, &state.offset, &state.stride, &state.texture,
        &state.lighting, &state.cull, &state.depth, &state.depthWrite,
        &state.depthFunc,
        &state.blend, &state.source, &state.destination, &state.colorOp,
        &state.colorArg, &state.colorArg2,
        &state.alphaOp, &state.alphaArg, &state.alphaArg2,
        &state.vertexShader, &state.pixelShader,
        &state.scissor, &state.colorWrite,
        &state.stencil, &state.stencilFunc, &state.stencilRef,
        &state.stencilMask, &state.stencilFail, &state.stencilZFail,
        &state.stencilPass, &state.stencilWriteMask,
        &state.alphaTest, &state.alphaFunc, &state.alphaRef,
        &state.depthBias, &state.slopeDepthBias,
        &state.stage1ColorOp, &state.stage1AlphaOp,
        &state.samples,
        &state.sampleQuality, &state.depthFormat, &state.depthSamples,
        &state.depthQuality);
    return fields == 51 && state.width > 0 && state.height > 0 &&
        state.width <= 4096 && state.height <= 4096 &&
        state.format == D3DFMT_A8R8G8B8 &&
        state.samples <= D3DMULTISAMPLE_16_SAMPLES &&
        state.depthSamples == state.samples &&
        state.depthQuality == state.sampleQuality &&
        state.viewWidth > 0 && state.viewHeight > 0 &&
        state.viewX < state.width && state.viewY < state.height &&
        // The application's viewport can extend a few pixels past the
        // resized render target. DX9 clips it; preserve the captured state.
        state.viewWidth <= 4096 && state.viewHeight <= 4096 &&
        state.viewWidth <= state.width - state.viewX + 16 &&
        state.viewHeight <= state.height - state.viewY + 16 &&
        state.fvf == (D3DFVF_XYZRHW | D3DFVF_DIFFUSE) &&
        state.offset == 0 && state.stride == sizeof(LineVertex) &&
        state.texture == 0 && state.vertexShader == 0 &&
        state.pixelShader == 0;
}

bool ApplyCapturedState(IDirect3DDevice9* device, const CapturedState& state) {
    const D3DVIEWPORT9 viewport{state.viewX, state.viewY,
        state.viewWidth, state.viewHeight, state.minZ, state.maxZ};
    return SUCCEEDED(device->SetViewport(&viewport)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_LIGHTING, state.lighting)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_CULLMODE, state.cull)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ZENABLE, state.depth)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ZWRITEENABLE, state.depthWrite)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ZFUNC, state.depthFunc)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ALPHABLENDENABLE, state.blend)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_SRCBLEND, state.source)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_DESTBLEND, state.destination)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_SCISSORTESTENABLE, state.scissor)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_COLORWRITEENABLE, state.colorWrite)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILENABLE, state.stencil)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILFUNC, state.stencilFunc)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILREF, state.stencilRef)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILMASK, state.stencilMask)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILFAIL, state.stencilFail)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILZFAIL, state.stencilZFail)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILPASS, state.stencilPass)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_STENCILWRITEMASK, state.stencilWriteMask)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ALPHATESTENABLE, state.alphaTest)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ALPHAFUNC, state.alphaFunc)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ALPHAREF, state.alphaRef)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_DEPTHBIAS, state.depthBias)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_SLOPESCALEDEPTHBIAS,
                                         state.slopeDepthBias)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLOROP, state.colorOp)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLORARG1, state.colorArg)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLORARG2, state.colorArg2)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAOP, state.alphaOp)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAARG1, state.alphaArg)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAARG2, state.alphaArg2)) &&
        SUCCEEDED(device->SetTextureStageState(1, D3DTSS_COLOROP,
                                              state.stage1ColorOp)) &&
        SUCCEEDED(device->SetTextureStageState(1, D3DTSS_ALPHAOP,
                                              state.stage1AlphaOp));
}

bool Prepare(IDirect3DDevice9* device, IDirect3DSurface9* target,
             unsigned width, unsigned height) {
    D3DMATRIX identity{};
    identity.m[0][0] = identity.m[1][1] =
        identity.m[2][2] = identity.m[3][3] = 1.0f;
    D3DVIEWPORT9 viewport{0, 0, width, height, 0.0f, 1.0f};
    return SUCCEEDED(device->SetRenderTarget(0, target)) &&
        SUCCEEDED(device->SetViewport(&viewport)) &&
        SUCCEEDED(device->SetTransform(D3DTS_WORLD, &identity)) &&
        SUCCEEDED(device->SetTransform(D3DTS_VIEW, &identity)) &&
        SUCCEEDED(device->SetTransform(D3DTS_PROJECTION, &identity)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ZENABLE, FALSE)) &&
        SUCCEEDED(device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE)) &&
        SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->SetVertexShader(nullptr)) &&
        SUCCEEDED(device->SetPixelShader(nullptr)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_COLOROP, D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_COLORARG1, D3DTA_DIFFUSE));
}

bool ReadPixels(IDirect3DDevice9* device, IDirect3DSurface9* target,
                IDirect3DSurface9* staging, unsigned width, unsigned height,
                std::vector<DWORD>& pixels,
                IDirect3DSurface9* resolved = nullptr) {
    if (resolved && FAILED(device->StretchRect(target, nullptr, resolved,
            nullptr, D3DTEXF_NONE))) return false;
    if (FAILED(device->GetRenderTargetData(
            resolved ? resolved : target, staging))) return false;
    D3DLOCKED_RECT locked{};
    if (FAILED(staging->LockRect(&locked, nullptr, D3DLOCK_READONLY)))
        return false;
    pixels.resize(static_cast<std::size_t>(width) * height);
    for (unsigned row = 0; row < height; ++row)
        std::memcpy(pixels.data() + static_cast<std::size_t>(row) * width,
            static_cast<const unsigned char*>(locked.pBits) +
                row * locked.Pitch, width * sizeof(DWORD));
    return SUCCEEDED(staging->UnlockRect());
}

bool CheckLineState(IDirect3DDevice9* device) {
    struct ExpectedState {
        D3DRENDERSTATETYPE state;
        DWORD value;
    };
    const ExpectedState expected[] = {
        {D3DRS_LIGHTING, FALSE},
        {D3DRS_CULLMODE, D3DCULL_NONE},
        {D3DRS_ZENABLE, FALSE},
        {D3DRS_ZWRITEENABLE, FALSE},
        {D3DRS_ALPHABLENDENABLE, TRUE},
        {D3DRS_SRCBLEND, D3DBLEND_SRCALPHA},
        {D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA},
    };
    DWORD actual = 0;
    for (const auto& state : expected)
        if (FAILED(device->GetRenderState(state.state, &actual)) ||
            actual != state.value) return false;
    if (FAILED(device->GetFVF(&actual)) ||
        actual != (D3DFVF_XYZRHW | D3DFVF_DIFFUSE) ||
        FAILED(device->GetTextureStageState(0, D3DTSS_COLOROP, &actual)) ||
        actual != D3DTOP_SELECTARG1 ||
        FAILED(device->GetTextureStageState(0, D3DTSS_COLORARG1, &actual)) ||
        actual != D3DTA_DIFFUSE) return false;
    IDirect3DBaseTexture9* texture = nullptr;
    const HRESULT textureStatus = device->GetTexture(0, &texture);
    if (texture) texture->Release();
    return SUCCEEDED(textureStatus) && texture == nullptr;
}

bool CheckCapturedState(IDirect3DDevice9* device,
                        const CapturedState& state) {
    const std::array<std::pair<D3DRENDERSTATETYPE, DWORD>, 23> renderStates{{
        {D3DRS_LIGHTING, state.lighting}, {D3DRS_CULLMODE, state.cull},
        {D3DRS_ZENABLE, state.depth}, {D3DRS_ZWRITEENABLE, state.depthWrite},
        {D3DRS_ZFUNC, state.depthFunc}, {D3DRS_ALPHABLENDENABLE, state.blend},
        {D3DRS_SRCBLEND, state.source}, {D3DRS_DESTBLEND, state.destination},
        {D3DRS_SCISSORTESTENABLE, state.scissor},
        {D3DRS_COLORWRITEENABLE, state.colorWrite},
        {D3DRS_STENCILENABLE, state.stencil},
        {D3DRS_STENCILFUNC, state.stencilFunc},
        {D3DRS_STENCILREF, state.stencilRef},
        {D3DRS_STENCILMASK, state.stencilMask},
        {D3DRS_STENCILFAIL, state.stencilFail},
        {D3DRS_STENCILZFAIL, state.stencilZFail},
        {D3DRS_STENCILPASS, state.stencilPass},
        {D3DRS_STENCILWRITEMASK, state.stencilWriteMask},
        {D3DRS_ALPHATESTENABLE, state.alphaTest},
        {D3DRS_ALPHAFUNC, state.alphaFunc},
        {D3DRS_ALPHAREF, state.alphaRef},
        {D3DRS_DEPTHBIAS, state.depthBias},
        {D3DRS_SLOPESCALEDEPTHBIAS, state.slopeDepthBias},
    }};
    const std::array<std::pair<D3DTEXTURESTAGESTATETYPE, DWORD>, 6> stages{{
        {D3DTSS_COLOROP, state.colorOp}, {D3DTSS_COLORARG1, state.colorArg},
        {D3DTSS_COLORARG2, state.colorArg2},
        {D3DTSS_ALPHAOP, state.alphaOp}, {D3DTSS_ALPHAARG1, state.alphaArg},
        {D3DTSS_ALPHAARG2, state.alphaArg2},
    }};
    DWORD actual = 0;
    for (const auto& item : renderStates)
        if (FAILED(device->GetRenderState(item.first, &actual)) ||
            actual != item.second) {
            std::fprintf(stderr, "render state %u expected=%lu actual=%lu\n",
                item.first, item.second, actual);
            return false;
        }
    for (const auto& item : stages)
        if (FAILED(device->GetTextureStageState(0, item.first, &actual)) ||
            actual != item.second) {
            std::fprintf(stderr, "texture stage %u expected=%lu actual=%lu\n",
                item.first, item.second, actual);
            return false;
        }
    if (FAILED(device->GetTextureStageState(1, D3DTSS_COLOROP, &actual)) ||
        actual != state.stage1ColorOp ||
        FAILED(device->GetTextureStageState(1, D3DTSS_ALPHAOP, &actual)) ||
        actual != state.stage1AlphaOp) return false;
    if (FAILED(device->GetFVF(&actual)) || actual != state.fvf) return false;
    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.X != state.viewX || viewport.Y != state.viewY ||
        viewport.Width != state.viewWidth ||
        viewport.Height != state.viewHeight ||
        viewport.MinZ != state.minZ || viewport.MaxZ != state.maxZ) return false;
    IDirect3DBaseTexture9* texture = nullptr;
    IDirect3DVertexShader9* vertexShader = nullptr;
    IDirect3DPixelShader9* pixelShader = nullptr;
    const bool valid = SUCCEEDED(device->GetTexture(0, &texture)) &&
        SUCCEEDED(device->GetVertexShader(&vertexShader)) &&
        SUCCEEDED(device->GetPixelShader(&pixelShader)) &&
        !texture && !vertexShader && !pixelShader;
    if (texture) texture->Release();
    if (vertexShader) vertexShader->Release();
    if (pixelShader) pixelShader->Release();
    return valid;
}

bool DrawLegacy(IDirect3DDevice9* device) {
    IDirect3DVertexBuffer9* vertices = nullptr;
    IDirect3DIndexBuffer9* indices = nullptr;
    bool valid = SUCCEEDED(device->CreateVertexBuffer(sizeof(kVertices),
        D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &vertices, nullptr)) &&
        SUCCEEDED(device->CreateIndexBuffer(sizeof(kIndices),
            D3DUSAGE_WRITEONLY, D3DFMT_INDEX16, D3DPOOL_MANAGED,
            &indices, nullptr));
    void* mapped = nullptr;
    if (valid) {
        valid = SUCCEEDED(vertices->Lock(0, 0, &mapped, 0));
        if (valid) {
            std::memcpy(mapped, kVertices.data(), sizeof(kVertices));
            valid = SUCCEEDED(vertices->Unlock());
        }
    }
    if (valid) {
        valid = SUCCEEDED(indices->Lock(0, 0, &mapped, 0));
        if (valid) {
            std::memcpy(mapped, kIndices.data(), sizeof(kIndices));
            valid = SUCCEEDED(indices->Unlock());
        }
    }
    if (valid) {
        valid = SUCCEEDED(device->Clear(0, nullptr,
                D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xff000000, 1.0f, 0)) &&
            SUCCEEDED(device->BeginScene());
        if (valid) {
            valid = SUCCEEDED(device->SetStreamSource(0, vertices, 0,
                    sizeof(Vertex))) &&
                SUCCEEDED(device->SetIndices(indices)) &&
                SUCCEEDED(device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_LIGHTING, FALSE)) &&
                SUCCEEDED(device->DrawIndexedPrimitive(
                    D3DPT_TRIANGLELIST, 0, 0, 3, 0, 1));
            valid = SUCCEEDED(device->EndScene()) && valid;
        }
    }
    if (indices) indices->Release();
    if (vertices) vertices->Release();
    return valid;
}

bool DrawLegacyLines(IDirect3DDevice9* device,
                     const std::array<LineVertex, 8>& lines,
                     const CapturedState* captured = nullptr,
                     float clearDepth = 1.0f) {
    IDirect3DVertexBuffer9* vertices = nullptr;
    if (FAILED(device->CreateVertexBuffer(sizeof(lines),
            D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &vertices, nullptr)))
        return false;
    void* mapped = nullptr;
    bool valid = SUCCEEDED(vertices->Lock(0, 0, &mapped, 0));
    if (valid) {
        std::memcpy(mapped, lines.data(), sizeof(lines));
        valid = SUCCEEDED(vertices->Unlock());
    }
    if (valid) {
        valid = SUCCEEDED(device->Clear(0, nullptr,
                D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xff000000, clearDepth, 0)) &&
            SUCCEEDED(device->BeginScene());
        if (valid) {
            valid = SUCCEEDED(device->SetTexture(0, nullptr)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_LIGHTING, FALSE)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_ZENABLE, FALSE)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_SRCBLEND,
                    D3DBLEND_SRCALPHA)) &&
                SUCCEEDED(device->SetRenderState(D3DRS_DESTBLEND,
                    D3DBLEND_INVSRCALPHA)) &&
                SUCCEEDED(device->SetTextureStageState(
                    0, D3DTSS_COLOROP, D3DTOP_SELECTARG1)) &&
                SUCCEEDED(device->SetTextureStageState(
                    0, D3DTSS_COLORARG1, D3DTA_DIFFUSE)) &&
                SUCCEEDED(device->SetTextureStageState(
                    0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1)) &&
                SUCCEEDED(device->SetTextureStageState(
                    0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE)) &&
                SUCCEEDED(device->SetStreamSource(0, vertices, 0,
                    sizeof(LineVertex))) &&
                SUCCEEDED(device->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE)) &&
                (!captured || ApplyCapturedState(device, *captured)) &&
                SUCCEEDED(device->DrawPrimitive(D3DPT_LINELIST, 0, 4));
            valid = SUCCEEDED(device->EndScene()) && valid;
        }
    }
    vertices->Release();
    return valid;
}
}

int main(int argc, char** argv) {
    if (argc > 3) return 2;
    CapturedState capturedState{};
    if (argc == 3 && !ReadCapturedState(argv[2], capturedState)) {
        std::fprintf(stderr, "invalid or unsupported live selection state\n");
        return 2;
    }
    auto lines = kSelectionLines;
    if (argc >= 2) {
        std::ifstream captured(argv[1], std::ios::binary);
        if (!captured.read(reinterpret_cast<char*>(lines.data()),
                static_cast<std::streamsize>(sizeof(lines))) ||
            captured.peek() != std::char_traits<char>::eof()) {
            std::fprintf(stderr, "line capture must contain exactly %zu bytes\n",
                         sizeof(lines));
            return 2;
        }
    }
    unsigned width = kWidth, height = kHeight;
    if (argc >= 2) {
        for (const auto& line : lines) {
            if (!std::isfinite(line.x) || !std::isfinite(line.y) ||
                line.x < 0 || line.y < 0 || line.x > 4094 ||
                line.y > 4094) return 2;
            width = (std::max)(width,
                static_cast<unsigned>(std::ceil(line.x)) + 2);
            height = (std::max)(height,
                static_cast<unsigned>(std::ceil(line.y)) + 2);
        }
    }
    if (argc == 3) {
        width = capturedState.width;
        height = capturedState.height;
    }
    IDirect3D9* context = Direct3DCreate9(D3D_SDK_VERSION);
    if (!context) return 77;
    const HWND window = CreateWindowExW(0, L"STATIC", L"RHI parity",
        WS_OVERLAPPEDWINDOW, 0, 0, width, height,
        nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!window) { context->Release(); return 77; }
    D3DPRESENT_PARAMETERS parameters{};
    parameters.BackBufferWidth = width;
    parameters.BackBufferHeight = height;
    parameters.BackBufferFormat = D3DFMT_A8R8G8B8;
    parameters.SwapEffect = D3DSWAPEFFECT_DISCARD;
    parameters.Windowed = TRUE;
    parameters.hDeviceWindow = window;
    parameters.EnableAutoDepthStencil = TRUE;
    parameters.AutoDepthStencilFormat = D3DFMT_D16;
    IDirect3DDevice9* native = nullptr;
    if (FAILED(context->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL,
            window, D3DCREATE_SOFTWARE_VERTEXPROCESSING,
            &parameters, &native))) {
        DestroyWindow(window);
        context->Release();
        return 77;
    }
    IDirect3DSurface9* target = nullptr;
    IDirect3DSurface9* staging = nullptr;
    bool valid = SUCCEEDED(native->CreateRenderTarget(width, height,
        D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE,
        &target, nullptr)) &&
        SUCCEEDED(native->CreateOffscreenPlainSurface(width, height,
            D3DFMT_A8R8G8B8, D3DPOOL_SYSTEMMEM, &staging, nullptr));
    std::vector<DWORD> legacy, adapted;
    if (valid) valid = Prepare(native, target, width, height) &&
        DrawLegacy(native) &&
        ReadPixels(native, target, staging, width, height, legacy);
    if (valid) {
        auto device = mikudancestudio::rhi::CreateD3D9Device(native);
        using namespace mikudancestudio::rhi;
        const auto vertex = device->CreateBuffer(
            {BufferUsage::Vertex, sizeof(kVertices)}, kVertices.data());
        const auto index = device->CreateBuffer(
            {BufferUsage::Index, sizeof(kIndices)}, kIndices.data());
        valid = vertex && index && Prepare(native, target, width, height) &&
            device->BeginFrame({0, 0, 0, 1}) &&
            device->DrawIndexed(device->Record(IndexedDraw{vertex, index, 0, 3, 3})) &&
            device->EndFrame() &&
            ReadPixels(native, target, staging, width, height, adapted) &&
            device->Present();
    }
    if (valid) {
        unsigned differences = 0;
        for (std::size_t pixel = 0; pixel < legacy.size(); ++pixel)
            if (legacy[pixel] != adapted[pixel]) ++differences;
        const auto center = height / 2 * width + width / 2;
        valid = legacy.size() == static_cast<std::size_t>(width) * height &&
            differences == 0 &&
            (legacy[center] & 0x00ffffff) == 0x00ff0000;
        std::printf("rhi_d3d9_parity pixels=%zu differences=%u "
                    "legacy_center=%08x adapted_center=%08x\n",
            legacy.size(), differences, legacy[center], adapted[center]);
    }
    if (valid) valid = Prepare(native, target, width, height) &&
        DrawLegacyLines(native, lines) &&
        CheckLineState(native) &&
        ReadPixels(native, target, staging, width, height, legacy);
    if (valid) {
        auto device = mikudancestudio::rhi::CreateD3D9Device(native);
        using namespace mikudancestudio::rhi;
        const auto vertex = device->CreateBuffer(
            {BufferUsage::Vertex, sizeof(lines)}, lines.data());
        valid = vertex && Prepare(native, target, width, height) &&
            device->BeginFrame({0, 0, 0, 1}) &&
            device->SetFixedPipeline({}) &&
            !device->Draw(device->Record(NonIndexedDraw{vertex, 1, 8})) &&
            device->Draw(device->Record(NonIndexedDraw{vertex, 0, 8})) &&
            device->EndFrame() && CheckLineState(native) &&
            ReadPixels(native, target, staging, width, height, adapted) &&
            device->Present();
    }
    if (valid) {
        unsigned differences = 0, colored = 0;
        for (std::size_t pixel = 0; pixel < legacy.size(); ++pixel) {
            if (legacy[pixel] != adapted[pixel]) ++differences;
            if (legacy[pixel] != 0xff000000) ++colored;
        }
        valid = legacy.size() == static_cast<std::size_t>(width) * height &&
            differences == 0 && colored != 0;
        std::printf("rhi_d3d9_line_parity source=%s pixels=%zu "
                    "differences=%u colored=%u\n",
            argc >= 2 ? "captured" : "fixture", legacy.size(),
            differences, colored);
    }
    if (valid && argc == 3) {
        IDirect3DSurface9* liveTarget = nullptr;
        IDirect3DSurface9* liveDepth = nullptr;
        bool supported = SUCCEEDED(native->CreateRenderTarget(width, height,
            static_cast<D3DFORMAT>(capturedState.format),
            static_cast<D3DMULTISAMPLE_TYPE>(capturedState.samples),
            capturedState.sampleQuality, FALSE, &liveTarget, nullptr)) &&
            SUCCEEDED(native->CreateDepthStencilSurface(width, height,
            static_cast<D3DFORMAT>(capturedState.depthFormat),
            static_cast<D3DMULTISAMPLE_TYPE>(capturedState.depthSamples),
            capturedState.depthQuality, FALSE, &liveDepth, nullptr));
        if (!supported) {
            std::fprintf(stderr, "captured target/depth MSAA is unavailable on replay device\n");
            valid = false;
        } else {
            valid = Prepare(native, liveTarget, width, height) &&
                SUCCEEDED(native->SetDepthStencilSurface(liveDepth)) &&
                DrawLegacyLines(native, lines, &capturedState) &&
                ReadPixels(native, liveTarget, staging, width, height,
                    legacy, target);
            if (!valid)
                std::fprintf(stderr, "captured legacy target/state replay failed\n");
        }
        if (valid) {
            auto device = mikudancestudio::rhi::CreateD3D9Device(native);
            using namespace mikudancestudio::rhi;
            const auto vertex = device->CreateBuffer(
                {BufferUsage::Vertex, sizeof(lines)}, lines.data());
            valid = vertex && Prepare(native, liveTarget, width, height) &&
                device->BeginFrame({0, 0, 0, 1}) &&
                ApplyCapturedState(native, capturedState) &&
                device->SetFixedPipeline(SelectionBoxPipeline());
            if (valid && !CheckCapturedState(native, capturedState)) {
                std::fprintf(stderr, "adapter selection pipeline state differs from capture\n");
                valid = false;
            }
            if (valid)
                valid = device->Draw(device->Record(NonIndexedDraw{vertex, 0, 8})) && device->EndFrame() &&
                    ReadPixels(native, liveTarget, staging, width, height,
                        adapted, target) && device->Present();
            if (!valid)
                std::fprintf(stderr, "captured adapter target/state replay failed\n");
        }
        if (valid) {
            unsigned differences = 0, colored = 0;
            unsigned minX = width, minY = height, maxX = 0, maxY = 0;
            for (std::size_t pixel = 0; pixel < legacy.size(); ++pixel) {
                if (legacy[pixel] != adapted[pixel]) ++differences;
                if (legacy[pixel] != 0xff000000) {
                    ++colored;
                    const unsigned x = static_cast<unsigned>(pixel % width);
                    const unsigned y = static_cast<unsigned>(pixel / width);
                    minX = (std::min)(minX, x);
                    minY = (std::min)(minY, y);
                    maxX = (std::max)(maxX, x);
                    maxY = (std::max)(maxY, y);
                }
            }
            std::printf("rhi_d3d9_live_state_replay target=%ux%u viewport=%u,%u,%u,%u "
                        "pixels=%zu differences=%u colored=%u coloredBounds=%u,%u,%u,%u\n",
                width, height, capturedState.viewX, capturedState.viewY,
                capturedState.viewWidth, capturedState.viewHeight,
                legacy.size(), differences, colored,
                minX, minY, maxX, maxY);
            valid = differences == 0 && colored != 0;
        }
        if (valid && capturedState.depth &&
            capturedState.depthFunc == D3DCMP_LESSEQUAL) {
            auto occludedLines = lines;
            for (auto& line : occludedLines) line.z = 0.5f;
            valid = Prepare(native, liveTarget, width, height) &&
                DrawLegacyLines(native, occludedLines, &capturedState, 0.0f) &&
                ReadPixels(native, liveTarget, staging, width, height,
                    legacy, target);
            if (valid) {
                auto device = mikudancestudio::rhi::CreateD3D9Device(native);
                using namespace mikudancestudio::rhi;
                const auto vertex = device->CreateBuffer(
                    {BufferUsage::Vertex, sizeof(occludedLines)},
                    occludedLines.data());
                valid = vertex && Prepare(native, liveTarget, width, height) &&
                    device->BeginFrame({0, 0, 0, 1}) &&
                    SUCCEEDED(native->Clear(0, nullptr, D3DCLEAR_ZBUFFER,
                        0, 0.0f, 0)) &&
                    ApplyCapturedState(native, capturedState) &&
                    device->SetFixedPipeline(SelectionBoxPipeline()) &&
                    CheckCapturedState(native, capturedState) &&
                    device->Draw(device->Record(NonIndexedDraw{vertex, 0, 8})) && device->EndFrame() &&
                    ReadPixels(native, liveTarget, staging, width, height,
                        adapted, target) && device->Present();
            }
            if (valid) {
                unsigned differences = 0, legacyColored = 0, adaptedColored = 0;
                for (std::size_t pixel = 0; pixel < legacy.size(); ++pixel) {
                    differences += legacy[pixel] != adapted[pixel];
                    legacyColored += legacy[pixel] != 0xff000000;
                    adaptedColored += adapted[pixel] != 0xff000000;
                }
                std::printf("rhi_d3d9_depth_probe differences=%u "
                            "legacy_colored=%u adapted_colored=%u\n",
                    differences, legacyColored, adaptedColored);
                valid = differences == 0 && legacyColored == 0 &&
                    adaptedColored == 0;
            }
        }
        native->SetRenderTarget(0, target);
        if (liveDepth) liveDepth->Release();
        if (liveTarget) liveTarget->Release();
    }
    if (staging) staging->Release();
    if (target) target->Release();
    native->Release();
    DestroyWindow(window);
    context->Release();
    return valid ? 0 : 1;
}
