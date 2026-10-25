// The members of MMDApp that src/io/vsq_load.cpp touches. The real class
// pulls in Direct3D, DirectSound and the 0xA55E0-byte state layout, none of
// which the file's behavior depends on. A member renamed or retyped in the
// real class shows up as a link or compile error in the file under test, not
// here, because the file calls only these.
#pragma once
#include <cstdint>

namespace mikudancestudio {
struct MMDAppState {
    std::int32_t currentFrame;
    std::int32_t timelineStartFrame;
    std::uint8_t waveEnabled;
    std::int32_t sidebarWidth;
    std::uint32_t aviBackgroundEnabled;
};
class MMDApp {
public:
    MMDAppState state;
    void* hwnd;
    unsigned char englishUI;
    unsigned char* model;
    std::uint32_t lastRegisteredFrame;
    std::int32_t playbackPhysicsMode;

    void*& Hwnd() { return hwnd; }
    unsigned char& EnglishUI() { return englishUI; }
    unsigned char*& SelectedModel() { return model; }
    std::uint32_t& LastRegisteredFrame() { return lastRegisteredFrame; }
    std::int32_t& PlaybackPhysicsMode() { return playbackPhysicsMode; }
};
}  // namespace mikudancestudio
