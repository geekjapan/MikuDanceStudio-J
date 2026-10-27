#include "mikudancestudio/d3dx_dyn.hpp"
#include <array>
#include <iomanip>
#include <iostream>
#include <vector>

namespace mikudancestudio {
namespace mdl {
struct BoneRecord {
    float matInit[16];
    float position[3];
};
struct ModelRecord {
    int centerBone;
    int selectedBone;
    std::vector<BoneRecord> bones;
};
ModelRecord* Mdl(unsigned char* model) { return reinterpret_cast<ModelRecord*>(model); }
BoneRecord* Bones(unsigned char* model) { return Mdl(model)->bones.data(); }
}
enum class CameraAttachmentReference { Origin, ModelRoot, SelectedBone };
struct MMDApp {
    std::vector<mdl::ModelRecord> models;
    int parent, parentBone, selected;
    CameraAttachmentReference reference;
    std::array<float, 9> camera;
    d3dx::D3DXMATRIXF basis{};
    int CameraParentModel() { return parent; }
    int CameraParentBone() { return parentBone; }
    CameraAttachmentReference CameraReferenceMode() { return reference; }
    unsigned char* SelectedModel() { return reinterpret_cast<unsigned char*>(&models[selected]); }
    d3dx::D3DXMATRIXF& CameraAttachmentBasis() { return basis; }
    float& CameraPositionX() { return camera[0]; }
    float& CameraPositionY() { return camera[1]; }
    float& CameraPositionZ() { return camera[2]; }
    float& ViewOffsetX() { return camera[3]; }
    float& ViewOffsetY() { return camera[4]; }
    float& CameraDistance() { return camera[5]; }
    float CameraPitch() { return camera[6]; }
    float CameraYaw() { return camera[7]; }
    float CameraRoll() { return camera[8]; }
};
unsigned char* ModelAt(MMDApp* app, int slot) {
    return reinterpret_cast<unsigned char*>(&app->models[slot]);
}
#include "camera_reload_body.inc"
}

int main() {
    using namespace mikudancestudio;
    MMDApp app{};
    int reference, count;
    if (!(std::cin >> app.parent >> app.parentBone >> app.selected >> reference >> count)
        || count <= 0 || count > 255)
        return 1;
    app.reference = static_cast<CameraAttachmentReference>(reference);
    for (float& value : app.camera) std::cin >> value;
    app.models.resize(count);
    for (auto& model : app.models) {
        int bones;
        std::cin >> model.centerBone >> model.selectedBone >> bones;
        if (bones <= 0 || bones > 100000) return 1;
        model.bones.resize(bones);
        for (auto& bone : model.bones) {
            for (float& value : bone.matInit) std::cin >> value;
            for (float& value : bone.position) std::cin >> value;
        }
    }
    if (!std::cin) return 1;
    PostModelReload(&app);
    std::cout << std::setprecision(9);
    for (float value : app.camera) std::cout << value << ' ';
    for (const auto& row : app.basis.m)
        for (float value : row) std::cout << value << ' ';
    std::cout << '\n';
}
