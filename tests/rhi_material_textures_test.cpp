#include "mikudancestudio/rhi_material_textures.hpp"
#include <chrono>
#include <cstdio>
#include <fstream>
#include <limits>
#include <cmath>

using namespace mikudancestudio::rhi;
namespace fs = std::filesystem;
namespace {
// Original 2x2 RGBA fixture; no third-party model/texture required by CI.
const std::vector<std::uint8_t> png = {137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,
    0,0,0,2,0,0,0,2,8,6,0,0,0,114,182,13,36,0,0,0,18,73,68,65,84,120,156,99,248,
    207,192,240,31,12,129,52,24,0,0,73,200,9,247,249,171,182,13,0,0,0,0,73,69,78,
    68,174,66,96,130};
const std::vector<std::uint8_t> rgba = {255,0,0,255,0,255,0,255,
    0,0,255,255,255,255,255,255};
void U32(std::vector<std::uint8_t>& b, unsigned at, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) b[at + i] = static_cast<std::uint8_t>(value >> (i * 8));
}
std::vector<std::uint8_t> Bmp(bool topDown = false) {
    std::vector<std::uint8_t> b(70);
    b[0] = 'B'; b[1] = 'M'; U32(b, 2, 70); U32(b, 10, 54); U32(b, 14, 40);
    U32(b, 18, 2); U32(b, 22, topDown ? 0xfffffffeu : 2);
    b[26] = 1; b[28] = 24;
    for (unsigned y = 0; y < 2; ++y) for (unsigned x = 0; x < 2; ++x) {
        const auto from = ((topDown ? y : 1 - y) * 2 + x) * 4;
        const auto to = 54 + y * 8 + x * 3; // padded scanline
        b[to] = rgba[from + 2]; b[to + 1] = rgba[from + 1]; b[to + 2] = rgba[from];
    }
    return b;
}
void Write(const fs::path& path, const std::vector<std::uint8_t>& bytes) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
}
bool Bind(Device& device, Handle texture) {
    return device.BeginFrame({}) && device.SetFixedPipeline(HudSpritePipeline()) &&
        device.BindTexture(0, texture) && device.EndFrame() && device.Present();
}
}
int main() {
    RgbaImage image;
    for (bool top : {false, true}) {
        auto bmp = Bmp(top);
        const bool decoded = DecodeTextureRgba(bmp.data(), bmp.size(), image);
        if (!decoded || image.pixels != rgba || image.width != 2 || image.height != 2) {
            std::fprintf(stderr, "BMP topDown=%u decoded=%u dimensions=%ux%u channels=%zu\n",
                top, decoded, image.width, image.height, image.pixels.size());
            return 1;
        }
        if (DecodePngRgba(bmp.data(), bmp.size(), image)) return 1;
        bmp.pop_back();
        if (DecodeTextureRgba(bmp.data(), bmp.size(), image) || !image.pixels.empty()) return 2;
    }
    if (!DecodeTextureRgba(png.data(), png.size(), image) || image.pixels != rgba ||
        DecodeTextureRgba(png.data(), png.size() / 2, image)) return 3;
    const auto root = fs::temp_directory_path() / ("mds-toon-" + std::to_string(
        std::chrono::high_resolution_clock::now().time_since_epoch().count()));
    fs::create_directories(root);
    struct Cleanup { fs::path path; ~Cleanup() { std::error_code e; fs::remove_all(path, e); } } cleanup{root};
    const CallbackAssetSource builtin([](AssetId, std::vector<std::uint8_t>& out) {
        out = png; return true;
    });
    ToonTextureResolver resolver(root / "shared", builtin);
    ToonRequest request;
    MaterialTextureAsset initial, fileAsset, fallback;
    if (!resolver.Load(request, initial) || initial.origin != TextureOrigin::Builtin ||
        initial.fallback || initial.content.image.pixels != rgba) return 4;
    request.kind = ToonKind::Shared; request.sharedSlot = 1;
    if (!resolver.Load(request, fallback) || !fallback.fallback ||
        fallback.origin != TextureOrigin::Builtin) return 5;
    Write(root / "shared/toon01.bmp", Bmp());
    if (!resolver.Load(request, fileAsset) || fileAsset.fallback ||
        fileAsset.origin != TextureOrigin::SharedFile || fileAsset.identity != fallback.identity ||
        fileAsset.content.revision != fallback.content.revision) return 6;
    Write(root / "shared/toon01.bmp", {1,2,3});
    if (!resolver.Load(request, fallback) || !fallback.fallback) return 7;
    request.kind = ToonKind::ModelFile; request.modelDirectory = root / "model";
    request.path = "textures\\..\\textures\\custom.png";
    Write(root / "model/textures/custom.png", png);
    if (!resolver.Load(request, fileAsset) || fileAsset.origin != TextureOrigin::ModelFile ||
        fileAsset.content.image.pixels != rgba) return 8;
    request.path = root / "model/textures/custom.png";
    MaterialTextureAsset absolute;
    if (!resolver.Load(request, absolute) || absolute.identity != fileAsset.identity) return 9;
    request.path = "missing.png";
    if (resolver.Load(request, fallback) || !fallback.content.image.pixels.empty()) return 10;
    request.missing = MissingToonPolicy::Default;
    if (!resolver.Load(request, fallback) || !fallback.fallback ||
        fallback.identity != initial.identity) return 11;
    request.kind = ToonKind::Shared; request.sharedSlot = 11;
    if (resolver.Load(request, fallback) || !fallback.content.image.pixels.empty()) return 12;
    // No hidden dependency on builtin files: a real model file can stand alone.
    const CallbackAssetSource missing([](AssetId, std::vector<std::uint8_t>&) { return false; });
    ToonTextureResolver noBuiltin(root / "absent", missing);
    if (noBuiltin.Load({}, fallback)) return 13;
    // .sph/.spa are material semantics; decode their bytes by content.
    Write(root / "model/metal.SPH", Bmp());
    Write(root / "model/add.spa", png);
    MaterialTextureAsset sphereAsset;
    if (LoadMaterialTexture(root / "model", "metal.SPH", sphereAsset) != MaterialResourceStatus::Ready ||
        sphereAsset.content.image.pixels != rgba ||
        LoadMaterialTexture(root / "model", "add.spa", sphereAsset) != MaterialResourceStatus::Ready ||
        sphereAsset.content.image.pixels != rgba) return 20;
    if (LoadMaterialTexture(root / "model", {}, sphereAsset) != MaterialResourceStatus::Absent ||
        !sphereAsset.identity.empty() || LoadMaterialTexture(root / "model", "lost.sph", sphereAsset) !=
        MaterialResourceStatus::Missing || sphereAsset.identity.empty() || !sphereAsset.content.image.pixels.empty()) return 21;
    Write(root / "model/corrupt.spa", {1,2,3});
    if (LoadMaterialTexture(root / "model", "corrupt.spa", sphereAsset) != MaterialResourceStatus::Missing) return 22;
    MaterialTextureLayout layout;
    if (!BuildMaterialTextureLayout(true, "metal.SPH", {}, 0, layout) ||
        layout.stages[1].role != MaterialTextureRole::Sphere || layout.sphere != SphereOperation::Multiply ||
        layout.stages[1].coordinates != MaterialCoordinates::CameraNormal ||
        !BuildMaterialTextureLayout(true, "base.png", "add.spa", 0, layout) ||
        layout.stages[1].role != MaterialTextureRole::Base || layout.stages[2].role != MaterialTextureRole::Sphere ||
        layout.stages[2].color != MaterialCombine::Add ||
        !BuildMaterialTextureLayout(false, {}, "sphere.png", 1, layout) ||
        layout.stages[1].role != MaterialTextureRole::Sphere || layout.stages[2].role != MaterialTextureRole::None ||
        !BuildMaterialTextureLayout(false, "base.png", "sphere.png", 3, layout) ||
        layout.stages[2].coordinates != MaterialCoordinates::MeshUv1 ||
        layout.stages[2].color != MaterialCombine::Modulate ||
        !BuildMaterialTextureLayout(false, "base.png", "sphere.png", 0, layout) ||
        layout.stages[2].role != MaterialTextureRole::None ||
        BuildMaterialTextureLayout(false, {}, "sphere.png", 4, layout) ||
        layout.stages[0].role != MaterialTextureRole::None) return 23;
    if (!BuildMaterialTextureLayout(true, "map.Sph", {}, 0, layout) ||
        layout.stages[1].role != MaterialTextureRole::Base ||
        !BuildMaterialTextureLayout(true, "map.sph.backup", {}, 0, layout) ||
        layout.stages[1].role != MaterialTextureRole::Sphere) return 26;
    auto device = CreateNullDevice();
    MaterialTextureCache cache(*device);
    const auto first = cache.Get(fileAsset), reused = cache.Get(absolute);
    if (!first || first.index != reused.index || first.generation != reused.generation ||
        cache.Uploads() != 1 || cache.Hits() != 1 || !Bind(*device, first)) return 14;
    auto updated = fileAsset;
    updated.content.image.pixels[0] ^= 1;
    updated.content.revision = ImageRevision(updated.content.image);
    const auto changed = cache.Get(updated);
    if (!changed || cache.Uploads() != 2 || device->Destroy(first) || !Bind(*device, changed)) return 15;
    if (!device->PrepareForReset() || cache.Get(updated) || !device->RestoreAfterReset()) return 45;
    const auto retained = cache.Get(updated);
    if (retained.generation != changed.generation || cache.Uploads()!=2 || !Bind(*device,retained)) return 46;
    cache.Invalidate();
    if (device->Destroy(changed) || !device->PrepareForReset() || cache.Get(updated) ||
        !device->RestoreAfterReset()) return 16;
    const auto rebuilt = cache.Get(updated);
    if (!rebuilt || cache.Uploads() != 3 || !Bind(*device, rebuilt)) return 17;
    auto replacement = CreateNullDevice();
    MaterialTextureCache replacementCache(*replacement);
    const auto replacementTexture = replacementCache.Get(updated);
    if (!replacementTexture || replacementTexture.device == rebuilt.device ||
        replacement->Destroy(rebuilt) || !Bind(*replacement, replacementTexture)) return 18;
    cache.Invalidate(); replacementCache.Invalidate();
    if (device->Destroy(rebuilt) || replacement->Destroy(replacementTexture)) return 19;
    if (!replacementCache.Rebind(*device)) return 48;
    const auto rebound = replacementCache.Get(updated);
    if (!rebound || rebound.device != rebuilt.device || replacementCache.Uploads()!=2 || !Bind(*device,rebound)) return 47;
    replacementCache.Invalidate();
    // Upload policy is part of the cache key even when the decoded pixels match.
    const auto single = cache.Get(fileAsset);
    auto mipAsset = fileAsset;
    mipAsset.mips = TextureDesc::Mips::GenerateLinear;
    const auto mipTexture = cache.Get(mipAsset), mipReuse = cache.Get(mipAsset);
    if (!single || !mipTexture || mipTexture.generation != mipReuse.generation ||
        device->Destroy(single) || !Bind(*device, mipTexture)) return 24;
    auto invalidMips = mipAsset;
    invalidMips.mips = static_cast<TextureDesc::Mips>(255);
    if (cache.Get(invalidMips)) return 25;
    MaterialShaderInputs shader;
    const std::array<float,16> identity{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    shader.world=shader.view=shader.projection=identity;
    shader.world[12]=3;shader.world[13]=-2;shader.world[14]=5;
    shader.view[0]=0;shader.view[2]=-1;shader.view[8]=1;shader.view[10]=0;
    shader.projection={2,0,0,0,0,3,0,0,0,0,2,1,0,0,-2,0};
    shader.nativeDiffuse={.8f,.6f,.4f,.5f};shader.shininess=16;
    shader.lights[0].enabled=true;shader.lights[0].direction={0,-2,0};
    if(!BuildShaderNormalMatrix(shader.world,shader.view,shader.normalView))return 26;
    if(!ValidateMaterialShaderInputs(shader))return 26;
    auto position=TransformShaderVector({1,2,3,1},shader.world);
    if(position!=std::array<float,4>{4,0,8,1})return 27;
    position=TransformShaderVector(position,shader.view);
    if(position!=std::array<float,4>{8,0,-4,1})return 28;
    position=TransformShaderVector(position,shader.projection);
    if(position!=std::array<float,4>{16,0,-10,-4})return 29;
    if(TransformShaderVector({1,2,3,0},shader.world)!=std::array<float,4>{1,2,3,0})return 30;
    auto invalidShader=shader;invalidShader.world[3]=1;
    if(ValidateMaterialShaderInputs(invalidShader))return 31;
    invalidShader=shader;invalidShader.lights[0].direction={0,0,0};
    if(ValidateMaterialShaderInputs(invalidShader))return 32;
    auto scaled=identity;scaled[0]=2;scaled[5]=4;scaled[10]=8;scaled[12]=99;
    std::array<float,16> normal;
    if(!BuildShaderNormalMatrix(scaled,identity,normal) || normal[0]!=.5f || normal[5]!=.25f ||
       normal[10]!=.125f || TransformShaderVector({2,4,8,0},normal)!=std::array<float,4>{1,1,1,0})return 33;
    scaled[0]=0;if(BuildShaderNormalMatrix(scaled,identity,normal))return 34;
    scaled=identity;scaled[0]=2;scaled[5]=4;scaled[10]=8;
    if(!BuildShaderNormalMatrix(scaled,shader.view,normal))return 35;
    const auto tangent=TransformShaderVector(TransformShaderVector({1,1,0,0},scaled),shader.view);
    const auto transformedNormal=TransformShaderVector({1,-1,0,0},normal);
    if(std::abs(tangent[0]*transformedNormal[0]+tangent[1]*transformedNormal[1]+tangent[2]*transformedNormal[2])>1e-6f)return 36;
    invalidShader=shader;invalidShader.nativeDiffuse[0]=std::numeric_limits<float>::quiet_NaN();
    if(ValidateMaterialShaderInputs(invalidShader))return 37;
    invalidShader=shader;invalidShader.layout.stages[0].role=static_cast<MaterialTextureRole>(255);
    if(ValidateMaterialShaderInputs(invalidShader))return 38;
    MaterialTextureLayout cascade;
    if(!BuildMaterialTextureLayout(false,"base.bmp","sphere.spa",2,cascade))return 39;
    std::array<std::array<float,4>,3> sampled{{{{.5f,.25f,1,.5f}},{{.5f,1,.25f,.5f}},{{.875f,.5f,0,.5f}}}};
    std::array<float,4> shaded;
    if(!EvaluateMaterialTextureCascade(cascade,{1,1,1,1},sampled,shaded) ||
       shaded!=std::array<float,4>{1,.75f,.25f,.125f})return 40;
    if(MaterialAlphaTest(shaded[3],true,DepthComparison::GreaterEqual,64) ||
       !MaterialAlphaTest(shaded[3],true,DepthComparison::Less,64) ||
       !MaterialAlphaTest(64/255.f,true,DepthComparison::Equal,64) ||
       MaterialAlphaTest(1,true,DepthComparison::Never,0) ||
       !MaterialAlphaTest(0,false,DepthComparison::Never,255))return 41;
    if(!BuildMaterialTextureLayout(false,"","sphere.sph",1,cascade) ||
       !EvaluateMaterialTextureCascade(cascade,{1,1,1,1},sampled,shaded) ||
       shaded!=std::array<float,4>{.25f,.25f,.25f,.25f})return 42;
    auto rejected=cascade;rejected.stages[1].color=MaterialCombine::SelectTexture;
    if(EvaluateMaterialTextureCascade(rejected,{1,1,1,1},sampled,shaded) || shaded!=std::array<float,4>{})return 43;
    if(!MaterialAlphaTest(127.8f/255,true,DepthComparison::GreaterEqual,128) ||
       MaterialAlphaTest(127.49f/255,true,DepthComparison::GreaterEqual,128))return 44;
    std::puts("Base/Sphere/Toon resolution, BMP/PNG RGBA, shader layout, upload/bind/reuse/revision/reset/replacement/release: PASS");
    return 0;
}
