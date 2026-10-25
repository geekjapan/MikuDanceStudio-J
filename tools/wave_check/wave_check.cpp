// Runs the real WAV loading code (src/media/wave_audio.cpp, wave_data_chunk.cpp)
// on every *.wav in a directory and prints one text block per file.
// tests/fixtures/rust/media/README.md says how the dump is used.
#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/ported_funcs.hpp"
#include "mikudancestudio/wave_data_chunk.hpp"

const char* g_lastMessage = nullptr;
LONG g_lastSeek = 0;
int g_threadsStarted = 0;

namespace mikudancestudio {

void WaveCtxReset(void* obj);

void CloseDataFile(void* obj) {
    auto* audio = static_cast<WaveAudioContext*>(obj);
    if (audio->parseStream)
        std::fclose(audio->parseStream);
    WaveCtxReset(obj);
}
const wchar_t* ResolveUserFilePath(PathResolutionWorkspace& paths, const wchar_t* path) {
    size_t i = 0;
    for (; path[i]; ++i)
        paths.resolvedPath[i] = path[i];
    paths.resolvedPath[i] = 0;
    return paths.resolvedPath;
}
void TimelineDrawTicks(int, int) {}
void SetFrameNormalized(int) {}
void PanelPaint(MMDApp*) {}

}

using namespace mikudancestudio;

namespace {

struct FakeDirectSound : IDirectSound {
    DWORD bufferBytes = 0;
    HRESULT CreateSoundBuffer(const DSBUFFERDESC* desc, IDirectSoundBuffer** out, void*) override {
        bufferBytes = desc->dwBufferBytes;
        *out = new IDirectSoundBuffer;
        return 0;
    }
};

void Scan(const std::string& path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    std::int32_t size = -1, offset = -1;
    // The header reads leave the stream at byte 36 when WaveLoadFile scans.
    std::fseek(f, 36, SEEK_SET);
    if (ScanWaveDataChunk(f, size, offset))
        std::printf("scan ok %d %d\n", size, offset);
    else
        std::printf("scan fail\n");
    std::fclose(f);
}

void Dump(const std::string& path, const std::string& name) {
    std::printf("file %s\n", name.c_str());
    Scan(path);

    FakeDirectSound ds;
    WaveAudioContext ctx = {};
    ctx.englishUI = 1;
    ctx.directSound = &ds;
    MMDApp app;
    app.audio = &ctx;
    for (size_t i = 0; i <= path.size(); ++i)
        app.wavePath[i] = static_cast<unsigned char>(path[i]);
    g_lastMessage = nullptr;
    LoadWaveFile(&app);

    std::printf("loaded %d\n", app.waveEnabled);
    std::printf("message %s\n", g_lastMessage ? g_lastMessage : "none");
    if (!app.waveEnabled)
        return;
    const WAVEFORMATEX& f = ctx.format;
    std::printf("format %u %u %u %u %u %u %u\n", f.wFormatTag, f.nChannels, f.nSamplesPerSec,
                f.nAvgBytesPerSec, f.nBlockAlign, f.wBitsPerSample, f.cbSize);
    std::printf("data %d %d\n", ctx.dataSize, ctx.dataOffset);
    std::printf("buffer_bytes %d %u\n", ctx.bufferBytes, ds.bufferBytes);
    std::printf("failures %d\n", ctx.failureCount);
    std::printf("columns %d\n", ctx.waveformColumns);
    for (int pass = 0; pass < 2; ++pass) {
        std::printf(pass ? "min" : "max");
        const unsigned char* a = pass ? ctx.waveformMin : ctx.waveformMax;
        for (int i = 0; i < ctx.waveformColumns; ++i)
            std::printf(" %u", a[i]);
        std::printf("\n");
    }
    // WaveSeekAndFeed seeks the data file and starts the (here inert) feed thread.
    for (int frame : {0, 1, 2, 7, 15, 29, 30, 101}) {
        WaveSeekAndFeed(&ctx, frame / 30.0);
        std::printf("seek %d %d\n", frame, g_lastSeek);
    }
}

}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: wave_check <dir-with-wav-files>\n");
        return 2;
    }
    std::vector<std::string> names;
    for (const auto& e : std::filesystem::directory_iterator(argv[1]))
        if (e.path().extension() == ".wav")
            names.push_back(e.path().filename().string());
    std::sort(names.begin(), names.end());
    for (const auto& n : names)
        Dump((std::filesystem::path(argv[1]) / n).string(), n);
    return 0;
}
