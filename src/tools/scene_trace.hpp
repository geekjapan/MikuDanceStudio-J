#pragma once
#include "mikudancestudio/pmm_scene_evaluation.hpp"
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <ostream>

namespace mikudancestudio::tools {
// Trace format 1 ("L1" = the portable C++ evaluator, EvaluatePmmSceneFrame).
// Text, LF line endings, fields separated by single spaces.
//
//   trace  := header block*
//   header := "mds-trace 1 L1" LF
//   block  := one frame; frames 0..N-1 in order. Every line starts with the
//             frame number. Lines of a block, in this fixed order:
//             for each model in document order: all bones, then all morphs;
//             then camera, then light
//   bone   := frame "bone" slot index tx ty tz rx ry rz rw LF
//   morph  := frame "morph" slot index weight LF
//   camera := frame "camera" px py pz rx ry rz distance fov LF
//   light  := frame "light" r g b dx dy dz LF
//   frame, slot, index := unsigned decimal; index is the bone/morph index
//   float  := C99 hex float, printf("%a") of the float widened to double
//             (for example 0x1.8p+1); always finite, nan/inf is an error
//
// A track is (kind, slot, index) and a field is a column. Bone rotation is
// the stored PMM key order (x y z w). Accessories, gravity, self-shadow,
// display, and IK state are not traced.
inline bool TraceFloat(std::ostream& out, float value) {
    if (!std::isfinite(value)) return false;
    char text[40];
    std::snprintf(text, sizeof text, " %a", static_cast<double>(value));
    out << text;
    return true;
}
template<std::size_t N>
bool TraceFloats(std::ostream& out, const std::array<float, N>& values) {
    for (const float value : values)
        if (!TraceFloat(out, value)) return false;
    return true;
}
// Returns false if a frame fails to evaluate, a value is not finite, or the
// stream fails. The caller discards the output in that case.
inline bool WriteSceneTrace(std::ostream& out,
                            const format::PmmSceneDocument& scene,
                            std::uint32_t frames) {
    out << "mds-trace 1 L1\n";
    format::PmmSceneEvaluation pose;
    for (std::uint32_t frame = 0; frame < frames; ++frame) {
        if (!format::EvaluatePmmSceneFrame(scene, frame, pose)) return false;
        for (const auto& model : pose.models) {
            for (std::size_t i = 0; i < model.bones.size(); ++i) {
                out << frame << " bone " << unsigned(model.slot) << ' ' << i;
                if (!TraceFloats(out, model.bones[i].translation) ||
                    !TraceFloats(out, model.bones[i].rotation)) return false;
                out << '\n';
            }
            for (std::size_t i = 0; i < model.morphValues.size(); ++i) {
                out << frame << " morph " << unsigned(model.slot) << ' ' << i;
                if (!TraceFloat(out, model.morphValues[i])) return false;
                out << '\n';
            }
        }
        out << frame << " camera";
        if (!TraceFloats(out, pose.camera.position) ||
            !TraceFloats(out, pose.camera.rotation) ||
            !TraceFloat(out, pose.camera.distance) ||
            !TraceFloat(out, pose.camera.fov)) return false;
        out << '\n' << frame << " light";
        if (!TraceFloats(out, pose.lightState)) return false;
        out << '\n';
    }
    return out.good();
}
}
