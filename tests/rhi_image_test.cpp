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
    // Generated legal TGA fixture: bottom-up BGRA -> canonical top-down RGBA.
    std::vector<std::uint8_t> tga(18);tga[2]=2;tga[12]=2;tga[14]=2;tga[16]=32;tga[17]=8;
    tga.insert(tga.end(),{255,0,0,17, 255,255,255,18, 0,0,255,19, 0,255,0,20});
    if(!mikudancestudio::rhi::DecodeTextureRgba(tga.data(),tga.size(),image) || image.pixels!=std::vector<std::uint8_t>{255,0,0,19,0,255,0,20,0,0,255,17,255,255,255,18})return 5;
    if(mikudancestudio::rhi::DecodeTextureRgba(tga.data(),tga.size()-1,image) || !image.pixels.empty())return 6;
    tga.resize(18);tga[2]=10;tga[17]=0x28;tga.insert(tga.end(),{0x81,0,0,255,255,1,0,255,0,128,255,0,0,64});
    if(!mikudancestudio::rhi::DecodeTextureRgba(tga.data(),tga.size(),image) || image.pixels!=std::vector<std::uint8_t>{255,0,0,255,255,0,0,255,0,255,0,128,0,0,255,64})return 7;
    tga[18]=0x84;if(mikudancestudio::rhi::DecodeTextureRgba(tga.data(),tga.size(),image) || !image.pixels.empty())return 8;
    return 0;
}
