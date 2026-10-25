// Oracle for rust/crates/mds-skin: loads each model with the real PMD/PMX
// loaders, then for each case of the case file sets the morph weights, the
// bone skinning matrices (BoneRecord::matInit) and the camera, runs the real
// ModelApplyMorphs and UpdateModelVertexBuffers, and prints the vertex
// buffers, the composed material values and the bone morph work records.
//
// Usage: skin_check <fixture dir> <case file>   (dump on stdout)
//
// Case file (written by tests/fixtures/rust/skin/gen_skin.py), one item per
// line, floats as the 8 hex digits of their bits:
//   model <file>              load <fixture dir>/<file>
//   qdef <vertex>...          set those PMX vertices to weight type 4
//   case <name>               start a case: weights 0, matrices identity
//   world <16 floats>         the frame world matrix
//   camera <x> <y> <z> <fov>
//   edge <scale>              ModelRecord::edgeScale
//   shadow <0|1>              self-shadow on (opaque PMX edge alpha)
//   morph <index> <weight>
//   bone <index> <16 floats>
//   end                       run the case and print it
// Dump: "model <file> <pmx|pmd> vertices <n> stride <bytes>", then per case
// "case <name>", one "v <i> <main record words> <edge record words>" per
// vertex, one "m <i> <16 words>" per material (diffuseMirror rgb, diffuse a,
// specular, ambient, specularPower, edgeColor, edgeSize) and one
// "b <i> <bone> <translation> <rotation>" per bone morph work record.
#include <Windows.h>
#include <d3d9.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "mikudancestudio/d3d_wrapper.hpp"
#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"
#include "mikudancestudio/path_workspace.hpp"
#include "mikudancestudio/ported_funcs.hpp"

namespace mikudancestudio {
void ModelInitDefaults(unsigned char* m);

void InitBoneSortOrder(unsigned char*) {}
void PostLoadInit(unsigned char*) {}
void SetPhysicsMode(unsigned char*, int, unsigned char* const*, int) {}
void CreateRigidBody(PhysicsScene*, void** out, int, float, float, float, const float*, int,
                     float, float, float, float, float, char, std::uint16_t) {
    out[0] = out[1] = nullptr;
}
int CreatePhysJoint(PhysicsScene*, void*, void*, float, float, float, float, float, float, float,
                    float, float, float, float, float, float, float, float, float, float, float,
                    float, float, float, float, float, float, float, float, float, float, float,
                    float, float, float) {
    return 0;
}
void TransformJointPointOriginal(float out[3], const float*, const float*) {
    out[0] = out[1] = out[2] = 0.0f;
}
float JointRadiusBound(const float*, float, float) { return 0.0f; }
const wchar_t* ResolveUserFilePath(PathResolutionWorkspace& paths, const wchar_t* path) {
    wcscpy_s(paths.resolvedPath, 256, path);
    return paths.resolvedPath;
}
errno_t ConvertMaterialName(unsigned char*, const char*, wchar_t* out, rsize_t, const wchar_t*) {
    out[0] = 0;
    return 0;
}
int LoadTextureShared(unsigned char*, wchar_t*) { return 0; }
void ConvertAnsiToWide(const D3DRenderer*, const char*, wchar_t* out, int) { out[0] = 0; }
void WideToSjis(const D3DRenderer*, char*, const wchar_t*, std::size_t) {}
} // namespace mikudancestudio

