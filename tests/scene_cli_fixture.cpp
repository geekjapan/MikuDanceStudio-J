#include "mikudancestudio/pmm_scene_document.hpp"
#include "mikudancestudio/scene_resources.hpp"
#include "model_reader_fixture.hpp"
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {
struct Bytes {
    std::vector<std::uint8_t> data;
    void byte(std::uint8_t value) { data.push_back(value); }
    void word(std::uint32_t value) {
        for (int shift = 0; shift < 32; shift += 8) byte(value >> shift);
    }
    void zero(std::size_t count) { data.insert(data.end(), count, 0); }
};
int Read(void* context, void* destination, std::size_t length) {
    auto& stream = *static_cast<std::istream*>(context);
    stream.read(static_cast<char*>(destination),
                static_cast<std::streamsize>(length));
    return static_cast<int>(stream.gcount());
}
Bytes Scene() {
    Bytes bytes;
    bytes.zero(30);
    std::memcpy(bytes.data.data(), "Polygon Movie maker", 19);
    std::memcpy(bytes.data.data() + 20, "0002", 5);
    bytes.word(640); bytes.word(480); bytes.word(200); bytes.word(0x42340000);
    bytes.zero(7);
    bytes.byte(1); bytes.byte(1);
    bytes.byte(1); bytes.byte(1); bytes.byte('M');
    bytes.byte(1); bytes.byte('M');
    const auto path = bytes.data.size();
    bytes.zero(256);
    std::memcpy(bytes.data.data() + path, "lost.pmd", 8);
    bytes.byte(1);
    bytes.word(1); bytes.byte(1); bytes.byte('B');
    bytes.word(1); bytes.byte(1); bytes.byte('F');
    bytes.word(1); bytes.word(0);
    bytes.word(1); bytes.word(0);
    bytes.byte(1); bytes.byte(1); bytes.word(0);
    for (int index = 0; index < 4; ++index) bytes.word(0);
    bytes.byte(0); bytes.byte(1); bytes.word(0); bytes.word(100);
    bytes.zero(58); bytes.word(0);
    bytes.zero(17); bytes.word(0);
    bytes.zero(23); bytes.word(0);
    bytes.zero(31); bytes.word(0); bytes.byte(1); bytes.zero(16);
    bytes.byte(0); bytes.word(0x3f800000); bytes.byte(0); bytes.byte(1);
    bytes.zero(78); bytes.word(0);
    bytes.zero(37);
    bytes.zero(37); bytes.word(0);
    bytes.zero(24);
    bytes.byte(0); bytes.word(0); bytes.byte(0);
    bytes.zero(28);
    bytes.zero(257);
    bytes.zero(272);
    bytes.zero(269);
    bytes.zero(11);
    bytes.zero(31);
    bytes.zero(34); bytes.word(0);
    bytes.byte(0); bytes.word(0);
    bytes.zero(18); bytes.word(0);
    bytes.zero(92);
    bytes.byte(1); bytes.byte(1); bytes.word(5);
    return bytes;
}
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const auto directory = std::filesystem::u8path(argv[1]);
    const auto assets = directory / "assets";
    std::error_code error;
    std::filesystem::create_directories(assets, error);
    if (error) return 3;
    const auto pmd = model_reader_fixture::Pmd(false, false);
    std::ofstream model(assets / "recovered.pmd", std::ios::binary);
    model.write(reinterpret_cast<const char*>(pmd.data.data()),
                static_cast<std::streamsize>(pmd.data.size()));
    model.close();
    const auto scene = Scene();
    std::ofstream file(directory / "scene.pmm", std::ios::binary);
    file.write(reinterpret_cast<const char*>(scene.data.data()),
               static_cast<std::streamsize>(scene.data.size()));
    file.close();
    std::ifstream check(directory / "scene.pmm", std::ios::binary);
    mikudancestudio::format::PmmSceneDocument parsed;
    if (!check || !mikudancestudio::format::ReadPmmSceneDocument(
            Read, &check, nullptr, nullptr, parsed) ||
        parsed.models.size() != 1 || parsed.models[0].slot != 1 ||
        parsed.models[0].layout.boneCount != 1 ||
        parsed.models[0].layout.morphCount != 1 ||
        parsed.models[0].layout.ikCount != 1) return 4;
    mikudancestudio::format::SceneResourceResolver resources(
        directory / "scene.pmm");
    mikudancestudio::format::ModelDocument resolved;
    const auto& reference = parsed.models[0].path;
    if (resources.ResolveModel(1, reference, resolved) ||
        resources.Missing().size() != 1 ||
        resources.Missing()[0].reference.rawPath != reference ||
        resources.Missing()[0].tried.size() != 1) return 5;
    resources.ReselectModel(1, assets / "recovered.pmd");
    if (!resources.ResolveModel(1, reference, resolved) ||
        resolved.kind != mikudancestudio::format::ModelKind::Pmd ||
        resources.Resolved().at(1) !=
            (assets / "recovered.pmd").lexically_normal()) return 6;
    mikudancestudio::format::SceneResourceResolver rooted(
        directory / "scene.pmm");
    rooted.AddSearchRoot(assets);
    std::array<char, 256> relative{};
    std::memcpy(relative.data(), "recovered.pmd", 13);
    if (!rooted.ResolveModel(1, relative, resolved) ||
        rooted.Resolved().at(1) !=
            (assets / "recovered.pmd").lexically_normal()) return 7;
    std::filesystem::remove(directory / "roundtrip.pmm", error);
    return 0;
}
