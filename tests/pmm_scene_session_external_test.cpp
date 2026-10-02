#include "mikudancestudio/scene_session.hpp"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>

using namespace mikudancestudio::format;
namespace {
struct Bytes {
    std::vector<std::uint8_t> data;
    std::size_t offset = 0;
};
int Read(void* context, void* destination, std::size_t length) {
    auto& bytes = *static_cast<Bytes*>(context);
    const auto count = std::min(length, bytes.data.size() - bytes.offset);
    if (count) std::memcpy(destination, bytes.data.data() + bytes.offset, count);
    bytes.offset += count;
    return static_cast<int>(count);
}
bool Write(void* context, const void* source, std::size_t length) {
    auto& bytes = *static_cast<Bytes*>(context);
    const auto* first = static_cast<const std::uint8_t*>(source);
    bytes.data.insert(bytes.data.end(), first, first + length);
    return true;
}
bool ResolveModel(void* context, std::uint8_t,
                  const std::array<char, 256>&, ModelDocument& model) {
    std::ifstream file(static_cast<const char*>(context), std::ios::binary);
    if (!file) return false;
    Bytes bytes;
    bytes.data.assign(std::istreambuf_iterator<char>{file}, {});
    return ReadModelDocument(Read, &bytes, model);
}
}
int main() {
    const char* path = std::getenv("MDS_PMM_SCENE_SESSION_FIXTURE");
    if (!path || !*path) return 77;
    std::ifstream file(path, std::ios::binary);
    if (!file) return 1;
    Bytes source;
    source.data.assign(std::istreambuf_iterator<char>{file}, {});
    SceneSession session;
    const char* modelPath = std::getenv("MDS_PMM_SCENE_MODEL_FIXTURE");
    if (!SceneSession::Load(Read, &source,
                            modelPath ? ResolveModel : nullptr,
                            const_cast<char*>(modelPath), session) ||
        session.Document().models.size() != 1 ||
        session.Document().models[0].boneKeys.dense.empty()) return 2;
    if (modelPath) {
        std::vector<std::optional<PmmWorldMatrix>> world;
        if (!session.KinematicWorld(session.Document().models[0].slot, world) ||
            world.size() != session.Document().models[0].layout.boneCount)
            return 8;
        const auto available = std::count_if(world.begin(), world.end(),
            [](const auto& bone) { return bone.has_value(); });
        if (available == 0) return 8;
        std::printf("kinematic bones=%zu/%zu\n", available, world.size());
        const auto boneIndex = static_cast<std::int32_t>(std::distance(
            world.begin(), std::find_if(world.begin(), world.end(),
                [](const auto& bone) { return bone.has_value(); })));
        Bytes probeSource = source;
        probeSource.offset = 0;
        SceneSession probe;
        if (!SceneSession::Load(Read, &probeSource, ResolveModel,
                                const_cast<char*>(modelPath), probe)) {
            std::fprintf(stderr, "camera probe load failed\n");
            return 9;
        }
        if (!probe.Edit([&](PmmSceneDocument& document) {
                document.cameraKeys.dense[0].parentModel =
                    document.models[0].slot;
                document.cameraKeys.dense[0].parentBone = boneIndex;
            })) {
            std::fprintf(stderr, "camera probe edit failed\n");
            return 9;
        }
        if (!probe.Seek(0)) {
            std::fprintf(stderr, "camera probe seek failed\n");
            return 9;
        }
        std::array<float, 3> attached{}, expected{};
        if (!probe.KinematicWorld(probe.Document().models[0].slot, world) ||
            !PmmAttachedBonePoint(*probe.Models()[0], world, boneIndex,
                                  expected)) {
            std::fprintf(stderr, "camera probe bone matrix failed\n");
            return 9;
        }
        if (!probe.CameraAttachmentPoint(attached)) {
            std::fprintf(stderr, "camera probe anchor failed: model=%d bone=%d\n",
                probe.Pose().camera.parentModel, probe.Pose().camera.parentBone);
            return 9;
        }
        for (int axis = 0; axis < 3; ++axis)
            if (std::fabs(attached[axis] - expected[axis]) > 0.0001f)
                return 9;
    }
    std::printf("v2 accessories=%zu\n", session.Document().accessories.size());
    const auto width = session.Document().envelope.settings.renderWidth;
    const auto boneX =
        session.Document().models[0].boneKeys.dense[0].position[0];
    const bool hasShadow = !session.Document().selfShadowKeys.dense.empty();
    const float shadowDistance = hasShadow ?
        session.Document().selfShadowKeys.dense[0].distance : 0.0f;
    const bool hasGravity = !session.Document().gravityKeys.dense.empty();
    const float gravityAcceleration = hasGravity ?
        session.Document().gravityKeys.dense[0].acceleration : 0.0f;
    if (!session.Edit([](PmmSceneDocument& scene) {
            ++scene.envelope.settings.renderWidth;
            scene.models[0].boneKeys.dense[0].position[0] += 1.0f;
            scene.models[0].bonePose[0].components[0] += 1.0f;
            if (!scene.selfShadowKeys.dense.empty())
                scene.selfShadowKeys.dense[0].distance += 0.001f;
            if (!scene.gravityKeys.dense.empty())
                scene.gravityKeys.dense[0].acceleration += 1.0f;
        })) return 3;
    if (!session.Seek(0) || !session.StartPlayback() ||
        !session.Advance(5.0f / 30.0f)) return 4;
    Bytes saved;
    if (!session.Save(Write, &saved)) return 5;
    SceneSession reloaded;
    if (!SceneSession::Load(Read, &saved, nullptr, nullptr, reloaded) ||
        reloaded.Document().envelope.settings.renderWidth != width + 1 ||
        reloaded.Document().models[0].boneKeys.dense[0].position[0] !=
            boneX + 1.0f ||
        (hasShadow &&
         reloaded.Document().selfShadowKeys.dense[0].distance !=
             shadowDistance + 0.001f) ||
        (hasGravity &&
         reloaded.Document().gravityKeys.dense[0].acceleration !=
             gravityAcceleration + 1.0f) ||
        !reloaded.Seek(0) || !reloaded.StartPlayback() ||
        !reloaded.Advance(5.0f / 30.0f)) return 6;
    if (hasGravity &&
        (reloaded.Pose().gravity.acceleration !=
             session.Pose().gravity.acceleration ||
         reloaded.Document().physics.gravityMagnitude !=
             session.Pose().gravity.acceleration ||
         reloaded.Document().physics.gravityNoise !=
             session.Pose().gravity.noise ||
         reloaded.Document().physics.gravityDirection !=
             session.Pose().gravity.direction ||
         reloaded.Document().physics.gravityNoiseEnabled !=
             session.Pose().gravity.noiseEnabled)) return 7;
    return 0;
}
