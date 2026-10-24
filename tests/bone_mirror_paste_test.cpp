#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"
#include "mikudancestudio/ported_funcs.hpp"

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

namespace mds = mikudancestudio;
namespace mdl = mikudancestudio::mdl;

namespace {
int failures = 0;
std::vector<char> refreshes;
void Check(bool value, const char* message) {
    if (!value) { std::fprintf(stderr, "%s\n", message); ++failures; }
}
}

namespace mikudancestudio {
MMDApp::MMDApp() : state{} {}
MMDApp* g_Block = nullptr;
// Keep the pose/undo implementation real; observe only the UI boundaries.
void RebuildTimelineTrackPanel(MMDApp*) { refreshes.push_back('T'); }
void InvalidateSelectionReadouts(MMDApp*) { refreshes.push_back('R'); }
// The original element constructor is empty; the array constructor is real.
void IdentityCtor(void*) {}
void NotifyBonePhysicsMode(unsigned char*, int, unsigned char) {
    std::fputs("Unexpected physics mode change in pose undo\n", stderr);
    std::abort();
}
}

namespace {
// Input records follow the original clipboard ABI, independently of the helper.
struct CopiedPose { char name[20]; float position[3]; float rotation[4]; };
static_assert(sizeof(CopiedPose) == 0x30);

struct Fixture {
    std::unique_ptr<mds::MMDApp> app = std::make_unique<mds::MMDApp>();
    std::unique_ptr<mdl::ModelRecord> model = std::make_unique<mdl::ModelRecord>();
    std::array<mdl::BoneRecord, 8> bones{};
    std::array<unsigned char, 8> selected{}, physics{};
    std::array<CopiedPose, 4> copies{};
    Fixture() {
        app->ModelSlot(0) = reinterpret_cast<unsigned char*>(model.get());
        model->boneCount = static_cast<int>(bones.size());
        model->boneTable = bones.data();
        model->boneSelection = selected.data();
        model->bonePhysicsState = physics.data();
        model->undoState[0] = model->undoState[1] = 29;
        model->redoDirty = 1;
        app->BoneCopyRecords() = copies.data();
        for (int i = 0; i < static_cast<int>(bones.size()); ++i) {
            std::snprintf(bones[i].name, sizeof bones[i].name, "bone%d", i);
            bones[i].trans[0] = 10.0f + i;
            bones[i].trans[1] = 20.0f + i;
            bones[i].trans[2] = 30.0f + i;
            bones[i].rotQuat[0] = 0.1f;
            bones[i].rotQuat[1] = 0.2f;
            bones[i].rotQuat[2] = 0.3f;
            bones[i].rotQuat[3] = 0.9f;
            physics[i] = static_cast<unsigned char>(i + 2);
            selected[i] = 1;
        }
        refreshes.clear();
    }
    ~Fixture() {
        for (auto& ring : model->undoRings)
            for (auto& slot : ring.slots) {
                ::operator delete(slot.bonePose);
                ::operator delete(slot.auxiliaryPose);
            }
    }
    void Copy(int index, const char* name) {
        auto& pose = copies[index];
        strcpy_s(pose.name, name);
        pose.position[0] = 2.0f + index;
        pose.position[1] = 3.0f;
        pose.position[2] = 4.0f;
        pose.rotation[0] = 0.25f;
        pose.rotation[1] = 0.5f;
        pose.rotation[2] = 0.75f;
        pose.rotation[3] = 1.0f;
    }
    void Paste(int count) {
        app->state.copiedBoneCount = count;
        mds::PasteMirroredBonePose(app.get(), nullptr);
    }
};

void TestSidePair(const char* sourceName, const char* targetName) {
    Fixture f;
    strcpy_s(f.bones[3].name, sourceName);
    strcpy_s(f.bones[5].name, targetName);
    const auto oldTarget = f.bones[5];
    const auto oldSource = f.bones[3];
    f.Copy(0, sourceName);
    f.Paste(1);
    auto& undo = f.model->undoRings[0].slots[0];
    Check(f.model->undoState[0] == 0 && f.model->undoState[1] == 0,
          "Reverse paste must wrap both undo cursors at 30");
    Check(f.model->undoDirty == 1 && f.model->redoDirty == 0 &&
          undo.operation == 1 && undo.dirty == 1, "Reverse paste undo header");
    Check(f.model->selectedBone == 5 && f.selected[5] == 1 && f.selected[3] == 0,
          "Reverse paste must select the opposite-side target");
    Check(std::memcmp(f.bones[3].trans, oldSource.trans, sizeof oldSource.trans) == 0,
          "Paired source bone must remain unchanged");
    Check(f.bones[5].trans[0] == -2 && f.bones[5].trans[1] == 3 && f.bones[5].trans[2] == 4,
          "Mirror position X only");
    Check(f.bones[5].rotQuat[0] == 0.25f && f.bones[5].rotQuat[1] == -0.5f &&
          f.bones[5].rotQuat[2] == -0.75f && f.bones[5].rotQuat[3] == 1,
          "Mirror quaternion Y and Z only");
    Check(undo.bonePose[0].boneIndex == 5 && undo.bonePose[0].physicsDisabled == 7 &&
          std::memcmp(undo.bonePose[0].position, oldTarget.trans, sizeof oldTarget.trans) == 0 &&
          std::memcmp(undo.bonePose[0].rotation, oldTarget.rotQuat, sizeof oldTarget.rotQuat) == 0,
          "Undo snapshot must contain the target pose and prior physics state");
    Check(f.physics[5] == 1 && f.app->PhysicsResetPending() == 1 &&
          refreshes == std::vector<char>{'T', 'R'}, "Reverse paste refresh and physics flags");
    int frame = 17;
    mds::UndoModelEdit(reinterpret_cast<unsigned char*>(f.model.get()), frame);
    Check(std::memcmp(f.bones[5].trans, oldTarget.trans, sizeof oldTarget.trans) == 0 &&
          std::memcmp(f.bones[5].rotQuat, oldTarget.rotQuat, sizeof oldTarget.rotQuat) == 0 &&
          f.physics[5] == 7 && frame == 17, "Undo must restore the old target pose");
    mds::RedoModelEdit(reinterpret_cast<unsigned char*>(f.model.get()), frame);
    Check(f.bones[5].trans[0] == -2 && f.bones[5].rotQuat[1] == -0.5f &&
          f.physics[5] == 1, "Redo must restore the mirrored pose");
}
}

