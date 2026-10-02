#include "mikudancestudio/pmm_format.hpp"
#include <cstdlib>
#include <cstring>
#include <vector>
using namespace mikudancestudio::format;
namespace {
struct Input {
    std::vector<std::uint8_t> bytes;
    std::size_t offset = 0;
    bool read(void* destination, std::size_t count) {
        if (count > bytes.size() - offset) return false;
        std::memcpy(destination, bytes.data() + offset, count);
        offset += count;
        return true;
    }
    void byte(std::uint8_t value) { bytes.push_back(value); }
    void word(std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8) byte(value >> shift);
    }
};
bool Read(void* context, void* destination, std::size_t count) {
    return static_cast<Input*>(context)->read(destination, count);
}
void Check(bool condition) { if (!condition) std::abort(); }
}
int main() {
    Input settings;
    settings.word(1280); settings.word(720); settings.word(230);
    settings.word(0x42340000);
    for (int index = 0; index < 7; ++index) settings.byte(index % 3);
    PmmSceneSettings scene;
    Check(ReadPmmSceneSettings(Read, &settings, PmmVersion::V1, scene));
    Check(settings.offset == 22 && scene.renderWidth == 1280 &&
          scene.renderHeight == 720 && scene.editPanelWidth == 230 &&
          scene.cameraFov == 45.0f && scene.options[1] == 1 &&
          scene.options[2] == 0 && scene.options[6] == 0);
    settings.offset = 0;
    Check(ReadPmmSceneSettings(Read, &settings, PmmVersion::V2, scene));
    Check(settings.offset == 23 && scene.options[6] == 0);
    settings.bytes.pop_back(); settings.offset = 0; scene.renderWidth = 42;
    Check(!ReadPmmSceneSettings(Read, &settings, PmmVersion::V2, scene));
    Check(scene.renderWidth == 42);
    Input timelineBytes;
    timelineBytes.word(30); timelineBytes.word(10); timelineBytes.word(40);
    timelineBytes.word(3); timelineBytes.byte(2); timelineBytes.byte(2);
    timelineBytes.byte(0); timelineBytes.byte(1);
    timelineBytes.word(12); timelineBytes.word(96);
    PmmTimelineSettings timeline;
    Check(ReadPmmTimelineSettings(Read, &timelineBytes, timeline));
    Check(timelineBytes.offset == 28 && timeline.currentFrame == 30 &&
          timeline.startFrame == 10 && timeline.lastRegisteredFrame == 40 &&
          timeline.editMode == 3 && timeline.cameraReferenceMode == 2 &&
          timeline.playbackLoop == 1 && timeline.returnToStart == 0 &&
          timeline.startAtCurrent == 1 && timeline.playStartFrame == 12 &&
          timeline.playStopFrame == 96);
    timelineBytes.bytes.pop_back(); timelineBytes.offset = 0;
    timeline.currentFrame = 77;
    Check(!ReadPmmTimelineSettings(Read, &timelineBytes, timeline));
    Check(timeline.currentFrame == 77);
    Input mediaBytes;
    mediaBytes.byte(2);
    for (int index = 0; index < 256; ++index)
        mediaBytes.byte(index < 5 ? "a.wav"[index] : 0);
    mediaBytes.word(12); mediaBytes.word(24); mediaBytes.word(0x3f800000);
    for (int index = 0; index < 256; ++index)
        mediaBytes.byte(index < 5 ? "a.avi"[index] : 0);
    mediaBytes.word(1);
    mediaBytes.word(32); mediaBytes.word(64); mediaBytes.word(0x3f000000);
    for (int index = 0; index < 256; ++index)
        mediaBytes.byte(index < 5 ? "a.bmp"[index] : 0);
    mediaBytes.byte(1);
    PmmWaveReference wave;
    PmmBackgroundReference avi, picture;
    Check(ReadPmmWaveReference(Read, &mediaBytes, wave));
    Check(ReadPmmBackgroundReference(Read, &mediaBytes,
                                     PmmBackgroundKind::Avi, avi));
    Check(ReadPmmBackgroundReference(Read, &mediaBytes,
                                     PmmBackgroundKind::Picture, picture));
    Check(mediaBytes.offset == mediaBytes.bytes.size() && wave.enabled == 1 &&
          wave.pathBytes[0] == 'a' && avi.offsetX == 12 &&
          avi.offsetY == 24 && avi.scale == 1.0f && avi.enabled == 1 &&
          picture.offsetX == 32 && picture.scale == 0.5f &&
          picture.pathBytes[2] == 'b' && picture.enabled == 1);
    mediaBytes.bytes.pop_back(); mediaBytes.offset = 257 + 272;
    picture.offsetX = 77;
    Check(!ReadPmmBackgroundReference(Read, &mediaBytes,
                                      PmmBackgroundKind::Picture, picture));
    Check(picture.offsetX == 77);
    Input viewBytes;
    viewBytes.byte(2); viewBytes.byte(0); viewBytes.byte(1);
    viewBytes.word(0x41f00000); viewBytes.word(2);
    PmmViewSettings view;
    Check(ReadPmmViewSettings(Read, &viewBytes, view));
    Check(viewBytes.offset == 11 && view.fpsOverlay == 1 &&
          view.groundGrid == 0 && view.groundShadow == 1 &&
          view.fpsLimit == 30.0f && view.captureMode == 2);
    viewBytes.bytes.pop_back(); viewBytes.offset = 0;
    view.captureMode = 99;
    Check(!ReadPmmViewSettings(Read, &viewBytes, view));
    Check(view.captureMode == 99);
    Input physicsBytes;
    physicsBytes.word(5); physicsBytes.word(0x3f000000);
    physicsBytes.byte(1); physicsBytes.byte(2);
    physicsBytes.word(0x411ccccd); physicsBytes.word(10);
    physicsBytes.word(0); physicsBytes.word(0xbf800000);
    physicsBytes.word(0); physicsBytes.byte(1);
    PmmPhysicsSettings physics;
    Check(ReadPmmPhysicsSettings(Read, &physicsBytes, physics));
    Check(physicsBytes.offset == 31 && physics.accessoryRenderOrder == 5 &&
          physics.projectedShadowAmbient == 0.5f &&
          physics.projectedShadowBlend == 1 && physics.playbackMode == 2 &&
          physics.gravityNoise == 10 && physics.gravityDirection[1] == -1.0f &&
          physics.gravityNoiseEnabled == 1);
    physicsBytes.bytes.pop_back(); physicsBytes.offset = 0;
    physics.accessoryRenderOrder = 77;
    Check(!ReadPmmPhysicsSettings(Read, &physicsBytes, physics));
    Check(physics.accessoryRenderOrder == 77);
    Input appearanceBytes;
    appearanceBytes.word(10); appearanceBytes.word(20);
    appearanceBytes.word(30); appearanceBytes.byte(1);
    appearanceBytes.word(4); appearanceBytes.word(5);
    for (int index = 0; index < 16; ++index)
        appearanceBytes.word(0x3f800000);
    appearanceBytes.byte(1); appearanceBytes.byte(0);
    appearanceBytes.byte(1); appearanceBytes.word(200);
    PmmSceneAppearance appearance;
    Check(ReadPmmSceneAppearance(Read, &appearanceBytes, appearance));
    Check(appearanceBytes.offset == 92 && appearance.outlineColor[2] == 30 &&
          appearance.blackBackground == 1 && appearance.cameraParentModel == 4 &&
          appearance.cameraParentBone == 5 && appearance.cameraAttachmentBasis[15] == 1.0f &&
          appearance.followCamera == 1 && appearance.floorVisible == 1 &&
          appearance.maxFrame == 200);
    appearanceBytes.bytes.pop_back(); appearanceBytes.offset = 0;
    appearance.maxFrame = 77;
    Check(!ReadPmmSceneAppearance(Read, &appearanceBytes, appearance));
    Check(appearance.maxFrame == 77);
    Input accessory;
    accessory.word(10); accessory.word(2); accessory.word(20);
    accessory.byte(0x65);
    accessory.word(3); accessory.word(4);
    for (int index = 0; index < 7; ++index) accessory.word(0x3f800000);
    accessory.byte(1); accessory.byte(2);
    PmmAccessoryKey accessoryKey;
    Check(ReadPmmAccessoryKey(Read, &accessory, accessoryKey));
    Check(accessory.offset == 51 && accessoryKey.frame == 10 &&
          accessoryKey.visible == 1 && accessoryKey.opacity == 0.5f &&
          accessoryKey.parentModel == 3 && accessoryKey.parentBone == 4 &&
          accessoryKey.position[0] == 1.0f && accessoryKey.scale == 1.0f &&
          accessoryKey.shadowEnabled == 1 && accessoryKey.selected == 0);
    accessory.bytes.pop_back(); accessory.offset = 0;
    accessoryKey.frame = 99;
    Check(!ReadPmmAccessoryKey(Read, &accessory, accessoryKey));
    Check(accessoryKey.frame == 99);
    Input accessoryStateBytes;
    accessoryStateBytes.byte(0x65);
    accessoryStateBytes.word(3); accessoryStateBytes.word(4);
    for (int index = 0; index < 7; ++index)
        accessoryStateBytes.word(0x3f800000);
    accessoryStateBytes.byte(1); accessoryStateBytes.byte(1);
    PmmAccessoryState accessoryState;
    Check(ReadPmmAccessoryState(Read, &accessoryStateBytes,
                                PmmVersion::V2, accessoryState));
    Check(accessoryStateBytes.offset == 39 && accessoryState.visible == 1 &&
          accessoryState.opacity == 0.5f && accessoryState.parentModel == 3 &&
          accessoryState.position[2] == 1.0f && accessoryState.scale == 1.0f &&
          accessoryState.shadowEnabled == 1 && accessoryState.additiveBlend == 1);
    accessoryStateBytes.offset = 0;
    Check(ReadPmmAccessoryState(Read, &accessoryStateBytes,
                                PmmVersion::V1, accessoryState));
    Check(accessoryStateBytes.offset == 38 && accessoryState.additiveBlend == 0);
    accessoryStateBytes.bytes.pop_back(); accessoryStateBytes.offset = 0;
    accessoryState.scale = 99;
    Check(!ReadPmmAccessoryState(Read, &accessoryStateBytes,
                                 PmmVersion::V2, accessoryState));
    Check(accessoryState.scale == 99);
    Input display;
    display.word(7); display.word(1); display.word(9);
    display.byte(1); display.byte(1); display.byte(2);
    display.word(11); display.word(12); display.byte(1);
    PmmDisplayKey displayKey;
    Check(ReadPmmDisplayKey(Read, &display, PmmVersion::V2, 2, 1, displayKey));
    Check(display.offset == 24 && displayKey.frame == 7 &&
          displayKey.visible == 1 && displayKey.allocated == 1 &&
          displayKey.ikEnabled[0] == 1 && displayKey.ikEnabled[1] == 0 &&
          displayKey.rigidStates[0].modelIndex == 11 &&
          displayKey.rigidStates[0].boneIndex == 12);
    Input v1;
    v1.word(7); v1.word(1); v1.word(9);
    v1.byte(2); v1.byte(1); v1.byte(0); v1.byte(2);
    Check(ReadPmmDisplayKey(Read, &v1, PmmVersion::V1, 2, 1, displayKey));
    Check(v1.offset == 16 && displayKey.visible == 0 &&
          displayKey.allocated == 0 && displayKey.rigidStates.empty());
    display.bytes.pop_back(); display.offset = 0;
    displayKey.frame = 99;
    Check(!ReadPmmDisplayKey(Read, &display, PmmVersion::V2, 2, 1, displayKey));
    Check(displayKey.frame == 99);
    Check(!ReadPmmDisplayKey(Read, &v1, PmmVersion::V1, 100'001, 0, displayKey));
    Input selectionV1;
    selectionV1.byte(3); selectionV1.byte(1); selectionV1.word(5);
    for (int index = 0; index < 4; ++index) selectionV1.word(index + 10);
    selectionV1.byte(3); selectionV1.byte(1); selectionV1.byte(2);
    selectionV1.byte(0); selectionV1.word(15); selectionV1.word(100);
    PmmModelSelection selection;
    Check(ReadPmmModelSelection(Read, &selectionV1, PmmVersion::V1, 0, selection));
    Check(selectionV1.offset == selectionV1.bytes.size() &&
          selection.comboIndex == 3 && selection.loadComplete == 1 &&
          selection.selectedBone == 5 && selection.selectedMorphs[3] == 13 &&
          selection.groupFlags.size() == 3 && selection.groupFlags[0] == 1 &&
          selection.groupFlags[1] == 0 && selection.boneListPos == 15 &&
          selection.maxFrame == 100);
    Input selectionV2;
    selectionV2.byte(4); selectionV2.byte(2); selectionV2.word(7);
    for (int index = 0; index < 4; ++index) selectionV2.word(index + 20);
    selectionV2.byte(99); selectionV2.byte(1); selectionV2.byte(0);
    selectionV2.word(25); selectionV2.word(200);
    Check(ReadPmmModelSelection(Read, &selectionV2, PmmVersion::V2, 2, selection));
    Check(selectionV2.offset == selectionV2.bytes.size() &&
          selection.comboIndex == 4 && selection.loadComplete == 0 &&
          selection.selectedMorphs[3] == 23 && selection.groupFlags.size() == 2 &&
          selection.groupFlags[0] == 1 && selection.maxFrame == 200);
    selectionV2.bytes.pop_back(); selectionV2.offset = 0;
    selection.comboIndex = 55;
    Check(!ReadPmmModelSelection(Read, &selectionV2, PmmVersion::V2, 2, selection));
    Check(selection.comboIndex == 55);
}