namespace {
using namespace mikudancestudio;

[[noreturn]] void Fail(const std::string& what) {
    std::fprintf(stderr, "skin_check: %s\n", what.c_str());
    std::exit(1);
}

std::uint32_t Bits(float value) {
    std::uint32_t bits;
    std::memcpy(&bits, &value, 4);
    return bits;
}

struct Tokens {
    std::vector<std::string> items;
    std::size_t next = 1;
    const std::string& Word() {
        if (next >= items.size())
            Fail("short line: " + items[0]);
        return items[next++];
    }
    long Int() { return std::strtol(Word().c_str(), nullptr, 10); }
    float Float() {
        const std::uint32_t bits = std::strtoul(Word().c_str(), nullptr, 16);
        float value;
        std::memcpy(&value, &bits, 4);
        return value;
    }
    void Floats(float* out, int count) {
        for (int i = 0; i < count; ++i)
            out[i] = Float();
    }
};

constexpr float kIdentity[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};

struct Model {
    std::string file;
    unsigned char* record = nullptr;
    bool pmx = false;
    std::uint32_t stride = 0;
};

Model Load(const std::string& dir, const std::string& file) {
    Model model;
    model.file = file;
    model.record = static_cast<unsigned char*>(operator new(mdl::kSize));
    std::memset(model.record, 0, mdl::kSize);
    ModelInitDefaults(model.record);
    static IDirect3DDevice9 device;
    static D3DRenderer renderer{&device};
    static PathResolutionWorkspace paths;
    const std::string path = dir + "/" + file;
    std::vector<wchar_t> wide(path.begin(), path.end());
    wide.push_back(0);
    if (!ModelLoadPMD(model.record, nullptr, wide.data(), &renderer, 0, 0, 0, nullptr, paths))
        Fail("cannot load " + path);
    const mdl::ModelRecord& state = *mdl::Mdl(model.record);
    model.pmx = state.physicsMode == 2;
    model.stride = model.pmx ? 32 + 16 * state.pmxAdditionalUvCount : 32;
    std::printf("model %s %s vertices %u stride %u\n", file.c_str(), model.pmx ? "pmx" : "pmd",
                state.vertexCount, model.stride);
    return model;
}

void Print(const Model& model) {
    unsigned char* m = model.record;
    const mdl::ModelRecord& state = *mdl::Mdl(m);
    const auto& main = mdl::ResourceAs<IDirect3DVertexBuffer9>(mdl::Mdl(m)->vertexBuffer)->data;
    const auto& edge = mdl::ResourceAs<IDirect3DVertexBuffer9>(mdl::Mdl(m)->vertexBuffer2)->data;
    for (std::uint32_t i = 0; i < state.vertexCount; ++i) {
        std::printf("v %u", i);
        for (std::uint32_t w = 0; w < model.stride / 4; ++w) {
            std::uint32_t word;
            std::memcpy(&word, &main[model.stride * i + 4 * w], 4);
            std::printf(" %08x", word);
        }
        for (int w = 0; w < 4; ++w) {
            std::uint32_t word;
            std::memcpy(&word, &edge[16 * i + 4 * w], 4);
            std::printf(" %08x", word);
        }
        std::printf("\n");
    }
    for (std::uint32_t i = 0; i < state.materialCount; ++i) {
        const mdl::ModelMaterialRecord& mat = state.materials[i];
        const float values[16] = {mat.diffuseMirror[0], mat.diffuseMirror[1], mat.diffuseMirror[2],
                                  mat.diffuse[3],       mat.specular[0],      mat.specular[1],
                                  mat.specular[2],      mat.ambient[0],       mat.ambient[1],
                                  mat.ambient[2],       mat.specularPower,    mat.edgeColor[0],
                                  mat.edgeColor[1],     mat.edgeColor[2],     mat.edgeColor[3],
                                  mat.edgeSize};
        std::printf("m %u", i);
        for (float value : values)
            std::printf(" %08x", Bits(value));
        std::printf("\n");
    }
    const mdl::BoneMorphOffsetRecord* work = mdl::BoneMorphOffsets(m);
    for (int i = 0; i < mdl::BoneMorphOffsetCount(m); ++i) {
        const mdl::BoneMorphOffsetRecord& rec = work[i];
        std::printf("b %d %d %08x %08x %08x %08x %08x %08x %08x\n", i, rec.boneIndex,
                    Bits(rec.translation[0]), Bits(rec.translation[1]), Bits(rec.translation[2]),
                    Bits(rec.rotation[0]), Bits(rec.rotation[1]), Bits(rec.rotation[2]),
                    Bits(rec.rotation[3]));
    }
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 3)
        Fail("usage: skin_check <fixture dir> <case file>");
    FILE* in = std::fopen(argv[2], "r");
    if (in == nullptr)
        Fail(std::string("cannot open ") + argv[2]);
    Model model;
    MMDApp app{};
    float world[16];
    char line[4096];
    while (std::fgets(line, sizeof line, in) != nullptr) {
        Tokens t;
        for (char* p = std::strtok(line, " \t\r\n"); p; p = std::strtok(nullptr, " \t\r\n"))
            t.items.emplace_back(p);
        if (t.items.empty() || t.items[0][0] == '#')
            continue;
        const std::string& op = t.items[0];
        if (op == "model") {
            model = Load(argv[1], t.Word());
            continue;
        }
        if (model.record == nullptr)
            Fail("no model before " + op);
        mdl::ModelRecord& state = *mdl::Mdl(model.record);
        if (op == "qdef") {
            while (t.next < t.items.size()) {
                const long v = t.Int();
                if (!model.pmx || v < 0 || v >= static_cast<long>(state.vertexCount))
                    Fail("bad qdef vertex");
                state.pmxVertices[v].weightType = mdl::PmxWeightType::qdef;
            }
        } else if (op == "case") {
            std::printf("case %s\n", t.Word().c_str());
            for (std::uint32_t i = 0; i < state.morphCount; ++i)
                state.morphs[i].value = 0.0f;
            for (std::uint32_t i = 0; i < state.boneCount; ++i)
                std::memcpy(state.boneTable[i].matInit, kIdentity, sizeof kIdentity);
            std::memcpy(world, kIdentity, sizeof kIdentity);
        } else if (op == "world") {
            t.Floats(world, 16);
        } else if (op == "camera") {
            t.Floats(app.state.cameraPosition, 3);
            app.state.cameraFov = t.Float();
        } else if (op == "edge") {
            state.edgeScale = t.Float();
        } else if (op == "shadow") {
            app.state.selfShadowEnabled = static_cast<unsigned char>(t.Int());
        } else if (op == "morph") {
            const long i = t.Int();
            if (i < 0 || i >= static_cast<long>(state.morphCount))
                Fail("bad morph index");
            state.morphs[i].value = t.Float();
        } else if (op == "bone") {
            const long i = t.Int();
            if (i < 0 || i >= static_cast<long>(state.boneCount))
                Fail("bad bone index");
            t.Floats(state.boneTable[i].matInit, 16);
        } else if (op == "end") {
            ModelApplyMorphs(model.record);
            UpdateModelVertexBuffers(&app, model.record, world);
            Print(model);
        } else {
            Fail("unknown line " + op);
        }
    }
    std::fclose(in);
    return 0;
}
