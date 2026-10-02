#include "mikudancestudio/rhi_image.hpp"
#include <cstdint>
#include <fstream>
#include <iterator>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 2) return 1;
    std::ifstream input(argv[1], std::ios::binary);
    const std::vector<std::uint8_t> png{
        std::istreambuf_iterator<char>{input}, {}};
    mikudancestudio::rhi::RgbaImage image;
    if (!mikudancestudio::rhi::DecodePngRgba(
            png.data(), png.size(), image) ||
        image.width != 512 || image.height != 512 ||
        image.pixels.size() != 512u * 512u * 4u) return 2;
    std::uint64_t hash = 1469598103934665603ull;
    for (std::uint8_t channel : image.pixels)
        hash = (hash ^ channel) * 1099511628211ull;
    if (hash != 0xc710daea6ce8abdeull) return 3;
    image.pixels.clear();
    if (mikudancestudio::rhi::DecodePngRgba(
            png.data(), png.size() / 2, image) ||
        !image.pixels.empty()) return 4;
    return 0;
}
