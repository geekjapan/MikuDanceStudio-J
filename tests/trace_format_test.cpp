// Portable test of the L2 trace line formatter and the --mds-trace argument
// parser. Standalone: no Windows, Bullet, or app headers.
// Build and run on macOS or Linux:
//   clang++ -std=c++17 -Wall -Wextra -I src/tools tests/trace_format_test.cpp -o /tmp/trace_format_test && /tmp/trace_format_test
// On Windows it is the ctest target: ctest --test-dir build -R trace_format
#include "trace_args.hpp"
#include "trace_l2.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

namespace {
int g_failures = 0;
#define CHECK(condition)                                                          \
    do {                                                                          \
        if (!(condition)) {                                                       \
            std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, \
                         #condition);                                             \
            ++g_failures;                                                         \
        }                                                                         \
    } while (0)

using namespace mikudancestudio::tools;

float FromBits(std::uint32_t bits) {
    float value;
    std::memcpy(&value, &bits, sizeof value);
    return value;
}

std::string Hex(float value) {
    char text[20];
    return l2::FormatHexFloat(value, text) == 0 ? std::string("<none>") : std::string(text);
}

void TestHexFloat() {
    CHECK(Hex(1.0f) == "0x1.000000p+0");
    CHECK(Hex(3.0f) == "0x1.800000p+1");
    CHECK(Hex(-0.5f) == "-0x1.000000p-1");
    CHECK(Hex(0.0f) == "0x0.000000p+0");
    CHECK(Hex(-0.0f) == "-0x0.000000p+0");
    CHECK(Hex(0.1f) == "0x1.99999ap-4");
    CHECK(Hex(FromBits(0x7F7FFFFFu)) == "0x1.fffffep+127");
    CHECK(Hex(FromBits(0x00800000u)) == "0x1.000000p-126");
    CHECK(Hex(FromBits(0x00000001u)) == "0x1.000000p-149");  // smallest subnormal
    CHECK(Hex(FromBits(0x00400000u)) == "0x1.000000p-127");  // largest-bit subnormal
    CHECK(Hex(FromBits(0x007FFFFFu)) == "0x1.fffffcp-127");
    CHECK(Hex(std::numeric_limits<float>::infinity()) == "<none>");
    CHECK(Hex(-std::numeric_limits<float>::infinity()) == "<none>");
    CHECK(Hex(std::numeric_limits<float>::quiet_NaN()) == "<none>");
}

// Every sampled float must parse back to itself; on a C library whose %a
// agrees (not MSVC) the text must equal printf("%.6a") of the widened value.
void TestRoundTrip() {
    std::uint32_t state = 12345;
    for (int i = 0; i < 200000; ++i) {
        state = state * 1664525u + 1013904223u;
        const float value = FromBits(state);
        char text[20];
        if (!std::isfinite(value)) {
            CHECK(l2::FormatHexFloat(value, text) == 0);
            continue;
        }
        const std::size_t length = l2::FormatHexFloat(value, text);
        CHECK(length > 0 && length < 20 && text[length] == '\0');
        const double parsed = std::strtod(text, nullptr);
        CHECK(parsed == static_cast<double>(value));
        CHECK(std::signbit(parsed) == std::signbit(value));
#if !defined(_MSC_VER)
        char reference[40];
        std::snprintf(reference, sizeof reference, "%.6a", static_cast<double>(value));
        CHECK(std::strcmp(reference, text) == 0);
#endif
    }
}

void TestLines() {
    const float translation[3] = {1.0f, -2.0f, 0.5f};
    const float rotation[4] = {0.0f, 0.0f, 0.0f, 1.0f};
    float matrix[16] = {};
    for (int i = 0; i < 4; ++i) matrix[i * 5] = 1.0f;
    matrix[12] = 3.0f;
    matrix[13] = -0.0f;
    matrix[14] = 0.1f;
    const float position[3] = {0.25f, 10.0f, -1.5f};
    const float quaternion[4] = {0.0f, 0.70710677f, 0.0f, 0.70710677f};

    std::ostringstream out;
    l2::WriteHeader(out);
    CHECK(l2::WriteBoneLine(out, 7, 0, 12, translation, rotation));
    CHECK(l2::WriteBoneWorldLine(out, 7, 0, 12, matrix));
    CHECK(l2::WriteMorphLine(out, 7, 1, 3, 0.5f));
    CHECK(l2::WriteRigidLine(out, 7, 1, 40, position, quaternion));
    const std::string expected =
        "mds-trace 1 L2\n"
        "7 bone 0 12 0x1.000000p+0 -0x1.000000p+1 0x1.000000p-1 "
        "0x0.000000p+0 0x0.000000p+0 0x0.000000p+0 0x1.000000p+0\n"
        "7 bonew 0 12 0x1.000000p+0 0x0.000000p+0 0x0.000000p+0 0x0.000000p+0 "
        "0x0.000000p+0 0x1.000000p+0 0x0.000000p+0 0x0.000000p+0 "
        "0x0.000000p+0 0x0.000000p+0 0x1.000000p+0 0x0.000000p+0 "
        "0x1.800000p+1 -0x0.000000p+0 0x1.99999ap-4 0x1.000000p+0\n"
        "7 morph 1 3 0x1.000000p-1\n"
        "7 rigid 1 40 0x1.000000p-2 0x1.400000p+3 -0x1.800000p+0 "
        "0x0.000000p+0 0x1.6a09e6p-1 0x0.000000p+0 0x1.6a09e6p-1\n";
    CHECK(out.str() == expected);
    if (out.str() != expected) std::fprintf(stderr, "got:\n%s", out.str().c_str());

    // A non-finite value fails the line, so the caller discards the trace.
    std::ostringstream bad;
    const float notNumber[3] = {0.0f, std::numeric_limits<float>::quiet_NaN(), 0.0f};
    CHECK(!l2::WriteBoneLine(bad, 0, 0, 0, notNumber, rotation));
    CHECK(!l2::WriteMorphLine(bad, 0, 0, 0, std::numeric_limits<float>::infinity()));
    float badMatrix[16] = {};
    badMatrix[15] = std::numeric_limits<float>::infinity();
    CHECK(!l2::WriteBoneWorldLine(bad, 0, 0, 0, badMatrix));
    CHECK(!l2::WriteRigidLine(bad, 0, 0, 0, notNumber, quaternion));
}

TraceArgs Parse(std::initializer_list<const wchar_t*> args, TraceRequest* request) {
    std::vector<const wchar_t*> argv(args);
    return ParseTraceArgs(static_cast<int>(argv.size()), argv.data(), request);
}

void TestArgs() {
    TraceRequest request;
    CHECK(ParseTraceArgs(2, nullptr, &request) == TraceArgs::NotRequested);
    CHECK(Parse({L"app"}, &request) == TraceArgs::NotRequested);
    CHECK(Parse({L"app", L"scene.pmm"}, &request) == TraceArgs::NotRequested);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o.trace", L"600"}, &request) ==
          TraceArgs::Ready);
    CHECK(request.pmm == L"a.pmm" && request.out == L"o.trace" && request.frames == 600);
    CHECK(Parse({L"app", L"--mds-trace", L"DIR\\A.PMM", L"o", L"1"}, &request) ==
          TraceArgs::Ready);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"100000"}, &request) ==
          TraceArgs::Ready);
    CHECK(Parse({L"app", L"--mds-trace"}, &request) == TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o"}, &request) == TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"5", L"x"}, &request) ==
          TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"0"}, &request) == TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"-3"}, &request) ==
          TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"12x"}, &request) ==
          TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"100001"}, &request) ==
          TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"o", L"9999999"}, &request) ==
          TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmd", L"o", L"5"}, &request) == TraceArgs::Malformed);
    CHECK(Parse({L"app", L"--mds-trace", L"a.pmm", L"", L"5"}, &request) == TraceArgs::Malformed);
    CHECK(Parse({L"app", L"x.pmm", L"--mds-trace", L"a.pmm", L"o", L"5"}, &request) ==
          TraceArgs::NotRequested);
}
}  // namespace

int main() {
    TestHexFloat();
    TestRoundTrip();
    TestLines();
    TestArgs();
    if (g_failures != 0) {
        std::fprintf(stderr, "trace_format_test: %d failure(s)\n", g_failures);
        return 1;
    }
    std::puts("trace_format_test: ok");
    return 0;
}
