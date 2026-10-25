// rcp_table.exe - Windows x64 oracle for the SSE reciprocal estimates rcpss
// and rsqrtss of the host CPU, under the default MXCSR.
//
//   rcp_table.exe digest [--threads n]
//       One digest per block of 2^20 inputs over all 2^32 float bit patterns,
//       for rcpss and rsqrtss, as "digest <fn> <block> <hex16>" lines with the
//       rules of math_digest.hpp (NaN outputs canonicalised).
//   rcp_table.exe table [--threads n]
//       The compact form of both instructions: one 2048-entry table each and
//       the exponent and special-value rules below. Then sweeps all 2^32
//       inputs of both and compares the rules with the instruction bit for
//       bit (NaN payloads and signs included) and prints a "# verified" line
//       per function. Exits 1 when any input differs.
//   rcp_table.exe dump <rcpss|rsqrtss> <first> <count> <file>
//       Raw little-endian u32 output bits for inputs first .. first+count-1.
//
// Compact form, b = input bits, s = sign bit, e = biased exponent, m = mantissa.
//   rcpss:   RCP[i] = rcpss(0x3F800000 | i << 12), i = mantissa bits 22..12.
//            e == 0 (zero, denormal): s | inf.  e == 255: m ? b | quiet bit : s.
//            Otherwise the exponent field is 253 - e, or the result is s (zero)
//            when that is below 1; the mantissa field is that of RCP[(b >> 12) & 0x7FF].
//   rsqrtss: RSQ[i] = rsqrtss(0x3F000000 + (i << 13)), i = bits 23..13 of b,
//            so bit 10 of i is the exponent parity. NaN: b | quiet bit.
//            s and e == 0: -inf.  s otherwise: the default NaN 0xFFC00000.
//            +0 and +denormal: +inf.  +inf: +0.  Otherwise RSQ[(b >> 13) & 0x7FF]
//            with (e - 126 - (e & 1)) / 2 subtracted from its exponent field.
//
// Build in a VS 2022 x64 developer shell:
//   cl /nologo /O2 /EHsc /utf-8 /std:c++17 rcp_table.cpp
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <fcntl.h>
#include <intrin.h>
#include <io.h>
#include <xmmintrin.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "math_digest.hpp"

namespace {
using namespace mikudancestudio::oracle;

float Rcp(float x) {
    return _mm_cvtss_f32(_mm_rcp_ss(_mm_set_ss(x)));
}
float Rsqrt(float x) {
    return _mm_cvtss_f32(_mm_rsqrt_ss(_mm_set_ss(x)));
}

const Function kFunctions[] = {
    {"rcpss", Scheme::One, Rcp, nullptr},
    {"rsqrtss", Scheme::One, Rsqrt, nullptr},
};

const Function* Find(const char* name) {
    for (const Function& fn : kFunctions)
        if (std::strcmp(fn.name, name) == 0)
            return &fn;
    return nullptr;
}

std::string CpuBrand() {
    int regs[4];
    char brand[49] = {};
    __cpuid(regs, 0x80000000);
    if (static_cast<unsigned>(regs[0]) < 0x80000004u)
        return "unknown";
    for (unsigned i = 0; i < 3; ++i) {
        __cpuid(regs, static_cast<int>(0x80000002u + i));
        std::memcpy(brand + 16 * i, regs, 16);
    }
    return brand;
}

void PrintHeader(const char* mode) {
    std::printf("# rcp-table 1 mode=%s\n", mode);
    std::printf("# cpu=%s\n", CpuBrand().c_str());
    std::printf("# msc_ver=%d\n", _MSC_VER);
    std::printf("# mxcsr=%08x\n", _mm_getcsr());
}

int RunDigest(int argc, char** argv) {
    unsigned threads = std::thread::hardware_concurrency();
    for (int i = 2; i < argc; ++i) {
        if (std::strcmp(argv[i], "--threads") == 0 && i + 1 < argc)
            threads = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 10));
        else
            return 2;
    }
    PrintHeader("digest");
    std::printf("# blocks=0..%u block_size=%u\n", kBlockCount, kBlockSize);
    for (const Function& fn : kFunctions)
        PrintDigests(stdout, fn, 0, kBlockCount, threads);
    std::printf("# end digest\n");
    return 0;
}

std::uint32_t g_rcp[2048], g_rsq[2048];

std::uint32_t RcpRule(std::uint32_t b) {
    const std::uint32_t s = b & 0x80000000u, e = (b >> 23) & 0xFF, m = b & 0x7FFFFFu;
    if (e == 0)
        return s | 0x7F800000u;
    if (e == 255)
        return m ? b | 0x400000u : s;
    const int exponent = 253 - static_cast<int>(e);
    if (exponent < 1)
        return s;
    return s | static_cast<std::uint32_t>(exponent) << 23 | (g_rcp[(b >> 12) & 0x7FF] & 0x7FFFFFu);
}

