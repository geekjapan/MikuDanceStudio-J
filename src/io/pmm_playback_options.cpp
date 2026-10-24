#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "pmm_playback_options.hpp"

#include <cstdio>

#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/panel_controls.hpp"
#include "pmm_io_common.hpp"

namespace mikudancestudio {

void RestorePmmPlaybackOptions(MMDApp* app, HWND main, int fd, char* text,
                               unsigned char& playbackByte) {
    // x64 RVA 0x7FFA8 reads directly into app+0x378, before updating the UI.
    // Reading into the member also preserves its value if the file ends here.
    pmm_io::Rd(fd, &app->state.cameraReferenceMode, 1);
    const auto reference = app->CameraReferenceMode();
    SendMessageA(GetDlgItem(main, panel::kCameraRefModelCheckbox), BM_SETCHECK,
                 reference == CameraAttachmentReference::ModelRoot, 0);
    SendMessageA(GetDlgItem(main, panel::kCameraRefBoneCheckbox), BM_SETCHECK,
                 reference == CameraAttachmentReference::SelectedBone, 0);

    pmm_io::Rd(fd, &playbackByte, 1);
    app->state.playbackLoopEnabled = playbackByte ? 1 : 0;
    SendMessageA(GetDlgItem(main, panel::kPlaybackLoopCheckbox), BM_SETCHECK, playbackByte ? 1 : 0,
                 0);
    pmm_io::Rd(fd, &playbackByte, 1);
    app->state.playbackReturnsToStartFrame = playbackByte ? 1 : 0;
    SendMessageA(GetDlgItem(main, panel::kPlaybackReturnCheckbox), BM_SETCHECK,
                 playbackByte ? 1 : 0, 0);
    pmm_io::Rd(fd, &playbackByte, 1);
    app->state.playbackStartsAtCurrentFrame = playbackByte ? 1 : 0;
    SendMessageA(GetDlgItem(main, panel::kPlaybackFromCurrentCheckbox), BM_SETCHECK,
                 playbackByte ? 1 : 0, 0);
    std::int32_t playStartFrame = 0, playStopFrame = 0;
    pmm_io::Rd(fd, &playStartFrame, 4);
    {
        HWND item = GetDlgItem(main, panel::kPlayStartFrameEdit);
        SendMessageA(item, EM_SETSEL, 0, GetWindowTextLengthA(item));
        sprintf_s(text, 0x100, "%d", playStartFrame);
        SendMessageA(item, EM_REPLACESEL, 0, reinterpret_cast<LPARAM>(text));
    }
    pmm_io::Rd(fd, &playStopFrame, 4);
    {
        HWND item = GetDlgItem(main, panel::kPlayStopFrameEdit);
        SendMessageA(item, EM_SETSEL, 0, GetWindowTextLengthA(item));
        sprintf_s(text, 0x100, "%d", playStopFrame);
        SendMessageA(item, EM_REPLACESEL, 0, reinterpret_cast<LPARAM>(text));
    }
}

} // namespace mikudancestudio
