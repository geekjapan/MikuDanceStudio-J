#include "mikudancestudio/render_snapshot.hpp"
int main() {
    using namespace mikudancestudio;
    format::ModelDocument model;
    model.kind = format::ModelKind::Pmd;
    model.pmd.bones.resize(3);
    model.pmd.bones[1].parent = 0;
    model.pmd.vertices.resize(1);
    model.pmd.vertices[0].bone[0] = 1;
    model.pmd.vertices[0].bone[1] = 65535; // Zero weight is ignored.
    model.pmd.vertices[0].weightPercent = 100;
    model.pmd.indices = {0, 0, 0};
    const auto classify = [&] { return render::ClassifyBatchDependency(model, 0, 3); };
    if (classify() != render::BatchDependency::Independent) return 1;
    format::PmdIkData ik;
    ik.boneIndex = ik.targetBone = 2;
    ik.links = {0};
    model.pmd.ikChains.push_back(ik);
    if (classify() != render::BatchDependency::Ik) return 2;
    model.pmd.ikChains[0].links.clear();
    if (classify() != render::BatchDependency::Independent) return 3;
    format::RigidData rigid;
    rigid.boneIndex = 0;
    rigid.mode = 1;
    model.pmd.rigids.push_back(rigid);
    if (classify() != render::BatchDependency::Physics) return 4;
    model.pmd.rigids[0].mode = 0;
    if (classify() != render::BatchDependency::Independent) return 5;
    model.pmd.bones[0].type = 5;
    if (classify() != render::BatchDependency::Unsupported) return 6;
    model.pmd.bones[0].type = 0;
    model.pmd.bones[0].parent = 1;
    if (classify() != render::BatchDependency::Invalid) return 7;
    model.pmd.bones[0].parent = -1;
    model.pmd.vertices[0].weightPercent = 99;
    if (classify() != render::BatchDependency::Invalid) return 8;
    model.pmd.vertices[0].weightPercent = 100;
    model.pmd.indices[0] = 1;
    if (classify() != render::BatchDependency::Invalid ||
        render::ClassifyBatchDependency(model, 2, 3) != render::BatchDependency::Invalid)
        return 9;
    model.kind = format::ModelKind::Pmx;
    if (classify() != render::BatchDependency::Unsupported) return 10;
    return 0;
}
