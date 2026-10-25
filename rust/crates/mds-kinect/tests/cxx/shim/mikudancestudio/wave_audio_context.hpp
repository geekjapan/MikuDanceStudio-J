// The five fields of WaveAudioContext that audio_pose_helpers.cpp touches.
#pragma once
#include <Windows.h>
#include <cstdint>
namespace mikudancestudio {
struct WaveAudioContext {
    unsigned char* waveformMax;
    unsigned char* waveformMin;
    wchar_t path[256];
    std::uint8_t englishUI;
    LONG volume;
};
} // namespace mikudancestudio
