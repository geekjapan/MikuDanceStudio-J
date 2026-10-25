#pragma once
// The slice of MMDApp that LoadWaveFile (src/media/wave_audio.cpp) touches.
#include <cstdint>

#include "mikudancestudio/path_workspace.hpp"
#include "mikudancestudio/wave_audio_context.hpp"

namespace mikudancestudio {
class MMDApp {
public:
    void*& Hwnd() { return hwnd; }
    std::uint8_t& DirectSoundAvailable() { return directSound; }
    std::uint8_t& EnglishUI() { return english; }
    WaveAudioContext*& Audio() { return audio; }
    wchar_t* WavePath() { return wavePath; }
    std::uint8_t& WaveEnabled() { return waveEnabled; }
    PathResolutionWorkspace& PathWorkspace() { return paths; }
    HDC& TimelineDC() { return dc; }
    std::int32_t& TimelineStartFrame() { return startFrame; }
    std::int32_t& SidebarWidth() { return sidebar; }
    std::int32_t& FrameNormalization() { return normalization; }

    void* hwnd = nullptr;
    std::uint8_t directSound = 1, english = 1, waveEnabled = 0;
    WaveAudioContext* audio = nullptr;
    wchar_t wavePath[256] = {};
    PathResolutionWorkspace paths = {};
    HDC dc = nullptr;
    std::int32_t startFrame = 0, sidebar = 0, normalization = 0;
};
}
