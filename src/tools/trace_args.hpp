#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace mikudancestudio::tools {
// Command lines of the two headless modes. The flag must be the first
// argument, and <pmm> must end in ".pmm" (any case).
//   MikuDanceStudio.exe --mds-trace <pmm> <out> <frames>
//     Exactly these four arguments. <frames> is a decimal number in
//     1..kMaxTraceFrames.
//   MikuDanceStudio.exe --mds-frame-dump <pmm> <out-dir> <frame>...
//     One or more decimal frame numbers in 0..kMaxTraceFrames-1, strictly
//     ascending.
struct TraceRequest {
    enum class Mode {
        Trace,
        FrameDump
    };
    Mode mode = Mode::Trace;
    std::wstring pmm;
    std::wstring out;                      // the trace file, or the frame dump directory
    std::uint32_t frames = 0;              // passes: the trace length, or the last dump frame + 1
    std::vector<std::uint32_t> dumpFrames; // FrameDump only
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
    } else if (flag == L"--mds-frame-dump") {
        if (argc < 5)
            return TraceArgs::Malformed;
        for (int i = 4; i < argc; ++i) {
            std::uint32_t frame = 0;
            if (!ParseDecimal(argv[i], &frame) || frame >= kMaxTraceFrames ||
                (!parsed.dumpFrames.empty() && frame <= parsed.dumpFrames.back()))
                return TraceArgs::Malformed;
            parsed.dumpFrames.push_back(frame);
        }
        parsed.mode = TraceRequest::Mode::FrameDump;
        parsed.frames = parsed.dumpFrames.back() + 1;
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
