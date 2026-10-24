#pragma once
#include <cstddef>
#include <cstdint>
#include <string>

namespace mikudancestudio::tools {
// Command line of the trace mode:
//   MikuDanceStudio.exe --mds-trace <pmm> <out> <frames>
// The flag must be the first argument and the line must have exactly these
// four arguments. <pmm> must end in ".pmm" (any case). <frames> is a decimal
// number in 1..kMaxTraceFrames.
struct TraceRequest {
    std::wstring pmm;
    std::wstring out;
    std::uint32_t frames = 0;
};

enum class TraceArgs { NotRequested, Ready, Malformed };

constexpr std::uint32_t kMaxTraceFrames = 100000;

inline bool EndsWithPmm(const std::wstring& path) {
    if (path.size() < 4) return false;
    const wchar_t* tail = path.c_str() + path.size() - 4;
    static const wchar_t kLower[] = L".pmm";
    for (int i = 0; i < 4; ++i) {
        wchar_t c = tail[i];
        if (c >= L'A' && c <= L'Z') c = static_cast<wchar_t>(c - L'A' + L'a');
        if (c != kLower[i]) return false;
    }
    return true;
}

// argv is the usual argv (argv[0] = program). Without the flag the result is
// NotRequested and *request is untouched, so the normal startup is unchanged.
inline TraceArgs ParseTraceArgs(int argc, const wchar_t* const* argv, TraceRequest* request) {
    if (argv == nullptr || argc < 2 || argv[1] == nullptr || std::wstring(argv[1]) != L"--mds-trace")
        return TraceArgs::NotRequested;
    if (argc != 5) return TraceArgs::Malformed;
    const std::wstring frames = argv[4];
    if (frames.empty() || frames.size() > 6) return TraceArgs::Malformed;
    std::uint32_t count = 0;
    for (const wchar_t c : frames) {
        if (c < L'0' || c > L'9') return TraceArgs::Malformed;
        count = count * 10 + static_cast<std::uint32_t>(c - L'0');
    }
    if (count < 1 || count > kMaxTraceFrames) return TraceArgs::Malformed;
    TraceRequest parsed;
    parsed.pmm = argv[2];
    parsed.out = argv[3];
    parsed.frames = count;
    if (!EndsWithPmm(parsed.pmm) || parsed.out.empty()) return TraceArgs::Malformed;
    *request = parsed;
    return TraceArgs::Ready;
}
}  // namespace mikudancestudio::tools
