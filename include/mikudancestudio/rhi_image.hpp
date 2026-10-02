#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include <memory>

namespace mikudancestudio::rhi {
struct RgbaImage {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::vector<std::uint8_t> pixels;
};
// Optional backend service. Raw decode and explicit target size remain owned
// by the caller. Failure clears output; it never authorizes a parity gate.
class TexturePreparer {
public:
    virtual ~TexturePreparer() = default;
    virtual bool Prepare(const RgbaImage& source, std::uint32_t width,
                         std::uint32_t height, RgbaImage& prepared) = 0;
};

// Decode a PNG asset at the portable boundary. Pixels are tightly packed RGBA8.
bool DecodePngRgba(const void* bytes, std::size_t length, RgbaImage& image);
// Content detection, independent of filename extension. Supports PNG and BMP.
bool DecodeTextureRgba(const void* bytes, std::size_t length, RgbaImage& image);
std::uint64_t ImageRevision(const RgbaImage& image);
// Experimental legacy resize candidate. Integrates the periodic bilinear
// reconstruction over destination texels, then applies ordered 4x4 dithering.
// Explicit dimensions come from a host policy, never from the decoder. It is
// NOT a claim of bit-identical D3DX filtering; callers must validate before use.
bool PrepareTriangleDitherWrap(const RgbaImage& source, std::uint32_t width,
                              std::uint32_t height, RgbaImage& prepared);
bool NextPowerOfTwoTextureSize(std::uint32_t source, std::uint32_t limit,
                              std::uint32_t& target);
}
