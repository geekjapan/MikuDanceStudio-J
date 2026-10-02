#include "pmm_format_win.hpp"
#include "pmm_io_common.hpp"
#include "mikudancestudio/pmm_document.hpp"
#include "mikudancestudio/pmm_scene_document.hpp"
#include "mikudancestudio/pmm_scene_evaluation.hpp"
#include "mikudancestudio/model_reader.hpp"
#include <array>
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iterator>
#include <string>
#include <fcntl.h>
#include <io.h>
#include <process.h>
#include <vector>
namespace {
void Check(bool condition) { if (!condition) std::abort(); }
struct Input {
    std::vector<std::uint8_t> bytes;
    std::size_t offset = 0;
};
int Read(void* context, void* destination, std::size_t length) {
    auto& input = *static_cast<Input*>(context);
    const auto available = input.bytes.size() - input.offset;
    const auto count = length < available ? length : available;
    if (count) std::memcpy(destination, input.bytes.data() + input.offset, count);
    input.offset += count;
    return static_cast<int>(count);
}
bool Write(void* context, const void* source, std::size_t length) {
    auto& bytes = *static_cast<std::vector<std::uint8_t>*>(context);
    const auto* first = static_cast<const std::uint8_t*>(source);
    bytes.insert(bytes.end(), first, first + length);
    return true;
}
bool ResolveV1(void* context, std::uint8_t,
               const std::array<char, 20>&,
               const std::array<char, 256>& rawPath,
               mikudancestudio::format::PmmModelLayout& layout) {
    const auto* root = static_cast<const std::filesystem::path*>(context);
    const auto length = std::find(rawPath.begin(), rawPath.end(), '\0') - rawPath.begin();
    const std::string path(rawPath.data(), length);
    const auto last = path.find_last_of("\\/");
    const auto name = path.substr(last == std::string::npos ? 0 : last + 1);
    std::ifstream stream(*root / "Model" / name, std::ios::binary);
    if (!stream) return false;
    Input input;
    input.bytes.assign(std::istreambuf_iterator<char>{stream}, {});
    mikudancestudio::format::ModelDocument model;
    if (!mikudancestudio::format::ReadModelDocument(Read, &input, model))
        return false;
    if (model.kind != mikudancestudio::format::ModelKind::Pmd) return false;
    layout.boneCount = static_cast<std::uint32_t>(model.pmd.bones.size());
    layout.morphCount = static_cast<std::uint32_t>(model.pmd.morphs.size());
    layout.ikCount = static_cast<std::uint32_t>(model.pmd.ikChains.size());
    return true;
}
void CheckSceneParity(const mikudancestudio::format::PmmSceneDocument& memory,
                      const mikudancestudio::format::PmmSceneDocument& file) {
    Check(memory.sections.size() == file.sections.size() &&
          memory.models.size() == file.models.size() &&
          memory.accessories.size() == file.accessories.size() &&
          memory.timeline.currentFrame == file.timeline.currentFrame &&
          memory.view.captureMode == file.view.captureMode &&
          memory.cameraKeys.dense.size() == file.cameraKeys.dense.size() &&
          memory.lightKeys.sparse.size() == file.lightKeys.sparse.size());
    for (std::size_t index = 0; index < memory.models.size(); ++index) {
        const auto& left = memory.models[index];
        const auto& right = file.models[index];
        Check(left.slot == right.slot && left.path == right.path &&
              left.layout.boneCount == right.layout.boneCount &&
              left.layout.morphCount == right.layout.morphCount &&
              left.layout.ikCount == right.layout.ikCount &&
              left.selection.maxFrame == right.selection.maxFrame &&
              left.boneKeys.dense.size() == right.boneKeys.dense.size() &&
              left.boneKeys.sparse.size() == right.boneKeys.sparse.size() &&
              left.morphKeys.sparse.size() == right.morphKeys.sparse.size() &&
              left.displayKeys.sparse.size() == right.displayKeys.sparse.size() &&
              left.bonePose.size() == right.bonePose.size());
    }
    for (std::size_t index = 0; index < memory.accessories.size(); ++index) {
        const auto& left = memory.accessories[index];
        const auto& right = file.accessories[index];
        Check(left.slot == right.slot && left.path == right.path &&
              left.keyRecords.sparse.size() == right.keyRecords.sparse.size() &&
              left.state.parentModel == right.state.parentModel);
    }
}
template<class Runtime, class Disk, class Reader, class Compare>
void CheckRuntimeTrack(int fd,
                       const mikudancestudio::format::PmmKeyTrack<Disk>& track,
                       Reader read, Compare compare) {
    const auto check = [&](std::size_t offset, const Disk& expected) {
        Check(_lseeki64(fd, static_cast<__int64>(offset), SEEK_SET) ==
              static_cast<__int64>(offset));
        Runtime actual{};
        read(fd, actual);
        Check(actual.frame == expected.frame &&
              actual.previous == expected.previous &&
              actual.next == expected.next);
        compare(actual, expected);
    };
    Check(track.denseRecordOffsets.size() == track.dense.size());
    for (std::size_t index = 0; index < track.dense.size(); ++index)
        check(track.denseRecordOffsets[index], track.dense[index]);
    for (const auto& key : track.sparse)
        check(key.recordOffset, key.value);
}
void CheckRuntimeRecordParity(const char* path,
                              const mikudancestudio::format::PmmSceneDocument& scene) {
    using namespace mikudancestudio;
    const auto version = scene.envelope.header.version == format::PmmVersion::V1
        ? pmm_io::PmmStream::V1 : pmm_io::PmmStream::V2;
    const int fd = _open(path, _O_BINARY | _O_RDONLY);
    Check(fd >= 0);
    const auto display = [&](std::size_t offset,
                             const format::PmmDisplayKey& expected,
                             const format::PmmSceneModel& model) {
        Check(_lseeki64(fd, static_cast<__int64>(offset), SEEK_SET) ==
              static_cast<__int64>(offset));
        format::PmmDisplayKey actual;
        Check(pmm_io::ReadPmmDisplayKey(fd, version, model.layout.ikCount,
                                        model.rigidCount, actual));
        Check(actual.frame == expected.frame &&
              actual.previous == expected.previous &&
              actual.next == expected.next &&
              actual.visible == expected.visible &&
              actual.allocated == expected.allocated &&
              actual.ikEnabled == expected.ikEnabled &&
              actual.rigidStates.size() == expected.rigidStates.size());
        for (std::size_t index = 0; index < actual.rigidStates.size(); ++index)
            Check(actual.rigidStates[index].modelIndex ==
                      expected.rigidStates[index].modelIndex &&
                  actual.rigidStates[index].boneIndex ==
                      expected.rigidStates[index].boneIndex);
    };
    for (const auto& model : scene.models) {
        const auto bone = [&](int handle, mdl::BoneKey& value) {
            if (version == pmm_io::PmmStream::V1)
                pmm_io::ReadPmmBoneKey<pmm_io::PmmStream::V1>(handle, value);
            else
                pmm_io::ReadPmmBoneKey<pmm_io::PmmStream::V2>(handle, value);
        };
        CheckRuntimeTrack<mdl::BoneKey>(fd, model.boneKeys, bone,
            [&](const auto& actual, const auto& disk) {
                Check(std::memcmp(actual.interpolation, disk.interpolation.data(), 16) == 0 &&
                      std::memcmp(actual.position, disk.position.data(), sizeof actual.position) == 0 &&
                      std::memcmp(actual.rotation, disk.rotation.data(), sizeof actual.rotation) == 0 &&
                      actual.allocated == disk.allocated &&
                      (version == pmm_io::PmmStream::V1 ||
                       actual.physicsDisabled == disk.physicsDisabled));
            });
        CheckRuntimeTrack<mdl::MorphKey>(fd, model.morphKeys,
            pmm_io::ReadPmmMorphKey,
            [](const auto& actual, const auto& disk) {
                Check(actual.value == disk.value && actual.allocated == disk.allocated);
            });
        Check(model.displayKeys.denseRecordOffsets.size() ==
              model.displayKeys.dense.size());
        for (std::size_t index = 0; index < model.displayKeys.dense.size(); ++index)
            display(model.displayKeys.denseRecordOffsets[index],
                    model.displayKeys.dense[index], model);
        for (const auto& key : model.displayKeys.sparse)
            display(key.recordOffset, key.value, model);
    }
    CheckRuntimeTrack<mdl::CameraKey>(fd, scene.cameraKeys,
        [&](int handle, mdl::CameraKey& value) {
            if (version == pmm_io::PmmStream::V1)
                pmm_io::ReadPmmCameraKey<pmm_io::PmmStream::V1>(handle, value);
            else
                pmm_io::ReadPmmCameraKey<pmm_io::PmmStream::V2>(handle, value);
        }, [&](const auto& actual, const auto& disk) {
            Check(actual.distance == disk.distance &&
                  std::memcmp(actual.eye, disk.eye.data(), sizeof actual.eye) == 0 &&
                  std::memcmp(actual.target, disk.target.data(), sizeof actual.target) == 0 &&
                  std::memcmp(actual.interpolation, disk.interpolation.data(),
                              sizeof actual.interpolation) == 0 &&
                  actual.perspective == disk.perspective && actual.fov == disk.fov &&
                  actual.selected == disk.selected &&
                  (version == pmm_io::PmmStream::V1 ||
                   (actual.parentModel == disk.parentModel &&
                    actual.parentBone == disk.parentBone)));
        });
    CheckRuntimeTrack<mdl::LightKey>(fd, scene.lightKeys, pmm_io::ReadPmmLightKey,
        [](const auto& actual, const auto& disk) {
            Check(std::memcmp(actual.color, disk.color.data(), sizeof actual.color) == 0 &&
                  std::memcmp(actual.direction, disk.direction.data(),
                              sizeof actual.direction) == 0 &&
                  actual.selected == disk.selected);
        });
    for (const auto& accessory : scene.accessories)
        CheckRuntimeTrack<mdl::AccessoryKey>(fd, accessory.keyRecords,
            pmm_io::ReadPmmAccessoryKey,
            [](const auto& actual, const auto& disk) {
                Check(actual.visible == disk.visible &&
                      actual.opacity == disk.opacity &&
                      actual.parentModel == disk.parentModel &&
                      actual.parentBone == disk.parentBone &&
                      std::memcmp(actual.position, disk.position.data(),
                                  sizeof actual.position) == 0 &&
                      std::memcmp(actual.rotation, disk.rotation.data(),
                                  sizeof actual.rotation) == 0 &&
                      actual.scale == disk.scale &&
                      actual.shadowEnabled == disk.shadowEnabled &&
                      actual.selected == disk.selected);
            });
    if (version == pmm_io::PmmStream::V2)
        CheckRuntimeTrack<mdl::GravityKey>(fd, scene.gravityKeys,
            pmm_io::ReadPmmGravityKey,
            [](const auto& actual, const auto& disk) {
                Check(actual.noiseEnabled == disk.noiseEnabled &&
                      actual.noise == disk.noise &&
                      actual.acceleration == disk.acceleration &&
                      std::memcmp(actual.direction, disk.direction.data(),
                                  sizeof actual.direction) == 0 &&
                      actual.selected == disk.selected);
            });
    CheckRuntimeTrack<mdl::SelfShadowKey>(fd, scene.selfShadowKeys,
        pmm_io::ReadPmmSelfShadowKey,
        [](const auto& actual, const auto& disk) {
            Check(actual.mode == disk.mode && actual.distance == disk.distance &&
                  actual.selected == disk.selected);
        });
    _close(fd);
}
void CheckVersion(bool v1) {
    Input input;
    input.bytes.resize(30, 0);
    std::memcpy(input.bytes.data(), "Polygon Movie maker", 19);
    std::memcpy(input.bytes.data() + 20, v1 ? "0001" : "0002", 5);
    const auto word = [&input](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            input.bytes.push_back(static_cast<std::uint8_t>(value >> shift));
    };
    word(640); word(480); word(200); word(0x42340000);
    input.bytes.insert(input.bytes.end(), v1 ? 6 : 7, 0);
    input.bytes.push_back(0); input.bytes.push_back(v1 ? 1 : 0);
    if (v1) input.bytes.insert(input.bytes.end(), 20, 'M');
    input.bytes.insert(input.bytes.end(), {1, 2, 3, 4});
    int pipe[2]{};
    Check(_pipe(pipe, 4096, _O_BINARY) == 0);
    Check(_write(pipe[1], input.bytes.data(),
                 static_cast<unsigned>(input.bytes.size())) ==
          static_cast<int>(input.bytes.size()));
    _close(pipe[1]);
    mikudancestudio::format::PmmDocument memory, file;
    Check(mikudancestudio::format::ReadPmmDocument(Read, &input, memory));
    Check(mikudancestudio::format::ReadPmmDocument(
          mikudancestudio::ReadPmmFileBytesResult, &pipe[0], file));
    Check(memory.header.version == file.header.version &&
          memory.settings.renderWidth == file.settings.renderWidth &&
          memory.v1ModelNames == file.v1ModelNames &&
          memory.prefixBytes == file.prefixBytes &&
          memory.remainingBytes == file.remainingBytes);
    _close(pipe[0]);
}
void CheckExternal() {
    const char* path = std::getenv("MDS_PMM_FIXTURE");
    if (!path || !*path) return;
    std::ifstream stream(path, std::ios::binary);
    Check(stream.good());
    std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>{stream}, {});
    Input input{bytes};
    mikudancestudio::format::PmmDocument memory, file;
    Check(mikudancestudio::format::ReadPmmDocument(Read, &input, memory));
    int fd = _open(path, _O_BINARY | _O_RDONLY);
    Check(fd >= 0);
    Check(mikudancestudio::format::ReadPmmDocument(
          mikudancestudio::ReadPmmFileBytesResult, &fd, file));
    _close(fd);
    Check(memory.header.version == file.header.version &&
          memory.settings.renderWidth == file.settings.renderWidth &&
          memory.settings.renderHeight == file.settings.renderHeight &&
          memory.selectedModelSlot == file.selectedModelSlot &&
          memory.modelCount == file.modelCount &&
          memory.v1ModelNames == file.v1ModelNames &&
          memory.prefixBytes == file.prefixBytes &&
          memory.remainingBytes == file.remainingBytes);
    std::vector<std::uint8_t> roundTrip;
    Check(mikudancestudio::format::WritePmmDocument(Write, &roundTrip, file));
    Check(roundTrip == bytes);
    if (file.header.version == mikudancestudio::format::PmmVersion::V2) {
        mikudancestudio::format::PmmSceneDocument scene, fromFile;
        input.offset = 0;
        Check(mikudancestudio::format::ReadPmmSceneDocument(
              Read, &input, nullptr, nullptr, scene));
        fd = _open(path, _O_BINARY | _O_RDONLY);
        Check(fd >= 0);
        Check(mikudancestudio::format::ReadPmmSceneDocument(
              mikudancestudio::ReadPmmFileBytesResult, &fd,
              nullptr, nullptr, fromFile));
        _close(fd);
        Check(scene.models.size() == file.modelCount &&
              scene.envelope.remainingBytes == file.remainingBytes &&
              scene.sections.size() == fromFile.sections.size() &&
              scene.sections.front().kind ==
                  mikudancestudio::format::PmmSceneSectionKind::Header);
        CheckSceneParity(scene, fromFile);
        CheckRuntimeRecordParity(path, scene);
        std::vector<std::uint8_t> sceneRoundTrip;
        Check(mikudancestudio::format::WritePmmSceneDocument(
            Write, &sceneRoundTrip, scene, nullptr, nullptr));
        Check(sceneRoundTrip == bytes);
        std::size_t selectorChecks = 0;
        std::size_t boundedWindows = 0;
        for (const std::uint32_t frame : {0u, 1u, 10u, 30u, 100u}) {
            mikudancestudio::format::PmmSceneEvaluation evaluated;
            Check(mikudancestudio::format::EvaluatePmmSceneFrame(
                scene, frame, evaluated));
            Check(evaluated.models.size() == scene.models.size());
            for (std::size_t i = 0; i < scene.models.size(); ++i) {
                Check(evaluated.models[i].selectors.size() ==
                      scene.models[i].rigidCount);
                selectorChecks += evaluated.models[i].selectors.size();
                for (const auto& selector : evaluated.models[i].selectors)
                    if (selector.windowStart != 0 || selector.windowEnd != 0)
                        ++boundedWindows;
            }
        }
        std::printf("PMM v2 selector evaluations: %zu, bounded windows: %zu\n",
                    selectorChecks, boundedWindows);
        for (std::size_t index = 0; index < scene.sections.size(); ++index) {
            const auto& section = scene.sections[index];
            const auto& compared = fromFile.sections[index];
            Check(section.kind == compared.kind && section.offset == compared.offset &&
                  section.size == compared.size);
            if (section.kind == mikudancestudio::format::PmmSceneSectionKind::Tail ||
                section.size == 0) continue;
            Input truncated{bytes};
            truncated.bytes.resize(section.offset + section.size - 1);
            Check(!mikudancestudio::format::ReadPmmSceneDocument(
                  Read, &truncated, nullptr, nullptr, fromFile));
        }
    } else if (const char* modelRoot = std::getenv("MDS_PMM_MODEL_ROOT")) {
        auto root = std::filesystem::path(modelRoot);
        mikudancestudio::format::PmmSceneDocument scene, fromFile;
        input.offset = 0;
        Check(mikudancestudio::format::ReadPmmSceneDocument(
              Read, &input, ResolveV1, &root, scene));
        fd = _open(path, _O_BINARY | _O_RDONLY);
        Check(fd >= 0);
        Check(mikudancestudio::format::ReadPmmSceneDocument(
              mikudancestudio::ReadPmmFileBytesResult, &fd,
              ResolveV1, &root, fromFile));
        _close(fd);
        Check(scene.models.size() == file.modelCount &&
              scene.sections.size() == fromFile.sections.size());
        CheckSceneParity(scene, fromFile);
        CheckRuntimeRecordParity(path, scene);
        for (const std::uint32_t frame : {0u, 1u, 10u, 30u, 100u}) {
            mikudancestudio::format::PmmSceneEvaluation evaluated;
            Check(mikudancestudio::format::EvaluatePmmSceneFrame(
                scene, frame, evaluated));
            Check(evaluated.frame == frame &&
                  evaluated.models.size() == scene.models.size());
            for (std::size_t i = 0; i < scene.models.size(); ++i)
                Check(evaluated.models[i].slot == scene.models[i].slot &&
                      evaluated.models[i].morphValues.size() ==
                          scene.models[i].layout.morphCount &&
                      evaluated.models[i].ikEnabled.size() ==
                          scene.models[i].layout.ikCount);
        }
        std::vector<std::uint8_t> written;
        Check(mikudancestudio::format::WritePmmSceneDocument(
            Write, &written, scene, ResolveV1, &root));
        Check(written == bytes);
        scene.envelope.settings.renderWidth += 1;
        scene.timeline.currentFrame += 1;
        scene.lightState[0] += 0.125f;
        std::vector<bool> editable(bytes.size());
        const auto allow = [&](std::size_t offset, std::size_t count) {
            Check(offset <= editable.size() && count <= editable.size() - offset);
            for (std::size_t i = 0; i < count; ++i) editable[offset + i] = true;
        };
        allow(30, 4);
        allow(scene.timelineOffset, 4);
        allow(scene.lightStateOffset, 4);
        bool changedBone = false, changedMorph = false, changedIk = false;
        for (auto& model : scene.models) {
            if (!changedBone && !model.bonePose.empty()) {
                model.bonePose[0].components[0] += 0.25f;
                allow(model.bonePoseOffset, 4);
                changedBone = true;
            }
            if (!changedMorph && !model.morphPose.empty()) {
                model.morphPose[0] += 0.25f;
                allow(model.morphPoseOffset, 4);
                changedMorph = true;
            }
            if (!changedIk && !model.ikPose.empty()) {
                model.ikPose[0] ^= 1;
                allow(model.ikPoseOffset, 1);
                changedIk = true;
            }
        }
        Check(changedBone && changedMorph && changedIk);
        written.clear();
        Check(mikudancestudio::format::WritePmmSceneDocument(
            Write, &written, scene, ResolveV1, &root));
        Check(written.size() == bytes.size());
        for (std::size_t i = 0; i < bytes.size(); ++i)
            Check(editable[i] || written[i] == bytes[i]);
        Input edited{written};
        mikudancestudio::format::PmmSceneDocument reloaded;
        Check(mikudancestudio::format::ReadPmmSceneDocument(
            Read, &edited, ResolveV1, &root, reloaded));
        const auto savedPath = std::filesystem::temp_directory_path() /
            ("mds-pmm-edited-" + std::to_string(_getpid()) + ".pmm");
        {
            std::ofstream saved(savedPath, std::ios::binary | std::ios::trunc);
            Check(saved.good());
            saved.write(reinterpret_cast<const char*>(written.data()),
                        static_cast<std::streamsize>(written.size()));
            Check(saved.good());
        }
        fd = _wopen(savedPath.c_str(), _O_BINARY | _O_RDONLY);
        Check(fd >= 0);
        mikudancestudio::format::PmmSceneDocument fromSavedFile;
        Check(mikudancestudio::format::ReadPmmSceneDocument(
            mikudancestudio::ReadPmmFileBytesResult, &fd, ResolveV1,
            &root, fromSavedFile));
        _close(fd);
        std::filesystem::remove(savedPath);
        CheckSceneParity(reloaded, fromSavedFile);
        Check(reloaded.envelope.settings.renderWidth ==
                  scene.envelope.settings.renderWidth &&
              reloaded.timeline.currentFrame == scene.timeline.currentFrame &&
              reloaded.lightState[0] == scene.lightState[0]);
        for (std::size_t i = 0; i < scene.models.size(); ++i) {
            Check(reloaded.models[i].bonePose.size() == scene.models[i].bonePose.size() &&
                  reloaded.models[i].morphPose == scene.models[i].morphPose &&
                  reloaded.models[i].ikPose == scene.models[i].ikPose);
            for (std::size_t j = 0; j < scene.models[i].bonePose.size(); ++j)
                Check(reloaded.models[i].bonePose[j].components ==
                          scene.models[i].bonePose[j].components &&
                      reloaded.models[i].bonePose[j].flags ==
                          scene.models[i].bonePose[j].flags);
        }
        for (std::size_t index = 0; index < scene.sections.size(); ++index) {
            const auto& section = scene.sections[index];
            const auto& compared = fromFile.sections[index];
            Check(section.kind == compared.kind && section.offset == compared.offset &&
                  section.size == compared.size);
            if (section.kind == mikudancestudio::format::PmmSceneSectionKind::Tail ||
                section.size == 0) continue;
            Input truncated{bytes};
            truncated.bytes.resize(section.offset + section.size - 1);
            Check(!mikudancestudio::format::ReadPmmSceneDocument(
                  Read, &truncated, ResolveV1, &root, fromFile));
        }
    }
}
}
int main() { CheckVersion(true); CheckVersion(false); CheckExternal(); }
