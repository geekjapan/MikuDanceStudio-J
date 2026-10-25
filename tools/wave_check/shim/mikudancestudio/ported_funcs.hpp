#pragma once
// The cross-module declarations wave_audio.cpp uses; the harness defines them.
#include <Windows.h>
#include <cstdio>

namespace mikudancestudio {
struct PathResolutionWorkspace;
class MMDApp;
class PhysicsScene;
void CloseDataFile(void* file);
const wchar_t* ResolveUserFilePath(PathResolutionWorkspace& paths, const wchar_t* path);
void TimelineDrawTicks(int frameOffset, int width);
void SetFrameNormalized(int v);
void PanelPaint(MMDApp* app);
void LoadWaveFile(MMDApp* app);
bool WaveStartPlayback(void* obj);
bool WaveStreamFeed(void* obj, void* buf, int bytes, void* buf2, int bytes2);
void CloseDataFile(void* file);
void WaveSeekAndFeed(void* obj, double seconds);
}
