#include "mikudancestudio/model_geometry.hpp"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>

using namespace mikudancestudio::format;

namespace {
struct Input {
    std::vector<std::uint8_t> bytes;
    std::size_t offset = 0;
};
bool Read(void* context, void* destination, std::size_t size) {
    auto& input = *static_cast<Input*>(context);
    if (size > input.bytes.size() - input.offset) return false;
    std::memcpy(destination, input.bytes.data() + input.offset, size);
    input.offset += size;
    return true;
}
void PutUnsigned(Input& input, std::uint32_t value, int width) {
    for (int index = 0; index < width; ++index)
        input.bytes.push_back(static_cast<std::uint8_t>(value >> (8 * index)));
}
void PutFloat(Input& input, float value) {
    std::uint32_t bits;
    std::memcpy(&bits, &value, sizeof bits);
    PutUnsigned(input, bits, 4);
}
void TestPmd() {
    Input input;
    PutUnsigned(input, 1, 4);
    for (int component = 0; component < 8; ++component)
        PutFloat(input, static_cast<float>(component));
    PutUnsigned(input, 0xFEDC, 2);
    PutUnsigned(input, 7, 2);
    input.bytes.push_back(80);
    input.bytes.push_back(1);
    PutUnsigned(input, 0xFEDC, 2);
    std::uint32_t count = 0;
    PmdVertexData vertex;
    std::uint16_t index = 0;
    assert(ReadGeometryCount(Read, &input, count) && count == 1);
    assert(ReadPmdVertex(Read, &input, vertex));
    assert(vertex.position[2] == 2 && vertex.normal[0] == 3);
    assert(vertex.uv[1] == 7 && vertex.bone[0] == 0xFEDC);
    assert(vertex.bone[1] == 7 && vertex.weightPercent == 80 && vertex.edgeDisabled == 1);
    assert(ReadPmdIndex(Read, &input, index) && index == 0xFEDC);
    assert(!ReadPmdIndex(Read, &input, index) && index == 0xFEDC);
}
void TestPmxWeights() {
    for (std::uint8_t weightType = 0; weightType <= 4; ++weightType) {
        Input input;
        for (int component = 0; component < 8; ++component)
            PutFloat(input, static_cast<float>(component));
        for (int uv = 0; uv < 2; ++uv)
            for (int component = 0; component < 4; ++component)
                PutFloat(input, static_cast<float>(uv * 4 + component));
        input.bytes.push_back(weightType);
        int bones = weightType == 0 ? 1 :
                    (weightType == 1 || weightType == 3 ? 2 :
                     weightType == 2 ? 4 : 0);
        for (int index = 0; index < bones; ++index)
            PutUnsigned(input, index == 0 ? 0xFFFF : index, 2);
        int weights = weightType == 1 || weightType == 3 ? 1 :
                      weightType == 2 ? 4 : 0;
        for (int index = 0; index < weights; ++index)
            PutFloat(input, 0.25f * (index + 1));
        if (weightType == 3)
            for (int index = 0; index < 9; ++index)
                PutFloat(input, static_cast<float>(index));
        PutFloat(input, 0.75f);
        PmxVertexData vertex;
        assert(ReadPmxVertex(Read, &input, 2, 2, vertex));
        assert(input.offset == input.bytes.size());
        assert(vertex.position[2] == 2 && vertex.uv[1] == 7);
        assert(vertex.additionalUv[3][1] == 7.0f);
        assert(vertex.weightType == weightType && vertex.edgeScale == 0.75f);
        if (bones) assert(vertex.bone[0] == -1);
        if (weights) assert(vertex.weight[0] == 0.25f);
        if (weightType == 3)
            assert(vertex.center[0] == 0 && vertex.r0[0] == 3 && vertex.r1[2] == 8);
    }
}
void TestWidthsAndTruncation() {
    for (int width : {1, 2, 4}) {
        Input input;
        PutUnsigned(input, width == 1 ? 0xFF : width == 2 ? 0xFFFF : 0xFFFFFFFF, width);
        std::int32_t index = 0;
        assert(ReadPmxVertexIndex(Read, &input, width, index));
        assert(index == (width == 1 ? 255 : width == 2 ? 65535 : -1));
        input.offset = 0;
        assert(!ReadPmxVertexIndex(Read, &input, 3, index) && input.offset == 0);
        input.bytes.pop_back();
        assert(!ReadPmxVertexIndex(Read, &input, width, index));
    }
    Input input;
    input.bytes.resize(32, 0);
    PmxVertexData vertex;
    vertex.edgeScale = 9.0f;
    assert(!ReadPmxVertex(Read, &input, 0, 1, vertex));
    assert(vertex.edgeScale == 9.0f);
    input.offset = 0;
    assert(!ReadPmxVertex(Read, &input, 5, 1, vertex) && input.offset == 0);
    assert(!ReadPmxVertex(Read, &input, 0, 3, vertex) && input.offset == 0);
    for (int width : {1, 4}) {
        Input signedInput;
        signedInput.bytes.resize(32, 0);
        signedInput.bytes.push_back(0);
        PutUnsigned(signedInput, width == 1 ? 0xFF : 0xFFFFFFFF, width);
        PutFloat(signedInput, 1.0f);
        assert(ReadPmxVertex(Read, &signedInput, 0, width, vertex));
        assert(vertex.bone[0] == -1 && signedInput.offset == signedInput.bytes.size());
    }
}
}  // namespace

int main() {
    TestPmd();
    TestPmxWeights();
    TestWidthsAndTruncation();
}