int main() {
    // Expected side mappings come from x64 RVA 0x44580..0x446E9:
    // search the exact-name bone for SJIS left/right, then compare suffixes.
    TestSidePair("\x8D\xB6" "arm", "\x89\x45" "arm");
    TestSidePair("\x89\x45" "arm", "\x8D\xB6" "arm");
    TestSidePair("A\x8D\xB6" "arm", "B\x89\x45" "arm");
    {
        Fixture f;
        strcpy_s(f.bones[3].name, "\x8D\xB6" "arm");
        strcpy_s(f.bones[5].name, "\x89\x45" "leg");
        f.Copy(0, f.bones[3].name);
        f.Paste(1);
        Check(f.model->selectedBone == 3 && f.bones[3].trans[0] == -2 &&
              f.bones[5].trans[0] == 15, "Different suffix must fall back to exact-name bone");
    }
    {
        Fixture f;
        f.Copy(0, "bone4");
        f.Copy(1, "missing");
        f.Paste(2);
        Check(f.bones[4].trans[0] == -2 && f.model->selectedBone == 4 &&
              refreshes == std::vector<char>{'T', 'R'}, "Center bone fallback and missing-name skip");
        const auto& slot = f.model->undoRings[0].slots[0];
        const mdl::BonePoseSnapshot zero{};
        Check(slot.dirty == 2 && std::memcmp(&slot.bonePose[1], &zero, sizeof zero) == 0,
              "Skipped clipboard entry must retain its zeroed undo slot");
    }
    {
        Fixture f;
        f.Paste(0);
        Check(f.model->undoState[0] == 29 && f.model->redoDirty == 1 &&
              f.selected[0] == 1 && refreshes.empty() && f.app->PhysicsResetPending() == 0,
              "Empty clipboard must leave selection, undo and refresh state unchanged");
    }
    return failures == 0 ? 0 : 1;
}
