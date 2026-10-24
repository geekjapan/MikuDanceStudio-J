// ===========================================================================
// --mds-trace <pmm> <out> <frames>  (RM-3, Windows x64 only)
// ===========================================================================
// Records the L2 trace (format: trace_l2.hpp) of a PMM through the app's own
// per-frame model and physics code, without rendering or presenting.
//
// FrameDriver (src/app/frame_driver.cpp) cannot be called as is: it renders,
// presents, and reads input. The model and physics update inside it is the
// pair PlaybackCatchup + PhysicsFrame, so this file calls those two per pass
// and arms the same state the AVI-record start of FrameDriver section 10
// arms. That mode (frame-step playback) advances N / AviRecordFps seconds
// per pass from a counter, not from the wall clock, so the trace is
// repeatable: at 30 fps one pass is one timeline frame and two 1/60 s ticks
// of the Bullet world.
//
// Deviation from section 10: ArmFrameStep also seeks every model to frame 0
// (SeekModelFrame, as the timeline does) because in the GUI the user has
// already sought to the start frame before recording; here nobody did.
//
// Not run per pass, compared with FrameDriver: RenderFrameScene, Present,
// mouse and keyboard input, the Kinect pump, the text and line overlays, the
// timeline flag handoff (section 7), and the model reload path (section 8).
// The PhysicsFrame settle request (selActive) is fixed at 0, as with no model
// selected. PlaybackPhysicsMode comes from the loaded project and is not
// overridden: with mode 0 the world does not step.
// =========================================================================//
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>

#include "btBulletDynamicsCommon.h"

#include "mikudancestudio/globals.hpp"
#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"
#include "mikudancestudio/ported_funcs.hpp"

#include "trace_l2.hpp"
#include "trace_mode.hpp"

