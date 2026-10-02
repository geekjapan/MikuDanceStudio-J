#include "mikudancestudio/scene_resources.hpp"
#include <algorithm>
#include <fstream>
#include <iterator>
#include <utility>

namespace mikudancestudio::format {
namespace {
int Read(void* context, void* destination, std::size_t length) {
    return static_cast<int>(static_cast<std::istream*>(context)->read(
        static_cast<char*>(destination), static_cast<std::streamsize>(length))
        .gcount());
}
std::string RawPath(const std::array<char, 256>& path) {
    const auto end = std::find(path.begin(), path.end(), '\0');
    return {path.begin(), end};
}
std::optional<std::filesystem::path> AsciiPath(const std::string& raw) {
    if (std::any_of(raw.begin(), raw.end(), [](unsigned char ch) {
            return ch < 32 || ch >= 127;
        })) return std::nullopt;
    return std::filesystem::u8path(raw);
}
}
SceneResourceResolver::SceneResourceResolver(std::filesystem::path scenePath)
    : scenePath_(std::move(scenePath)), decoder_(AsciiPath) {}
void SceneResourceResolver::AddSearchRoot(std::filesystem::path root) {
    roots_.push_back(std::move(root));
}
void SceneResourceResolver::SetPathDecoder(DecodePath decoder) {
    decoder_ = std::move(decoder);
}
void SceneResourceResolver::ReselectModel(std::uint8_t slot,
                                          std::filesystem::path path) {
    selections_[slot] = std::move(path);
}
bool SceneResourceResolver::ResolveModel(
        std::uint8_t slot, const std::array<char, 256>& path,
        ModelDocument& model) {
    std::vector<std::filesystem::path> candidates;
    const auto override = selections_.find(slot);
    if (override != selections_.end()) {
        candidates.push_back(override->second);
    } else if (decoder_) {
        const auto decoded = decoder_(RawPath(path));
        if (decoded && !decoded->empty()) {
            if (decoded->is_absolute()) candidates.push_back(*decoded);
            else {
                candidates.push_back(scenePath_.parent_path() / *decoded);
                for (const auto& root : roots_)
                    candidates.push_back(root / *decoded);
            }
        }
    }
    for (const auto& candidate : candidates) {
        std::ifstream file(candidate, std::ios::binary);
        ModelDocument parsed;
        if (file && ReadModelDocument(Read, &file, parsed) &&
            parsed.kind != ModelKind::Unknown) {
            resolved_[slot] = candidate.lexically_normal();
            model = std::move(parsed);
            return true;
        }
    }
    missing_.push_back({{slot, path}, std::move(candidates)});
    return false;
}
bool SceneResourceResolver::Resolve(void* context, std::uint8_t slot,
                                    const std::array<char, 256>& path,
                                    ModelDocument& model) {
    return static_cast<SceneResourceResolver*>(context)->ResolveModel(
        slot, path, model);
}
}
