#include "mikudancestudio/pmm_scene_document.hpp"
#include "mikudancestudio/scene_session.hpp"
#include "model_reader_fixture.hpp"
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <vector>
using namespace mikudancestudio::format;
namespace {
struct Bytes {
    std::vector<std::uint8_t> data;
    std::size_t offset = 0;
    void byte(std::uint8_t value) { data.push_back(value); }
    void word(std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8) byte(value >> shift);
    }
    void zero(std::size_t count) { data.insert(data.end(), count, 0); }
};
int Read(void* context, void* destination, std::size_t length) {
    auto& input = *static_cast<Bytes*>(context);
    const auto count = std::min(length, input.data.size() - input.offset);
    if (count) std::memcpy(destination, input.data.data() + input.offset, count);
    input.offset += count;
    return static_cast<int>(count);
}
bool Write(void* context, const void* source, std::size_t length) {
    auto& bytes = *static_cast<std::vector<std::uint8_t>*>(context);
    const auto* first = static_cast<const std::uint8_t*>(source);
    bytes.insert(bytes.end(), first, first + length);
    return true;
}
bool Resolve(void*, std::uint8_t slot, const std::array<char, 20>&,
             const std::array<char, 256>&, PmmModelLayout& layout) {
    if (slot != 1) return false;
    layout = {};
    return true;
}
void CheckAt(bool value, int line) {
    if (!value) {
        std::fprintf(stderr, "check failed at line %d\n", line);
        std::abort();
    }
}
#define Check(value) CheckAt((value), __LINE__)
Bytes Fixture(bool v1) {
    Bytes b;
    b.zero(30);
    std::memcpy(b.data.data(), "Polygon Movie maker", 19);
    std::memcpy(b.data.data() + 20, v1 ? "0001" : "0002", 5);
    b.word(640); b.word(480); b.word(200); b.word(0x42340000);
    b.zero(v1 ? 6 : 7);
    b.byte(1); b.byte(1); // selected slot and model count
    if (v1) {
        b.zero(20); b.data.back() = 'M';
        b.byte(1); b.zero(20); b.zero(256);
    } else {
        b.byte(1); b.byte(1); b.byte('M');
        b.byte(1); b.byte('M'); b.zero(256);
        b.byte(0); b.word(0); b.word(0); b.word(0); b.word(0);
    }
    b.byte(1); b.byte(1); b.word(0); // model selection
    for (int i = 0; i < 4; ++i) b.word(0);
    b.byte(0); b.word(0); b.word(100);
    b.word(0); b.word(0); // bone/morph sparse counts
    b.zero(14); b.word(0); // display head and sparse count
    if (!v1) {
        b.byte(0); b.word(0x3f800000); b.byte(0); b.byte(1);
    }
    b.zero(v1 ? 70 : 78); b.word(0); // camera
    b.zero(37); // camera state, including perspective
    b.zero(37); b.word(0); // light
    b.zero(24); // light state
    b.byte(0); b.word(0); b.byte(0); // accessory list
    b.zero(28); // timeline
    b.zero(257); // wave
    b.zero(272); // AVI
    b.zero(269); // picture
    b.zero(11); // view
    if (v1) {
        // Old v1 file may end at the first optional tail gate.
        return b;
    }
    b.zero(31); // physics
    b.zero(34); b.word(0); // gravity head + sparse count
    b.byte(0); b.word(0); // shadow mode and interval
    b.zero(18); b.word(0); // self-shadow head + sparse count
    b.zero(92); // appearance
    b.byte(1); b.byte(1); b.word(5); // one model tail entry
    return b;
}
Bytes FullV1Tail(Bytes b) {
    b.zero(8); b.byte(0); // render order, ambient, model flag
    b.word(0); b.byte(0); b.byte(1); // edge, blend, next gate
    b.word(0); b.byte(1); // per-model edge, next gate
    b.zero(22); b.byte(1); // playback physics and gravity, next gate
    b.byte(1); b.word(0); b.byte(0); b.byte(1); // shadow mode, interval, toon, gate
    b.zero(18); b.word(0); b.byte(1); // shadow track, next gate
    b.zero(12); b.byte(1); // outline colors, next gate
    b.byte(0); b.byte(1); // black background, next gate
    b.zero(8); b.word(0); b.zero(8); b.byte(1); // camera parents, next gate
    b.zero(66); b.byte(1); // attachment basis, flags, next gate
    b.byte(1); b.byte(1); // floor and next gate
    b.byte(1); // model previous display order
    return b;
}
Bytes PopulatedV2() {
    const auto base = Fixture(false);
    Bytes b;
    b.data.insert(b.data.end(), base.data.begin(), base.data.begin() + 55);
    b.byte(1); b.byte(1); b.byte('M'); b.byte(1); b.byte('M');
    b.zero(256);
    b.byte(1); // display group count
    b.word(1); b.byte(1); b.byte('B'); // bone name
    b.word(1); b.byte(1); b.byte('F'); // morph name
    b.word(1); b.word(0); // IK source bone
    b.word(1); b.word(0); // rigid selector source bone
    b.byte(1); b.byte(1); b.word(0); // selection
    for (int i = 0; i < 4; ++i) b.word(0);
    b.byte(0); b.byte(1); b.word(0); b.word(100); // group and range
    b.zero(58); b.word(1); b.word(2); b.zero(58); // bone head and sparse key
    b.zero(17); b.word(1); b.word(2); b.zero(17); // morph head and sparse key
    b.zero(23); b.word(1); b.word(2); b.zero(23); // display/IK/rigid keys
    b.zero(31); b.word(0); b.byte(1); b.zero(16); // current pose
    b.byte(0); b.word(0x3f800000); b.byte(0); b.byte(1); // model tail
    b.data.insert(b.data.end(), base.data.begin() + 397,
                  base.data.begin() + 581); // camera and light
    b.byte(2); b.word(0); b.byte(1); // accessory selection and count
    b.zero(100); // accessory list name
    b.byte(2); b.zero(100); b.zero(256); b.byte(0); // accessory identity
    b.zero(51); b.word(1); b.word(2); b.zero(51);
    b.zero(39); // accessory keys and current state
    b.data.insert(b.data.end(), base.data.begin() + 587, base.data.end());
    return b;
}
void CheckEditableWriteback(Bytes fixture, bool v1) {
    PmmSceneDocument scene;
    Check(ReadPmmSceneDocument(Read, &fixture, v1 ? Resolve : nullptr,
                               nullptr, scene));
    std::vector<std::uint8_t> output;
    Check(WritePmmSceneDocument(Write, &output, scene,
                                v1 ? Resolve : nullptr));
    Check(output == fixture.data);

    scene.envelope.settings.renderWidth = 1280;
    scene.envelope.settings.cameraFov = 52.0f;
    scene.envelope.settings.options[0] ^= 1;
    scene.timeline.currentFrame = 12;
    scene.timeline.startFrame = 3;
    scene.timeline.lastRegisteredFrame = 80;
    scene.timeline.playbackLoop ^= 1;
    scene.lightState[0] = 0.4f;
    scene.lightState[4] = -0.6f;
    if (scene.selfShadowStateOffset != 0) {
        scene.selfShadowMode = 2;
        scene.physicsInterval = 0.02f;
    }
    if (!scene.selfShadowKeys.dense.empty()) {
        scene.selfShadowKeys.dense[0].mode = 2;
        scene.selfShadowKeys.dense[0].distance = 0.02f;
    }
    if (scene.physicsOffset != 0) {
        scene.physics.gravityMagnitude = 7.0f;
        scene.physics.gravityNoise = 17;
        scene.physics.gravityDirection = {0.0f, -0.5f, 0.0f};
        scene.physics.gravityNoiseEnabled = 1;
    }
    if (!scene.gravityKeys.dense.empty()) {
        scene.gravityKeys.dense[0].acceleration = 9.0f;
        scene.gravityKeys.dense[0].noise = 5;
        scene.gravityKeys.dense[0].direction = {0.0f, -1.0f, 0.0f};
        scene.gravityKeys.dense[0].noiseEnabled = 1;
    }
    if (!scene.models[0].bonePose.empty()) {
        scene.models[0].bonePose[0].components[0] = 1.5f;
        scene.models[0].bonePose[0].flags[0] = 1;
        scene.models[0].morphPose[0] = 0.75f;
        scene.models[0].ikPose[0] = 1;
    }
    if (!scene.accessories.empty()) {
        auto& accessory = scene.accessories[0];
        accessory.keyRecords.dense[0].visible = 1;
        accessory.keyRecords.dense[0].opacity = 0.75f;
        accessory.keyRecords.dense[0].position[0] = 3.0f;
        accessory.keyRecords.sparse[0].value.scale = 2.0f;
        accessory.state.visible = 1;
        accessory.state.opacity = 0.5f;
        accessory.state.parentModel = 4;
        accessory.state.rotation[1] = 6.0f;
    }
    output.clear();
    Check(WritePmmSceneDocument(Write, &output, scene,
                                v1 ? Resolve : nullptr));
    Check(output.size() == fixture.data.size() && output != fixture.data);
    Bytes edited{output};
    PmmSceneDocument reloaded;
    Check(ReadPmmSceneDocument(Read, &edited, v1 ? Resolve : nullptr,
                               nullptr, reloaded));
    Check(reloaded.envelope.settings.renderWidth == 1280 &&
          reloaded.envelope.settings.cameraFov == 52.0f &&
          reloaded.timeline.currentFrame == 12 &&
          reloaded.timeline.startFrame == 3 &&
          reloaded.timeline.lastRegisteredFrame == 80 &&
          reloaded.timeline.playbackLoop == 1 &&
          reloaded.lightState[0] == 0.4f &&
          reloaded.lightState[4] == -0.6f);
    if (scene.selfShadowStateOffset != 0)
        Check(reloaded.selfShadowMode == 2 &&
              reloaded.physicsInterval == 0.02f);
    if (!scene.selfShadowKeys.dense.empty())
        Check(reloaded.selfShadowKeys.dense[0].mode == 2 &&
              reloaded.selfShadowKeys.dense[0].distance == 0.02f);
    if (scene.physicsOffset != 0)
        Check(reloaded.physics.gravityMagnitude == 7.0f &&
              reloaded.physics.gravityNoise == 17 &&
              reloaded.physics.gravityDirection[1] == -0.5f &&
              reloaded.physics.gravityNoiseEnabled == 1);
    if (!scene.gravityKeys.dense.empty())
        Check(reloaded.gravityKeys.dense[0].acceleration == 9.0f &&
              reloaded.gravityKeys.dense[0].noise == 5 &&
              reloaded.gravityKeys.dense[0].direction[1] == -1.0f &&
              reloaded.gravityKeys.dense[0].noiseEnabled == 1);
    if (!scene.models[0].bonePose.empty())
        Check(reloaded.models[0].bonePose[0].components[0] == 1.5f &&
              reloaded.models[0].bonePose[0].flags[0] == 1 &&
              reloaded.models[0].morphPose[0] == 0.75f &&
              reloaded.models[0].ikPose[0] == 1);
    if (!scene.accessories.empty())
        Check(reloaded.accessories[0].keyRecords.dense[0].visible == 1 &&
              reloaded.accessories[0].keyRecords.dense[0].opacity == 0.75f &&
              reloaded.accessories[0].keyRecords.dense[0].position[0] == 3.0f &&
              reloaded.accessories[0].keyRecords.sparse[0].value.scale == 2.0f &&
              reloaded.accessories[0].state.opacity == 0.5f &&
              reloaded.accessories[0].state.parentModel == 4 &&
              reloaded.accessories[0].state.rotation[1] == 6.0f);
    output.clear();
    scene.models[0].slot = 7;
    Check(!WritePmmSceneDocument(Write, &output, scene,
                                 v1 ? Resolve : nullptr) && output.empty());
}
bool ResolveModel(void*, std::uint8_t slot,
                  const std::array<char, 256>&, ModelDocument& output) {
    if (slot != 1 && slot != 2) return false;
    auto source = model_reader_fixture::Pmd();
    return ReadModelDocument(model_reader_fixture::Bytes::read, &source, output);
}
bool ResolveEmptyModel(void*, std::uint8_t slot,
                       const std::array<char, 256>&,
                       ModelDocument& output) {
    if (slot != 1) return false;
    output = {};
    output.kind = ModelKind::Pmd;
    return true;
}
void CheckSceneSession() {
    auto fixture = PopulatedV2();
    SceneSession session;
    Check(SceneSession::Load(Read, &fixture, ResolveModel, nullptr, session));
    Check(session.Loaded() && session.Models().size() == 1 &&
          session.Models()[0].has_value() &&
          session.Models()[0]->kind == ModelKind::Pmd);
    Check(session.Edit([](PmmSceneDocument& scene) {
        scene.envelope.settings.renderWidth = 1280;
        scene.cameraKeys.dense[0].parentModel = 1;
        scene.cameraKeys.dense[0].parentBone = 0;
        scene.cameraKeys.dense[0].distance = -35.0f;
        scene.cameraKeys.dense[0].fov = 45;
        scene.cameraKeys.dense[0].interpolation[0][0] = 42;
        scene.models[0].boneKeys.dense[0].position[0] = 2.0f;
        scene.models[0].boneKeys.sparse[0].value.position[1] = 3.0f;
        scene.models[0].morphKeys.dense[0].value = 0.75f;
        scene.models[0].morphKeys.sparse[0].value.value = 0.25f;
        scene.models[0].displayKeys.dense[0].visible = 1;
        scene.models[0].displayKeys.sparse[0].value.visible = 1;
        scene.models[0].displayKeys.sparse[0].value.ikEnabled[0] = 1;
        scene.lightKeys.dense[0].color[0] = 0.4f;
        scene.models[0].bonePose[0].components[0] = 4.0f;
        scene.accessories[0].keyRecords.dense[0].position[0] = 7.0f;
        scene.accessories[0].state.position[0] = 8.0f;
    }));
    Check(session.Pose().models[0].bones[0].translation[0] == 4.0f &&
          session.Pose().accessories[0].position[0] == 8.0f &&
          session.Document().models[0].bonePose[0].components[0] == 4.0f);
    std::vector<std::uint8_t> saved;
    Check(session.Save(Write, &saved));
    Bytes savedInput{saved};
    PmmSceneDocument checked;
    Check(ReadPmmSceneDocument(Read, &savedInput, nullptr, nullptr, checked));
    Check(checked.envelope.settings.renderWidth == 1280 &&
          checked.cameraKeys.dense[0].parentModel == 1 &&
          checked.cameraKeys.dense[0].parentBone == 0 &&
          checked.cameraKeys.dense[0].distance == -35.0f &&
          checked.cameraKeys.dense[0].fov == 45 &&
          checked.cameraKeys.dense[0].interpolation[0][0] == 42 &&
          checked.models[0].boneKeys.dense[0].position[0] == 2.0f &&
          checked.models[0].boneKeys.sparse[0].value.position[1] == 3.0f &&
          checked.models[0].morphKeys.dense[0].value == 0.75f &&
          checked.models[0].morphKeys.sparse[0].value.value == 0.25f &&
          checked.models[0].displayKeys.dense[0].visible == 1 &&
          checked.models[0].displayKeys.sparse[0].value.visible == 1 &&
          checked.models[0].displayKeys.sparse[0].value.ikEnabled[0] == 1 &&
          checked.lightKeys.dense[0].color[0] == 0.4f &&
          checked.accessories[0].keyRecords.dense[0].position[0] == 7.0f &&
          checked.accessories[0].state.position[0] == 8.0f &&
          checked.models[0].bonePose[0].components[0] == 4.0f);
    const auto beforeInvalid = session.Document().models[0].boneKeys.dense[0].position[0];
    Check(!session.Edit([](PmmSceneDocument& scene) {
        scene.models[0].boneKeys.dense[0].next = 999;
    }));
    Check(session.Document().models[0].boneKeys.dense[0].position[0] ==
          beforeInvalid);
    Check(session.Seek(0) && !session.Playing() &&
          session.Document().models[0].bonePose[0].components[0] == 2.0f &&
          session.Pose().accessories[0].position[0] == 7.0f);
    Check(session.StartPlayback() && session.Playing());
    Check(session.Advance(5.0f / 30.0f) &&
          session.Pose().models[0].bones[0].translation[0] == 2.0f &&
          session.Pose().accessories[0].position[0] == 7.0f);
    saved.clear();
    Check(session.Save(Write, &saved));
    Bytes reloadedInput{saved};
    SceneSession reloaded;
    Check(SceneSession::Load(Read, &reloadedInput, ResolveModel,
                             nullptr, reloaded));
    Check(reloaded.Document().models[0].bonePose[0].components[0] == 2.0f &&
          reloaded.Document().accessories[0].state.position[0] == 7.0f &&
          reloaded.Document().timeline.currentFrame == 5);

    auto v1 = Fixture(true);
    SceneSession legacy;
    Check(!SceneSession::Load(Read, &v1, nullptr, nullptr, legacy));
    v1.offset = 0;
    Check(SceneSession::Load(Read, &v1, ResolveEmptyModel, nullptr, legacy));
    Check(legacy.Document().envelope.header.version == PmmVersion::V1 &&
          legacy.Models()[0].has_value());
    Check(!legacy.Edit([](PmmSceneDocument& scene) {
        scene.cameraKeys.dense[0].parentModel = 1;
    }));
    Check(legacy.Edit([](PmmSceneDocument& scene) {
        scene.envelope.settings.renderWidth = 900;
    }));
    Check(legacy.Seek(0) && legacy.StartPlayback() && legacy.Advance(0.0f));
    std::vector<std::uint8_t> legacyBytes;
    Check(legacy.Save(Write, &legacyBytes));
    Bytes legacyInput{legacyBytes};
    SceneSession legacyReloaded;
    Check(SceneSession::Load(Read, &legacyInput, ResolveEmptyModel,
                             nullptr, legacyReloaded));
    Check(legacyReloaded.Document().envelope.settings.renderWidth == 900);

    auto multi = PopulatedV2();
    PmmSceneDocument original;
    Check(ReadPmmSceneDocument(Read, &multi, nullptr, nullptr, original));
    const auto section = original.sections[1];
    std::vector<std::uint8_t> second(
        multi.data.begin() + section.offset,
        multi.data.begin() + section.offset + section.size);
    second[0] = 2;
    multi.data.insert(multi.data.begin() + section.offset + section.size,
                      second.begin(), second.end());
    multi.data[54] = 2;
    multi.byte(2);
    multi.word(5);
    multi.offset = 0;
    SceneSession twoModels;
    Check(SceneSession::Load(Read, &multi, ResolveModel, nullptr, twoModels));
    Check(twoModels.Document().models.size() == 2 &&
          twoModels.Models()[1].has_value());
    Check(twoModels.Seek(0) && twoModels.StartPlayback() &&
          twoModels.Advance(5.0f / 30.0f) &&
          twoModels.Pose().models.size() == 2);
    Check(twoModels.Edit([](PmmSceneDocument& scene) {
        scene.models[1].boneKeys.dense[0].position[0] = 6.0f;
        scene.models[1].bonePose[0].components[0] = 6.0f;
    }));
    std::vector<std::uint8_t> multiBytes;
    Check(twoModels.Save(Write, &multiBytes));
    Bytes multiInput{multiBytes};
    SceneSession multiReloaded;
    Check(SceneSession::Load(Read, &multiInput, ResolveModel,
                             nullptr, multiReloaded));
    Check(multiReloaded.Document().models.size() == 2 &&
          multiReloaded.Document().models[1].boneKeys.dense[0].position[0] ==
              6.0f &&
          multiReloaded.Document().models[1].bonePose[0].components[0] ==
              6.0f);
}
}
int main() {
    PmmSceneDocument scene;
    auto v1 = Fixture(true);
    Check(!ReadPmmSceneDocument(Read, &v1, nullptr, nullptr, scene));
    v1.offset = 0;
    Check(ReadPmmSceneDocument(Read, &v1, Resolve, nullptr, scene));
    Check(v1.offset == v1.data.size() && scene.models.size() == 1 &&
          scene.models[0].slot == 1 && scene.models[0].selection.maxFrame == 100 &&
          scene.camera.dense == 1 && scene.sections.size() == 6);
    Check(scene.physicsOffset == 0 &&
          scene.physics.gravityMagnitude == 9.8000002f &&
          scene.physics.gravityNoise == 10 &&
          scene.physics.gravityDirection[1] == -1.0f);
    auto fullV1 = FullV1Tail(Fixture(true));
    Check(ReadPmmSceneDocument(Read, &fullV1, Resolve, nullptr, scene));
    Check(scene.selfShadow.dense == 1 && scene.sections.back().kind ==
          PmmSceneSectionKind::Tail &&
          scene.sections.back().offset + scene.sections.back().size ==
          fullV1.data.size());
    Check(scene.physics.gravityMagnitude == 0.0f &&
          scene.physics.gravityNoise == 0);
    Check(scene.v1TailStage == 12 && scene.models[0].previousDisplayOrder == 1);
    auto brokenV1 = fullV1;
    brokenV1.data.pop_back(); brokenV1.offset = 0;
    Check(!ReadPmmSceneDocument(Read, &brokenV1, Resolve, nullptr, scene));
    Check(scene.v1TailStage == 12 && scene.models[0].previousDisplayOrder == 1);
    auto v2 = Fixture(false);
    Check(ReadPmmSceneDocument(Read, &v2, nullptr, nullptr, scene));
    Check(v2.offset == v2.data.size() && scene.models.size() == 1 &&
          scene.models[0].layout.boneCount == 0 && scene.gravity.dense == 1 &&
          scene.selfShadow.dense == 1 && scene.sections.back().offset +
          scene.sections.back().size == v2.data.size() &&
          scene.modelRegistrations.size() == 1 &&
          scene.modelRegistrations[0].selection == 5);
    for (std::size_t index = 1; index < scene.sections.size(); ++index)
        Check(scene.sections[index].offset == scene.sections[index - 1].offset +
              scene.sections[index - 1].size);
    auto populated = PopulatedV2();
    Check(ReadPmmSceneDocument(Read, &populated, nullptr, nullptr, scene));
    Check(scene.models.size() == 1 && scene.models[0].layout.boneCount == 1 &&
          scene.models[0].layout.morphCount == 1 &&
          scene.models[0].layout.ikCount == 1 &&
          scene.models[0].rigidCount == 1 &&
          scene.models[0].bones.dense == 1 &&
          scene.models[0].displays.dense == 1 &&
          scene.models[0].boneNames[0][0] == 'B' &&
          scene.models[0].morphNames[0][0] == 'F' &&
          scene.models[0].boneKeys.dense.size() == 1 &&
          scene.models[0].boneKeys.sparse.size() == 1 &&
          scene.models[0].boneKeys.sparse[0].index == 2 &&
          scene.models[0].displayKeys.dense[0].ikEnabled.size() == 1 &&
          scene.models[0].displayKeys.dense[0].rigidStates.size() == 1 &&
          scene.models[0].displayKeys.sparse.size() == 1 &&
          scene.models[0].bonePose.size() == 1 &&
          scene.models[0].rigidPose.size() == 1 &&
          scene.accessories.size() == 1 && scene.accessories[0].slot == 2 &&
          scene.accessories[0].keys.dense == 1 &&
          scene.accessories[0].keyRecords.dense.size() == 1 &&
          scene.accessories[0].keyRecords.sparse[0].index == 2);
    auto invalid = populated;
    for (int i = 0; i < 4; ++i)
        invalid.data[55 + 262 + i] = 0xff; // invalid signed bone count
    invalid.offset = 0;
    Check(!ReadPmmSceneDocument(Read, &invalid, nullptr, nullptr, scene));
    v2.offset = 0;
    Check(ReadPmmSceneDocument(Read, &v2, nullptr, nullptr, scene));
    const auto complete = scene.envelope.remainingBytes.size();
    for (std::size_t end = 0; end < v2.data.size() - 6; ++end) {
        Bytes truncated = v2;
        truncated.data.resize(end);
        truncated.offset = 0;
        Check(!ReadPmmSceneDocument(Read, &truncated, nullptr, nullptr, scene));
        Check(scene.envelope.remainingBytes.size() == complete);
    }
    v2.data.push_back(1); v2.offset = 0;
    Check(!ReadPmmSceneDocument(Read, &v2, nullptr, nullptr, scene));
    CheckEditableWriteback(Fixture(true), true);
    CheckEditableWriteback(PopulatedV2(), false);
    CheckSceneSession();
}
