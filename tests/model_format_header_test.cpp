#include "mikudancestudio/model_format_header.hpp"
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <vector>
namespace {
void Check(bool condition) { if (!condition) std::abort(); }
struct Input { std::vector<std::uint8_t> data; std::size_t offset = 0; };
bool Read(void* context, void* output, std::size_t size) {
    auto& input = *static_cast<Input*>(context);
    if (size > input.data.size() - input.offset) return false;
    if (size) std::memcpy(output, input.data.data() + input.offset, size);
    input.offset += size;
    return true;
}
void Append32(Input& input, std::uint32_t value) {
    for (int shift = 0; shift < 32; shift += 8)
        input.data.push_back(static_cast<std::uint8_t>(value >> shift));
}
}
int main() {
    using namespace mikudancestudio::format;
    Check(IdentifyModel({'P','m','d'}) == ModelKind::Pmd);
    Check(IdentifyModel({'P','M','X'}) == ModelKind::Pmx);
    Check(IdentifyModel({'P','m','x'}) == ModelKind::Unknown);
    Input pmd;
    Append32(pmd, 0x3f800000);
    pmd.data.resize(4 + 20 + 256);
    pmd.data[4] = 'M';
    PmdHeader pmdHeader;
    Check(ReadPmdHeader(Read, &pmd, pmdHeader) == ModelHeaderStatus::Ok);
    Check(pmdHeader.version == 1.0f && pmdHeader.name[0] == 'M');
    pmd.data.pop_back(); pmd.offset = 0;
    Check(ReadPmdHeader(Read, &pmd, pmdHeader) == ModelHeaderStatus::Truncated);
    Check(pmdHeader.name[0] == 'M');
    Input pmx;
    pmx.data.push_back(0);
    Append32(pmx, 0x40000000);
    const std::uint8_t settings[9]{8,0,1,2,1,1,2,1,1};
    pmx.data.insert(pmx.data.end(), settings, settings + 9);
    PmxHeader pmxHeader;
    Check(ReadPmxHeader(Read, &pmx, pmxHeader) == ModelHeaderStatus::Ok);
    Check(pmxHeader.version == 2.0f && pmxHeader.vertexIndexSize == 2 &&
          pmxHeader.additionalUvCount == 1);
    pmx.data[6] = 1; pmx.offset = 0;
    Check(ReadPmxHeader(Read, &pmx, pmxHeader) == ModelHeaderStatus::UnsupportedEncoding);
    pmx.data[6] = 0; pmx.data[5] = 7; pmx.offset = 0;
    Check(ReadPmxHeader(Read, &pmx, pmxHeader) == ModelHeaderStatus::InvalidSettings);
    pmx.data[5] = 8;
    pmx.data[6] = 0; pmx.data[4] = 0; pmx.offset = 0;
    Check(ReadPmxHeader(Read, &pmx, pmxHeader) == ModelHeaderStatus::InvalidVersion);
    pmx.data.pop_back(); pmx.offset = 0;
    pmx.data[4] = 0x40;
    Check(ReadPmxHeader(Read, &pmx, pmxHeader) == ModelHeaderStatus::Truncated);
    Input texts;
    Append32(texts, 4);
    texts.data.insert(texts.data.end(), {0x42,0,0x43,0});
    for (int index = 1; index < 4; ++index) Append32(texts, 0);
    PmxTexts fields;
    Check(ReadPmxTexts(Read, &texts, fields) == ModelHeaderStatus::Ok);
    Check(fields.fields[0].size() == 4 && fields.fields[0][0] == 0x42);
    texts.data.pop_back(); texts.offset = 0;
    Check(ReadPmxTexts(Read, &texts, fields) == ModelHeaderStatus::Truncated);
    Check(fields.fields[0].size() == 4);
    texts.data[0] = 3; texts.offset = 0;
    Check(ReadPmxTexts(Read, &texts, fields) == ModelHeaderStatus::InvalidSettings);
    texts.data[0] = 0xff; texts.data[1] = 0xff;
    texts.data[2] = 0x7f; texts.data[3] = 0; texts.offset = 0;
    Check(ReadPmxTexts(Read, &texts, fields) == ModelHeaderStatus::InvalidSettings);
    Input name;
    Append32(name, 4);
    name.data.insert(name.data.end(), {0x42, 0, 0x43, 0});
    std::vector<std::uint8_t> nameBytes;
    Check(ReadPmxText(Read, &name, nameBytes) == ModelHeaderStatus::Ok);
    Check(nameBytes.size() == 4 && nameBytes[2] == 0x43);
    name.offset = 0;
    Check(SkipPmxText(Read, &name) == ModelHeaderStatus::Ok);
    Check(name.offset == name.data.size());
    name.data.pop_back(); name.offset = 0;
    Check(ReadPmxText(Read, &name, nameBytes) == ModelHeaderStatus::Truncated);
    Check(nameBytes.size() == 4);
    name.data[0] = 3; name.offset = 0;
    Check(ReadPmxText(Read, &name, nameBytes) == ModelHeaderStatus::InvalidSettings);
    name.data.clear(); Append32(name, 0); name.offset = 0;
    Check(ReadPmxText(Read, &name, nameBytes) == ModelHeaderStatus::Ok);
    Check(nameBytes.empty() && name.offset == name.data.size());
}
