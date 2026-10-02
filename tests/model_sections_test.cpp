#include "mikudancestudio/model_sections.hpp"
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <vector>
using namespace mikudancestudio::format;
namespace {
void Check(bool condition) { if (!condition) std::abort(); }
struct Buffer {
    std::vector<std::uint8_t> data;
    std::size_t offset = 0;
    template<class T> void add(T value) {
        std::uint8_t bytes[sizeof value];
        std::memcpy(bytes, &value, sizeof value);
        data.insert(data.end(), bytes, bytes + sizeof bytes);
    }
    void zeros(std::size_t count) { data.insert(data.end(), count, 0); }
    static bool read(void* context, void* destination, std::size_t count) {
        auto& buffer = *static_cast<Buffer*>(context);
        if (count > buffer.data.size() - buffer.offset) return false;
        std::memcpy(destination, buffer.data.data() + buffer.offset, count);
        buffer.offset += count;
        return true;
    }
    static int readResult(void* context, void* destination, std::size_t count) {
        auto& buffer = *static_cast<Buffer*>(context);
        const std::size_t available = buffer.data.size() - buffer.offset;
        const std::size_t actual = count < available ? count : available;
        if (actual) std::memcpy(destination, buffer.data.data() + buffer.offset, actual);
        buffer.offset += actual;
        return static_cast<int>(actual);
    }
};
}
int main() {
    Buffer pmd;
    for (int index = 0; index < 4; ++index) pmd.add(float(index + 1));
    pmd.add(5.0f);
    for (int index = 0; index < 6; ++index) pmd.add(float(index));
    pmd.add(std::uint8_t(7)); pmd.add(std::uint8_t(1));
    pmd.add(std::int32_t(42)); pmd.zeros(20);
    MaterialData material;
    assert(ReadPmdMaterial(Buffer::read, &pmd, material));
    assert(material.diffuse[3] == 4 && material.specularPower == 5);
    assert(material.toonReference == 7 && material.flags == 1);
    assert(material.faceVertexCount == 42 && pmd.offset == pmd.data.size());
    pmd.offset = 0; pmd.data.pop_back();
    material.faceVertexCount = -99;
    assert(!ReadPmdMaterial(Buffer::read, &pmd, material));
    assert(material.faceVertexCount == -99);
    Buffer pmx;
    for (int index = 0; index < 4 + 3; ++index) pmx.add(0.0f);
    pmx.add(2.0f);
    for (int index = 0; index < 3; ++index) pmx.add(0.0f);
    pmx.add(std::uint8_t(0x10));
    for (int index = 0; index < 4; ++index) pmx.add(0.0f);
    pmx.add(0.5f);
    pmx.add(std::int16_t(-1)); pmx.add(std::int16_t(258));
    pmx.add(std::uint8_t(2)); pmx.add(std::uint8_t(0));
    pmx.add(std::int16_t(3)); pmx.add(std::int32_t(4));
    pmx.zeros(4); pmx.add(std::int32_t(12));
    assert(ReadPmxMaterial(Buffer::read, &pmx, 2, material));
    assert(material.textureIndex == -1 && material.sphereIndex == 258);
    assert(material.toonIndex == 3 && material.toonReference == 0xFE);
    assert(material.faceVertexCount == 12 && pmx.offset == pmx.data.size());
    pmx.offset = 0; pmx.data.pop_back();
    material.faceVertexCount = -99;
    assert(!ReadPmxMaterial(Buffer::read, &pmx, 2, material));
    assert(material.faceVertexCount == -99);

    Buffer boneBytes;
    boneBytes.zeros(20);
    boneBytes.add(std::int16_t(-1)); boneBytes.add(std::int16_t(2));
    boneBytes.add(std::uint8_t(3)); boneBytes.add(std::int16_t(4));
    for (int index = 0; index < 3; ++index) boneBytes.add(float(index));
    BoneData bone;
    assert(ReadPmdBone(Buffer::read, &boneBytes, bone));
    assert(bone.parent == -1 && bone.tailBone == 2 && bone.tailIdx == 4);
    Buffer ikBytes;
    ikBytes.add(std::uint16_t(1)); ikBytes.add(std::uint16_t(2));
    ikBytes.add(std::uint8_t(2)); ikBytes.add(std::uint16_t(16));
    ikBytes.add(0.5f); ikBytes.add(std::uint16_t(3)); ikBytes.add(std::uint16_t(4));
    PmdIkData ik;
    assert(ReadPmdIk(Buffer::read, &ikBytes, ik));
    assert(ik.links.size() == 2 && ik.links[1] == 4 && ik.iterations == 16);
    Buffer pmxBone;
    for (int index = 0; index < 3; ++index) pmxBone.add(float(index + 1));
    pmxBone.add(std::int8_t(-1)); pmxBone.add(std::int32_t(7));
    pmxBone.add(std::uint16_t(0x2D21));
    pmxBone.add(std::int8_t(2)); pmxBone.add(std::int8_t(-2));
    pmxBone.add(0.25f);
    for (int index = 0; index < 9; ++index) pmxBone.add(float(index));
    pmxBone.add(std::int32_t(33));
    pmxBone.add(std::int8_t(5)); pmxBone.add(std::int32_t(10));
    pmxBone.add(0.7f); pmxBone.add(std::int32_t(1));
    pmxBone.add(std::int8_t(6)); pmxBone.add(std::uint8_t(1));
    for (int index = 0; index < 6; ++index) pmxBone.add(float(index + 10));
    assert(ReadPmxBone(Buffer::read, &pmxBone, 1, bone));
    assert(bone.parent == -1 && bone.tailBone == 2 && bone.tailIdx == -2);
    assert(bone.localAxes[5] == 8 && bone.extParent == 33);
    assert(bone.ikTarget == 5 && bone.ikLinks.size() == 1);
    assert(bone.ikLinks[0].maximum[2] == 15 && pmxBone.offset == pmxBone.data.size());
    pmxBone.offset = 0; pmxBone.data.pop_back();
    bone.layer = -99;
    assert(!ReadPmxBone(Buffer::read, &pmxBone, 1, bone));
    assert(bone.layer == -99);
    Buffer rigidBytes;
    rigidBytes.zeros(20); rigidBytes.add(std::int16_t(-1));
    rigidBytes.add(std::uint8_t(3)); rigidBytes.add(std::uint16_t(0x1234));
    rigidBytes.add(std::uint8_t(2));
    for (int index = 0; index < 9 + 5; ++index) rigidBytes.add(float(index + 1));
    rigidBytes.add(std::uint8_t(2));
    RigidData rigid;
    assert(ReadPmdRigid(Buffer::read, &rigidBytes, rigid));
    assert(rigid.boneIndex == -1 && rigid.noCollapse == 0x1234);
    assert(rigid.size[0] == 1 && rigid.friction == 14 && rigid.mode == 2);
    Buffer pmxRigid;
    pmxRigid.add(std::int8_t(-1)); pmxRigid.add(std::uint8_t(3));
    pmxRigid.add(std::uint16_t(0x1234)); pmxRigid.add(std::uint8_t(2));
    for (int index = 0; index < 14; ++index) pmxRigid.add(float(index + 1));
    pmxRigid.add(std::uint8_t(2));
    assert(ReadPmxRigid(Buffer::read, &pmxRigid, 1, rigid));
    assert(rigid.boneIndex == -1 && rigid.friction == 14);
    Buffer jointBytes;
    jointBytes.zeros(20);
    jointBytes.add(std::int32_t(1)); jointBytes.add(std::int32_t(2));
    for (int index = 0; index < 6 + 12 + 6; ++index)
        jointBytes.add(float(index + 1));
    JointData joint;
    assert(ReadPmdJoint(Buffer::read, &jointBytes, joint));
    assert(joint.rigidA == 1 && joint.rigidB == 2);
    assert(joint.limits[3] == 7 && joint.limits[0] == 10);
    assert(joint.limits[9] == 13 && joint.limits[6] == 16);
    Buffer pmxJoint;
    pmxJoint.add(std::uint8_t(0));
    pmxJoint.add(std::int16_t(-1)); pmxJoint.add(std::int16_t(257));
    for (int index = 0; index < 24; ++index) pmxJoint.add(float(index + 1));
    assert(ReadPmxJoint(Buffer::read, &pmxJoint, 2, joint));
    assert(joint.rigidA == -1 && joint.rigidB == 257);
    assert(joint.limits[3] == 7 && joint.springs[5] == 24);
    Buffer pmdMorph;
    pmdMorph.zeros(20); pmdMorph.add(std::int32_t(1));
    pmdMorph.add(std::uint8_t(2)); pmdMorph.add(std::uint32_t(257));
    pmdMorph.add(1.0f); pmdMorph.add(2.0f); pmdMorph.add(3.0f);
    PmdMorphHeaderData pmdHeader;
    PmdMorphOffsetData pmdOffset;
    assert(ReadPmdMorphHeader(Buffer::read, &pmdMorph, pmdHeader));
    assert(pmdHeader.offsetCount == 1 && pmdHeader.panel == 2);
    assert(ReadPmdMorphOffset(Buffer::read, &pmdMorph, pmdOffset));
    assert(pmdOffset.vertexIndex == 257 && pmdOffset.offset[2] == 3);
    pmdMorph.offset = 0; pmdMorph.data.pop_back();
    assert(ReadPmdMorphHeader(Buffer::read, &pmdMorph, pmdHeader));
    pmdOffset.vertexIndex = 999;
    assert(!ReadPmdMorphOffset(Buffer::read, &pmdMorph, pmdOffset));
    assert(pmdOffset.vertexIndex == 999);
    Buffer pmdDisplay;
    pmdDisplay.add(std::uint16_t(5)); pmdDisplay.zeros(50);
    pmdDisplay.add(std::uint16_t(7)); pmdDisplay.add(std::uint8_t(3));
    std::uint16_t target = 0; std::uint8_t group = 0;
    char groupName[50]{};
    assert(ReadPmdDisplayTarget(Buffer::read, &pmdDisplay, target));
    assert(ReadPmdGroupName(Buffer::read, &pmdDisplay, groupName));
    assert(ReadPmdBoneFrame(Buffer::read, &pmdDisplay, target, group));
    assert(target == 7 && group == 3 && pmdDisplay.offset == pmdDisplay.data.size());
    Buffer pmxMorphHeader;
    pmxMorphHeader.add(std::uint8_t(4)); pmxMorphHeader.add(std::uint8_t(8));
    pmxMorphHeader.add(std::int32_t(2));
    PmxMorphHeaderData morphHeader;
    assert(ReadPmxMorphHeader(Buffer::read, &pmxMorphHeader, morphHeader));
    assert(morphHeader.panel == 4 && morphHeader.type == 8 &&
           morphHeader.offsetCount == 2);
    const PmxMorphIndexSizes sizes{1, 1, 1, 1};
    for (std::uint8_t type = 0; type <= 8; ++type) {
        Buffer offsetBytes;
        offsetBytes.add(std::uint8_t(0xFF));
        if (type == 8) offsetBytes.add(std::uint8_t(1));
        const int count = type == 0 ? 1 : type == 1 ? 3 :
            type == 2 ? 7 : type == 8 ? 28 : 4;
        for (int index = 0; index < count; ++index)
            offsetBytes.add(float(index + 1));
        PmxMorphOffsetData offset;
        assert(ReadPmxMorphOffset(Buffer::read, &offsetBytes, type, sizes, offset));
        assert(offset.index == ((type == 1 || (type >= 3 && type <= 7)) ? 255 : -1));
        assert(offset.values[count - 1] == count);
        assert(offset.operation == (type == 8 ? 1 : 0));
        assert(offsetBytes.offset == offsetBytes.data.size());
        offsetBytes.offset = 0; offsetBytes.data.pop_back();
        offset.index = 999;
        assert(!ReadPmxMorphOffset(Buffer::read, &offsetBytes, type, sizes, offset));
        assert(offset.index == 999);
    }
    Buffer pmxDisplay;
    pmxDisplay.add(std::uint8_t(1)); pmxDisplay.add(std::int32_t(2));
    pmxDisplay.add(std::uint8_t(0)); pmxDisplay.add(std::int16_t(-1));
    pmxDisplay.add(std::uint8_t(1)); pmxDisplay.add(std::int32_t(257));
    std::uint8_t special = 0; std::int32_t entries = 0;
    PmxDisplayEntryData displayEntry;
    assert(ReadPmxDisplayHeader(Buffer::read, &pmxDisplay, special, entries));
    assert(special == 1 && entries == 2);
    assert(ReadPmxDisplayEntry(Buffer::read, &pmxDisplay, 2, 4, displayEntry));
    assert(displayEntry.type == 0 && displayEntry.index == -1);
    assert(ReadPmxDisplayEntry(Buffer::read, &pmxDisplay, 2, 4, displayEntry));
    assert(displayEntry.type == 1 && displayEntry.index == 257);
    assert(pmxDisplay.offset == pmxDisplay.data.size());
    pmxDisplay.offset = 0; pmxDisplay.data.pop_back();
    assert(ReadPmxDisplayHeader(Buffer::read, &pmxDisplay, special, entries));
    assert(ReadPmxDisplayEntry(Buffer::read, &pmxDisplay, 2, 4, displayEntry));
    displayEntry.index = 999;
    assert(!ReadPmxDisplayEntry(Buffer::read, &pmxDisplay, 2, 4, displayEntry));
    assert(displayEntry.index == 999);
    Buffer counts;
    counts.add(std::uint8_t(255));
    counts.add(std::uint16_t(0x1234));
    counts.add(std::uint32_t(0x87654321));
    std::uint32_t count = 0;
    Check(ReadModelSectionCount(Buffer::read, &counts, 1, count) && count == 255);
    Check(ReadModelSectionCount(Buffer::read, &counts, 2, count) && count == 0x1234);
    Check(ReadModelSectionCount(Buffer::read, &counts, 4, count) && count == 0x87654321);
    Check(counts.offset == counts.data.size());
    counts.offset = 0; count = 42;
    Check(!ReadModelSectionCount(Buffer::read, &counts, 3, count));
    Check(count == 42 && counts.offset == 0);
    counts.data.pop_back(); counts.offset = 3;
    Check(!ReadModelSectionCount(Buffer::read, &counts, 4, count));
    Check(count == 42);
    Buffer english;
    for (int index = 0; index < 20; ++index)
        english.add(static_cast<std::uint8_t>(index + 1));
    for (int index = 0; index < 256; ++index)
        english.add(static_cast<std::uint8_t>(index));
    english.zeros(20);
    english.zeros(50);
    english.zeros(100);
    PmdEnglishModelData modelEnglish;
    Check(ReadPmdEnglishModel(Buffer::read, &english, modelEnglish));
    Check(modelEnglish.name[0] == 1 && modelEnglish.name[19] == 20);
    Check(static_cast<std::uint8_t>(modelEnglish.comment[255]) == 255);
    char boneName[20]{};
    char displayName[50]{};
    char toonName[100]{};
    Check(ReadPmdEnglishName(Buffer::read, &english, boneName));
    Check(ReadPmdEnglishGroupName(Buffer::read, &english, displayName));
    Check(ReadPmdToonName(Buffer::read, &english, toonName));
    Check(english.offset == english.data.size());
    english.offset = 0; english.data.pop_back();
    toonName[0] = 'x';
    english.offset = 20 + 256 + 20 + 50;
    Check(!ReadPmdToonName(Buffer::read, &english, toonName));
    Check(toonName[0] == 'x');
    english.offset = 0; english.data.resize(20 + 255);
    modelEnglish.name[0] = 'x';
    Check(!ReadPmdEnglishModel(Buffer::read, &english, modelEnglish));
    Check(modelEnglish.name[0] == 'x');
    Buffer optional;
    optional.add(std::uint8_t(1));
    PmdEnglishPresence presence;
    Check(ReadPmdEnglishPresence(Buffer::readResult, &optional, presence));
    Check(presence.hasEnglish && presence.hasToonFields);
    Check(ReadPmdEnglishPresence(Buffer::readResult, &optional, presence));
    Check(!presence.hasEnglish && !presence.hasToonFields);
    optional.offset = 0; optional.data[0] = 0;
    Check(ReadPmdEnglishPresence(Buffer::readResult, &optional, presence));
    Check(!presence.hasEnglish && presence.hasToonFields);
    auto readError = [](void*, void*, std::size_t) -> int { return -1; };
    Check(ReadPmdEnglishPresence(readError, nullptr, presence));
    Check(!presence.hasEnglish && presence.hasToonFields);
    optional.data.clear(); optional.offset = 0;
    std::uint32_t optionalCount = 99;
    Check(ReadPmdOptionalCount(Buffer::readResult, &optional, optionalCount) ==
          PmdOptionalRead::EndOfFile && optionalCount == 0);
    optional.add(std::uint32_t(0x12345678));
    Check(ReadPmdOptionalCount(Buffer::readResult, &optional, optionalCount) ==
          PmdOptionalRead::Value && optionalCount == 0x12345678);
    optional.offset = 0;
    optional.data.pop_back();
    optionalCount = 99;
    Check(ReadPmdOptionalCount(Buffer::readResult, &optional, optionalCount) ==
          PmdOptionalRead::Truncated && optionalCount == 99);
    Check(ReadPmdOptionalCount(readError, nullptr, optionalCount) ==
          PmdOptionalRead::ReadError && optionalCount == 99);
}
