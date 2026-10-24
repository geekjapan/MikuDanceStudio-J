// math_vectors.exe - Windows x64 oracle for the math the model and physics code
// get from D3DX and from the C runtime (RM-3 lanes 6, 7, and 8).
//
//   math_vectors.exe d3dx [--seed N]
//       Lane 6. For every d3dx::Api entry that src/model or src/physics calls
//       (below), feeds fixed seeded inputs to the real d3dx9_43.dll through
//       d3dx::Get() and prints inputs and outputs as hex bit patterns.
//   math_vectors.exe crt [--func a,b] [--blocks first last] [--threads n] [--no-fma3]
//       Lanes 7 and 8. Prints one 64-bit digest per block of 2^20 consecutive
//       float bit patterns (4096 blocks) for sinf cosf tanf asinf acosf atanf
//       atan2f expf logf powf, as "digest <fn> <block> <hex16>" lines. The
//       digest rules (second argument of atan2f and powf, NaN canonicalising)
//       are in math_digest.hpp; math_digest_host builds the same digests from
//       det_math.h, so a diff of the two outputs is lane 8.
//
// Operator runbook (Windows x64 host named by gate G2; all lanes at the PR head
// unless said otherwise). Run the commands in cmd.exe: the redirects of
// Windows PowerShell 5.1 write UTF-16. MikuDanceStudio.exe is a GUI program, so
// cmd does not wait for it or set ERRORLEVEL unless it is started with
// `start /wait "" <exe> <args>`. Build once:
//   cmake -S . -B build -G "Visual Studio 17 2022" -A x64 [conan toolchain]
//   cmake --build build --config Release --target MikuDanceStudio math_vectors fx_reflect trace_format_test
// Lane 1  Regression lane against trunk. Build MikuDanceStudio.exe at trunk
//         and at the head. In each, open tests\fixtures\rust\swing600.pmm in the
//         GUI (no --mds-trace), go to frame 600, save as a new PMM. Pass when
//         `certutil -hashfile trunk.pmm SHA256` equals the head's. Save regression.txt.
// Lane 2  start /wait "" MikuDanceStudio.exe --mds-trace tests\fixtures\rust\swing600.pmm a.trace 600
//         echo %ERRORLEVEL%
//         start /wait "" MikuDanceStudio.exe --mds-trace tests\fixtures\rust\swing600.pmm b.trace 600
//         echo %ERRORLEVEL% & fc /b a.trace b.trace & findstr /n /b /c:"mds-trace 1 L2" a.trace
//         (exit 0 both, `1:mds-trace 1 L2`, files identical). Save l2-repeat.txt.
// Lane 3  Build a PMM that holds tests\fixtures\rust\chain8_ik.pmx (load the
//         model in the GUI, save as chain8_ik.pmm), then run --mds-trace on it
//         twice as in lane 2. Save l2-ik.txt.
// Lane 4  Same for chain8.pmx with its rigid bodies in a PMM with physics on
//         (physics mode 1 or 2). Pass when the trace has 600 frames of `rigid`
//         lines (`findstr /b /c:"599 rigid" l2.trace`) and the two runs match.
//         Save l2-physics.txt.
// Lane 5  Compare the `bone` and `morph` lines of the lane 2 trace with the L1
//         trace of RM-2 (`mds_scene_cli`) for the same PMM. List every
//         differing (kind, slot, index). Save l1-vs-l2.txt.
// Lane 6  math_vectors.exe d3dx > d3dx-vectors.txt
//         Pass when the summary lines cover the 12 entries below.
// Lane 7  math_vectors.exe crt > crt-digests.txt ; also with --no-fma3 >
//         crt-digests-nofma3.txt. Pass when each of the 10 functions has 4096
//         `digest` lines (`findstr /b /c:"digest sinf " crt-digests.txt | find /c /v ""`).
//         Why two runs: the UCRT picks FMA3 code paths for several of these
//         functions when the CPU has FMA3, and the original x64 build used the
//         VC10 CRT without FMA3. The header lines record the CPU.
// Lane 8  On macOS: clang++ -std=c++17 -O2 -pthread -I tools/oracle
//           tools/oracle/math_digest_host.cpp -o math_digest_host
//         ./math_digest_host > det.txt ; diff <(grep ^digest det.txt)
//           <(grep ^digest crt-digests.txt) | grep -c '^<'  per function.
//         Save det-vs-crt.txt with the per-function count of differing blocks.
// Lane 9  fx_reflect.exe over the ray-mmd corpus and res\assets\*.fx (see fx_reflect.cpp).
// Lane 10 start "" MikuDanceStudio.exe  (the GUI starts as before; close it), then
//         start /wait "" MikuDanceStudio.exe --mds-trace C:\no\such.pmm x.trace 5
//         echo %ERRORLEVEL% & dir x.trace x.trace.tmp
//         (1, and both files absent). Save startup.txt.
// Perf    tools\oracle\startup_time.ps1, see that file.
//
// D3DX entries covered (d3dx::Api members called through d3dx::Get() from
// src/model and src/physics): multiply inverse quatFromMatrix vec3Normalize
// quatMultiply matrixRotationQuaternion quatToAxisAngle quatNormalize rotX
// rotY rotZ translation.
// Not covered: fromFileExW, called from src/model/path_resolve.cpp. It is a
// texture loader that needs a Direct3D device and a file, not a math function.
// struct Api holds static member functions, not function pointers.
//
// Output lines (d3dx mode), bit patterns are 8 lowercase hex digits per float,
// arrays are comma separated:
//   d3dx <fn> <n> <argname>=<words> ... ret=<0|1> <outname>=<words> ...
// ret=0 means the call returned a null pointer (D3DX does this for a singular
// inverse). Output buffers are prefilled with the sentinel 0x3f800001.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <fcntl.h>
#include <intrin.h>
#include <io.h>
#include <math.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "mikudancestudio/d3dx_dyn.hpp"
#include "math_digest.hpp"

