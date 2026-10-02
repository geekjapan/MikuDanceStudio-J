#include "mikudancestudio/pmm_format.hpp"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <vector>
namespace {
void Check(bool condition) { if (!condition) std::abort(); }
struct Input {
    std::vector<char> bytes;
    std::size_t offset = 0;
};
bool Read(void* context, void* destination, std::size_t length) {
    auto& input = *static_cast<Input*>(context);
    if (length > input.bytes.size() - input.offset) return false;
    std::memcpy(destination, input.bytes.data() + input.offset, length);
    input.offset += length;
    return true;
}
std::array<char, 30> Header(std::size_t offset, const char* version) {
    std::array<char, 30> bytes{};
    bytes.fill('!');
    constexpr char signature[] = "Polygon Movie maker";
    std::copy_n(signature, sizeof signature - 1, bytes.data() + offset);
    std::copy_n(version, 5, bytes.data() + offset + 0x14);
    return bytes;
}
}
int main() {
    using namespace mikudancestudio::format;
    PmmHeader parsed;
    auto bytes = Header(0, "0001");
    Check(ParsePmmHeader(bytes, parsed) == PmmHeaderStatus::Ok);
    Check(parsed.version == PmmVersion::V1 && parsed.signatureOffset == 0);
    bytes = Header(5, "0002");
    Input input{{bytes.begin(), bytes.end()}};
    Check(ReadPmmHeader(Read, &input, parsed) == PmmHeaderStatus::Ok);
    Check(parsed.version == PmmVersion::V2 && parsed.signatureOffset == 5);
    Check(input.offset == bytes.size());
    input.bytes.pop_back(); input.offset = 0;
    Check(ReadPmmHeader(Read, &input, parsed) == PmmHeaderStatus::Truncated);
    Check(parsed.version == PmmVersion::V2 && parsed.signatureOffset == 5);
    bytes = Header(0, "0003");
    Check(ParsePmmHeader(bytes, parsed) == PmmHeaderStatus::UnsupportedVersion);
    bytes = Header(0, "0001");
    bytes[24] = 'X';
    Check(ParsePmmHeader(bytes, parsed) == PmmHeaderStatus::UnsupportedVersion);
    bytes = Header(5, "0001");
    bytes[2] = '\0';
    Check(ParsePmmHeader(bytes, parsed) == PmmHeaderStatus::InvalidSignature);
    bytes.fill('!');
    Check(ParsePmmHeader(bytes, parsed) == PmmHeaderStatus::InvalidSignature);
    bytes.fill('!');
    constexpr char signature[] = "Polygon Movie maker";
    std::copy_n(signature, sizeof signature - 1, bytes.data() + 10);
    Check(ParsePmmHeader(bytes, parsed) == PmmHeaderStatus::UnsupportedVersion);
    Check(parsed.version == PmmVersion::V2 && parsed.signatureOffset == 5);
    Input bone;
    const auto append32 = [](Input& target, std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            target.bytes.push_back(static_cast<char>(value >> shift));
    };
    append32(bone, 42); append32(bone, 1); append32(bone, 9);
    for (int lane = 0; lane < 4; ++lane)
        for (int group = 0; group < 4; ++group)
            bone.bytes.push_back(static_cast<char>(lane + group * 4));
    for (int index = 0; index < 7; ++index) append32(bone, 0x3f800000);
    bone.bytes.push_back(2);
    Input v1 = bone;
    bone.bytes.push_back(3);
    PmmBoneKey boneKey;
    Check(ReadPmmBoneKey(Read, &bone, PmmVersion::V2, boneKey));
    Check(bone.offset == 58 && boneKey.frame == 42 && boneKey.previous == 1 &&
          boneKey.interpolation[15] == 15 && boneKey.position[0] == 1.0f &&
          boneKey.allocated == 2 && boneKey.physicsDisabled == 3);
    boneKey.physicsDisabled = 8;
    Check(ReadPmmBoneKey(Read, &v1, PmmVersion::V1, boneKey));
    Check(v1.offset == 57 && boneKey.physicsDisabled == 0);
    v1.bytes.pop_back(); v1.offset = 0;
    boneKey.frame = 99;
    Check(!ReadPmmBoneKey(Read, &v1, PmmVersion::V1, boneKey));
    Check(boneKey.frame == 99);
    Input morph;
    append32(morph, 17); append32(morph, 4); append32(morph, 22);
    append32(morph, 0x3e800000); morph.bytes.push_back(1);
    PmmMorphKey morphKey;
    Check(ReadPmmMorphKey(Read, &morph, morphKey));
    Check(morph.offset == 17 && morphKey.frame == 17 &&
          morphKey.value == 0.25f && morphKey.allocated == 1);
    morph.bytes.pop_back(); morph.offset = 0;
    morphKey.frame = 88;
    Check(!ReadPmmMorphKey(Read, &morph, morphKey) && morphKey.frame == 88);
    Check(!ReadPmmBoneKey(nullptr, &bone, PmmVersion::V2, boneKey));
    Check(!ReadPmmMorphKey(nullptr, &morph, morphKey));
    Input camera;
    for (int i = 0; i < 3; ++i) append32(camera, i + 1);
    for (int i = 0; i < 7; ++i) append32(camera, 0x3f800000);
    Input cameraV1 = camera;
    append32(camera, 7); append32(camera, 8);
    for (int i = 0; i < 24; ++i) {
        camera.bytes.push_back(static_cast<char>(i));
        cameraV1.bytes.push_back(static_cast<char>(i));
    }
    camera.bytes.push_back(1); append32(camera, 45); camera.bytes.push_back(2);
    cameraV1.bytes.push_back(2); append32(cameraV1, 30);
    cameraV1.bytes.push_back(1);
    PmmCameraKey cameraKey;
    Check(ReadPmmCameraKey(Read, &camera, PmmVersion::V2, cameraKey));
    Check(camera.offset == 78 && cameraKey.frame == 1 &&
          cameraKey.eye[0] == 1.0f && cameraKey.parentModel == 7 &&
          cameraKey.parentBone == 8 && cameraKey.interpolation[3][5] == 23 &&
          cameraKey.perspective == 1 && cameraKey.fov == 45 &&
          cameraKey.selected == 0);
    Check(ReadPmmCameraKey(Read, &cameraV1, PmmVersion::V1, cameraKey));
    Check(cameraV1.offset == 70 && cameraKey.parentModel == 0 &&
          cameraKey.perspective == 0 && cameraKey.selected == 1);
    cameraV1.bytes.pop_back(); cameraV1.offset = 0;
    cameraKey.frame = 99;
    Check(!ReadPmmCameraKey(Read, &cameraV1, PmmVersion::V1, cameraKey));
    Check(cameraKey.frame == 99);
    Input light;
    for (int i = 0; i < 3; ++i) append32(light, i + 1);
    for (int i = 0; i < 6; ++i) append32(light, 0x3f800000);
    light.bytes.push_back(1);
    PmmLightKey lightKey;
    Check(ReadPmmLightKey(Read, &light, lightKey));
    Check(light.offset == 37 && lightKey.frame == 1 &&
          lightKey.color[0] == 1.0f && lightKey.direction[2] == 1.0f &&
          lightKey.selected == 1);
    Input shadow;
    for (int i = 0; i < 3; ++i) append32(shadow, i + 1);
    shadow.bytes.push_back(3); append32(shadow, 0x3f800000);
    shadow.bytes.push_back(2);
    PmmSelfShadowKey shadowKey;
    Check(ReadPmmSelfShadowKey(Read, &shadow, shadowKey));
    Check(shadow.offset == 18 && shadowKey.mode == 3 &&
          shadowKey.distance == 1.0f && shadowKey.selected == 0);
    Input gravity;
    for (int i = 0; i < 3; ++i) append32(gravity, i + 1);
    gravity.bytes.push_back(1); append32(gravity, 4);
    for (int i = 0; i < 4; ++i) append32(gravity, 0x3f800000);
    gravity.bytes.push_back(2);
    PmmGravityKey gravityKey;
    Check(ReadPmmGravityKey(Read, &gravity, gravityKey));
    Check(gravity.offset == 34 && gravityKey.noiseEnabled == 1 &&
          gravityKey.noise == 4 && gravityKey.acceleration == 1.0f &&
          gravityKey.direction[2] == 1.0f && gravityKey.selected == 0);
    gravity.bytes.pop_back(); gravity.offset = 0;
    gravityKey.frame = 99;
    Check(!ReadPmmGravityKey(Read, &gravity, gravityKey) &&
          gravityKey.frame == 99);
}