namespace mikudancestudio::tools {
namespace {

constexpr std::size_t kEnvFileNameLength = 0x100;  // MMDApp::EnvFileName() capacity

std::wstring FullPath(const std::wstring& path) {
    wchar_t buffer[MAX_PATH * 4];
    const DWORD length = GetFullPathNameW(path.c_str(), MAX_PATH * 4, buffer, nullptr);
    if (length == 0 || length >= MAX_PATH * 4) return std::wstring();
    return std::wstring(buffer, length);
}

// One pass of the bone and morph update that FrameDriver runs per model
// (OrderedMorphPhysicsPass in playback_catchup.cpp): morph application, then
// SetPhysicsMode, which runs the bone transform, IK, and world pass.
void PoseAllModels(MMDApp* app) {
    unsigned char** models = app->ModelSlots();
    const int mode = app->PlaybackPhysicsMode();
    for (int order = 0; order < kModelSlotCount; ++order) {
        for (int slot = 0; slot < kModelSlotCount; ++slot) {
            unsigned char* model = models[slot];
            if (model == nullptr || mdl::Mdl(model)->comboSelIndex2 != order) continue;
            ModelApplyMorphs(model);
            SetPhysicsMode(model, 0, models, mode);
        }
    }
}

// Appends the lines of one frame. False if a value is not finite or a rigid
// body is missing.
bool WriteFrame(std::ostream& out, MMDApp* app, std::uint32_t frame) {
    for (int slot = 0; slot < kModelSlotCount; ++slot) {
        unsigned char* model = app->ModelSlot(slot);
        if (model == nullptr) continue;
        const auto* record = mdl::Mdl(model);
        const mdl::BoneRecord* bones = mdl::Bones(model);
        const mdl::MorphRecord* morphs = mdl::Morphs(model);
        const mdl::RigidRecord* rigids = mdl::Rigids(model);
        const unsigned id = static_cast<unsigned>(slot);
        for (std::uint32_t i = 0; i < record->boneCount; ++i)
            if (!l2::WriteBoneLine(out, frame, id, i, bones[i].trans, bones[i].rotQuat))
                return false;
        for (std::uint32_t i = 0; i < record->boneCount; ++i)
            if (!l2::WriteBoneWorldLine(out, frame, id, i, bones[i].matInit)) return false;
        for (std::uint32_t i = 0; i < record->morphCount; ++i)
            if (!l2::WriteMorphLine(out, frame, id, i, morphs[i].value)) return false;
        for (std::uint32_t i = 0; i < record->rigidCount; ++i) {
            const auto* body = static_cast<const btRigidBody*>(rigids[i].body);
            if (body == nullptr) return false;
            const btTransform& transform = body->getWorldTransform();
            const btVector3& origin = transform.getOrigin();
            const btQuaternion rotation = transform.getRotation();
            const float position[3] = {origin.x(), origin.y(), origin.z()};
            const float quaternion[4] = {rotation.x(), rotation.y(), rotation.z(), rotation.w()};
            if (!l2::WriteRigidLine(out, frame, id, i, position, quaternion)) return false;
        }
    }
    return out.good();
}

// FrameDriver section 10 (0x479CC6) for frames [0, frames], then the frame-0
// pose. Frame-step playback with AviRecordFps = 30.
void ArmFrameStep(MMDApp* app, std::uint32_t frames) {
    auto& s = *app;
    s.CurrentFrame() = 0;
    s.AviRecordStartFrame() = 0;
    s.AviRecordEndFrame() = static_cast<std::int32_t>(frames);
    s.AviRecordFps() = 30.0f;
    s.state.frameStepPlayback = 1;
    s.state.playbackStartSeconds = 0.0f;
    s.state.playbackEndSeconds = static_cast<float>(frames) / g_FrameScale;
    s.PlaybackCursorSeconds() = 0.0f;
    s.state.playbackFrameChanged = 1;
    s.state.playbackActive = 1;
    s.DeltaTime() = 1.0f / 30.0f;
    // Snap every model to timeline frame 0 like the timeline does, then
    // rebuild the track cursors and compute the frame-0 bone matrices.
    for (int slot = 0; slot < kModelSlotCount; ++slot)
        if (unsigned char* model = s.ModelSlot(slot))
            SeekModelFrame(model, 0, s.PlaybackPhysicsMode());
    UpdateBoneFrames(app);
    s.state.recordedFrameCount = 0;
    PoseAllModels(app);
}

void DeleteTemp(const std::wstring& temp) { DeleteFileW(temp.c_str()); }
}  // namespace

bool PrepareTraceRequest(TraceRequest* request) {
    const std::wstring pmm = FullPath(request->pmm);
    const std::wstring out = FullPath(request->out);
    if (pmm.empty() || out.empty() || pmm.size() >= kEnvFileNameLength) return false;
    if (out.size() + 4 >= MAX_PATH * 4) return false;
    if (_wcsicmp(pmm.c_str(), out.c_str()) == 0) return false;
    const DWORD attributes = GetFileAttributesW(pmm.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
        return false;
    request->pmm = pmm;
    request->out = out;
    return true;
}

int RunTraceMode(MMDApp* app, const TraceRequest& request) {
    ShowWindow(static_cast<HWND>(app->Hwnd()), SW_HIDE);
    bool anyModel = false;
    for (int slot = 0; slot < kModelSlotCount; ++slot)
        anyModel = anyModel || app->ModelSlot(slot) != nullptr;
    if (!anyModel || app->Physics() == nullptr || app->Physics()->world == nullptr) {
        OutputDebugStringA("mds-trace: the PMM loaded no model\n");
        return 1;
    }

    const std::wstring temp = request.out + L".tmp";
    std::ofstream file(std::filesystem::path(temp), std::ios::binary | std::ios::trunc);  // LF stays LF
    if (!file) return 1;

    ArmFrameStep(app, request.frames);
    l2::WriteHeader(file);
    bool ok = WriteFrame(file, app, 0);
    for (std::uint32_t frame = 1; ok && frame < request.frames; ++frame) {
        app->state.messageSeen = 2;  // the render gate of AdvanceFrameRenderGate, playing
        PlaybackCatchup(app, 0);
        PhysicsFrame(app, 0);
        ok = WriteFrame(file, app, frame);
    }
    file.flush();
    ok = ok && file.good();
    file.close();
    if (!ok) {
        DeleteTemp(temp);
        return 1;
    }
    if (!MoveFileExW(temp.c_str(), request.out.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteTemp(temp);
        return 1;
    }
    return 0;
}
}  // namespace mikudancestudio::tools
