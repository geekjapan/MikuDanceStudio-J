#include "mikudancestudio/rhi_material_textures.hpp"
#include <cstdio>
using namespace mikudancestudio::rhi;
int main() {
    // Original RGB fixture. Expected bytes independently captured from
    // Microsoft's d3dx9_43 default filter, rather than calculated here.
    RgbaImage raw{3, 3, {}};
    for (unsigned y = 0; y < 3; ++y) for (unsigned x = 0; x < 3; ++x) {
        raw.pixels.push_back(x == 0 ? 0 : x == 1 ? 127 : 255);
        raw.pixels.push_back(y == 0 ? 0 : y == 1 ? 127 : 255);
        raw.pixels.push_back((x + y) % 2 ? 255 : 0);
        raw.pixels.push_back(255);
    }
    const auto retained = raw.pixels;
    const std::vector<std::uint8_t> expected = {
        48,48,21,255, 79,48,157,255, 175,48,157,255, 207,48,20,255,
        48,79,157,255, 79,79,119,255, 175,80,120,255, 207,79,156,255,
        48,175,157,255, 79,175,119,255, 175,175,120,255, 207,175,157,255,
        48,207,21,255, 79,207,156,255, 175,207,157,255, 207,207,20,255};
    RgbaImage prepared;
    if (!PrepareTriangleDitherWrap(raw, 4, 4, prepared) || prepared.pixels != expected ||
        raw.pixels != retained || prepared.width != 4 || prepared.height != 4) return 1;
    RgbaImage copy;
    if (!PrepareTriangleDitherWrap(raw, 3, 3, copy) || copy.pixels != retained ||
        !PrepareTriangleDitherWrap(copy, 4, 4, copy) || copy.pixels != expected) return 2;
    if (PrepareTriangleDitherWrap(raw, 2, 4, copy) || !copy.pixels.empty() ||
        PrepareTriangleDitherWrap(raw, 7, 4, copy) || !copy.pixels.empty() ||
        PrepareTriangleDitherWrap({}, 4, 4, copy)) return 3;
    auto corrupt = raw; corrupt.pixels.pop_back();
    if (PrepareTriangleDitherWrap(corrupt, 4, 4, copy)) return 4;
    std::uint32_t size = 99;
    if (!NextPowerOfTwoTextureSize(106, 4096, size) || size != 128 ||
        !NextPowerOfTwoTextureSize(1, 4096, size) || size != 1 ||
        !NextPowerOfTwoTextureSize(4096, 4096, size) || size != 4096 ||
        NextPowerOfTwoTextureSize(106, 127, size) || size ||
        NextPowerOfTwoTextureSize(0, 4096, size) || size ||
        NextPowerOfTwoTextureSize(4097, 4096, size) || size) return 5;
    // CPU preparation is separate from decode; only explicitly accepted data
    // replaces the cache upload. Rebuild does not destroy retained raw pixels.
    auto device = CreateNullDevice();
    MaterialTextureCache cache(*device);
    MaterialTextureAsset asset;
    asset.identity = "test:original3x3";
    asset.content = {raw, ImageRevision(raw)};
    asset.prepared = {prepared, ImageRevision(prepared)};
    const auto decoded = cache.Get(asset);
    asset.usePrepared = true;
    const auto resized = cache.Get(asset), hit = cache.Get(asset);
    if (!decoded || !resized || resized.index != hit.index ||
        resized.generation != hit.generation || cache.Uploads() != 2 ||
        cache.Hits() != 1 || device->Destroy(decoded) || asset.content.image.pixels != retained) return 6;
    cache.Invalidate();
    if (!device->PrepareForReset() || cache.Get(asset) || !device->RestoreAfterReset() ||
        !cache.Get(asset) || cache.Uploads() != 3 || asset.content.image.pixels != retained) return 7;
    asset.prepared = {};
    if (cache.Get(asset)) return 8;
    // Independent arithmetic facts, odd/non-square sizes, full-chain sealing,
    // provenance tampering and failed preparation preserving the accepted asset.
    RgbaImage square{2,2,{0,10,20,0, 1,11,21,64, 2,12,22,128, 3,13,23,255}};
    PreparedMipChain chain;
    if(!PreparePortableMipChain(square,MipPreparationPolicy::BoxLinear,chain) || chain.levels.size()!=2 ||
       chain.levels[1].pixels!=std::vector<std::uint8_t>({2,12,22,112}) || !ValidatePreparedMipChain(square,chain))return 9;
    auto tampered=chain;tampered.levels[1].pixels[0]++;if(ValidatePreparedMipChain(square,tampered))return 10;
    tampered=chain;tampered.providerRevision++;if(ValidatePreparedMipChain(square,tampered))return 11;
    auto truncated=chain.levels;truncated.pop_back();
    if(SealPreparedMipChain(square,MipPreparationPolicy::BoxLinear,1,truncated,tampered) || !tampered.levels.empty())return 12;
    RgbaImage odd{3,1,{0,0,0,255,0,0,0,255,255,255,255,255}};
    if(!PreparePortableMipChain(odd,MipPreparationPolicy::BoxLinear,tampered) ||
       tampered.levels.size()!=2 || tampered.levels[1].pixels!=std::vector<std::uint8_t>({85,85,85,255}))return 13;
    MaterialTextureAsset explicitAsset;explicitAsset.identity="explicit";explicitAsset.content={square,ImageRevision(square)};
    if(!PrepareMaterialMipChain(explicitAsset,MipPreparationPolicy::BoxLinear) || cache.Get(explicitAsset))return 14;
    const auto revision=explicitAsset.mipChain->revision;
    if(PrepareMaterialMipChain(explicitAsset,MipPreparationPolicy::Dx9AutoLinear) || explicitAsset.mipChain->revision!=revision)return 15;
    auto changedSource=square;changedSource.pixels[0]++;if(ValidatePreparedMipChain(changedSource,chain))return 16;
    std::puts("Original decode preservation, measured 3x3 filter vector, explicit size policy and prepared-resource lifetime: PASS");
    return 0;
}
