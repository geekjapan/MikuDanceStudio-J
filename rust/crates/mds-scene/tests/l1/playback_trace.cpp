// Fractional-frame L1 trace driver for RM-6 lanes 7 and 9.
// mds_scene_cli --trace evaluates integer frames only (EvaluatePmmSceneFrame).
// This driver calls the C++ playback evaluator (StartPmmScenePlayback and
// AdvancePmmScenePlayback), which takes float cursor seconds and a fractional
// frame, and writes the pose in trace format 1 exactly as scene_trace.hpp does.
//
// usage: playback_trace <pmm> out.trace (--seconds s[,s...] | --half-frames n)
#include "mikudancestudio/pmm_scene_evaluation.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace mikudancestudio::format;

static int Read(void* opaque, void* output, std::size_t size) {
    auto& stream = *static_cast<std::istream*>(opaque);
    stream.read(static_cast<char*>(output), static_cast<std::streamsize>(size));
    return static_cast<int>(stream.gcount());
}
static bool Float(std::ostream& out, float value) {
    if (!std::isfinite(value)) return false;
    char text[40];
    std::snprintf(text, sizeof text, " %a", static_cast<double>(value));
    out << text;
    return true;
}
template<std::size_t N>
static bool Floats(std::ostream& out, const std::array<float, N>& v) {
    for (float x : v) if (!Float(out, x)) return false;
    return true;
}
static bool WritePose(std::ostream& out, unsigned label, const PmmSceneEvaluation& pose) {
    for (const auto& model : pose.models) {
        for (std::size_t i = 0; i < model.bones.size(); ++i) {
            out << label << " bone " << unsigned(model.slot) << ' ' << i;
            if (!Floats(out, model.bones[i].translation) ||
                !Floats(out, model.bones[i].rotation)) return false;
            out << '\n';
        }
        for (std::size_t i = 0; i < model.morphValues.size(); ++i) {
            out << label << " morph " << unsigned(model.slot) << ' ' << i;
            if (!Float(out, model.morphValues[i])) return false;
            out << '\n';
        }
    }
    out << label << " camera";
    if (!Floats(out, pose.camera.position) || !Floats(out, pose.camera.rotation) ||
        !Float(out, pose.camera.distance) || !Float(out, pose.camera.fov)) return false;
    out << '\n' << label << " light";
    if (!Floats(out, pose.lightState)) return false;
    out << '\n';
    return true;
}

int main(int argc, char** argv) {
    if (argc != 5) { std::cerr << "usage\n"; return 2; }
    std::vector<float> seconds;
    const std::string mode = argv[3];
    if (mode == "--seconds") {
        std::stringstream list(argv[4]);
        std::string item;
        while (std::getline(list, item, ',')) seconds.push_back(std::stof(item));
    } else if (mode == "--half-frames") {
        const unsigned n = static_cast<unsigned>(std::stoul(argv[4]));
        for (unsigned k = 0; k <= 2 * n; ++k)
            seconds.push_back(static_cast<float>(k) / 60.0f);
    } else { std::cerr << "usage\n"; return 2; }
    std::ifstream source(argv[1], std::ios::binary);
    PmmSceneDocument scene;
    if (!source || !ReadPmmSceneDocument(Read, &source, nullptr, nullptr, scene)) {
        std::cerr << "load failed\n";
        return 3;
    }
    PmmScenePlaybackState state;
    if (!StartPmmScenePlayback(scene, state)) { std::cerr << "start failed\n"; return 4; }
    std::ofstream out(argv[2], std::ios::binary);
    out << "mds-trace 1 L1\n";
    for (std::size_t k = 0; k < seconds.size(); ++k) {
        if (!AdvancePmmScenePlayback(scene, seconds[k], state)) {
            std::cerr << "advance failed at sample " << k << '\n';
            return 5;
        }
        if (!WritePose(out, static_cast<unsigned>(k), state.pose)) { std::cerr << "non-finite\n"; return 6; }
    }
    return out.good() ? 0 : 7;
}
