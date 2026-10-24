// macOS/Linux build of the block digests with det_math.h (lane 8 reference).
//   clang++ -std=c++17 -O2 -pthread -I tools/oracle tools/oracle/math_digest_host.cpp -o /tmp/math_digest_host
//   /tmp/math_digest_host [--func name[,name...]] [--blocks first last] [--threads n]
// Prints the same "digest <fn> <block> <hex16>" lines as `math_vectors.exe crt`,
// so `diff` of the two outputs lists the blocks that differ.
// The functions are the det_math.h ones: sinf is (float)sin((double)x) etc.
#include "det_math.h"  // must come first: it #defines sinf, cosf, ...
#include "math_digest.hpp"

#include <chrono>
#include <cstdlib>
#include <string>

using namespace mikudancestudio::oracle;

int main(int argc, char** argv) {
    const Function functions[] = {MDS_DIGEST_FUNCTIONS};
    std::string only;
    std::uint32_t first = 0, last = kBlockCount;
    unsigned threads = std::thread::hardware_concurrency();
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--func" && i + 1 < argc) {
            only = "," + std::string(argv[++i]) + ",";
        } else if (arg == "--blocks" && i + 2 < argc) {
            first = static_cast<std::uint32_t>(std::strtoul(argv[++i], nullptr, 10));
            last = static_cast<std::uint32_t>(std::strtoul(argv[++i], nullptr, 10));
        } else if (arg == "--threads" && i + 1 < argc) {
            threads = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 10));
        } else {
            std::fprintf(stderr, "usage: %s [--func a,b] [--blocks first last] [--threads n]\n",
                         argv[0]);
            return 2;
        }
    }
    if (first >= last || last > kBlockCount) {
        std::fprintf(stderr, "blocks must satisfy 0 <= first < last <= %u\n", kBlockCount);
        return 2;
    }
    std::printf("# math-digest 1 source=det_math.h blocks=%u..%u block_size=%u\n", first, last,
                kBlockSize);
    for (const Function& fn : functions) {
        if (!only.empty() && only.find("," + std::string(fn.name) + ",") == std::string::npos)
            continue;
        const auto start = std::chrono::steady_clock::now();
        PrintDigests(stdout, fn, first, last, threads ? threads : 1);
        const double seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        std::fprintf(stderr, "# %s %u blocks, %u threads, %.1f s\n", fn.name, last - first,
                     threads, seconds);
    }
    return 0;
}
