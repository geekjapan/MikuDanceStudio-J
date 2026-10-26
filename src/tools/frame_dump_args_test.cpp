// Checks the --mds-frame-dump command line of trace_args.hpp. Portable:
//   c++ -std=c++17 -I src/tools src/tools/frame_dump_args_test.cpp && ./a.out
#include "trace_args.hpp"

#include <cstdio>
#include <initializer_list>
#include <vector>

using namespace mikudancestudio::tools;

namespace {
int g_failures = 0;

#define CHECK(condition)                                                                           \
    do {                                                                                           \
        if (!(condition)) {                                                                        \
            std::fprintf(stderr, "%s:%d: CHECK(%s)\n", __FILE__, __LINE__, #condition);            \
            ++g_failures;                                                                          \
        }                                                                                          \
    } while (0)

TraceArgs Parse(std::initializer_list<const wchar_t*> args, TraceRequest* request) {
    std::vector<const wchar_t*> argv(args);
    return ParseTraceArgs(static_cast<int>(argv.size()), argv.data(), request);
}
} // namespace

int main() {
    TraceRequest request;
    CHECK(Parse({L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"0", L"150", L"599"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::FrameDump && request.pmm == L"a.pmm" &&
          request.out == L"dir" && request.frames == 600);
    CHECK((request.dumpFrames == std::vector<std::uint32_t>{0, 150, 599}));
    CHECK(Parse({L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"7"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.frames == 8 && request.dumpFrames.size() == 1);

    // No frame, not ascending, a repeat, out of range, not a number, not a PMM.
    for (auto args : std::vector<std::vector<const wchar_t*>>{
             {L"app", L"--mds-frame-dump", L"a.pmm", L"dir"},
             {L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"5", L"4"},
             {L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"5", L"5"},
             {L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"100000"},
             {L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"-1"},
             {L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L""},
             {L"app", L"--mds-frame-dump", L"a.pmx", L"dir", L"0"},
             {L"app", L"--mds-frame-dump", L"a.pmm", L"", L"0"}}) {
        TraceRequest untouched;
        CHECK(ParseTraceArgs(static_cast<int>(args.size()), args.data(), &untouched) ==
              TraceArgs::Malformed);
        CHECK(untouched.dumpFrames.empty() && untouched.pmm.empty());
    }

    CHECK(Parse({L"app", L"--mds-edge-probe", L"a.pmm", L"probe.txt", L"0", L"30"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::EdgeProbe && request.out == L"probe.txt" &&
          request.frames == 31 && (request.dumpFrames == std::vector<std::uint32_t>{0, 30}));
    CHECK(Parse({L"app", L"--mds-edge-probe", L"a.pmm", L"probe.txt", L"3", L"3"}, &request) ==
          TraceArgs::Malformed);

    CHECK(Parse({L"app", L"--mds-mme-dump", L"a.pmm", L"dir", L"0", L"2"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::MmeDump && request.out == L"dir" &&
          request.frames == 3 && (request.dumpFrames == std::vector<std::uint32_t>{0, 2}));
    CHECK(Parse({L"app", L"--mds-mme-dump", L"a.pmm", L"dir"}, &request) == TraceArgs::Malformed);

    CHECK(Parse({L"app", L"--mds-mesh-dump", L"a.pmm", L"dir", L"cube.x", L"p.vac"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::MeshDump && request.out == L"dir" &&
          (request.meshFiles == std::vector<std::wstring>{L"cube.x", L"p.vac"}));
    CHECK(Parse({L"app", L"--mds-mesh-dump", L"a.pmm", L"dir"}, &request) == TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-mesh-dump", L"a.pmm", L"dir", L""}, &request) ==
          TraceArgs::Malformed);

    CHECK(Parse({L"app", L"--mds-frame-dump-4096", L"a.pmm", L"dir", L"0", L"30"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::FrameDump && request.shadowMapSize == 4096 &&
          request.frames == 31);
    CHECK(Parse({L"app", L"--mds-frame-dump", L"a.pmm", L"dir", L"0"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.shadowMapSize == 0);

    CHECK(Parse({L"app", L"--mds-ground-probe", L"a.pmm", L"g.txt", L"0", L"30"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::GroundProbe && request.out == L"g.txt" &&
          request.frames == 31 && (request.dumpFrames == std::vector<std::uint32_t>{0, 30}));
    CHECK(Parse({L"app", L"--mds-ground-probe", L"a.pmm", L"g.txt"}, &request) ==
          TraceArgs::Malformed);

    CHECK(Parse({L"app", L"--mds-msaa-probe", L"a.pmm", L"msaa.txt"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::MsaaProbe && request.out == L"msaa.txt" &&
          request.dumpFrames.empty());
    CHECK(Parse({L"app", L"--mds-msaa-probe", L"a.pmm", L"msaa.txt", L"0"}, &request) ==
          TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-msaa-probe", L"a.pmx", L"msaa.txt"}, &request) ==
          TraceArgs::Malformed);

    // --mds-trace still parses as a trace.
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o.trace", L"600"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.mode == TraceRequest::Mode::Trace && request.frames == 600 &&
          request.dumpFrames.empty());

    if (g_failures == 0)
        std::puts("frame_dump_args: ok");
    return g_failures == 0 ? 0 : 1;
}
