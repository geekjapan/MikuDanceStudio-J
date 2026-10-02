#include "pmm_format_win.hpp"
#include "pmm_io_common.hpp"
#include <array>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <io.h>
#include <vector>
namespace {
void Check(bool condition) { if (!condition) std::abort(); }
}
int main() {
    std::array<char, 30> bytes{};
    bytes.fill('!');
    constexpr char signature[] = "Polygon Movie maker";
    std::memcpy(bytes.data() + 5, signature, sizeof signature - 1);
    std::memcpy(bytes.data() + 25, "0002", 5);
    int pipe[2]{};
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], bytes.data(), static_cast<unsigned>(bytes.size())) ==
          static_cast<int>(bytes.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmHeader memory, file;
    Check(mikudancestudio::format::ParsePmmHeader(bytes, memory) ==
          mikudancestudio::format::PmmHeaderStatus::Ok);
    Check(mikudancestudio::format::ReadPmmHeader(
              mikudancestudio::ReadPmmFileBytes, &pipe[0], file) ==
          mikudancestudio::format::PmmHeaderStatus::Ok);
    Check(memory.version == file.version &&
          memory.signatureOffset == file.signatureOffset);
    _close(pipe[0]);
    std::vector<char> records;
    const auto append32 = [&records](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            records.push_back(static_cast<char>(value >> shift));
    };
    append32(42); append32(1); append32(9);
    for (int lane = 0; lane < 4; ++lane)
        for (int group = 0; group < 4; ++group)
            records.push_back(static_cast<char>(lane + group * 4));
    for (int index = 0; index < 7; ++index) append32(0x3f800000);
    records.push_back(2); records.push_back(3);
    append32(17); append32(4); append32(22);
    append32(0x3e800000); records.push_back(1);
    for (int i = 0; i < 3; ++i) append32(i + 1);
    for (int i = 0; i < 7; ++i) append32(0x3f800000);
    append32(7); append32(8);
    for (int i = 0; i < 24; ++i) records.push_back(static_cast<char>(i));
    records.push_back(1); append32(45); records.push_back(2);
    for (int i = 0; i < 3; ++i) append32(i + 1);
    for (int i = 0; i < 6; ++i) append32(0x3f800000);
    records.push_back(1);
    for (int i = 0; i < 3; ++i) append32(i + 1);
    records.push_back(3); append32(0x3f800000); records.push_back(2);
    for (int i = 0; i < 3; ++i) append32(i + 1);
    records.push_back(1); append32(4);
    for (int i = 0; i < 4; ++i) append32(0x3f800000);
    records.push_back(2);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], records.data(), static_cast<unsigned>(records.size())) ==
          static_cast<int>(records.size()));
    _close(pipe[1]);
    mikudancestudio::mdl::BoneKey bone{};
    mikudancestudio::pmm_io::ReadPmmBoneKey<
        mikudancestudio::pmm_io::PmmStream::V2>(pipe[0], bone);
    mikudancestudio::mdl::MorphKey morph{};
    mikudancestudio::pmm_io::ReadPmmMorphKey(pipe[0], morph);
    mikudancestudio::mdl::CameraKey camera{};
    mikudancestudio::pmm_io::ReadPmmCameraKey<
        mikudancestudio::pmm_io::PmmStream::V2>(pipe[0], camera);
    mikudancestudio::mdl::LightKey light{};
    mikudancestudio::pmm_io::ReadPmmLightKey(pipe[0], light);
    mikudancestudio::mdl::SelfShadowKey shadow{};
    mikudancestudio::pmm_io::ReadPmmSelfShadowKey(pipe[0], shadow);
    mikudancestudio::mdl::GravityKey gravity{};
    mikudancestudio::pmm_io::ReadPmmGravityKey(pipe[0], gravity);
    Check(bone.frame == 42 && bone.interpolation[15] == 15 &&
          bone.position[0] == 1.0f && bone.physicsDisabled == 3);
    Check(morph.frame == 17 && morph.value == 0.25f && morph.allocated == 1);
    Check(camera.frame == 1 && camera.parentModel == 7 && camera.parentBone == 8 &&
          camera.eye[0] == 1.0f && camera.interpolation[3][5] == 23 &&
          camera.perspective == 1 && camera.selected == 0);
    Check(light.color[0] == 1.0f && light.direction[2] == 1.0f &&
          light.selected == 1);
    Check(shadow.mode == 3 && shadow.distance == 1.0f && shadow.selected == 0);
    Check(gravity.noiseEnabled == 1 && gravity.noise == 4 &&
          gravity.acceleration == 1.0f && gravity.direction[2] == 1.0f &&
          gravity.selected == 0);
    _close(pipe[0]);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    std::vector<char> v1Records(records.begin(), records.begin() + 57);
    for (int i = 0; i < 3; ++i)
        for (int shift = 0; shift < 32; shift += 8)
            v1Records.push_back(static_cast<char>((i + 1) >> shift));
    for (int i = 0; i < 7; ++i)
        for (int shift = 0; shift < 32; shift += 8)
            v1Records.push_back(static_cast<char>(0x3f800000u >> shift));
    for (int i = 0; i < 24; ++i) v1Records.push_back(static_cast<char>(i));
    v1Records.push_back(2);
    for (int shift = 0; shift < 32; shift += 8)
        v1Records.push_back(static_cast<char>(30 >> shift));
    v1Records.push_back(1);
    Check(_write(pipe[1], v1Records.data(),
                 static_cast<unsigned>(v1Records.size())) ==
          static_cast<int>(v1Records.size()));
    _close(pipe[1]);
    mikudancestudio::mdl::BoneKey v1{};
    v1.physicsDisabled = 8;
    mikudancestudio::pmm_io::ReadPmmBoneKey<
        mikudancestudio::pmm_io::PmmStream::V1>(pipe[0], v1);
    Check(v1.frame == 42 && v1.allocated == 2 && v1.physicsDisabled == 8);
    mikudancestudio::mdl::CameraKey v1Camera{};
    v1Camera.parentModel = 99;
    mikudancestudio::pmm_io::ReadPmmCameraKey<
        mikudancestudio::pmm_io::PmmStream::V1>(pipe[0], v1Camera);
    Check(v1Camera.frame == 1 && v1Camera.parentModel == 99 &&
          v1Camera.interpolation[3][5] == 23 && v1Camera.fov == 30 &&
          v1Camera.perspective == 0 && v1Camera.selected == 1);
    _close(pipe[0]);
    std::vector<char> sections;
    const auto word = [&sections](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            sections.push_back(static_cast<char>(value >> shift));
    };
    word(1280); word(720); word(240); word(0x42340000);
    for (int index = 0; index < 7; ++index) sections.push_back(index == 2);
    word(10); word(2); word(20); sections.push_back(0x65);
    word(3); word(4);
    for (int index = 0; index < 7; ++index) word(0x3f800000);
    sections.push_back(1); sections.push_back(2);
    word(7); word(1); word(9);
    sections.push_back(1); sections.push_back(1); sections.push_back(2);
    word(11); word(12); sections.push_back(1);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], sections.data(), static_cast<unsigned>(sections.size())) ==
          static_cast<int>(sections.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmSceneSettings settings;
    Check(mikudancestudio::format::ReadPmmSceneSettings(
          mikudancestudio::ReadPmmFileBytes, &pipe[0],
          mikudancestudio::format::PmmVersion::V2, settings));
    Check(settings.renderWidth == 1280 && settings.options[2] == 1);
    mikudancestudio::mdl::AccessoryKey accessory{};
    mikudancestudio::pmm_io::ReadPmmAccessoryKey(pipe[0], accessory);
    Check(accessory.frame == 10 && accessory.visible == 1 &&
          accessory.opacity == 0.5f && accessory.parentModel == 3 &&
          accessory.position[0] == 1.0f && accessory.shadowEnabled == 1 &&
          accessory.selected == 0);
    mikudancestudio::format::PmmDisplayKey display;
    Check(mikudancestudio::pmm_io::ReadPmmDisplayKey(
          pipe[0], mikudancestudio::pmm_io::PmmStream::V2, 2, 1, display));
    Check(display.frame == 7 && display.ikEnabled[1] == 0 &&
          display.rigidStates[0].boneIndex == 12 && display.allocated == 1);
    _close(pipe[0]);
    std::vector<char> v1Display;
    const auto displayWord = [&v1Display](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            v1Display.push_back(static_cast<char>(value >> shift));
    };
    displayWord(7); displayWord(1); displayWord(9);
    v1Display.push_back(1); v1Display.push_back(1);
    v1Display.push_back(0); v1Display.push_back(1);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], v1Display.data(),
                 static_cast<unsigned>(v1Display.size())) ==
          static_cast<int>(v1Display.size()));
    _close(pipe[1]);
    Check(mikudancestudio::pmm_io::ReadPmmDisplayKey(
          pipe[0], mikudancestudio::pmm_io::PmmStream::V1, 2, 0, display));
    Check(display.frame == 7 && display.visible == 1 &&
          display.ikEnabled.size() == 2 && display.ikEnabled[1] == 0 &&
          display.rigidStates.empty() && display.allocated == 1);
    _close(pipe[0]);
    std::vector<char> timelineBytes;
    const auto timelineWord = [&timelineBytes](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            timelineBytes.push_back(static_cast<char>(value >> shift));
    };
    timelineWord(30); timelineWord(10); timelineWord(40); timelineWord(3);
    timelineBytes.push_back(2); timelineBytes.push_back(1);
    timelineBytes.push_back(0); timelineBytes.push_back(1);
    timelineWord(12); timelineWord(96);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], timelineBytes.data(),
                 static_cast<unsigned>(timelineBytes.size())) ==
          static_cast<int>(timelineBytes.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmTimelineSettings timeline;
    Check(mikudancestudio::format::ReadPmmTimelineSettings(
          mikudancestudio::ReadPmmFileBytes, &pipe[0], timeline));
    Check(timeline.currentFrame == 30 && timeline.playStartFrame == 12 &&
          timeline.playStopFrame == 96 && timeline.cameraReferenceMode == 2);
    _close(pipe[0]);
    std::vector<char> media;
    const auto mediaWord = [&media](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            media.push_back(static_cast<char>(value >> shift));
    };
    media.push_back(1);
    media.insert(media.end(), 256, '\0'); media[1] = 'w';
    mediaWord(12); mediaWord(24); mediaWord(0x3f800000);
    media.insert(media.end(), 256, '\0'); media[269] = 'a';
    mediaWord(1);
    mediaWord(32); mediaWord(64); mediaWord(0x3f000000);
    media.insert(media.end(), 256, '\0');
    media.push_back(1);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], media.data(), static_cast<unsigned>(media.size())) ==
          static_cast<int>(media.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmWaveReference wave;
    mikudancestudio::format::PmmBackgroundReference avi, picture;
    Check(mikudancestudio::format::ReadPmmWaveReference(
          mikudancestudio::ReadPmmFileBytes, &pipe[0], wave));
    Check(mikudancestudio::format::ReadPmmBackgroundReference(
          mikudancestudio::ReadPmmFileBytes, &pipe[0],
          mikudancestudio::format::PmmBackgroundKind::Avi, avi));
    Check(mikudancestudio::format::ReadPmmBackgroundReference(
          mikudancestudio::ReadPmmFileBytes, &pipe[0],
          mikudancestudio::format::PmmBackgroundKind::Picture, picture));
    Check(wave.enabled == 1 && wave.pathBytes[0] == 'w' &&
          avi.offsetX == 12 && avi.pathBytes[0] == 'a' && avi.enabled == 1 &&
          picture.offsetX == 32 && picture.scale == 0.5f && picture.enabled == 1);
    _close(pipe[0]);
    std::vector<char> viewBytes{1, 0, 1, 0, 0, static_cast<char>(0xf0), 0x41,
                                2, 0, 0, 0};
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], viewBytes.data(),
                 static_cast<unsigned>(viewBytes.size())) ==
          static_cast<int>(viewBytes.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmViewSettings view;
    Check(mikudancestudio::format::ReadPmmViewSettings(
          mikudancestudio::ReadPmmFileBytes, &pipe[0], view));
    Check(view.fpsOverlay == 1 && view.groundShadow == 1 &&
          view.fpsLimit == 30.0f && view.captureMode == 2);
    _close(pipe[0]);
    std::vector<char> physicsBytes;
    const auto physicsWord = [&physicsBytes](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            physicsBytes.push_back(static_cast<char>(value >> shift));
    };
    physicsWord(5); physicsWord(0x3f000000);
    physicsBytes.push_back(1); physicsBytes.push_back(2);
    physicsWord(0x411ccccd); physicsWord(10);
    physicsWord(0); physicsWord(0xbf800000); physicsWord(0);
    physicsBytes.push_back(1);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], physicsBytes.data(),
                 static_cast<unsigned>(physicsBytes.size())) ==
          static_cast<int>(physicsBytes.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmPhysicsSettings physics;
    Check(mikudancestudio::format::ReadPmmPhysicsSettings(
          mikudancestudio::ReadPmmFileBytes, &pipe[0], physics));
    Check(physics.accessoryRenderOrder == 5 &&
          physics.projectedShadowAmbient == 0.5f &&
          physics.playbackMode == 2 && physics.gravityNoise == 10 &&
          physics.gravityDirection[1] == -1.0f);
    _close(pipe[0]);
    std::vector<char> appearanceBytes;
    const auto appearanceWord = [&appearanceBytes](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            appearanceBytes.push_back(static_cast<char>(value >> shift));
    };
    appearanceWord(10); appearanceWord(20); appearanceWord(30);
    appearanceBytes.push_back(1);
    appearanceWord(4); appearanceWord(5);
    for (int index = 0; index < 16; ++index) appearanceWord(0x3f800000);
    appearanceBytes.push_back(1); appearanceBytes.push_back(0);
    appearanceBytes.push_back(1); appearanceWord(200);
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], appearanceBytes.data(),
                 static_cast<unsigned>(appearanceBytes.size())) ==
          static_cast<int>(appearanceBytes.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmSceneAppearance appearance;
    Check(mikudancestudio::format::ReadPmmSceneAppearance(
          mikudancestudio::ReadPmmFileBytes, &pipe[0], appearance));
    Check(appearance.outlineColor[2] == 30 && appearance.cameraParentModel == 4 &&
          appearance.cameraAttachmentBasis[15] == 1.0f &&
          appearance.floorVisible == 1 && appearance.maxFrame == 200);
    _close(pipe[0]);
    for (auto version : {mikudancestudio::format::PmmVersion::V1,
                         mikudancestudio::format::PmmVersion::V2}) {
        std::vector<char> accessoryStateBytes;
        const auto stateWord = [&accessoryStateBytes](std::uint32_t value) {
            for (int shift = 0; shift < 32; shift += 8)
                accessoryStateBytes.push_back(static_cast<char>(value >> shift));
        };
        accessoryStateBytes.push_back(0x65);
        stateWord(3); stateWord(4);
        for (int index = 0; index < 7; ++index) stateWord(0x3f800000);
        accessoryStateBytes.push_back(1);
        if (version == mikudancestudio::format::PmmVersion::V2)
            accessoryStateBytes.push_back(1);
        Check(_pipe(pipe, 4096, _O_BINARY) == 0);
        Check(_write(pipe[1], accessoryStateBytes.data(),
                     static_cast<unsigned>(accessoryStateBytes.size())) ==
              static_cast<int>(accessoryStateBytes.size()));
        _close(pipe[1]);
        mikudancestudio::format::PmmAccessoryState state;
        Check(mikudancestudio::format::ReadPmmAccessoryState(
              mikudancestudio::ReadPmmFileBytes, &pipe[0], version, state));
        Check(state.visible == 1 && state.opacity == 0.5f &&
              state.parentModel == 3 && state.scale == 1.0f &&
              state.shadowEnabled == 1 &&
              state.additiveBlend == (version == mikudancestudio::format::PmmVersion::V2));
        _close(pipe[0]);
    }
    for (auto version : {mikudancestudio::format::PmmVersion::V1,
                         mikudancestudio::format::PmmVersion::V2}) {
        std::vector<char> selectionBytes;
        const auto add32 = [&selectionBytes](std::uint32_t value) {
            for (int shift = 0; shift < 32; shift += 8)
                selectionBytes.push_back(static_cast<char>(value >> shift));
        };
        selectionBytes.push_back(3); selectionBytes.push_back(1); add32(5);
        for (int index = 0; index < 4; ++index) add32(index + 10);
        selectionBytes.push_back(version == mikudancestudio::format::PmmVersion::V1 ? 2 : 99);
        selectionBytes.push_back(1); selectionBytes.push_back(0);
        add32(15); add32(100);
        Check(_pipe(pipe, 4096, _O_BINARY) == 0);
        Check(_write(pipe[1], selectionBytes.data(),
                     static_cast<unsigned>(selectionBytes.size())) ==
              static_cast<int>(selectionBytes.size()));
        _close(pipe[1]);
        mikudancestudio::format::PmmModelSelection diskSelection;
        Check(mikudancestudio::format::ReadPmmModelSelection(
              mikudancestudio::ReadPmmFileBytes, &pipe[0], version, 2,
              diskSelection));
        Check(diskSelection.comboIndex == 3 && diskSelection.loadComplete == 1 &&
              diskSelection.selectedBone == 5 && diskSelection.selectedMorphs[3] == 13 &&
              diskSelection.groupFlags.size() == 2 &&
              diskSelection.groupFlags[0] == 1 && diskSelection.maxFrame == 100);
        _close(pipe[0]);
    }
}
