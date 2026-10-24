#pragma once

#include <Windows.h>

namespace mikudancestudio {
class MMDApp;

void RestorePmmPlaybackOptions(MMDApp* app, HWND main, int fd, char* text,
                               unsigned char& playbackByte);
}  // namespace mikudancestudio
