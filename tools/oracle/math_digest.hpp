// Portable block digests of float math functions over all 2^32 float bit
// patterns. Included by math_vectors.cpp (MSVC CRT, Windows) and by
// math_digest_host.cpp (det_math.h, macOS or Linux). Both sides must compute
// bit-identical digests for bit-identical function results, so every rule
// below is part of the format. No platform headers.
//
// Domain. Input number b in [0, 2^32) is the bit pattern of the float x.
// Block k covers b in [k * 2^20, (k + 1) * 2^20): 4096 blocks, ascending b.
//
// Two-argument functions. The second argument is a pure function of b:
//   h  = fmix32(b)                        (murmur3 finalizer)
//   atan2f(y = x, x2):  x2 has the sign and 23 mantissa bits of h and the
//                       biased exponent of x moved by ((h >> 23) % 9) - 4,
//                       clamped to [1, 254]. The ratio stays near 2^+-4.
//   powf(x, y):         y has the sign and mantissa bits of h and the biased
//                       exponent 123 + ((h >> 23) % 9), so |y| in [2^-4, 2^5).
// atan2f(y, x) receives the swept value as y and the derived value as x.
//
// Digest. out = bits of f(...) as uint32; any NaN is replaced by 0x7FC00000
// (NaN payload and sign differ between CRTs and are not compared). Then
//   state = 0xCBF29CE484222325
//   per input in ascending b:  state = (state ^ out) * 0x9E3779B97F4A7C15
//                              state ^= state >> 32
// The block digest is the final state, printed as 16 lowercase hex digits.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

namespace mikudancestudio::oracle {

inline float BitsToFloat(std::uint32_t bits) {
    float value;
    std::memcpy(&value, &bits, sizeof value);
    return value;
}
inline std::uint32_t FloatToBits(float value) {
    std::uint32_t bits;
    std::memcpy(&bits, &value, sizeof bits);
    return bits;
}
inline std::uint32_t Fmix32(std::uint32_t h) {
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    h *= 0xC2B2AE35u;
    h ^= h >> 16;
    return h;
}

enum class Scheme { One, Atan2, Pow };

inline float SecondArgument(Scheme scheme, std::uint32_t b) {
    const std::uint32_t h = Fmix32(b);
    std::uint32_t exponent = 0;
    if (scheme == Scheme::Atan2) {
        const int moved = static_cast<int>((b >> 23) & 0xFF) +
                          static_cast<int>((h >> 23) % 9) - 4;
        exponent = static_cast<std::uint32_t>(moved < 1 ? 1 : moved > 254 ? 254 : moved);
    } else {
        exponent = 123 + (h >> 23) % 9;
    }
    return BitsToFloat((h & 0x807FFFFFu) | (exponent << 23));
}

struct Function {
    const char* name;
    Scheme scheme;
    float (*one)(float);
    float (*two)(float, float);
};

inline std::uint32_t CanonicalBits(float value) {
    const std::uint32_t bits = FloatToBits(value);
    return (bits & 0x7FFFFFFFu) > 0x7F800000u ? 0x7FC00000u : bits;
}

constexpr std::uint32_t kBlockCount = 4096;
constexpr std::uint32_t kBlockSize = 1u << 20;

inline std::uint64_t BlockDigest(const Function& fn, std::uint32_t block) {
    std::uint64_t state = 0xCBF29CE484222325ull;
    const std::uint32_t first = block * kBlockSize;
    for (std::uint32_t i = 0; i < kBlockSize; ++i) {
        const std::uint32_t b = first + i;
        const float x = BitsToFloat(b);
        const float result = fn.scheme == Scheme::One
                                 ? fn.one(x)
                                 : fn.two(x, SecondArgument(fn.scheme, b));
        state = (state ^ CanonicalBits(result)) * 0x9E3779B97F4A7C15ull;
        state ^= state >> 32;
    }
    return state;
}

// Digests for blocks [firstBlock, lastBlock) on `threads` workers; one
// "digest <fn> <block> <hex16>" line per block, printed in ascending block
// order. Returns the number of lines printed.
inline std::uint32_t PrintDigests(std::FILE* out, const Function& fn, std::uint32_t firstBlock,
                                  std::uint32_t lastBlock, unsigned threads) {
    const std::uint32_t count = lastBlock - firstBlock;
    std::vector<std::uint64_t> digests(count);
    std::atomic<std::uint32_t> next{0};
    auto work = [&] {
        for (std::uint32_t i; (i = next.fetch_add(1)) < count;)
            digests[i] = BlockDigest(fn, firstBlock + i);
    };
    std::vector<std::thread> pool;
    for (unsigned t = 1; t < (threads ? threads : 1); ++t) pool.emplace_back(work);
    work();
    for (auto& thread : pool) thread.join();
    for (std::uint32_t i = 0; i < count; ++i)
        std::fprintf(out, "digest %s %u %016llx\n", fn.name, firstBlock + i,
                     static_cast<unsigned long long>(digests[i]));
    return count;
}

// Same table text in both programs; expanded where sinf etc. mean the local
// math library (the CRT on Windows, det_math.h on the host).
#define MDS_DIGEST_FUNCTIONS                                                              \
    {"sinf", Scheme::One, [](float x) { return sinf(x); }, nullptr},                      \
    {"cosf", Scheme::One, [](float x) { return cosf(x); }, nullptr},                      \
    {"tanf", Scheme::One, [](float x) { return tanf(x); }, nullptr},                      \
    {"asinf", Scheme::One, [](float x) { return asinf(x); }, nullptr},                    \
    {"acosf", Scheme::One, [](float x) { return acosf(x); }, nullptr},                    \
    {"atanf", Scheme::One, [](float x) { return atanf(x); }, nullptr},                    \
    {"atan2f", Scheme::Atan2, nullptr, [](float y, float x) { return atan2f(y, x); }},    \
    {"expf", Scheme::One, [](float x) { return expf(x); }, nullptr},                      \
    {"logf", Scheme::One, [](float x) { return logf(x); }, nullptr},                      \
    {"powf", Scheme::Pow, nullptr, [](float x, float y) { return powf(x, y); }}

}  // namespace mikudancestudio::oracle
