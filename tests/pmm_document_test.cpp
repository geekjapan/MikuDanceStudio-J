#include "mikudancestudio/pmm_document.hpp"
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <vector>
namespace {
struct Input {
    std::vector<std::uint8_t> bytes;
    std::size_t offset = 0;
};
int Read(void* context, void* destination, std::size_t length) {
    auto& input = *static_cast<Input*>(context);
    const auto count = std::min(length, input.bytes.size() - input.offset);
    if (count) std::memcpy(destination, input.bytes.data() + input.offset, count);
    input.offset += count;
    return static_cast<int>(count);
}
int ReadChunked(void* context, void* destination, std::size_t length) {
    return Read(context, destination, std::min(length, std::size_t{3}));
}
bool Write(void* context, const void* source, std::size_t length) {
    auto& bytes = *static_cast<std::vector<std::uint8_t>*>(context);
    const auto* first = static_cast<const std::uint8_t*>(source);
    bytes.insert(bytes.end(), first, first + length);
    return true;
}
void Check(bool condition) { if (!condition) std::abort(); }
Input Fixture(const char* version, bool v1) {
    Input input;
    input.bytes.resize(30, 0);
    std::memcpy(input.bytes.data(), "Polygon Movie maker", 19);
    std::memcpy(input.bytes.data() + 20, version, 5);
    const auto word = [&input](std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8)
            input.bytes.push_back(static_cast<std::uint8_t>(value >> shift));
    };
    word(1280); word(720); word(200); word(0x42340000);
    for (int index = 0; index < (v1 ? 6 : 7); ++index)
        input.bytes.push_back(index == 2);
    input.bytes.push_back(1);
    input.bytes.push_back(1);
    if (v1) {
        input.bytes.resize(input.bytes.size() + 20, 0);
        input.bytes[input.bytes.size() - 20] = 'M';
    }
    input.bytes.insert(input.bytes.end(), {0x12, 0x34, 0x56});
    return input;
}
}
int main() {
    using namespace mikudancestudio::format;
    PmmDocument document;
    auto v1 = Fixture("0001", true);
    Check(ReadPmmDocument(Read, &v1, document));
    Check(v1.offset == v1.bytes.size() && document.header.version == PmmVersion::V1 &&
          document.settings.renderWidth == 1280 && document.modelCount == 1 &&
          document.v1ModelNames.size() == 1 && document.v1ModelNames[0][0] == 'M' &&
          document.remainingBytes == std::vector<std::uint8_t>({0x12, 0x34, 0x56}));
    std::vector<std::uint8_t> written;
    Check(WritePmmDocument(Write, &written, document) && written == v1.bytes);
    v1.offset = 0;
    Check(ReadPmmDocument(ReadChunked, &v1, document));
    Check(v1.offset == v1.bytes.size());
    written.clear();
    Check(WritePmmDocument(Write, &written, document) && written == v1.bytes);
    auto v2 = Fixture("0002", false);
    Check(ReadPmmDocument(Read, &v2, document));
    Check(v2.offset == v2.bytes.size() && document.header.version == PmmVersion::V2 &&
          document.v1ModelNames.empty() && document.settings.options[2] == 1);
    written.clear();
    Check(WritePmmDocument(Write, &written, document) && written == v2.bytes);
    auto truncated = Fixture("0001", true);
    truncated.bytes.resize(30 + 22 + 2 + 19);
    Check(!ReadPmmDocument(Read, &truncated, document));
    Check(document.header.version == PmmVersion::V2 &&
          document.remainingBytes.size() == 3);
    v2.bytes[24] = '9'; v2.offset = 0;
    Check(!ReadPmmDocument(Read, &v2, document));
    Check(!ReadPmmDocument(nullptr, &v2, document));
    Check(!WritePmmDocument(nullptr, &written, document));
}
