#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <ostream>

namespace mikudancestudio::tools::l2 {
// Trace format 1 ("L2" = the Windows x64 app, real D3DX and Bullet 2.75).
// Same header form and conventions as the L1 trace of src/tools/scene_trace.hpp
// (text, LF line endings, fields separated by single spaces); L2 keeps the L1
// "bone" and "morph" lines field for field and adds "bonew" and "rigid".
//
//   trace  := header block*
//   header := "mds-trace 1 L2" LF
//   block  := one frame; frames 0..N-1 in order. Every line starts with the
//             frame number. Lines of a block, in this fixed order:
//             for each loaded model in ascending slot order:
//               all bones (bone index order), then all bonew in the same
//               order, then all morphs, then all rigid bodies
//   bone   := frame "bone" slot index tx ty tz rx ry rz rw LF
//   bonew  := frame "bonew" slot index m00 m01 m02 m03 m10 .. m33 LF
//   morph  := frame "morph" slot index weight LF
//   rigid  := frame "rigid" slot index px py pz qx qy qz qw LF
//   frame, slot, index := unsigned decimal; index is the bone, morph, or
//             rigid body index in the model's own table order
//   float  := hex float "[-]0x1.hhhhhhp[+-]d", exactly 6 hex digits, written
//             by FormatHexFloat below (not by printf, because CRTs differ in
//             the digit count of %a); or "[-]0x0.000000p+0" for zero. The
//             value is the float widened to double; nan/inf is an error
//
// A track is (kind, slot, index) and a field is a column. Meaning of the
// fields, from the x64 model record layout:
//   bone   the pose after key interpolation, BoneRecord::trans (tx ty tz)
//          and BoneRecord::rotQuat (rx ry rz rw, stored key order x y z w).
//          This is the quantity the L1 "bone" line carries, so lane 5 of
//          RM-3 compares the two traces on this kind and on "morph".
//   bonew  the bone's world matrix after the full bone update (append
//          transforms, IK, physics follow), BoneRecord::matInit, the matrix
//          the skinning code reads. The 16 floats are in D3DXMATRIXF memory
//          order, m[row][col] row by row (row-vector convention, translation
//          in m30 m31 m32).
//   morph  MorphRecord::value, the morph weight after key interpolation and
//          group morph application.
//   rigid  the Bullet rigid body world transform: origin (px py pz) and the
//          rotation of the basis as a quaternion (qx qy qz qw).
// Camera, light, accessories, gravity, and display state are not traced.
//
// Frame numbering. Frame 0 is the model state right after the PMM loaded, the
// models were seeked to timeline frame 0, and one bone-and-morph pass ran,
// before any physics step. Frame f (f >= 1) is the state after f frame-step
// passes of the app (PlaybackCatchup then PhysicsFrame at 30 fps): timeline
// time f / 30 s. Each pass runs one or two 1/60 s catch-up ticks, depending
// on float accumulation of the playback cursor, plus the settle step of the
// remaining time budget; the count is deterministic for a given input.

// Hex float of a widened float, without printf. Writes at most 20 bytes
// including the terminating NUL; returns the length, or 0 for nan and inf.
inline std::size_t FormatHexFloat(float value, char out[20]) {
    std::uint32_t bits;
    std::memcpy(&bits, &value, sizeof bits);
    const std::uint32_t biased = (bits >> 23) & 0xFFu;
    std::uint32_t mantissa = bits & 0x7FFFFFu;
    if (biased == 0xFFu) return 0;
    int exponent = 0;
    if (biased != 0) {
        exponent = static_cast<int>(biased) - 127;
    } else if (mantissa != 0) {  // float subnormal: normal as a double
        exponent = -126;
        while ((mantissa & 0x800000u) == 0) {
            mantissa <<= 1;
            --exponent;
        }
        mantissa &= 0x7FFFFFu;
    }
    const bool isZero = biased == 0 && (bits & 0x7FFFFFu) == 0;
    const std::uint32_t digits = mantissa << 1;  // 23 bits -> 24 bits -> 6 hex digits
    std::size_t n = 0;
    if ((bits >> 31) != 0) out[n++] = '-';
    out[n++] = '0';
    out[n++] = 'x';
    out[n++] = isZero ? '0' : '1';
    out[n++] = '.';
    for (int shift = 20; shift >= 0; shift -= 4)
        out[n++] = "0123456789abcdef"[(digits >> shift) & 0xFu];
    out[n++] = 'p';
    out[n++] = exponent < 0 ? '-' : '+';
    const unsigned magnitude = static_cast<unsigned>(exponent < 0 ? -exponent : exponent);
    if (magnitude >= 100) out[n++] = static_cast<char>('0' + magnitude / 100);
    if (magnitude >= 10) out[n++] = static_cast<char>('0' + magnitude / 10 % 10);
    out[n++] = static_cast<char>('0' + magnitude % 10);
    out[n] = '\0';
    return n;
}

inline bool WriteFloat(std::ostream& out, float value) {
    char text[20];
    if (FormatHexFloat(value, text) == 0) return false;
    out << ' ' << text;
    return true;
}

inline bool WriteFloats(std::ostream& out, const float* values, std::size_t count) {
    for (std::size_t i = 0; i < count; ++i)
        if (!WriteFloat(out, values[i])) return false;
    return true;
}

inline void WriteHeader(std::ostream& out) { out << "mds-trace 1 L2\n"; }

// Each Write*Line returns false when a value is not finite (the caller then
// discards the whole trace); the line is then incomplete.
inline bool WriteBoneLine(std::ostream& out, std::uint32_t frame, unsigned slot,
                          std::size_t index, const float translation[3],
                          const float rotation[4]) {
    out << frame << " bone " << slot << ' ' << index;
    if (!WriteFloats(out, translation, 3) || !WriteFloats(out, rotation, 4)) return false;
    out << '\n';
    return true;
}

inline bool WriteBoneWorldLine(std::ostream& out, std::uint32_t frame, unsigned slot,
                               std::size_t index, const float matrix[16]) {
    out << frame << " bonew " << slot << ' ' << index;
    if (!WriteFloats(out, matrix, 16)) return false;
    out << '\n';
    return true;
}

inline bool WriteMorphLine(std::ostream& out, std::uint32_t frame, unsigned slot,
                           std::size_t index, float weight) {
    out << frame << " morph " << slot << ' ' << index;
    if (!WriteFloat(out, weight)) return false;
    out << '\n';
    return true;
}

inline bool WriteRigidLine(std::ostream& out, std::uint32_t frame, unsigned slot,
                           std::size_t index, const float position[3],
                           const float rotation[4]) {
    out << frame << " rigid " << slot << ' ' << index;
    if (!WriteFloats(out, position, 3) || !WriteFloats(out, rotation, 4)) return false;
    out << '\n';
    return true;
}
}  // namespace mikudancestudio::tools::l2
