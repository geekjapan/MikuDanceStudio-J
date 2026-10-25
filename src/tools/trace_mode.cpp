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
// Message boxes: the MMD-port loaders call MessageBoxA on bad input, and a
// modal box would block this headless run forever. ArmTraceDialogGuard
// installs a WH_CBT hook on the WinMain thread (the loaders, the PMM load in
// InitMainWindowAndD3D, and the frame loop all run on it; the audio feed
// thread and the DirectShow threads never show a box) that turns the first
// dialog (class #32770) into exit 1 with the box text on stderr.
//
// Not run per pass, compared with FrameDriver: RenderFrameScene, Present,
// mouse and keyboard input, the Kinect pump, the text and line overlays, the
// timeline flag handoff (section 7), and the model reload path (section 8).
// The PhysicsFrame settle request (selActive) is fixed at 0, as with no model
// selected. PlaybackPhysicsMode comes from the loaded project and is not
// overridden: with mode 0 the world does not step.
//
// --mds-frame-dump <pmm> <out-dir> <frame>...  (golden images, wave 2)
// Steps the same passes as --mds-trace, so frame f shows the pose of the
// trace's frame-f lines, and after the pass of each requested frame renders
// it and writes "<out-dir>\<pmm stem>-<frame>.png". The render is the
// picture-file output of the View menu ("render to picture file",
// command_view_menu.cpp, saved by TimelineAdvance in frame_driver.cpp): a
// RecWindow is the recording window, so RenderFrameScene draws the scene at
// the output size from the back buffer origin and skips the text, line,
// sprite, and debug overlays. The output size is fixed at 640x360 (the app's
// default) whatever the PMM says. The save copies TimelineAdvance's
// StretchRect and D3DXSaveSurfaceToFileW, but not its tail, which destroys
// the window and resizes the device after every picture. Only the
// multisampled back buffer path is supported; without multisampling the
// recording path renders into a capture surface that the picture command
// never creates, so the run fails instead.
//
// --mds-edge-probe <pmm> <out> <frame>...  (golden2, wave 3)
// Runs the setup and the passes of --mds-frame-dump, and at each requested
// frame writes, instead of the image, the inputs and the result of the edge
// thickness that UpdateModelVertexBuffers computes for that frame's render
// (PmdEdgeDistance in src/model/model_skinning.cpp). RenderFrameScene reads
// the frame world matrix right after SetupFrameWorldTransform, so the probe
// calls that and reads the same matrix; it draws nothing. Format:
//   "mds-edge-probe 1" LF, then per requested frame:
//   frame "camera" perspective fov target.xyz distance pitch yaw roll
//         selfShadowEnabled selfShadowMode selfShadowDistance LF
//   frame "world" m00 m01 .. m33 LF       (the frame world matrix, row by row)
//   frame "picture" offX offY scale width height viewScale viewport.ltrb
//         renderWidth renderHeight quad.ltrb rhw0..rhw5 LF   (only with a
//         background picture shown: its placement inputs, the overlay quad
//         drawn, and the rhw of its six vertices)
//   frame "edge" slot bone point.xyz world.xyz target_distance edgeScale edge LF
//         (per loaded model in slot order: the bone PmdEdgeDistance uses, its
//         bind position moved by matInit, that point moved by the world
//         matrix, its distance to CameraPosition, and the result)
// Floats are printf "%.9g", which reads back to the same float.
//
// --mds-mesh-dump <pmm> <out-dir> <x-file>...  (accgold, wave 3): mesh_dump.cpp.
//
// --mds-mme-dump <pmm> <out-dir> <frame>...  (mmegold, wave 3)
// --mds-frame-dump through the app's MME path: the PMM load notifies the
// embedded MMEffect (mme::NotifyPmmLoaded), whose first frame autoloads
// "<pmm dir>\<pmm stem>.emm" and assigns the effects as the MME dialog's EMM
// load does; models also get a same-name .fx beside them. Unlike
// --mds-frame-dump every pass is rendered, as AVI recording renders every
// frame, so ELAPSEDTIME, animated textures, and render targets that carry over
// see the frames the app would. UpdateBoneFrames (ArmFrameStep) disables the
// current-frame edit as playback does, so MME runs in its non-edit mode from
// the first frame and TIME is the timeline time, not the wall clock. Frame 0
// is rendered once more before the passes so that its ELAPSEDTIME does not
// come from the wall clock either (RunFrameDump). Each
// requested frame writes "<out-dir>\<pmm stem>-<frame>.png" and the probe
// "<out-dir>\<pmm stem>-<frame>.mme.txt" (mme_probe.cpp):
//   "mds-mme-probe 1" LF, "frame" frame seconds LF, then per object MME
//   registered (registration order):
//   "object" file "effect" path|- "class" scriptClass "render" renderClass
//         "shown" 0|1 LF
//   then per loaded effect (sorted by path; a source effect and each assigned
//   instance of it), its parameters following:
//   "effect" path "class" scriptClass "order" scriptOrder "errors" 0|1 LF
//         (paths relative to the PMM directory, '/' separators)
//   "param" name semantic|- class type RxCxElements values... LF
//         (every top-level bool, int, and float parameter in declaration
//         order; matrices row by row, ints and bools as integers)
// The values are what the effect holds after the frame, which for a
// per-object parameter is the last draw's. The run fails when a requested
// frame loaded no effect.
// =========================================================================//
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cwchar>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>

