// Unit checks for the L1 trace writer (src/tools/scene_trace.hpp) and, when
// given `<mds_scene_cli> <fixture dir>`, for the --trace/--frames CLI options.
#include "scene_trace.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <sstream>
#include <string>
#include <vector>
#ifndef _WIN32
#include <sys/wait.h>
#endif

using namespace mikudancestudio::format;
namespace fs = std::filesystem;
namespace {
void CheckAt(bool value, int line) {
    if (!value) {
        std::fprintf(stderr, "check failed at line %d\n", line);
        std::abort();
    }
}
#define Check(value) CheckAt((value), __LINE__)

PmmSceneDocument Fixture() {
    PmmSceneDocument scene;
    PmmCameraKey camera;
    camera.fov = 45;
    camera.distance = 12.5f;
    camera.eye = {1.0f, 2.0f, 3.0f};
    camera.target = {0.25f, 0.5f, 0.75f};
    scene.cameraKeys.dense.push_back(camera);
    PmmLightKey light0, light10;
    light0.next = 7;
    light0.color = {0.2f, 0.4f, 0.6f};
    light0.direction = {0.0f, -1.0f, 0.0f};
    light10.frame = 10;
    light10.previous = 0;
    light10.color = {0.8f, 0.6f, 0.4f};
    light10.direction = {1.0f, 0.0f, 0.0f};
    scene.lightKeys.dense.push_back(light0);
    scene.lightKeys.sparse.push_back({7, 0, light10});
    PmmSceneModel model;
    model.slot = 3;
    model.layout.boneCount = 1;
    model.layout.morphCount = 1;
    model.layout.ikCount = 1;
    model.rigidCount = 1;
    model.rigidSources = {-1};
    PmmBoneKey bone0, bone10;
    bone0.next = 4;
    bone0.position = {0.5f, -1.5f, 2.25f};
    bone0.rotation = {0.0f, 0.0f, 0.0f, 1.0f};
    bone10.frame = 10;
    bone10.previous = 0;
    bone10.position = {10.5f, -1.5f, 2.25f};
    bone10.rotation = {0.0f, 0.0f, 0.70710677f, 0.70710677f};
    model.boneKeys.dense.push_back(bone0);
    model.boneKeys.sparse.push_back({4, 0, bone10});
    PmmMorphKey morph0, morph10;
    morph0.next = 5;
    morph10.frame = 10;
    morph10.previous = 0;
    morph10.value = 1.0f;
    model.morphKeys.dense.push_back(morph0);
    model.morphKeys.sparse.push_back({5, 0, morph10});
    PmmDisplayKey display0;
    display0.visible = 1;
    display0.ikEnabled = {0};
    display0.rigidStates = {{2, 3}};
    model.displayKeys.dense.push_back(display0);
    scene.models.push_back(std::move(model));
    return scene;
}
std::string Trace(const PmmSceneDocument& scene, std::uint32_t frames,
                  bool expected = true) {
    std::ostringstream out;
    Check(mikudancestudio::tools::WriteSceneTrace(out, scene, frames) ==
          expected);
    return out.str();
}
std::vector<std::string> Lines(const std::string& text) {
    std::vector<std::string> lines;
    std::istringstream in(text);
    for (std::string line; std::getline(in, line);) lines.push_back(line);
    return lines;
}
// Fields of a trace line after the name columns, as floats (bit-exact parse
// of the hex floats).
std::vector<float> Floats(const std::string& line, std::size_t skip) {
    std::istringstream in(line);
    std::string word;
    std::vector<float> values;
    for (std::size_t i = 0; in >> word; ++i)
        if (i >= skip) values.push_back(static_cast<float>(
            std::strtod(word.c_str(), nullptr)));
    return values;
}
void CheckWriter() {
    const auto scene = Fixture();
    const auto first = Trace(scene, 12);
    Check(first == Trace(scene, 12));
    const auto lines = Lines(first);
    // header + 12 frames x (1 bone + 1 morph + camera + light)
    Check(lines.size() == 1 + 12 * 4 && lines[0] == "mds-trace 1 L1");
    Check(lines[1].rfind("0 bone 3 0 ", 0) == 0 &&
          lines[2].rfind("0 morph 3 0 ", 0) == 0 &&
          lines[3].rfind("0 camera ", 0) == 0 &&
          lines[4].rfind("0 light ", 0) == 0 &&
          lines[5].rfind("1 bone 3 0 ", 0) == 0);
    // Frame 0 equals key 0 bit for bit.
    const auto& bone = scene.models[0].boneKeys.dense[0];
    const auto bone0 = Floats(lines[1], 4);
    Check(bone0.size() == 7 && bone0[0] == bone.position[0] &&
          bone0[1] == bone.position[1] && bone0[2] == bone.position[2] &&
          bone0[3] == bone.rotation[0] && bone0[6] == bone.rotation[3]);
    Check(Floats(lines[2], 4) == std::vector<float>{0.0f});
    const auto& camera = scene.cameraKeys.dense[0];
    const auto camera0 = Floats(lines[3], 2);
    Check(camera0.size() == 8 && camera0[6] == camera.distance &&
          camera0[7] == 45.0f);
    const auto& light = scene.lightKeys.dense[0];
    Check(Floats(lines[4], 2) ==
          (std::vector<float>{light.color[0], light.color[1], light.color[2],
                              light.direction[0], light.direction[1],
                              light.direction[2]}));
    // Linear midpoint, computed by hand: 0.5 + (10.5 - 0.5) * 5 / 10.
    const auto mid = Floats(lines[1 + 5 * 4], 4);
    Check(mid[0] == 5.5f && mid[1] == -1.5f);
    Check(Floats(lines[2 + 5 * 4], 4) == std::vector<float>{0.5f});
    // After the last key the values hold.
    const auto last = Floats(lines[1 + 10 * 4], 4);
    Check(last[0] == 10.5f && Floats(lines[1 + 11 * 4], 4) == last);
    // Non-finite values are an error, not a trace.
    auto bad = scene;
    bad.models[0].morphKeys.sparse[0].value.value =
        std::numeric_limits<float>::quiet_NaN();
    Trace(bad, 12, false);
}

int Run(const std::string& command) {
    const int raw = std::system(command.c_str());
#ifdef _WIN32
    return raw;
#else
    return WIFEXITED(raw) ? WEXITSTATUS(raw) : -1;
#endif
}
std::string Quote(const fs::path& path) { return "\"" + path.string() + "\""; }
std::string Slurp(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(in), {}};
}
void CheckCli(const fs::path& cli, const fs::path& fixture) {
    const auto scene = fixture / "scene.pmm";
    const auto model = fixture / "assets" / "recovered.pmd";
    const auto work = fixture / "trace_cli";
    std::error_code error;
    fs::remove_all(work, error);
    fs::create_directories(work);
    const auto base = Quote(cli) + " " + Quote(scene);
    const auto reselect = " --reselect 1 " + Quote(model);
    const auto quiet = " 2>" + std::string(
#ifdef _WIN32
        "nul"
#else
        "/dev/null"
#endif
        );
    for (const char* name : {"a", "b"})
        Check(Run(base + " " + Quote(work / (std::string(name) + ".pmm")) +
                  reselect + " --trace " + Quote(work / (std::string(name) + ".trace")) +
                  " --frames 4 >" + Quote(work / "stdout")) == 0);
    const auto a = Slurp(work / "a.trace");
    Check(Lines(a).size() == 1 + 4 * 4 && Lines(a)[0] == "mds-trace 1 L1");
    Check(a == Slurp(work / "b.trace"));
    // Trace mode only evaluates: it writes no output scene.
    Check(!fs::exists(work / "a.pmm") && !fs::exists(work / "b.pmm"));
    // Bad --frames: exit 2, no trace file.
    for (const char* frames : {"-1", "abc", ""}) {
        Check(Run(base + " " + Quote(work / "c.pmm") + reselect + " --trace " +
                  Quote(work / "c.trace") + " --frames \"" + frames + "\"" +
                  quiet) == 2);
        Check(!fs::exists(work / "c.trace") && !fs::exists(work / "c.pmm"));
    }
    // --trace and --frames come as a pair.
    Check(Run(base + " " + Quote(work / "c.pmm") + reselect + " --trace " +
              Quote(work / "c.trace") + quiet) == 2);
    Check(!fs::exists(work / "c.trace"));
    // Model that cannot load: non-zero, no trace file.
    Check(Run(base + " " + Quote(work / "d.pmm") + " --trace " +
              Quote(work / "d.trace") + " --frames 4" + quiet) != 0);
    Check(!fs::exists(work / "d.trace") && !fs::exists(work / "d.trace.tmp"));
    fs::remove_all(work, error);
}
}
int main(int argc, char** argv) {
    CheckWriter();
    if (argc == 3) CheckCli(argv[1], argv[2]);
    else if (argc != 1) return 2;
    return 0;
}
