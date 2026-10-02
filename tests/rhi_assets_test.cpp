#include "mikudancestudio/rhi_assets.hpp"
#include <cstdint>
#include <fstream>
#include <iterator>
#include <vector>

namespace {
using namespace mikudancestudio::rhi;
// Model a backend whose texture handles are invalidated by reset.
class EvictingDevice final : public Device {
    std::unique_ptr<Device> inner = CreateNullDevice();
    std::vector<Handle> textures;
public:
    Backend BackendType() const override { return inner->BackendType(); }
    Capabilities Features() const override { return inner->Features(); }
    DeviceStatus Status() const override { return inner->Status(); }
    ResourceLifecycleCapabilities ResourceLifecycleFeatures() const override {
        auto caps=inner->ResourceLifecycleFeatures(); caps.retainsTextures=false; return caps;
    }
    Handle CreateBuffer(BufferDesc d,const void* p=nullptr) override { return inner->CreateBuffer(d,p); }
    Handle CreateTexture(TextureDesc d) override { auto h=inner->CreateTexture(d); if(h)textures.push_back(h); return h; }
    bool UploadTexture(Handle h,TexturePixels p) override { return inner->UploadTexture(h,p); }
    bool BindTexture(std::uint32_t n,Handle h) override { return inner->BindTexture(n,h); }
    bool Upload(Handle h,std::size_t o,const void* p,std::size_t n) override { return inner->Upload(h,o,p,n); }
    bool Destroy(Handle h) override { return inner->Destroy(h); }
    bool BeginFrame(ClearColor c) override { return inner->BeginFrame(c); }
    bool SetFixedPipeline(FixedPipelineState p) override { return inner->SetFixedPipeline(p); }
    bool Draw(NonIndexedDraw d) override { return inner->Draw(d); }
    bool DrawIndexed(IndexedDraw d) override { return inner->DrawIndexed(d); }
    bool EndFrame() override { return inner->EndFrame(); }
    bool Present() override { return inner->Present(); }
    bool PrepareForReset() override {
        for(auto h:textures) inner->Destroy(h);
        textures.clear(); return inner->PrepareForReset();
    }
    bool RestoreAfterReset() override { return inner->RestoreAfterReset(); }
};
}
int main(int argc, char** argv) {
    using namespace mikudancestudio::rhi;
    if (argc != 2) return 1;
    const FileAssetSource files(argv[1]);
    std::vector<std::uint8_t> bytes;
    if (!files.Read(AssetId::HudSprites, bytes) || bytes.empty() ||
        files.Read(static_cast<AssetId>(0xffff), bytes) || !bytes.empty())
        return 2;
    if (!files.Read(AssetId::HudSprites, bytes)) return 3;
    const CallbackAssetSource embedded([&](AssetId id,
            std::vector<std::uint8_t>& output) {
        if (id != AssetId::HudSprites) return false;
        output = bytes;
        return true;
    });
    AtlasAsset fileAtlas, embeddedAtlas;
    AtlasAsset fontAtlas;
    if (!LoadAtlas(files, AssetId::HudSprites, fileAtlas) ||
        !LoadAtlas(embedded, AssetId::HudSprites, embeddedAtlas) ||
        !LoadAtlas(files, AssetId::SceneFont, fontAtlas) ||
        fileAtlas.image.width != 512 || fileAtlas.image.height != 512 ||
        fontAtlas.image.width != 512 || fontAtlas.image.height != 512 ||
        fileAtlas.image.pixels != embeddedAtlas.image.pixels ||
        fileAtlas.revision != embeddedAtlas.revision ||
        fileAtlas.revision == 0) return 4;
    const CallbackAssetSource missing([](AssetId,
            std::vector<std::uint8_t>& output) {
        output = {1, 2, 3};
        return false;
    });
    AtlasAsset failed = fileAtlas;
    if (LoadAtlas(missing, AssetId::HudSprites, failed) ||
        failed.revision || !failed.image.pixels.empty()) return 5;

    auto device = CreateNullDevice();
    EvictingDevice replacement;
    AtlasTextureCache cache(*device);
    const auto fontTexture = cache.Get(AssetId::SceneFont, fontAtlas);
    if (!fontTexture || cache.Uploads() != 1) return 6;
    const auto first = cache.Get(AssetId::HudSprites, fileAtlas);
    const auto reused = cache.Get(AssetId::HudSprites, embeddedAtlas);
    if (!first || first.index != reused.index ||
        first.generation != reused.generation ||
        cache.Uploads() != 2 || cache.Hits() != 1 ||
        !device->BeginFrame({}) ||
        !device->SetFixedPipeline(HudSpritePipeline()) ||
        !device->BindTexture(0, first) ||
        !device->EndFrame() || !device->Present()) return 6;
    auto updatedAtlas = fileAtlas;
    updatedAtlas.image.pixels[0] ^= 1;
    ++updatedAtlas.revision;
    const auto changed = cache.Get(AssetId::HudSprites, updatedAtlas);
    if (!changed || (changed.index == first.index &&
                     changed.generation == first.generation) ||
        device->UploadTexture(first, {bytes.data(), 4, bytes.size()}) ||
        cache.Uploads() != 3) return 7;

    cache.Invalidate();
    if (device->Destroy(changed) || !device->PrepareForReset() ||
        cache.Get(AssetId::HudSprites, fileAtlas) ||
        !device->RestoreAfterReset()) return 8;
    const auto rebuilt = cache.Get(AssetId::HudSprites, fileAtlas);
    if (!rebuilt || (rebuilt.index == changed.index &&
                     rebuilt.generation == changed.generation) ||
        cache.Uploads() != 4 ||
        !device->BeginFrame({}) ||
        !device->SetFixedPipeline(HudSpritePipeline()) ||
        !device->BindTexture(0, rebuilt) ||
        !device->EndFrame() || !device->Present()) return 9;
    const auto vertices = device->CreateBuffer({BufferUsage::Vertex, 84});
    const auto recorded = device->Record(NonIndexedDraw{vertices, 0, 3});
    if (!vertices || !device->BeginFrame({}) || !device->SetFixedPipeline(HudSpritePipeline()) ||
        !device->BindTexture(0, rebuilt) || !device->Draw(recorded) || cache.Rebind(replacement) ||
        !device->EndFrame() || !device->Present()) return 14;
    if (!device->PrepareForReset() || cache.Get(AssetId::HudSprites, fileAtlas) ||
        !device->RestoreAfterReset()) return 11;
    const auto retained = cache.Get(AssetId::HudSprites, fileAtlas);
    if (retained.index != rebuilt.index || retained.generation != rebuilt.generation ||
        cache.Uploads() != 4 || !device->BeginFrame({}) ||
        !device->SetFixedPipeline(HudSpritePipeline()) || !device->BindTexture(0, retained) ||
        device->Draw(recorded) || !device->Draw(device->Record(NonIndexedDraw{vertices,0,3})) ||
        !device->EndFrame() || !device->Present()) return 12;
    if (!cache.Rebind(replacement)) return 17;
    const auto restored = cache.Get(AssetId::HudSprites, fileAtlas);
    if (!restored || restored.device == retained.device || cache.Uploads() != 5 ||
        !replacement.BeginFrame({}) || !replacement.SetFixedPipeline(HudSpritePipeline()) ||
        !replacement.BindTexture(0, restored) || !replacement.EndFrame() || !replacement.Present()) return 13;
    if (!replacement.PrepareForReset() || cache.Get(AssetId::HudSprites,fileAtlas) ||
        !replacement.RestoreAfterReset()) return 15;
    const auto reuploaded=cache.Get(AssetId::HudSprites,fileAtlas);
    const auto newVertices=replacement.CreateBuffer({BufferUsage::Vertex,84});
    if (!reuploaded || cache.Uploads()!=6 || !newVertices ||
        !replacement.BeginFrame({}) || !replacement.SetFixedPipeline(HudSpritePipeline()) ||
        replacement.BindTexture(0,restored) || !replacement.BindTexture(0,reuploaded) ||
        !replacement.Draw(replacement.Record(NonIndexedDraw{newVertices,0,3})) ||
        !replacement.EndFrame() || !replacement.Present()) return 16;
    cache.Invalidate();
    if (replacement.Destroy(reuploaded)) return 10;
    return 0;
}
