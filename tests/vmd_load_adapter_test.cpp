#define WIN32_LEAN_AND_MEAN
#include <Windows.h>

#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

#include "mikudancestudio/global_key_layout.hpp"
#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/ported_funcs.hpp"
#include "mikudancestudio/vmd_format.hpp"
#include "mikudancestudio/vmd_track_apply.hpp"

int main() {
    using namespace mikudancestudio;
    auto app = std::make_unique<MMDApp>();
    std::memset(&app->state, 0, sizeof app->state);
    app->state.optflag[0] = 1;
    std::vector<mdl::CameraKey> cameras(mdl::kTimelineKeyCapacity);
    std::vector<mdl::LightKey> lights(mdl::kTimelineKeyCapacity);
    std::vector<mdl::SelfShadowKey> shadows(mdl::kTimelineKeyCapacity);
    app->CameraKeys() = cameras.data();
    app->LightKeys() = lights.data();
    app->ShadowKeys() = shadows.data();

    format::VmdDocument motion;
    const char cameraName[] =
        "\x83\x4a\x83\x81\x83\x89\x81\x45\x8f\xc6\x96\xbe";
    std::memcpy(motion.modelName.data(), cameraName, sizeof cameraName);
    format::VmdCameraKey camera;
    camera.frame = 12;
    camera.distance = -35.0f;
    camera.eye[0] = 2.5f;
    camera.fov = 36;
    camera.perspective = 1;
    camera.interpolation[2][1] = 81;
    motion.cameras.push_back(camera);
    format::VmdLightKey light;
    light.frame = 14;
    light.color[0] = 0.75f;
    motion.lights.push_back(light);
    format::VmdShadowKey shadow;
    shadow.frame = 16;
    shadow.mode = 2;
    shadow.distance = 0.5f;
    motion.shadows.push_back(shadow);

    wchar_t directory[MAX_PATH]{};
    wchar_t path[MAX_PATH]{};
    if (!GetTempPathW(MAX_PATH, directory) ||
        !GetTempFileNameW(directory, L"vmd", 0, path)) return 1;
    std::FILE* stream = nullptr;
    if (_wfopen_s(&stream, path, L"wb") != 0 || stream == nullptr) return 1;
    const bool written = format::WriteVmd(stream, motion);
    std::fclose(stream);
    if (!written) return 1;

    format::VmdDocument parsed;
    stream = nullptr;
    const bool opened = _wfopen_s(&stream, path, L"rb") == 0 && stream != nullptr;
    const bool valid = opened && format::ReadVmd(stream, parsed);
    if (stream != nullptr) std::fclose(stream);
    if (!valid) return 1;
    ApplyVmdGlobalTracks(app.get(), parsed);
    DeleteFileW(path);
    const bool ok = cameras[1].frame == 12 &&
                    cameras[1].distance == -35.0f &&
                    cameras[1].eye[0] == 2.5f &&
                    cameras[1].fov == 36 &&
                    cameras[1].perspective == 1 &&
                    cameras[1].interpolation[2][2] == 81 &&
                    lights[1].frame == 14 &&
                    lights[1].color[0] == 0.75f &&
                    shadows[1].frame == 16 &&
                    shadows[1].mode == 2 &&
                    shadows[1].distance == 0.5f;
    app->CameraKeys() = nullptr;
    app->LightKeys() = nullptr;
    app->ShadowKeys() = nullptr;
    if (!ok) {
        std::fprintf(stderr,
            "VMD load values: cam frame=%u distance=%f eye=%f fov=%d view=%u curve=%u; light frame=%u color=%f; shadow frame=%u mode=%u distance=%f\n",
            cameras[1].frame, cameras[1].distance, cameras[1].eye[0],
            cameras[1].fov, cameras[1].perspective,
            cameras[1].interpolation[2][2], lights[1].frame,
            lights[1].color[0], shadows[1].frame, shadows[1].mode,
            shadows[1].distance);
        return 1;
    }
    std::puts("VMD Windows camera load adapter passed");
}