std::uint32_t RsqRule(std::uint32_t b) {
    const std::uint32_t e = (b >> 23) & 0xFF;
    if ((b & 0x7FFFFFFFu) > 0x7F800000u)
        return b | 0x400000u;
    if (b >> 31)
        return e == 0 ? 0xFF800000u : 0xFFC00000u;
    if (e == 0)
        return 0x7F800000u;
    if (e == 255)
        return 0;
    const int shift = (static_cast<int>(e) - 126 - static_cast<int>(e & 1)) / 2; // exact: even
    return static_cast<std::uint32_t>(static_cast<int>(g_rsq[(b >> 13) & 0x7FF]) -
                                      shift * (1 << 23));
}

// Inputs where the rule differs from the instruction; the first one in `first`.
std::uint64_t Sweep(const Function& fn, std::uint32_t (*rule)(std::uint32_t), unsigned threads,
                    std::uint32_t* first) {
    std::atomic<std::uint32_t> next{0};
    std::atomic<std::uint64_t> bad{0};
    std::atomic<std::uint32_t> firstBad{0xFFFFFFFFu};
    auto work = [&] {
        for (std::uint32_t block; (block = next.fetch_add(1)) < kBlockCount;) {
            std::uint64_t count = 0;
            for (std::uint32_t i = 0; i < kBlockSize; ++i) {
                const std::uint32_t b = block * kBlockSize + i;
                if (FloatToBits(fn.one(BitsToFloat(b))) == rule(b))
                    continue;
                if (count++ == 0) {
                    std::uint32_t seen = firstBad.load();
                    while (b < seen && !firstBad.compare_exchange_weak(seen, b)) {}
                }
            }
            bad += count;
        }
    };
    std::vector<std::thread> pool;
    for (unsigned t = 1; t < (threads ? threads : 1); ++t)
        pool.emplace_back(work);
    work();
    for (auto& thread : pool)
        thread.join();
    *first = firstBad.load();
    return bad.load();
}

int RunTable(int argc, char** argv) {
    unsigned threads = std::thread::hardware_concurrency();
    for (int i = 2; i < argc; ++i) {
        if (std::strcmp(argv[i], "--threads") == 0 && i + 1 < argc)
            threads = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 10));
        else
            return 2;
    }
    for (std::uint32_t i = 0; i < 2048; ++i) {
        g_rcp[i] = FloatToBits(Rcp(BitsToFloat(0x3F800000u | i << 12)));
        g_rsq[i] = FloatToBits(Rsqrt(BitsToFloat(0x3F000000u + (i << 13))));
    }
    PrintHeader("table");
    std::printf("# rcpss <i> <bits of rcpss(0x3F800000 | i << 12)>\n");
    std::printf("# rsqrtss <i> <bits of rsqrtss(0x3F000000 + (i << 13))>\n");
    std::printf("# rules: tools/oracle/rcp_table.cpp\n");
    for (std::uint32_t i = 0; i < 2048; ++i)
        std::printf("rcpss %u %08x\n", i, g_rcp[i]);
    for (std::uint32_t i = 0; i < 2048; ++i)
        std::printf("rsqrtss %u %08x\n", i, g_rsq[i]);
    std::uint64_t total = 0;
    const struct {
        const Function& fn;
        std::uint32_t (*rule)(std::uint32_t);
    } checks[] = {{kFunctions[0], RcpRule}, {kFunctions[1], RsqRule}};
    for (const auto& check : checks) {
        std::uint32_t first = 0;
        const std::uint64_t bad = Sweep(check.fn, check.rule, threads, &first);
        std::printf("# verified %s inputs=4294967296 mismatches=%llu", check.fn.name,
                    static_cast<unsigned long long>(bad));
        if (bad)
            std::printf(" first=%08x", first);
        std::printf("\n");
        total += bad;
    }
    std::printf("# end table\n");
    return total ? 1 : 0;
}

int RunDump(int argc, char** argv) {
    if (argc != 6)
        return 2;
    const Function* fn = Find(argv[2]);
    if (!fn)
        return 2;
    const std::uint32_t first = static_cast<std::uint32_t>(std::strtoul(argv[3], nullptr, 0));
    const std::uint32_t count = static_cast<std::uint32_t>(std::strtoul(argv[4], nullptr, 0));
    std::vector<std::uint32_t> out(count);
    for (std::uint32_t i = 0; i < count; ++i)
        out[i] = FloatToBits(fn->one(BitsToFloat(first + i)));
    std::FILE* file = std::fopen(argv[5], "wb");
    if (!file || std::fwrite(out.data(), 4, count, file) != count || std::fclose(file))
        return 1;
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    _setmode(_fileno(stdout), _O_BINARY); // LF line ends, so outputs diff against macOS ones
    if (argc >= 2 && std::strcmp(argv[1], "digest") == 0)
        return RunDigest(argc, argv);
    if (argc >= 2 && std::strcmp(argv[1], "table") == 0)
        return RunTable(argc, argv);
    if (argc >= 2 && std::strcmp(argv[1], "dump") == 0)
        return RunDump(argc, argv);
    std::fprintf(stderr, "usage: rcp_table digest [--threads n]\n"
                         "       rcp_table table [--threads n]\n"
                         "       rcp_table dump <rcpss|rsqrtss> <first> <count> <file>\n");
    return 2;
}
