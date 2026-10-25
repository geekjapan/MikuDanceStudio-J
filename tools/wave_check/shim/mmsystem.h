#pragma once
#include <Windows.h>
#define WAVE_FORMAT_PCM 1
typedef std::uint16_t WORD;
#pragma pack(push, 1)
struct WAVEFORMATEX {
    WORD wFormatTag;
    WORD nChannels;
    DWORD nSamplesPerSec;
    DWORD nAvgBytesPerSec;
    WORD nBlockAlign;
    WORD wBitsPerSample;
    WORD cbSize;
};
#pragma pack(pop)
