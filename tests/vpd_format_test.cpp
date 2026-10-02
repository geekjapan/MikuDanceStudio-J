#include "mikudancestudio/vpd_format.hpp"

#include <cstdio>
#include <cstdlib>
#include <string>

namespace {

void Require(bool condition, const char* message) {
    if (!condition) {
        std::fputs(message, stderr);
        std::abort();
    }
}

std::string ReadAll(std::FILE* stream) {
    std::rewind(stream);
    std::string bytes;
    int ch;
    while ((ch = std::fgetc(stream)) != EOF)
        bytes.push_back(static_cast<char>(ch));
    return bytes;
}

}  // namespace

int main() {
    using namespace mikudancestudio::format;
    VpdDocument original;
    original.modelName = "Miku";
    VpdBone bone;
    bone.name = "center";
    bone.translation[0] = 1.25f;
    bone.translation[1] = -2.0f;
    original.bones.push_back(bone);

    std::FILE* stream = std::tmpfile();
    Require(stream != nullptr, "cannot create temporary stream\n");
    Require(WriteVpd(stream, original), "VPD writer failed\n");
    const std::string expected =
        "Vocaloid Pose Data file\n\n"
        "Miku.osm;\t\t// \x90\x65\x83\x74\x83\x40\x83\x43\x83\x8b\x96\xbc\n"
        "1;\t\t\t\t// \x91\x8d\x83\x7c\x81\x5b\x83\x59\x83\x7b\x81\x5b\x83\x93\x90\x94\n\n"
        "Bone0{center\n"
        "  1.250000,-2.000000,0.000000;\t\t\t\t// trans x,y,z\n"
        "  0.000000,0.000000,0.000000,1.000000;\t\t// Quaternion x,y,z,w\n"
        "}\n\n";
    Require(ReadAll(stream) == expected, "VPD bytes changed from legacy writer\n");

    std::rewind(stream);
    VpdDocument parsed;
    Require(ReadVpd(stream, parsed), "VPD reader rejected writer output\n");
    Require(parsed.modelName == "Miku" && parsed.bones.size() == 1 &&
            parsed.bones[0].name == "center" &&
            parsed.bones[0].translation[0] == 1.25f &&
            parsed.bones[0].rotation[3] == 1.0f,
            "VPD round trip changed pose data\n");
    std::fclose(stream);

    std::string windowsBytes;
    for (char ch : expected) {
        if (ch == '\n') windowsBytes.push_back('\r');
        windowsBytes.push_back(ch);
    }
    stream = std::tmpfile();
    Require(stream != nullptr, "cannot create temporary stream\n");
    Require(std::fwrite(windowsBytes.data(), 1, windowsBytes.size(), stream) ==
                windowsBytes.size(), "cannot write CRLF VPD\n");
    std::rewind(stream);
    Require(ReadVpd(stream, parsed) && parsed.bones.size() == 1 &&
            parsed.bones[0].name == "center",
            "VPD reader rejected Windows CRLF file\n");
    std::fclose(stream);

    stream = std::tmpfile();
    Require(stream != nullptr, "cannot create temporary stream\n");
    Require(std::fwrite(expected.data(), 1, expected.size() - 3, stream) ==
                expected.size() - 3, "cannot write truncated VPD\n");
    std::rewind(stream);
    Require(!ReadVpd(stream, parsed), "truncated VPD was accepted\n");
    Require(parsed.modelName == "Miku" && parsed.bones.size() == 1,
            "failed VPD read changed the destination\n");
    std::fclose(stream);
}
