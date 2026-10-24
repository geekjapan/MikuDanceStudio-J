// Bone-panel reverse paste (x64 RVA 0x44313..0x449AB, x86 0x0048203D).
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <cstdint>
#include <cstring>
#include <new>

#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"
#include "mikudancestudio/ported_funcs.hpp"
#include "mikudancestudio/panel_controls.hpp"

namespace mikudancestudio {
namespace {
using BoneCopyRecord = mdl::BonePoseClipboardRecord;

// 32-bit multiply with the original's overflow idiom (mul/seto/neg/or):
// returns 0xFFFFFFFF when the product overflows (cases 496/497/498).
static std::uint32_t MulOrMax(std::uint32_t a, std::uint32_t b) {
    const std::uint64_t r = static_cast<std::uint64_t>(a) * b;
    return r > 0xFFFFFFFFull ? 0xFFFFFFFFu : static_cast<std::uint32_t>(r);
}

// Shift-JIS left/right markers: x64 0x7FF7CB54D9BC / 0x7FF7CB54D9C0.
static const char kBoneNameNeedleLeft[] = "\x8D\xB6";
static const char kBoneNameNeedleRight[] = "\x89\x45";

}  // namespace

// Paste the mirrored copied pose, preserving each target pose in the undo slot.
void PasteMirroredBonePose(MMDApp* app, HWND hwnd) {
    if (app->state.copiedBoneCount == 0) {
        return;  // jz def_47E903 (no-op)
    }
    unsigned char* model = app->SelectedModel();
    auto* modelRecord = mikudancestudio::mdl::Mdl(model);
    const std::int32_t boneCount = modelRecord->boneCount;
    unsigned char* selected = modelRecord->boneSelection;
    for (std::int32_t i = 0; i < boneCount; ++i) {
        selected[i] = 0;
    }
    EnableWindow(GetDlgItem(hwnd, panel::kUndoButton), TRUE);
    EnableWindow(GetDlgItem(hwnd, panel::kRedoButton), FALSE);
    modelRecord->undoDirty = 1;
    modelRecord->redoDirty = 0;
    ++modelRecord->undoState[0];
    if (modelRecord->undoState[0] >= 0x1E) {
        modelRecord->undoState[0] = 0;
    }
    const std::int32_t undoCursor = modelRecord->undoState[0];
    modelRecord->undoState[1] = undoCursor;
    auto& undo = modelRecord->undoRings[0].slots[undoCursor];
    undo.operation = 1;
    undo.dirty = app->state.copiedBoneCount;
    unsigned char* undoPoseBytes =
        reinterpret_cast<unsigned char*>(undo.bonePose);
    if (undoPoseBytes != nullptr) {
        ::operator delete(undoPoseBytes);
        undo.bonePose = nullptr;
    }
    const std::int32_t count = app->state.copiedBoneCount;
    undoPoseBytes = static_cast<unsigned char*>(::operator new(
        MulOrMax(static_cast<std::uint32_t>(count), 0x24u)));
    if (undoPoseBytes != nullptr) {
        ConstructArrayElements(undoPoseBytes, 0x24,
                               static_cast<std::uint32_t>(count),
                               &IdentityCtor);
    }
    undo.bonePose = reinterpret_cast<mikudancestudio::mdl::BonePoseSnapshot*>(
        undoPoseBytes);
    memset(undoPoseBytes, 0, static_cast<std::size_t>(count) * 0x24u);

    auto& records =
        reinterpret_cast<BoneCopyRecord*&>(app->BoneCopyRecords());
    for (std::int32_t copiedPoseIndex = 0; copiedPoseIndex < count;
         ++copiedPoseIndex) {
        model = app->SelectedModel();
        modelRecord = mikudancestudio::mdl::Mdl(model);
        const std::int32_t nBones = modelRecord->boneCount;
        selected = modelRecord->boneSelection;
        mikudancestudio::mdl::BoneRecord* const bones = modelRecord->boneTable;
        unsigned char* physicsState = modelRecord->bonePhysicsState;
        const BoneCopyRecord& src = records[copiedPoseIndex];
        // Resolve the copied name before looking for its opposite-side suffix.
        std::int32_t sourceBoneIndex = -1;
        for (std::int32_t k = 0; k < nBones; ++k) {
            if (strcmp(bones[k].name, src.name) == 0) {
                sourceBoneIndex = k;
                break;
            }
        }
        if (sourceBoneIndex < 0) {
            continue;  // no exact-name bone: record skipped
        }
        std::int32_t targetBoneIndex = -1;
        const char* leftMarker =
            strstr(bones[sourceBoneIndex].name, kBoneNameNeedleLeft);
        if (leftMarker != nullptr) {
            // Left to right: compare the suffix after the two-byte side marker.
            const char* nameSuffix = leftMarker + 2;
            for (std::int32_t k = 0; k < nBones; ++k) {
                const char* candidateMarker =
                    strstr(bones[k].name, kBoneNameNeedleRight);
                if (candidateMarker != nullptr &&
                    strcmp(candidateMarker + 2, nameSuffix) == 0) {
                    targetBoneIndex = k;
                    break;
                }
            }
        }
        if (targetBoneIndex < 0) {
            // Right to left uses the same exact-name bone (x64 RVA 0x4463C..0x44651).
            const char* nameSuffix = strstr(
                bones[sourceBoneIndex].name, kBoneNameNeedleRight);
            if (nameSuffix != nullptr) {
                nameSuffix += 2;
                for (std::int32_t k = 0; k < nBones; ++k) {
                    const char* candidateMarker =
                        strstr(bones[k].name, kBoneNameNeedleLeft);
                    if (candidateMarker != nullptr &&
                        strcmp(candidateMarker + 2, nameSuffix) == 0) {
                        targetBoneIndex = k;
                        break;
                    }
                }
            }
        }
        if (targetBoneIndex < 0) {
            targetBoneIndex = sourceBoneIndex;  // fallback to the exact-name match
        }
        undoPoseBytes = reinterpret_cast<unsigned char*>(undo.bonePose);
        auto& rec = reinterpret_cast<mikudancestudio::mdl::BonePoseSnapshot*>(
            undoPoseBytes)[copiedPoseIndex];
        mikudancestudio::mdl::BoneRecord* bone = &bones[targetBoneIndex];
        rec.boneIndex = targetBoneIndex;
        selected[targetBoneIndex] = 1;
        // old pos into the undo record
        memcpy(rec.position, bone->trans, sizeof rec.position);
        // new pos from the copy record - X negated (fchs)
        bone->trans[0] = -src.position[0];
        bone->trans[1] = src.position[1];
        bone->trans[2] = src.position[2];
        // old quat into the undo record
        memcpy(rec.rotation, bone->rotQuat, sizeof rec.rotation);
        // new quat from the copy record - Y and Z negated (fchs)
        bone->rotQuat[0] = src.rotation[0];
        bone->rotQuat[1] = -src.rotation[1];
        bone->rotQuat[2] = -src.rotation[2];
        bone->rotQuat[3] = src.rotation[3];
        rec.physicsDisabled = physicsState[targetBoneIndex];
        physicsState[targetBoneIndex] = 1;
        modelRecord->selectedBone = targetBoneIndex;
        RebuildTimelineTrackPanel(app);
        InvalidateSelectionReadouts(app);
    }
    SetFocus(hwnd);
    app->PhysicsResetPending() = 1;
}

}  // namespace mikudancestudio
