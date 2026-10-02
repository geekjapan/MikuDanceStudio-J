#include "mikudancestudio/vmd_format.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace {

void Require(bool ok, const char* message) {
    if (!ok) {
        std::fputs(message, stderr);
        std::abort();
    }
}

std::string Serialize(const mikudancestudio::format::VmdDocument& document) {
    std::FILE* file = std::tmpfile();
    Require(file != nullptr, "tmpfile failed\n");
    Require(mikudancestudio::format::WriteVmd(file, document), "VMD write failed\n");
    std::rewind(file);
    std::string bytes;
    int ch;
    while ((ch = std::fgetc(file)) != EOF) bytes.push_back(static_cast<char>(ch));
    std::fclose(file);
    return bytes;
}

bool Parse(const std::string& bytes, mikudancestudio::format::VmdDocument& document) {
    std::FILE* file = std::tmpfile();
    Require(file != nullptr, "tmpfile failed\n");
    Require(std::fwrite(bytes.data(), 1, bytes.size(), file) == bytes.size(),
            "tmpfile write failed\n");
    std::rewind(file);
    const bool ok = mikudancestudio::format::ReadVmd(file, document);
    std::fclose(file);
    return ok;
}

}  // namespace

int main() {
    using namespace mikudancestudio::format;
    VmdDocument original;
    std::memcpy(original.modelName.data(), "model", 5);
    VmdBoneKey bone;
    std::memcpy(bone.name.data(), "center", 6);
    bone.frame = 0x01020304;
    bone.position[0] = 1.25f;
    bone.rotation[3] = 1.0f;
    for (std::size_t i = 0; i < bone.interpolation.size(); ++i)
        bone.interpolation[i] = static_cast<std::uint8_t>(i);
    original.bones.push_back(bone);
    VmdMorphKey morph;
    std::memcpy(morph.name.data(), "smile", 5);
    morph.frame = 2;
    morph.value = 0.5f;
    original.morphs.push_back(morph);
    VmdCameraKey camera;
    camera.frame = 3;
    camera.distance = -20.0f;
    camera.eye[1] = 10.0f;
    camera.interpolation[5][3] = 77;
    camera.fov = 30;
    camera.perspective = 1;
    original.cameras.push_back(camera);
    VmdLightKey light;
    light.frame = 4;
    light.color[0] = 0.8f;
    original.lights.push_back(light);
    VmdShadowKey shadow;
    shadow.frame = 5;
    shadow.mode = 2;
    shadow.distance = 0.75f;
    original.shadows.push_back(shadow);
    VmdIkKey ik;
    ik.frame = 6;
    ik.visible = 1;
    VmdIkEntry entry;
    std::memcpy(entry.name.data(), "leg", 3);
    entry.enabled = 1;
    ik.entries.push_back(entry);
    original.ik.push_back(ik);

    const std::string bytes = Serialize(original);
    Require(bytes.size() == 336, "VMD2 section sizes changed\n");
    Require(static_cast<unsigned char>(bytes[69]) == 4 &&
            static_cast<unsigned char>(bytes[72]) == 1,
            "VMD frame is not little endian\n");
    VmdDocument parsed;
    Require(Parse(bytes, parsed), "VMD2 parse failed\n");
    Require(parsed.bones.size() == 1 && parsed.morphs.size() == 1 &&
            parsed.cameras.size() == 1 && parsed.lights.size() == 1 &&
            parsed.shadows.size() == 1 && parsed.ik.size() == 1 &&
            parsed.bones[0].interpolation[63] == 63 &&
            parsed.cameras[0].interpolation[5][3] == 77 &&
            parsed.ik[0].entries[0].enabled == 1,
            "VMD2 tracks changed on parse\n");
    Require(Serialize(parsed) == bytes, "VMD2 bytes changed on round trip\n");

    VmdDocument shortMotion;
    Require(Parse(bytes.substr(0, 192), shortMotion) &&
            shortMotion.bones.size() == 1 && shortMotion.morphs.size() == 1 &&
            shortMotion.cameras.empty() && !shortMotion.hasCameraSection,
            "bone/morph VMD without later track counts was rejected\n");

    VmdDocument old;
    old.version = VmdVersion::V1;
    old.cameras.push_back(camera);
    old.cameras[0].interpolation[0][0] = 10;
    old.cameras[0].interpolation[0][1] = 20;
    old.cameras[0].interpolation[0][2] = 30;
    old.cameras[0].interpolation[0][3] = 40;
    const std::string oldBytes = Serialize(old);
    Require(oldBytes.size() == 92, "VMD1 compact camera size changed\n");
    Require(Parse(oldBytes, parsed) && parsed.version == VmdVersion::V1 &&
            parsed.cameras.size() == 1 &&
            parsed.cameras[0].interpolation[5][2] == 30 &&
            parsed.cameras[0].fov == 45,
            "VMD1 shared camera interpolation was not expanded\n");

    VmdDocument unchanged = parsed;
    Require(!Parse(bytes.substr(0, bytes.size() - 1), parsed),
            "truncated VMD2 IK entry accepted\n");
    Require(parsed.version == unchanged.version &&
            parsed.cameras.size() == unchanged.cameras.size(),
            "failed VMD read changed destination\n");
}