namespace {
using mikudancestudio::d3dx::D3DXMATRIXF;
using mikudancestudio::oracle::BitsToFloat;
using mikudancestudio::oracle::FloatToBits;

struct SplitMix64 {
    std::uint64_t state;
    std::uint64_t Next() {
        std::uint64_t z = (state += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    // Uniform in [-2, 2): a 24 bit integer scaled by powers of two, exact.
    float Float() { return static_cast<float>(Next() >> 40) / 16777216.0f * 4.0f - 2.0f; }
};

std::string Words(const float* values, int count) {
    std::string text;
    char word[12];
    for (int i = 0; i < count; ++i) {
        std::snprintf(word, sizeof word, i ? ",%08x" : "%08x", FloatToBits(values[i]));
        text += word;
    }
    return text;
}

void Fill(float* values, int count) {
    for (int i = 0; i < count; ++i) values[i] = BitsToFloat(0x3f800001u);
}

void Line(const char* fn, int n, const std::string& body) {
    std::printf("d3dx %s %d %s\n", fn, n, body.c_str());
}

void Matrix(SplitMix64& rng, float m[16]) {
    for (int i = 0; i < 16; ++i) m[i] = rng.Float();
}
void Quaternion(SplitMix64& rng, float q[4], bool unit) {
    for (int i = 0; i < 4; ++i) q[i] = rng.Float();
    if (!unit) return;
    const float length = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
    for (int i = 0; i < 4; ++i) q[i] /= length;
}

constexpr int kRandomCases = 32;
int g_counts[12];
const char* const kNames[12] = {"multiply", "inverse", "quatFromMatrix", "vec3Normalize",
                                "quatMultiply", "matrixRotationQuaternion", "quatToAxisAngle",
                                "quatNormalize", "rotX", "rotY", "rotZ", "translation"};
void Count(int index) { ++g_counts[index]; }

int RunD3dx(std::uint64_t seed) {
    auto& api = mikudancestudio::d3dx::Get();
    SplitMix64 rng{seed};
    const float identity[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    const float zero[16] = {};
    const float unitQuat[4] = {0, 0, 0, 1};
    const float zeroQuat[4] = {0, 0, 0, 0};

    // multiply: out = a * b
    for (int n = 0; n < kRandomCases + 3; ++n) {
        float a[16], b[16], out[16];
        Matrix(rng, a);
        Matrix(rng, b);
        if (n == kRandomCases) std::memcpy(a, identity, sizeof a);
        if (n == kRandomCases + 1) std::memcpy(b, identity, sizeof b);
        if (n == kRandomCases + 2) std::memcpy(a, zero, sizeof a);
        Fill(out, 16);
        const bool ret = api.multiply(reinterpret_cast<D3DXMATRIXF*>(out),
                                      reinterpret_cast<const D3DXMATRIXF*>(a),
                                      reinterpret_cast<const D3DXMATRIXF*>(b)) != nullptr;
        Line("multiply", n, "a=" + Words(a, 16) + " b=" + Words(b, 16) +
                                " ret=" + (ret ? "1" : "0") + " out=" + Words(out, 16));
        Count(0);
    }
    // inverse: physics passes a null determinant; both forms are recorded.
    for (int n = 0; n < kRandomCases + 2; ++n) {
        float m[16], out[16], det = BitsToFloat(0x3f800001u);
        Matrix(rng, m);
        if (n == kRandomCases) std::memcpy(m, identity, sizeof m);
        if (n == kRandomCases + 1) std::memcpy(m, zero, sizeof m);
        Fill(out, 16);
        const bool withDet = (n & 1) == 0;
        const bool ret = api.inverse(reinterpret_cast<D3DXMATRIXF*>(out), withDet ? &det : nullptr,
                                     reinterpret_cast<const D3DXMATRIXF*>(m)) != nullptr;
        Line("inverse", n, "m=" + Words(m, 16) + " detarg=" + (withDet ? "1" : "0") +
                               " ret=" + (ret ? "1" : "0") + " det=" + Words(&det, 1) +
                               " out=" + Words(out, 16));
        Count(1);
    }
    // quatFromMatrix: rotation matrices built the way the loaders build them,
    // plus raw random matrices.
    for (int n = 0; n < kRandomCases + 1; ++n) {
        float m[16], out[4];
        if (n == kRandomCases) {
            std::memcpy(m, identity, sizeof m);
        } else if ((n & 1) == 0) {
            D3DXMATRIXF x, y, z, xy, xyz;
            api.rotX(&x, rng.Float() * 3.0f);
            api.rotY(&y, rng.Float() * 3.0f);
            api.rotZ(&z, rng.Float() * 3.0f);
            api.multiply(&xy, &x, &y);
            api.multiply(&xyz, &xy, &z);
            std::memcpy(m, &xyz, sizeof m);
        } else {
            Matrix(rng, m);
        }
        Fill(out, 4);
        const bool ret =
            api.quatFromMatrix(out, reinterpret_cast<const D3DXMATRIXF*>(m)) != nullptr;
        Line("quatFromMatrix", n, "m=" + Words(m, 16) + " ret=" + (ret ? "1" : "0") +
                                      " out=" + Words(out, 4));
        Count(2);
    }
    // vec3Normalize
    for (int n = 0; n < kRandomCases + 3; ++n) {
        float v[3] = {rng.Float(), rng.Float(), rng.Float()};
        float out[3];
        if (n == kRandomCases) v[0] = v[1] = v[2] = 0.0f;
        if (n == kRandomCases + 1) { v[0] = 1e-30f; v[1] = 0.0f; v[2] = 0.0f; }
        if (n == kRandomCases + 2) { v[0] = 3e18f; v[1] = 4e18f; v[2] = 0.0f; }
        Fill(out, 3);
        const bool ret = api.vec3Normalize(out, v) != nullptr;
        Line("vec3Normalize", n, "v=" + Words(v, 3) + " ret=" + (ret ? "1" : "0") +
                                     " out=" + Words(out, 3));
        Count(3);
    }
    // quatMultiply
    for (int n = 0; n < kRandomCases + 1; ++n) {
        float a[4], b[4], out[4];
        Quaternion(rng, a, (n & 1) != 0);
        Quaternion(rng, b, (n & 2) != 0);
        if (n == kRandomCases) { std::memcpy(a, unitQuat, sizeof a); }
        Fill(out, 4);
        const bool ret = api.quatMultiply(out, a, b) != nullptr;
        Line("quatMultiply", n, "a=" + Words(a, 4) + " b=" + Words(b, 4) +
                                    " ret=" + (ret ? "1" : "0") + " out=" + Words(out, 4));
        Count(4);
    }
    // matrixRotationQuaternion (the loader feeds zero quaternions)
    for (int n = 0; n < kRandomCases + 2; ++n) {
        float q[4], out[16];
        Quaternion(rng, q, (n & 1) != 0);
        if (n == kRandomCases) std::memcpy(q, zeroQuat, sizeof q);
        if (n == kRandomCases + 1) std::memcpy(q, unitQuat, sizeof q);
        Fill(out, 16);
        const bool ret =
            api.matrixRotationQuaternion(reinterpret_cast<D3DXMATRIXF*>(out), q) != nullptr;
        Line("matrixRotationQuaternion", n,
             "q=" + Words(q, 4) + " ret=" + (ret ? "1" : "0") + " out=" + Words(out, 16));
        Count(5);
    }
    // quatToAxisAngle: void; outputs are axis[3] and angle
    for (int n = 0; n < kRandomCases + 3; ++n) {
        float q[4], axis[3], angle = BitsToFloat(0x3f800001u);
        Quaternion(rng, q, (n & 1) != 0);
        if (n == kRandomCases) std::memcpy(q, unitQuat, sizeof q);
        if (n == kRandomCases + 1) std::memcpy(q, zeroQuat, sizeof q);
        if (n == kRandomCases + 2) { q[0] = q[1] = q[2] = 0.0f; q[3] = 1.5f; }
        Fill(axis, 3);
        api.quatToAxisAngle(q, axis, &angle);
        Line("quatToAxisAngle", n, "q=" + Words(q, 4) + " axis=" + Words(axis, 3) +
                                       " angle=" + Words(&angle, 1));
        Count(6);
    }
    // quatNormalize
    for (int n = 0; n < kRandomCases + 2; ++n) {
        float q[4], out[4];
        Quaternion(rng, q, false);
        if (n == kRandomCases) std::memcpy(q, zeroQuat, sizeof q);
        if (n == kRandomCases + 1) std::memcpy(q, unitQuat, sizeof q);
        Fill(out, 4);
        const bool ret = api.quatNormalize(out, q) != nullptr;
        Line("quatNormalize", n, "q=" + Words(q, 4) + " ret=" + (ret ? "1" : "0") +
                                     " out=" + Words(out, 4));
        Count(7);
    }
    // rotX rotY rotZ: angles in radians, random in [-6, 6) plus the usual suspects
    const float angles[] = {0.0f, 1.5707964f, -1.5707964f, 3.1415927f, -3.1415927f,
                            6.2831855f, 1e-8f, 100.0f, 1e6f};
    using RotFn = D3DXMATRIXF* (WINAPI*)(D3DXMATRIXF*, float);
    const RotFn rotations[3] = {&mikudancestudio::d3dx::Api::rotX,
                                &mikudancestudio::d3dx::Api::rotY,
                                &mikudancestudio::d3dx::Api::rotZ};
    for (int axisIndex = 0; axisIndex < 3; ++axisIndex) {
        for (int n = 0; n < kRandomCases + 9; ++n) {
            const float angle = n < kRandomCases ? rng.Float() * 3.0f : angles[n - kRandomCases];
            float out[16];
            Fill(out, 16);
            const bool ret = rotations[axisIndex](reinterpret_cast<D3DXMATRIXF*>(out), angle) != nullptr;
            Line(kNames[8 + axisIndex], n,
                 "angle=" + Words(&angle, 1) + " ret=" + (ret ? "1" : "0") + " out=" + Words(out, 16));
            Count(8 + axisIndex);
        }
    }
    // translation
    for (int n = 0; n < kRandomCases; ++n) {
        const float t[3] = {rng.Float() * 100.0f, rng.Float() * 100.0f, rng.Float()};
        float out[16];
        Fill(out, 16);
        const bool ret = api.translation(reinterpret_cast<D3DXMATRIXF*>(out), t[0], t[1], t[2]) != nullptr;
        Line("translation", n, "t=" + Words(t, 3) + " ret=" + (ret ? "1" : "0") + " out=" + Words(out, 16));
        Count(11);
    }
    for (int i = 0; i < 12; ++i) std::printf("summary d3dx %s %d\n", kNames[i], g_counts[i]);
    std::printf("# end d3dx\n");
    return 0;
}

std::string CpuBrand() {
    int regs[4];
    char brand[49] = {};
    __cpuid(regs, 0x80000000);
    if (static_cast<unsigned>(regs[0]) < 0x80000004u) return "unknown";
    for (unsigned i = 0; i < 3; ++i) {
        __cpuid(regs, static_cast<int>(0x80000002u + i));
        std::memcpy(brand + 16 * i, regs, 16);
    }
    return brand;
}

void PrintHeader(const char* mode) {
    std::printf("# math-vectors 1 mode=%s\n", mode);
    std::printf("# cpu=%s\n", CpuBrand().c_str());
    std::printf("# msc_ver=%d\n", _MSC_VER);
    if (HMODULE d3dx = GetModuleHandleA("d3dx9_43.dll")) {
        char path[MAX_PATH] = {};
        GetModuleFileNameA(d3dx, path, MAX_PATH);
        std::printf("# d3dx_module=%s\n", path);
    }
}

int RunCrt(int argc, char** argv) {
    using namespace mikudancestudio::oracle;
    const Function functions[] = {MDS_DIGEST_FUNCTIONS};
    std::string only;
    std::uint32_t first = 0, last = kBlockCount;
    unsigned threads = std::thread::hardware_concurrency();
    bool noFma3 = false;
    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--func" && i + 1 < argc) {
            only = "," + std::string(argv[++i]) + ",";
        } else if (arg == "--blocks" && i + 2 < argc) {
            first = static_cast<std::uint32_t>(std::strtoul(argv[++i], nullptr, 10));
            last = static_cast<std::uint32_t>(std::strtoul(argv[++i], nullptr, 10));
        } else if (arg == "--threads" && i + 1 < argc) {
            threads = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 10));
        } else if (arg == "--no-fma3") {
            noFma3 = true;
        } else {
            return 2;
        }
    }
    if (first >= last || last > kBlockCount) return 2;
    // UCRT x64: switch the FMA3 code paths of the math functions off or on.
    // Returns nonzero when they are enabled after the call.
    const int fma3 = _set_FMA3_enable(noFma3 ? 0 : 1);
    PrintHeader("crt");
    std::printf("# fma3_enabled=%d blocks=%u..%u block_size=%u\n", fma3, first, last, kBlockSize);
    for (const Function& fn : functions) {
        if (!only.empty() && only.find("," + std::string(fn.name) + ",") == std::string::npos)
            continue;
        PrintDigests(stdout, fn, first, last, threads ? threads : 1);
    }
    std::printf("# end crt\n");
    return 0;
}
}  // namespace

int main(int argc, char** argv) {
    _setmode(_fileno(stdout), _O_BINARY);  // LF line ends, so outputs diff against macOS ones
    if (argc >= 2 && std::strcmp(argv[1], "d3dx") == 0) {
        std::uint64_t seed = 0x4d445331u;  // "MDS1"
        if (argc == 4 && std::strcmp(argv[2], "--seed") == 0)
            seed = std::strtoull(argv[3], nullptr, 0);
        else if (argc != 2)
            return 2;
        PrintHeader("d3dx");
        std::printf("# seed=0x%llx\n", static_cast<unsigned long long>(seed));
        return RunD3dx(seed);
    }
    if (argc >= 2 && std::strcmp(argv[1], "crt") == 0) return RunCrt(argc, argv);
    std::fprintf(stderr,
                 "usage: math_vectors d3dx [--seed N]\n"
                 "       math_vectors crt [--func a,b] [--blocks first last] [--threads n] [--no-fma3]\n");
    return 2;
}
