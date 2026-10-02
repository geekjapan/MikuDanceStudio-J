#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include "mikudancestudio/rhi_d3d9.hpp"
#include <array>
#include <cstdint>
#include <cstdio>

int main() {
    auto* context = Direct3DCreate9(D3D_SDK_VERSION);
    if (!context) return 77;
    const HWND window = CreateWindowExW(0, L"STATIC", L"rhi test",
        WS_OVERLAPPEDWINDOW, 0, 0, 64, 64,
        nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!window) { context->Release(); return 77; }
    D3DPRESENT_PARAMETERS parameters{};
    parameters.BackBufferWidth = 64;
    parameters.BackBufferHeight = 64;
    parameters.BackBufferFormat = D3DFMT_A8R8G8B8;
    parameters.SwapEffect = D3DSWAPEFFECT_DISCARD;
    parameters.Windowed = TRUE;
    parameters.hDeviceWindow = window;
    parameters.EnableAutoDepthStencil = TRUE;
    parameters.AutoDepthStencilFormat = D3DFMT_D16;
    IDirect3DDevice9* native = nullptr;
    const auto createResult = context->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL,
            window, D3DCREATE_SOFTWARE_VERTEXPROCESSING,
            &parameters, &native);
    if (FAILED(createResult)) {
        std::fprintf(stderr, "DX9 CreateDevice failed HRESULT=0x%08lx\n", static_cast<unsigned long>(createResult));
        DestroyWindow(window);
        context->Release();
        return 77;
    }
    auto device = mikudancestudio::rhi::CreateD3D9Device(native);
    using namespace mikudancestudio::rhi;
    const std::array<float, 12> vertices{
        -0.5f, -0.5f, 0.5f, 0, 0.5f, -0.5f, 0.5f, 0,
        0.0f, 0.5f, 0.5f, 0};
    const std::array<std::uint16_t, 3> indices{0, 1, 2};
    const auto vertex = device->CreateBuffer(
        {BufferUsage::Vertex, sizeof(vertices)}, vertices.data());
    const auto index = device->CreateBuffer(
        {BufferUsage::Index, sizeof(indices)}, indices.data());
    bool valid = device->BackendType() == Backend::D3D9 &&
        vertex && index && device->BeginFrame({}) &&
        !device->DrawIndexed(device->Record(IndexedDraw{vertex, index, 1, 3, 3})) &&
        !device->DrawIndexed(device->Record(IndexedDraw{vertex, index, 0, 3, 3,
                              VertexLayout::ScreenPositionColor})) &&
        device->DrawIndexed(device->Record(IndexedDraw{vertex, index, 0, 3, 3})) &&
        device->EndFrame() && device->Present() &&
        device->Destroy(index) &&
        !device->BeginFrame({2, 0, 0, 1}) &&
        device->BeginFrame({}) &&
        !device->DrawIndexed(device->Record(IndexedDraw{vertex, index, 0, 3, 3})) &&
        device->EndFrame() && device->Present();
    struct ScreenVertex {
        float x, y, z, reciprocalW;
        std::uint32_t color;
    };
    const std::array<ScreenVertex, 2> line{{
        {8, 8, 0, 1, 0xffffffff}, {48, 48, 0, 1, 0xffffffff}}};
    const std::array<std::uint8_t, 16> rgba{
        0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
        0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x12};
    const auto atlas = device->CreateTexture({2, 2});
    struct SpriteVertex {
        float x, y, z, rhw;
        std::uint32_t color;
        float u, v;
    };
    const std::array<SpriteVertex, 3> spriteVertices{{
        {8, 8, 0, 1, 0xffffffff, 0, 0},
        {8, 48, 0, 1, 0xffffffff, 0, 1},
        {48, 8, 0, 1, 0xffffffff, 1, 0}}};
    const auto sprite = device->CreateBuffer(
        {BufferUsage::Vertex, sizeof(spriteVertices)},
        spriteVertices.data());
    auto cache = CreateBorrowedOverlayCache(native);
    if (valid) {
        const auto drawNative = [](IDirect3DDevice9* current,
                                   unsigned first, unsigned primitives) {
            return static_cast<long>(current->DrawPrimitive(
                D3DPT_TRIANGLELIST, first, primitives));
        };
        long drawStatus = E_FAIL;
        const TextureDesc description{2, 2, TextureFormat::Rgba8};
        const TexturePixels pixels{rgba.data(), 8, rgba.size()};
        valid = cache && SUCCEEDED(native->BeginScene()) &&
            !cache->Draw(OverlayAtlasSlot::Sprite, 1, description,
                {}, spriteVertices.data(), sizeof(spriteVertices), {},
                drawNative, &drawStatus) &&
            cache->Draw(OverlayAtlasSlot::Sprite, 1, description,
                pixels, spriteVertices.data(), sizeof(spriteVertices), {},
                drawNative, &drawStatus) &&
            cache->Draw(OverlayAtlasSlot::Sprite, 1, description,
                {}, spriteVertices.data(), sizeof(spriteVertices), {},
                drawNative, &drawStatus) &&
            cache->Stats(OverlayAtlasSlot::Sprite).uploads == 1 &&
            cache->Stats(OverlayAtlasSlot::Sprite).hits == 1 &&
            cache->Draw(OverlayAtlasSlot::Text, 1, description,
                pixels, spriteVertices.data(), sizeof(spriteVertices), {},
                drawNative, &drawStatus) &&
            cache->Stats(OverlayAtlasSlot::Text).uploads == 1 &&
            cache->Draw(OverlayAtlasSlot::Sprite, 2, description,
                pixels, spriteVertices.data(), sizeof(spriteVertices), {},
                drawNative, &drawStatus) &&
            cache->Stats(OverlayAtlasSlot::Sprite).uploads == 2;
        native->EndScene();
        cache.reset();
    }
    if (valid) {
        valid = atlas && sprite &&
            device->BeginFrame({}) &&
            device->SetFixedPipeline(HudSpritePipeline()) &&
            !device->BindTexture(0, atlas) &&
            device->EndFrame() && device->Present() &&
            !device->UploadTexture(atlas, {rgba.data(), 7, rgba.size()}) &&
            device->UploadTexture(atlas, {rgba.data(), 8, rgba.size()}) &&
            !device->BindTexture(0, atlas) &&
            device->BeginFrame({}) &&
            device->SetFixedPipeline(HudSpritePipeline()) &&
            !device->Draw(device->Record(NonIndexedDraw{sprite, 0, 3})) &&
            device->BindTexture(0, atlas) &&
            !device->Destroy(atlas) &&
            device->Draw(device->Record(NonIndexedDraw{sprite, 0, 3})) &&
            device->EndFrame() && device->Present();
    }
    if (valid) {
        const auto retained = device->CreateBuffer(
            {BufferUsage::Vertex, sizeof(line)}, line.data());
        const auto transient = device->CreateBuffer(
            {BufferUsage::Vertex, sizeof(line), true}, line.data());
        AtlasTextureCache textures(*device);
        AtlasAsset cpuAtlas;
        cpuAtlas.image.width = cpuAtlas.image.height = 2;
        cpuAtlas.image.pixels.assign(rgba.begin(), rgba.end());
        cpuAtlas.revision = 1;
        const auto cachedTexture = textures.Get(AssetId::HudSprites, cpuAtlas);
        const auto oldDraw = device->Record(NonIndexedDraw{retained, 0, 2});
        const auto beforeReset = device->Status();
        const SubmissionIdentity beforeSubmission{beforeReset.identity, beforeReset.epoch};
        const auto lifecycle = device->ResourceLifecycleFeatures();
        valid = cachedTexture && textures.Uploads() == 1 && IsCurrentSubmission(beforeReset, beforeSubmission) &&
            lifecycle.resetProtocol && lifecycle.retainsStaticBuffers &&
            lifecycle.retainsTextures && lifecycle.invalidatesDynamicBuffers &&
            !lifecycle.ownsNativeReset && retained && transient && !device->RestoreAfterReset() &&
            device->PrepareForReset() &&
            device->Status().state == DeviceState::ResetPending &&
            !textures.Get(AssetId::HudSprites, cpuAtlas) &&
            !IsCurrentSubmission(device->Status(), beforeSubmission) && !device->BeginFrame({}) &&
            !device->CreateBuffer({BufferUsage::Vertex, sizeof(line)}) &&
            !device->Destroy(transient) &&
            SUCCEEDED(native->Reset(&parameters)) &&
            device->RestoreAfterReset() &&
            device->Status().epoch == beforeReset.epoch + 1 &&
            textures.Get(AssetId::HudSprites, cpuAtlas).generation == cachedTexture.generation &&
            textures.Uploads() == 1 &&
            !IsCurrentSubmission(device->Status(), beforeSubmission) &&
            !device->RestoreAfterReset();
        if (valid) {
            const auto replacement = device->CreateBuffer(
                {BufferUsage::Vertex, sizeof(line), true}, line.data());
            valid = replacement && device->BeginFrame({}) &&
                device->SetFixedPipeline({}) &&
                !device->Draw(device->Record(NonIndexedDraw{transient, 0, 2})) &&
                !device->Draw(oldDraw) &&
                device->Draw(device->Record(NonIndexedDraw{retained, 0, 2})) &&
                device->Draw(device->Record(NonIndexedDraw{replacement, 0, 2})) &&
                device->EndFrame() && device->Present();
            if (valid) {
                valid = device->UploadTexture(atlas,
                        {rgba.data(), 8, rgba.size()}) &&
                    device->BeginFrame({}) &&
                    device->SetFixedPipeline(HudSpritePipeline()) &&
                    device->BindTexture(0, cachedTexture) &&
                    device->Draw(device->Record(NonIndexedDraw{sprite, 0, 3})) &&
                    device->EndFrame() && device->Present() &&
                    device->Destroy(atlas) &&
                    !device->BindTexture(0, atlas);
            }
        }
    }
    device.reset();
    if (valid) {
        // A failed setup must not issue a draw or disturb inherited state.
        // A callback failure must report that submission already happened,
        // so an application fallback cannot draw the batch twice.
        struct ModelVertex { float x, y, z, nx, ny, nz, u, v; };
        const std::array<ModelVertex, 3> mesh{{
            {-0.5f,-0.5f,0.5f,0,0,1,0,0}, {0.5f,-0.5f,0.5f,0,0,1,1,0},
            {0,0.5f,0.5f,0,0,1,0.5f,1}}};
        unsigned calls = 0;
        long status = S_OK;
        bool issued = true;
        const auto fail = [&](IDirect3DDevice9*, unsigned, unsigned, unsigned) {
            ++calls;
            return static_cast<long>(E_FAIL);
        };
        native->SetRenderState(D3DRS_CULLMODE, D3DCULL_CW);
        native->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        valid = SUCCEEDED(native->BeginScene()) &&
            !DrawModelBatchInScene(native, mesh.data(), sizeof(mesh), indices.data(),
                sizeof(indices), 1, 3, {}, fail, &status, false, &issued) &&
            !issued && calls == 0 &&
            !DrawModelBatchInScene(native, mesh.data(), sizeof(mesh), indices.data(),
                sizeof(indices), 0, 3, {}, fail, &status, false, &issued) &&
            issued && calls == 1 && status == E_FAIL;
        DWORD cull = 0, depthWrite = 1;
        valid = valid && SUCCEEDED(native->GetRenderState(D3DRS_CULLMODE, &cull)) &&
            SUCCEEDED(native->GetRenderState(D3DRS_ZWRITEENABLE, &depthWrite)) &&
            cull == D3DCULL_CW && !depthWrite;
        auto cache = CreateBorrowedModelTextureCache(native);
        MaterialTextureAsset toon;
        toon.identity = "test:toon";
        toon.content.image = {2, 2, std::vector<std::uint8_t>(rgba.begin(), rgba.end())};
        toon.content.revision = ImageRevision(toon.content.image);
        IDirect3DBaseTexture9* before = nullptr;
        native->GetTexture(0, &before);
        bool sawOwned = false;
        const auto check = [&](IDirect3DDevice9* d, unsigned, unsigned, unsigned) {
            IDirect3DBaseTexture9* bound = nullptr;
            sawOwned = SUCCEEDED(d->GetTexture(0, &bound)) && bound && bound != before;
            if (bound) bound->Release();
            return static_cast<long>(sawOwned ? S_OK : E_FAIL);
        };
        valid = valid && cache && cache->Draw(toon, mesh.data(), sizeof(mesh), indices.data(),
            sizeof(indices), 0, 3, {}, check, &status, false, &issued) && issued && sawOwned;
        IDirect3DBaseTexture9* after = nullptr;
        valid = valid && SUCCEEDED(native->GetTexture(0, &after)) && before == after;
        if (after) after->Release();
        auto baseAsset = toon, sphereAsset = toon;
        baseAsset.identity = "test:base";
        baseAsset.mips = TextureDesc::Mips::GenerateLinear;
        sphereAsset.identity = "test:sphere";
        baseAsset.content.image.pixels[0] = 0x71;
        sphereAsset.content.image.pixels[0] = 0x82;
        baseAsset.content.revision = ImageRevision(baseAsset.content.image);
        sphereAsset.content.revision = ImageRevision(sphereAsset.content.image);
        std::array<IDirect3DBaseTexture9*, 3> oldBindings{};
        for (unsigned s = 0; s < 3; ++s) native->GetTexture(s, &oldBindings[s]);
        const std::array<const MaterialTextureAsset*, 3> inputs{&toon, &baseAsset, &sphereAsset};
        const auto checkMaterial = [&](IDirect3DDevice9* d, unsigned, unsigned, unsigned) -> long {
            for (unsigned s = 0; s < 3; ++s) {
                IDirect3DBaseTexture9* bound = nullptr;
                const bool ready = SUCCEEDED(d->GetTexture(s, &bound)) && bound &&
                    bound != oldBindings[s] && bound->GetType() == D3DRTYPE_TEXTURE;
                bool identical = ready;
                if (ready) {
                    auto* texture = static_cast<IDirect3DTexture9*>(bound);
                    D3DSURFACE_DESC desc{};
                    identical = SUCCEEDED(texture->GetLevelDesc(0, &desc)) &&
                        ((desc.Usage & D3DUSAGE_AUTOGENMIPMAP) != 0) ==
                            (inputs[s]->mips == TextureDesc::Mips::GenerateLinear);
                    D3DLOCKED_RECT lock{};
                    identical = identical && SUCCEEDED(texture->LockRect(0, &lock, nullptr, D3DLOCK_READONLY));
                    if (identical) {
                        const auto* p = static_cast<const std::uint8_t*>(lock.pBits);
                        const auto& expected = inputs[s]->content.image.pixels;
                        identical = p[2] == expected[0] && p[1] == expected[1] &&
                            p[0] == expected[2] && p[3] == expected[3];
                        identical = SUCCEEDED(texture->UnlockRect(0)) && identical;
                    }
                }
                if (bound) bound->Release();
                if (!identical) return E_FAIL;
            }
            return S_OK;
        };
        valid = valid && cache->DrawMaterial(inputs, mesh.data(), sizeof(mesh), indices.data(),
            sizeof(indices), 0, 3, {}, checkMaterial, &status, false, &issued) && issued &&
            cache->Stats().uploads == 3;
        for (unsigned s = 0; s < 3; ++s) {
            IDirect3DBaseTexture9* binding = nullptr;
            valid = valid && SUCCEEDED(native->GetTexture(s, &binding)) && binding == oldBindings[s];
            if (binding) binding->Release();
        }
        // A failed secondary upload must not submit even the first-stage draw.
        auto invalid = sphereAsset;
        invalid.content.image.pixels.pop_back();
        valid = valid && !cache->DrawMaterial({&toon, &baseAsset, &invalid}, mesh.data(),
            sizeof(mesh), indices.data(), sizeof(indices), 0, 3, {}, checkMaterial, &status,
            false, &issued) && !issued;
        for (auto* binding : oldBindings) if (binding) binding->Release();
        valid = valid && cache->Draw(toon, mesh.data(), sizeof(mesh), indices.data(),
            sizeof(indices), 0, 3, {}, fail, &status, false, &issued) == false && issued &&
            cache->Stats().uploads == 3 && cache->Stats().hits >= 4;
        if (before) before->Release();
        before = nullptr;
        native->EndScene();
        cache.reset();
        // A reset discards the adapter cache, but retained CPU pixels reupload.
        valid = valid && SUCCEEDED(native->Reset(&parameters));
        cache = CreateBorrowedModelTextureCache(native);
        valid = valid && cache && SUCCEEDED(native->BeginScene()) &&
            cache->Draw(toon, mesh.data(), sizeof(mesh), indices.data(), sizeof(indices),
                0, 3, {}, check, &status) && cache->Stats().uploads == 1;
        native->EndScene();
    }
    native->Release();
    DestroyWindow(window);
    context->Release();
    return valid ? 0 : 1;
}
