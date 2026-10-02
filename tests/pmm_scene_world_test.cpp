#include "mikudancestudio/pmm_scene_world.hpp"
#include <cmath>

using namespace mikudancestudio::format;
namespace {
bool Near(float actual, float expected) {
    return std::fabs(actual - expected) < 0.0001f;
}
}

int main() {
    ModelDocument model;
    model.kind = ModelKind::Pmd;
    model.pmd.bones.resize(3);
    model.pmd.bones[0].parent = -1;
    model.pmd.bones[1].parent = 0;
    model.pmd.bones[1].position[0] = 2.0f;
    model.pmd.bones[2].parent = 1;
    model.pmd.bones[2].position[0] = 4.0f;
    PmmEvaluatedModel pose;
    pose.bones.resize(3);
    for (auto& bone : pose.bones) bone.rotation[3] = 1.0f;
    pose.bones[0].translation[0] = 3.0f;
    pose.bones[1].translation[1] = 1.0f;
    std::vector<std::optional<PmmWorldMatrix>> world;
    std::array<float, 3> point{};
    if (!EvaluatePmmKinematicWorld(model, pose, world) || world.size() != 3 ||
        !PmmAttachedBonePoint(model, world, 2, point) ||
        !Near(point[0], 7.0f) || !Near(point[1], 1.0f)) return 1;
    PmmEvaluatedAccessory accessory;
    accessory.scale = 0.1f;
    accessory.position = {1, 2, 3};
    accessory.parentModel = -1;
    PmmWorldMatrix placement{};
    if (!PmmAccessoryWorld(accessory, nullptr, nullptr, placement) ||
        !Near(placement[12], 1) || !Near(placement[13], 2) ||
        !Near(placement[14], 3)) return 9;
    accessory.scale = 0.2f;
    accessory.rotation[2] = 1.57079632679f;
    if (!PmmAccessoryWorld(accessory, nullptr, nullptr, placement) ||
        !Near(placement[1], 2) || !Near(placement[4], -2)) return 11;
    accessory.scale = 0.1f;
    accessory.rotation[2] = 0;
    accessory.parentModel = 0;
    accessory.parentBone = 2;
    if (!PmmAccessoryWorld(accessory, &model, &world, placement) ||
        !Near(placement[12], 8) || !Near(placement[13], 3) ||
        !Near(placement[14], 3)) return 10;

    pose.bones[1].rotation = {0, 0, 0.70710678f, 0.70710678f};
    if (!EvaluatePmmKinematicWorld(model, pose, world) ||
        !PmmAttachedBonePoint(model, world, 2, point) ||
        !Near(point[0], 5.0f) || !Near(point[1], 3.0f)) return 2;

    model.pmd.bones[1].type = 8;
    if (!EvaluatePmmKinematicWorld(model, pose, world) ||
        !world[0] || world[1] || world[2] ||
        PmmAttachedBonePoint(model, world, 2, point) ||
        PmmAccessoryWorld(accessory, &model, &world, placement)) return 3;
    model.pmd.bones[1].type = 0;
    model.pmd.rigids.resize(1);
    model.pmd.rigids[0].boneIndex = 1;
    if (!EvaluatePmmKinematicWorld(model, pose, world) ||
        world[1] || world[2]) return 4;
    model.pmd.rigids.clear();

    model.pmd.bones[0].parent = 2;
    world.clear();
    if (EvaluatePmmKinematicWorld(model, pose, world) || !world.empty()) return 5;
    model.pmd.bones[0].parent = -1;
    model.pmd.bones[1].parent = 5;
    if (EvaluatePmmKinematicWorld(model, pose, world) || !world.empty()) return 6;
    model.pmd.bones[1].parent = 0;
    pose.bones[0].translation[0] = std::nanf("");
    if (EvaluatePmmKinematicWorld(model, pose, world) || !world.empty()) return 7;

    pose.bones[0].translation[0] = 0;
    model.kind = ModelKind::Pmx;
    model.pmx.bones.resize(3);
    for (std::size_t index = 0; index < 3; ++index)
        model.pmx.bones[index].fields = model.pmd.bones[index];
    model.pmx.bones[1].fields.flags = 0x0100;
    if (!EvaluatePmmKinematicWorld(model, pose, world) ||
        !world[0] || world[1] || world[2]) return 8;
    return 0;
}
