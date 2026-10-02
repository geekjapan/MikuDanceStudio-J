#include "mikudancestudio/render_snapshot.hpp"
#include "mikudancestudio/scene_resources.hpp"
#include <filesystem>
#include <fstream>

namespace {
int Read(void* context, void* data, std::size_t size) {
    auto& stream = *static_cast<std::istream*>(context);
    stream.read(static_cast<char*>(data), static_cast<std::streamsize>(size));
    return static_cast<int>(stream.gcount());
}
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const auto directory = std::filesystem::u8path(argv[1]);
    const auto path = directory / "scene.pmm";
    std::ifstream stream(path, std::ios::binary);
    mikudancestudio::format::SceneResourceResolver resources(path);
    resources.ReselectModel(1, directory / "assets/recovered.pmd");
    mikudancestudio::format::SceneSession session;
    if (!stream || !mikudancestudio::format::SceneSession::Load(
            Read, &stream,
            mikudancestudio::format::SceneResourceResolver::Resolve,
            &resources, session)) return 3;
    mikudancestudio::render::SceneSnapshot snapshot;
    if (!mikudancestudio::render::CaptureSceneSnapshot(session, snapshot) ||
        snapshot.models.size() != 1 || snapshot.models[0].slot != 1 ||
        snapshot.models[0].vertexCount != 1 ||
        snapshot.models[0].indexCount != 3 ||
        snapshot.models[0].batches.size() != 1 ||
        snapshot.models[0].batches[0].firstIndex != 0 ||
        snapshot.models[0].batches[0].indexCount != 3 ||
        snapshot.models[0].bones.size() != 1) return 4;
    if (!session.Seek(4) ||
        !mikudancestudio::render::CaptureSceneSnapshot(session, snapshot) ||
        snapshot.frame != 4 || snapshot.models[0].indexCount != 3)
        return 5;
    return 0;
}
