#pragma once
#include "mikudancestudio/scene_session.hpp"
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace mikudancestudio::format {
struct SceneModelReference {
    std::uint8_t slot = 0;
    std::array<char, 256> rawPath{};
};
struct MissingSceneModel {
    SceneModelReference reference;
    std::vector<std::filesystem::path> tried;
};

class SceneResourceResolver {
public:
    using DecodePath = std::function<std::optional<std::filesystem::path>(
        const std::string&)>;
    explicit SceneResourceResolver(std::filesystem::path scenePath);
    void AddSearchRoot(std::filesystem::path root);
    void SetPathDecoder(DecodePath decoder);
    void ReselectModel(std::uint8_t slot, std::filesystem::path path);
    bool ResolveModel(std::uint8_t slot, const std::array<char, 256>& path,
                      ModelDocument& model);
    static bool Resolve(void* context, std::uint8_t slot,
                        const std::array<char, 256>& path,
                        ModelDocument& model);
    const std::vector<MissingSceneModel>& Missing() const { return missing_; }
    const std::map<std::uint8_t, std::filesystem::path>& Resolved() const {
        return resolved_;
    }
private:
    std::filesystem::path scenePath_;
    std::vector<std::filesystem::path> roots_;
    DecodePath decoder_;
    std::map<std::uint8_t, std::filesystem::path> selections_;
    std::map<std::uint8_t, std::filesystem::path> resolved_;
    std::vector<MissingSceneModel> missing_;
};
}
