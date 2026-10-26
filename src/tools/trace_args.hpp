#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace mikudancestudio::tools {
// Command lines of the headless modes. The flag must be the first
// argument, and <pmm> must end in ".pmm" (any case).
//   MikuDanceStudio.exe --mds-trace <pmm> <out> <frames>
//     Exactly these four arguments. <frames> is a decimal number in
//     1..kMaxTraceFrames.
//   MikuDanceStudio.exe --mds-frame-dump <pmm> <out-dir> <frame>...
//     One or more decimal frame numbers in 0..kMaxTraceFrames-1, strictly
//     ascending.
//   MikuDanceStudio.exe --mds-edge-probe <pmm> <out> <frame>...
//     The frames as for --mds-frame-dump; <out> is the probe text file.
//   MikuDanceStudio.exe --mds-frame-dump-4096 <pmm> <out-dir> <frame>...
//     --mds-frame-dump with a 4096x4096 self-shadow map, as the shadow
//     panel's checkbox selects it.
//   MikuDanceStudio.exe --mds-ground-probe <pmm> <out> <frame>...
//     The frames as for --mds-frame-dump; <out> lists the model draws of each
//     requested frame and those under the ground shadow matrix.
//   MikuDanceStudio.exe --mds-msaa-probe <pmm> <out>
//     Exactly these four arguments. Writes the multisample coverage of quads
//     at sub-pixel offsets; the PMM only hosts the device.
//   MikuDanceStudio.exe --mds-mme-dump <pmm> <out-dir> <frame>...
//     The frames as for --mds-frame-dump; writes an image and an MME probe
//     per frame.
//   MikuDanceStudio.exe --mds-mesh-dump <pmm> <out-dir> <x-file>...
//     One or more accessory files (.x or .vac). The PMM only hosts the device.
struct TraceRequest {
    enum class Mode {
        Trace,
        FrameDump,
        EdgeProbe,
        MeshDump,
        MmeDump,
        GroundProbe,
        MsaaProbe
    };
    Mode mode = Mode::Trace;
    std::wstring pmm;
    std::wstring out;                      // the trace or probe file, or the frame dump directory
    std::uint32_t frames = 0;              // passes: the trace length, or the last dump frame + 1
    std::vector<std::uint32_t> dumpFrames; // FrameDump, EdgeProbe, and MmeDump
    std::vector<std::wstring> meshFiles;   // MeshDump
    std::int32_t shadowMapSize = 0;        // FrameDump: 0 keeps the app's 2048
};

enum class TraceArgs {
    NotRequested,
    Ready,
    Malformed
};

constexpr std::uint32_t kMaxTraceFrames = 100000;

inline bool EndsWithPmm(const std::wstring& path) {
    if (path.size() < 4)
        return false;
    const wchar_t* tail = path.c_str() + path.size() - 4;
    static const wchar_t kLower[] = L".pmm";
    for (int i = 0; i < 4; ++i) {
        wchar_t c = tail[i];
        if (c >= L'A' && c <= L'Z')
            c = static_cast<wchar_t>(c - L'A' + L'a');
        if (c != kLower[i])
            return false;
    }
    return true;
}

// Up to six decimal digits.
inline bool ParseDecimal(const std::wstring& text, std::uint32_t* value) {
    if (text.empty() || text.size() > 6)
        return false;
    std::uint32_t number = 0;
    for (const wchar_t c : text) {
        if (c < L'0' || c > L'9')
            return false;
        number = number * 10 + static_cast<std::uint32_t>(c - L'0');
    }
    *value = number;
    return true;
}

// argv is the usual argv (argv[0] = program). Without either flag the result
// is NotRequested and *request is untouched, so the normal startup is
// unchanged.
inline TraceArgs ParseTraceArgs(int argc, const wchar_t* const* argv, TraceRequest* request) {
    if (argv == nullptr || argc < 2 || argv[1] == nullptr)
        return TraceArgs::NotRequested;
    const std::wstring flag = argv[1];
    TraceRequest parsed;
    if (flag == L"--mds-trace") {
        if (argc != 5 || !ParseDecimal(argv[4], &parsed.frames) || parsed.frames < 1 ||
            parsed.frames > kMaxTraceFrames)
            return TraceArgs::Malformed;
    } else if (flag == L"--mds-msaa-probe") {
        if (argc != 4)
            return TraceArgs::Malformed;
        parsed.mode = TraceRequest::Mode::MsaaProbe;
    } else if (flag == L"--mds-frame-dump" || flag == L"--mds-frame-dump-4096" ||
               flag == L"--mds-edge-probe" || flag == L"--mds-ground-probe" ||
               flag == L"--mds-mme-dump") {
        if (argc < 5)
            return TraceArgs::Malformed;
        for (int i = 4; i < argc; ++i) {
            std::uint32_t frame = 0;
            if (!ParseDecimal(argv[i], &frame) || frame >= kMaxTraceFrames ||
                (!parsed.dumpFrames.empty() && frame <= parsed.dumpFrames.back()))
                return TraceArgs::Malformed;
            parsed.dumpFrames.push_back(frame);
        }
        parsed.mode = flag == L"--mds-edge-probe"     ? TraceRequest::Mode::EdgeProbe
                      : flag == L"--mds-ground-probe" ? TraceRequest::Mode::GroundProbe
                      : flag == L"--mds-mme-dump"     ? TraceRequest::Mode::MmeDump
                                                      : TraceRequest::Mode::FrameDump;
        if (flag == L"--mds-frame-dump-4096")
            parsed.shadowMapSize = 4096;
        parsed.frames = parsed.dumpFrames.back() + 1;
    } else if (flag == L"--mds-mesh-dump") {
        if (argc < 5)
            return TraceArgs::Malformed;
        for (int i = 4; i < argc; ++i) {
            if (argv[i] == nullptr || argv[i][0] == L'\0')
                return TraceArgs::Malformed;
            parsed.meshFiles.push_back(argv[i]);
        }
        parsed.mode = TraceRequest::Mode::MeshDump;
    } else {
        return TraceArgs::NotRequested;
    }
    parsed.pmm = argv[2];
    parsed.out = argv[3];
    if (!EndsWithPmm(parsed.pmm) || parsed.out.empty())
        return TraceArgs::Malformed;
    *request = parsed;
    return TraceArgs::Ready;
}
} // namespace mikudancestudio::tools