#include "btBulletDynamicsCommon.h"

#include "mikudancestudio/d3dx_dyn.hpp"
#include "mikudancestudio/globals.hpp"
#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"
#include "mikudancestudio/ported_funcs.hpp"

#include "trace_l2.hpp"
#include "trace_mode.hpp"

namespace mikudancestudio::tools {
namespace {

constexpr std::size_t kEnvFileNameLength = 0x100; // MMDApp::EnvFileName() capacity
constexpr std::int32_t kDumpWidth = 640;          // window_init.cpp output size default
constexpr std::int32_t kDumpHeight = 360;
constexpr int kD3dxPng = 3; // D3DXIFF_PNG

std::wstring FullPath(const std::wstring& path) {
    wchar_t buffer[MAX_PATH * 4];
    const DWORD length = GetFullPathNameW(path.c_str(), MAX_PATH * 4, buffer, nullptr);
    if (length == 0 || length >= MAX_PATH * 4)
        return std::wstring();
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
            if (model == nullptr || mdl::Mdl(model)->comboSelIndex2 != order)
                continue;
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
        if (model == nullptr)
            continue;
        const auto* record = mdl::Mdl(model);
        const mdl::BoneRecord* bones = mdl::Bones(model);
        const mdl::MorphRecord* morphs = mdl::Morphs(model);
        const mdl::RigidRecord* rigids = mdl::Rigids(model);
        const unsigned id = static_cast<unsigned>(slot);
        for (std::uint32_t i = 0; i < record->boneCount; ++i)
            if (!l2::WriteBoneLine(out, frame, id, i, bones[i].trans, bones[i].rotQuat))
                return false;
        for (std::uint32_t i = 0; i < record->boneCount; ++i)
            if (!l2::WriteBoneWorldLine(out, frame, id, i, bones[i].matInit))
                return false;
        for (std::uint32_t i = 0; i < record->morphCount; ++i)
            if (!l2::WriteMorphLine(out, frame, id, i, morphs[i].value))
                return false;
        for (std::uint32_t i = 0; i < record->rigidCount; ++i) {
            const auto* body = static_cast<const btRigidBody*>(rigids[i].body);
            if (body == nullptr)
                return false;
            const btTransform& transform = body->getWorldTransform();
            const btVector3& origin = transform.getOrigin();
            const btQuaternion rotation = transform.getRotation();
            const float position[3] = {origin.x(), origin.y(), origin.z()};
            const float quaternion[4] = {rotation.x(), rotation.y(), rotation.z(), rotation.w()};
            if (!l2::WriteRigidLine(out, frame, id, i, position, quaternion))
                return false;
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
            SeekModelFrame(*mdl::Mdl(model), 0, s.PlaybackPhysicsMode());
    UpdateBoneFrames(app);
    s.state.recordedFrameCount = 0;
    PoseAllModels(app);
}

void DeleteTemp(const std::wstring& temp) {
    DeleteFileW(temp.c_str());
}

std::wstring g_guardTemp;
std::ofstream* g_guardFile = nullptr; // the open temp file while RunTraceMode writes it

std::string Utf8(const wchar_t* text) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1)
        return std::string();
    std::string utf8(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text, -1, &utf8[0], size, nullptr, nullptr);
    utf8.pop_back();
    return utf8;
}

// Appends the text of each Static child. MessageBox and the app's own
// dialogs give their message different control IDs, so match by class.
BOOL CALLBACK AppendStaticText(HWND child, LPARAM lParam) {
    wchar_t childClass[8] = L"";
    wchar_t text[1024] = L"";
    if (GetClassNameW(child, childClass, 8) != 0 && _wcsicmp(childClass, L"Static") == 0 &&
        GetWindowTextW(child, text, 1024) > 0) {
        std::string& out = *reinterpret_cast<std::string*>(lParam);
        if (!out.empty())
            out += " | ";
        out += Utf8(text);
    }
    return TRUE;
}

void WriteError(const std::string& line) {
    HANDLE error = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written = 0;
    if (error != nullptr && error != INVALID_HANDLE_VALUE)
        WriteFile(error, line.data(), static_cast<DWORD>(line.size()), &written, nullptr);
    OutputDebugStringA(line.c_str());
}

[[noreturn]] void AbortOnDialog(HWND dialog) {
    wchar_t caption[256] = L"";
    GetWindowTextW(dialog, caption, 256);
    std::string text;
    EnumChildWindows(dialog, AppendStaticText, reinterpret_cast<LPARAM>(&text));
    WriteError("mds-trace: dialog: " + Utf8(caption) + ": " + text + "\n");
    if (g_guardFile != nullptr)
        g_guardFile->close(); // DeleteFileW needs it closed
    DeleteTemp(g_guardTemp);
    // Not ExitProcess: this runs inside MessageBox with the app half built,
    // and DLL detach would wait on the audio and DirectShow threads.
    TerminateProcess(GetCurrentProcess(), 1);
    for (;;)
        Sleep(INFINITE);
}

LRESULT CALLBACK DialogGuardProc(int code, WPARAM wParam, LPARAM lParam) {
    if (code == HCBT_ACTIVATE) {
        wchar_t windowClass[8] = L"";
        const HWND window = reinterpret_cast<HWND>(wParam);
        if (GetClassNameW(window, windowClass, 8) != 0 && wcscmp(windowClass, L"#32770") == 0)
            AbortOnDialog(window);
    }
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

// Renders the current pose and writes it to `path` as PNG through "<path>.tmp".
bool DumpFrame(MMDApp* app, const std::wstring& path) {
    D3DRenderer* r = app->Renderer();
    IDirect3DDevice9* device = r->device;
    app->state.messageSeen = 2; // RenderFrameScene draws nothing before the first message
    RenderFrameScene(app);

    IDirect3DSurface9* surface = nullptr;
    if (FAILED(device->CreateRenderTarget(kDumpWidth, kDumpHeight, r->backbufferFormat,
                                          D3DMULTISAMPLE_NONE, 0, FALSE, &surface, nullptr)))
        return false;
    if (r->backbufferSurface == nullptr)
        device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &r->backbufferSurface);
    RECT rect{0, 0, kDumpWidth, kDumpHeight};
    HRESULT hr = device->StretchRect(r->backbufferSurface, &rect, surface, &rect, D3DTEXF_LINEAR);
    if (FAILED(hr))
        hr = device->StretchRect(r->backbufferSurface, &rect, surface, &rect, D3DTEXF_NONE);
    const std::wstring temp = path + L".tmp";
    g_guardTemp = temp;
    if (SUCCEEDED(hr))
        hr = d3dx::Get().saveSurfaceToFileW(temp.c_str(), kD3dxPng, surface, nullptr, &rect);
    surface->Release();
    if (FAILED(hr) || !MoveFileExW(temp.c_str(), path.c_str(),
                                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteTemp(temp);
        return false;
    }
    return true;
}

// PmdEdgeDistance (src/model/model_skinning.cpp) with its inputs; the same
// float operations in the same order.
bool WriteEdgeProbe(std::ostream& out, MMDApp* app, std::uint32_t frame) {
    SetupFrameWorldTransform(app);
    D3DMATRIX world{};
    if (FAILED(app->Renderer()->device->GetTransform(D3DTS_WORLD, &world)))
        return false;
    const float* m = &world.m[0][0];
    const float* target = app->CameraPosition();
    char line[512];
    std::snprintf(line, sizeof line,
                  "%u camera %d %.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g %d %d %.9g\n", frame,
                  static_cast<int>(app->CameraPerspective()), app->CameraFov(), target[0],
                  target[1], target[2], app->CameraDistance(), app->CameraPitch(), app->CameraYaw(),
                  app->CameraRoll(), static_cast<int>(app->state.selfShadowEnabled),
                  static_cast<int>(app->SelfShadowMode()), app->ShadowDistance());
    out << line;
    int at = std::snprintf(line, sizeof line, "%u world", frame);
    for (int i = 0; i < 16; ++i)
        at += std::snprintf(line + at, sizeof line - at, " %.9g", m[i]);
    out << line << '\n';
    if (app->PictureBackgroundEnabled() != 0) {
        // The overlay quad as PicBgOverlayRefresh (src/render/bg_overlay.cpp)
        // wrote it: left, top, right, bottom in render-target pixels.
        float quad[4]{};
        float rhw[6]{};
        void* locked = nullptr;
        IDirect3DVertexBuffer9* vb = app->PictureOverlayVertices();
        if (vb == nullptr || FAILED(vb->Lock(0, 0xA8, &locked, D3DLOCK_READONLY)))
            return false;
        const float* v = static_cast<const float*>(locked);
        quad[0] = v[0x38 / 4];
        quad[1] = v[0x3C / 4];
        quad[2] = v[0x00 / 4];
        quad[3] = v[0x20 / 4];
        for (int i = 0; i < 6; ++i)
            rhw[i] = v[i * 7 + 3]; // 28-byte vertices: x y z rhw color u v
        vb->Unlock();
        const RECT& view = app->ViewportRect();
        std::snprintf(line, sizeof line,
                      "%u picture %d %d %.9g %d %d %.9g %ld %ld %ld %ld %d %d %.9g %.9g %.9g %.9g "
                      "%.9g %.9g %.9g %.9g %.9g %.9g\n",
                      frame, app->PictureOffsetX(), app->PictureOffsetY(), app->PictureScale(),
                      app->PictureWidth(), app->PictureHeight(), app->Renderer()->viewScale,
                      view.left, view.top, view.right, view.bottom, app->RenderWidth(),
                      app->RenderHeight(), quad[0], quad[1], quad[2], quad[3], rhw[0], rhw[1],
                      rhw[2], rhw[3], rhw[4], rhw[5]);
        out << line;
    }
    for (int slot = 0; slot < kModelSlotCount; ++slot) {
        unsigned char* model = app->ModelSlot(slot);
        if (model == nullptr)
            continue;
        const mdl::ModelRecord& record = *mdl::Mdl(model);
        const mdl::BoneRecord* bones = mdl::Bones(model);
        const int boneCount = static_cast<int>(record.boneCount);
        const int bone = boneCount > 1 ? 1 : 0;
        float point[3]{};
        if (bones != nullptr && boneCount > 0) {
            const float* p = bones[bone].position;
            const float* b = bones[bone].matInit;
            point[0] = p[0] * b[0] + p[1] * b[4] + p[2] * b[8] + b[12];
            point[1] = p[0] * b[1] + p[1] * b[5] + p[2] * b[9] + b[13];
            point[2] = p[0] * b[2] + p[1] * b[6] + p[2] * b[10] + b[14];
        }
        float moved[3];
        moved[0] = point[0] * m[0] + point[1] * m[4] + point[2] * m[8] + m[12];
        moved[1] = point[0] * m[1] + point[1] * m[5] + point[2] * m[9] + m[13];
        moved[2] = point[0] * m[2] + point[1] * m[6] + point[2] * m[10] + m[14];
        const float dx = moved[0] - target[0];
        const float dy = moved[1] - target[1];
        const float dz = moved[2] - target[2];
        const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
        const float edge = distance * 0.00004500000068219379f *
                           (app->CameraFov() * 0.6000000238418579f + 1.0f) * record.edgeScale;
        std::snprintf(line, sizeof line,
                      "%u edge %d %d %.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g\n", frame, slot,
                      bone, point[0], point[1], point[2], moved[0], moved[1], moved[2], distance,
                      record.edgeScale, edge);
        out << line;
    }
    return out.good();
}

// With `probe` set (--mds-edge-probe) the requested frames are probed instead
// of rendered, after the same setup. An MME dump renders every pass.
int RunFrameDump(MMDApp* app, const TraceRequest& request, std::ostream* probe) {
    D3DRenderer* r = app->Renderer();
    if (r == nullptr || r->device == nullptr)
        return 1;
    char info[192];
    std::snprintf(info, sizeof info,
                  "mds-frame-dump: %dx%d, back buffer %dx%d format %d multisample %d quality %lu, "
                  "camera perspective %d\n",
                  kDumpWidth, kDumpHeight, r->screenWidth, r->screenHeight,
                  static_cast<int>(r->backbufferFormat),
                  static_cast<int>(r->presentParameters.MultiSampleType),
                  r->presentParameters.MultiSampleQuality,
                  static_cast<int>(app->CameraPerspective()));
    WriteError(info);
    if (r->multisampleAvailable == 0 || r->screenWidth < kDumpWidth ||
        r->screenHeight < kDumpHeight) {
        WriteError("mds-frame-dump: needs a multisampled back buffer of at least 640x360\n");
        return 1;
    }

    app->RenderWidth() = kDumpWidth;
    app->RenderHeight() = kDumpHeight;
    const HWND window = CreateWindowExA(0, "RecWindow", "mds-frame-dump", WS_POPUP | WS_CAPTION, 0,
                                        0, kDumpWidth, kDumpHeight, nullptr, nullptr,
                                        static_cast<HINSTANCE>(app->HInstance()), nullptr);
    if (window == nullptr)
        return 1;
    app->RecordingWindow() = window;
    RefreshMainWindowViewport(app); // viewport (0, 0, 640, 360) and the projection aspect

    const std::wstring prefix =
        request.out + L"\\" + std::filesystem::path(request.pmm).stem().wstring() + L"-";
    const bool mme = request.mode == TraceRequest::Mode::MmeDump;
    ArmFrameStep(app, request.frames);
    if (mme) {
        // MmeUpdateFrameTime takes the first non-edit frame's ELAPSEDTIME from
        // the wall clock when the frame before it was in edit mode (the app
        // drew one while loading). This render takes that frame, so frame 0
        // sees 0 and every later frame 1/30.
        app->state.messageSeen = 2;
        RenderFrameScene(app);
    }
    bool ok = true;
    std::size_t next = 0;
    for (std::uint32_t frame = 0; ok && frame < request.frames; ++frame) {
        if (frame > 0) {
            app->state.messageSeen = 2; // as RunTraceMode
            PlaybackCatchup(app, 0);
            PhysicsFrame(app, 0);
        }
        if (frame != request.dumpFrames[next]) {
            if (mme) {
                app->state.messageSeen = 2;
                RenderFrameScene(app);
            }
            continue;
        }
        ++next;
        if (probe != nullptr) {
            ok = WriteEdgeProbe(*probe, app, frame);
            continue;
        }
        ok = DumpFrame(app, prefix + std::to_wstring(frame) + L".png");
        if (ok && mme) {
            const int effects = WriteMmeProbe(
                prefix + std::to_wstring(frame) + L".mme.txt", frame, app->PlaybackCursorSeconds(),
                std::filesystem::path(request.pmm).parent_path().wstring());
            ok = effects > 0;
            if (effects == 0)
                WriteError("mds-mme-dump: frame " + std::to_string(frame) +
                           ": no MME effect loaded\n");
        }
    }
    if (mme)
        WriteMmeLog();
    // ShutdownCleanup tears down a recording graph when a recording window is set.
    app->RecordingWindow() = nullptr;
    DestroyWindow(window);
    if (!ok)
        WriteError("mds-frame-dump: render or save failed\n");
    return ok ? 0 : 1;
}
} // namespace

bool ArmTraceDialogGuard(const TraceRequest& request) {
    g_guardTemp = request.out + L".tmp";
    return SetWindowsHookExW(WH_CBT, DialogGuardProc, nullptr, GetCurrentThreadId()) != nullptr;
}

bool PrepareTraceRequest(TraceRequest* request) {
    const std::wstring pmm = FullPath(request->pmm);
    const std::wstring out = FullPath(request->out);
    if (pmm.empty() || out.empty() || pmm.size() >= kEnvFileNameLength)
        return false;
    // A dump file name adds "\<stem>-<frame>.png.tmp" (or ".mme.txt.tmp"), at
    // most the PMM name plus 20.
    const bool images = request->mode == TraceRequest::Mode::FrameDump ||
                        request->mode == TraceRequest::Mode::MmeDump;
    if (out.size() + 4 + (images ? pmm.size() + 20 : 0) >= MAX_PATH * 4)
        return false;
    if (_wcsicmp(pmm.c_str(), out.c_str()) == 0)
        return false;
    const DWORD attributes = GetFileAttributesW(pmm.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
        return false;
    const DWORD outAttributes = GetFileAttributesW(out.c_str());
    const bool toDirectory = request->mode == TraceRequest::Mode::FrameDump ||
                             request->mode == TraceRequest::Mode::MeshDump ||
                             request->mode == TraceRequest::Mode::MmeDump;
    if (toDirectory && (outAttributes == INVALID_FILE_ATTRIBUTES ||
                        (outAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0))
        return false;
    // LoadAccessoryObject changes the current directory, and a missing file
    // would raise its "Cannot find xfile" box. Its path buffers hold 256 wchars.
    for (std::wstring& file : request->meshFiles) {
        file = FullPath(file);
        const DWORD fileAttributes = GetFileAttributesW(file.c_str());
        if (file.empty() || file.size() >= kEnvFileNameLength ||
            out.size() + std::filesystem::path(file).filename().wstring().size() + 10 >=
                MAX_PATH * 4 ||
            fileAttributes == INVALID_FILE_ATTRIBUTES ||
            (fileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
            return false;
    }
    request->pmm = pmm;
    request->out = out;
    return true;
}

int RunTraceMode(MMDApp* app, const TraceRequest& request) {
    ShowWindow(static_cast<HWND>(app->Hwnd()), SW_HIDE);
    if (request.mode == TraceRequest::Mode::MeshDump)
        return RunMeshDump(app, request);
    bool anyModel = false;
    for (int slot = 0; slot < kModelSlotCount; ++slot)
        anyModel = anyModel || app->ModelSlot(slot) != nullptr;
    if (!anyModel || app->Physics() == nullptr || app->Physics()->world == nullptr) {
        OutputDebugStringA("mds-trace: the PMM loaded no model\n");
        return 1;
    }
    if (request.mode == TraceRequest::Mode::FrameDump ||
        request.mode == TraceRequest::Mode::MmeDump)
        return RunFrameDump(app, request, nullptr);

    const std::wstring temp = request.out + L".tmp";
    std::ofstream file(std::filesystem::path(temp),
                       std::ios::binary | std::ios::trunc); // LF stays LF
    if (!file)
        return 1;
    g_guardFile = &file;

    bool ok = true;
    if (request.mode == TraceRequest::Mode::EdgeProbe) {
        file << "mds-edge-probe 1\n";
        ok = RunFrameDump(app, request, &file) == 0;
    } else {
        ArmFrameStep(app, request.frames);
        l2::WriteHeader(file);
        ok = WriteFrame(file, app, 0);
        for (std::uint32_t frame = 1; ok && frame < request.frames; ++frame) {
            app->state.messageSeen = 2; // the render gate of AdvanceFrameRenderGate, playing
            PlaybackCatchup(app, 0);
            PhysicsFrame(app, 0);
            ok = WriteFrame(file, app, frame);
        }
    }
    file.flush();
    ok = ok && file.good();
    file.close();
    g_guardFile = nullptr;
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
} // namespace mikudancestudio::tools
